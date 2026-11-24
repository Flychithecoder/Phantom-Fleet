"""
Threads funnel tracker — measures reply → profile view → bio link click →
subscribe conversion per linked Threads account.

Why this matters: the whole case for shipping Threads before Reddit/TikTok
is "IG posts drive Threads replies, Threads replies drive bio-link clicks,
bio-link clicks drive OF subs." Without this tracker we can't tell whether
the cross-posting bridge is actually paying for itself.

Attribution chain:
    IG post → Threads reply (reply_posted event, emitted by executor)
           → user visits Threads replier's profile (profile_view event)
           → user taps the bio link (bio_link_click event)
           → user converts on the funnel landing (subscribe event)

Each event carries the threads_account_id. We roll up per-account and
cross-platform. The Funnel Conversion Agent (Phase 1/2 shared) consumes
the per-account rollup when it re-ranks persona/funnel pairs.

Storage: in-memory ring per account. In production this goes to Postgres
`threads_funnel_events` with the same schema; the API layer is identical.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

log = logging.getLogger("phantom_fleet.platforms.threads_funnel")

EventKind = Literal[
    "reply_posted",      # Emitted by the executor on dispatch success
    "post_posted",       # Original post (not a reply)
    "profile_view",      # Someone opened this account's profile
    "bio_link_click",    # They tapped the bio link
    "subscribe",         # The funnel landing page fired a subscribe
]

# Event kinds in funnel order — used to render the funnel visualization.
FUNNEL_ORDER: tuple[EventKind, ...] = (
    "reply_posted", "profile_view", "bio_link_click", "subscribe",
)


@dataclass
class FunnelEvent:
    kind:               EventKind
    threads_account_id: str
    ig_account_id:      Optional[str] = None
    action_id:          Optional[str] = None     # Links back to queue entry
    target:             str = ""                 # IG post handle or url
    meta:               dict = field(default_factory=dict)
    ts:                 str = ""                 # ISO8601 UTC

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()


@dataclass
class AccountFunnel:
    """Per-account funnel counters + the derived rates."""
    threads_account_id: str
    reply_posted:       int = 0
    post_posted:        int = 0
    profile_view:       int = 0
    bio_link_click:     int = 0
    subscribe:          int = 0

    def as_dict(self) -> dict:
        reply_to_view  = _safe_ratio(self.profile_view,   self.reply_posted)
        view_to_click  = _safe_ratio(self.bio_link_click, self.profile_view)
        click_to_sub   = _safe_ratio(self.subscribe,      self.bio_link_click)
        reply_to_sub   = _safe_ratio(self.subscribe,      self.reply_posted)
        return {
            "threads_account_id": self.threads_account_id,
            "counts": {
                "reply_posted":   self.reply_posted,
                "post_posted":    self.post_posted,
                "profile_view":   self.profile_view,
                "bio_link_click": self.bio_link_click,
                "subscribe":      self.subscribe,
            },
            "rates": {
                "reply_to_view":  reply_to_view,
                "view_to_click":  view_to_click,
                "click_to_sub":   click_to_sub,
                "reply_to_sub":   reply_to_sub,     # end-to-end
            },
        }


def _safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


class ThreadsFunnelTracker:
    """
    Single-process event sink for Threads funnel attribution.

    Keeps the last 2000 events in a deque for the activity feed and a per
    -account counter dict for fast summaries. The ring is bounded so a
    runaway cross-post loop can't exhaust memory.
    """

    def __init__(self, ring_size: int = 2000, repo: Any | None = None):
        self._events: deque[FunnelEvent] = deque(maxlen=ring_size)
        self._counters: dict[str, AccountFunnel] = {}
        self._repo = repo       # Optional ThreadsRepository for write-through

    def set_repo(self, repo: Any | None) -> None:
        self._repo = repo

    def restore_counters(self, snapshot: dict[str, dict[str, int]]) -> None:
        """Rehydrate per-account counters from DB after restart."""
        for acc, kinds in snapshot.items():
            c = AccountFunnel(threads_account_id=acc)
            c.reply_posted   = int(kinds.get("reply_posted", 0))
            c.post_posted    = int(kinds.get("post_posted", 0))
            c.profile_view   = int(kinds.get("profile_view", 0))
            c.bio_link_click = int(kinds.get("bio_link_click", 0))
            c.subscribe      = int(kinds.get("subscribe", 0))
            self._counters[acc] = c
        log.info("ThreadsFunnelTracker: restored %d accounts", len(snapshot))

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def record(self, event: FunnelEvent) -> AccountFunnel:
        self._events.append(event)
        counter = self._counters.setdefault(
            event.threads_account_id,
            AccountFunnel(threads_account_id=event.threads_account_id),
        )
        if event.kind == "reply_posted":
            counter.reply_posted += 1
        elif event.kind == "post_posted":
            counter.post_posted += 1
        elif event.kind == "profile_view":
            counter.profile_view += 1
        elif event.kind == "bio_link_click":
            counter.bio_link_click += 1
        elif event.kind == "subscribe":
            counter.subscribe += 1
        if self._repo is not None:
            try:
                asyncio.create_task(self._repo.record_funnel_event({
                    "kind":               event.kind,
                    "threads_account_id": event.threads_account_id,
                    "ig_account_id":      event.ig_account_id,
                    "action_id":          event.action_id,
                    "target":             event.target,
                    "meta":               event.meta,
                    "ts":                 event.ts,
                }))
            except RuntimeError:
                # No running loop (e.g. in sync tests) — DB write-through
                # is best-effort, in-memory is source of truth.
                pass
        return counter

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def recent(self, limit: int = 100,
               threads_account_id: Optional[str] = None) -> list[dict]:
        rows: list[dict] = []
        for ev in reversed(self._events):
            if threads_account_id and ev.threads_account_id != threads_account_id:
                continue
            rows.append({
                "kind":               ev.kind,
                "threads_account_id": ev.threads_account_id,
                "ig_account_id":      ev.ig_account_id,
                "action_id":          ev.action_id,
                "target":             ev.target,
                "ts":                 ev.ts,
            })
            if len(rows) >= limit:
                break
        return rows

    def for_account(self, threads_account_id: str) -> AccountFunnel:
        return self._counters.get(
            threads_account_id,
            AccountFunnel(threads_account_id=threads_account_id),
        )

    def summary(self) -> dict:
        """Cross-account rollup — totals and best-performing accounts."""
        totals = AccountFunnel(threads_account_id="__all__")
        for c in self._counters.values():
            totals.reply_posted   += c.reply_posted
            totals.post_posted    += c.post_posted
            totals.profile_view   += c.profile_view
            totals.bio_link_click += c.bio_link_click
            totals.subscribe      += c.subscribe

        # Top N accounts by end-to-end rate (require at least 1 reply to
        # avoid divide-by-zero "100%" leaderboard noise from fresh accounts).
        ranked = sorted(
            (c for c in self._counters.values() if c.reply_posted > 0),
            key=lambda c: (
                _safe_ratio(c.subscribe, c.reply_posted),
                c.subscribe,
            ),
            reverse=True,
        )
        return {
            "totals":    totals.as_dict(),
            "accounts":  len(self._counters),
            "top":       [c.as_dict() for c in ranked[:5]],
            "ring_size": len(self._events),
        }
