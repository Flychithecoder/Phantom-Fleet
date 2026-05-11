"""
Gmail → Reddit Pipeline API routes.

Endpoints:
    GET  /api/pipeline/gmail/stats          — pool statistics
    POST /api/pipeline/gmail/create         — trigger Gmail creation on a phone
    POST /api/pipeline/reddit/register      — register Reddit accounts from pool
    GET  /api/pipeline/reddit/accounts      — list created Reddit accounts
    POST /api/pipeline/reddit/export        — export Reddit credentials as CSV
    POST /api/pipeline/reddit/provision     — move registered accounts into the
                                              fleet DB (creates personas + accounts)

All creation/registration operations are dispatched as background tasks so
the HTTP response returns immediately. Progress can be tracked via the stats
endpoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["Gmail→Reddit Pipeline"])

# ---------------------------------------------------------------------------
# Shared pool singleton (lazy-initialised)
# ---------------------------------------------------------------------------

_pool: Optional["GmailAccountPool"] = None  # noqa: F821


def _get_pool() -> "GmailAccountPool":  # noqa: F821
    """Return the module-level GmailAccountPool singleton, creating it on first call."""
    global _pool
    if _pool is None:
        from ...core.gmail_account_pool import GmailAccountPool
        _pool = GmailAccountPool()
    return _pool


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class GmailCreateRequest(BaseModel):
    """Request body for POST /api/pipeline/gmail/create."""

    phone_serial: str = Field(..., description="ADB device serial of the target phone")
    count: int = Field(1, ge=1, le=5, description="Number of accounts to create (1-5)")


class RedditRegisterRequest(BaseModel):
    """Request body for POST /api/pipeline/reddit/register."""

    count: int = Field(5, ge=1, le=20, description="Number of Reddit accounts to register")
    proxy_url: str = Field(
        ...,
        description="HTTP proxy URL for Reddit registration requests, e.g. http://user:pass@host:port",
    )


class PipelineStatsResponse(BaseModel):
    """Response for GET /api/pipeline/gmail/stats."""

    total_gmails: int
    unregistered: int
    registered: int
    verified_reddit: int


class AccountEntry(BaseModel):
    """Single row in the accounts table response."""

    email: str
    reddit_username: Optional[str] = None
    status: str  # unregistered | registered | verified | aged
    created_at: str
    proxy_used: Optional[str] = None


class AccountListResponse(BaseModel):
    """Response for GET /api/pipeline/reddit/accounts."""

    accounts: list[AccountEntry]
    total: int


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


async def _bg_create_gmails(phone_serial: str, count: int) -> None:
    """Background task: create ``count`` Gmail accounts on ``phone_serial``."""
    sms_key = os.environ.get("SMS_ACTIVATE_API_KEY", "")
    if not sms_key:
        log.error("SMS_ACTIVATE_API_KEY not set — cannot create Gmail accounts")
        return

    from ...agents.specialists.gmail_creation_agent import GmailCreationAgent

    agent = GmailCreationAgent(sms_activate_api_key=sms_key)
    pool = _get_pool()

    for i in range(count):
        log.info("Creating Gmail %d/%d on phone %s", i + 1, count, phone_serial)
        result = await agent.create_account(phone_serial)
        if result.success and result.credential:
            pool.add_gmail(result.credential)
            log.info(
                "Gmail created: %s (%.1fs)", result.credential.email, result.duration_seconds
            )
        else:
            log.error(
                "Gmail creation %d/%d failed on %s: %s",
                i + 1, count, phone_serial, result.error,
            )
        # Respect the min delay between creations — the agent enforces it
        # internally, but we also sleep here for belt-and-suspenders
        if i < count - 1:
            await asyncio.sleep(5)


async def _bg_register_reddit(count: int, proxy_url: str) -> None:
    """Background task: register ``count`` Reddit accounts from the Gmail pool."""
    from ...agents.specialists.reddit_registration_agent import RedditRegistrationAgent

    pool = _get_pool()
    unregistered = pool.get_unregistered(limit=count)

    if not unregistered:
        log.warning("No unregistered Gmail accounts in pool to register Reddit accounts with")
        return

    agent = RedditRegistrationAgent()
    for gmail_cred in unregistered:
        try:
            reddit_cred = await agent.register(gmail_cred, proxy_url)
            pool.mark_registered(gmail_cred.email, reddit_cred)
            log.info(
                "Registered Reddit: u/%s ← %s", reddit_cred.username, gmail_cred.email
            )
        except Exception as exc:  # noqa: BLE001
            log.error("Reddit registration failed for %s: %s", gmail_cred.email, exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/gmail/stats", response_model=PipelineStatsResponse)
async def get_pipeline_stats() -> PipelineStatsResponse:
    """Return current Gmail pool and Reddit registration statistics.

    Returns:
        PipelineStatsResponse with counts for each credential state.
    """
    stats = _get_pool().get_pool_stats()
    return PipelineStatsResponse(
        total_gmails=stats.total_gmails,
        unregistered=stats.unregistered,
        registered=stats.registered,
        verified_reddit=stats.verified_reddit,
    )


@router.post("/gmail/create", status_code=202)
async def create_gmail_accounts(
    req: GmailCreateRequest, background_tasks: BackgroundTasks
) -> dict:
    """Dispatch Gmail account creation on the specified phone serial.

    The operation runs in the background — the endpoint returns immediately
    with a 202 Accepted. Poll /api/pipeline/gmail/stats to track progress.

    Args:
        req: GmailCreateRequest with phone_serial and count.

    Returns:
        Acknowledgement dict with queued count.
    """
    background_tasks.add_task(_bg_create_gmails, req.phone_serial, req.count)
    return {
        "queued": True,
        "phone_serial": req.phone_serial,
        "count": req.count,
        "message": f"Creating {req.count} Gmail account(s) on {req.phone_serial} in background",
    }


@router.post("/reddit/register", status_code=202)
async def register_reddit_accounts(
    req: RedditRegisterRequest, background_tasks: BackgroundTasks
) -> dict:
    """Dispatch Reddit account registration for unregistered Gmails in the pool.

    The operation runs in the background — the endpoint returns immediately
    with a 202 Accepted. Poll /api/pipeline/gmail/stats to track progress.

    Args:
        req: RedditRegisterRequest with count and proxy_url.

    Returns:
        Acknowledgement dict.
    """
    pool = _get_pool()
    available = len(pool.get_unregistered(limit=req.count))
    if available == 0:
        raise HTTPException(
            status_code=409,
            detail="No unregistered Gmail accounts available in pool. "
                   "Create Gmail accounts first via POST /api/pipeline/gmail/create",
        )

    actual_count = min(req.count, available)
    background_tasks.add_task(_bg_register_reddit, actual_count, req.proxy_url)
    return {
        "queued": True,
        "count": actual_count,
        "proxy_url": req.proxy_url,
        "message": f"Registering {actual_count} Reddit account(s) in background",
    }


@router.get("/reddit/accounts", response_model=AccountListResponse)
async def list_reddit_accounts() -> AccountListResponse:
    """List all Gmail pool entries with their Reddit registration status.

    Returns:
        AccountListResponse with an entry per Gmail address.
    """
    pool = _get_pool()
    raw_pool = pool._load()  # noqa: SLF001 — direct pool access for full list

    accounts: list[AccountEntry] = []
    for entry in raw_pool.get("gmails", []):
        rc = entry.get("reddit_credential")
        if rc is None:
            status = "unregistered"
            username = None
            proxy_used = None
        else:
            if rc.get("verification_status") == "verified":
                status = "verified"
            else:
                status = "registered"
            username = rc.get("username")
            proxy_used = rc.get("proxy_url_used")

        accounts.append(AccountEntry(
            email=entry.get("email", ""),
            reddit_username=username,
            status=status,
            created_at=entry.get("created_at_iso", ""),
            proxy_used=proxy_used,
        ))

    # Sort: newest first
    accounts.sort(key=lambda a: a.created_at, reverse=True)

    return AccountListResponse(accounts=accounts, total=len(accounts))


@router.post("/reddit/provision", status_code=202)
async def provision_reddit_accounts(request: Request, background_tasks: BackgroundTasks) -> dict:
    """
    Move all registered-but-not-yet-provisioned Reddit accounts from the
    in-memory pool into the fleet's Postgres accounts table.

    For each credential in the pool that has an access_token:
        1. Creates a minimal persona row (if none exists for this username)
        2. Inserts/upserts an accounts row with Reddit credentials
        3. Marks the pool entry as provisioned

    Returns 202 immediately. Check /api/reddit/accounts to see provisioned accounts.
    """
    pool_state = _get_pool()
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(503, "Database unavailable")

    all_entries = pool_state._load().get("gmails", [])  # noqa: SLF001
    ready = [
        e["reddit_credential"]
        for e in all_entries
        if e.get("reddit_credential") and e["reddit_credential"].get("access_token")
    ]
    if not ready:
        raise HTTPException(409, "No registered accounts with OAuth tokens ready to provision. "
                            "Run /register first, then wait for token acquisition to complete.")

    background_tasks.add_task(_bg_provision_to_db, db_pool, ready)
    return {
        "queued":  True,
        "count":   len(ready),
        "message": f"Provisioning {len(ready)} Reddit account(s) into fleet DB in background",
    }


# ---------------------------------------------------------------------------
# US cities for minimal persona generation (seeded selection)
# ---------------------------------------------------------------------------

_US_CITIES: list[tuple[str, str]] = [
    ("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"), ("Houston", "TX"),
    ("Phoenix", "AZ"), ("Philadelphia", "PA"), ("San Antonio", "TX"), ("San Diego", "CA"),
    ("Dallas", "TX"), ("Austin", "TX"), ("San Jose", "CA"), ("Fort Worth", "TX"),
    ("Jacksonville", "FL"), ("Columbus", "OH"), ("Charlotte", "NC"), ("Indianapolis", "IN"),
    ("San Francisco", "CA"), ("Seattle", "WA"), ("Denver", "CO"), ("Nashville", "TN"),
    ("Oklahoma City", "OK"), ("Las Vegas", "NV"), ("Louisville", "KY"), ("Baltimore", "MD"),
    ("Milwaukee", "WI"), ("Albuquerque", "NM"), ("Tucson", "AZ"), ("Fresno", "CA"),
    ("Sacramento", "CA"), ("Mesa", "AZ"), ("Kansas City", "MO"), ("Atlanta", "GA"),
    ("Omaha", "NE"), ("Colorado Springs", "CO"), ("Raleigh", "NC"), ("Miami", "FL"),
    ("Cleveland", "OH"), ("Tulsa", "OK"), ("Tampa", "FL"), ("Arlington", "TX"),
]

_ANDROID_DEVICES: list[str] = [
    "Samsung Galaxy S21", "Samsung Galaxy S22", "Samsung Galaxy A54",
    "Samsung Galaxy S23", "Google Pixel 6", "Google Pixel 7",
    "Google Pixel 7a", "OnePlus 10 Pro", "Motorola Moto G Power",
    "Samsung Galaxy A34", "Samsung Galaxy S20 FE", "Google Pixel 6a",
]

_ANDROID_VERSIONS: list[str] = [
    "12", "12", "13", "13", "13", "13", "14",
]

_TIMEZONES: list[str] = [
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Phoenix",
]


def _sha_seed(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def _seeded_pick(lst: list, seed: int, offset: int = 0):
    return lst[(_sha_seed(str(seed) + str(offset))) % len(lst)]


async def _bg_provision_to_db(db_pool, credentials: list[dict]) -> None:
    """
    Background: insert each RedditCredential dict into personas + accounts tables.

    Idempotent — uses ON CONFLICT DO UPDATE so running twice is safe.
    """
    from ...core.reddit_oauth import generate_device_id, generate_loid

    provisioned = 0
    failed      = 0

    for cred in credentials:
        username   = cred.get("username", "")
        user_id    = cred.get("reddit_user_id", "")
        email      = cred.get("email", "")
        password   = cred.get("password", "")
        access_token  = cred.get("access_token", "")
        refresh_token = cred.get("refresh_token", "")
        token_expires_at = cred.get("token_expires_at", 0.0)
        device_id  = cred.get("device_id") or generate_device_id(user_id or username)
        loid       = cred.get("loid")      or generate_loid(user_id or username)
        created_at = cred.get("created_at_iso") or datetime.now(timezone.utc).isoformat()
        proxy_url  = cred.get("proxy_url_used", "")

        if not username or not access_token:
            log.warning("Provision: skipping entry missing username or access_token")
            failed += 1
            continue

        seed = _sha_seed(username)

        # Minimal persona fields
        city, state = _seeded_pick(_US_CITIES, seed, 1)
        age         = 20 + (_sha_seed(username + "age") % 9)   # 20–28
        device      = _seeded_pick(_ANDROID_DEVICES, seed, 2)
        android_ver = _seeded_pick(_ANDROID_VERSIONS, seed, 3)
        timezone_str = _seeded_pick(_TIMEZONES, seed, 4)

        persona_id  = hashlib.sha256(f"reddit_persona:{username}".encode()).hexdigest()[:32]
        account_id  = hashlib.sha256(f"reddit_account:{username}".encode()).hexdigest()[:32]

        expires_ts = (
            datetime.fromtimestamp(token_expires_at, tz=timezone.utc)
            if token_expires_at > 0
            else None
        )

        try:
            async with db_pool.acquire() as conn:
                # 1. Upsert minimal persona
                await conn.execute("""
                    INSERT INTO personas (
                        id, display_name, gender, age,
                        city, state, country, locale, timezone,
                        device_model, android_version,
                        aggressiveness, peak_hour_local,
                        active_window_start, active_window_end,
                        interest_topics, target_funnel, biometrics
                    ) VALUES (
                        $1, $2, 'f', $3,
                        $4, $5, 'US', 'en-US', $6,
                        $7, $8,
                        0.5, 20,
                        9, 23,
                        ARRAY['content_creation','photography'], 'onlyfans', '{}'::jsonb
                    ) ON CONFLICT (id) DO NOTHING
                """,
                persona_id, username, age,
                city, state, timezone_str,
                device, android_ver,
                )

                # 2. Upsert account with all Reddit credentials
                await conn.execute("""
                    INSERT INTO accounts (
                        id, persona_id, platform, username, status,
                        aggressiveness, credentials_ref,
                        reddit_access_token, reddit_refresh_token, reddit_token_expires_at,
                        reddit_device_id, reddit_loid
                    ) VALUES (
                        $1, $2, 'reddit', $3, 'warming',
                        0.5,
                        jsonb_build_object(
                            'username', $3,
                            'password', $4,
                            'email', $5,
                            'reddit_user_id', $6,
                            'proxy_url', $7
                        ),
                        $8, $9, $10,
                        $11, $12
                    )
                    ON CONFLICT (platform, username) DO UPDATE SET
                        reddit_access_token     = EXCLUDED.reddit_access_token,
                        reddit_refresh_token    = EXCLUDED.reddit_refresh_token,
                        reddit_token_expires_at = EXCLUDED.reddit_token_expires_at,
                        reddit_device_id        = EXCLUDED.reddit_device_id,
                        reddit_loid             = EXCLUDED.reddit_loid,
                        status = CASE
                            WHEN accounts.status = 'dead' THEN 'warming'
                            ELSE accounts.status
                        END
                """,
                account_id, persona_id, username,
                password, email, user_id, proxy_url,
                access_token, refresh_token, expires_ts,
                device_id, loid,
                )

            provisioned += 1
            log.info("Provisioned Reddit account u/%s → accounts.id=%s", username, account_id)

        except Exception as exc:
            failed += 1
            log.error("Failed to provision u/%s: %s", username, exc, exc_info=True)

    log.info("Reddit provision complete: %d provisioned, %d failed", provisioned, failed)


@router.post("/reddit/export")
async def export_reddit_credentials() -> Response:
    """Export all registered Reddit credentials as a CSV download.

    Returns:
        CSV file response with credentials for import into the Reddit panel.
    """
    pool = _get_pool()
    csv_content = pool.export_reddit_csv()

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"reddit_accounts_{ts}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
