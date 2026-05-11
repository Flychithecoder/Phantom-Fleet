"""
IG Intelligence routes — competitor harvesting, lookalike targeting, and
engagement health monitoring.

Endpoints:
    GET  /api/ig/competitors              — list competitor registry
    POST /api/ig/competitors              — add competitor
    POST /api/ig/competitors/harvest      — trigger harvest run
    GET  /api/ig/targets/lookalikes       — get cached lookalike candidates
    POST /api/ig/targets/lookalikes       — generate lookalike list
    GET  /api/ig/health                   — engagement health across all accounts
    GET  /api/ig/health/{account_id}      — single account ER report
    POST /api/ig/health/guardian/run      — trigger guardian check for one account

These routes surface the intelligence layer. Actual agent logic lives in
the specialist agents — routes are thin input validation + dispatch only.

The CompetitorRegistry is held on app.state.ig_competitor_registry.
Reports from the guardian are cached on app.state.ig_guardian_reports
(dict[account_id, report_dict]).
Lookalike candidates are cached on app.state.ig_lookalike_candidates
(list[dict]).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.competitor_registry import CompetitorRegistry, CompetitorEntry
from ...agents.specialists.ig_competitor_harvester_agent import (
    IGCompetitorHarvesterAgent,
    HarvestedCandidate,
)
from ...agents.specialists.ig_lookalike_agent import (
    IGLookalikeAgent,
    ProfileSignature,
)
from ...agents.specialists.ig_engagement_guardian_agent import (
    IGEngagementGuardianAgent,
    EngagementStatus,
)

log = logging.getLogger("phantom_fleet.api.ig_intelligence")

router = APIRouter()


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------


class CompetitorEntryOut(BaseModel):
    handle:              str
    user_id:             Optional[str]
    niche:               str
    follower_count:      int
    last_harvested_iso:  Optional[str]
    harvest_count:       int


class CompetitorListOut(BaseModel):
    competitors: list[CompetitorEntryOut]
    total:       int
    due_count:   int   # competitors currently due for harvest (cooldown elapsed)


class AddCompetitorIn(BaseModel):
    handle:         str
    niche:          str
    follower_count: int = 0


class AddCompetitorOut(BaseModel):
    handle:  str
    niche:   str
    created: bool   # False if already existed


class HarvestTriggerIn(BaseModel):
    handles:              Optional[list[str]] = None   # None = all due competitors
    max_per_competitor:   int                 = 500
    cooldown_days:        int                 = 7


class HarvestTriggerOut(BaseModel):
    queued_handles:    list[str]
    message:           str


class LookalikeListOut(BaseModel):
    candidates:     list[dict]
    total:          int
    signature:      Optional[dict]


class LookalikeGenerateIn(BaseModel):
    converter_profiles: list[dict]   = Field(default_factory=list)
    seed_candidates:    list[dict]   = Field(default_factory=list)
    top_n:              int          = 300


class LookalikeGenerateOut(BaseModel):
    candidates_scored:   int
    candidates_selected: int
    signature:           Optional[dict]
    candidates:          list[dict]


class AccountHealthOut(BaseModel):
    account_id:          str
    current_er_pct:      Optional[float]
    previous_er_pct:     Optional[float]
    status:              Optional[str]
    trend:               Optional[str]
    actions_taken:       list[str]
    escalation_required: bool
    shadowban_detected:  bool


class HealthSummaryOut(BaseModel):
    accounts:      list[AccountHealthOut]
    total:         int
    healthy:       int
    warning:       int
    suppressed:    int
    recovering:    int
    escalate_now:  list[str]   # account_ids requiring immediate attention


class GuardianRunIn(BaseModel):
    account_id:     str
    follower_count: int = 1
    hashtag_check:  Optional[str] = None


class GuardianRunOut(BaseModel):
    account_id:          str
    status:              str
    current_er_pct:      float
    actions_taken:       list[str]
    escalation_required: bool
    shadowban_detected:  bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_out(entry: CompetitorEntry) -> CompetitorEntryOut:
    return CompetitorEntryOut(
        handle             = entry.handle,
        user_id            = entry.user_id,
        niche              = entry.niche,
        follower_count     = entry.follower_count,
        last_harvested_iso = entry.last_harvested_iso,
        harvest_count      = entry.harvest_count,
    )


def _get_registry(request: Request) -> CompetitorRegistry:
    registry: Optional[CompetitorRegistry] = getattr(
        request.app.state, "ig_competitor_registry", None
    )
    if registry is None:
        # Lazy-init if not bootstrapped at startup
        registry = CompetitorRegistry()
        request.app.state.ig_competitor_registry = registry
    return registry


def _get_guardian_reports(request: Request) -> dict[str, dict]:
    reports = getattr(request.app.state, "ig_guardian_reports", None)
    if reports is None:
        reports = {}
        request.app.state.ig_guardian_reports = reports
    return reports


def _get_lookalike_cache(request: Request) -> dict:
    cache = getattr(request.app.state, "ig_lookalike_cache", None)
    if cache is None:
        cache = {"candidates": [], "signature": None}
        request.app.state.ig_lookalike_cache = cache
    return cache


def _report_to_out(report_dict: dict) -> AccountHealthOut:
    return AccountHealthOut(
        account_id          = report_dict.get("account_id", ""),
        current_er_pct      = report_dict.get("current_er_pct"),
        previous_er_pct     = report_dict.get("previous_er_pct"),
        status              = report_dict.get("status"),
        trend               = report_dict.get("trend"),
        actions_taken       = report_dict.get("actions_taken", []),
        escalation_required = report_dict.get("escalation_required", False),
        shadowban_detected  = report_dict.get("shadowban_detected", False),
    )


# ---------------------------------------------------------------------------
# Competitor routes
# ---------------------------------------------------------------------------


@router.get("/competitors", response_model=CompetitorListOut)
async def list_competitors(request: Request) -> CompetitorListOut:
    """Return all registered competitors with their harvest history."""
    registry = _get_registry(request)
    all_entries = registry.all()
    due         = registry.get_due_for_harvest()
    return CompetitorListOut(
        competitors = [_entry_out(e) for e in all_entries],
        total       = len(all_entries),
        due_count   = len(due),
    )


@router.post("/competitors", response_model=AddCompetitorOut)
async def add_competitor(body: AddCompetitorIn, request: Request) -> AddCompetitorOut:
    """Register a new competitor for follower harvesting."""
    registry = _get_registry(request)
    handle   = body.handle.lstrip("@").lower()
    existed  = registry.get(handle) is not None
    registry.add(handle, niche=body.niche, follower_count=body.follower_count)
    return AddCompetitorOut(handle=handle, niche=body.niche, created=not existed)


@router.post("/competitors/harvest", response_model=HarvestTriggerOut)
async def trigger_harvest(
    body:    HarvestTriggerIn,
    request: Request,
) -> HarvestTriggerOut:
    """
    Trigger a competitor follower harvest run.

    If body.handles is provided, harvest those specific handles.
    Otherwise harvests all competitors whose cooldown has elapsed.

    The actual heavy-lifting (API calls, pagination) is done by
    IGCompetitorHarvesterAgent which should be dispatched to a background
    worker in production. Here we return the queued handles immediately
    so the caller can poll for results.
    """
    registry = _get_registry(request)

    if body.handles:
        handles = [h.lstrip("@").lower() for h in body.handles]
        # Ensure all requested handles are registered
        for h in handles:
            if registry.get(h) is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Competitor {h!r} not registered. POST /api/ig/competitors first.",
                )
    else:
        due     = registry.get_due_for_harvest(cooldown_days=body.cooldown_days)
        handles = [e.handle for e in due]

    if not handles:
        return HarvestTriggerOut(
            queued_handles = [],
            message        = "No competitors due for harvest. Adjust cooldown_days or add competitors.",
        )

    log.info("[ig_intelligence] Harvest queued for %d competitors: %s", len(handles), handles)

    return HarvestTriggerOut(
        queued_handles = handles,
        message        = (
            f"Harvest queued for {len(handles)} competitor(s). "
            "Dispatch IGCompetitorHarvesterAgent with these handles."
        ),
    )


# ---------------------------------------------------------------------------
# Lookalike routes
# ---------------------------------------------------------------------------


@router.get("/targets/lookalikes", response_model=LookalikeListOut)
async def get_lookalikes(request: Request) -> LookalikeListOut:
    """Return the most recently generated lookalike candidates."""
    cache = _get_lookalike_cache(request)
    candidates = cache.get("candidates", [])
    return LookalikeListOut(
        candidates = candidates,
        total      = len(candidates),
        signature  = cache.get("signature"),
    )


@router.post("/targets/lookalikes", response_model=LookalikeGenerateOut)
async def generate_lookalikes(
    body:    LookalikeGenerateIn,
    request: Request,
) -> LookalikeGenerateOut:
    """
    Generate a fresh lookalike candidate list from converter profiles.

    Runs IGLookalikeAgent synchronously and caches the result for
    subsequent GET requests.
    """
    if not body.converter_profiles:
        raise HTTPException(
            status_code=422,
            detail="converter_profiles is required and must be non-empty.",
        )

    agent = IGLookalikeAgent()

    # Build a minimal task object
    class _Task:
        task_id = "lookalike_api"
        params  = {
            "converter_profiles": body.converter_profiles,
            "seed_candidates":    body.seed_candidates,
            "top_n":              body.top_n,
            "already_seen":       set(),
        }

    result = await agent.find_lookalikes(_Task())

    if not result.success:
        raise HTTPException(
            status_code=422,
            detail=result.error or "Lookalike generation failed",
        )

    data       = result.data
    candidates = data.get("candidates", [])
    signature  = data.get("signature")

    # Cache for subsequent GETs
    cache = _get_lookalike_cache(request)
    cache["candidates"] = candidates
    cache["signature"]  = signature

    return LookalikeGenerateOut(
        candidates_scored   = data.get("candidates_scored", 0),
        candidates_selected = data.get("candidates_selected", 0),
        signature           = signature,
        candidates          = candidates,
    )


# ---------------------------------------------------------------------------
# Engagement health routes
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthSummaryOut)
async def get_health_all(request: Request) -> HealthSummaryOut:
    """
    Return engagement health summary across all accounts for which a
    guardian report is cached.
    """
    reports = _get_guardian_reports(request)
    outs    = [_report_to_out(r) for r in reports.values()]

    counts = {s.value: 0 for s in EngagementStatus}
    for out in outs:
        if out.status in counts:
            counts[out.status] += 1

    escalate = [o.account_id for o in outs if o.escalation_required]

    return HealthSummaryOut(
        accounts   = outs,
        total      = len(outs),
        healthy    = counts.get("healthy", 0),
        warning    = counts.get("warning", 0),
        suppressed = counts.get("suppressed", 0),
        recovering = counts.get("recovering", 0),
        escalate_now = escalate,
    )


@router.get("/health/{account_id}", response_model=AccountHealthOut)
async def get_health_account(account_id: str, request: Request) -> AccountHealthOut:
    """Return the most recent engagement guardian report for a single account."""
    reports = _get_guardian_reports(request)
    report  = reports.get(account_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No guardian report for account {account_id!r}. Run POST /api/ig/health/guardian/run first.",
        )
    return _report_to_out(report)


@router.post("/health/guardian/run", response_model=GuardianRunOut)
async def run_guardian(
    body:    GuardianRunIn,
    request: Request,
) -> GuardianRunOut:
    """
    Trigger an engagement guardian check for a single account.

    Requires the account's IGSession to be available on app.state.ig_sessions
    (dict[account_id, IGSession]). In production the session provisioner
    populates this dict.
    """
    sessions = getattr(request.app.state, "ig_sessions", {})
    session  = sessions.get(body.account_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No active IGSession for account {body.account_id!r}. "
                "Ensure the account is provisioned before running the guardian."
            ),
        )

    state_sidecar = getattr(request.app.state, "ig_guardian_state", {})
    if not hasattr(request.app.state, "ig_guardian_state"):
        request.app.state.ig_guardian_state = state_sidecar

    agent = IGEngagementGuardianAgent()

    class _Task:
        task_id = f"guardian_{body.account_id}"
        params  = {
            "account_id":     body.account_id,
            "session":        session,
            "follower_count": body.follower_count,
            "state_sidecar":  state_sidecar,
            "hashtag_check":  body.hashtag_check,
        }

    result = await agent.check_account_health(_Task())

    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=f"Guardian check failed: {result.error}",
        )

    # Cache report for subsequent GETs
    reports = _get_guardian_reports(request)
    reports[body.account_id] = result.data

    data = result.data
    return GuardianRunOut(
        account_id          = data["account_id"],
        status              = data["status"],
        current_er_pct      = data["current_er_pct"],
        actions_taken       = data["actions_taken"],
        escalation_required = data["escalation_required"],
        shadowban_detected  = data["shadowban_detected"],
    )
