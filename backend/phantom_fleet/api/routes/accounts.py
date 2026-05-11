"""
Account management routes.

In-memory store for the demo/test layer — in production these rows live
in the Postgres `accounts` table. The store is attached to app.state so
tests can seed it without a DB.

Endpoints:
    GET    /api/accounts                           — list all accounts
    GET    /api/accounts/{account_id}              — single account detail
    POST   /api/accounts/provision                 — bulk provision from credentials
    GET    /api/accounts/{account_id}/health       — ping_session() liveness check
    POST   /api/accounts/{account_id}/assign-phone — assign to a phone/clone slot
    POST   /api/accounts/{account_id}/login        — trigger login flow
    GET    /api/accounts/{account_id}/session      — session status
    POST   /api/accounts/{account_id}/session/refresh — refresh session
    DELETE /api/accounts/{account_id}/session      — logout / clear session
    POST   /api/accounts/bulk-login                — login multiple accounts (max 5 concurrent)

Proxy gate: POST /provision raises 422 ProxyNotVerified if the target phone
is not in PROXY_READY state — we never touch the platform without a verified
proxy on the wire.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from ...core.phone_controller import ProxyNotVerified

log = logging.getLogger("phantom_fleet.api.accounts")

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory account store (replaces DB in the API layer; tests seed this)
# ---------------------------------------------------------------------------

# Keyed by account_id. In production, swap for asyncpg queries.
_ACCOUNTS: dict[str, dict] = {}


def _store() -> dict[str, dict]:
    """Return the global in-memory store. Tests can monkey-patch this."""
    return _ACCOUNTS


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AccountOut(BaseModel):
    account_id: str
    username: str
    platform: str
    phone_serial: Optional[str]
    clone_index: Optional[int]
    warmup_day: int
    status: str          # active | paused | banned | provisioning
    created_at: str
    session_valid: Optional[bool]


class AccountListOut(BaseModel):
    accounts: list[AccountOut]
    total: int


class CredentialIn(BaseModel):
    """
    Account credential.  Two accepted formats:

    Format A — separate fields (legacy):
        { "username": "user", "password": "pass", "platform": "instagram" }

    Format B — unified credential string:
        { "credential_string": "Username:password:2fakey", "platform": "instagram" }

    When credential_string is provided it takes precedence and the username /
    password / two_fa_secret fields are parsed from it automatically, so callers
    don't need to split the string themselves.  This is the format supplied by
    the user for all 2fa.live accounts.
    """
    credential_string: Optional[str] = None   # "Username:password:2fakey"
    username: Optional[str] = None
    password: Optional[str] = None
    platform: str = "instagram"
    phone_serial: Optional[str] = None        # target phone for provisioning
    two_fa_secret: Optional[str] = None       # filled automatically from credential_string
    two_fa_provider: str = "2fa_live"         # default to 2fa.live for all new accounts
    threads_bio: str = ""                      # Threads profile bio / funnel tagline
    threads_funnel_url: str = ""               # Threads external_url — Telegram channel URL (never direct OnlyFans — flagged by Meta)

    def model_post_init(self, __context) -> None:
        """Parse credential_string into fields if provided."""
        if self.credential_string:
            parts = self.credential_string.strip().split(":")
            if len(parts) >= 3:
                self.username = parts[0]
                self.password = parts[1]
                self.two_fa_secret = ":".join(parts[2:])
            elif len(parts) == 2:
                self.username = parts[0]
                self.password = parts[1]
            else:
                raise ValueError(
                    "credential_string must be 'username:password' or "
                    "'username:password:2fakey'"
                )


class ProvisionRequestIn(BaseModel):
    credentials: list[CredentialIn]


class ProvisionResultOut(BaseModel):
    provisioned: int
    failed: int
    results: list[dict]   # per-account {account_id, username, status, error}


class LoginRequestIn(BaseModel):
    """
    Login request.  Accepts either:
      - Separate fields: username, password, two_fa_secret (optional)
      - Unified string: credential_string = "Username:password:2fakey"
    """
    credential_string: Optional[str] = None   # "Username:password:2fakey"
    username: Optional[str] = None
    password: Optional[str] = None
    phone_serial: Optional[str] = None
    two_fa_secret: Optional[str] = None
    two_fa_provider: str = "2fa_live"   # "totp" | "2fa_live" | "sms_activate"

    def model_post_init(self, __context) -> None:
        if self.credential_string:
            parts = self.credential_string.strip().split(":")
            if len(parts) >= 3:
                self.username = parts[0]
                self.password = parts[1]
                self.two_fa_secret = ":".join(parts[2:])
            elif len(parts) == 2:
                self.username = parts[0]
                self.password = parts[1]


class LoginResultOut(BaseModel):
    account_id: str
    username: str
    ig_user_id: str
    session_valid: bool


class SessionStatusOut(BaseModel):
    account_id: str
    has_session: bool
    is_valid: bool
    checked_at: str


class BulkLoginIn(BaseModel):
    credentials: list[LoginRequestIn]


class BulkLoginResultOut(BaseModel):
    succeeded: int
    failed: int
    results: list[dict]


class AssignPhoneIn(BaseModel):
    phone_serial: str
    clone_index: int = 0


class AssignPhoneOut(BaseModel):
    account_id: str
    phone_serial: str
    clone_index: int


class HealthOut(BaseModel):
    account_id: str
    session_valid: bool
    checked_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_out(row: dict) -> AccountOut:
    return AccountOut(
        account_id=row["account_id"],
        username=row["username"],
        platform=row["platform"],
        phone_serial=row.get("phone_serial"),
        clone_index=row.get("clone_index"),
        warmup_day=row.get("warmup_day", 0),
        status=row.get("status", "active"),
        created_at=row.get("created_at", ""),
        session_valid=row.get("session_valid"),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=AccountListOut)
async def list_accounts(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    phone_serial: Optional[str] = None,
) -> AccountListOut:
    """List all accounts with optional platform/status/phone_serial filter."""
    store = _store()
    rows = list(store.values())

    if platform:
        rows = [r for r in rows if r.get("platform") == platform]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if phone_serial:
        rows = [r for r in rows if r.get("phone_serial") == phone_serial]

    return AccountListOut(
        accounts=[_row_to_out(r) for r in rows],
        total=len(rows),
    )


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(account_id: str) -> AccountOut:
    """Return a single account by ID."""
    store = _store()
    row = store.get(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id!r} not found")
    return _row_to_out(row)


@router.post("/provision", response_model=ProvisionResultOut)
async def provision_accounts(
    body: ProvisionRequestIn,
    request: Request,
) -> ProvisionResultOut:
    """
    Bulk-provision accounts from a credentials list.

    For each credential:
        1. Checks that the target phone is in PROXY_READY state (if phone_serial given).
        2. Delegates to AccountProvisioner to bootstrap the session.
        3. Stores the account in the in-memory store.

    Returns per-account success/failure list.
    """
    from ..provisioner import AccountProvisioner

    fleet = request.app.state.ctx.fleet
    provisioner = AccountProvisioner(fleet=fleet, store=_store())

    results: list[dict] = []
    provisioned = 0
    failed = 0

    for cred in body.credentials:
        try:
            account_id = await provisioner.provision_one(
                username=cred.username,
                password=cred.password,
                platform=cred.platform,
                phone_serial=cred.phone_serial,
                two_fa_secret=cred.two_fa_secret,
                two_fa_provider=cred.two_fa_provider,
                threads_bio=cred.threads_bio,
                threads_funnel_url=cred.threads_funnel_url,
            )
            results.append({
                "account_id": account_id,
                "username": cred.username,
                "platform": cred.platform,
                "status": "provisioned",
                "error": None,
            })
            provisioned += 1
        except ProxyNotVerified as exc:
            results.append({
                "account_id": None,
                "username": cred.username,
                "platform": cred.platform,
                "status": "failed",
                "error": f"proxy_not_verified: {exc}",
            })
            failed += 1
        except Exception as exc:
            log.exception("provision failed for %s", cred.username)
            results.append({
                "account_id": None,
                "username": cred.username,
                "platform": cred.platform,
                "status": "failed",
                "error": str(exc),
            })
            failed += 1

    return ProvisionResultOut(provisioned=provisioned, failed=failed, results=results)


@router.get("/{account_id}/health", response_model=HealthOut)
async def account_health(account_id: str) -> HealthOut:
    """
    Lightweight session health check via InstagramClient.ping_session().
    Returns True if the stored session cookie is still valid.

    Note: for non-IG platforms, returns True (stub — wire per-platform ping).
    """
    store = _store()
    row = store.get(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id!r} not found")

    # For accounts with a live session object, call ping_session()
    ig_session = row.get("_ig_session")
    if ig_session is not None and row.get("platform") == "instagram":
        from ...core.instagram_client import InstagramClient
        proxy_url = row.get("proxy_url", "socks5://127.0.0.1:8089")
        client = InstagramClient(session=ig_session, proxy_url=proxy_url)
        try:
            async with client as c:
                valid = await c.ping_session()
        except Exception:
            valid = False
        row["session_valid"] = valid
    else:
        # Platform not IG or no live session — assume valid (session not stored yet)
        valid = row.get("session_valid", True)

    return HealthOut(
        account_id=account_id,
        session_valid=valid,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/{account_id}/assign-phone", response_model=AssignPhoneOut)
async def assign_phone(
    account_id: str,
    body: AssignPhoneIn,
    request: Request,
) -> AssignPhoneOut:
    """
    Assign an account to a phone's clone slot.

    Updates the in-memory store and the phone's CloneSlot.account_id.
    Raises 404 if either the account or the phone is not registered.
    Raises 409 if the clone slot is already occupied by a different account.
    """
    store = _store()
    row = store.get(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id!r} not found")

    fleet = request.app.state.ctx.fleet
    phone = fleet.get(body.phone_serial)
    if phone is None:
        raise HTTPException(
            status_code=404,
            detail=f"Phone {body.phone_serial!r} not registered",
        )

    # Check clone slot availability
    for clone in phone.clones:
        if clone.clone_index == body.clone_index:
            if clone.account_id is not None and clone.account_id != account_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Clone slot {body.clone_index} on {body.phone_serial} "
                        f"is occupied by account {clone.account_id!r}"
                    ),
                )
            clone.account_id = account_id
            break

    # Update account row
    row["phone_serial"] = body.phone_serial
    row["clone_index"] = body.clone_index

    log.info(
        "Assigned account %s → phone %s clone %d",
        account_id, body.phone_serial, body.clone_index,
    )

    return AssignPhoneOut(
        account_id=account_id,
        phone_serial=body.phone_serial,
        clone_index=body.clone_index,
    )


# ---------------------------------------------------------------------------
# Session management routes
# ---------------------------------------------------------------------------


@router.post("/{account_id}/login", response_model=LoginResultOut)
async def login_account(
    account_id: str,
    body: LoginRequestIn,
    request: Request,
) -> LoginResultOut:
    """
    Trigger the full Instagram login flow for an existing account record.

    If the account does not exist yet it is provisioned on the fly.
    Stores the resulting session encrypted via IGSessionStore.
    """
    from ...core.ig_session_manager import IGLoginFailed, IGCheckpointRequired
    from ..provisioner import AccountProvisioner

    fleet = request.app.state.ctx.fleet
    store = _store()
    provisioner = AccountProvisioner(fleet=fleet, store=store)

    # Check proxy if phone_serial given
    proxy_url = "socks5://127.0.0.1:8089"
    if body.phone_serial:
        phone = fleet.get(body.phone_serial)
        if phone is None:
            raise HTTPException(status_code=404, detail=f"Phone {body.phone_serial!r} not registered")
        from ...core.phone_controller import PhoneState
        if phone.state != PhoneState.PROXY_READY:
            raise HTTPException(
                status_code=422,
                detail=f"Phone {body.phone_serial} proxy not verified",
            )
        proxy_url = f"socks5://{phone.proxy_host}:{phone.proxy_port}"

    try:
        from ..provisioner import _build_default_device_profile
        from ...core.ig_session_manager import (
            IGLoginFlow, TOTPProvider, TwoFALiveProvider, SMSActivateProvider,
        )
        from ...core.ig_session_store import IGSessionStore

        device = _build_default_device_profile(account_id)
        code_provider = None
        if body.two_fa_secret:
            if body.two_fa_provider == "totp":
                code_provider = TOTPProvider(body.two_fa_secret)
            elif body.two_fa_provider == "2fa_live":
                # TwoFALiveProvider accepts either raw secret or "Username:password:2fakey"
                code_provider = TwoFALiveProvider.from_credential_string(body.two_fa_secret)
            elif body.two_fa_provider == "sms_activate":
                parts = body.two_fa_secret.split(":", 1)
                if len(parts) != 2:
                    raise HTTPException(
                        status_code=422,
                        detail="sms_activate two_fa_secret must be 'api_key:activation_id'",
                    )
                code_provider = SMSActivateProvider(api_key=parts[0], activation_id=parts[1])

        flow = IGLoginFlow(device=device, proxy_url=proxy_url)
        session = await flow.login(
            account_id=account_id,
            username=body.username,
            password=body.password,
            code_provider=code_provider,
        )

        # Save session to encrypted file store
        try:
            session_store = IGSessionStore()
            await session_store.save(account_id, session)
        except RuntimeError:
            pass  # PHANTOM_SESSION_KEY not set — in-memory only

        # Persist session credentials to PostgreSQL so operational routes
        # (scheduler, warmup, scraper, ai_agent) can read them from the DB.
        pool = getattr(request.app.state, "db_pool", None)
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE accounts
                           SET sessionid = $1,
                               csrftoken = $2,
                               mid       = $3,
                               user_id   = $4,
                               username  = $5,
                               status    = 'active'
                         WHERE id = $6
                        """,
                        session.session_id,
                        session.csrftoken,
                        session.mid,
                        session.ig_user_id,
                        session.username,
                        account_id,
                    )
            except Exception as db_exc:
                log.warning(
                    "login_account: failed to persist session to DB for %s: %s",
                    account_id, db_exc,
                )

        # Upsert account row (in-memory store for test/dev layer)
        now_iso = datetime.now(timezone.utc).isoformat()
        if account_id not in store:
            store[account_id] = {
                "account_id": account_id,
                "username": body.username,
                "platform": "instagram",
                "phone_serial": body.phone_serial,
                "clone_index": None,
                "warmup_day": 0,
                "status": "active",
                "created_at": now_iso,
                "proxy_url": proxy_url,
            }
        store[account_id]["session_valid"] = True
        store[account_id]["_ig_session"] = session

    except IGCheckpointRequired as exc:
        raise HTTPException(
            status_code=403,
            detail=f"checkpoint_required: {exc.checkpoint_url}",
        )
    except IGLoginFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        log.exception("login_account failed for %s", body.username)
        raise HTTPException(status_code=500, detail=str(exc))

    return LoginResultOut(
        account_id=account_id,
        username=session.username,
        ig_user_id=session.ig_user_id,
        session_valid=session.is_valid,
    )


@router.patch("/{account_id}")
async def update_account(account_id: str, request: Request) -> dict:
    """
    Partial update for account settings.

    Accepts any subset of the scheduler / engagement settings columns:
        start_hour, end_hour, tags, clone_package, status,
        follow_enabled, follow_daily_max, follow_min_delay, follow_max_delay,
        like_enabled, like_daily_max, like_min_delay, like_max_delay,
        story_enabled, story_daily_max, comment_enabled, comment_daily_max,
        dm_enabled, dm_daily_max, unfollow_enabled, unfollow_daily_max

    Writes to the DB `accounts` table (only fields present in the request body).
    Also updates the in-memory store so the running executor sees changes immediately.
    """
    _PATCHABLE = {
        "start_hour", "end_hour", "tags", "clone_package", "status",
        "follow_enabled", "follow_daily_max", "follow_min_delay", "follow_max_delay",
        "like_enabled", "like_daily_max", "like_min_delay", "like_max_delay",
        "story_enabled", "story_daily_max",
        "comment_enabled", "comment_daily_max",
        "dm_enabled", "dm_daily_max",
        "unfollow_enabled", "unfollow_daily_max",
    }

    body = await request.json()
    updates = {k: v for k, v in body.items() if k in _PATCHABLE}

    if not updates:
        return {"account_id": account_id, "updated": []}

    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            set_clauses = ", ".join(
                f"{col} = ${i + 2}" for i, col in enumerate(updates.keys())
            )
            values = [account_id] + list(updates.values())
            async with pool.acquire() as conn:
                result = await conn.execute(
                    f"UPDATE accounts SET {set_clauses} WHERE id = $1",
                    *values,
                )
            if result == "UPDATE 0":
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail=f"Account {account_id!r} not found")
        except Exception as exc:
            log.warning("update_account DB write failed for %s: %s", account_id, exc)

    # Mirror to in-memory store (best-effort)
    store = _store()
    if account_id in store:
        store[account_id].update(updates)

    log.info("update_account: %s — updated %s", account_id, list(updates.keys()))
    return {"account_id": account_id, "updated": list(updates.keys())}


@router.post("/{account_id}/detect-clone")
async def detect_clone_package(
    account_id: str,
    request: Request,
) -> dict:
    """
    Detect which clone app is currently open on the phone and save it
    as this account's clone_package.

    Flow:
        1. User opens their Instagram or Threads clone on the phone.
        2. Frontend calls this endpoint.
        3. We call GET http://{phone_ip}:8090/device/foreground-package
           on the Companion APK to read whatever package is in the foreground.
        4. Save result to accounts.clone_package in DB + in-memory store.

    Body: { "phone_ip": "192.168.1.42" }
    Returns: { "clone_package": "com.instagram.android.clone3" }
    """
    import httpx

    body = await request.json()
    phone_ip: str = body.get("phone_ip", "").strip()
    phone_serial: str = body.get("phone_serial", "").strip()

    # If only phone_serial was given, look up wifi_ip from phone_heartbeats
    if not phone_ip and phone_serial:
        pool = getattr(request.app.state, "db_pool", None)
        if pool:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT wifi_ip FROM phone_heartbeats WHERE serial = $1",
                        phone_serial,
                    )
                if row:
                    phone_ip = row["wifi_ip"]
            except Exception:
                pass
        if not phone_ip:
            # Fall back to in-memory fleet
            fleet = request.app.state.ctx.fleet
            phone = fleet.get(phone_serial)
            if phone and hasattr(phone, "wifi_ip") and phone.wifi_ip:
                phone_ip = phone.wifi_ip

    if not phone_ip:
        raise HTTPException(
            status_code=422,
            detail="phone_ip is required (or phone_serial with a registered heartbeat)",
        )

    # Call the companion APK on the phone
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"http://{phone_ip}:8090/device/foreground-package")
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach companion APK at {phone_ip}:8090 — {exc}",
        )

    clone_package: str = data.get("pkg", "").strip()
    if not clone_package:
        raise HTTPException(
            status_code=422,
            detail="Companion APK returned empty package name. Make sure the clone app is open.",
        )

    # Persist to DB
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE accounts SET clone_package = $1 WHERE id = $2",
                    clone_package, account_id,
                )
        except Exception as db_exc:
            log.warning("detect_clone_package: DB update failed for %s: %s", account_id, db_exc)

    # Update in-memory store
    store = _store()
    if account_id in store:
        store[account_id]["clone_package"] = clone_package

    log.info("detect_clone_package: account=%s pkg=%s", account_id, clone_package)
    return {"clone_package": clone_package}


@router.get("/{account_id}/session", response_model=SessionStatusOut)
async def get_session_status(account_id: str) -> SessionStatusOut:
    """Return session existence and validity for an account."""
    from ...core.ig_session_store import IGSessionStore

    try:
        session_store = IGSessionStore()
        is_valid = await session_store.is_valid(account_id)
        has_session = (await session_store.load(account_id)) is not None
    except RuntimeError:
        # PHANTOM_SESSION_KEY not set — fall back to in-memory store flag
        store = _store()
        row = store.get(account_id)
        has_session = row is not None and row.get("_ig_session") is not None
        is_valid = bool(row.get("session_valid", False)) if row else False

    return SessionStatusOut(
        account_id=account_id,
        has_session=has_session,
        is_valid=is_valid,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/{account_id}/session/refresh", response_model=HealthOut)
async def refresh_session(account_id: str) -> HealthOut:
    """
    Refresh an existing session via ping_session().
    If the session is dead, clears the stored session and returns session_valid=False.
    Caller should trigger a fresh login via POST /{account_id}/login.
    """
    from ...core.ig_session_store import IGSessionStore
    from ...core.instagram_client import InstagramClient, IGSessionExpired

    store = _store()
    row = store.get(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id!r} not found")

    ig_session = row.get("_ig_session")
    if ig_session is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active session in memory for {account_id!r}. Trigger /login first.",
        )

    proxy_url = row.get("proxy_url", "socks5://127.0.0.1:8089")
    client = InstagramClient(session=ig_session, proxy_url=proxy_url)

    try:
        session_store = IGSessionStore()
        refreshed = await session_store.refresh(account_id, client)
        row["session_valid"] = True
        row["_ig_session"] = refreshed
        valid = True
    except IGSessionExpired:
        row["session_valid"] = False
        try:
            session_store = IGSessionStore()
            await session_store.delete(account_id)
        except RuntimeError:
            pass
        valid = False
    except RuntimeError:
        # PHANTOM_SESSION_KEY not set — do an in-memory ping only
        async with client as c:
            valid = await c.ping_session()
        row["session_valid"] = valid

    return HealthOut(
        account_id=account_id,
        session_valid=valid,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@router.delete("/{account_id}/session", status_code=204)
async def delete_session(account_id: str) -> None:
    """
    Logout and clear the stored session for an account.
    The account row is kept; only the session data is removed.
    """
    from ...core.ig_session_store import IGSessionStore

    store = _store()
    row = store.get(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id!r} not found")

    row.pop("_ig_session", None)
    row["session_valid"] = False

    try:
        session_store = IGSessionStore()
        await session_store.delete(account_id)
    except RuntimeError:
        pass

    log.info("Session cleared for account %s", account_id)


def _get_fleet(request: Request):
    return request.app.state.ctx.fleet


@router.post("/bulk-login", response_model=BulkLoginResultOut)
async def bulk_login(body: BulkLoginIn, request: Request) -> BulkLoginResultOut:
    """
    Login multiple accounts concurrently, limited to 5 simultaneous logins
    via a semaphore. Returns per-account success/failure list.
    """
    import asyncio
    from ...core.ig_session_manager import IGLoginFailed, IGCheckpointRequired

    fleet = request.app.state.ctx.fleet
    store = _store()
    semaphore = asyncio.Semaphore(5)
    results: list[dict] = []

    async def _login_one(cred: LoginRequestIn) -> dict:
        async with semaphore:
            tmp_account_id = str(uuid.uuid4())
            try:
                from ..provisioner import AccountProvisioner
                provisioner = AccountProvisioner(fleet=fleet, store=store)
                aid = await provisioner.provision_one(
                    username=cred.username,
                    password=cred.password,
                    platform="instagram",
                    phone_serial=cred.phone_serial,
                    two_fa_secret=cred.two_fa_secret,
                    two_fa_provider=cred.two_fa_provider,
                )
                return {
                    "account_id": aid,
                    "username": cred.username,
                    "status": "ok",
                    "error": None,
                }
            except IGCheckpointRequired as exc:
                return {
                    "account_id": None,
                    "username": cred.username,
                    "status": "checkpoint",
                    "error": f"checkpoint_required: {exc.checkpoint_url}",
                }
            except IGLoginFailed as exc:
                return {
                    "account_id": None,
                    "username": cred.username,
                    "status": "failed",
                    "error": str(exc),
                }
            except Exception as exc:
                log.exception("bulk-login failed for %s", cred.username)
                return {
                    "account_id": None,
                    "username": cred.username,
                    "status": "failed",
                    "error": str(exc),
                }

    tasks = [_login_one(cred) for cred in body.credentials]
    results = list(await asyncio.gather(*tasks))

    succeeded = sum(1 for r in results if r["status"] == "ok")
    failed = len(results) - succeeded

    return BulkLoginResultOut(succeeded=succeeded, failed=failed, results=results)


# ---------------------------------------------------------------------------
# Bulk CSV import
# ---------------------------------------------------------------------------

import csv
import io


@router.post("/bulk-import")
async def bulk_import_accounts(
    file: UploadFile = File(...),
    request: Request = None,
) -> dict:
    """
    Bulk import accounts from a CSV file.

    CSV format (header row required):
        username,password,two_fa_secret,phone_serial,platform,home_state,home_city

    Only username and password are required. All other columns are optional.
    Returns {queued: N, skipped: N, errors: [{row: N, username: str, error: str}]}
    """
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # strip BOM if present
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return {"queued": 0, "skipped": 0, "errors": [{"row": 0, "error": "Empty or invalid CSV"}]}

    # Normalize header names (lowercase, strip spaces)
    fieldnames = [f.lower().strip() for f in reader.fieldnames]

    queued: list[dict] = []
    errors: list[dict] = []

    for row_num, raw_row in enumerate(reader, start=2):
        row = {k.lower().strip(): v.strip() for k, v in raw_row.items() if k}
        username = row.get("username", "").strip()
        password = row.get("password", "").strip()

        if not username or not password:
            errors.append({"row": row_num, "username": username or "—", "error": "username and password required"})
            continue

        queued.append({
            "username":       username,
            "password":       password,
            "two_fa_secret":  row.get("two_fa_secret") or row.get("2fa_secret") or None,
            "phone_serial":   row.get("phone_serial") or row.get("phone") or None,
            "platform":       row.get("platform", "instagram"),
            "home_state":     row.get("home_state") or row.get("state") or "NY",
            "home_city":      row.get("home_city") or row.get("city") or "New York",
        })

    # Store queued credentials in the pending import store for background provisioning
    store = _store()
    _pending_imports = getattr(request.app.state, "pending_imports", []) if request else []
    _pending_imports.extend(queued)
    if request:
        request.app.state.pending_imports = _pending_imports

    return {
        "queued":  len(queued),
        "skipped": 0,
        "errors":  errors,
        "message": f"Queued {len(queued)} accounts for provisioning. "
                   "Trigger POST /api/accounts/provision-pending to start.",
    }


@router.post("/provision-pending")
async def provision_pending(request: Request) -> dict:
    """
    Start provisioning all queued imports from bulk-import.
    Runs in the background — returns immediately.
    """
    pending = getattr(request.app.state, "pending_imports", [])
    if not pending:
        return {"message": "No pending imports.", "count": 0}

    # Move to in-flight and clear pending
    request.app.state.pending_imports = []
    fleet = _get_fleet(request)

    async def _run():
        from ...api.provisioner import AccountProvisioner
        store = _store()
        provisioner = AccountProvisioner(fleet=fleet, store=store)
        results = []
        for cred in pending:
            try:
                account_id = await provisioner.provision_one(
                    username=cred["username"],
                    password=cred["password"],
                    platform=cred.get("platform", "instagram"),
                    phone_serial=cred.get("phone_serial"),
                    two_fa_secret=cred.get("two_fa_secret"),
                )
                results.append({"username": cred["username"], "account_id": account_id, "status": "ok"})
            except Exception as exc:
                results.append({"username": cred["username"], "error": str(exc), "status": "failed"})
        log.info("Bulk provision complete: %d accounts", len(results))

    import asyncio
    asyncio.create_task(_run(), name="bulk_provision")

    return {"message": f"Provisioning {len(pending)} accounts in background.", "count": len(pending)}
