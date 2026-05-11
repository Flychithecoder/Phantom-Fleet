"""
Comment pod API routes.

Endpoints:
    GET  /api/comment-pods              — list all pods with member counts
    POST /api/comment-pods              — create a new pod
    POST /api/comment-pods/{id}/rotate  — force pod membership rotation
    GET  /api/comment-pods/{id}/stats   — comment counts and engagement lift
    POST /api/comment-pods/auto-assign  — auto-assign accounts to pods by niche

SAFETY NOTES:
    - Pod creation and rotation are non-destructive IG actions — they modify
      only in-memory/DB pod state, not the Instagram platform itself.
    - Comment EXECUTION happens via IGCommentPodAgent.run_pod_comment(), which
      is invoked by the agent scheduler, NOT by these routes.
    - These routes are management-plane only (CLAUDE.md agent-audit: no
      direct write paths from the HTTP surface to the IG API).

State:
    The IGCommentPodAgent singleton is held on app.state.pod_agent (set at
    startup by the app lifespan). Tests inject a fresh agent instance.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ...agents.specialists.ig_comment_pod_agent import IGCommentPodAgent
from ...core.comment_pod import (
    POD_MAX_ACCOUNTS,
    POD_MIN_ACCOUNTS,
    VALID_NICHES,
    CommentPod,
    PodCommentStats,
)

log = logging.getLogger("phantom_fleet.api.comment_pods")

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreatePodRequest(BaseModel):
    account_ids: list[str] = Field(
        ...,
        min_length=POD_MIN_ACCOUNTS,
        max_length=POD_MAX_ACCOUNTS,
        description=f"List of {POD_MIN_ACCOUNTS}-{POD_MAX_ACCOUNTS} internal account IDs",
    )
    niche: str = Field(
        ...,
        description=f"Pod content niche. One of: {sorted(VALID_NICHES)}",
    )

    @field_validator("niche")
    @classmethod
    def niche_must_be_valid(cls, v: str) -> str:
        if v not in VALID_NICHES:
            raise ValueError(f"niche {v!r} not in VALID_NICHES={sorted(VALID_NICHES)}")
        return v

    @field_validator("account_ids")
    @classmethod
    def account_ids_size_check(cls, v: list[str]) -> list[str]:
        if not (POD_MIN_ACCOUNTS <= len(v) <= POD_MAX_ACCOUNTS):
            raise ValueError(
                f"account_ids must have {POD_MIN_ACCOUNTS}-{POD_MAX_ACCOUNTS} items"
            )
        return v


class AutoAssignRequest(BaseModel):
    accounts: list[dict[str, Any]] = Field(
        ...,
        description="List of account dicts with at least 'account_id' and 'niche' keys",
    )
    niche_key: str = Field("niche", description="Key in each account dict for the niche value")
    id_key:    str = Field("account_id", description="Key in each account dict for the account ID")


class PodOut(BaseModel):
    pod_id:           str
    account_ids:      list[str]
    member_count:     int
    niche:            str
    created_at_iso:   str
    last_rotated_iso: str
    needs_rotation:   bool


class PodStatsOut(BaseModel):
    pod_id:            str
    total_comments:    int
    comments_today:    int
    members_active:    int
    avg_delay_seconds: float
    last_activity_iso: Optional[str]
    errors:            list[str]


class PodsListOut(BaseModel):
    pods:  list[PodOut]
    total: int


class CreatePodOut(BaseModel):
    pod:     PodOut
    message: str


class RotateOut(BaseModel):
    pod:     PodOut
    message: str


class AutoAssignOut(BaseModel):
    pods_created: list[PodOut]
    total_pods:   int
    message:      str


# ---------------------------------------------------------------------------
# Dependency — pod agent from app.state
# ---------------------------------------------------------------------------


def _get_pod_agent(request: Request) -> IGCommentPodAgent:
    """
    Return the IGCommentPodAgent singleton from app.state.

    In tests, app.state.pod_agent is set to a fresh IGCommentPodAgent()
    so tests are isolated without mocking the dependency itself.
    """
    agent: Optional[IGCommentPodAgent] = getattr(
        request.app.state, "pod_agent", None
    )
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "IGCommentPodAgent not initialized on app.state.pod_agent. "
                "Check app startup lifespan."
            ),
        )
    return agent


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def _pod_to_out(pod: CommentPod) -> PodOut:
    return PodOut(
        pod_id=pod.pod_id,
        account_ids=pod.account_ids,
        member_count=len(pod.account_ids),
        niche=pod.niche,
        created_at_iso=pod.created_at_iso,
        last_rotated_iso=pod.last_rotated_iso,
        needs_rotation=pod.needs_rotation,
    )


def _stats_to_out(stats: PodCommentStats) -> PodStatsOut:
    return PodStatsOut(
        pod_id=stats.pod_id,
        total_comments=stats.total_comments,
        comments_today=stats.comments_today,
        members_active=stats.members_active,
        avg_delay_seconds=stats.avg_delay_seconds,
        last_activity_iso=stats.last_activity_iso,
        errors=stats.errors,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=PodsListOut)
async def list_pods(
    agent: IGCommentPodAgent = Depends(_get_pod_agent),
) -> PodsListOut:
    """List all comment pods with member counts and rotation status."""
    pods = [_pod_to_out(p) for p in agent.list_pods()]
    return PodsListOut(pods=pods, total=len(pods))


@router.post("", response_model=CreatePodOut, status_code=201)
async def create_pod(
    body: CreatePodRequest,
    agent: IGCommentPodAgent = Depends(_get_pod_agent),
) -> CreatePodOut:
    """
    Create a new comment pod.

    The pod is registered in the agent's in-memory store immediately.
    Persist pod_id to your DB if you need it to survive process restart.
    """
    try:
        pod = agent.create_pod(
            account_ids=body.account_ids,
            niche=body.niche,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    log.info("API: created pod %s niche=%s", pod.pod_id, pod.niche)
    return CreatePodOut(
        pod=_pod_to_out(pod),
        message=f"Pod {pod.pod_id} created with {len(pod.account_ids)} members.",
    )


@router.post("/{pod_id}/rotate", response_model=RotateOut)
async def rotate_pod(
    pod_id: str,
    agent: IGCommentPodAgent = Depends(_get_pod_agent),
) -> RotateOut:
    """
    Force an immediate membership rotation for a pod.

    Shuffles 1-2 members to prevent a fixed A→B→C social-graph motif
    that would form a detectable cluster at fleet scale.
    """
    try:
        pod = agent.rotate_pod(pod_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Pod {pod_id!r} not found.",
        )

    log.info("API: force-rotated pod %s", pod_id)
    return RotateOut(
        pod=_pod_to_out(pod),
        message=f"Pod {pod_id} rotated successfully.",
    )


@router.get("/{pod_id}/stats", response_model=PodStatsOut)
async def get_pod_stats(
    pod_id: str,
    agent: IGCommentPodAgent = Depends(_get_pod_agent),
) -> PodStatsOut:
    """
    Return engagement stats for a single pod.

    Includes total comments posted, today's count, and any errors.
    """
    stats = agent.get_stats(pod_id)
    if stats is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pod {pod_id!r} not found or has no stats yet.",
        )
    return _stats_to_out(stats)


@router.post("/auto-assign", response_model=AutoAssignOut, status_code=201)
async def auto_assign(
    body: AutoAssignRequest,
    agent: IGCommentPodAgent = Depends(_get_pod_agent),
) -> AutoAssignOut:
    """
    Auto-assign a flat list of accounts into pods of 8-12, grouped by niche.

    Accounts whose niche is not in VALID_NICHES are assigned to 'general'.
    Residual accounts (< 8 per niche after filling full pods) are logged
    and skipped — add them to existing pods manually or wait until enough
    accumulate for a full pod.

    Request body::

        {
          "accounts": [
            {"account_id": "acct_001", "niche": "fitness"},
            {"account_id": "acct_002", "niche": "lifestyle"},
            ...
          ]
        }
    """
    if not body.accounts:
        raise HTTPException(status_code=422, detail="accounts list must not be empty")

    try:
        pods = agent.assign_accounts_to_pods(
            accounts=body.accounts,
            niche_key=body.niche_key,
            id_key=body.id_key,
        )
    except Exception as exc:
        log.error("auto_assign error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    log.info("API: auto-assigned %d accounts into %d pods", len(body.accounts), len(pods))
    return AutoAssignOut(
        pods_created=[_pod_to_out(p) for p in pods],
        total_pods=len(pods),
        message=(
            f"Created {len(pods)} pod(s) from {len(body.accounts)} accounts. "
            "Accounts that did not fill a full pod were skipped."
        ),
    )
