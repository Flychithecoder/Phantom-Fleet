"""
Instagram executor — drains the IG queue through the mirror bridge →
companion APK primitives.

Mirror of ThreadsExecutor, applied to IG primitives (follow / like /
story_view / post). ADB is claimed per-phone (single-holder), and
inter-action delays sample a LogNormal that is deterministic on the
entry's action_id, so a stop/start cycle doesn't shuffle timing.

The companion APK dispatch is a STUB today — we log the call and mark
the queue entry dispatched. When the real APK lands, swap
`_dispatch_via_apk`; the surface above does not change.

Funnel wiring: a successful "post" dispatch fires an
InstagramFunnelTracker `post_posted` event. Other kinds don't register
as funnel-top events.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from . import instagram as ig_mod
from . import instagram_diurnal as ig_diurnal
from .instagram_funnel import IGFunnelEvent, InstagramFunnelTracker

_DIURNAL_SKIP_THRESHOLD = 0.10

log = logging.getLogger("phantom_fleet.platforms.instagram_executor")


# ---------------------------------------------------------------------------
# LogNormal timing — inter-action delay sampler (IG primitive means)
# ---------------------------------------------------------------------------

# Measured from real IG usage: fast taps (like, story_view), slower on
# follow (profile load), long on post (compose + review).
_DELAY_MEAN  = {"follow": 60.0, "like": 18.0, "story_view": 12.0, "post": 240.0}
_DELAY_SIGMA = {"follow": 0.35, "like": 0.30, "story_view": 0.35, "post": 0.50}


def _seed_delay(entry_id: str, kind: str) -> float:
    digest = hashlib.sha256(f"ig-delay:{entry_id}:{kind}".encode()).hexdigest()
    return int(digest[:16], 16) / 0xFFFF_FFFF_FFFF_FFFF


def _inv_normal(u: float) -> float:
    """Abramowitz-Stegun 26.2.23 inverse-normal (matches threads.py)."""
    if u <= 0 or u >= 1:
        u = 0.5
    t = math.sqrt(-2.0 * math.log(min(u, 1 - u)))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
    return -z if u > 0.5 else z


def sample_delay(entry_id: str, kind: str) -> float:
    """
    LogNormal-sampled seconds until the account's next IG action. Clamped
    to [5s, 20min] so a bad seed never hammers or stalls.
    """
    mean = _DELAY_MEAN.get(kind, 30.0)
    sigma = _DELAY_SIGMA.get(kind, 0.4)
    u = _seed_delay(entry_id, kind)
    z = _inv_normal(u)
    mu = math.log(mean) - 0.5 * sigma * sigma
    secs = math.exp(mu + sigma * z)
    return max(5.0, min(secs, 1200.0))


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


@dataclass
class IGExecutorStats:
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    dispatched: int = 0
    failed:     int = 0
    by_kind:    dict = None  # type: ignore[assignment]
    diurnal_skipped: int = 0
    session_skipped: int = 0
    last_error: Optional[str] = None
    last_dispatch_at: Optional[str] = None

    def __post_init__(self):
        if self.by_kind is None:
            self.by_kind = {"follow": 0, "like": 0, "story_view": 0, "post": 0}


class InstagramExecutor:
    """
    Background loop that drains queued IG actions through the mirror
    bridge. One action per tick keeps the LogNormal-sampled inter-action
    cadence honest.
    """

    def __init__(
        self,
        fleet,
        mirror,
        queue_getter: Callable[[], list[dict]],
        funnel: Optional[InstagramFunnelTracker] = None,
        session: Optional[object] = None,
        tick_sec: float = 2.0,
    ):
        self.fleet = fleet
        self.mirror = mirror
        self._queue_getter = queue_getter
        self.funnel = funnel
        self.session = session
        self.tick_sec = tick_sec
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._next_eligible: dict[str, float] = {}
        self.stats = IGExecutorStats()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self.stats.started_at = datetime.now(timezone.utc).isoformat()
        self.stats.stopped_at = None
        self._task = asyncio.create_task(self._loop(), name="instagram_executor")
        log.info("InstagramExecutor started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None
        self.stats.stopped_at = datetime.now(timezone.utc).isoformat()
        log.info("InstagramExecutor stopped")

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
                    log.exception("InstagramExecutor tick failed")
                    self.stats.failed += 1
                    self.stats.last_error = str(exc)
                try:
                    await asyncio.wait_for(self._stop_event.wait(),
                                           timeout=self.tick_sec)
                except asyncio.TimeoutError:
                    pass
        finally:
            log.info("InstagramExecutor loop exited")

    async def _tick(self) -> None:
        queue = self._queue_getter()
        now = asyncio.get_running_loop().time()
        for entry in queue:
            if entry.get("status") != "queued":
                continue
            acc = entry["account_id"]
            if self._next_eligible.get(acc, 0.0) > now:
                continue
            # Diurnal gate: if the account's local hour is in sleep range,
            # defer this entry (don't mark failed — leave it queued until
            # the hour rolls over). Stamp the entry so the UI can see it.
            from ..api.routes.accounts import _store
            row = _store().get(acc, {}) or {}
            w = ig_diurnal.weight_now(acc, row)
            if w < _DIURNAL_SKIP_THRESHOLD:
                entry["diurnal_weight"] = round(w, 3)
                self.stats.diurnal_skipped += 1
                self._next_eligible[acc] = now + 300  # recheck in 5 min
                return
            # Session gate — if the session manager is wired and the account
            # is not dispatchable (expired, 2fa pending, locked), skip.
            if self.session is not None and not self.session.is_dispatchable(acc):
                entry["session_skip"] = True
                self.stats.session_skipped += 1
                self._next_eligible[acc] = now + 600
                return
            await self._dispatch(entry)
            delay = sample_delay(entry["action_id"], entry["kind"])
            self._next_eligible[acc] = now + delay
            return

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, entry: dict) -> None:
        serial = self._phone_serial_for(entry["account_id"])
        if not serial:
            entry["status"] = "failed"
            entry["error"] = "no phone_serial for account"
            self.stats.failed += 1
            return

        try:
            if self.mirror is not None and getattr(self.mirror, "available", False):
                async with self.mirror.claim_adb(
                    serial, ttl_sec=30, reason="instagram_executor",
                ):
                    await self._dispatch_via_apk(serial, entry)
            else:
                await self._dispatch_via_apk(serial, entry)
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            self.stats.failed += 1
            log.warning("IG dispatch failed for %s: %s",
                        entry["account_id"], exc)
            return

        entry["status"] = "dispatched"
        entry["dispatched_at"] = datetime.now(timezone.utc).isoformat()
        entry["phone_serial"] = serial
        self.stats.dispatched += 1
        self.stats.by_kind[entry["kind"]] = self.stats.by_kind.get(entry["kind"], 0) + 1
        self.stats.last_dispatch_at = entry["dispatched_at"]

        # post → funnel. follow / like / story_view aren't funnel-top events
        # (impressions and profile_views come from the executor on the
        # viewing side, not the actor side).
        if entry["kind"] == "post" and self.funnel is not None:
            self.funnel.record(IGFunnelEvent(
                kind="post_posted",
                ig_account_id=entry["account_id"],
                post_id=entry["action_id"],
                target=entry.get("target", ""),
            ))

    def _phone_serial_for(self, account_id: str) -> Optional[str]:
        from ..api.routes.accounts import _store
        row = _store().get(account_id)
        if row is None:
            return None
        return row.get("phone_serial")

    async def _dispatch_via_apk(self, serial: str, entry: dict) -> None:
        """
        STUB: companion APK isn't live yet. The real build POSTs to the
        APK's local HTTP socket (adb forward → tcp:8089) with the routed
        primitive name; everything above stays the same.
        """
        route = entry.get("route", ig_mod.ACTION_ROUTES[entry["kind"]])
        log.info("[instagram] %s → %s on %s (target=%s)",
                 route, entry["account_id"], serial, entry.get("target", ""))
        await asyncio.sleep(0.05)

    def status(self) -> dict:
        return {
            "running":         self.running(),
            "tick_sec":        self.tick_sec,
            "started_at":      self.stats.started_at,
            "stopped_at":      self.stats.stopped_at,
            "dispatched":      self.stats.dispatched,
            "failed":          self.stats.failed,
            "by_kind":         dict(self.stats.by_kind),
            "diurnal_skipped": self.stats.diurnal_skipped,
            "diurnal_threshold": _DIURNAL_SKIP_THRESHOLD,
            "session_skipped": self.stats.session_skipped,
            "last_error":      self.stats.last_error,
            "last_dispatch_at": self.stats.last_dispatch_at,
        }
