"""Fleet-side routes for the Staffroom mission system of record.

Mounted under `/api/platforms/staffroom`. See
`backend/phantom_fleet/platforms/staffroom.py` for the StaffroomClient and
MissionStore. The store is constructed in app lifespan and attached to
`request.app.state.staffroom`.

Pilot stays read-only against Fleet. These routes only talk to Staffroom
over HTTP and surface the mission state back to the Fleet UI; they do not
touch devices or billing.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/platforms/staffroom", tags=["staffroom"])


def _store(request: Request):
    store = getattr(request.app.state, "staffroom", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Staffroom integration not initialised")
    return store


class _DispatchIn(BaseModel):
    workflow: str
    seed: Optional[str] = None
    standing_grant: Optional[str] = None
    role: Optional[str] = None
    team: str = "claude"  # "claude" (default) or "glm"


class _AdoptIn(BaseModel):
    request_id: str
    staffroom_mission_id: str
    workflow: str


class _CadenceTickIn(BaseModel):
    force: bool = False


class _CadenceToggleIn(BaseModel):
    grant_name: str
    disabled: bool = True


@router.get("/missions/summary")
async def missions_summary(request: Request) -> dict:
    return _store(request).summary()


@router.post("/missions/dispatch")
async def missions_dispatch(request: Request, body: _DispatchIn) -> dict:
    store = _store(request)
    try:
        rec = store.dispatch(
            body.workflow, body.seed,
            standing_grant=body.standing_grant,
            role=body.role,
            team=body.team,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return rec.as_dict()


@router.get("/roster")
async def roster_get(request: Request) -> dict:
    return _store(request).roster()


@router.get("/roster/{team}")
async def roster_by_team(request: Request, team: str) -> dict:
    """Return the named team's roster. 'claude' = main; 'glm' = GLM-plan."""
    store = _store(request)
    try:
        return store.roster_for_team(team)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/research-grants")
async def research_grants_get(request: Request) -> dict:
    """Role × research-tool grants (internet_search, page_reader,
    site_crawler, treg scope, daily budget).  Authoritative decision lives
    in Staffroom's MCP token scope; this endpoint lets the Fleet UI show
    which roles are expected to be able to do which research."""
    from ...platforms.staffroom import RESEARCH_GRANTS
    return {"grants": RESEARCH_GRANTS}


@router.get("/cadences")
async def cadences_list(request: Request) -> dict:
    return {"cadences": _store(request).cadence_list()}


@router.post("/cadences/tick")
async def cadences_tick(request: Request, body: _CadenceTickIn) -> dict:
    return {"results": _store(request).cadence_tick(force=body.force)}


@router.post("/cadences/toggle")
async def cadences_toggle(request: Request, body: _CadenceToggleIn) -> dict:
    store = _store(request)
    try:
        return {"state": store.cadence_disable(body.grant_name, body.disabled)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/missions/{request_id}")
async def mission_get(request: Request, request_id: str) -> dict:
    store = _store(request)
    rec = store.get(request_id)
    if not rec:
        raise HTTPException(status_code=404, detail="no such mission")
    return rec.as_dict()


@router.post("/missions/{request_id}/refresh")
async def mission_refresh(request: Request, request_id: str) -> dict:
    store = _store(request)
    rec = store.refresh(request_id)
    if not rec:
        raise HTTPException(status_code=404, detail="no such mission")
    return rec.as_dict()


@router.get("/missions/{request_id}/ghost-preview")
async def mission_ghost_preview(request: Request, request_id: str) -> dict:
    """Moonshot #2 — shadow-execution dry run (v1 static).

    Produces an owner-facing preview card BEFORE approval: snapshots the
    Staffroom DB, scans the brief for expected tool calls, reads Causal
    Fleet Memory for historical outcome / approval rates on the same
    workflow, calls simulate_action_sequence for reality-anchored
    outcome prediction, and flags artifact conflicts.

    Read-only; never spawns a claude subprocess. The v2 upgrade (live
    fork against the snapshot) will keep this endpoint shape.
    """
    import asyncio
    from ...core.ghost_preview import preview_mission
    store = _store(request)
    rec = store.get(request_id)
    if not rec:
        raise HTTPException(status_code=404, detail="no such mission")
    mid = rec.staffroom_mission_id
    if not mid:
        raise HTTPException(
            status_code=409,
            detail="mission has no staffroom_mission_id yet; dispatch must complete first",
        )
    # Read the brief from Staffroom's sqlite via the preview helper.
    import sqlite3
    from ...core.simulate import _staffroom_db_path
    with sqlite3.connect(_staffroom_db_path()) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT prompt FROM missions WHERE id=?", (mid,)).fetchone()
    if not row or not row["prompt"]:
        raise HTTPException(status_code=404, detail="mission prompt not in Staffroom")
    return await asyncio.to_thread(preview_mission, mid, row["prompt"])


@router.post("/missions/adopt")
async def mission_adopt(request: Request, body: _AdoptIn) -> dict:
    """Bind an existing Staffroom mission to a Fleet request_id.
    Used to re-attach missions created before persistence, or ones created
    directly on Staffroom outside the Fleet dispatch path."""
    store = _store(request)
    rec = store.adopt(body.request_id, body.staffroom_mission_id, body.workflow)
    return rec.as_dict()


@router.get("/missions/{request_id}/open-url")
async def mission_open_url(request: Request, request_id: str) -> dict:
    store = _store(request)
    url = store.open_url(request_id)
    if not url:
        raise HTTPException(status_code=404, detail="no mapped mission yet")
    return {"url": url}
