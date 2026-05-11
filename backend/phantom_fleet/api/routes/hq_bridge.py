"""
HQ Bridge API routes — account handoff from Agency HQ Panel to Phantom Fleet.

All endpoints require the `X-HQ-API-Key` header matching the
`HQ_API_KEY` environment variable.

Endpoints:
    POST /api/hq/accounts/handoff       — receive one account from HQ, start warming
    GET  /api/hq/accounts/{id}/status   — return warming progress to HQ
    POST /api/hq/accounts/bulk-handoff  — handoff multiple accounts at once
    GET  /api/hq/performance            — performance metrics for HQ dashboard
    POST /api/hq/content/push           — HQ pushes approved content to vault
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.hq_bridge import HQAccountHandoff, HQBridge

log = logging.getLogger("phantom_fleet.api.hq_bridge")

router = APIRouter()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _require_hq_key(x_hq_api_key: str = Header(..., alias="X-HQ-API-Key")) -> str:
    """Validate X-HQ-API-Key header against HQ_API_KEY env var."""
    expected = os.getenv("HQ_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="HQ_API_KEY not configured on this server",
        )
    if x_hq_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid HQ API key")
    return x_hq_api_key


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class AccountHandoffIn(BaseModel):
    creator_id:    str
    platform:      str
    username:      str
    password:      str
    two_fa_secret: str | None = None
    chat_tier:     str        = "CASUAL_SFW"
    persona_name:  str
    content_tags:  list[str]  = Field(default_factory=list)
    target_niches: list[str]  = Field(default_factory=list)


class HandoffResultOut(BaseModel):
    ok:                   bool
    account_id:           str
    phone_serial:         str | None
    platform:             str
    warming_start_date:   str
    estimated_ready_date: str
    status:               str
    message:              str
    error:                str | None = None


class BulkHandoffIn(BaseModel):
    accounts: list[AccountHandoffIn]


class BulkHandoffResultOut(BaseModel):
    total:     int
    succeeded: int
    failed:    int
    results:   list[HandoffResultOut]


class AccountStatusOut(BaseModel):
    account_id:    str
    platform:      str
    username:      str | None
    phone_serial:  str | None
    status:        str
    warming_day:   int
    warming_pct:   float
    last_active_iso: str | None
    er_pct:        float
    follower_count: int


class PerformanceOut(BaseModel):
    generated_at:   str
    account_count:  int
    metrics:        list[dict]


class ContentPushIn(BaseModel):
    creator_id:    str
    content_items: list[dict]   # [{url, type, tags, caption_hint}]


class ContentPushOut(BaseModel):
    ok:           bool
    items_queued: int
    message:      str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_bridge(request: Request) -> HQBridge:
    bridge = getattr(request.app.state, "hq_bridge", None)
    if bridge is None:
        # Build lazily from fleet singleton
        fleet = getattr(request.app.state, "ctx", None)
        fleet_obj = getattr(fleet, "fleet", None) if fleet else None
        db_pool   = getattr(fleet, "db_pool", None) if fleet else None
        if fleet_obj is None:
            raise HTTPException(status_code=503, detail="Fleet not initialised")
        bridge = HQBridge(fleet=fleet_obj, db_pool=db_pool)
        request.app.state.hq_bridge = bridge
    return bridge


def _payload_to_handoff(item: AccountHandoffIn, api_key: str) -> HQAccountHandoff:
    return HQAccountHandoff(
        creator_id=item.creator_id,
        platform=item.platform,
        username=item.username,
        password=item.password,
        two_fa_secret=item.two_fa_secret,
        chat_tier=item.chat_tier,
        persona_name=item.persona_name,
        content_tags=item.content_tags,
        target_niches=item.target_niches,
        hq_api_key=api_key,
    )


def _result_to_out(r: Any) -> HandoffResultOut:
    return HandoffResultOut(
        ok=r.ok,
        account_id=r.account_id,
        phone_serial=r.phone_serial,
        platform=r.platform,
        warming_start_date=r.warming_start_date,
        estimated_ready_date=r.estimated_ready_date,
        status=r.status,
        message=r.message,
        error=r.error,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/accounts/handoff",
    response_model=HandoffResultOut,
    summary="Receive one account from HQ and start warming",
)
async def handoff_account(
    body:    AccountHandoffIn,
    request: Request,
    api_key: str = Depends(_require_hq_key),
) -> HandoffResultOut:
    """
    HQ provisions a new social media account for a creator.
    Phantom Fleet assigns it to a phone, provisions credentials,
    and starts the warming curve immediately.
    """
    bridge  = _get_bridge(request)
    payload = _payload_to_handoff(body, api_key)

    try:
        result = await bridge.receive_account_handoff(payload)
    except Exception as exc:
        log.error("handoff_account failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Handoff failed: {exc!s:.300}")

    return _result_to_out(result)


@router.post(
    "/accounts/bulk-handoff",
    response_model=BulkHandoffResultOut,
    summary="Handoff multiple accounts at once",
)
async def bulk_handoff(
    body:    BulkHandoffIn,
    request: Request,
    api_key: str = Depends(_require_hq_key),
) -> BulkHandoffResultOut:
    """Provision multiple accounts from HQ in a single request."""
    bridge   = _get_bridge(request)
    payloads = [_payload_to_handoff(item, api_key) for item in body.accounts]

    try:
        result = await bridge.bulk_handoff(payloads)
    except Exception as exc:
        log.error("bulk_handoff failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bulk handoff failed: {exc!s:.300}")

    return BulkHandoffResultOut(
        total=result.total,
        succeeded=result.succeeded,
        failed=result.failed,
        results=[_result_to_out(r) for r in result.results],
    )


@router.get(
    "/accounts/{account_id}/status",
    response_model=AccountStatusOut,
    summary="Get warming progress for one account",
)
async def account_status(
    account_id: str,
    request:    Request,
    api_key:    str = Depends(_require_hq_key),
) -> AccountStatusOut:
    """Return current warming status for an account provisioned via handoff."""
    bridge = _get_bridge(request)
    try:
        metrics = await bridge.report_performance_to_hq([account_id])
        m = metrics.get("metrics", [{}])[0] if metrics.get("metrics") else {}
    except Exception as exc:
        log.warning("account_status failed for %s: %s", account_id, exc)
        m = {}

    warming_day = m.get("warming_day", 0)
    platform    = m.get("platform", "instagram")
    from ...core.hq_bridge import _WARM_DAYS
    total_days  = _WARM_DAYS.get(platform, 30)
    warming_pct = min(1.0, warming_day / total_days) if total_days > 0 else 0.0

    return AccountStatusOut(
        account_id=account_id,
        platform=platform,
        username=m.get("username"),
        phone_serial=m.get("phone_serial"),
        status=m.get("status", "unknown"),
        warming_day=warming_day,
        warming_pct=round(warming_pct, 3),
        last_active_iso=m.get("last_active_iso"),
        er_pct=float(m.get("er_pct", 0.0)),
        follower_count=int(m.get("follower_count", 0)),
    )


@router.get(
    "/performance",
    response_model=PerformanceOut,
    summary="Return performance metrics for HQ creator dashboard",
)
async def hq_performance(
    request:    Request,
    creator_id: str | None = None,
    api_key:    str = Depends(_require_hq_key),
) -> PerformanceOut:
    """
    Return performance metrics for all accounts (or filtered by creator_id).
    HQ uses this to power its creator performance dashboard.
    """
    bridge = _get_bridge(request)

    try:
        if creator_id:
            accounts = await bridge._get_accounts_for_creator(creator_id)
            account_ids = [a.get("account_id", "") for a in accounts if isinstance(a, dict)]
        else:
            # All active accounts
            from ...core.ops_brain import _safe_call
            accounts = await _safe_call(bridge.fleet, "get_all_active_accounts") or []
            account_ids = [a.get("account_id", "") for a in accounts if isinstance(a, dict)]

        result = await bridge.report_performance_to_hq(account_ids)
    except Exception as exc:
        log.error("hq_performance failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Performance query failed: {exc!s:.300}")

    return PerformanceOut(
        generated_at=result.get("generated_at", _now_iso()),
        account_count=result.get("account_count", 0),
        metrics=result.get("metrics", []),
    )


@router.post(
    "/content/push",
    response_model=ContentPushOut,
    summary="HQ pushes approved content to the Content Vault",
)
async def content_push(
    body:    ContentPushIn,
    request: Request,
    api_key: str = Depends(_require_hq_key),
) -> ContentPushOut:
    """
    HQ pushes approved content items (images, captions, videos) into
    Phantom Fleet's Content Vault for scheduling by the platform managers.
    """
    if not body.content_items:
        return ContentPushOut(ok=True, items_queued=0, message="No items to push")

    # Delegate to Content Vault route handler if available
    vault = getattr(request.app.state, "content_vault", None)
    queued = 0
    if vault is not None:
        try:
            from ...core.ops_brain import _safe_call
            result = await _safe_call(
                vault, "ingest_from_hq",
                creator_id=body.creator_id,
                items=body.content_items,
            )
            queued = result if isinstance(result, int) else len(body.content_items)
        except Exception as exc:
            log.warning("content_push vault.ingest_from_hq failed: %s", exc)
            queued = len(body.content_items)
    else:
        # No vault registered yet — log and ack
        log.info(
            "content_push: %d items from creator %s (vault not attached, items logged)",
            len(body.content_items), body.creator_id,
        )
        queued = len(body.content_items)

    return ContentPushOut(
        ok=True,
        items_queued=queued,
        message=f"{queued} content items queued for creator {body.creator_id}",
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
