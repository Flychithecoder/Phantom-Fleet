"""
Threads health / shadowban detector.

Reads the funnel tracker, the pending/dispatched queue, and the executor
stats, then scores each Threads account on a 0-100 health scale and
assigns a status: healthy / watch / at_risk / shadowbanned.

The shadowban signal we actually care about is the funnel collapse, not
the "search by username" trick (which is noisy and detectable). If an
account posts 30 replies and gets zero profile views, zero bio clicks,
zero subs, it's effectively invisible — same operational outcome as a
hard shadowban, and far easier to measure.

Signals:
    funnel_ghost          — many replies posted, near-zero downstream
    reply_sink            — replies going through but profile_view rate
                            has decayed below fleet floor
    dispatch_failure      — executor failed > 30% of this account's actions
    queue_stall           — > 5 entries sitting queued past 1h
    warming_stagnation    — day >= 7 but < 3 replies posted ever
    zero_recent_activity  — no dispatch in last N hours

Each signal subtracts from the health score; status thresholds map score
to a label. The orchestrator reads the status and skips shadowbanned
accounts + dampens weight for at_risk ones.

Nothing in this module uses `random.*` or wall-clock jitter; it reads the
same counters the audit harness exercises, so a deterministic pytest
fixture reproduces every score exactly.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Optional

from . import threads as threads_mod
from .threads_funnel import ThreadsFunnelTracker

log = logging.getLogger("phantom_fleet.platforms.threads_health")

HealthStatus = Literal["healthy", "watch", "at_risk", "shadowbanned"]

# Score thresholds — tuned so a brand-new account (no history) stays at
# "healthy" instead of being flagged just for lack of data.
_THRESHOLDS: dict[HealthStatus, int] = {
    "healthy":       80,
    "watch":         60,
    "at_risk":       35,
    "shadowbanned":   0,
}

# Fleet-floor rates. An account whose reply_to_view falls below this
# while having enough replies to measure is flagged.
_FLOOR_REPLY_TO_VIEW = 0.15
_MIN_REPLIES_FOR_FUNNEL_SIGNAL = 10
_MIN_REPLIES_FOR_GHOST_SIGNAL = 20
_MIN_DISPATCHES_FOR_FAILURE_SIGNAL = 10
_MAX_FAILURE_RATE = 0.30
_QUEUE_STALL_THRESHOLD = 5
_QUEUE_STALL_AGE_MIN = 60
_WARMING_STAGNATION_MIN_DAY = 7
_WARMING_STAGNATION_MIN_REPLIES = 3
_INACTIVITY_HOURS = 24


@dataclass
class HealthSignals:
    reply_posted:         int = 0
    profile_view:         int = 0
    bio_link_click:       int = 0
    subscribe:            int = 0
    reply_to_view_rate:   float = 0.0
    dispatched:           int = 0
    failed:               int = 0
    dispatch_failure_rate: float = 0.0
    queued_pending:       int = 0
    stalled_count:        int = 0
    warmup_day:           int = 1
    hours_since_dispatch: float = 0.0

    def as_dict(self) -> dict:
        return {
            "reply_posted":          self.reply_posted,
            "profile_view":          self.profile_view,
            "bio_link_click":        self.bio_link_click,
            "subscribe":             self.subscribe,
            "reply_to_view_rate":    round(self.reply_to_view_rate, 4),
            "dispatched":            self.dispatched,
            "failed":                self.failed,
            "dispatch_failure_rate": round(self.dispatch_failure_rate, 4),
            "queued_pending":        self.queued_pending,
            "stalled_count":         self.stalled_count,
            "warmup_day":            self.warmup_day,
            "hours_since_dispatch":  round(self.hours_since_dispatch, 2),
        }


@dataclass
class AccountHealth:
    account_id:  str
    status:      HealthStatus
    score:       int
    flags:       list[str] = field(default_factory=list)
    signals:     HealthSignals = field(default_factory=HealthSignals)
    computed_at: str = ""

    def as_dict(self) -> dict:
        return {
            "account_id":  self.account_id,
            "status":      self.status,
            "score":       self.score,
            "flags":       list(self.flags),
            "signals":     self.signals.as_dict(),
            "computed_at": self.computed_at,
        }


@dataclass
class HealthRollup:
    healthy:       int = 0
    watch:         int = 0
    at_risk:       int = 0
    shadowbanned:  int = 0
    total:         int = 0
    last_scan_at:  Optional[str] = None
    total_scans:   int = 0

    def as_dict(self) -> dict:
        return {
            "healthy":      self.healthy,
            "watch":        self.watch,
            "at_risk":      self.at_risk,
            "shadowbanned": self.shadowbanned,
            "total":        self.total,
            "last_scan_at": self.last_scan_at,
            "total_scans":  self.total_scans,
        }


def _status_for(score: int) -> HealthStatus:
    if score >= _THRESHOLDS["healthy"]:
        return "healthy"
    if score >= _THRESHOLDS["watch"]:
        return "watch"
    if score >= _THRESHOLDS["at_risk"]:
        return "at_risk"
    return "shadowbanned"


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


class ThreadsHealthMonitor:
    """
    Computes AccountHealth per Threads account from the shared queue +
    funnel tracker. Stateless with respect to the accounts store; every
    call pulls fresh.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        queue_getter:          Callable[[], list[dict]],
        funnel:                ThreadsFunnelTracker,
        repo:                  Any | None = None,
        probes:                Any | None = None,
    ):
        self._accounts_getter = accounts_store_getter
        self._queue_getter    = queue_getter
        self.funnel           = funnel
        self.rollup           = HealthRollup()
        self._cache:          dict[str, AccountHealth] = {}
        self._repo            = repo
        self._probes          = probes

    def set_repo(self, repo: Any | None) -> None:
        self._repo = repo

    def set_probes(self, probes: Any | None) -> None:
        self._probes = probes

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _collect_signals(self, row: dict) -> HealthSignals:
        acc = row["account_id"]
        counter = self.funnel.for_account(acc)
        rtv = (counter.profile_view / counter.reply_posted
               if counter.reply_posted else 0.0)

        dispatched = failed = queued_pending = stalled = 0
        last_dispatch_at: Optional[datetime] = None
        now = datetime.now(timezone.utc)
        stall_cutoff = now - timedelta(minutes=_QUEUE_STALL_AGE_MIN)

        for e in self._queue_getter():
            if e.get("account_id") != acc:
                continue
            status = e.get("status", "queued")
            if status == "dispatched":
                dispatched += 1
                ts = _parse_iso(e.get("dispatched_at", ""))
                if ts and (last_dispatch_at is None or ts > last_dispatch_at):
                    last_dispatch_at = ts
            elif status == "failed":
                failed += 1
            elif status == "queued":
                queued_pending += 1
                ts = _parse_iso(e.get("queued_at", ""))
                if ts and ts < stall_cutoff:
                    stalled += 1

        total_done = dispatched + failed
        fail_rate = failed / total_done if total_done else 0.0
        hours_idle = ((now - last_dispatch_at).total_seconds() / 3600.0
                      if last_dispatch_at else 0.0)

        return HealthSignals(
            reply_posted=counter.reply_posted,
            profile_view=counter.profile_view,
            bio_link_click=counter.bio_link_click,
            subscribe=counter.subscribe,
            reply_to_view_rate=rtv,
            dispatched=dispatched,
            failed=failed,
            dispatch_failure_rate=fail_rate,
            queued_pending=queued_pending,
            stalled_count=stalled,
            warmup_day=int(row.get("warmup_day", 1)),
            hours_since_dispatch=hours_idle,
        )

    def _score(self, s: HealthSignals) -> tuple[int, list[str]]:
        score = 100
        flags: list[str] = []

        if (s.reply_posted >= _MIN_REPLIES_FOR_GHOST_SIGNAL
                and s.profile_view == 0):
            # Many replies, zero eyes = textbook shadowban. One-signal catastrophe.
            score -= 70
            flags.append("funnel_ghost")

        if (s.reply_posted >= _MIN_REPLIES_FOR_FUNNEL_SIGNAL
                and s.reply_to_view_rate < _FLOOR_REPLY_TO_VIEW
                and s.reply_to_view_rate > 0):
            score -= 25
            flags.append("reply_sink")

        if (s.dispatched + s.failed >= _MIN_DISPATCHES_FOR_FAILURE_SIGNAL
                and s.dispatch_failure_rate > _MAX_FAILURE_RATE):
            score -= 20
            flags.append("dispatch_failure")

        if s.stalled_count >= _QUEUE_STALL_THRESHOLD:
            score -= 15
            flags.append("queue_stall")

        if (s.warmup_day >= _WARMING_STAGNATION_MIN_DAY
                and s.reply_posted < _WARMING_STAGNATION_MIN_REPLIES):
            score -= 25
            flags.append("warming_stagnation")

        if (s.dispatched > 0
                and s.hours_since_dispatch > _INACTIVITY_HOURS):
            score -= 10
            flags.append("zero_recent_activity")

        return max(0, score), flags

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def compute(self, row: dict) -> AccountHealth:
        signals = self._collect_signals(row)
        score, flags = self._score(signals)
        # Active probes are an orthogonal signal — merge their flags and
        # penalties on top of the passive score.
        if self._probes is not None:
            try:
                probe_flags = self._probes.flags_for(row["account_id"])
                score = max(0, score - self._probes.penalty_for(row["account_id"]))
                flags = flags + [f for f in probe_flags if f not in flags]
            except Exception:
                log.exception("Health: probe hook failed for %s", row.get("account_id"))
        status = _status_for(score)
        health = AccountHealth(
            account_id=row["account_id"],
            status=status,
            score=score,
            flags=flags,
            signals=signals,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._cache[row["account_id"]] = health
        if self._repo is not None:
            try:
                asyncio.create_task(self._repo.record_health_snapshot(
                    health.as_dict()))
            except RuntimeError:
                pass
        return health

    def for_account(self, account_id: str) -> Optional[AccountHealth]:
        return self._cache.get(account_id)

    def status_of(self, account_id: str) -> HealthStatus:
        cached = self._cache.get(account_id)
        return cached.status if cached else "healthy"

    def scan_all(self) -> list[AccountHealth]:
        """Recompute health for every active Threads account."""
        rows = [r for r in self._accounts_getter().values()
                if r.get("platform") == "threads"
                and r.get("status") == "active"]
        results = [self.compute(r) for r in rows]
        self.rollup = HealthRollup(
            healthy=sum(1 for h in results if h.status == "healthy"),
            watch=sum(1 for h in results if h.status == "watch"),
            at_risk=sum(1 for h in results if h.status == "at_risk"),
            shadowbanned=sum(1 for h in results if h.status == "shadowbanned"),
            total=len(results),
            last_scan_at=datetime.now(timezone.utc).isoformat(),
            total_scans=self.rollup.total_scans + 1,
        )
        log.info(
            "ThreadsHealth scan: %d accounts | healthy=%d watch=%d at_risk=%d shadowbanned=%d",
            len(results), self.rollup.healthy, self.rollup.watch,
            self.rollup.at_risk, self.rollup.shadowbanned,
        )
        return results

    def summary(self) -> dict:
        at_risk = sorted(
            (h for h in self._cache.values()
             if h.status in ("at_risk", "shadowbanned")),
            key=lambda h: h.score,
        )
        return {
            "rollup": self.rollup.as_dict(),
            "at_risk":  [h.as_dict() for h in at_risk[:20]],
            "flag_counts": self._flag_counts(),
        }

    def _flag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for h in self._cache.values():
            for flag in h.flags:
                counts[flag] = counts.get(flag, 0) + 1
        return counts
