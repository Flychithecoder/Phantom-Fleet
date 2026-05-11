"""
Account replacement routes — dead account detection, spare pool management,
and automated replacement cycle.

Endpoints:
    GET  /api/accounts/dead                    — list dead accounts needing replacement
    POST /api/accounts/replacement/run         — trigger replacement cycle
    GET  /api/accounts/spare-pool              — spare credential pool status
    POST /api/accounts/spare-pool/upload       — upload spare credentials (CSV or JSON)
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from ...agents.specialists.ig_account_replacement_agent import (
    IGAccountReplacementAgent,
    SpareCredentialPool,
    ReplacementCycleResult,
    DeadAccountRecord,
)

log = logging.getLogger("phantom_fleet.api.replacement")

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory spare credential pool (persisted to app.state in production)
# ---------------------------------------------------------------------------

# Module-level store; tests can monkey-patch _spare_pool() to inject data.
_SPARE_POOL: SpareCredentialPool = SpareCredentialPool()


def _spare_pool() -> SpareCredentialPool:
    return _SPARE_POOL


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DeadAccountOut(BaseModel):
    account_id: str
    username: str
    phone_serial: str
    clone_package: str
    died_at_iso: str
    cause: str
    warming_day: int
    funnel_enrollments: list[str]
    replacement_account_id: Optional[str]


class DeadAccountListOut(BaseModel):
    dead_accounts: list[DeadAccountOut]
    total: int


class SparePoolStatusOut(BaseModel):
    total_spares: int
    is_healthy: bool
    min_pool_size: int
    status: str  # "healthy" | "low" | "empty"


class ReplacementRunOut(BaseModel):
    accounts_replaced: int
    accounts_pending: int
    spare_pool_remaining: int
    escalated_pool_low: bool
    replaced_pairs: list[dict]
    errors: list[str]
    run_at_iso: str


class SpareUploadOut(BaseModel):
    uploaded: int
    total_pool_size: int
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dead_record_to_out(r: DeadAccountRecord) -> DeadAccountOut:
    return DeadAccountOut(
        account_id=r.account_id,
        username=r.username,
        phone_serial=r.phone_serial,
        clone_package=r.clone_package,
        died_at_iso=r.died_at_iso,
        cause=r.cause,
        warming_day=r.warming_day,
        funnel_enrollments=r.funnel_enrollments,
        replacement_account_id=r.replacement_account_id,
    )


def _build_agent(request: Request) -> IGAccountReplacementAgent:
    """
    Construct the replacement agent with the app's real dependencies.
    In tests, request.app.state.ctx provides mock repos.
    """
    ctx = getattr(request.app.state, "ctx", None)
    account_repo = getattr(ctx, "account_repo", None) if ctx else None
    provisioner = getattr(ctx, "provisioner", None) if ctx else None
    funnel_repo = getattr(ctx, "funnel_repo", None) if ctx else None

    if account_repo is None or provisioner is None:
        raise HTTPException(
            status_code=503,
            detail="Account repo or provisioner not initialised — check app startup.",
        )

    return IGAccountReplacementAgent(
        account_repo=account_repo,
        provisioner=provisioner,
        funnel_repo=funnel_repo,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/dead", response_model=DeadAccountListOut)
async def list_dead_accounts(request: Request) -> DeadAccountListOut:
    """
    List all dead Instagram accounts that have not yet been replaced.

    Also surfaces accounts that have been inactive for 72+ hours and whose
    session ping fails.
    """
    agent = _build_agent(request)
    dead = await agent.detect_dead_accounts()
    return DeadAccountListOut(
        dead_accounts=[_dead_record_to_out(r) for r in dead],
        total=len(dead),
    )


@router.post("/replacement/run", response_model=ReplacementRunOut)
async def run_replacement_cycle(request: Request) -> ReplacementRunOut:
    """
    Trigger one replacement cycle.

    - Detects all dead accounts.
    - Provisions replacements from the spare pool (max 10 per cycle).
    - Transfers funnel enrollments (step reset to 0).
    - Escalates if spare pool < 5.

    Returns a full cycle report.
    """
    agent = _build_agent(request)
    pool = _spare_pool()
    result: ReplacementCycleResult = await agent.run_replacement_cycle(pool)

    return ReplacementRunOut(
        accounts_replaced=result.accounts_replaced,
        accounts_pending=result.accounts_pending,
        spare_pool_remaining=result.spare_pool_remaining,
        escalated_pool_low=result.escalated_pool_low,
        replaced_pairs=result.replaced_pairs,
        errors=result.errors,
        run_at_iso=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/spare-pool", response_model=SparePoolStatusOut)
async def get_spare_pool_status() -> SparePoolStatusOut:
    """Return the current spare credential pool status."""
    pool = _spare_pool()
    total = len(pool.credentials)

    if total == 0:
        status = "empty"
    elif not pool.is_healthy:
        status = "low"
    else:
        status = "healthy"

    return SparePoolStatusOut(
        total_spares=total,
        is_healthy=pool.is_healthy,
        min_pool_size=pool.min_pool_size,
        status=status,
    )


@router.post("/spare-pool/upload", response_model=SpareUploadOut)
async def upload_spare_credentials(
    file: UploadFile = File(...),
) -> SpareUploadOut:
    """
    Upload spare credentials as a CSV or JSON file.

    CSV format (with header):
        username,password,two_fa_secret
        account1,pass1,
        account2,pass2,TOTP_SECRET

    JSON format:
        [{"username": "...", "password": "...", "two_fa_secret": "..."}]

    two_fa_secret is optional.
    """
    pool = _spare_pool()

    if file.content_type not in (
        "text/csv",
        "application/json",
        "text/plain",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported content type {file.content_type!r}. "
                "Upload a .csv or .json file."
            ),
        )

    raw = await file.read()
    text = raw.decode("utf-8", errors="replace")

    new_creds: list[dict] = []
    filename = (file.filename or "").lower()

    if filename.endswith(".json") or file.content_type == "application/json":
        import json as _json
        try:
            parsed = _json.loads(text)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=422, detail="JSON must be a list of objects.")
        for row in parsed:
            if not isinstance(row, dict):
                continue
            username = row.get("username", "").strip()
            password = row.get("password", "").strip()
            if username and password:
                new_creds.append({
                    "username": username,
                    "password": password,
                    "two_fa_secret": row.get("two_fa_secret", "") or "",
                })
    else:
        # CSV
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            username = (row.get("username") or "").strip()
            password = (row.get("password") or "").strip()
            if username and password:
                new_creds.append({
                    "username": username,
                    "password": password,
                    "two_fa_secret": (row.get("two_fa_secret") or "").strip(),
                })

    if not new_creds:
        raise HTTPException(
            status_code=422,
            detail="No valid credentials found in uploaded file. "
                   "Ensure the file has 'username' and 'password' columns.",
        )

    pool.credentials.extend(new_creds)

    log.info("Uploaded %d spare credentials. Pool total: %d", len(new_creds), len(pool.credentials))

    return SpareUploadOut(
        uploaded=len(new_creds),
        total_pool_size=len(pool.credentials),
        message=f"Uploaded {len(new_creds)} credentials. Pool is now {'healthy' if pool.is_healthy else 'low'}.",
    )
