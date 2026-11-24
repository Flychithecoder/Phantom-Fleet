"""
Threads active shadowban probes.

Passive detection (ThreadsHealthMonitor) watches funnel decay — if replies
stop producing views, we flag it. That's downstream. This module adds
UPSTREAM probes: active checks run by a separate (shadowbanned-immune)
account that query platform surfaces for the suspect account's content.

Three probe kinds, each a distinct detection path:

    search_reach    — searcher queries "@<handle>", expects to see the
                      suspect in results. Missing → search-hidden.
    hashtag_reach   — suspect posts with a probe hashtag, searcher
                      opens the hashtag feed, expects the post. Missing
                      → hashtag-ghosted.
    reply_visibility — suspect posts a reply to a known thread, searcher
                      opens the thread, expects the reply. Missing →
                      reply-hidden (the classic hard shadowban).

Each probe uses a DIFFERENT searcher account every run (never the suspect
checking itself — that's a self-view which platforms always serve). The
searcher pool is a ring of healthy fleet accounts; probes never schedule
a searcher that's at_risk or shadowbanned.

In dev, dispatch is simulated: a fake "world" returns `found=False` if
the suspect's current health is at_risk / shadowbanned, else True. The
dispatcher is a single swap-point (`_dispatch_probe`) that will later
route through the mirror bridge; the probe scheduler, result storage,
and health hookup don't change.

Nothing in this module uses `random.*` — probe selection and timing are
deterministic via seed.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Optional

log = logging.getLogger("phantom_fleet.platforms.threads_probes")

ProbeKind = Literal["search_reach", "hashtag_reach", "reply_visibility"]

PROBE_KINDS: tuple[ProbeKind, ...] = (
    "search_reach", "hashtag_reach", "reply_visibility",
)

# Flag name that each probe failure adds to the health monitor.
PROBE_FLAG: dict[ProbeKind, str] = {
    "search_reach":     "search_hidden",
    "hashtag_reach":    "hashtag_ghosted",
    "reply_visibility": "reply_hidden",
}

# Penalty each failed probe subtracts from the health score. Reply hiding
# is the strongest signal (classical shadowban); search hiding is less
# definitive (can be rate-limiting).
PROBE_PENALTY: dict[ProbeKind, int] = {
    "search_reach":     15,
    "hashtag_reach":    25,
    "reply_visibility": 45,
}


@dataclass
class ProbeResult:
    probe_id:   str
    kind:       ProbeKind
    account_id: str                        # The suspect being probed
    searcher_id: str                       # The account doing the look-up
    found:      bool                       # True = visible, False = hidden
    detail:     str                        # Human-readable one-liner
    checked_at: str

    def as_dict(self) -> dict:
        return {
            "probe_id":    self.probe_id,
            "kind":        self.kind,
            "account_id":  self.account_id,
            "searcher_id": self.searcher_id,
            "found":       self.found,
            "detail":      self.detail,
            "checked_at":  self.checked_at,
        }


@dataclass
class ProbeStats:
    total_run:        int = 0
    total_found:      int = 0
    total_hidden:     int = 0
    last_run_at:      Optional[str] = None
    hidden_rate:      float = 0.0

    def as_dict(self) -> dict:
        return {
            "total_run":    self.total_run,
            "total_found":  self.total_found,
            "total_hidden": self.total_hidden,
            "last_run_at":  self.last_run_at,
            "hidden_rate":  round(self.hidden_rate, 4),
        }


# ---------------------------------------------------------------------------
# Probe scheduler
# ---------------------------------------------------------------------------


class ThreadsProbeScheduler:
    """
    Runs the three probe kinds per active Threads account on a tick.

    Never picks a searcher that is itself compromised (at_risk /
    shadowbanned) — that would poison the signal, because a shadowbanned
    searcher's "I can't see them" is really "I can't see anyone."

    Results are stored in a bounded ring per-account + a global ring for
    the UI. The health monitor pulls recent per-account results and
    converts probe failures into new flags.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        health_monitor:        Any,         # ThreadsHealthMonitor; typed loosely to avoid cycle
        tick_sec:              float = 90.0,
        results_per_account:   int = 20,
        global_ring:           int = 500,
        result_ttl_sec:        int = 24 * 3600,
    ):
        self._accounts_getter = accounts_store_getter
        self.health = health_monitor
        self.tick_sec = tick_sec
        self.result_ttl_sec = result_ttl_sec

        self._results: dict[str, deque[ProbeResult]] = {}
        self._results_per_account = results_per_account
        self._global: deque[ProbeResult] = deque(maxlen=global_ring)
        self.stats = ProbeStats()

        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="threads_probes")
        log.info("ThreadsProbeScheduler started (tick=%ss)", self.tick_sec)

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
                await self.tick()
            except Exception:
                log.exception("ThreadsProbeScheduler tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.tick_sec)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def _clean_searcher_pool(self) -> list[dict]:
        """
        Return fleet accounts healthy enough to be trusted as a searcher.
        Excludes anyone at_risk / shadowbanned / paused / retired.
        """
        pool: list[dict] = []
        for row in self._accounts_getter().values():
            if row.get("platform") != "threads":
                continue
            if row.get("status") != "active":
                continue
            h_status = self.health.status_of(row["account_id"]) \
                if self.health is not None else "healthy"
            if h_status in ("at_risk", "shadowbanned"):
                continue
            pool.append(row)
        return pool

    def _pick_searcher(self, pool: list[dict], suspect_id: str,
                        kind: ProbeKind, idx: int) -> Optional[dict]:
        """Deterministic rotation — same suspect + kind + idx → same searcher."""
        if not pool:
            return None
        seed = f"probe:{suspect_id}:{kind}:{idx}"
        h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
        # Prefer a searcher that is NOT the suspect
        candidates = [r for r in pool if r["account_id"] != suspect_id] or pool
        return candidates[h % len(candidates)]

    async def tick(self) -> dict:
        """Run one sweep: one probe of each kind per active suspect."""
        store = self._accounts_getter()
        suspects = [r for r in store.values()
                    if r.get("platform") == "threads"
                    and r.get("status") == "active"]
        pool = self._clean_searcher_pool()

        moved = {"run": 0, "hidden": 0, "skipped_no_searcher": 0}
        for i, row in enumerate(suspects):
            for kind in PROBE_KINDS:
                searcher = self._pick_searcher(pool, row["account_id"], kind, i)
                if searcher is None:
                    moved["skipped_no_searcher"] += 1
                    continue
                result = await self._dispatch_probe(row, searcher, kind)
                self._record(result)
                moved["run"] += 1
                if not result.found:
                    moved["hidden"] += 1
        self._refresh_stats()
        return moved

    # ------------------------------------------------------------------
    # Dispatcher — dev simulation; real APK hook lives here later
    # ------------------------------------------------------------------

    async def _dispatch_probe(self, suspect: dict, searcher: dict,
                               kind: ProbeKind) -> ProbeResult:
        """
        In dev: derive found=True/False from suspect's current health.
        A clean suspect is found; an at_risk or shadowbanned one is
        hidden per-kind with a probabilistic-looking (deterministic)
        schedule — the searcher always sees a suspect that the metrics
        already say is dead.

        In prod this method ADB-drives the mirror to perform the actual
        search / hashtag open / thread open and reads the result from a
        screen scrape. Nothing above this layer knows which mode we're in.
        """
        suspect_id = suspect["account_id"]
        h = self.health.for_account(suspect_id) if self.health is not None else None
        detail = f"simulated via health={'unknown' if h is None else h.status}"
        # Clean account → visible on every kind.
        # at_risk    → one kind hidden (deterministic per account_id + kind).
        # shadowbanned → all three kinds hidden.
        status = (h.status if h is not None else "healthy")
        if status == "healthy" or status == "watch":
            found = True
        elif status == "shadowbanned":
            found = False
        else:  # at_risk
            # Hide exactly one kind per suspect — "flaky" shadowban stage.
            idx = int(hashlib.sha256(f"{suspect_id}:atrisk".encode()).hexdigest()[:4], 16) % 3
            picked = PROBE_KINDS[idx]
            found = kind != picked

        return ProbeResult(
            probe_id=hashlib.sha256(
                f"{suspect_id}:{searcher['account_id']}:{kind}:"
                f"{datetime.now(timezone.utc).timestamp()}".encode()
            ).hexdigest()[:16],
            kind=kind,
            account_id=suspect_id,
            searcher_id=searcher["account_id"],
            found=found,
            detail=detail,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _record(self, r: ProbeResult) -> None:
        self._global.append(r)
        ring = self._results.setdefault(
            r.account_id, deque(maxlen=self._results_per_account))
        ring.append(r)

    def _refresh_stats(self) -> None:
        total = len(self._global)
        hidden = sum(1 for r in self._global if not r.found)
        self.stats.total_run = total
        self.stats.total_hidden = hidden
        self.stats.total_found = total - hidden
        self.stats.hidden_rate = (hidden / total) if total else 0.0
        self.stats.last_run_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def for_account(self, account_id: str,
                     limit: int = 10) -> list[dict]:
        ring = self._results.get(account_id, deque())
        return [r.as_dict() for r in list(ring)[-limit:][::-1]]

    def recent(self, limit: int = 50) -> list[dict]:
        rows: list[dict] = []
        for r in reversed(self._global):
            rows.append(r.as_dict())
            if len(rows) >= limit:
                break
        return rows

    def flags_for(self, account_id: str) -> list[str]:
        """
        Convert recent per-account probes into health flag strings.
        A probe kind is a flag if the MAJORITY of recent samples of that
        kind came back hidden — one miss isn't shadowban, a run of them is.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.result_ttl_sec)
        buckets: dict[ProbeKind, list[bool]] = {k: [] for k in PROBE_KINDS}
        for r in self._results.get(account_id, deque()):
            try:
                ts = datetime.fromisoformat(r.checked_at)
            except Exception:
                ts = None
            if ts and ts < cutoff:
                continue
            buckets[r.kind].append(r.found)
        flags: list[str] = []
        for kind, samples in buckets.items():
            if len(samples) >= 2 and samples.count(False) * 2 >= len(samples):
                flags.append(PROBE_FLAG[kind])
        return flags

    def penalty_for(self, account_id: str) -> int:
        return sum(PROBE_PENALTY[k]
                   for k in PROBE_KINDS
                   if PROBE_FLAG[k] in self.flags_for(account_id))
