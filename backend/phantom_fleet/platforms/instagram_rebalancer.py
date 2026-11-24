"""
Instagram fleet rebalancer — IG counterpart of ThreadsFleetRebalancer.

Watches the same three signals on the IG side:
    * IG health shadowban rate (shadowbanned / total active IG accounts)
    * IG probe hidden rate (recent hidden / recent probe runs)
    * IG recovery enrollment velocity (new enrollments / 5 min)

Sets GREEN / YELLOW / RED with hysteretic transitions (trip_streak=2,
clear_streak=3). Exposes plan_per_tick_multiplier and linking_allowed
for the IG orchestrator and account-link endpoints.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Optional

log = logging.getLogger("phantom_fleet.platforms.instagram_rebalancer")

IGFleetLevel = Literal["green", "yellow", "red"]


@dataclass
class IGRebalancerThresholds:
    yellow_shadowban_rate:   float = 0.15
    red_shadowban_rate:      float = 0.30
    yellow_hidden_rate:      float = 0.40
    red_hidden_rate:         float = 0.60
    yellow_enrollment_burst: int   = 3
    enrollment_window_sec:   int   = 300
    trip_streak:             int   = 2
    clear_streak:            int   = 3

    def as_dict(self) -> dict:
        return {
            "yellow_shadowban_rate":   self.yellow_shadowban_rate,
            "red_shadowban_rate":      self.red_shadowban_rate,
            "yellow_hidden_rate":      self.yellow_hidden_rate,
            "red_hidden_rate":         self.red_hidden_rate,
            "yellow_enrollment_burst": self.yellow_enrollment_burst,
            "enrollment_window_sec":   self.enrollment_window_sec,
            "trip_streak":             self.trip_streak,
            "clear_streak":            self.clear_streak,
        }


@dataclass
class IGFleetSnapshot:
    total:             int = 0
    shadowbanned:      int = 0
    at_risk:           int = 0
    watch:             int = 0
    healthy:           int = 0
    shadowban_rate:    float = 0.0
    hidden_rate:       float = 0.0
    probes_total:      int = 0
    probes_hidden:     int = 0
    enrollment_burst:  int = 0

    def as_dict(self) -> dict:
        return {
            "total":            self.total,
            "shadowbanned":     self.shadowbanned,
            "at_risk":          self.at_risk,
            "watch":            self.watch,
            "healthy":          self.healthy,
            "shadowban_rate":   round(self.shadowban_rate, 4),
            "hidden_rate":      round(self.hidden_rate, 4),
            "probes_total":     self.probes_total,
            "probes_hidden":    self.probes_hidden,
            "enrollment_burst": self.enrollment_burst,
        }


@dataclass
class IGRebalancerEvent:
    ts:         str
    kind:       str
    from_level: Optional[IGFleetLevel]
    to_level:   Optional[IGFleetLevel]
    reason:     str

    def as_dict(self) -> dict:
        return {
            "ts":         self.ts,
            "kind":       self.kind,
            "from_level": self.from_level,
            "to_level":   self.to_level,
            "reason":     self.reason,
        }


@dataclass
class IGRebalancerStats:
    level:           IGFleetLevel = "green"
    last_transition: Optional[str] = None
    total_ticks:     int = 0
    total_alerts:    int = 0
    over_streak:     int = 0
    under_streak:    int = 0
    pending_level:   Optional[IGFleetLevel] = None

    def as_dict(self) -> dict:
        return {
            "level":           self.level,
            "last_transition": self.last_transition,
            "total_ticks":     self.total_ticks,
            "total_alerts":    self.total_alerts,
            "over_streak":     self.over_streak,
            "under_streak":    self.under_streak,
            "pending_level":   self.pending_level,
        }


def _rank(level: IGFleetLevel) -> int:
    return {"green": 0, "yellow": 1, "red": 2}[level]


class InstagramFleetRebalancer:
    """Fleet-wide governor for the IG side."""

    def __init__(
        self,
        health:     Any,
        probes:     Any,
        recovery:   Any,
        thresholds: IGRebalancerThresholds | None = None,
        tick_sec:   float = 20.0,
        alert_sink: Callable[[dict], None] | None = None,
    ):
        self.health   = health
        self.probes   = probes
        self.recovery = recovery
        self.t        = thresholds or IGRebalancerThresholds()
        self.tick_sec = tick_sec
        self.alert_sink = alert_sink or (lambda e: None)

        self.stats = IGRebalancerStats()
        self.events: deque[IGRebalancerEvent] = deque(maxlen=200)
        self._last_snapshot: Optional[IGFleetSnapshot] = None

        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="instagram_rebalancer")
        log.info("InstagramFleetRebalancer started (tick=%ss)", self.tick_sec)

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
                self.tick()
            except Exception:
                log.exception("InstagramFleetRebalancer tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.tick_sec)
            except asyncio.TimeoutError:
                pass

    def _snapshot(self) -> IGFleetSnapshot:
        rollup = getattr(self.health, "rollup", None)
        total = getattr(rollup, "total", 0)
        shadowbanned = getattr(rollup, "shadowbanned", 0)
        at_risk = getattr(rollup, "at_risk", 0)
        watch = getattr(rollup, "watch", 0)
        healthy = getattr(rollup, "healthy", 0)
        shadowban_rate = (shadowbanned / total) if total else 0.0

        pstats = getattr(self.probes, "stats", None)
        p_total = getattr(pstats, "total_run", 0)
        p_hidden = getattr(pstats, "total_hidden", 0)
        hidden_rate = (p_hidden / p_total) if p_total else 0.0

        burst = 0
        if self.recovery is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=self.t.enrollment_window_sec)
            for rec in self.recovery.records.values():
                try:
                    entered = datetime.fromisoformat(rec.entered_at)
                except Exception:
                    continue
                if entered >= cutoff:
                    burst += 1

        return IGFleetSnapshot(
            total=total, shadowbanned=shadowbanned, at_risk=at_risk,
            watch=watch, healthy=healthy, shadowban_rate=shadowban_rate,
            hidden_rate=hidden_rate, probes_total=p_total,
            probes_hidden=p_hidden, enrollment_burst=burst,
        )

    def _classify(self, s: IGFleetSnapshot) -> tuple[IGFleetLevel, str]:
        reasons: list[str] = []
        if s.shadowban_rate >= self.t.red_shadowban_rate:
            reasons.append(f"shadowban rate {s.shadowban_rate:.1%} ≥ "
                           f"{self.t.red_shadowban_rate:.0%}")
            return "red", " · ".join(reasons)
        if s.hidden_rate >= self.t.red_hidden_rate and s.probes_total > 0:
            reasons.append(f"probe hidden rate {s.hidden_rate:.1%} ≥ "
                           f"{self.t.red_hidden_rate:.0%}")
            return "red", " · ".join(reasons)
        if s.shadowban_rate >= self.t.yellow_shadowban_rate:
            reasons.append(f"shadowban rate {s.shadowban_rate:.1%} ≥ "
                           f"{self.t.yellow_shadowban_rate:.0%}")
        if s.hidden_rate >= self.t.yellow_hidden_rate and s.probes_total > 0:
            reasons.append(f"probe hidden rate {s.hidden_rate:.1%} ≥ "
                           f"{self.t.yellow_hidden_rate:.0%}")
        if s.enrollment_burst >= self.t.yellow_enrollment_burst:
            reasons.append(f"{s.enrollment_burst} enrollments in "
                           f"{self.t.enrollment_window_sec}s")
        if reasons:
            return "yellow", " · ".join(reasons)
        return "green", "nominal"

    def tick(self) -> dict:
        snap = self._snapshot()
        self._last_snapshot = snap
        target, reason = self._classify(snap)

        self.stats.total_ticks += 1

        if target != self.stats.level:
            if self.stats.pending_level != target:
                self.stats.pending_level = target
                self.stats.over_streak = 1
                self.stats.under_streak = 0
            else:
                self.stats.over_streak += 1
            escalating = _rank(target) > _rank(self.stats.level)
            needed = self.t.trip_streak if escalating else self.t.clear_streak
            if self.stats.over_streak >= needed:
                prev = self.stats.level
                self.stats.level = target
                self.stats.last_transition = datetime.now(timezone.utc).isoformat()
                self.stats.pending_level = None
                self.stats.over_streak = 0
                self._event("transition", prev, target, reason)
                if target == "red":
                    self.stats.total_alerts += 1
                    try:
                        self.alert_sink({
                            "level": "high", "topic": "instagram_fleet_red",
                            "reason": reason,
                            "snapshot": snap.as_dict(),
                        })
                    except Exception:
                        log.exception("ig rebalancer alert_sink raised")
                    self._event("alert", prev, target, "on-call alert fired")
        else:
            self.stats.pending_level = None
            self.stats.over_streak = 0

        return {"snapshot": snap.as_dict(), "level": self.stats.level,
                "reason": reason, "pending_level": self.stats.pending_level}

    def _event(self, kind: str, from_level, to_level, reason: str) -> None:
        ev = IGRebalancerEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            kind=kind, from_level=from_level, to_level=to_level, reason=reason,
        )
        self.events.append(ev)
        log.info("IG Rebalancer %s %s→%s: %s", kind, from_level, to_level, reason)

    def plan_per_tick_multiplier(self) -> float:
        if self.stats.level == "red":    return 0.0
        if self.stats.level == "yellow": return 0.5
        return 1.0

    def linking_allowed(self) -> bool:
        return self.stats.level == "green"

    def summary(self) -> dict:
        return {
            "running":    self.running(),
            "stats":      self.stats.as_dict(),
            "thresholds": self.t.as_dict(),
            "snapshot":   (self._last_snapshot.as_dict()
                           if self._last_snapshot else None),
            "throttles": {
                "plan_per_tick_multiplier": self.plan_per_tick_multiplier(),
                "linking_allowed":          self.linking_allowed(),
            },
            "events":     [e.as_dict() for e in list(self.events)[-30:][::-1]],
        }
