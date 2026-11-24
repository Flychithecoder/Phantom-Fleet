"""
Threads orchestrator — decides what every linked Threads account should
be doing right now.

It reads every account's warming day, today's remaining budget, and the
funnel performance from the ThreadsFunnelTracker, then enqueues the next
batch of actions into the executor queue. The executor pulls from that
queue with its own timing — the orchestrator is purely the planner.

Budget-aware: an account with 0 reply budget left today will not get
more replies queued, even if the funnel loves it. Funnel-weighted: an
account whose reply→sub rate is 2× the fleet mean gets up to 2× the
discretionary action share. Warming-respecting: posts never enqueue
before day 8 (matches the base curve).

The orchestrator does NOT touch distribution math — those live in
threads.py (budgets) and threads_executor.py (inter-action delays).
It only chooses which account/kind to spend budget on each tick.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from . import threads as threads_mod
from .threads_funnel import ThreadsFunnelTracker
from .threads_health import ThreadsHealthMonitor

log = logging.getLogger("phantom_fleet.platforms.threads_orchestrator")


# Weight ceiling: no single account gets more than this × the fleet mean
# share, even if its reply→sub rate is sky-high. Keeps a single hot account
# from starving the fleet of cross-posts.
_MAX_FUNNEL_WEIGHT = 2.5


@dataclass
class PlanEntry:
    account_id: str
    kind:       str
    target:     str
    body:       str
    reason:     str                 # Why the orchestrator picked this


@dataclass
class OrchestratorStats:
    last_run_at:  Optional[str] = None
    last_plan:    list[PlanEntry] = field(default_factory=list)
    total_runs:   int = 0
    total_enqueued: int = 0


# ---------------------------------------------------------------------------
# Content generators — stubbed, swap for Content Agent / ModelForge later
# ---------------------------------------------------------------------------


_REPLY_LIBRARY = (
    "this hit different fr",
    "needed this today ngl",
    "ok but how did you know",
    "reposting this to my story later",
    "brb grabbing my notes app",
    "say it louder for the people in the back",
    "literally obsessed",
    "sending to my group chat rn",
)

_POST_LIBRARY = (
    "softly reminding you that rest is productive too",
    "if it's not a yes, it's a no",
    "the glow up is the healing",
    "tonight we romanticize the mundane",
    "bio link if you want the full story",
    "catch me being delulu on main again",
)


def _draw(library: tuple[str, ...], seed: str) -> str:
    """Deterministic pick from a library so audits are reproducible."""
    idx = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % len(library)
    return library[idx]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ThreadsOrchestrator:
    """
    Plans the next batch of Threads actions, writes them to the shared
    queue, and reports what it did.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        queue_getter:          Callable[[], list[dict]],
        funnel:                ThreadsFunnelTracker,
        tick_sec:              float = 60.0,
        plan_per_tick:         int = 6,
        health:                Optional[ThreadsHealthMonitor] = None,
        agent:                 Optional[object] = None,
        agent_ring:            Optional[object] = None,
        rebalancer:            Optional[object] = None,
    ):
        self._accounts_getter = accounts_store_getter
        self._queue_getter = queue_getter
        self.funnel = funnel
        self.health = health
        self.agent = agent
        self.agent_ring = agent_ring
        self.rebalancer = rebalancer
        self.tick_sec = tick_sec
        self.plan_per_tick = plan_per_tick
        self.stats = OrchestratorStats()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="threads_orchestrator")
        log.info("ThreadsOrchestrator started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                log.exception("ThreadsOrchestrator tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.tick_sec)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _threads_accounts(self) -> list[dict]:
        return [r for r in self._accounts_getter().values()
                if r.get("platform") == "threads" and r.get("status") == "active"]

    def _used_today(self, account_id: str) -> dict[str, int]:
        today = datetime.now(timezone.utc).date().isoformat()
        used = {"follow": 0, "reply": 0, "repost": 0, "post": 0}
        for e in self._queue_getter():
            if e.get("account_id") == account_id and e.get("date") == today:
                used[e["kind"]] = used.get(e["kind"], 0) + 1
        return used

    def _remaining(self, row: dict) -> dict[str, int]:
        b = threads_mod.budget_for(row["account_id"],
                                    int(row.get("warmup_day", 1)))
        used = self._used_today(row["account_id"])
        return {
            "follow": max(0, b.follow - used["follow"]),
            "reply":  max(0, b.reply  - used["reply"]),
            "repost": max(0, b.repost - used["repost"]),
            "post":   max(0, b.post   - used["post"]),
        }

    def _funnel_weight(self, account_id: str, mean_rate: float) -> float:
        if mean_rate <= 0:
            base = 1.0
        else:
            rate = self.funnel.for_account(account_id).as_dict()["rates"]["reply_to_sub"]
            if rate <= 0:
                base = 0.6                            # Cold accounts get slightly less
            else:
                base = min(_MAX_FUNNEL_WEIGHT, rate / mean_rate)
        # Health dampener: at_risk accounts get 0.3× share, watch gets 0.75×.
        if self.health is not None:
            status = self.health.status_of(account_id)
            if status == "at_risk":
                base *= 0.3
            elif status == "watch":
                base *= 0.75
        return base

    def _fleet_mean_reply_to_sub(self) -> float:
        totals = self.funnel.summary()["totals"]
        rate = totals["rates"]["reply_to_sub"]
        return rate if rate > 0 else 0.0

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def run_once(self) -> list[PlanEntry]:
        """Plan + enqueue one round. Returns the plan for observability."""
        accounts = self._threads_accounts()
        if not accounts:
            self.stats.last_run_at = datetime.now(timezone.utc).isoformat()
            self.stats.last_plan = []
            self.stats.total_runs += 1
            return []

        mean_rate = self._fleet_mean_reply_to_sub()

        # Health gate: refresh scores, then drop shadowbanned accounts
        # before ranking so they can't consume a plan slot. at_risk ones
        # stay but take a weight hit inside _funnel_weight.
        if self.health is not None:
            self.health.scan_all()
            accounts = [r for r in accounts
                        if self.health.status_of(r["account_id"])
                           != "shadowbanned"]
            if not accounts:
                self.stats.last_run_at = datetime.now(timezone.utc).isoformat()
                self.stats.last_plan = []
                self.stats.total_runs += 1
                log.info("ThreadsOrchestrator: all accounts shadowbanned; skipping tick")
                return []

        # Rank accounts: funnel weight first, then warming day (older warmer
        # accounts are closer to posting), then account_id for determinism.
        ranked = sorted(
            accounts,
            key=lambda r: (
                -self._funnel_weight(r["account_id"], mean_rate),
                -int(r.get("warmup_day", 1)),
                r["account_id"],
            ),
        )

        plan: list[PlanEntry] = []
        q = self._queue_getter()
        today = datetime.now(timezone.utc).date().isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Rebalancer throttle — RED halts dispatch, YELLOW halves plan size.
        effective_plan_cap = self.plan_per_tick
        if self.rebalancer is not None:
            mul = self.rebalancer.plan_per_tick_multiplier()
            effective_plan_cap = max(0, int(round(self.plan_per_tick * mul)))
            if effective_plan_cap == 0:
                log.info("ThreadsOrchestrator: rebalancer RED — dispatch paused")
                self.stats.last_run_at = now_iso
                self.stats.last_plan = []
                self.stats.total_runs += 1
                return []

        for row in ranked:
            if len(plan) >= effective_plan_cap:
                break
            remaining = self._remaining(row)

            # Priority order: post > reply > repost > follow. Posts are the
            # rarest + highest-funnel-impact action; follows are warmup glue.
            for kind in ("post", "reply", "repost", "follow"):
                if remaining[kind] <= 0:
                    continue
                if kind == "reply" and not threads_mod.can_cross_post(row):
                    continue

                weight = self._funnel_weight(row["account_id"], mean_rate)
                reason = (
                    f"day {row.get('warmup_day', 1)} · "
                    f"{kind} budget {remaining[kind]} left · "
                    f"funnel weight {weight:.2f}"
                )

                target, body = self._compose(row, kind)
                if self.agent is not None and self.agent_ring is not None:
                    # Route through the ThreadsAgent so the dispatch rides
                    # the CLAUDE.md agent frame (allowlist, caps, audit).
                    from ..agents.threads_agent import dispatch_one
                    rec = await dispatch_one(self.agent, self.agent_ring, {
                        "account_id": row["account_id"],
                        "kind":       kind,
                        "target":     target,
                        "body":       body,
                        "reason":     reason,
                        "planner":    "orchestrator",
                    })
                    if rec.status != "success":
                        log.info("Orchestrator agent run %s for %s %s: %s",
                                 rec.run_id, row["account_id"], kind, rec.status)
                        continue
                else:
                    entry = {
                        "action_id":  f"th-{uuid.uuid4().hex[:12]}",
                        "account_id": row["account_id"],
                        "kind":       kind,
                        "target":     target,
                        "body":       body,
                        "route":      threads_mod.ACTION_ROUTES[kind],
                        "date":       today,
                        "queued_at":  now_iso,
                        "status":     "queued",
                        "planner":    "orchestrator",
                        "reason":     reason,
                    }
                    q.append(entry)
                plan.append(PlanEntry(
                    account_id=row["account_id"], kind=kind,
                    target=target, body=body, reason=reason,
                ))
                break   # one new action per account per tick

        self.stats.last_run_at = datetime.now(timezone.utc).isoformat()
        self.stats.last_plan = plan
        self.stats.total_runs += 1
        self.stats.total_enqueued += len(plan)
        log.info("ThreadsOrchestrator: %d actions planned, %d accounts ranked",
                 len(plan), len(accounts))
        return plan

    def _compose(self, row: dict, kind: str) -> tuple[str, str]:
        seed = f"{row['account_id']}:{kind}:{self.stats.total_runs}"
        if kind == "post":
            return "", _draw(_POST_LIBRARY, seed)
        if kind == "reply":
            # Targets whoever the IG parent last posted at — stub for now.
            return f"@ig_target_{(self.stats.total_runs % 7) + 1}", _draw(_REPLY_LIBRARY, seed)
        if kind == "repost":
            return f"@thread_{(self.stats.total_runs % 9) + 1}", ""
        # follow
        return f"@fresh_{(self.stats.total_runs % 11) + 1}", ""
