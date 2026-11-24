"""
IG → Threads auto cross-post bridge.

When an IG account posts, the linked Threads account should fire a reply
within a short window — that's the funnel path the whole Threads ship-first
decision hinges on. This module is the glue:

    IG executor / Content Agent → emit IGPostEvent
                                → IGEventBus fans out to subscribers
                                → ThreadsCrossPostBridge enqueues a reply
                                   from the linked Threads account
                                → Threads executor dispatches via mirror
                                → Funnel tracker records reply_posted

The bridge is budget-aware: if the linked Threads account has no reply
budget left today, it skips (not retries — the orchestrator picks it up
next day). It's also day-7 gated: fresh IG accounts can't trigger Threads
replies (would fast-track new-account detection).

The bus is deliberately in-memory + process-local. In production the same
surface fronts a Redis Stream so the IG side can publish without caring
whether the Threads subscriber is up.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from . import threads as threads_mod
from .threads_funnel import ThreadsFunnelTracker

log = logging.getLogger("phantom_fleet.platforms.ig_bridge")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@dataclass
class IGPostEvent:
    """An IG account published a post. The Threads side reacts."""
    ig_account_id: str
    post_id:       str                            # IG post id / shortcode
    caption:       str = ""
    source:        str = "manual"                 # "manual" | "executor" | "agent"
    ts:            str = ""

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()


Subscriber = Callable[[IGPostEvent], Awaitable[None]]


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


class IGEventBus:
    """
    Fan-out bus for IG events. Subscribers are async callables; the bus
    swallows individual subscriber errors so one bad handler never kills
    the dispatch chain. All events are kept in a ring for observability.
    """

    def __init__(self, ring_size: int = 500, repo=None):
        self._events: deque[IGPostEvent] = deque(maxlen=ring_size)
        self._subscribers: list[Subscriber] = []
        self._repo = repo

    def set_repo(self, repo) -> None:
        self._repo = repo

    def restore_events(self, rows: list[dict]) -> None:
        """Replay durable IG events into the in-memory ring on startup."""
        for r in reversed(rows):           # oldest first so ring order is right
            ev = IGPostEvent(
                ig_account_id=r["ig_account_id"], post_id=r["post_id"],
                caption=r.get("caption", ""), source=r.get("source", "manual"),
                ts=r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"]),
            )
            self._events.append(ev)
        log.info("IGEventBus: restored %d events", len(rows))

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    def recent(self, limit: int = 50) -> list[dict]:
        rows: list[dict] = []
        for ev in reversed(self._events):
            rows.append({
                "ig_account_id": ev.ig_account_id,
                "post_id":       ev.post_id,
                "caption":       ev.caption,
                "source":        ev.source,
                "ts":            ev.ts,
            })
            if len(rows) >= limit:
                break
        return rows

    async def publish(self, event: IGPostEvent) -> list[dict]:
        """
        Publish one event. Returns a per-subscriber outcome list so the
        caller can report what the bridge did without digging in logs.
        """
        self._events.append(event)
        if self._repo is not None:
            try:
                asyncio.create_task(self._repo.record_ig_event({
                    "ig_account_id": event.ig_account_id,
                    "post_id":       event.post_id,
                    "caption":       event.caption,
                    "source":        event.source,
                    "ts":            event.ts,
                }))
            except RuntimeError:
                pass
        outcomes: list[dict] = []
        for fn in self._subscribers:
            name = getattr(fn, "__name__", repr(fn))
            try:
                result = await fn(event)
                outcomes.append({"subscriber": name, "ok": True,
                                  "result": result})
            except Exception as exc:
                log.exception("IGEventBus subscriber %s failed", name)
                outcomes.append({"subscriber": name, "ok": False,
                                  "error": f"{type(exc).__name__}: {exc}"})
        return outcomes


# ---------------------------------------------------------------------------
# Cross-post bridge subscriber
# ---------------------------------------------------------------------------


# Reply templates seeded deterministically on post_id so audits replay.
_REPLY_HOOKS = (
    "needed to see this today",
    "running it back",
    "catch me stitching this in my next drop",
    "you GET it",
    "look at this and look at my bio",
    "this is the vibe check I needed",
    "already drafted my repost",
    "the way I felt that",
)


def _draw_reply(post_id: str) -> str:
    idx = int(hashlib.sha256(post_id.encode()).hexdigest()[:8], 16) % len(_REPLY_HOOKS)
    return _REPLY_HOOKS[idx]


@dataclass
class BridgeStats:
    events_in:    int = 0
    replies_out:  int = 0
    skipped_budget:   int = 0
    skipped_no_link:  int = 0
    skipped_gate:     int = 0
    last_action_id:   Optional[str] = None


class ThreadsCrossPostBridge:
    """
    Subscribes to IGEventBus. For each IGPostEvent, finds the linked
    Threads account and enqueues a reply targeting the IG post.

    Checks, in order:
      1. Is there a Threads account linked to this IG account? (else skip)
      2. Has the IG parent passed day 7 of warming? (else skip — same guard
         as a hand-fired cross-post)
      3. Does the Threads account have reply budget left today? (else skip)

    No retries. The orchestrator will pick up on the next tick if the
    account is worth replying from.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        queue_getter:          Callable[[], list[dict]],
        funnel:                Optional[ThreadsFunnelTracker] = None,
    ):
        self._accounts_getter = accounts_store_getter
        self._queue_getter    = queue_getter
        self.funnel           = funnel
        self.stats            = BridgeStats()

    async def __call__(self, event: IGPostEvent) -> dict:
        self.stats.events_in += 1
        store = self._accounts_getter()

        ig = store.get(event.ig_account_id)
        if ig is None or ig.get("platform") != "instagram":
            self.stats.skipped_no_link += 1
            return {"skipped": "ig_not_found"}

        if not threads_mod.can_cross_post(ig):
            self.stats.skipped_gate += 1
            return {"skipped": "ig_below_day_7",
                    "ig_warmup_day": int(ig.get("warmup_day", 0))}

        th = next((r for r in store.values()
                   if r.get("platform") == "threads"
                   and r.get("ig_account_id") == event.ig_account_id), None)
        if th is None:
            self.stats.skipped_no_link += 1
            return {"skipped": "no_threads_link"}

        remaining = self._reply_budget_remaining(th)
        if remaining <= 0:
            self.stats.skipped_budget += 1
            return {"skipped": "no_reply_budget",
                    "threads_account_id": th["account_id"]}

        action_id = f"th-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        self._queue_getter().append({
            "action_id":  action_id,
            "account_id": th["account_id"],
            "kind":       "reply",
            "target":     f"ig://{event.ig_account_id}/{event.post_id}",
            "body":       _draw_reply(event.post_id),
            "route":      threads_mod.ACTION_ROUTES["reply"],
            "date":       now.date().isoformat(),
            "queued_at":  now.isoformat(),
            "status":     "queued",
            "planner":    "ig_bridge",
            "ig_source_post": event.post_id,
            "reason":     f"IG cross-post from {event.ig_account_id}",
        })
        self.stats.replies_out += 1
        self.stats.last_action_id = action_id
        return {
            "queued": True,
            "action_id": action_id,
            "threads_account_id": th["account_id"],
        }

    def _reply_budget_remaining(self, th: dict) -> int:
        budget = threads_mod.budget_for(th["account_id"],
                                         int(th.get("warmup_day", 1)))
        today = datetime.now(timezone.utc).date().isoformat()
        used = 0
        for e in self._queue_getter():
            if (e.get("account_id") == th["account_id"]
                    and e.get("kind") == "reply"
                    and e.get("date") == today):
                used += 1
        return max(0, budget.reply - used)
