"""Target & comment admission HTTP surface.

Upstream (Treg agents via Staffroom) POSTs candidates; the owner
approves via Staffroom MCP tools; the picker reads 'active' only.

Endpoints:
  POST /api/targets/ingest              {rows: [...], source}
  GET  /api/targets/pending             ?farm_id=&limit=
  POST /api/targets/{id}/approve        {approver}
  POST /api/targets/{id}/reject         {approver, reason}

  POST /api/targets/comments/ingest     {rows: [...], source}
  GET  /api/targets/comments/pending    ?limit=
  POST /api/targets/comments/{id}/approve   {approver}
  POST /api/targets/comments/{id}/reject    {approver, reason}

  GET  /api/targets/pending_counts
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...core import targets_admission as ta

router = APIRouter(prefix="/api/targets", tags=["targets"])


class _TargetRow(BaseModel):
    kind: str = Field(..., pattern="^(account|media)$")
    handle: str = Field(..., min_length=1, max_length=120)
    media_code: Optional[str] = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list)
    locale: Optional[str] = Field(default=None, max_length=16)
    farm_id: Optional[str] = Field(default=None, max_length=64)


class _IngestIn(BaseModel):
    rows: list[_TargetRow]
    source: str = Field(..., min_length=1, max_length=64)


class _ApproveIn(BaseModel):
    approver: str = Field(..., min_length=1, max_length=120)


class _RejectIn(BaseModel):
    approver: str = Field(..., min_length=1, max_length=120)
    reason: str = Field(..., min_length=1, max_length=500)


class _CommentRow(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    niche: str = Field(default="generic", max_length=40)


class _CommentIngestIn(BaseModel):
    rows: list[_CommentRow]
    source: str = Field(..., min_length=1, max_length=64)


# ---- targets ----

@router.post("/ingest")
async def ingest(body: _IngestIn) -> dict:
    return ta.ingest_targets(
        [r.model_dump() for r in body.rows], source=body.source,
    )


@router.get("/pending")
async def pending(
    farm_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return {"rows": ta.list_pending_targets(farm_id=farm_id, limit=limit)}


@router.post("/{target_id}/approve")
async def approve(target_id: int, body: _ApproveIn) -> dict:
    res = ta.approve_target(target_id, body.approver)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("reason"))
    return res


@router.post("/{target_id}/reject")
async def reject(target_id: int, body: _RejectIn) -> dict:
    res = ta.reject_target(target_id, body.approver, body.reason)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("reason"))
    return res


# ---- comments ----

@router.post("/comments/ingest")
async def ingest_comments(body: _CommentIngestIn) -> dict:
    return ta.ingest_comments(
        [r.model_dump() for r in body.rows], source=body.source,
    )


@router.get("/comments/pending")
async def pending_comments(
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return {"rows": ta.list_pending_comments(limit=limit)}


@router.post("/comments/{comment_id}/approve")
async def approve_comment(comment_id: int, body: _ApproveIn) -> dict:
    res = ta.approve_comment(comment_id, body.approver)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("reason"))
    return res


@router.post("/comments/{comment_id}/reject")
async def reject_comment(comment_id: int, body: _RejectIn) -> dict:
    res = ta.reject_comment(comment_id, body.approver, body.reason)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("reason"))
    return res


# ---- signals for owner_brief ----

@router.get("/pending_counts")
async def pending_counts() -> dict:
    return ta.pending_counts()
