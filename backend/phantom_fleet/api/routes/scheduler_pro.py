"""
Scheduler Pro routes — visual calendar-based posting system.

Endpoints:
    GET    /api/scheduler-pro/schedules                       — list all schedules
    POST   /api/scheduler-pro/schedules                       — create schedule
    PATCH  /api/scheduler-pro/schedules/{id}                  — update schedule
    DELETE /api/scheduler-pro/schedules/{id}                  — delete schedule
    POST   /api/scheduler-pro/schedules/{id}/accounts         — assign accounts
    GET    /api/scheduler-pro/schedules/{id}/accounts         — list assigned accounts
    POST   /api/scheduler-pro/schedules/{id}/generate         — generate N-day queue
    GET    /api/scheduler-pro/queue                           — main queue view (filterable)
    GET    /api/scheduler-pro/calendar                        — calendar view grouped by date
    GET    /api/scheduler-pro/timeline/{account_id}          — per-account posting timeline
    GET    /api/scheduler-pro/stats                           — aggregate stats
"""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.scheduler_pro")
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateScheduleRequest(BaseModel):
    name: str
    group_id: Optional[str] = None
    post_type: str = "text"
    posts_per_day: int = 3
    posting_start: str = "09:00"
    posting_end: str = "22:00"
    caption_mode: str = "ai"          # ai / template / manual
    caption_template: Optional[str] = None
    vault_model: Optional[str] = None

class UpdateScheduleRequest(BaseModel):
    name: Optional[str] = None
    post_type: Optional[str] = None
    posts_per_day: Optional[int] = None
    posting_start: Optional[str] = None
    posting_end: Optional[str] = None
    caption_mode: Optional[str] = None
    caption_template: Optional[str] = None
    vault_model: Optional[str] = None
    status: Optional[str] = None

class AssignAccountsRequest(BaseModel):
    account_ids: list[str]

class GenerateQueueRequest(BaseModel):
    days: int = 7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


def _generate_posting_times(count: int, start_time: str, end_time: str, account_id: str, day_str: str) -> list[str]:
    """
    Generate `count` unique posting times within the window.
    Seeded per account+day so the same account posts at consistent-ish times
    but each account has a different schedule (avoids fleet-wide time cluster).
    """
    sh, sm = map(int, start_time.split(":"))
    eh, em = map(int, end_time.split(":"))
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    span = max(end_min - start_min, 1)

    seed = int.from_bytes(
        hashlib.sha256(f"{account_id}|{day_str}|sched_times".encode()).digest()[:8], "big"
    )
    rng = random.Random(seed)

    times: list[str] = []
    for _ in range(count):
        m = start_min + rng.randint(0, span - 1)
        h, mi = divmod(m, 60)
        times.append(f"{h:02d}:{mi:02d}")
    return sorted(times)


# ---------------------------------------------------------------------------
# Schedule CRUD
# ---------------------------------------------------------------------------

@router.get("/schedules")
async def list_schedules(request: Request):
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch("""
            SELECT ps.*,
                   g.name AS group_name,
                   (SELECT COUNT(*) FROM pro_schedule_accounts WHERE schedule_id=ps.id) AS account_count,
                   (SELECT COUNT(*) FROM pro_schedule_queue
                    WHERE schedule_id=ps.id AND status='pending') AS pending_posts,
                   (SELECT COUNT(*) FROM pro_schedule_queue
                    WHERE schedule_id=ps.id AND status='posted') AS posted_count
            FROM pro_schedules ps
            LEFT JOIN groups g ON g.id = ps.group_id
            ORDER BY ps.created_at DESC
        """)
        return {"schedules": [dict(r) for r in rows]}


@router.post("/schedules")
async def create_schedule(body: CreateScheduleRequest, request: Request):
    if not body.name:
        raise HTTPException(400, "name required")
    async with _pool(request).acquire() as conn:
        sid = await conn.fetchval(
            """
            INSERT INTO pro_schedules
                (name, group_id, post_type, posts_per_day, posting_start, posting_end,
                 caption_mode, caption_template, vault_model)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING id
            """,
            body.name, body.group_id, body.post_type, body.posts_per_day,
            body.posting_start, body.posting_end, body.caption_mode,
            body.caption_template, body.vault_model,
        )
        return {"success": True, "id": sid}


@router.patch("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, body: UpdateScheduleRequest, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM pro_schedules WHERE id=$1", schedule_id)
        if not row:
            raise HTTPException(404, "Schedule not found")

        sets, vals, idx = [], [], 1
        fields = {
            "name": body.name, "post_type": body.post_type, "posts_per_day": body.posts_per_day,
            "posting_start": body.posting_start, "posting_end": body.posting_end,
            "caption_mode": body.caption_mode, "caption_template": body.caption_template,
            "vault_model": body.vault_model, "status": body.status,
        }
        for col, val in fields.items():
            if val is not None:
                sets.append(f"{col}=${idx}")
                vals.append(val)
                idx += 1

        if not sets:
            raise HTTPException(400, "Nothing to update")

        vals.append(schedule_id)
        await conn.execute(f"UPDATE pro_schedules SET {', '.join(sets)} WHERE id=${idx}", *vals)
        return {"success": True}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        await conn.execute("DELETE FROM pro_schedules WHERE id=$1", schedule_id)
        return {"success": True}


# ---------------------------------------------------------------------------
# Account assignment
# ---------------------------------------------------------------------------

@router.post("/schedules/{schedule_id}/accounts")
async def assign_accounts(schedule_id: str, body: AssignAccountsRequest, request: Request):
    if not body.account_ids:
        raise HTTPException(400, "account_ids required")
    async with _pool(request).acquire() as conn:
        added = 0
        async with conn.transaction():
            for acc_id in body.account_ids:
                result = await conn.execute(
                    "INSERT INTO pro_schedule_accounts (schedule_id, account_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    schedule_id, acc_id,
                )
                if result != "INSERT 0 0":
                    added += 1
        return {"added": added}


@router.get("/schedules/{schedule_id}/accounts")
async def schedule_accounts(schedule_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.id, a.username, a.status, a.follower_count, psa.status AS schedule_status
            FROM pro_schedule_accounts psa
            JOIN accounts a ON a.id = psa.account_id
            WHERE psa.schedule_id = $1
            ORDER BY a.username
        """, schedule_id)
        return {"accounts": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Queue generation
# ---------------------------------------------------------------------------

@router.post("/schedules/{schedule_id}/generate")
async def generate_queue(schedule_id: str, body: GenerateQueueRequest, request: Request):
    async with _pool(request).acquire() as conn:
        schedule = await conn.fetchrow("SELECT * FROM pro_schedules WHERE id=$1", schedule_id)
        if not schedule:
            raise HTTPException(404, "Schedule not found")

        accounts = await conn.fetch(
            "SELECT account_id FROM pro_schedule_accounts WHERE schedule_id=$1", schedule_id
        )
        if not accounts:
            raise HTTPException(400, "No accounts assigned to this schedule")

        generated = 0
        today = date.today()
        async with conn.transaction():
            for d in range(body.days):
                day_date = today + timedelta(days=d)
                day_str = day_date.isoformat()

                for row in accounts:
                    acc_id = row["account_id"]
                    times = _generate_posting_times(
                        schedule["posts_per_day"],
                        schedule["posting_start"],
                        schedule["posting_end"],
                        acc_id,
                        day_str,
                    )
                    for t in times:
                        scheduled_at = datetime.fromisoformat(f"{day_str}T{t}:00+00:00")
                        # Skip if already queued for this slot
                        exists = await conn.fetchval(
                            """
                            SELECT 1 FROM pro_schedule_queue
                            WHERE schedule_id=$1 AND account_id=$2 AND scheduled_at=$3
                            """,
                            schedule_id, acc_id, scheduled_at,
                        )
                        if exists:
                            continue
                        await conn.execute(
                            """
                            INSERT INTO pro_schedule_queue
                                (schedule_id, account_id, scheduled_at, post_type)
                            VALUES ($1,$2,$3,$4)
                            """,
                            schedule_id, acc_id, scheduled_at, schedule["post_type"],
                        )
                        generated += 1

        return {
            "generated": generated,
            "days": body.days,
            "accounts": len(accounts),
            "posts_per_day": schedule["posts_per_day"],
        }


# ---------------------------------------------------------------------------
# Queue / Calendar views
# ---------------------------------------------------------------------------

@router.get("/queue")
async def get_queue(
    request: Request,
    schedule_id: Optional[str] = None,
    account_id: Optional[str] = None,
    date_filter: Optional[str] = None,
    status: Optional[str] = "pending",
    limit: int = 500,
):
    async with _pool(request).acquire() as conn:
        conditions = ["1=1"]
        params: list = []
        idx = 1

        if schedule_id:
            conditions.append(f"q.schedule_id=${idx}")
            params.append(schedule_id)
            idx += 1
        if account_id:
            conditions.append(f"q.account_id=${idx}")
            params.append(account_id)
            idx += 1
        if date_filter:
            conditions.append(f"q.scheduled_at::date=${idx}")
            params.append(date_filter)
            idx += 1
        if status:
            conditions.append(f"q.status=${idx}")
            params.append(status)
            idx += 1

        where = " AND ".join(conditions)
        rows = await conn.fetch(
            f"""
            SELECT q.*, a.username, a.follower_count, ps.name AS schedule_name
            FROM pro_schedule_queue q
            JOIN accounts a ON a.id = q.account_id
            JOIN pro_schedules ps ON ps.id = q.schedule_id
            WHERE {where}
            ORDER BY q.scheduled_at ASC
            LIMIT ${idx}
            """,
            *params, limit,
        )
        return {"queue": [dict(r) for r in rows], "count": len(rows)}


@router.get("/calendar")
async def get_calendar(
    request: Request,
    schedule_id: Optional[str] = None,
    days: int = 7,
):
    async with _pool(request).acquire() as conn:
        conditions = [
            "q.scheduled_at::date >= CURRENT_DATE",
            f"q.scheduled_at::date <= CURRENT_DATE + INTERVAL '{days} days'",
        ]
        params: list = []
        if schedule_id:
            conditions.append("q.schedule_id=$1")
            params.append(schedule_id)

        where = " AND ".join(conditions)
        rows = await conn.fetch(
            f"""
            SELECT q.scheduled_at::date AS day, q.account_id, a.username,
                   COUNT(*)                                                   AS posts,
                   SUM(CASE WHEN q.status='pending'  THEN 1 ELSE 0 END)      AS pending,
                   SUM(CASE WHEN q.status='posted'   THEN 1 ELSE 0 END)      AS posted,
                   SUM(CASE WHEN q.status='failed'   THEN 1 ELSE 0 END)      AS failed,
                   MIN(q.scheduled_at)                                        AS first_post,
                   MAX(q.scheduled_at)                                        AS last_post
            FROM pro_schedule_queue q
            JOIN accounts a ON a.id = q.account_id
            WHERE {where}
            GROUP BY day, q.account_id, a.username
            ORDER BY day ASC, a.username ASC
            """,
            *params,
        )

        # Group by date
        calendar: dict[str, list] = {}
        for r in rows:
            d = dict(r)
            day_key = str(d["day"])
            if day_key not in calendar:
                calendar[day_key] = []
            calendar[day_key].append(d)

        return {"calendar": calendar, "days": len(calendar)}


@router.get("/timeline/{account_id}")
async def account_timeline(account_id: str, request: Request, days: int = 7):
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT q.*, ps.name AS schedule_name
            FROM pro_schedule_queue q
            JOIN pro_schedules ps ON ps.id = q.schedule_id
            WHERE q.account_id = $1
              AND q.scheduled_at::date >= CURRENT_DATE
              AND q.scheduled_at::date <= CURRENT_DATE + INTERVAL '1 day' * $2
            ORDER BY q.scheduled_at ASC
            """,
            account_id, days,
        )
        return {"posts": [dict(r) for r in rows]}


@router.get("/stats")
async def scheduler_stats(request: Request):
    async with _pool(request).acquire() as conn:
        stats = {
            "schedules":    await conn.fetchval("SELECT COUNT(*) FROM pro_schedules"),
            "total_queued": await conn.fetchval("SELECT COUNT(*) FROM pro_schedule_queue WHERE status='pending'"),
            "today_pending": await conn.fetchval(
                "SELECT COUNT(*) FROM pro_schedule_queue WHERE status='pending' AND scheduled_at::date=CURRENT_DATE"
            ),
            "today_posted": await conn.fetchval(
                "SELECT COUNT(*) FROM pro_schedule_queue WHERE status='posted' AND scheduled_at::date=CURRENT_DATE"
            ),
            "today_failed": await conn.fetchval(
                "SELECT COUNT(*) FROM pro_schedule_queue WHERE status='failed' AND scheduled_at::date=CURRENT_DATE"
            ),
            "total_posted": await conn.fetchval("SELECT COUNT(*) FROM pro_schedule_queue WHERE status='posted'"),
        }
        return stats
