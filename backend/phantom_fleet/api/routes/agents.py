"""
Agent status routes.

Endpoints:
    GET /api/agents          — list all manager classes with config
    GET /api/agents/status   — summary of all agent states (last run, cost)
    GET /api/agents/{name}   — single manager detail

These are READ-ONLY status endpoints. Agents are triggered by the ChiefAgentManager
on its schedule, not by direct HTTP calls — keeps the API from being a backdoor
to bypassing the agent mesh's cost/loop/confirmation gates.

If you need to trigger an agent run for debugging, use the existing
POST /api/v1/agents/{name}/run endpoint in the legacy main.py (which
still enforces the same guardrails).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...agents.managers import MANAGER_CLASSES, PLATFORM_META

log = logging.getLogger("phantom_fleet.api.agents")

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory agent run state (populated by agent mesh on completion)
# ---------------------------------------------------------------------------

# agent_name -> last run summary dict. In production this comes from the DB.
_AGENT_RUN_STATE: dict[str, dict] = {}


def _run_state() -> dict[str, dict]:
    return _AGENT_RUN_STATE


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AgentConfigOut(BaseModel):
    name: str
    max_iterations: int
    max_usd_per_run: float
    max_usd_per_session: float
    allowed_tools: list[str]
    confirmation_required_for: list[str]
    supervises: list[str]
    escalates_to: Optional[str]


class AgentLastRunOut(BaseModel):
    run_id: Optional[str]
    status: Optional[str]
    cost_usd: Optional[float]
    started_at: Optional[str]
    ended_at: Optional[str]


class AgentDetailOut(BaseModel):
    name: str
    platform_meta: Optional[dict]
    config: AgentConfigOut
    last_run: AgentLastRunOut


class AgentsListOut(BaseModel):
    agents: list[AgentDetailOut]
    total: int


class AgentsStatusOut(BaseModel):
    """Condensed one-liner per agent for dashboard status widgets."""
    summary: dict[str, dict]   # name -> {status, cost_usd, run_id}
    total_agents: int
    agents_with_recent_run: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_out(cls) -> AgentConfigOut:
    cfg = cls.config
    supervises: list[str] = list(getattr(cfg, "supervises", ()))
    escalates_to: Optional[str] = getattr(cfg, "escalates_to", None)
    return AgentConfigOut(
        name=cfg.name,
        max_iterations=cfg.max_iterations,
        max_usd_per_run=cfg.max_usd_per_run,
        max_usd_per_session=cfg.max_usd_per_session,
        allowed_tools=list(getattr(cfg, "allowed_tools", ())),
        confirmation_required_for=list(getattr(cfg, "confirmation_required_for", ())),
        supervises=supervises,
        escalates_to=escalates_to,
    )


def _last_run_out(name: str) -> AgentLastRunOut:
    state = _run_state().get(name, {})
    return AgentLastRunOut(
        run_id=state.get("run_id"),
        status=state.get("status"),
        cost_usd=state.get("cost_usd"),
        started_at=state.get("started_at"),
        ended_at=state.get("ended_at"),
    )


def _agent_detail(name: str, cls) -> AgentDetailOut:
    return AgentDetailOut(
        name=name,
        platform_meta=PLATFORM_META.get(name),
        config=_config_out(cls),
        last_run=_last_run_out(name),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=AgentsListOut)
async def list_agents() -> AgentsListOut:
    """Return all manager classes with their config and last run info."""
    details = [_agent_detail(name, cls) for name, cls in MANAGER_CLASSES.items()]
    return AgentsListOut(agents=details, total=len(details))


@router.get("/status", response_model=AgentsStatusOut)
async def agents_status() -> AgentsStatusOut:
    """
    One-liner status for every agent manager.
    Used by the dashboard status bar / alert widgets.
    """
    state = _run_state()
    summary: dict[str, dict] = {}
    agents_with_run = 0

    for name in MANAGER_CLASSES:
        run = state.get(name, {})
        summary[name] = {
            "status": run.get("status", "never_run"),
            "cost_usd": run.get("cost_usd", 0.0),
            "run_id": run.get("run_id"),
        }
        if run:
            agents_with_run += 1

    return AgentsStatusOut(
        summary=summary,
        total_agents=len(MANAGER_CLASSES),
        agents_with_recent_run=agents_with_run,
    )


@router.get("/{name}", response_model=AgentDetailOut)
async def get_agent(name: str) -> AgentDetailOut:
    """Return detail for a single named manager agent."""
    cls = MANAGER_CLASSES.get(name)
    if cls is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {name!r} not found. "
                   f"Available: {sorted(MANAGER_CLASSES.keys())}",
        )
    return _agent_detail(name, cls)
