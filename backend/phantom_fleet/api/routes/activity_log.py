"""
Activity log routes — Threads-panel style event feed.

Endpoints:
    GET    /api/activity                 — paginated activity feed (filterable)
    GET    /api/activity/stats           — counts by action/status for today
    DELETE /api/activity                 — prune logs older than N days
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.activity_log")
router = APIRouter()


class PruneRequest(BaseModel):
    older_than_days: int = 30


def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


@router.get("")
async def list_activity(
    request: Request,
    account_id: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    async with _pool(request).acquire() as conn:
        conditions = ["1=1"]
        params: list = []
        idx = 1

        if account_id:
            conditions.append(f"al.account_id=${idx}")
            params.append(account_id)
            idx += 1
        if action:
            conditions.append(f"al.action=${idx}")
            params.append(action)
            idx += 1
        if status:
            conditions.append(f"al.status=${idx}")
            params.append(status)
            idx += 1

        where = " AND ".join(conditions)
        rows = await conn.fetch(
            f"""
            SELECT al.*, a.username
            FROM activity_log al
            LEFT JOIN accounts a ON a.id = al.account_id
            WHERE {where}
            ORDER BY al.created_at DESC
            LIMIT ${idx} OFFSET ${idx+1}
            """,
            *params, limit, offset,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM activity_log al WHERE {where}", *params
        )
        return {"logs": [dict(r) for r in rows], "total": total}


@router.get("/stats")
async def activity_stats(request: Request):
    async with _pool(request).acquire() as conn:
        # Today's counts by action
        action_rows = await conn.fetch(
            """
            SELECT action, COUNT(*) AS n
            FROM activity_log
            WHERE created_at::date = CURRENT_DATE
            GROUP BY action
            ORDER BY n DESC
            """
        )
        # Today's counts by status
        status_rows = await conn.fetch(
            """
            SELECT status, COUNT(*) AS n
            FROM activity_log
            WHERE created_at::date = CURRENT_DATE
            GROUP BY status
            """
        )
        # Total all-time
        total = await conn.fetchval("SELECT COUNT(*) FROM activity_log")
        # Last 24h
        last_24h = await conn.fetchval(
            "SELECT COUNT(*) FROM activity_log WHERE created_at > now() - interval '24 hours'"
        )
        return {
            "total": total,
            "last_24h": last_24h,
            "today_by_action": {r["action"]: r["n"] for r in action_rows},
            "today_by_status": {r["status"]: r["n"] for r in status_rows},
        }


@router.delete("")
async def prune_logs(body: PruneRequest, request: Request):
    async with _pool(request).acquire() as conn:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM activity_log WHERE created_at < now() - ($1 || ' days')::interval",
            str(body.older_than_days),
        )
        await conn.execute(
            "DELETE FROM activity_log WHERE created_at < now() - ($1 || ' days')::interval",
            str(body.older_than_days),
        )
        return {"deleted": n}
