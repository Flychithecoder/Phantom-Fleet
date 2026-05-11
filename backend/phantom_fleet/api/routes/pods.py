"""
Engagement pods routes — mutual engagement ring for group accounts.

When any account in a pod posts media, all other pod members like/comment
on that post automatically within a configurable delay window.

Endpoints:
    GET    /api/pods                           — list all pods
    POST   /api/pods                           — create a pod
    PATCH  /api/pods/{id}                      — update pod config
    DELETE /api/pods/{id}                      — delete pod
    GET    /api/pods/{id}/members              — list pod member accounts
    POST   /api/pods/{id}/members              — assign accounts to pod
    GET    /api/pods/queue                     — pending pod actions
    POST   /api/pods/queue                     — manually queue a pod action
    POST   /api/pods/process                   — process pending pod queue (background)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.pods")
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreatePodRequest(BaseModel):
    name: str
    group_id: Optional[str] = None
    enabled: bool = True
    like_enabled: bool = True
    comment_enabled: bool = False
    comment_pool: list[str] = []
    delay_min_sec: int = 30
    delay_max_sec: int = 300

class UpdatePodRequest(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    like_enabled: Optional[bool] = None
    comment_enabled: Optional[bool] = None
    comment_pool: Optional[list[str]] = None
    delay_min_sec: Optional[int] = None
    delay_max_sec: Optional[int] = None

class AssignMembersRequest(BaseModel):
    account_ids: list[str]

class QueueActionRequest(BaseModel):
    pod_id: str
    poster_account_id: str
    media_id: str
    engager_account_id: str
    action: str = "like"                 # like / comment
    comment_text: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


# ---------------------------------------------------------------------------
# Pod CRUD
# ---------------------------------------------------------------------------

@router.get("")
async def list_pods(request: Request, group_id: Optional[str] = None):
    async with _pool(request).acquire() as conn:
        if group_id:
            rows = await conn.fetch(
                "SELECT * FROM pods WHERE group_id=$1 ORDER BY created_at DESC", group_id
            )
        else:
            rows = await conn.fetch("SELECT * FROM pods ORDER BY created_at DESC")
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("comment_pool"), str):
                try:
                    d["comment_pool"] = json.loads(d["comment_pool"])
                except Exception:
                    pass
            result.append(d)
        return {"pods": result}


@router.post("")
async def create_pod(body: CreatePodRequest, request: Request):
    async with _pool(request).acquire() as conn:
        pid = await conn.fetchval(
            """
            INSERT INTO pods
                (group_id, name, enabled, like_enabled, comment_enabled,
                 comment_pool, delay_min_sec, delay_max_sec)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8)
            RETURNING id
            """,
            body.group_id, body.name, body.enabled,
            body.like_enabled, body.comment_enabled,
            json.dumps(body.comment_pool),
            body.delay_min_sec, body.delay_max_sec,
        )
        return {"success": True, "id": pid}


@router.patch("/{pod_id}")
async def update_pod(pod_id: str, body: UpdatePodRequest, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM pods WHERE id=$1", pod_id)
        if not row:
            raise HTTPException(404, "Pod not found")

        sets, vals, idx = [], [], 1
        if body.name is not None:          sets.append(f"name=${idx}");            vals.append(body.name); idx+=1
        if body.enabled is not None:       sets.append(f"enabled=${idx}");         vals.append(body.enabled); idx+=1
        if body.like_enabled is not None:  sets.append(f"like_enabled=${idx}");    vals.append(body.like_enabled); idx+=1
        if body.comment_enabled is not None: sets.append(f"comment_enabled=${idx}"); vals.append(body.comment_enabled); idx+=1
        if body.comment_pool is not None:  sets.append(f"comment_pool=${idx}::jsonb"); vals.append(json.dumps(body.comment_pool)); idx+=1
        if body.delay_min_sec is not None: sets.append(f"delay_min_sec=${idx}");   vals.append(body.delay_min_sec); idx+=1
        if body.delay_max_sec is not None: sets.append(f"delay_max_sec=${idx}");   vals.append(body.delay_max_sec); idx+=1

        if not sets:
            raise HTTPException(400, "Nothing to update")

        vals.append(pod_id)
        await conn.execute(f"UPDATE pods SET {', '.join(sets)} WHERE id=${idx}", *vals)
        return {"success": True}


@router.delete("/{pod_id}")
async def delete_pod(pod_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        await conn.execute("DELETE FROM pods WHERE id=$1", pod_id)
        return {"success": True}


# ---------------------------------------------------------------------------
# Pod queue
# ---------------------------------------------------------------------------

@router.get("/queue")
async def get_pod_queue(request: Request, pod_id: Optional[str] = None, limit: int = 100):
    async with _pool(request).acquire() as conn:
        if pod_id:
            rows = await conn.fetch(
                """
                SELECT pq.*, a.username AS poster_username
                FROM pod_queue pq
                LEFT JOIN accounts a ON a.id = pq.poster_account_id
                WHERE pq.pod_id=$1
                ORDER BY pq.scheduled_at DESC LIMIT $2
                """,
                pod_id, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT pq.*, a.username AS poster_username
                FROM pod_queue pq
                LEFT JOIN accounts a ON a.id = pq.poster_account_id
                ORDER BY pq.scheduled_at DESC LIMIT $1
                """,
                limit,
            )
        return {"queue": [dict(r) for r in rows]}


@router.post("/queue")
async def queue_pod_action(body: QueueActionRequest, request: Request):
    async with _pool(request).acquire() as conn:
        row_id = await conn.fetchval(
            """
            INSERT INTO pod_queue
                (pod_id, poster_account_id, media_id, engager_account_id, action, comment_text)
            VALUES ($1,$2,$3,$4,$5,$6)
            RETURNING id
            """,
            body.pod_id, body.poster_account_id, body.media_id,
            body.engager_account_id, body.action, body.comment_text,
        )
        return {"id": row_id}


@router.post("/process")
async def process_pod_queue(request: Request):
    """Process up to 20 pending pod queue items in background."""
    pool = _pool(request)
    asyncio.create_task(_process_pod_queue_bg(pool))
    return {"ok": True, "message": "Pod queue processing started"}


async def _process_pod_queue_bg(pool) -> dict:
    async with pool.acquire() as conn:
        pending = await conn.fetch(
            "SELECT * FROM pod_queue WHERE status='pending' ORDER BY scheduled_at ASC LIMIT 20"
        )

    processed = 0
    for job in pending:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE pod_queue SET status='processing' WHERE id=$1", job["id"])

        try:
            # Get pod config
            async with pool.acquire() as conn:
                pod = await conn.fetchrow("SELECT * FROM pods WHERE id=$1", job["pod_id"])

            if not pod or not pod["enabled"]:
                async with pool.acquire() as conn:
                    await conn.execute("UPDATE pod_queue SET status='skipped' WHERE id=$1", job["id"])
                continue

            # Get the engager account session
            async with pool.acquire() as conn:
                acc = await conn.fetchrow(
                    "SELECT * FROM accounts WHERE id=$1 AND status='active'",
                    job["engager_account_id"],
                )

            if not acc:
                async with pool.acquire() as conn:
                    await conn.execute("UPDATE pod_queue SET status='failed' WHERE id=$1", job["id"])
                continue

            # Random delay within pod window
            import random
            delay = random.uniform(pod["delay_min_sec"], pod["delay_max_sec"])
            await asyncio.sleep(delay)

            from ...core.instagram_client import IGSession
            from ...core.threads_client import ThreadsClient
            from ...core.hybrid_runner import PlatformHeaders

            proxy_url = None
            if acc.get("proxy_id"):
                async with pool.acquire() as conn:
                    proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", acc["proxy_id"])
                    if proxy:
                        proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"

            session = IGSession(
                account_id=acc.get("id", ""),
                ig_user_id=acc.get("user_id", ""),
                username=acc["username"],
                session_id=acc.get("sessionid", ""),
                csrftoken=acc.get("csrftoken", ""),
                mid=acc.get("mid", ""),
                ds_user_id=acc.get("user_id", ""),
                headers=PlatformHeaders(),
            )

            like_count = 0
            comment_count = 0

            async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                if pod["like_enabled"] and job["action"] in ("like", "both"):
                    try:
                        await client.like(job["media_id"])
                        like_count += 1
                    except Exception as exc:
                        log.warning("Pod like %s: %s", acc["username"], exc)

                comment_pool = pod["comment_pool"]
                if isinstance(comment_pool, str):
                    try:
                        import json
                        comment_pool = json.loads(comment_pool)
                    except Exception:
                        comment_pool = []

                if pod["comment_enabled"] and comment_pool and job["action"] in ("comment", "both"):
                    comment = job.get("comment_text") or random.choice(comment_pool)
                    try:
                        await client.post_text(comment, reply_to_id=job["media_id"])
                        comment_count += 1
                    except Exception as exc:
                        log.warning("Pod comment %s: %s", acc["username"], exc)

            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE pod_queue SET status='done', done_at=now() WHERE id=$1",
                    job["id"],
                )
            processed += 1

        except Exception as exc:
            log.error("Pod job %s: %s", job["id"], exc)
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE pod_queue SET status='failed', error=$1 WHERE id=$2",
                    str(exc), job["id"],
                )

    return {"processed_count": processed}
