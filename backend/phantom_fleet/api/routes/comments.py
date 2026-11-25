"""Comment-generation HTTP surface.

POST /api/comments/generate  { niche, n, style_hints? }

Calls `core.comment_generator.generate_comments(...)` which routes via
Scaler Pro `cost_quality_router`, runs safety filters, and lands
survivors as `comment_pool.status='needs_approval'`. The response is
the receipt; it NEVER returns `active` rows and NEVER approves. The
owner approves via `/approvals`.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core import comment_generator as cg

router = APIRouter(prefix="/api/comments", tags=["comments"])


class _GenerateIn(BaseModel):
    niche: str = Field(..., min_length=1, max_length=40)
    n: int = Field(..., ge=1, le=200)
    style_hints: list[str] | None = Field(default=None, max_length=20)


@router.post("/generate")
async def generate(body: _GenerateIn) -> dict:
    try:
        receipt = cg.generate_comments(
            niche=body.niche,
            n=body.n,
            style_hints=body.style_hints,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return receipt
