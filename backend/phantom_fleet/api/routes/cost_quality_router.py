"""Cost/Quality router HTTP surface — moonshot #4.

POST /api/router/recommend {workflow, role?} — returns the team
recommendation with every factor that drove it. Read-only.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.cost_quality_router import recommend_team

router = APIRouter(prefix="/api/router", tags=["cost-quality-router"])


class _RecommendIn(BaseModel):
    workflow: str = Field(..., min_length=1, max_length=80)
    role: Optional[str] = Field(default=None, max_length=80)


@router.post("/recommend")
async def recommend(body: _RecommendIn) -> dict:
    try:
        return recommend_team(body.workflow, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
