"""
AI Agent routes — per-account autonomous agent control plane.

The AI agent is defined in core/ai_agent.py. These routes are thin
dispatchers: input validation → dispatch to the agent core.

Endpoints:
    GET    /api/ai-agent/status              — status of all running agents
    POST   /api/ai-agent/start/{account_id} — start agent for one account
    POST   /api/ai-agent/stop/{account_id}  — stop agent for one account
    POST   /api/ai-agent/start-all          — start all agents for active accounts
    POST   /api/ai-agent/start-group/{gid}  — start all agents in a group
    POST   /api/ai-agent/stop-all           — stop all agents
    POST   /api/ai-agent/run-once/{acct_id} — single agent tick (sync)
    GET    /api/ai-agent/logs               — activity log for ai_agent actions
    POST   /api/ai-agent/configure          — save global model/key/goal settings
    GET    /api/ai-agent/config             — get global config (key redacted)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.ai_agent")
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConfigureRequest(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    goal: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


def _agent_manager(request: Request):
    """Return the AgentManager singleton from app.state, or a lazily-created one."""
    from ...core.ai_agent import AgentManager
    mgr = getattr(request.app.state, "agent_manager", None)
    if mgr is None:
        mgr = AgentManager()
        request.app.state.agent_manager = mgr
    return mgr


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status")
async def agent_status(request: Request):
    mgr = _agent_manager(request)
    return {"agents": mgr.get_all_statuses()}


@router.post("/start/{account_id}")
async def start_agent(account_id: str, request: Request):
    pool = _pool(request)
    mgr = _agent_manager(request)
    async with pool.acquire() as conn:
        acc = await conn.fetchrow("SELECT id FROM accounts WHERE id=$1", account_id)
        if not acc:
            raise HTTPException(404, "Account not found")
    await mgr.start_agent(account_id, pool)
    return {"success": True}


@router.post("/stop/{account_id}")
async def stop_agent(account_id: str, request: Request):
    mgr = _agent_manager(request)
    mgr.stop_agent(account_id)
    return {"success": True}


@router.post("/start-all")
async def start_all_agents(request: Request):
    pool = _pool(request)
    mgr = _agent_manager(request)
    async with pool.acquire() as conn:
        accs = await conn.fetch("SELECT id FROM accounts WHERE status='active'")
    count = 0
    for acc in accs:
        await mgr.start_agent(acc["id"], pool)
        count += 1
    return {"success": True, "started": count}


@router.post("/start-group/{group_id}")
async def start_group_agents(group_id: str, request: Request):
    pool = _pool(request)
    mgr = _agent_manager(request)
    async with pool.acquire() as conn:
        accs = await conn.fetch(
            "SELECT id FROM accounts WHERE group_id=$1 AND status='active'", group_id
        )
    count = 0
    for acc in accs:
        await mgr.start_agent(acc["id"], pool)
        count += 1
    return {"success": True, "started": count}


@router.post("/stop-all")
async def stop_all_agents(request: Request):
    mgr = _agent_manager(request)
    mgr.stop_all()
    return {"success": True}


@router.post("/run-once/{account_id}")
async def run_once(account_id: str, request: Request):
    pool = _pool(request)
    mgr = _agent_manager(request)
    try:
        result = await mgr.agent_tick(account_id, pool)
        return {"success": True, "result": result}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/logs")
async def agent_logs(request: Request, account_id: Optional[str] = None, limit: int = 50):
    async with _pool(request).acquire() as conn:
        if account_id:
            rows = await conn.fetch(
                """
                SELECT al.*, a.username
                FROM activity_log al
                JOIN accounts a ON a.id = al.account_id
                WHERE al.action = 'ai_agent' AND al.account_id = $1
                ORDER BY al.created_at DESC
                LIMIT $2
                """,
                account_id, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT al.*, a.username
                FROM activity_log al
                JOIN accounts a ON a.id = al.account_id
                WHERE al.action = 'ai_agent'
                ORDER BY al.created_at DESC
                LIMIT $1
                """,
                limit,
            )

    parsed = []
    for r in rows:
        d = dict(r)
        try:
            d["detail"] = json.loads(d.get("message") or "{}")
        except Exception:
            d["detail"] = {}
        parsed.append(d)
    return {"logs": parsed}


@router.post("/configure")
async def configure_agent(body: ConfigureRequest, request: Request):
    pool = _pool(request)
    async with pool.acquire() as conn:
        upsert_sql = """
            INSERT INTO settings (key, value)
            VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()
        """
        if body.model:
            await conn.execute(upsert_sql, "ai_agent_model", body.model)
        if body.api_key:
            await conn.execute(upsert_sql, "openrouter_api_key", body.api_key)
        if body.goal:
            await conn.execute(upsert_sql, "ai_agent_goal", body.goal)
    return {"success": True}


@router.get("/config")
async def get_config(request: Request):
    async with _pool(request).acquire() as conn:
        model   = await conn.fetchval("SELECT value FROM settings WHERE key='ai_agent_model'") or ""
        api_key = await conn.fetchval("SELECT value FROM settings WHERE key='openrouter_api_key'") or ""
        goal    = await conn.fetchval("SELECT value FROM settings WHERE key='ai_agent_goal'") or ""
    return {
        "model":   model,
        "api_key": ("••••••••" + api_key[-4:]) if api_key else "",
        "goal":    goal,
    }
