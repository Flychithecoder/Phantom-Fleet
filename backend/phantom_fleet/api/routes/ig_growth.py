"""
IG Growth routes — follow+story engine, A/B tests, reaction rates.

Endpoints:
    GET  /api/ig/growth/sessions/today       — today's follow+story sessions across fleet
    GET  /api/ig/growth/follow-back-rate     — real-time follow-back rate by account/persona
    GET  /api/ig/growth/ab-tests             — list A/B tests
    POST /api/ig/growth/ab-tests             — create new A/B test
    GET  /api/ig/growth/ab-tests/{id}        — get A/B test report
    POST /api/ig/growth/ab-tests/{id}/conclude — mark test complete, declare winner
    GET  /api/ig/growth/story-react-rates    — reaction rates across fleet (should be 5-20%)

Routes are thin: input validation + dispatch to core layer only.
No business logic lives here.

State:
    app.state.ig_ab_test_manager — IGABTestManager singleton (set at startup)
    Session sidecar files are loaded per-request from
    /tmp/phantom_fleet/sidecars/ (ephemeral — daily cleanup expected).
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.ig_ab_test import (
    ABTestConfig,
    ABTestReport,
    ABTestVariant,
    IGABTestManager,
)

log = logging.getLogger("phantom_fleet.api.ig_growth")

router = APIRouter()

# ---------------------------------------------------------------------------
# Default manager (routes can also pull from app.state)
# ---------------------------------------------------------------------------

_default_manager = IGABTestManager()


def _get_manager(request: Request) -> IGABTestManager:
    return getattr(request.app.state, "ig_ab_test_manager", _default_manager)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateABTestRequest(BaseModel):
    name: str = Field(..., description="Human-readable test name")
    account_ids: list[str] = Field(..., description="Account IDs to include in the test")
    start_date_iso: str = Field(..., description="YYYY-MM-DD start date")
    end_date_iso: str = Field(..., description="YYYY-MM-DD end date")
    min_sample_size: int = Field(50, description="Min follows per variant before reporting")


class ABTestConfigOut(BaseModel):
    test_id: str
    name: str
    variant_a_count: int
    variant_b_count: int
    start_date_iso: str
    end_date_iso: str
    min_sample_size: int


class ABTestReportOut(BaseModel):
    test_id: str
    name: str
    metrics_a: dict
    metrics_b: dict
    winner: Optional[str]
    winner_lift_pct: float
    recommendation: str


class FollowStorySessionSummary(BaseModel):
    account_id: str
    date_iso: str
    followed_count: int
    stories_viewed: int
    stories_reacted: int
    follow_backs: int


class FollowBackRateEntry(BaseModel):
    account_id: str
    follows_sent: int
    follow_backs: int
    follow_back_rate: float


class StoryReactRateEntry(BaseModel):
    account_id: str
    story_views: int
    story_reacts: int
    react_rate: float
    within_range: bool   # True if 0.05 <= rate <= 0.20


# ---------------------------------------------------------------------------
# Helpers — load sidecar files
# ---------------------------------------------------------------------------

def _load_all_sidecars(date_iso: str) -> list[dict]:
    base = Path("/tmp/phantom_fleet/sidecars")
    if not base.exists():
        return []
    sidecars: list[dict] = []
    for p in base.glob(f"follow_story_*_{date_iso}.json"):
        try:
            sidecars.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return sidecars


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/sessions/today",
    response_model=list[FollowStorySessionSummary],
    summary="Today's follow+story sessions across fleet",
    description=(
        "Returns a summary of each account's morning follow session and "
        "afternoon story session for today. Data sourced from sidecar files."
    ),
)
async def get_sessions_today() -> list[FollowStorySessionSummary]:
    today = date.today().isoformat()
    sidecars = _load_all_sidecars(today)
    result: list[FollowStorySessionSummary] = []
    for s in sidecars:
        result.append(FollowStorySessionSummary(
            account_id=s.get("account_id", ""),
            date_iso=s.get("date_iso", today),
            followed_count=len(s.get("targets_followed", [])),
            stories_viewed=len(s.get("stories_viewed", [])),
            stories_reacted=len(s.get("stories_reacted", [])),
            follow_backs=s.get("follow_back_count", 0),
        ))
    return result


@router.get(
    "/follow-back-rate",
    response_model=list[FollowBackRateEntry],
    summary="Real-time follow-back rate by account",
    description=(
        "Computes follow_back_rate = follow_backs / follows_sent for each "
        "account today. Returns all accounts with at least one follow sent."
    ),
)
async def get_follow_back_rates() -> list[FollowBackRateEntry]:
    today = date.today().isoformat()
    sidecars = _load_all_sidecars(today)
    result: list[FollowBackRateEntry] = []
    for s in sidecars:
        follows_sent = len(s.get("targets_followed", []))
        if follows_sent == 0:
            continue
        follow_backs = s.get("follow_back_count", 0)
        result.append(FollowBackRateEntry(
            account_id=s.get("account_id", ""),
            follows_sent=follows_sent,
            follow_backs=follow_backs,
            follow_back_rate=follow_backs / follows_sent,
        ))
    return result


@router.get(
    "/story-react-rates",
    response_model=list[StoryReactRateEntry],
    summary="Story reaction rates across fleet",
    description=(
        "Returns the react_rate per account today. Healthy range: 5-20%. "
        "Accounts outside this range may be reacting too often (bot signal) "
        "or not enough (low conversion). "
        "within_range=True means 0.05 <= rate <= 0.20."
    ),
)
async def get_story_react_rates() -> list[StoryReactRateEntry]:
    today = date.today().isoformat()
    sidecars = _load_all_sidecars(today)
    result: list[StoryReactRateEntry] = []
    for s in sidecars:
        story_views = len(s.get("stories_viewed", []))
        if story_views == 0:
            continue
        story_reacts = len(s.get("stories_reacted", []))
        rate = story_reacts / story_views
        result.append(StoryReactRateEntry(
            account_id=s.get("account_id", ""),
            story_views=story_views,
            story_reacts=story_reacts,
            react_rate=round(rate, 4),
            within_range=0.05 <= rate <= 0.20,
        ))
    return result


# ---------------------------------------------------------------------------
# A/B test routes
# ---------------------------------------------------------------------------


@router.get(
    "/ab-tests",
    response_model=list[ABTestConfigOut],
    summary="List A/B tests",
)
async def list_ab_tests(request: Request) -> list[ABTestConfigOut]:
    manager = _get_manager(request)
    configs = manager.list_tests()
    return [
        ABTestConfigOut(
            test_id=c.test_id,
            name=c.name,
            variant_a_count=len(c.variant_a_account_ids),
            variant_b_count=len(c.variant_b_account_ids),
            start_date_iso=c.start_date_iso,
            end_date_iso=c.end_date_iso,
            min_sample_size=c.min_sample_size,
        )
        for c in configs
    ]


@router.post(
    "/ab-tests",
    response_model=ABTestConfigOut,
    status_code=201,
    summary="Create a new A/B test",
    description=(
        "Splits the provided account_ids 50/50 into variant A (Follow+Story-only) "
        "and variant B (Follow+Story+DM) using a stable hash assignment."
    ),
)
async def create_ab_test(request: Request, body: CreateABTestRequest) -> ABTestConfigOut:
    manager = _get_manager(request)
    if not body.account_ids:
        raise HTTPException(status_code=422, detail="account_ids must not be empty")
    if body.start_date_iso >= body.end_date_iso:
        raise HTTPException(status_code=422, detail="end_date_iso must be after start_date_iso")

    config = manager.create_test(
        name=body.name,
        account_ids=body.account_ids,
        start_date_iso=body.start_date_iso,
        end_date_iso=body.end_date_iso,
        min_sample_size=body.min_sample_size,
    )
    return ABTestConfigOut(
        test_id=config.test_id,
        name=config.name,
        variant_a_count=len(config.variant_a_account_ids),
        variant_b_count=len(config.variant_b_account_ids),
        start_date_iso=config.start_date_iso,
        end_date_iso=config.end_date_iso,
        min_sample_size=config.min_sample_size,
    )


@router.get(
    "/ab-tests/{test_id}",
    response_model=ABTestReportOut,
    summary="Get A/B test report",
    description="Returns current metrics and winner (if significant) for the given test.",
)
async def get_ab_test_report(request: Request, test_id: str) -> ABTestReportOut:
    manager = _get_manager(request)
    report = manager.generate_report(test_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"AB test '{test_id}' not found")
    d = report.to_dict()
    return ABTestReportOut(
        test_id=d["test_id"],
        name=d["name"],
        metrics_a=d["metrics_a"],
        metrics_b=d["metrics_b"],
        winner=d.get("winner"),
        winner_lift_pct=d.get("winner_lift_pct", 0.0),
        recommendation=d.get("recommendation", ""),
    )


@router.post(
    "/ab-tests/{test_id}/conclude",
    response_model=ABTestReportOut,
    summary="Conclude a test and declare a winner",
    description=(
        "Marks the test complete and returns the final report. "
        "Persists the conclusion to disk alongside the config."
    ),
)
async def conclude_ab_test(request: Request, test_id: str) -> ABTestReportOut:
    manager = _get_manager(request)
    report = manager.conclude_test(test_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"AB test '{test_id}' not found")
    d = report.to_dict()
    return ABTestReportOut(
        test_id=d["test_id"],
        name=d["name"],
        metrics_a=d["metrics_a"],
        metrics_b=d["metrics_b"],
        winner=d.get("winner"),
        winner_lift_pct=d.get("winner_lift_pct", 0.0),
        recommendation=d.get("recommendation", ""),
    )
