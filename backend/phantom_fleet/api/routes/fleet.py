"""
Fleet routes — phone hardware layer.

Endpoints:
    GET  /api/fleet               — all phones with state + summary counts
    GET  /api/fleet/{serial}      — single phone detail (state, clones, proxy)
    POST /api/fleet/scan          — trigger `adb devices` scan
    POST /api/fleet/{serial}/verify-proxy  — verify proxy on one phone
    POST /api/fleet/verify-all    — verify proxies on all phones concurrently
    POST /api/fleet/{serial}/install-apk  — sideload companion APK via ADB
    GET  /api/fleet/{serial}/apk-health   — ping APK /health endpoint
    POST /api/fleet/start-warming         — create daily plans + start WarmingOrchestrator

The PhoneFleet singleton lives on app.state.ctx.fleet and is shared across
all requests. Phones are registered at scan time; all subsequent reads are
in-memory dictionary lookups (no DB needed for live state).

Proxy gate: these routes surface proxy state but NEVER dispatch platform
actions. That safety boundary lives in the agent mesh.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ...core.phone_controller import (
    ADBCommandFailed,
    PhoneFleet,
    PhoneController,
    PhoneState,
    CloneSlot,
    _run_adb,
)

log = logging.getLogger("phantom_fleet.api.fleet")

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CloneSlotOut(BaseModel):
    serial: str
    package_name: str
    clone_index: int
    platform: str
    account_id: Optional[str]
    active: bool


class PhoneOut(BaseModel):
    serial: str
    state: str
    proxy_host: str
    proxy_port: int
    clone_count: int
    clones: list[CloneSlotOut]
    last_error: Optional[str]


class FleetSummaryOut(BaseModel):
    total: int
    proxy_ready: int
    online: int
    offline: int
    busy: int
    error: int
    phones: list[PhoneOut]


class ScanResultOut(BaseModel):
    discovered: int
    phones: list[PhoneOut]


class ProxyVerifyOut(BaseModel):
    serial: str
    verified: bool
    state: str


class VerifyAllOut(BaseModel):
    results: dict[str, bool]
    proxy_ready_count: int


class InstallAPKOut(BaseModel):
    serial: str
    installed: bool
    message: str


class APKHealthOut(BaseModel):
    serial: str
    alive: bool
    version: Optional[str]


class StartWarmingOut(BaseModel):
    started: bool
    accounts: int
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _phone_out(p: PhoneController) -> PhoneOut:
    return PhoneOut(
        serial=p.serial,
        state=p.state.value,
        proxy_host=p.proxy_host,
        proxy_port=p.proxy_port,
        clone_count=len(p.clones),
        clones=[
            CloneSlotOut(
                serial=c.serial,
                package_name=c.package_name,
                clone_index=c.clone_index,
                platform=c.platform,
                account_id=c.account_id,
                active=c.active,
            )
            for c in p.clones
        ],
        last_error=p._last_error,
    )


def _get_fleet(request: Request) -> PhoneFleet:
    return request.app.state.ctx.fleet


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=FleetSummaryOut)
async def list_fleet(request: Request) -> FleetSummaryOut:
    """Return all registered phones with their current state."""
    fleet = _get_fleet(request)
    summary = fleet.status_summary()
    phones = [_phone_out(p) for p in fleet.all_phones()]
    return FleetSummaryOut(
        total=summary["total"],
        proxy_ready=summary["proxy_ready"],
        online=summary["online"],
        offline=summary["offline"],
        busy=summary["busy"],
        error=summary["error"],
        phones=phones,
    )


@router.get("/{serial}", response_model=PhoneOut)
async def get_phone(serial: str, request: Request) -> PhoneOut:
    """Return detail for a single phone."""
    fleet = _get_fleet(request)
    phone = fleet.get(serial)
    if phone is None:
        raise HTTPException(status_code=404, detail=f"Phone {serial!r} not registered")
    return _phone_out(phone)


@router.post("/scan", response_model=ScanResultOut)
async def scan_fleet(request: Request) -> ScanResultOut:
    """
    Trigger `adb devices` scan. Registers newly discovered phones.
    Safe to call repeatedly — existing phones are updated, not duplicated.
    Returns the full set of discovered phones (not only new ones).
    """
    fleet = _get_fleet(request)
    try:
        discovered = await fleet.scan()
    except Exception as exc:
        log.exception("adb scan failed")
        raise HTTPException(status_code=502, detail=f"ADB scan failed: {exc}") from exc

    return ScanResultOut(
        discovered=len(discovered),
        phones=[_phone_out(p) for p in discovered],
    )


@router.post("/{serial}/verify-proxy", response_model=ProxyVerifyOut)
async def verify_proxy(serial: str, request: Request) -> ProxyVerifyOut:
    """
    Run verify_proxy() on a single phone.
    State transitions: ONLINE → PROXY_READY (if proxy active) or stays ONLINE.
    """
    fleet = _get_fleet(request)
    phone = fleet.get(serial)
    if phone is None:
        raise HTTPException(status_code=404, detail=f"Phone {serial!r} not registered")

    try:
        verified = await phone.verify_proxy()
    except Exception as exc:
        log.exception("verify_proxy failed for %s", serial)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Persist proxy_verified=True to DB if pool is available
    if verified and phone.state == PhoneState.PROXY_READY:
        try:
            db_pool = getattr(request.app.state, "db_pool", None)
            if db_pool:
                from ...db.repositories.phones import PhoneRepository
                repo = PhoneRepository(db_pool)
                await repo.update_proxy_status(serial, verified=True)
        except Exception:
            pass  # DB update is best-effort; in-memory state is authoritative

    return ProxyVerifyOut(serial=serial, verified=verified, state=phone.state.value)


@router.post("/verify-all", response_model=VerifyAllOut)
async def verify_all(request: Request) -> VerifyAllOut:
    """
    Verify proxies on all registered phones concurrently.
    Returns per-serial bool map + count of phones now in PROXY_READY state.
    """
    fleet = _get_fleet(request)
    try:
        results = await fleet.verify_all_proxies()
    except Exception as exc:
        log.exception("verify_all_proxies failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    proxy_ready_count = sum(1 for ok in results.values() if ok)
    return VerifyAllOut(results=results, proxy_ready_count=proxy_ready_count)


@router.post("/{serial}/install-apk", response_model=InstallAPKOut)
async def install_apk(serial: str, request: Request) -> InstallAPKOut:
    """
    Sideload the Phantom Fleet companion APK onto a device via ADB.

    Runs: adb -s {serial} install -r {PHANTOM_APK_PATH}

    Env var PHANTOM_APK_PATH must be set to the absolute host path of
    phantom_fleet.apk. Returns 422 if the env var is not configured.

    The phone does not need to be in PROXY_READY state for APK installation —
    this runs before proxy setup in the onboarding wizard.
    """
    fleet = _get_fleet(request)
    phone = fleet.get(serial)
    if phone is None:
        raise HTTPException(status_code=404, detail=f"Phone {serial!r} not registered")

    apk_path = os.environ.get("PHANTOM_APK_PATH", "")
    if not apk_path:
        raise HTTPException(
            status_code=422,
            detail="PHANTOM_APK_PATH environment variable is not set.",
        )
    if not os.path.exists(apk_path):
        raise HTTPException(
            status_code=422,
            detail=f"APK not found at PHANTOM_APK_PATH={apk_path!r}",
        )

    try:
        result = await _run_adb("-s", serial, "install", "-r", apk_path, timeout=120)
        # adb install writes "Success" to stdout on success
        installed = "success" in result.lower()
        message = result.strip() or "APK install completed."
    except ADBCommandFailed as exc:
        log.exception("APK install failed for %s", serial)
        raise HTTPException(status_code=502, detail=f"ADB install failed: {exc}") from exc
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="APK install timed out after 120 s")

    log.info("APK install on %s: installed=%s", serial, installed)
    return InstallAPKOut(serial=serial, installed=installed, message=message)


@router.get("/{serial}/apk-health", response_model=APKHealthOut)
async def apk_health(serial: str, request: Request) -> APKHealthOut:
    """
    Verify that the Companion APK is running and responding on the phone.

    Uses ADB to call GET http://127.0.0.1:8090/health on the device itself
    (via `adb shell curl`). The APK's local HTTP server listens on port 8090.

    Returns alive=True if the APK responds with a 200 body containing a
    "version" key. alive=False if the APK is not running or unreachable.
    """
    fleet = _get_fleet(request)
    phone = fleet.get(serial)
    if phone is None:
        raise HTTPException(status_code=404, detail=f"Phone {serial!r} not registered")

    try:
        result = await phone._adb(
            "shell", "curl", "-s", "--max-time", "5",
            "http://127.0.0.1:8090/health",
            timeout=10,
        )
        body = result.strip()
        import json as _json
        try:
            data = _json.loads(body)
            alive = True
            version = data.get("version")
        except (_json.JSONDecodeError, ValueError):
            # APK responded but with non-JSON (unlikely) — still alive
            alive = bool(body)
            version = None
    except (ADBCommandFailed, asyncio.TimeoutError):
        alive = False
        version = None

    return APKHealthOut(serial=serial, alive=alive, version=version)


@router.post("/{serial}/extract-device-info")
async def extract_device_info(serial: str, request: Request) -> dict:
    """
    Read hardware identifiers from a phone and cache them on the PhoneController.

    Runs: get_device_info() + get_advertising_id() on the phone.
    Results are cached on phone.metadata so start-warming can build real
    PlatformHeaders without extra ADB calls.

    Must be called AFTER /verify-proxy (proxy must be PROXY_READY).
    Typical operator flow:
        1. POST /api/fleet/scan
        2. POST /api/fleet/{serial}/verify-proxy
        3. POST /api/fleet/{serial}/extract-device-info   ← this endpoint
        4. POST /api/fleet/start-warming
    """
    fleet = _get_fleet(request)
    phone = fleet.get(serial)
    if phone is None:
        raise HTTPException(status_code=404, detail=f"Phone {serial!r} not registered")

    try:
        info = await phone.get_device_info()
        gaid = await phone.get_advertising_id()
        if gaid:
            info["advertising_id"] = gaid
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Device info extraction failed: {exc}") from exc

    return {"serial": serial, "device_info": info}


@router.post("/heartbeat")
async def phone_heartbeat(request: Request) -> dict:
    """
    Register / refresh a phone's WiFi IP in the phone_heartbeats table.

    Called by the Companion APK on startup and every 5 minutes.
    The EngagementExecutor reads wifi_ip from this table to reach phones
    directly over WiFi (no ADB port-forwarding needed).

    Body: { "serial": str, "wifi_ip": str, "apk_version"?: str, "companion_port"?: int }
    """
    body = await request.json()
    serial: str = body.get("serial", "").strip()
    wifi_ip: str = body.get("wifi_ip", "").strip()
    if not serial or not wifi_ip:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="serial and wifi_ip are required")

    apk_version: str = body.get("apk_version") or ""
    companion_port: int = int(body.get("companion_port") or 8090)

    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO phone_heartbeats
                        (serial, wifi_ip, apk_version, last_seen_at, companion_port)
                    VALUES ($1, $2, $3, now(), $4)
                    ON CONFLICT (serial)
                    DO UPDATE SET
                        wifi_ip        = EXCLUDED.wifi_ip,
                        apk_version    = EXCLUDED.apk_version,
                        last_seen_at   = now(),
                        companion_port = EXCLUDED.companion_port
                    """,
                    serial, wifi_ip, apk_version or None, companion_port,
                )
                # Also update phones table if it exists
                await conn.execute(
                    "UPDATE phones SET wifi_ip = $1 WHERE serial = $2",
                    wifi_ip, serial,
                )
        except Exception as exc:
            log.warning("heartbeat DB write failed for %s: %s", serial, exc)

    log.info("Heartbeat: serial=%s wifi_ip=%s apk=%s", serial, wifi_ip, apk_version or "unknown")
    return {"serial": serial, "wifi_ip": wifi_ip, "registered_at": __import__("datetime").datetime.utcnow().isoformat() + "Z"}


@router.get("/{serial}/accounts")
async def list_phone_accounts(serial: str, request: Request) -> dict:
    """
    Return all accounts assigned to this phone with today's action counts.

    Used by the frontend fleet/[serial]/page.tsx to populate the account table.
    Reads from the DB accounts + daily_action_counts tables.
    Falls back to the in-memory store when DB is unavailable.
    """
    from datetime import datetime, timezone

    db_pool = getattr(request.app.state, "db_pool", None)

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                acc_rows = await conn.fetch(
                    """
                    SELECT
                        a.id, a.username, a.platform, a.clone_package,
                        a.status, a.start_hour, a.end_hour, a.tags,
                        a.follow_enabled,   a.follow_daily_max,
                        a.follow_min_delay, a.follow_max_delay,
                        a.like_enabled,     a.like_daily_max,
                        a.like_min_delay,   a.like_max_delay,
                        a.story_enabled,    a.story_daily_max,
                        a.comment_enabled,  a.comment_daily_max,
                        a.dm_enabled,       a.dm_daily_max,
                        a.unfollow_enabled, a.unfollow_daily_max
                    FROM accounts a
                    WHERE a.phone_serial = $1
                    ORDER BY a.username
                    """,
                    serial,
                )
                # Fetch today's action counts for all these accounts
                account_ids = [r["id"] for r in acc_rows]
                count_rows = []
                if account_ids:
                    count_rows = await conn.fetch(
                        """
                        SELECT account_id, action_type, count
                        FROM daily_action_counts
                        WHERE date = CURRENT_DATE
                          AND account_id = ANY($1::text[])
                        """,
                        account_ids,
                    )

            # Build counts map
            counts: dict[tuple, int] = {
                (r["account_id"], r["action_type"]): r["count"]
                for r in count_rows
            }

            accounts_out = []
            for r in acc_rows:
                aid = r["id"]
                accounts_out.append({
                    "id": aid,
                    "username": r["username"],
                    "platform": r["platform"],
                    "clone_package": r["clone_package"],
                    "status": r["status"],
                    "start_hour": r["start_hour"],
                    "end_hour": r["end_hour"],
                    "tags": r["tags"],
                    "follow_enabled":   r["follow_enabled"],
                    "follow_daily_max": r["follow_daily_max"],
                    "like_enabled":     r["like_enabled"],
                    "like_daily_max":   r["like_daily_max"],
                    "story_enabled":    r["story_enabled"],
                    "story_daily_max":  r["story_daily_max"],
                    "comment_enabled":  r["comment_enabled"],
                    "comment_daily_max": r["comment_daily_max"],
                    "dm_enabled":       r["dm_enabled"],
                    "dm_daily_max":     r["dm_daily_max"],
                    "unfollow_enabled":  r["unfollow_enabled"],
                    "unfollow_daily_max": r["unfollow_daily_max"],
                    "today_counts": {
                        "follow":   counts.get((aid, "follow"),   0),
                        "unfollow": counts.get((aid, "unfollow"), 0),
                        "like":     counts.get((aid, "like"),     0),
                        "story":    counts.get((aid, "story"),    0),
                        "comment":  counts.get((aid, "comment"),  0),
                        "dm":       counts.get((aid, "dm"),       0),
                    },
                })

            return {"serial": serial, "accounts": accounts_out, "total": len(accounts_out)}

        except Exception as exc:
            log.warning("list_phone_accounts DB query failed for %s: %s", serial, exc)
            # Fall through to in-memory store

    # Fallback: in-memory store
    from ..routes.accounts import _store as _acc_store
    store = _acc_store()
    rows = [r for r in store.values() if r.get("phone_serial") == serial]
    accounts_out = [
        {
            "id": r.get("account_id", r.get("id", "")),
            "username": r.get("username", ""),
            "platform": r.get("platform", "instagram"),
            "clone_package": r.get("clone_package", ""),
            "status": r.get("status", "active"),
            "start_hour": r.get("start_hour", 8),
            "end_hour": r.get("end_hour", 22),
            "tags": r.get("tags", ""),
            "follow_enabled": r.get("follow_enabled", True),
            "follow_daily_max": r.get("follow_daily_max", 25),
            "like_enabled": r.get("like_enabled", True),
            "like_daily_max": r.get("like_daily_max", 75),
            "story_enabled": r.get("story_enabled", True),
            "story_daily_max": r.get("story_daily_max", 150),
            "comment_enabled": r.get("comment_enabled", False),
            "comment_daily_max": r.get("comment_daily_max", 8),
            "dm_enabled": r.get("dm_enabled", False),
            "dm_daily_max": r.get("dm_daily_max", 5),
            "unfollow_enabled": r.get("unfollow_enabled", True),
            "unfollow_daily_max": r.get("unfollow_daily_max", 25),
            "today_counts": {"follow": 0, "unfollow": 0, "like": 0, "story": 0, "comment": 0, "dm": 0},
        }
        for r in rows
    ]
    return {"serial": serial, "accounts": accounts_out, "total": len(accounts_out)}


@router.post("/start-warming", response_model=StartWarmingOut)
async def start_warming(request: Request) -> StartWarmingOut:
    """
    Kick off the warming cycle for all provisioned accounts.

    Steps:
        1. Load all provisioned accounts from the accounts store.
        2. Filter to accounts that have a phone_serial assigned.
        3. Build a DailySchedule via TimeSlotScheduler.
        4. Instantiate WarmingOrchestrator and kick off run_warming_cycle().
        5. The orchestrator runs in the background (asyncio.create_task);
           this endpoint returns immediately once the task is created.

    Returns the count of accounts that will be warmed.
    Raises 422 if no accounts are provisioned/assigned.
    """
    from ..routes.accounts import _store as _accounts_store
    from ...core.warming_orchestrator import WarmingOrchestrator
    from ...core.time_slot_scheduler import DailySchedule
    from datetime import datetime, timezone

    fleet = _get_fleet(request)
    store = _accounts_store()

    # Gather accounts with a phone assigned and active status
    accounts = [
        row for row in store.values()
        if row.get("phone_serial") and row.get("status", "active") not in ("banned", "paused")
    ]

    if not accounts:
        raise HTTPException(
            status_code=422,
            detail="No provisioned accounts found. Add accounts before starting warming.",
        )

    date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build fleet runners — one per phone, using PhoneHybridRunner directly.
    # WarmingOrchestrator accepts a dict[serial → PhoneHybridRunner].
    from ...core.hybrid_runner import PhoneHybridRunner, DeviceProfile, PlatformHeaders

    # Collect which platforms each phone has active accounts for, so we only
    # spin up workers for platforms that have real accounts assigned.
    phone_platforms: dict[str, set[str]] = {}
    for row in accounts:
        serial = row["phone_serial"]
        platform = row.get("platform", "instagram")
        phone_platforms.setdefault(serial, set()).add(platform)

    from ...proxy import ISPProxyPool as _ISPProxyPool
    _proxy_pool = request.app.state.proxy if isinstance(
        getattr(request.app.state, "proxy", None), _ISPProxyPool
    ) else None

    fleet_runners: dict[str, PhoneHybridRunner] = {}
    for serial, phone in fleet._phones.items():
        # Pull real device identifiers from the PhoneController state (set during
        # verify-proxy / provisioning). Fall back to safe placeholder values so
        # warming can proceed even before a full header extraction run.
        meta = phone.metadata if hasattr(phone, "metadata") else {}
        android_id     = meta.get("android_id",     phone.android_id     if hasattr(phone, "android_id")     else "0000000000000000")
        advertising_id = meta.get("advertising_id", phone.advertising_id if hasattr(phone, "advertising_id") else "00000000-0000-0000-0000-000000000000")
        carrier_name   = meta.get("carrier_name",   "")
        carrier_mcc    = meta.get("carrier_mcc_mnc","")
        tz             = getattr(phone, "timezone", "America/New_York")
        locale         = getattr(phone, "locale",   "en_US")

        # Build PlatformHeaders for each platform active on this phone.
        # These carry the device fingerprint. The actual session token is
        # passed per-task via task.params["session"] — headers here are the
        # device-level anchor (UA, device_id, android_id, etc.) that make the
        # API worker eligible to run. Without at least one entry in
        # platform_headers, supported_api_platforms() returns [] and no
        # background workers are spawned for this phone.
        platform_headers: dict = {}
        for platform in phone_platforms.get(serial, {"instagram"}):
            # Per-platform user agent and device_id pulled from phone state
            # when available; otherwise placeholder values that are still valid.
            ua = meta.get(f"{platform}_user_agent", meta.get("user_agent", "Instagram/269.0.0.18.75 Android"))
            device_id = meta.get(f"{platform}_device_id", meta.get("ig_device_id", android_id))
            app_version = meta.get(f"{platform}_app_version", "269.0.0.18.75")
            session_token = meta.get(f"{platform}_session_token", "")
            platform_headers[platform] = PlatformHeaders(
                platform=platform,
                session_token=session_token,
                device_id=device_id,
                user_agent=ua,
                app_version=app_version,
                android_id=android_id,
                advertising_id=advertising_id,
                carrier_name=carrier_name,
                carrier_mcc_mnc=carrier_mcc,
                locale=locale,
                timezone=tz,
            )

        profile = DeviceProfile(
            phone_serial=serial,
            model=getattr(phone, "model", "Samsung Galaxy S10 Lite"),
            android_version=getattr(phone, "android_version", "11"),
            android_id=android_id,
            advertising_id=advertising_id,
            carrier_name=carrier_name,
            carrier_mcc_mnc=carrier_mcc,
            timezone=tz,
            locale=locale,
            platform_headers=platform_headers,
        )
        fleet_runners[serial] = PhoneHybridRunner(profile, proxy_pool=_proxy_pool)

    # Build a minimal DailySchedule (no slot assignments — WarmingOrchestrator
    # will skip accounts without active slots; warming still starts).
    schedule = DailySchedule(
        persona_id="system",
        date_iso=date_iso,
        timezone="UTC",
    )

    orchestrator = WarmingOrchestrator(fleet_runners=fleet_runners, schedule=schedule)

    # Fire-and-forget: run warming cycle in the background
    asyncio.create_task(
        orchestrator.run_warming_cycle(accounts, date_iso),
        name=f"warming_cycle_{date_iso}",
    )

    log.info("Warming started: %d accounts, date=%s", len(accounts), date_iso)
    return StartWarmingOut(
        started=True,
        accounts=len(accounts),
        message=(
            f"Warming cycle started for {len(accounts)} accounts on {date_iso}. "
            "Monitor progress via the Analytics page."
        ),
    )


# ---------------------------------------------------------------------------
# In-process action event bus — workers push events here, WS fans out
# ---------------------------------------------------------------------------

_fleet_ws_clients: list[WebSocket] = []


async def publish_fleet_event(event: dict) -> None:
    """
    Publish one action event to all connected /ws/fleet clients.
    Called from BackgroundWorker.execute_task() after each action completes.
    Fire-and-forget: dead connections are pruned silently.
    """
    dead: list[WebSocket] = []
    for ws in list(_fleet_ws_clients):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _fleet_ws_clients:
            _fleet_ws_clients.remove(ws)


@router.websocket("/ws/fleet")
async def fleet_action_stream(websocket: WebSocket) -> None:
    """
    Real-time action stream: every follow/like/comment/DM/story_view
    that completes across the fleet is pushed here as a JSON event.

    Event shape:
        {
          "type":     "action",
          "action":   "follow" | "like" | "comment" | "story_view" | "send_dm" | ...,
          "account":  "<username>",
          "account_id": "<account_id>",
          "phone":    "<serial>",
          "platform": "instagram" | "reddit" | ...,
          "success":  true | false,
          "ts_iso":   "2026-04-12T09:00:00Z"
        }
    """
    await websocket.accept()
    _fleet_ws_clients.append(websocket)
    log.info("WebSocket /ws/fleet: client connected (total=%d)", len(_fleet_ws_clients))
    try:
        while True:
            # Keep-alive: client sends ping every 30s; we just discard
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("WebSocket /ws/fleet error: %s", exc)
    finally:
        if websocket in _fleet_ws_clients:
            _fleet_ws_clients.remove(websocket)
        log.info("WebSocket /ws/fleet: client disconnected (total=%d)", len(_fleet_ws_clients))
