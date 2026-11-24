"""
Threads recovery agent — shadowban rehab, not a kill switch.

When ThreadsHealthMonitor flags an account shadowbanned, the recovery
agent takes it out of rotation, runs it through a cool-down, resets
warming, and rewarms it under a lowered-budget profile. If health
recovers, it graduates back to active. If it gets flagged again during
rewarm, it earns a strike. Three strikes retires the account.

This is the natural counterpart to the detector:

    detector flags  →  agent enrolls  →  cool_down  →  rewarm (day 1)
       ↑                                                  │
       │  (re-flag on rewarm, strike+1)                   │
       └──────── fail ─────────────── health check ──── pass → graduated

State lives in-memory keyed by account_id (production: Postgres
`threads_recovery_records`). The agent runs as an asyncio background
task; `tick()` is also callable directly for tests and for the UI's
"Run now" button.

Nothing in this module uses `random.*`; every timer is wall-clock.
Cool-down defaults to 3 days in production but is `PHANTOM_RECOVERY_COOLDOWN_SEC`
overridable for dev so the loop is testable in seconds.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Optional

from .threads_funnel import ThreadsFunnelTracker
from .threads_health import ThreadsHealthMonitor

log = logging.getLogger("phantom_fleet.platforms.threads_recovery")

RecoveryPhase = Literal["cooling_down", "rewarming", "graduated", "retired"]

_DEFAULT_COOL_DOWN_SEC = int(os.getenv("PHANTOM_RECOVERY_COOLDOWN_SEC",
                                        str(3 * 24 * 3600)))
_DEFAULT_REWARM_REPLIES_TO_GRADUATE = 10
_DEFAULT_MAX_STRIKES = 3
_REWARM_START_DAY = 1


@dataclass
class RecoveryRecord:
    account_id:             str
    phase:                  RecoveryPhase
    strikes:                int = 0
    entered_at:             str = ""
    cool_down_until:        str = ""
    original_warmup_day:    int = 1
    rewarm_baseline_replies: int = 0
    rewarm_actions_observed: int = 0
    graduated_at:           Optional[str] = None
    retired_at:             Optional[str] = None
    notes:                  list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "account_id":              self.account_id,
            "phase":                   self.phase,
            "strikes":                 self.strikes,
            "entered_at":              self.entered_at,
            "cool_down_until":         self.cool_down_until,
            "original_warmup_day":     self.original_warmup_day,
            "rewarm_baseline_replies": self.rewarm_baseline_replies,
            "rewarm_actions_observed": self.rewarm_actions_observed,
            "graduated_at":            self.graduated_at,
            "retired_at":              self.retired_at,
            "notes":                   list(self.notes),
        }


@dataclass
class RecoveryStats:
    total_enrolled:     int = 0
    total_graduated:    int = 0
    total_retired:      int = 0
    cooling_down:       int = 0
    rewarming:          int = 0
    last_tick_at:       Optional[str] = None
    total_ticks:        int = 0

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


class ThreadsRecoveryAgent:
    """
    Autonomous rehab loop for shadowbanned Threads accounts.

    Reads ThreadsHealthMonitor on every tick for new enrollments and
    for mid-rewarm health checks. Writes directly to the accounts
    store (pause / rewarm with low warmup_day / retire). Honors the
    status field so the orchestrator stops dispatching to paused or
    retired accounts without needing its own gate.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        health:                ThreadsHealthMonitor,
        funnel:                ThreadsFunnelTracker,
        tick_sec:              float = 120.0,
        cool_down_sec:         int = _DEFAULT_COOL_DOWN_SEC,
        rewarm_graduate_replies: int = _DEFAULT_REWARM_REPLIES_TO_GRADUATE,
        max_strikes:           int = _DEFAULT_MAX_STRIKES,
        repo:                  Any | None = None,
    ):
        self._accounts_getter = accounts_store_getter
        self.health = health
        self.funnel = funnel
        self.tick_sec = tick_sec
        self.cool_down_sec = cool_down_sec
        self.rewarm_graduate_replies = rewarm_graduate_replies
        self.max_strikes = max_strikes

        self.records: dict[str, RecoveryRecord] = {}
        self.stats = RecoveryStats()
        self._repo = repo
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def set_repo(self, repo: Any | None) -> None:
        self._repo = repo

    def restore_records(self, rows: list[dict]) -> None:
        """Rehydrate recovery records from DB on startup."""
        for r in rows:
            self.records[r["account_id"]] = RecoveryRecord(
                account_id=r["account_id"], phase=r["phase"],
                strikes=int(r["strikes"]),
                entered_at=r["entered_at"], cool_down_until=r["cool_down_until"],
                original_warmup_day=int(r["original_warmup_day"]),
                rewarm_baseline_replies=int(r["rewarm_baseline_replies"]),
                rewarm_actions_observed=int(r["rewarm_actions_observed"]),
                graduated_at=r.get("graduated_at"),
                retired_at=r.get("retired_at"),
                notes=list(r.get("notes", [])),
            )
            if r["phase"] == "graduated":
                self.stats.total_graduated += 1
            elif r["phase"] == "retired":
                self.stats.total_retired += 1
        self.stats.total_enrolled = len(self.records)
        self._refresh_counters()
        log.info("ThreadsRecoveryAgent: restored %d records", len(rows))

    def _persist(self, rec: "RecoveryRecord") -> None:
        if self._repo is None:
            return
        try:
            asyncio.create_task(self._repo.upsert_recovery_record(rec.as_dict()))
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="threads_recovery")
        log.info("ThreadsRecoveryAgent started (cool_down=%ss)", self.cool_down_sec)

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
                log.exception("ThreadsRecoveryAgent tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.tick_sec)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _enroll(self, row: dict) -> RecoveryRecord:
        acc = row["account_id"]
        cool_until = self._now() + timedelta(seconds=self.cool_down_sec)
        rec = RecoveryRecord(
            account_id=acc,
            phase="cooling_down",
            entered_at=self._now().isoformat(),
            cool_down_until=cool_until.isoformat(),
            original_warmup_day=int(row.get("warmup_day", 1)),
            rewarm_baseline_replies=self.funnel.for_account(acc).reply_posted,
            notes=[f"enrolled: shadowbanned at day "
                   f"{row.get('warmup_day', 1)}"],
        )
        row["status"] = "paused"
        self.records[acc] = rec
        self.stats.total_enrolled += 1
        self._persist(rec)
        log.info("Recovery: enrolled %s (cool_down_until=%s)",
                 acc, rec.cool_down_until)
        return rec

    def _begin_rewarm(self, rec: RecoveryRecord, row: dict) -> None:
        rec.phase = "rewarming"
        rec.rewarm_baseline_replies = self.funnel.for_account(
            rec.account_id).reply_posted
        rec.rewarm_actions_observed = 0
        row["status"] = "active"
        row["warmup_day"] = _REWARM_START_DAY
        rec.notes.append(f"rewarm started at day {_REWARM_START_DAY}")
        self._persist(rec)
        log.info("Recovery: rewarm started for %s", rec.account_id)

    def _graduate(self, rec: RecoveryRecord, row: dict) -> None:
        rec.phase = "graduated"
        rec.graduated_at = self._now().isoformat()
        row["status"] = "active"
        rec.notes.append(
            f"graduated after {rec.rewarm_actions_observed} replies, "
            f"{rec.strikes} strikes")
        self.stats.total_graduated += 1
        self._persist(rec)
        log.info("Recovery: graduated %s", rec.account_id)

    def _strike(self, rec: RecoveryRecord, row: dict) -> None:
        rec.strikes += 1
        rec.notes.append(f"strike {rec.strikes}: re-flagged during rewarm")
        if rec.strikes >= self.max_strikes:
            self._retire(rec, row)
        else:
            cool_until = self._now() + timedelta(seconds=self.cool_down_sec)
            rec.phase = "cooling_down"
            rec.cool_down_until = cool_until.isoformat()
            row["status"] = "paused"
            self._persist(rec)
            log.info("Recovery: strike %d for %s, back to cool-down",
                     rec.strikes, rec.account_id)

    def _retire(self, rec: RecoveryRecord, row: dict) -> None:
        rec.phase = "retired"
        rec.retired_at = self._now().isoformat()
        row["status"] = "retired"
        rec.notes.append(f"retired after {rec.strikes} strikes")
        self.stats.total_retired += 1
        self._persist(rec)
        log.info("Recovery: retired %s after %d strikes",
                 rec.account_id, rec.strikes)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self) -> dict:
        """
        One pass: enroll new shadowbanned accounts, advance cool-down and
        rewarm phases, update stats. Returns a summary of what moved.
        """
        store = self._accounts_getter()
        moved: dict[str, list[str]] = {
            "enrolled": [], "rewarming": [],
            "graduated": [], "retired": [], "struck": [],
        }

        # 1. Enroll any new shadowbanned account not already tracked.
        for row in store.values():
            if (row.get("platform") == "threads"
                    and row["account_id"] not in self.records):
                h = self.health.for_account(row["account_id"])
                if h is not None and h.status == "shadowbanned":
                    self._enroll(row)
                    moved["enrolled"].append(row["account_id"])

        # 2. Advance each existing record.
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
                baseline = rec.rewarm_baseline_replies
                current = self.funnel.for_account(rec.account_id).reply_posted
                rec.rewarm_actions_observed = max(0, current - baseline)
                if rec.rewarm_actions_observed >= self.rewarm_graduate_replies:
                    # Re-score health at the graduation checkpoint.
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
            # graduated / retired: terminal

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
    # Observability
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        return {
            "running":  self.running(),
            "stats":    self.stats.as_dict(),
            "config": {
                "tick_sec":                self.tick_sec,
                "cool_down_sec":           self.cool_down_sec,
                "rewarm_graduate_replies": self.rewarm_graduate_replies,
                "max_strikes":             self.max_strikes,
            },
            "records":  [r.as_dict() for r in self._sorted_records()],
        }

    def _sorted_records(self) -> list[RecoveryRecord]:
        phase_rank = {"cooling_down": 0, "rewarming": 1,
                      "graduated": 2, "retired": 3}
        return sorted(
            self.records.values(),
            key=lambda r: (phase_rank.get(r.phase, 99), r.entered_at),
        )

    def for_account(self, account_id: str) -> Optional[RecoveryRecord]:
        return self.records.get(account_id)

    def force_graduate(self, account_id: str) -> Optional[RecoveryRecord]:
        """Dev helper: manual graduation from UI."""
        rec = self.records.get(account_id)
        if rec is None:
            return None
        row = self._accounts_getter().get(account_id)
        if row is not None:
            self._graduate(rec, row)
            self._refresh_counters()
        return rec

    def force_rewarm(self, account_id: str) -> Optional[RecoveryRecord]:
        """Dev helper: skip the cool-down timer."""
        rec = self.records.get(account_id)
        if rec is None or rec.phase != "cooling_down":
            return rec
        row = self._accounts_getter().get(account_id)
        if row is not None:
            self._begin_rewarm(rec, row)
            self._refresh_counters()
        return rec
