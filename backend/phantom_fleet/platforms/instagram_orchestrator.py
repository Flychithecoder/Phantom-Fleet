"""
Instagram orchestrator — the IG side's planner.

Mirror of ThreadsOrchestrator, applied to IG primitives:
  - Reads every IG account's warming day + today's remaining budget
    (from instagram.budget_for)
  - Reads funnel strength (post → threads_tap rate) from
    InstagramFunnelTracker
  - Filters out IG accounts the health monitor has flagged shadowbanned
    and dampens the weight for at_risk / watch
  - Picks the next action per account in priority order
    (post > story_view > like > follow) and enqueues it

The planner does not execute. It only writes action rows into the
shared in-memory IG queue; a separate executor (future work) pulls from
it. Nothing here uses random.* — ranking is deterministic.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Any

from . import instagram as ig_mod
from . import instagram_diurnal as ig_diurnal
from .instagram_funnel import InstagramFunnelTracker
from .instagram_health import InstagramHealthMonitor

log = logging.getLogger("phantom_fleet.platforms.instagram_orchestrator")

_MAX_FUNNEL_WEIGHT = 2.5
_ACTION_PRIORITY = ("post", "story_view", "like", "follow")


@dataclass
class IGPlanEntry:
    account_id: str
    kind:       str
    target:     str
    reason:     str


@dataclass
class IGOrchestratorStats:
    last_run_at:    Optional[str] = None
    last_plan:      list[IGPlanEntry] = field(default_factory=list)
    total_runs:     int = 0
    total_enqueued: int = 0


class InstagramOrchestrator:
    """Plans one batch of IG actions per tick and writes to the shared queue."""

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        queue_getter:          Callable[[], list[dict]],
        funnel:                InstagramFunnelTracker,
        health:                Optional[InstagramHealthMonitor] = None,
        tick_sec:              float = 60.0,
        plan_per_tick:         int = 6,
        rebalancer:            Any = None,
        agent:                 Any = None,
        agent_ring:            Any = None,
    ):
        self._accounts_getter = accounts_store_getter
        self._queue_getter    = queue_getter
        self.funnel = funnel
        self.health = health
        self.rebalancer = rebalancer
        self.agent = agent
        self.agent_ring = agent_ring
        self.tick_sec = tick_sec
        self.plan_per_tick = plan_per_tick
        self.stats = IGOrchestratorStats()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="instagram_orchestrator")
        log.info("InstagramOrchestrator started")

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
                log.exception("InstagramOrchestrator tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.tick_sec)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _ig_accounts(self) -> list[dict]:
        return [r for r in self._accounts_getter().values()
                if r.get("platform") == "instagram"
                and r.get("status") == "active"]

    def _used_today(self, account_id: str) -> dict[str, int]:
        today = datetime.now(timezone.utc).date().isoformat()
        used = {"follow": 0, "like": 0, "story_view": 0, "post": 0}
        for e in self._queue_getter():
            if e.get("account_id") == account_id and e.get("date") == today:
                used[e["kind"]] = used.get(e["kind"], 0) + 1
        return used

    def _remaining(self, row: dict) -> dict[str, int]:
        b = ig_mod.budget_for(row["account_id"],
                               int(row.get("warmup_day", 1)))
        used = self._used_today(row["account_id"])
        return {
            "follow":     max(0, b.follow     - used["follow"]),
            "like":       max(0, b.like       - used["like"]),
            "story_view": max(0, b.story_view - used["story_view"]),
            "post":       max(0, b.post       - used["post"]),
        }

    def _fleet_mean_post_to_threads(self) -> float:
        totals = self.funnel.summary()["totals"]
        rate = totals["rates"]["post_to_threads"]
        return rate if rate > 0 else 0.0

    def _funnel_weight(self, account_id: str, mean_rate: float) -> float:
        rate = self.funnel.for_account(account_id).as_dict()["rates"]["post_to_threads"]
        if mean_rate <= 0:
            base = 1.0
        elif rate <= 0:
            base = 0.6
        else:
            base = min(_MAX_FUNNEL_WEIGHT, rate / mean_rate)
        if self.health is not None:
            status = self.health.status_of(account_id)
            if status == "at_risk":
                base *= 0.3
            elif status == "watch":
                base *= 0.75
        row = self._accounts_getter().get(account_id, {})
        base *= ig_diurnal.weight_now(account_id, row)
        return base

    async def run_once(self) -> list[IGPlanEntry]:
        accounts = self._ig_accounts()
        if not accounts:
            self.stats.last_run_at = datetime.now(timezone.utc).isoformat()
            self.stats.last_plan = []
            self.stats.total_runs += 1
            return []

        # Health gate — rescore + drop shadowbanned.
        if self.health is not None:
            self.health.scan_all()
            accounts = [r for r in accounts
                        if self.health.status_of(r["account_id"])
                           != "shadowbanned"]
            if not accounts:
                self.stats.last_run_at = datetime.now(timezone.utc).isoformat()
                self.stats.last_plan = []
                self.stats.total_runs += 1
                return []

        mean_rate = self._fleet_mean_post_to_threads()
        ranked = sorted(
            accounts,
            key=lambda r: (
                -self._funnel_weight(r["account_id"], mean_rate),
                -int(r.get("warmup_day", 1)),
                r["account_id"],
            ),
        )

        plan: list[IGPlanEntry] = []
        q = self._queue_getter()
        today = datetime.now(timezone.utc).date().isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Rebalancer throttle — RED halts, YELLOW halves plan cap.
        effective_cap = self.plan_per_tick
        if self.rebalancer is not None:
            mul = self.rebalancer.plan_per_tick_multiplier()
            effective_cap = max(0, int(round(self.plan_per_tick * mul)))
            if effective_cap == 0:
                log.info("InstagramOrchestrator: rebalancer RED — paused")
                self.stats.last_run_at = now_iso
                self.stats.last_plan = []
                self.stats.total_runs += 1
                return []

        for row in ranked:
            if len(plan) >= effective_cap:
                break
            remaining = self._remaining(row)
            for kind in _ACTION_PRIORITY:
                if remaining[kind] <= 0:
                    continue
                weight = self._funnel_weight(row["account_id"], mean_rate)
                reason = (
                    f"day {row.get('warmup_day', 1)} · "
                    f"{kind} budget {remaining[kind]} left · "
                    f"funnel weight {weight:.2f}"
                )
                target = self._compose_target(row, kind)
                if self.agent is not None and self.agent_ring is not None:
                    from ..agents.instagram_agent import dispatch_one
                    await dispatch_one(self.agent, self.agent_ring, {
                        "account_id": row["account_id"],
                        "kind":       kind,
                        "target":     target,
                        "body":       "",
                        "reason":     reason,
                        "planner":    "ig_orchestrator",
                    })
                else:
                    q.append({
                        "action_id":  f"ig-{uuid.uuid4().hex[:12]}",
                        "account_id": row["account_id"],
                        "kind":       kind,
                        "target":     target,
                        "route":      ig_mod.ACTION_ROUTES[kind],
                        "date":       today,
                        "queued_at":  now_iso,
                        "status":     "queued",
                        "planner":    "ig_orchestrator",
                        "reason":     reason,
                    })
                plan.append(IGPlanEntry(
                    account_id=row["account_id"], kind=kind,
                    target=target, reason=reason,
                ))
                break

        self.stats.last_run_at = now_iso
        self.stats.last_plan = plan
        self.stats.total_runs += 1
        self.stats.total_enqueued += len(plan)
        log.info("InstagramOrchestrator: %d actions planned, %d accounts ranked",
                 len(plan), len(accounts))
        return plan

    def _compose_target(self, row: dict, kind: str) -> str:
        seed = f"ig:{row['account_id']}:{kind}:{self.stats.total_runs}"
        idx = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
        if kind == "post":       return ""
        if kind == "story_view": return f"story://account_{(idx % 11) + 1}"
        if kind == "like":       return f"ig://post_{(idx % 17) + 1}"
        return f"@fresh_target_{(idx % 13) + 1}"

    def status(self) -> dict:
        return {
            "running":        self.running(),
            "plan_per_tick":  self.plan_per_tick,
            "tick_sec":       self.tick_sec,
            "last_run_at":    self.stats.last_run_at,
            "total_runs":     self.stats.total_runs,
            "total_enqueued": self.stats.total_enqueued,
            "last_plan": [
                {"account_id": p.account_id, "kind": p.kind,
                 "target": p.target, "reason": p.reason}
                for p in self.stats.last_plan
            ],
        }
