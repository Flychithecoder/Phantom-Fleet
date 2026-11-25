"""Mission composer HTTP surface — moonshot #7."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.mission_composer import compose_mission

router = APIRouter(prefix="/api/compose", tags=["mission-composer"])


class _ComposeIn(BaseModel):
    workflow: str = Field(..., min_length=1, max_length=80)
    brief: str = Field(..., min_length=1, max_length=32_000)
    role: Optional[str] = Field(default=None, max_length=80)
    mission_id: str = Field(default="composer-hypothetical", max_length=64)


@router.post("/mission")
async def compose(body: _ComposeIn) -> dict:
    import asyncio
    try:
        return await asyncio.to_thread(
            compose_mission,
            workflow=body.workflow,
            brief=body.brief,
            role=body.role,
            mission_id=body.mission_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
