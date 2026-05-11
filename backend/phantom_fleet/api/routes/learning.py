"""
Learning engine routes — outcome recording and insight API.

Endpoints:
    POST   /api/learning/outcome          — record an action outcome
    GET    /api/learning/insights         — list insights (filterable by category)
    GET    /api/learning/context          — get prompt-ready context block for injection
    POST   /api/learning/analyze          — trigger analysis cycle (background)
    DELETE /api/learning/insights/{id}    — deprecate an insight
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.learning")
router = APIRouter()


class RecordOutcomeRequest(BaseModel):
    action_type: str            # e.g. "threads_follow", "threads_post", "dm_reply"
    outcome_score: float        # 0.0-1.0 (1.0 = perfect outcome)
    account_id: Optional[str] = None
    context: Optional[str] = None
    metadata: Optional[dict] = None

class ContextRequest(BaseModel):
    context: str                # e.g. "threads_post_acct_001"
    categories: Optional[list[str]] = None


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


@router.post("/outcome")
async def record_outcome(body: RecordOutcomeRequest, request: Request):
    from ...core.learning_engine import record_outcome
    pool = _pool(request)
    await record_outcome(
        pool,
        action_type=body.action_type,
        outcome_score=body.outcome_score,
        account_id=body.account_id,
        context=body.context,
        metadata=body.metadata,
    )
    return {"recorded": True}


@router.get("/insights")
async def list_insights(
    request: Request,
    category: Optional[str] = None,
    min_confidence: float = 0.0,
    limit: int = 50,
):
    async with _pool(request).acquire() as conn:
        if category:
            rows = await conn.fetch(
                """
                SELECT * FROM learning_insights
                WHERE category=$1 AND status='active' AND confidence >= $2
                ORDER BY confidence DESC, times_applied DESC
                LIMIT $3
                """,
                category, min_confidence, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM learning_insights
                WHERE status='active' AND confidence >= $1
                ORDER BY confidence DESC, times_applied DESC
                LIMIT $2
                """,
                min_confidence, limit,
            )
        return {"insights": [dict(r) for r in rows], "count": len(rows)}


@router.post("/context")
async def get_learning_context(body: ContextRequest, request: Request):
    from ...core.learning_engine import get_learning_context
    pool = _pool(request)
    result = await get_learning_context(
        pool,
        context=body.context,
        categories=body.categories,
    )
    return result


@router.post("/analyze")
async def trigger_analysis(request: Request):
    import asyncio
    from ...core.learning_engine import analyze
    pool = _pool(request)
    asyncio.create_task(analyze(pool))
    return {"ok": True, "message": "Analysis cycle started in background"}


@router.delete("/insights/{insight_id}")
async def deprecate_insight(insight_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM learning_insights WHERE id=$1", insight_id)
        if not row:
            raise HTTPException(404, "Insight not found")
        await conn.execute(
            "UPDATE learning_insights SET status='deprecated' WHERE id=$1", insight_id
        )
        return {"success": True}
