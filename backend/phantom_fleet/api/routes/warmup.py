"""
Warmup routes — day-based warmup plans for Threads accounts.

Endpoints:
    GET    /api/warmup          — list all active warmup plans with current-day limits
    POST   /api/warmup          — enroll accounts (by accountIds or groupId)
    DELETE /api/warmup/{id}     — deactivate a warmup plan
    POST   /api/warmup/run      — trigger warmup execution (background)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.warmup")
router = APIRouter()


# ---------------------------------------------------------------------------
# Day → action limits (matching JS source)
# ---------------------------------------------------------------------------

def get_day_limits(day_num: int) -> dict:
    if day_num <= 3:
        return {"likes": 10, "follows": 0,   "comments": 0}
    if day_num <= 7:
        return {"likes": 25, "follows": 10,  "comments": 0}
    if day_num <= 14:
        return {"likes": 40, "follows": 25,  "comments": 5}
    if day_num <= 21:
        return {"likes": 60, "follows": 50,  "comments": 10}
    return     {"likes": 80, "follows": 100, "comments": 15}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EnrollRequest(BaseModel):
    account_ids: Optional[list[str]] = None
    group_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_warmup_plans(request: Request):
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch("""
            SELECT wp.*, a.username, a.status AS account_status, g.name AS group_name,
                   (CURRENT_DATE - wp.start_date) + 1 AS current_day
            FROM warmup_plans wp
            JOIN accounts a ON a.id = wp.account_id
            LEFT JOIN groups g ON g.id = a.group_id
            ORDER BY wp.created_at DESC
        """)
        result = []
        for r in rows:
            d = dict(r)
            d["limits"] = get_day_limits(d.get("current_day") or 1)
            result.append(d)
        return {"plans": result}


@router.post("")
async def enroll_warmup(body: EnrollRequest, request: Request):
    async with _pool(request).acquire() as conn:
        targets: list[str] = []
        if body.account_ids:
            targets = body.account_ids
        elif body.group_id:
            rows = await conn.fetch("SELECT id FROM accounts WHERE group_id=$1", body.group_id)
            targets = [r["id"] for r in rows]

        if not targets:
            raise HTTPException(400, "No accounts specified — provide account_ids or group_id")

        today = date.today().isoformat()
        enrolled = 0
        for account_id in targets:
            exists = await conn.fetchrow(
                "SELECT id FROM warmup_plans WHERE account_id=$1 AND is_active=true",
                account_id,
            )
            if exists:
                continue
            await conn.execute(
                """
                INSERT INTO warmup_plans (account_id, start_date, is_active)
                VALUES ($1, $2, true)
                ON CONFLICT DO NOTHING
                """,
                account_id, today,
            )
            enrolled += 1
        return {"enrolled": enrolled}


@router.delete("/{plan_id}")
async def deactivate_warmup(plan_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        await conn.execute("UPDATE warmup_plans SET is_active=false WHERE id=$1", plan_id)
        return {"success": True}


@router.post("/run")
async def run_warmup(request: Request):
    """Trigger warmup execution in background. Returns immediately."""
    pool = _pool(request)
    asyncio.create_task(_run_warmup_background(pool))
    return {"ok": True, "message": "Warmup run started in background"}


# ---------------------------------------------------------------------------
# Warmup execution (background)
# ---------------------------------------------------------------------------

async def _run_warmup_background(pool) -> None:
    """
    For each active warmup plan:
      1. Like N trending posts (day-appropriate limit)
      2. Follow N scraped targets (day-appropriate limit)
    Uses the warmup_phases system for phase-aware caps.
    """
    from ...core.warmup_phases import is_action_allowed

    from ...core.instagram_client import IGSession
    from ...core.threads_client import ThreadsClient
    from ...core.hybrid_runner import PlatformHeaders
    import random as _random

    try:
        async with pool.acquire() as conn:
            plans = await conn.fetch("""
                SELECT wp.*, a.id AS acc_id, a.username, a.status AS acc_status,
                       a.warmup_phase, a.phase_started_at, a.proxy_id,
                       a.sessionid, a.csrftoken, a.mid, a.user_id AS ig_user_id,
                       (CURRENT_DATE - wp.start_date) + 1 AS day_num
                FROM warmup_plans wp
                JOIN accounts a ON a.id = wp.account_id
                WHERE wp.is_active = true AND a.status = 'active'
            """)

        log.info("Warmup: processing %d accounts", len(plans))

        for plan in plans:
            limits = get_day_limits(plan["day_num"] or 1)
            acc_id = plan["acc_id"]

            try:
                # Build session for this account
                session = IGSession(
                    account_id=acc_id,
                    ig_user_id=plan.get("ig_user_id", "") or "",
                    username=plan.get("username", "") or "",
                    session_id=plan.get("sessionid", "") or "",
                    csrftoken=plan.get("csrftoken", "") or "",
                    mid=plan.get("mid", "") or "",
                    ds_user_id=plan.get("ig_user_id", "") or "",
                    headers=PlatformHeaders(),
                )

                # Resolve proxy
                proxy_url: Optional[str] = None
                if plan.get("proxy_id"):
                    async with pool.acquire() as conn:
                        proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", plan["proxy_id"])
                        if proxy:
                            proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"

                # Skip accounts with no session
                if not session.session_id:
                    log.debug("Warmup skip %s: no session", plan["username"])
                    continue

                # Warmup likes from trending posts
                if limits["likes"] > 0:
                    async with pool.acquire() as conn:
                        posts = await conn.fetch(
                            "SELECT media_id FROM trending_posts ORDER BY RANDOM() LIMIT $1",
                            limits["likes"],
                        )
                    liked = 0
                    for p in posts:
                        try:
                            async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                                await client.like(p["media_id"])
                            liked += 1
                            await asyncio.sleep(3.0 + 4.0 * _random.random())
                        except Exception as exc:
                            log.warning("Warmup like %s: %s", plan["username"], exc)
                    log.info("Warmup %s day %d: liked %d posts", plan["username"], plan["day_num"], liked)

                # Warmup follows from scraped targets
                if limits["follows"] > 0:
                    async with pool.acquire() as conn2:
                        targets = await conn2.fetch(
                            """
                            SELECT id, user_id, username
                            FROM scraped_targets
                            WHERE status='pending'
                            ORDER BY source DESC, follower_count DESC
                            LIMIT $1
                            """,
                            limits["follows"],
                        )
                    followed = 0
                    for t in targets:
                        try:
                            async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                                await client.follow(t["user_id"])
                            async with pool.acquire() as conn3:
                                await conn3.execute(
                                    """
                                    UPDATE scraped_targets
                                    SET status='followed', followed_at=now(), followed_by=$1
                                    WHERE id=$2
                                    """,
                                    acc_id, t["id"],
                                )
                            followed += 1
                            await asyncio.sleep(8.0 + 7.0 * _random.random())
                        except Exception as exc:
                            log.warning("Warmup follow %s: %s", plan["username"], exc)
                    log.info("Warmup %s day %d: followed %d", plan["username"], plan["day_num"], followed)

                async with pool.acquire() as conn4:
                    await conn4.execute(
                        "UPDATE warmup_plans SET last_run=now() WHERE id=$1",
                        plan["id"],
                    )
            except Exception as exc:
                log.error("Warmup plan %s (%s): %s", plan["id"], plan["username"], exc)

    except Exception as exc:
        log.error("Warmup runner: %s", exc)
