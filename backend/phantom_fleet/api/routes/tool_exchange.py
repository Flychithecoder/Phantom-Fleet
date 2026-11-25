"""Tool exchange HTTP surface — moonshot #3.

A proposal registry. Agents POST /propose; the owner reviews and
approves or rejects. Approval unlocks the discovery surface — it does
NOT auto-execute code. Human wiring still required.

Endpoints:
  POST /api/tool_exchange/propose           {name, description, schema_json, use_case, implementation_hint?, proposed_by}
  GET  /api/tool_exchange/proposals         ?status=&limit=
  GET  /api/tool_exchange/proposals/{id}
  POST /api/tool_exchange/proposals/{id}/approve
  POST /api/tool_exchange/proposals/{id}/reject   {reason}
  GET  /api/tool_exchange/discover
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...core import tool_exchange as tx

router = APIRouter(prefix="/api/tool_exchange", tags=["tool-exchange"])


class _ProposeIn(BaseModel):
    name: str = Field(..., min_length=3, max_length=64)
    description: str = Field(..., min_length=1, max_length=1000)
    input_schema_json: str = Field(..., alias="schema_json", min_length=2, max_length=20_000)
    use_case: str = Field(..., min_length=1, max_length=2000)
    implementation_hint: str = Field(default="", max_length=2000)
    proposed_by: str = Field(..., min_length=1, max_length=120)

    model_config = {"populate_by_name": True}


class _RejectIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


@router.post("/propose")
async def propose(body: _ProposeIn) -> dict:
    try:
        return tx.propose_tool(
            name=body.name,
            description=body.description,
            schema_json=body.input_schema_json,
            use_case=body.use_case,
            implementation_hint=body.implementation_hint,
            proposed_by=body.proposed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/proposals")
async def proposals(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    try:
        return tx.list_proposals(status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str) -> dict:
    try:
        return tx.get_proposal(proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/proposals/{proposal_id}/approve")
async def approve(proposal_id: str) -> dict:
    try:
        return tx.approve_proposal(proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/proposals/{proposal_id}/reject")
async def reject(proposal_id: str, body: _RejectIn) -> dict:
    try:
        return tx.reject_proposal(proposal_id, body.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/discover")
async def discover() -> dict:
    return tx.discover_approved()
