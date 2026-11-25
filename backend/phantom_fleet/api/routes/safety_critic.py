"""Safety critic HTTP surface — moonshot #6."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.safety_critic import critique, rule_catalogue

router = APIRouter(prefix="/api/safety", tags=["safety-critic"])


class _CritiqueIn(BaseModel):
    brief: str = Field(..., min_length=1, max_length=32_000)


@router.post("/critique")
async def do_critique(body: _CritiqueIn) -> dict:
    try:
        return critique(body.brief)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/rules")
async def rules() -> dict:
    return rule_catalogue()
