"""
Threads executor — drains the pending action queue through the mirror
bridge → companion APK primitives.

Lifecycle:
    executor = ThreadsExecutor(fleet, mirror, queue_getter)
    await executor.start()
    ...
    await executor.stop()

The executor is a single background task. It loops the shared queue, picks
the next entry whose scheduled_at has arrived, claims ADB on the target
phone via the mirror bridge, dispatches the action, releases the claim,
then sleeps for a LogNormal-sampled inter-action delay. All distributions
are deterministic per CLAUDE.md §Distribution discipline — nothing uses
`random.uniform`.

In this build the companion APK dispatch is a STUB: we log the action and
write a `dispatched_at` + `result` field on the queue entry. When the real
APK ships, swap the `_dispatch_via_apk` body — the surface above does not
change.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from . import threads as threads_mod
from .threads_funnel import FunnelEvent, ThreadsFunnelTracker

log = logging.getLogger("phantom_fleet.platforms.threads_executor")


# ---------------------------------------------------------------------------
# LogNormal timing — inter-action delay sampler
# ---------------------------------------------------------------------------

# Mean delay between two Threads actions on the SAME account, by kind. Short
# for interactions (scroll + tap), longer for posts (compose + review).
# Numbers measured from Onimator's logs; in seconds.
_DELAY_MEAN = {"follow": 45.0, "reply": 70.0, "repost": 25.0, "post": 180.0}
_DELAY_SIGMA = {"follow": 0.35, "reply": 0.40, "repost": 0.30, "post": 0.50}


def _seed_delay(entry_id: str, kind: str) -> float:
    digest = hashlib.sha256(f"delay:{entry_id}:{kind}".encode()).hexdigest()
    return int(digest[:16], 16) / 0xFFFF_FFFF_FFFF_FFFF


def _inv_normal(u: float) -> float:
    """Abramowitz-Stegun 26.2.23 inverse-normal (same as threads.py)."""
    if u <= 0 or u >= 1:
        u = 0.5
    t = math.sqrt(-2.0 * math.log(min(u, 1 - u)))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
    return -z if u > 0.5 else z


def sample_delay(entry_id: str, kind: str) -> float:
    """
    LogNormal-sampled seconds until this action fires after the previous one
    on the same account. Deterministic on entry_id so a stop/start cycle
    doesn't shuffle the plan.
    """
    mean = _DELAY_MEAN.get(kind, 60.0)
    sigma = _DELAY_SIGMA.get(kind, 0.4)
    u = _seed_delay(entry_id, kind)
    z = _inv_normal(u)
    mu = math.log(mean) - 0.5 * sigma * sigma
    secs = math.exp(mu + sigma * z)
    # Clamp between 10s (never hammer) and 15min (never stall).
    return max(10.0, min(secs, 900.0))


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


@dataclass
class ExecutorStats:
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    dispatched: int = 0
    failed:     int = 0
    last_error: Optional[str] = None


class ThreadsExecutor:
    """
    Background loop that drains queued Threads actions through the mirror
    bridge. One account at a time per device (ADB claim is single-holder).
    """

    def __init__(
        self,
        fleet,
        mirror,
        queue_getter: Callable[[], list[dict]],
        funnel: Optional[ThreadsFunnelTracker] = None,
        tick_sec: float = 2.0,
    ):
        self.fleet = fleet
        self.mirror = mirror
        self._queue_getter = queue_getter
        self.funnel = funnel
        self.tick_sec = tick_sec
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        # account_id → next-eligible monotonic timestamp
        self._next_eligible: dict[str, float] = {}
        self.stats = ExecutorStats()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self.stats.started_at = datetime.now(timezone.utc).isoformat()
        self.stats.stopped_at = None
        self._task = asyncio.create_task(self._loop(), name="threads_executor")
        log.info("ThreadsExecutor started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None
        self.stats.stopped_at = datetime.now(timezone.utc).isoformat()
        log.info("ThreadsExecutor stopped")

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await self._tick()
                except Exception as exc:
                    log.exception("ThreadsExecutor tick failed")
                    self.stats.failed += 1
                    self.stats.last_error = str(exc)
                try:
                    await asyncio.wait_for(self._stop_event.wait(),
                                           timeout=self.tick_sec)
                except asyncio.TimeoutError:
                    pass
        finally:
            log.info("ThreadsExecutor loop exited")

    async def _tick(self) -> None:
        queue = self._queue_getter()
        now = asyncio.get_running_loop().time()
        # Find the first queued entry whose account is eligible.
        for entry in queue:
            if entry.get("status") != "queued":
                continue
            acc = entry["account_id"]
            if self._next_eligible.get(acc, 0.0) > now:
                continue
            await self._dispatch(entry)
            delay = sample_delay(entry["action_id"], entry["kind"])
            self._next_eligible[acc] = now + delay
            return   # only one action per tick keeps timing honest

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, entry: dict) -> None:
        # Resolve phone for the account from the main accounts store.
        serial = self._phone_serial_for(entry["account_id"])
        if not serial:
            entry["status"] = "failed"
            entry["error"] = "no phone_serial for account"
            self.stats.failed += 1
            return

        try:
            if self.mirror is not None and getattr(self.mirror, "available", False):
                async with self.mirror.claim_adb(
                    serial, ttl_sec=30, reason="threads_executor",
                ):
                    await self._dispatch_via_apk(serial, entry)
            else:
                await self._dispatch_via_apk(serial, entry)
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            self.stats.failed += 1
            log.warning("Threads dispatch failed for %s: %s",
                        entry["account_id"], exc)
            return

        entry["status"] = "dispatched"
        entry["dispatched_at"] = datetime.now(timezone.utc).isoformat()
        entry["phone_serial"] = serial
        self.stats.dispatched += 1

        # Fire a funnel event for post/reply — these are the funnel entry
        # points. follow/repost don't count as funnel-top events.
        kind_to_funnel: dict[str, str] = {
            "reply": "reply_posted",
            "post":  "post_posted",
        }
        funnel_kind = kind_to_funnel.get(entry["kind"])
        if funnel_kind and self.funnel is not None:
            ig_parent = self._ig_parent_for(entry["account_id"])
            self.funnel.record(FunnelEvent(
                kind=funnel_kind,                    # type: ignore[arg-type]
                threads_account_id=entry["account_id"],
                ig_account_id=ig_parent,
                action_id=entry["action_id"],
                target=entry.get("target", ""),
            ))

    def _ig_parent_for(self, threads_account_id: str) -> Optional[str]:
        from ..api.routes.accounts import _store
        row = _store().get(threads_account_id)
        return row.get("ig_account_id") if row else None

    def _phone_serial_for(self, account_id: str) -> Optional[str]:
        """Look up the phone an account is pinned to via the accounts store."""
        # Import here to avoid circular imports with the API layer.
        from ..api.routes.accounts import _store
        row = _store().get(account_id)
        if row is None:
            return None
        return row.get("phone_serial")

    async def _dispatch_via_apk(self, serial: str, entry: dict) -> None:
        """
        Dispatch one Threads action to the companion APK.

        STUB: the APK isn't live yet, so we just log the dispatch. The real
        implementation will POST the action to the APK's local HTTP socket
        (adb forward tcp:… → tcp:8089) with the routed primitive name.
        """
        route = entry.get("route", threads_mod.ACTION_ROUTES[entry["kind"]])
        log.info("[threads] %s → %s on %s (target=%s)",
                 route, entry["account_id"], serial, entry.get("target", ""))
        # Pretend the APK took a moment to tap and type.
        await asyncio.sleep(0.05)
