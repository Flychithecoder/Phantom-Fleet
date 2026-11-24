"""
Instagram recovery agent — shadowban rehab for the IG side of the fleet.

Mirrors the Threads recovery loop with IG-appropriate graduation signal:
posts observed on the IG event bus instead of reply count.

    detector flags  →  agent enrolls  →  cool_down  →  rewarm (day 1)
       ↑                                                  │
       │  (re-flag on rewarm, strike+1)                   │
       └──────── fail ─────────────── health check ──── pass → graduated

Three strikes retires. Default cool-down is 3 days;
`PHANTOM_IG_RECOVERY_COOLDOWN_SEC` overrides for dev. No `random.*`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Optional

from .instagram_health import InstagramHealthMonitor

log = logging.getLogger("phantom_fleet.platforms.instagram_recovery")

IGRecoveryPhase = Literal["cooling_down", "rewarming", "graduated", "retired"]

_DEFAULT_COOL_DOWN_SEC = int(os.getenv("PHANTOM_IG_RECOVERY_COOLDOWN_SEC",
                                        str(3 * 24 * 3600)))
_DEFAULT_REWARM_POSTS_TO_GRADUATE = 5
_DEFAULT_MAX_STRIKES = 3
_REWARM_START_DAY = 1


@dataclass
class IGRecoveryRecord:
    account_id:              str
    phase:                   IGRecoveryPhase
    strikes:                 int = 0
    entered_at:              str = ""
    cool_down_until:         str = ""
    original_warmup_day:     int = 1
    rewarm_baseline_posts:   int = 0
    rewarm_actions_observed: int = 0
    graduated_at:            Optional[str] = None
    retired_at:              Optional[str] = None
    notes:                   list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "account_id":              self.account_id,
            "phase":                   self.phase,
            "strikes":                 self.strikes,
            "entered_at":              self.entered_at,
            "cool_down_until":         self.cool_down_until,
            "original_warmup_day":     self.original_warmup_day,
            "rewarm_baseline_posts":   self.rewarm_baseline_posts,
            "rewarm_actions_observed": self.rewarm_actions_observed,
            "graduated_at":            self.graduated_at,
            "retired_at":              self.retired_at,
            "notes":                   list(self.notes),
        }


@dataclass
class IGRecoveryStats:
    total_enrolled:  int = 0
    total_graduated: int = 0
    total_retired:   int = 0
    cooling_down:    int = 0
    rewarming:       int = 0
    last_tick_at:    Optional[str] = None
    total_ticks:     int = 0

    def as_dict(self) -> dict:
        return {
            "total_enrolled":  self.total_enrolled,
            "total_graduated": self.total_graduated,
            "total_retired":   self.total_retired,
            "cooling_down":    self.cooling_down,
            "rewarming":       self.rewarming,
            "last_tick_at":    self.last_tick_at,
            "total_ticks":     self.total_ticks,
        }


class InstagramRecoveryAgent:
    """Shadowban rehab loop for IG accounts; counterpart to IG health."""

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        health:                InstagramHealthMonitor,
        ig_bus:                Any,
        tick_sec:              float = 120.0,
        cool_down_sec:         int   = _DEFAULT_COOL_DOWN_SEC,
        rewarm_posts_to_graduate: int = _DEFAULT_REWARM_POSTS_TO_GRADUATE,
        max_strikes:           int   = _DEFAULT_MAX_STRIKES,
    ):
        self._accounts_getter = accounts_store_getter
        self.health = health
        self.bus = ig_bus
        self.tick_sec = tick_sec
        self.cool_down_sec = cool_down_sec
        self.rewarm_posts_to_graduate = rewarm_posts_to_graduate
        self.max_strikes = max_strikes

        self.records: dict[str, IGRecoveryRecord] = {}
        self.stats = IGRecoveryStats()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="instagram_recovery")
        log.info("InstagramRecoveryAgent started (cool_down=%ss)", self.cool_down_sec)

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
                log.exception("InstagramRecoveryAgent tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.tick_sec)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _posts_in_ring(self, account_id: str) -> int:
        if self.bus is None:
            return 0
        return sum(1 for e in self.bus.recent(limit=500)
                   if e.get("ig_account_id") == account_id)

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    def _enroll(self, row: dict) -> IGRecoveryRecord:
        acc = row["account_id"]
        cool_until = self._now() + timedelta(seconds=self.cool_down_sec)
        rec = IGRecoveryRecord(
            account_id=acc,
            phase="cooling_down",
            entered_at=self._now().isoformat(),
            cool_down_until=cool_until.isoformat(),
            original_warmup_day=int(row.get("warmup_day", 1)),
            rewarm_baseline_posts=self._posts_in_ring(acc),
            notes=[f"enrolled: IG shadowbanned at day "
                   f"{row.get('warmup_day', 1)}"],
        )
        row["status"] = "paused"
        self.records[acc] = rec
        self.stats.total_enrolled += 1
        log.info("IGRecovery: enrolled %s", acc)
        return rec

    def _begin_rewarm(self, rec: IGRecoveryRecord, row: dict) -> None:
        rec.phase = "rewarming"
        rec.rewarm_baseline_posts = self._posts_in_ring(rec.account_id)
        rec.rewarm_actions_observed = 0
        row["status"] = "active"
        row["warmup_day"] = _REWARM_START_DAY
        rec.notes.append(f"rewarm started at day {_REWARM_START_DAY}")
        log.info("IGRecovery: rewarm started for %s", rec.account_id)

    def _graduate(self, rec: IGRecoveryRecord, row: dict) -> None:
        rec.phase = "graduated"
        rec.graduated_at = self._now().isoformat()
        row["status"] = "active"
        rec.notes.append(
            f"graduated after {rec.rewarm_actions_observed} posts, "
            f"{rec.strikes} strikes")
        self.stats.total_graduated += 1
        log.info("IGRecovery: graduated %s", rec.account_id)

    def _strike(self, rec: IGRecoveryRecord, row: dict) -> None:
        rec.strikes += 1
        rec.notes.append(f"strike {rec.strikes}: re-flagged during rewarm")
        if rec.strikes >= self.max_strikes:
            self._retire(rec, row)
        else:
            cool_until = self._now() + timedelta(seconds=self.cool_down_sec)
            rec.phase = "cooling_down"
            rec.cool_down_until = cool_until.isoformat()
            row["status"] = "paused"
            log.info("IGRecovery: strike %d for %s", rec.strikes, rec.account_id)

    def _retire(self, rec: IGRecoveryRecord, row: dict) -> None:
        rec.phase = "retired"
        rec.retired_at = self._now().isoformat()
        row["status"] = "retired"
        rec.notes.append(f"retired after {rec.strikes} strikes")
        self.stats.total_retired += 1
        log.info("IGRecovery: retired %s", rec.account_id)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self) -> dict:
        store = self._accounts_getter()
        moved: dict[str, list[str]] = {
            "enrolled": [], "rewarming": [],
            "graduated": [], "retired": [], "struck": [],
        }

        for row in store.values():
            if (row.get("platform") == "instagram"
                    and row["account_id"] not in self.records):
                h = self.health.for_account(row["account_id"])
                if h is not None and h.status == "shadowbanned":
                    self._enroll(row)
                    moved["enrolled"].append(row["account_id"])

        now = self._now()
        for rec in list(self.records.values()):
            row = store.get(rec.account_id)
            if row is None:
                continue
            if rec.phase == "cooling_down":
                cool_until = datetime.fromisoformat(rec.cool_down_until)
                if now >= cool_until:
                    self._begin_rewarm(rec, row)
                    moved["rewarming"].append(rec.account_id)
            elif rec.phase == "rewarming":
                baseline = rec.rewarm_baseline_posts
                current = self._posts_in_ring(rec.account_id)
                rec.rewarm_actions_observed = max(0, current - baseline)
                if rec.rewarm_actions_observed >= self.rewarm_posts_to_graduate:
                    fresh = self.health.compute(row)
                    if fresh.status in ("healthy", "watch"):
                        self._graduate(rec, row)
                        moved["graduated"].append(rec.account_id)
                    else:
                        self._strike(rec, row)
                        if rec.phase == "retired":
                            moved["retired"].append(rec.account_id)
                        else:
                            moved["struck"].append(rec.account_id)

        self._refresh_counters()
        self.stats.last_tick_at = now.isoformat()
        self.stats.total_ticks += 1
        return {"moved": moved, "stats": self.stats.as_dict()}

    def _refresh_counters(self) -> None:
        self.stats.cooling_down = sum(1 for r in self.records.values()
                                       if r.phase == "cooling_down")
        self.stats.rewarming = sum(1 for r in self.records.values()
                                    if r.phase == "rewarming")

    # ------------------------------------------------------------------
    # Observability + dev helpers
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        return {
            "running": self.running(),
            "stats":   self.stats.as_dict(),
            "config": {
                "tick_sec":                 self.tick_sec,
                "cool_down_sec":            self.cool_down_sec,
                "rewarm_posts_to_graduate": self.rewarm_posts_to_graduate,
                "max_strikes":              self.max_strikes,
            },
            "records": [r.as_dict() for r in self._sorted_records()],
        }

    def _sorted_records(self) -> list[IGRecoveryRecord]:
        phase_rank = {"cooling_down": 0, "rewarming": 1,
                      "graduated": 2, "retired": 3}
        return sorted(
            self.records.values(),
            key=lambda r: (phase_rank.get(r.phase, 99), r.entered_at),
        )

    def for_account(self, account_id: str) -> Optional[IGRecoveryRecord]:
        return self.records.get(account_id)

    def force_graduate(self, account_id: str) -> Optional[IGRecoveryRecord]:
        rec = self.records.get(account_id)
        if rec is None:
            return None
        row = self._accounts_getter().get(account_id)
        if row is not None:
            self._graduate(rec, row)
            self._refresh_counters()
        return rec

    def enroll(self, account_id: str, reason: str = "manual") -> Optional[IGRecoveryRecord]:
        """Public bridge the checkpoint handler uses to drop an account
        into cooldown when IG throws a challenge screen."""
        row = self._accounts_getter().get(account_id)
        if row is None:
            return None
        if account_id in self.records:
            rec = self.records[account_id]
            rec.notes.append(f"re-enroll · {reason}")
            return rec
        rec = self._enroll(row)
        rec.notes.append(f"enrolled · {reason}")
        self._refresh_counters()
        return rec

    def force_retire(self, account_id: str) -> Optional[IGRecoveryRecord]:
        row = self._accounts_getter().get(account_id)
        if row is None:
            return None
        rec = self.records.get(account_id) or self._enroll(row)
        self._retire(rec, row)
        self._refresh_counters()
        return rec

    def force_rewarm(self, account_id: str) -> Optional[IGRecoveryRecord]:
        rec = self.records.get(account_id)
        if rec is None or rec.phase != "cooling_down":
            return rec
        row = self._accounts_getter().get(account_id)
        if row is not None:
            self._begin_rewarm(rec, row)
            self._refresh_counters()
        return rec
