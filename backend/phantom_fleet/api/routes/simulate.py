"""Reality-anchored simulate() — moonshot #5 HTTP surface.

Exposes core.simulate as two POST endpoints the Staffroom MCP server can
proxy. Kept POST (not GET) so briefs with newlines / long text travel
cleanly in a JSON body.

Endpoints:
  POST /api/simulate/fleet_shape       {n?}
  POST /api/simulate/action_sequence   {brief, limit?, cohort_hint?}

Both are side-effect-free and cheap (the whole pipeline aims to stay
under 2s so a worker can call it in the middle of a tool loop).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.simulate import (
    simulate_action_sequence,
    simulate_fleet_shape_async,
)

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


class _FleetShapeIn(BaseModel):
    n: int = Field(default=10_000, ge=1000, le=10_000)


class _ActionSeqIn(BaseModel):
    brief: str = Field(..., min_length=3, max_length=16_000)
    limit: int = Field(default=5, ge=1, le=20)
    cohort_hint: Optional[str] = None


@router.post("/fleet_shape")
async def fleet_shape(body: _FleetShapeIn) -> dict:
    return await simulate_fleet_shape_async(body.n)


@router.post("/action_sequence")
async def action_sequence(body: _ActionSeqIn) -> dict:
    return simulate_action_sequence(
        brief=body.brief,
        limit=body.limit,
        cohort_hint=body.cohort_hint,
    )


class _GhostPreviewIn(BaseModel):
    """Brief-based ghost preview — for workers exploring a hypothetical
    action before dispatch. For an existing mission use the staffroom
    route /api/platforms/staffroom/missions/{id}/ghost-preview instead."""
    brief: str = Field(..., min_length=3, max_length=16_000)
    mission_id: Optional[str] = Field(default=None, max_length=64)


@router.post("/ghost_preview")
async def ghost_preview(body: _GhostPreviewIn) -> dict:
    """Moonshot #2 — shadow-execution dry run against a brief.
    Used by workers to preview the outcome shape BEFORE they dispatch."""
    import asyncio
    from ...core.ghost_preview import preview_mission
    mid = body.mission_id or "hypothetical-preview"
    return await asyncio.to_thread(preview_mission, mid, body.brief)
