"""
Instagram active shadowban probes.

Mirrors the Threads probe scheduler for IG-specific surfaces:

    handle_search    — searcher queries "@<username>", expects to see the
                       suspect. Missing → search-hidden.
    hashtag_page     — suspect posts with a probe hashtag, searcher opens
                       the hashtag feed, expects the post. Missing →
                       hashtag-ghosted.
    explore_surface  — searcher opens the explore feed on a persona that
                       follows the suspect. Missing after enough rotations
                       → explore-suppressed.

Searcher pool excludes any IG account that is itself at_risk or
shadowbanned (otherwise its "I can't see them" is really "I can't see
anyone"). Deterministic rotation via SHA256, no random.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Optional

log = logging.getLogger("phantom_fleet.platforms.instagram_probes")

IGProbeKind = Literal["handle_search", "hashtag_page", "explore_surface"]

IG_PROBE_KINDS: tuple[IGProbeKind, ...] = (
    "handle_search", "hashtag_page", "explore_surface",
)

IG_PROBE_FLAG: dict[IGProbeKind, str] = {
    "handle_search":   "ig_search_hidden",
    "hashtag_page":    "ig_hashtag_ghosted",
    "explore_surface": "ig_explore_suppressed",
}

IG_PROBE_PENALTY: dict[IGProbeKind, int] = {
    "handle_search":   20,
    "hashtag_page":    30,
    "explore_surface": 45,
}


@dataclass
class IGProbeResult:
    probe_id:    str
    kind:        IGProbeKind
    account_id:  str
    searcher_id: str
    found:       bool
    detail:      str
    checked_at:  str

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
class IGProbeStats:
    total_run:    int = 0
    total_found:  int = 0
    total_hidden: int = 0
    last_run_at:  Optional[str] = None
    hidden_rate:  float = 0.0

    def as_dict(self) -> dict:
        return {
            "total_run":    self.total_run,
            "total_found":  self.total_found,
            "total_hidden": self.total_hidden,
            "last_run_at":  self.last_run_at,
            "hidden_rate":  round(self.hidden_rate, 4),
        }


class InstagramProbeScheduler:
    """Active shadowban probes for IG accounts."""

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        health_monitor:        Any,
        tick_sec:              float = 120.0,
        results_per_account:   int = 20,
        global_ring:           int = 500,
        result_ttl_sec:        int = 24 * 3600,
    ):
        self._accounts_getter = accounts_store_getter
        self.health = health_monitor
        self.tick_sec = tick_sec
        self.result_ttl_sec = result_ttl_sec

        self._results: dict[str, deque[IGProbeResult]] = {}
        self._results_per_account = results_per_account
        self._global: deque[IGProbeResult] = deque(maxlen=global_ring)
        self.stats = IGProbeStats()

        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="instagram_probes")
        log.info("InstagramProbeScheduler started (tick=%ss)", self.tick_sec)

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
                log.exception("InstagramProbeScheduler tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.tick_sec)
            except asyncio.TimeoutError:
                pass

    def _clean_searcher_pool(self) -> list[dict]:
        pool: list[dict] = []
        for row in self._accounts_getter().values():
            if row.get("platform") != "instagram" or row.get("status") != "active":
                continue
            st = (self.health.status_of(row["account_id"])
                  if self.health is not None else "healthy")
            if st in ("at_risk", "shadowbanned"):
                continue
            pool.append(row)
        return pool

    def _pick_searcher(self, pool: list[dict], suspect_id: str,
                        kind: IGProbeKind, idx: int) -> Optional[dict]:
        if not pool:
            return None
        seed = f"ig-probe:{suspect_id}:{kind}:{idx}"
        h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
        candidates = [r for r in pool if r["account_id"] != suspect_id] or pool
        return candidates[h % len(candidates)]

    async def tick(self) -> dict:
        store = self._accounts_getter()
        suspects = [r for r in store.values()
                    if r.get("platform") == "instagram"
                    and r.get("status") == "active"]
        pool = self._clean_searcher_pool()

        moved = {"run": 0, "hidden": 0, "skipped_no_searcher": 0}
        for i, row in enumerate(suspects):
            for kind in IG_PROBE_KINDS:
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

    async def _dispatch_probe(self, suspect: dict, searcher: dict,
                               kind: IGProbeKind) -> IGProbeResult:
        """Dev simulation; real APK hook lives here later."""
        suspect_id = suspect["account_id"]
        h = self.health.for_account(suspect_id) if self.health is not None else None
        status = h.status if h is not None else "healthy"
        detail = f"simulated via health={status}"
        if status in ("healthy", "watch"):
            found = True
        elif status == "shadowbanned":
            found = False
        else:  # at_risk — one kind hidden
            idx = int(hashlib.sha256(f"{suspect_id}:ig-atrisk".encode()).hexdigest()[:4], 16) % 3
            found = kind != IG_PROBE_KINDS[idx]

        return IGProbeResult(
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

    def _record(self, r: IGProbeResult) -> None:
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

    # API

    def for_account(self, account_id: str, limit: int = 10) -> list[dict]:
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
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.result_ttl_sec)
        buckets: dict[IGProbeKind, list[bool]] = {k: [] for k in IG_PROBE_KINDS}
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
                flags.append(IG_PROBE_FLAG[kind])
        return flags

    def penalty_for(self, account_id: str) -> int:
        return sum(IG_PROBE_PENALTY[k]
                   for k in IG_PROBE_KINDS
                   if IG_PROBE_FLAG[k] in self.flags_for(account_id))
