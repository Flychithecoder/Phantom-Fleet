"""
Phantom Fleet Mirror bridge.

Thin async client for the local Phantom Fleet Mirroring HTTP + WS API
documented in docs/architecture/MIRROR_CONTRACT.md.

Responsibilities:
    - Discover devices from GET /devices (list + per-device fields)
    - Subscribe to WS /events and dispatch state changes to registered callbacks
    - Request / release USB ADB claims via /adb/acquire + /adb/release
    - Surface mirror health so the fleet can fall back to local adb when the
      mirror is down

Design rules (per the contract):
    - Mirror is OPTIONAL. If PHANTOM_MIRROR_URL is unset or the health check
      fails, callers must degrade to the local adb-devices code path.
    - acquire_adb() always sends a TTL — a crashed panel must never lock a
      phone forever.
    - Mirror responses are untrusted data; serial / model / android_version
      pass through `_sanitize_device()` before entering the PhoneFleet.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx

log = logging.getLogger("phantom_fleet.mirror_bridge")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


DEFAULT_MIRROR_URL = "http://127.0.0.1:8765"
# Per contract §3.1: the panel chooses TTLs; keep acquisitions short so a
# crashed action can't hold a phone > 2 minutes.
DEFAULT_ACQUIRE_TTL_SEC = 60
ACQUIRE_HOLDER_NAME = "phantom-fleet-panel"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MirrorDevice:
    """One row from GET /devices, sanitised and ready for PhoneFleet."""
    serial: str
    state: str                            # "online" | "offline" | …
    connection: str                       # "usb" | "wifi"
    model: str                            # e.g. "SM-G990U1"
    android_version: Optional[str]        # major only, e.g. "13"
    build_id: Optional[str]
    wifi_ip: Optional[str]
    mirror_slot: Optional[int]
    battery_pct: Optional[int]
    screen_on: Optional[bool]
    hw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MirrorAcquireResult:
    granted: bool
    released_until: Optional[str]         # ISO timestamp from mirror
    adb_server_port: Optional[int] = None
    reason: Optional[str] = None          # populated when granted=False
    retry_after_sec: Optional[int] = None


# ---------------------------------------------------------------------------
# Input sanitising
#
# The mirror runs on localhost but its payload is still untrusted data per
# CLAUDE.md. Enforce the field rules from CONTRACT.md §1.1.
# ---------------------------------------------------------------------------


_SERIAL_RE = re.compile(r"^[A-Za-z0-9:._\-]{1,64}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9 _\-]{1,32}$")
_ANDROID_MAJOR_RE = re.compile(r"^\d{1,2}$")


def _sanitize_device(raw: dict[str, Any]) -> Optional[MirrorDevice]:
    """Reject rows that violate the contract. Returns None if invalid."""
    serial = str(raw.get("serial", "")).strip()
    model = str(raw.get("model", "")).strip()
    if not _SERIAL_RE.match(serial):
        log.warning("mirror: rejecting device with bad serial %r", serial)
        return None
    if not _MODEL_RE.match(model):
        log.warning("mirror: rejecting device %s with bad model %r", serial, model)
        return None

    android_version = raw.get("android_version")
    if android_version is not None:
        android_version = str(android_version).strip()
        if not _ANDROID_MAJOR_RE.match(android_version):
            log.warning(
                "mirror: device %s android_version %r not a major int — "
                "coercing to None",
                serial, android_version,
            )
            android_version = None

    connection = str(raw.get("connection", "usb")).strip().lower()
    if connection not in ("usb", "wifi"):
        connection = "usb"

    def _opt_int(key: str) -> Optional[int]:
        v = raw.get(key)
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return MirrorDevice(
        serial=serial,
        state=str(raw.get("state", "unknown")).strip().lower(),
        connection=connection,
        model=model,
        android_version=android_version,
        build_id=(str(raw["build_id"]).strip() if raw.get("build_id") else None),
        wifi_ip=(str(raw["wifi_ip"]).strip() if raw.get("wifi_ip") else None),
        mirror_slot=_opt_int("mirror_slot"),
        battery_pct=_opt_int("battery_pct"),
        screen_on=(bool(raw["screen_on"]) if "screen_on" in raw else None),
        hw=raw.get("hw", {}) if isinstance(raw.get("hw"), dict) else {},
    )


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class MirrorBridge:
    """Async client for the local Phantom Fleet Mirroring API."""

    def __init__(
        self,
        base_url: str = DEFAULT_MIRROR_URL,
        *,
        holder: str = ACQUIRE_HOLDER_NAME,
        timeout_sec: float = 5.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.holder = holder
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_sec,
        )
        self._ws_task: Optional[asyncio.Task] = None
        self._listeners: list[Callable[[dict[str, Any]], Awaitable[None]]] = []
        self._available: Optional[bool] = None   # tri-state: None = not probed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """Probe the mirror. Returns True iff /health responded ok."""
        ok = await self.health()
        self._available = ok
        if ok:
            log.info("mirror: online at %s", self.base_url)
        else:
            log.warning(
                "mirror: not reachable at %s — fleet will use local adb",
                self.base_url,
            )
        return ok

    async def close(self) -> None:
        if self._ws_task is not None:
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None
        await self._client.aclose()

    @property
    def available(self) -> bool:
        """True iff the mirror responded to the last /health probe."""
        return bool(self._available)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> bool:
        try:
            r = await self._client.get("/health")
            r.raise_for_status()
            body = r.json()
            return str(body.get("status", "")).lower() == "ok"
        except (httpx.HTTPError, ValueError):
            return False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def list_devices(self) -> list[MirrorDevice]:
        """GET /devices, sanitised."""
        try:
            r = await self._client.get("/devices")
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("mirror: list_devices failed: %s", exc)
            self._available = False
            return []

        self._available = True
        rows = body.get("devices", []) if isinstance(body, dict) else []
        out: list[MirrorDevice] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            dev = _sanitize_device(raw)
            if dev is not None:
                out.append(dev)
        return out

    async def get_device(self, serial: str) -> Optional[MirrorDevice]:
        if not _SERIAL_RE.match(serial):
            return None
        try:
            r = await self._client.get(f"/devices/{serial}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            raw = r.json()
        except (httpx.HTTPError, ValueError):
            return None
        return _sanitize_device(raw) if isinstance(raw, dict) else None

    # ------------------------------------------------------------------
    # ADB claim handoff (contract §3)
    # ------------------------------------------------------------------

    async def acquire_adb(
        self,
        serial: str,
        *,
        ttl_sec: int = DEFAULT_ACQUIRE_TTL_SEC,
        reason: str = "",
    ) -> MirrorAcquireResult:
        if not _SERIAL_RE.match(serial):
            return MirrorAcquireResult(granted=False, released_until=None,
                                       reason="invalid_serial")
        # Cap TTL — hard rule, so a buggy caller can't park a phone > 5 min.
        ttl_sec = max(1, min(ttl_sec, 300))
        try:
            r = await self._client.post(
                f"/devices/{serial}/adb/acquire",
                json={"holder": self.holder, "ttl_sec": ttl_sec, "reason": reason},
            )
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("mirror: acquire_adb(%s) failed: %s", serial, exc)
            return MirrorAcquireResult(granted=False, released_until=None,
                                       reason="mirror_unreachable")
        return MirrorAcquireResult(
            granted=bool(body.get("granted")),
            released_until=body.get("released_until"),
            adb_server_port=body.get("adb_server_port"),
            reason=body.get("reason"),
            retry_after_sec=body.get("retry_after_sec"),
        )

    async def release_adb(self, serial: str) -> bool:
        if not _SERIAL_RE.match(serial):
            return False
        try:
            r = await self._client.post(
                f"/devices/{serial}/adb/release",
                json={"holder": self.holder},
            )
            r.raise_for_status()
            return bool(r.json().get("released"))
        except (httpx.HTTPError, ValueError):
            return False

    @contextlib.asynccontextmanager
    async def claim_adb(
        self,
        serial: str,
        *,
        ttl_sec: int = DEFAULT_ACQUIRE_TTL_SEC,
        reason: str = "",
    ) -> AsyncIterator[MirrorAcquireResult]:
        """
        Scoped USB ADB claim. Yields the acquire result; caller MUST check
        `.granted` before issuing ADB commands.

        On exit, always issues /release. A denied acquire still yields so the
        caller can report `.reason` / `.retry_after_sec` without another try.

        If the mirror is not available at all, yields a granted=True result so
        the caller can keep running on local adb — the bridge is optional per
        CONTRACT.md §9.
        """
        if not self.available:
            # Mirror off / unreachable: we aren't fighting it for USB, so just
            # hand the caller a synthetic grant and do nothing on release.
            yield MirrorAcquireResult(
                granted=True, released_until=None, reason="mirror_unavailable",
            )
            return

        result = await self.acquire_adb(serial, ttl_sec=ttl_sec, reason=reason)
        try:
            yield result
        finally:
            if result.granted:
                await self.release_adb(serial)

    # ------------------------------------------------------------------
    # Event stream (contract §1.3)
    # ------------------------------------------------------------------

    def on_event(
        self,
        callback: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Register a listener for events delivered on WS /events."""
        self._listeners.append(callback)

    async def _ws_loop(self) -> None:
        """
        Subscribe to WS /events and dispatch each JSON line to listeners.
        Reconnects with exponential backoff; one malformed line is logged
        and skipped rather than killing the whole loop.
        """
        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError:
            log.warning(
                "mirror: `websockets` not installed; skipping event stream. "
                "pip install websockets to enable live updates.",
            )
            return

        ws_url = self.base_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        ) + "/events"
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(ws_url) as ws:  # type: ignore[attr-defined]
                    log.info("mirror: WS connected %s", ws_url)
                    backoff = 1.0
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            log.debug("mirror: dropped malformed WS frame")
                            continue
                        if not isinstance(event, dict):
                            continue
                        await self._dispatch(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("mirror: WS loop error (%s), retry in %.1fs",
                            exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _dispatch(self, event: dict[str, Any]) -> None:
        for cb in list(self._listeners):
            try:
                await cb(event)
            except Exception:
                log.exception("mirror: event listener raised")

    def start_event_stream(self) -> None:
        """Kick off the WS /events subscription (idempotent)."""
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(
                self._ws_loop(), name="mirror_bridge_ws",
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def mirror_bridge_from_env() -> Optional[MirrorBridge]:
    """
    Build a MirrorBridge from PHANTOM_MIRROR_URL, or return None when the env
    var is empty / explicitly disabled. The panel then falls back to local
    adb discovery.
    """
    url = os.environ.get("PHANTOM_MIRROR_URL", "").strip()
    if not url or url.lower() in ("0", "false", "off", "disabled"):
        return None
    return MirrorBridge(base_url=url)
