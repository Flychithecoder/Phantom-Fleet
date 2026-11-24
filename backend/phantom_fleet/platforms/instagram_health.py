"""
Instagram health / shadowban detector.

The IG side of the fleet is the funnel's source — if an IG account goes
dark (no posts, no linked Threads mouth, silent for a day), the Threads
reply engine has nothing to answer to. This monitor scores each IG
account 0-100 and labels it healthy / watch / at_risk / shadowbanned on
signals we can actually see from live state:

Signals (each subtracts from the score):
    post_cadence_collapse   — day >= 7, zero IG events in the last 48h
    no_threads_link         — IG past day 7 with no linked Threads account
    warming_stagnation      — day >= 10, fewer than 2 IG posts ever seen
    zero_recent_activity    — > 24h since last IG event
    engagement_ghost        — > 5 IG posts in ring, but every linked Threads
                              reply skipped for "no_reply_budget" or failed

Status thresholds mirror the Threads monitor so the orchestrator / UI can
treat the two subsystems uniformly. Nothing in this module uses
`random.*` — every score is deterministic given the same event ring.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Optional

log = logging.getLogger("phantom_fleet.platforms.instagram_health")

IGHealthStatus = Literal["healthy", "watch", "at_risk", "shadowbanned"]

_THRESHOLDS: dict[IGHealthStatus, int] = {
    "healthy":      80,
    "watch":        60,
    "at_risk":      35,
    "shadowbanned":  0,
}

_POST_CADENCE_MIN_DAY     = 7
_POST_CADENCE_WINDOW_H    = 48
_WARMING_STAGNATION_DAY   = 10
_WARMING_STAGNATION_POSTS = 2
_INACTIVITY_HOURS         = 24
_ENGAGEMENT_GHOST_POSTS   = 5


@dataclass
class IGSignals:
    warmup_day:           int = 1
    posts_in_ring:        int = 0
    posts_last_48h:       int = 0
    hours_since_last_post: float = 0.0
    has_threads_link:     bool = False
    bridge_skipped_recent: int = 0
    bridge_queued_recent:  int = 0

    def as_dict(self) -> dict:
        return {
            "warmup_day":            self.warmup_day,
            "posts_in_ring":         self.posts_in_ring,
            "posts_last_48h":        self.posts_last_48h,
            "hours_since_last_post": round(self.hours_since_last_post, 2),
            "has_threads_link":      self.has_threads_link,
            "bridge_skipped_recent": self.bridge_skipped_recent,
            "bridge_queued_recent":  self.bridge_queued_recent,
        }


@dataclass
class IGAccountHealth:
    account_id:  str
    status:      IGHealthStatus
    score:       int
    flags:       list[str] = field(default_factory=list)
    signals:     IGSignals = field(default_factory=IGSignals)
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
class IGHealthRollup:
    healthy:      int = 0
    watch:        int = 0
    at_risk:      int = 0
    shadowbanned: int = 0
    total:        int = 0
    last_scan_at: Optional[str] = None
    total_scans:  int = 0

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


def _status_for(score: int) -> IGHealthStatus:
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
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


class InstagramHealthMonitor:
    """
    Scores every IG account from the shared accounts store + IG event bus
    + (optional) cross-post bridge stats.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        ig_bus:                Any,
        bridge:                Any | None = None,
        probes:                Any | None = None,
    ):
        self._accounts_getter = accounts_store_getter
        self._bus             = ig_bus
        self._bridge          = bridge
        self._probes          = probes
        self.rollup           = IGHealthRollup()
        self._cache:          dict[str, IGAccountHealth] = {}

    def set_probes(self, probes: Any | None) -> None:
        self._probes = probes

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _collect(self, row: dict) -> IGSignals:
        acc = row["account_id"]
        store = self._accounts_getter()
        events = self._bus.recent(limit=500) if self._bus is not None else []

        now = datetime.now(timezone.utc)
        cutoff_48h = now - timedelta(hours=_POST_CADENCE_WINDOW_H)
        posts_ring = posts_48h = 0
        last_ts: Optional[datetime] = None
        for e in events:
            if e.get("ig_account_id") != acc:
                continue
            posts_ring += 1
            ts = _parse_iso(e.get("ts", ""))
            if ts is None:
                continue
            if ts > cutoff_48h:
                posts_48h += 1
            if last_ts is None or ts > last_ts:
                last_ts = ts

        hours_idle = ((now - last_ts).total_seconds() / 3600.0
                      if last_ts else 0.0)
        has_link = any(
            r.get("platform") == "threads"
            and r.get("ig_account_id") == acc
            for r in store.values()
        )

        # Bridge counters are fleet-wide, not per-account — but when the
        # only IG posting into them is this account, they read directly.
        # We keep it as a coarse "bridge pressure" signal.
        bridge_skipped = bridge_queued = 0
        if self._bridge is not None:
            s = getattr(self._bridge, "stats", None)
            if s is not None:
                bridge_skipped = (s.skipped_budget + s.skipped_gate
                                  + s.skipped_no_link)
                bridge_queued = s.replies_out

        return IGSignals(
            warmup_day=int(row.get("warmup_day", 1)),
            posts_in_ring=posts_ring,
            posts_last_48h=posts_48h,
            hours_since_last_post=hours_idle,
            has_threads_link=has_link,
            bridge_skipped_recent=bridge_skipped,
            bridge_queued_recent=bridge_queued,
        )

    def _score(self, s: IGSignals) -> tuple[int, list[str]]:
        score = 100
        flags: list[str] = []

        if (s.warmup_day >= _POST_CADENCE_MIN_DAY
                and s.posts_last_48h == 0
                and s.posts_in_ring > 0):
            score -= 45
            flags.append("post_cadence_collapse")

        if s.warmup_day >= _POST_CADENCE_MIN_DAY and not s.has_threads_link:
            score -= 35
            flags.append("no_threads_link")

        if (s.warmup_day >= _WARMING_STAGNATION_DAY
                and s.posts_in_ring < _WARMING_STAGNATION_POSTS):
            score -= 30
            flags.append("warming_stagnation")

        if (s.posts_in_ring > 0
                and s.hours_since_last_post > _INACTIVITY_HOURS):
            score -= 15
            flags.append("zero_recent_activity")

        if (s.posts_in_ring >= _ENGAGEMENT_GHOST_POSTS
                and s.bridge_queued_recent == 0
                and s.bridge_skipped_recent >= s.posts_in_ring):
            score -= 50
            flags.append("engagement_ghost")

        return max(0, score), flags

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def compute(self, row: dict) -> IGAccountHealth:
        signals = self._collect(row)
        score, flags = self._score(signals)
        if self._probes is not None:
            try:
                probe_flags = self._probes.flags_for(row["account_id"])
                score = max(0, score - self._probes.penalty_for(row["account_id"]))
                flags = flags + [f for f in probe_flags if f not in flags]
            except Exception:
                log.exception("IG Health: probe hook failed for %s", row.get("account_id"))
        status = _status_for(score)
        health = IGAccountHealth(
            account_id=row["account_id"],
            status=status,
            score=score,
            flags=flags,
            signals=signals,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._cache[row["account_id"]] = health
        return health

    def for_account(self, account_id: str) -> Optional[IGAccountHealth]:
        return self._cache.get(account_id)

    def status_of(self, account_id: str) -> IGHealthStatus:
        cached = self._cache.get(account_id)
        return cached.status if cached else "healthy"

    def scan_all(self) -> list[IGAccountHealth]:
        rows = [r for r in self._accounts_getter().values()
                if r.get("platform") == "instagram"
                and r.get("status") == "active"]
        results = [self.compute(r) for r in rows]
        self.rollup = IGHealthRollup(
            healthy=sum(1 for h in results if h.status == "healthy"),
            watch=sum(1 for h in results if h.status == "watch"),
            at_risk=sum(1 for h in results if h.status == "at_risk"),
            shadowbanned=sum(1 for h in results if h.status == "shadowbanned"),
            total=len(results),
            last_scan_at=datetime.now(timezone.utc).isoformat(),
            total_scans=self.rollup.total_scans + 1,
        )
        log.info(
            "IGHealth scan: %d accounts | healthy=%d watch=%d at_risk=%d shadowbanned=%d",
            len(results), self.rollup.healthy, self.rollup.watch,
            self.rollup.at_risk, self.rollup.shadowbanned,
        )
        return results

    def summary(self) -> dict:
        at_risk = sorted(
            (h for h in self._cache.values()
             if h.status in ("at_risk", "shadowbanned", "watch")),
            key=lambda h: h.score,
        )
        return {
            "rollup":      self.rollup.as_dict(),
            "at_risk":     [h.as_dict() for h in at_risk[:20]],
            "flag_counts": self._flag_counts(),
        }

    def _flag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for h in self._cache.values():
            for flag in h.flags:
                counts[flag] = counts.get(flag, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Audit scenarios — fixtures the harness can call with no live app wiring
# ---------------------------------------------------------------------------


def audit_scenarios() -> list[dict]:
    """
    Return canonical IG-health scenarios the audit gate can score against.
    Each entry carries a built IGSignals + the expected status so the
    audit code can assert the detector's classifier on a cold instance.
    """
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "name":   "fresh_account",
            "signals": IGSignals(warmup_day=2, posts_in_ring=1,
                                  posts_last_48h=1, hours_since_last_post=6,
                                  has_threads_link=True),
            "expect": "healthy",
        },
        {
            "name":   "cadence_collapse",
            "signals": IGSignals(warmup_day=9, posts_in_ring=4,
                                  posts_last_48h=0, hours_since_last_post=60,
                                  has_threads_link=True),
            "expect": "at_risk",
        },
        {
            "name":   "no_link_past_day_7",
            "signals": IGSignals(warmup_day=10, posts_in_ring=6,
                                  posts_last_48h=3, hours_since_last_post=4,
                                  has_threads_link=False),
            "expect": "watch",
        },
        {
            "name":   "engagement_ghost",
            "signals": IGSignals(warmup_day=11, posts_in_ring=8,
                                  posts_last_48h=3, hours_since_last_post=2,
                                  has_threads_link=True,
                                  bridge_skipped_recent=8,
                                  bridge_queued_recent=0),
            "expect": "at_risk",
        },
        {
            "name":   "dark_account",
            "signals": IGSignals(warmup_day=12, posts_in_ring=10,
                                  posts_last_48h=0, hours_since_last_post=72,
                                  has_threads_link=False,
                                  bridge_skipped_recent=10,
                                  bridge_queued_recent=0),
            "expect": "shadowbanned",
        },
    ]


def score_signals(signals: IGSignals) -> tuple[int, list[str], IGHealthStatus]:
    """Stateless scorer the audit gate can call per scenario."""
    monitor = InstagramHealthMonitor(lambda: {}, ig_bus=None, bridge=None)
    score, flags = monitor._score(signals)
    return score, flags, _status_for(score)
