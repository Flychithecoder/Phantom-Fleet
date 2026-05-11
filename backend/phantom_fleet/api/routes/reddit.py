"""
Reddit API routes.

Provides:
    GET  /api/reddit/stats                  — fleet-wide Reddit overview
    GET  /api/reddit/accounts               — all Reddit accounts with state
    GET  /api/reddit/accounts/{id}/status   — per-account detail
    POST /api/reddit/accounts/{id}/advance  — manually advance farming stage
    GET  /api/reddit/subreddits             — subreddit library (filterable)
    POST /api/reddit/subreddits/seed        — upsert subreddits into library
    GET  /api/reddit/history/posts          — post history (filterable by account/sub)
    GET  /api/reddit/history/comments       — comment history
    GET  /api/reddit/shadowban-queue        — accounts pending shadowban check
    POST /api/reddit/trigger/karma-farm     — dispatch KarmaFarmingAgent for account(s)
    POST /api/reddit/trigger/post           — dispatch PostSchedulerAgent for account
    POST /api/reddit/trigger/discover       — dispatch SubredditDiscoveryAgent

All mutating trigger endpoints dispatch background tasks via the agent mesh.
They return 202 Accepted immediately.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------

async def _load_reddit_session(pool, account_id: str):
    """
    Load a RedditSession for an account from dedicated credential columns.

    Joins with the phones table to resolve the per-phone SOCKS5 proxy URL.
    Phone-backed accounts route API calls through the phone's residential IP
    (socks5://127.0.0.1:<deterministic_port>) — same IP Reddit sees from the
    native app. Accounts without a phone_id use no proxy (pure API mode).

    Returns (session, row, proxy_url) on success, or raises RuntimeError if
    credentials are missing or the account doesn't exist.
    """
    from ...core.reddit_client import RedditSession
    from ...core.hybrid_runner import PlatformHeaders
    from ...core.apk_client import APKClient

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT a.id, a.username,
                   a.reddit_access_token, a.reddit_refresh_token,
                   a.reddit_token_expires_at,
                   a.reddit_device_id, a.reddit_loid,
                   a.reddit_client_id,
                   a.metadata,
                   p.serial AS phone_serial
            FROM accounts a
            LEFT JOIN phones p ON p.id = a.phone_id
            WHERE a.id = $1 AND a.platform = 'reddit'
        """, account_id)

    if not row:
        raise RuntimeError(f"Reddit account {account_id} not found in DB")

    if not row["reddit_access_token"]:
        raise RuntimeError(
            f"Account {account_id} has no reddit_access_token — "
            "provision it first via POST /api/pipeline/reddit/provision"
        )

    # Resolve proxy URL — phone-backed uses deterministic per-phone port
    phone_serial: Optional[str] = row["phone_serial"]
    proxy_url: Optional[str] = None
    if phone_serial:
        apk       = APKClient(serial=phone_serial)
        proxy_url = apk.socks5_proxy_url

    # Resolve user_agent — prefer phone-extracted, fall back to default
    metadata     = dict(row["metadata"] or {})
    user_agent   = metadata.get("reddit_user_agent", "")
    android_id   = metadata.get("reddit_android_id", row["reddit_device_id"] or "")

    session = RedditSession(
        account_id=account_id,
        access_token=row["reddit_access_token"],
        refresh_token=row["reddit_refresh_token"] or "",
        user_id="",
        username=row["username"],
        client_id=row["reddit_client_id"] or "",
        headers=PlatformHeaders(
            platform="reddit",
            device_id=row["reddit_device_id"] or "",
            user_agent=user_agent,
            android_id=android_id,
            locale="en-US",
            extra={
                "reddit_device_id": row["reddit_device_id"] or "",
                "loid":             row["reddit_loid"] or "",
            },
        ),
    )
    return session, row, proxy_url


async def _refresh_and_persist(
    pool, account_id: str, session, proxy_url: Optional[str] = None
) -> bool:
    """
    Refresh the access token for an account and write the new token to DB.

    Returns True on success, False if the refresh_token is also invalid.
    """
    from ...core.reddit_client import RedditClient

    try:
        async with RedditClient(session, proxy_url=proxy_url or "socks5://127.0.0.1:8089") as client:
            new_token = await client.refresh_access_token()

        from datetime import datetime, timezone
        import time
        expires_ts = datetime.fromtimestamp(time.time() + 3600, tz=timezone.utc)

        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE accounts
                SET reddit_access_token     = $1,
                    reddit_refresh_token    = $2,
                    reddit_token_expires_at = $3
                WHERE id = $4
            """, new_token, session.refresh_token, expires_ts, account_id)

        log.info("Token refreshed and persisted for account %s", account_id)
        return True

    except RuntimeError as exc:
        log.error("Token refresh failed for %s: %s", account_id, exc)
        return False


async def _run_karma_farming_bg(pool, ctx: dict) -> None:
    """Load Reddit session from credential columns and run KarmaFarmingAgent."""
    from ...agents.specialists.reddit_karma_farming_agent import RedditKarmaFarmingAgent
    from ...core.reddit_client import RedditSessionExpired

    account_id = ctx.get("account_id", "")
    try:
        session, _row, proxy_url = await _load_reddit_session(pool, account_id)
        ctx["session"]   = session
        ctx["proxy_url"] = proxy_url
        agent = RedditKarmaFarmingAgent()
        await agent.run(ctx)
    except RedditSessionExpired:
        log.info("Token expired for %s — attempting refresh", account_id)
        try:
            session, _row, proxy_url = await _load_reddit_session(pool, account_id)
            refreshed = await _refresh_and_persist(pool, account_id, session, proxy_url)
            if refreshed:
                session, _row, proxy_url = await _load_reddit_session(pool, account_id)
                ctx["session"]   = session
                ctx["proxy_url"] = proxy_url
                agent = RedditKarmaFarmingAgent()
                await agent.run(ctx)
        except Exception as exc:
            log.error("Reddit karma farming bg (post-refresh) failed for %s: %s",
                      account_id, exc, exc_info=True)
    except Exception as exc:
        log.error("Reddit karma farming bg failed for %s: %s", account_id, exc, exc_info=True)


async def _run_post_scheduler_bg(pool, ctx: dict) -> None:
    """Load Reddit session from credential columns and run PostSchedulerAgent."""
    from ...agents.specialists.reddit_post_scheduler_agent import RedditPostSchedulerAgent
    from ...core.reddit_client import RedditSessionExpired

    account_id = ctx.get("account_id", "")
    try:
        session, _row, proxy_url = await _load_reddit_session(pool, account_id)
        ctx["session"]   = session
        ctx["proxy_url"] = proxy_url
        agent = RedditPostSchedulerAgent()
        await agent.run(ctx)
    except RedditSessionExpired:
        log.info("Token expired for %s — attempting refresh", account_id)
        try:
            session, _row, proxy_url = await _load_reddit_session(pool, account_id)
            refreshed = await _refresh_and_persist(pool, account_id, session, proxy_url)
            if refreshed:
                session, _row, proxy_url = await _load_reddit_session(pool, account_id)
                ctx["session"]   = session
                ctx["proxy_url"] = proxy_url
                agent = RedditPostSchedulerAgent()
                await agent.run(ctx)
        except Exception as exc:
            log.error("Reddit post scheduler bg (post-refresh) failed for %s: %s",
                      account_id, exc, exc_info=True)
    except Exception as exc:
        log.error("Reddit post scheduler bg failed for %s: %s", account_id, exc, exc_info=True)


async def _run_subreddit_discovery_bg(ctx: dict) -> None:
    """Run SubredditDiscoveryAgent (no per-account session required)."""
    from ...agents.specialists.reddit_subreddit_discovery_agent import SubredditDiscoveryAgent

    try:
        agent = SubredditDiscoveryAgent()
        await agent.run(ctx)
    except Exception as exc:
        log.error("Reddit subreddit discovery bg failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AccountRedditState(BaseModel):
    account_id:            str
    username:              str
    platform:              str
    status:                str
    reddit_farming_stage:  int
    reddit_cqs:            int
    reddit_comment_karma:  int
    reddit_link_karma:     int
    reddit_account_age_days: int
    reddit_comment_count:  int
    reddit_unique_subreddits: int
    reddit_posts_today:    int
    reddit_shadowban_status: str
    reddit_shadowban_checked_at: Optional[str]


class SubredditLibraryItem(BaseModel):
    id:             str
    name:           str
    nsfw:           bool
    subscribers:    int
    active_users:   int
    activity_score: float
    competition:    str
    min_karma_req:  int
    allows_text:    bool
    allows_links:   bool
    category:       str
    status:         str
    post_count:     int
    last_post_at:   Optional[str]
    discovered_at:  str


class SubredditSeedItem(BaseModel):
    name:          str
    nsfw:          bool = False
    subscribers:   int = 0
    activity_score: float = 0.0
    competition:   str = "medium"
    min_karma_req: int = 0
    allows_text:   bool = True
    allows_links:  bool = False
    category:      str = "general"


class PostHistoryItem(BaseModel):
    id:            str
    account_id:    str
    subreddit:     str
    title:         Optional[str]
    nsfw:          bool
    category:      str
    status:        str
    score:         int
    comment_count: int
    post_url:      Optional[str]
    created_at:    str


class TriggerRequest(BaseModel):
    account_id:  str
    session_cap_min: int = 15


class PostTriggerRequest(BaseModel):
    account_id:    str
    subreddit_pool: list[dict] = Field(default_factory=list)
    per_day_min:   int = 1
    per_day_max:   int = 3


class DiscoverRequest(BaseModel):
    nsfw_mix:  float = 0.5
    min_subs:  int = 5000
    max_new:   int = 200


class AdvanceStageRequest(BaseModel):
    force: bool = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/stats")
async def reddit_stats(request: Request) -> dict:
    """Fleet-wide Reddit overview: stage distribution, karma totals, shadowban count."""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        # Stage distribution
        stage_rows = await conn.fetch("""
            SELECT reddit_farming_stage AS stage, COUNT(*) AS cnt
            FROM accounts
            WHERE platform = 'reddit' AND status != 'dead'
            GROUP BY reddit_farming_stage
            ORDER BY reddit_farming_stage
        """)

        # Shadowban counts
        shadowban_row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE reddit_shadowban_status = 'shadowbanned') AS shadowbanned,
                COUNT(*) FILTER (WHERE reddit_shadowban_status = 'uncertain')    AS uncertain,
                COUNT(*) FILTER (WHERE reddit_shadowban_status = 'clean')        AS clean
            FROM accounts
            WHERE platform = 'reddit' AND status != 'dead'
        """)

        # Karma totals
        karma_row = await conn.fetchrow("""
            SELECT
                SUM(reddit_comment_karma) AS total_comment_karma,
                SUM(reddit_link_karma)    AS total_link_karma,
                AVG(reddit_cqs)           AS avg_cqs,
                COUNT(*)                  AS total_accounts
            FROM accounts
            WHERE platform = 'reddit' AND status != 'dead'
        """)

        # Posts today across fleet
        posts_today_row = await conn.fetchrow("""
            SELECT SUM(reddit_posts_today) AS posts_today
            FROM accounts
            WHERE platform = 'reddit' AND status = 'active'
        """)

        # Subreddit library size
        library_row = await conn.fetchrow("""
            SELECT COUNT(*) AS count FROM subreddit_library WHERE status = 'active'
        """)

    stage_dist = {str(r["stage"]): r["cnt"] for r in stage_rows}
    sb          = dict(shadowban_row) if shadowban_row else {}
    km          = dict(karma_row)     if karma_row     else {}

    return {
        "stage_distribution": {
            "1_lurk":     stage_dist.get("1", 0),
            "2_comment":  stage_dist.get("2", 0),
            "3_post":     stage_dist.get("3", 0),
            "4_full":     stage_dist.get("4", 0),
        },
        "shadowban": {
            "shadowbanned": sb.get("shadowbanned", 0),
            "uncertain":    sb.get("uncertain", 0),
            "clean":        sb.get("clean", 0),
        },
        "karma": {
            "total_comment_karma": int(km.get("total_comment_karma") or 0),
            "total_link_karma":    int(km.get("total_link_karma") or 0),
            "avg_cqs":             round(float(km.get("avg_cqs") or 0), 1),
            "total_accounts":      int(km.get("total_accounts") or 0),
        },
        "posts_today":      int((posts_today_row or {}).get("posts_today") or 0),
        "library_size":     int((library_row or {}).get("count") or 0),
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }


@router.get("/accounts")
async def list_reddit_accounts(
    request: Request,
    stage:   Optional[int] = None,
    status:  Optional[str] = None,
    limit:   int = 100,
    offset:  int = 0,
) -> dict:
    """List Reddit accounts with current farming state."""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    conditions = ["platform = 'reddit'"]
    params: list = []
    idx = 1

    if stage is not None:
        conditions.append(f"reddit_farming_stage = ${idx}")
        params.append(stage)
        idx += 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                id, username, platform, status,
                reddit_farming_stage, reddit_cqs,
                reddit_comment_karma, reddit_link_karma,
                reddit_account_age_days, reddit_comment_count,
                reddit_unique_subreddits, reddit_posts_today,
                reddit_shadowban_status, reddit_shadowban_checked_at
            FROM accounts
            WHERE {where}
            ORDER BY reddit_farming_stage DESC, reddit_cqs DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, limit, offset)

        total = await conn.fetchval(f"""
            SELECT COUNT(*) FROM accounts WHERE {where}
        """, *params)

    return {
        "accounts": [dict(r) for r in rows],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


@router.get("/accounts/{account_id}/status")
async def account_reddit_status(
    request:    Request,
    account_id: str,
) -> dict:
    """Detailed Reddit state for a single account including recent post/comment history."""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        acct = await conn.fetchrow("""
            SELECT
                id, username, platform, status,
                reddit_farming_stage, reddit_cqs,
                reddit_comment_karma, reddit_link_karma,
                reddit_account_age_days, reddit_comment_count,
                reddit_unique_subreddits, reddit_posts_today,
                reddit_shadowban_status, reddit_shadowban_checked_at,
                reddit_subscribed_subs
            FROM accounts
            WHERE id = $1 AND platform = 'reddit'
        """, account_id)

        if acct is None:
            raise HTTPException(404, "Reddit account not found")

        recent_posts = await conn.fetch("""
            SELECT id, subreddit, title, nsfw, category, status, score, created_at
            FROM reddit_post_history
            WHERE account_id = $1
            ORDER BY created_at DESC
            LIMIT 10
        """, account_id)

        recent_comments = await conn.fetch("""
            SELECT id, subreddit, post_id, status, karma_earned, created_at
            FROM reddit_comment_history
            WHERE account_id = $1
            ORDER BY created_at DESC
            LIMIT 10
        """, account_id)

        shadowban = await conn.fetchrow("""
            SELECT queued_at, quarantine_until, last_check_result, check_count
            FROM reddit_shadowban_queue
            WHERE account_id = $1
        """, account_id)

    return {
        "account":        dict(acct),
        "recent_posts":   [dict(r) for r in recent_posts],
        "recent_comments": [dict(r) for r in recent_comments],
        "shadowban_queue": dict(shadowban) if shadowban else None,
    }


@router.post("/accounts/{account_id}/advance")
async def advance_reddit_stage(
    request:    Request,
    account_id: str,
    body:       AdvanceStageRequest,
) -> dict:
    """
    Manually advance a Reddit account to the next farming stage.
    Requires the graduation criteria to be met unless force=True.
    Force advance is logged for audit.
    """
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        acct = await conn.fetchrow("""
            SELECT reddit_farming_stage, reddit_cqs, reddit_comment_count,
                   reddit_account_age_days
            FROM accounts
            WHERE id = $1 AND platform = 'reddit'
        """, account_id)

        if acct is None:
            raise HTTPException(404, "Reddit account not found")

        stage         = acct["reddit_farming_stage"]
        cqs           = acct["reddit_cqs"]
        comment_count = acct["reddit_comment_count"]
        age_days      = acct["reddit_account_age_days"]

        # Check graduation criteria unless force=True
        if not body.force:
            if stage == 1 and age_days < 7:
                raise HTTPException(400,
                    f"Stage 1→2 requires account_age_days >= 7 (current: {age_days})")
            if stage == 2 and comment_count < 20:
                raise HTTPException(400,
                    f"Stage 2→3 requires lifetime comments >= 20 (current: {comment_count})")
            if stage == 3 and cqs < 500:
                raise HTTPException(400,
                    f"Stage 3→4 requires CQS >= 500 (current: {cqs})")
            if stage >= 4:
                raise HTTPException(400, "Account is already at maximum stage 4")

        new_stage = min(stage + 1, 4)
        await conn.execute("""
            UPDATE accounts
            SET reddit_farming_stage = $1
            WHERE id = $2
        """, new_stage, account_id)

        log.info(
            "Reddit stage advance: account %s %d→%d (force=%s)",
            account_id, stage, new_stage, body.force,
        )

    return {
        "account_id": account_id,
        "old_stage":  stage,
        "new_stage":  new_stage,
        "forced":     body.force,
    }


# ---------------------------------------------------------------------------
# Subreddit library
# ---------------------------------------------------------------------------

@router.get("/subreddits")
async def list_subreddits(
    request:  Request,
    nsfw:     Optional[bool] = None,
    category: Optional[str]  = None,
    status:   str = "active",
    limit:    int = 200,
    offset:   int = 0,
) -> dict:
    """Browse the subreddit library with optional filters."""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    conditions = ["status = $1"]
    params: list = [status]
    idx = 2

    if nsfw is not None:
        conditions.append(f"nsfw = ${idx}")
        params.append(nsfw)
        idx += 1

    if category:
        conditions.append(f"category = ${idx}")
        params.append(category)
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, name, nsfw, subscribers, active_users, activity_score,
                   competition, min_karma_req, allows_text, allows_links,
                   category, status, post_count, last_post_at, discovered_at
            FROM subreddit_library
            WHERE {where}
            ORDER BY activity_score DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, limit, offset)

        total = await conn.fetchval(f"""
            SELECT COUNT(*) FROM subreddit_library WHERE {where}
        """, *params)

    return {
        "subreddits": [dict(r) for r in rows],
        "total":      total,
        "limit":      limit,
        "offset":     offset,
    }


@router.post("/subreddits/seed")
async def seed_subreddits(
    request: Request,
    items:   list[SubredditSeedItem],
) -> dict:
    """Upsert subreddits into the library. Used to add curated targets."""
    if not items:
        raise HTTPException(400, "No items provided")
    if len(items) > 500:
        raise HTTPException(400, "Maximum 500 subreddits per request")

    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    upserted = 0
    async with pool.acquire() as conn:
        for item in items:
            await conn.execute("""
                INSERT INTO subreddit_library
                    (name, nsfw, subscribers, activity_score, competition,
                     min_karma_req, allows_text, allows_links, category)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (name) DO UPDATE SET
                    nsfw           = EXCLUDED.nsfw,
                    subscribers    = EXCLUDED.subscribers,
                    activity_score = EXCLUDED.activity_score,
                    competition    = EXCLUDED.competition,
                    min_karma_req  = EXCLUDED.min_karma_req,
                    allows_text    = EXCLUDED.allows_text,
                    allows_links   = EXCLUDED.allows_links,
                    category       = EXCLUDED.category,
                    updated_at     = now()
            """,
            item.name, item.nsfw, item.subscribers, item.activity_score,
            item.competition, item.min_karma_req, item.allows_text,
            item.allows_links, item.category,
            )
            upserted += 1

    return {"upserted": upserted}


# ---------------------------------------------------------------------------
# Post history
# ---------------------------------------------------------------------------

@router.get("/history/posts")
async def post_history(
    request:    Request,
    account_id: Optional[str] = None,
    subreddit:  Optional[str] = None,
    nsfw:       Optional[bool] = None,
    limit:      int = 100,
    offset:     int = 0,
) -> dict:
    """Query Reddit post history with optional filters."""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    conditions: list[str] = []
    params: list = []
    idx = 1

    if account_id:
        conditions.append(f"account_id = ${idx}")
        params.append(account_id)
        idx += 1
    if subreddit:
        conditions.append(f"subreddit = ${idx}")
        params.append(subreddit)
        idx += 1
    if nsfw is not None:
        conditions.append(f"nsfw = ${idx}")
        params.append(nsfw)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, account_id, subreddit, title, nsfw, category,
                   status, score, comment_count, post_url, created_at
            FROM reddit_post_history
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, limit, offset)

        total = await conn.fetchval(f"""
            SELECT COUNT(*) FROM reddit_post_history {where}
        """, *params)

    return {
        "posts":  [dict(r) for r in rows],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


@router.get("/history/comments")
async def comment_history(
    request:    Request,
    account_id: Optional[str] = None,
    subreddit:  Optional[str] = None,
    limit:      int = 100,
    offset:     int = 0,
) -> dict:
    """Query Reddit comment history."""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    conditions: list[str] = []
    params: list = []
    idx = 1

    if account_id:
        conditions.append(f"account_id = ${idx}")
        params.append(account_id)
        idx += 1
    if subreddit:
        conditions.append(f"subreddit = ${idx}")
        params.append(subreddit)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, account_id, subreddit, post_id,
                   karma_earned, status, created_at
            FROM reddit_comment_history
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, limit, offset)

        total = await conn.fetchval(f"""
            SELECT COUNT(*) FROM reddit_comment_history {where}
        """, *params)

    return {
        "comments": [dict(r) for r in rows],
        "total":    total,
        "limit":    limit,
        "offset":   offset,
    }


# ---------------------------------------------------------------------------
# Shadowban queue
# ---------------------------------------------------------------------------

@router.get("/shadowban-queue")
async def shadowban_queue(request: Request) -> dict:
    """Accounts currently in the shadowban check queue."""
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT q.account_id, a.username,
                   q.queued_at, q.quarantine_until,
                   q.last_check_result, q.check_count
            FROM reddit_shadowban_queue q
            JOIN accounts a ON a.id = q.account_id
            ORDER BY q.queued_at DESC
        """)

    return {"queue": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Token management endpoints
# ---------------------------------------------------------------------------

@router.post("/accounts/login", status_code=202)
async def bulk_login_reddit_accounts(request: Request) -> dict:
    """
    Trigger OAuth login for all provisioned Reddit accounts that have no
    access_token yet (or whose token has expired).

    Reads credentials from accounts.credentials_ref JSONB (username + password
    stored by the provision step) and calls Reddit's password grant to populate
    the reddit_access_token / reddit_refresh_token / reddit_token_expires_at columns.

    Returns 202 immediately. Results are visible via GET /api/reddit/accounts.
    """
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, username, credentials_ref
            FROM accounts
            WHERE platform = 'reddit'
              AND status != 'dead'
              AND (reddit_access_token = '' OR reddit_token_expires_at < now())
            LIMIT 100
        """)

    if not rows:
        return {"queued": False, "message": "No accounts need token refresh"}

    asyncio.create_task(_run_bulk_login_bg(pool, [dict(r) for r in rows]))
    return {
        "queued":  True,
        "count":   len(rows),
        "message": f"Logging in {len(rows)} Reddit account(s) in background",
    }


@router.post("/accounts/{account_id}/refresh-token", status_code=200)
async def refresh_reddit_token(account_id: str, request: Request) -> dict:
    """
    Manually refresh the OAuth token for a single Reddit account.

    Useful when the account's access_token has expired and you want to
    re-activate it immediately without waiting for the background cycle.
    """
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    try:
        session, _row, proxy_url = await _load_reddit_session(pool, account_id)
    except RuntimeError as exc:
        raise HTTPException(404, str(exc))

    if not session.refresh_token:
        raise HTTPException(400, "Account has no refresh_token — re-provision the account")

    refreshed = await _refresh_and_persist(pool, account_id, session, proxy_url)
    if not refreshed:
        raise HTTPException(502, "Token refresh failed — refresh_token may be revoked. Re-provision.")

    return {
        "refreshed":  True,
        "account_id": account_id,
        "username":   session.username,
    }


async def _run_bulk_login_bg(pool, rows: list[dict]) -> None:
    """Background: acquire fresh OAuth tokens for accounts missing them."""
    from ...core.reddit_oauth import (
        password_grant, generate_device_id, generate_loid,
    )
    from datetime import datetime, timezone
    import time

    succeeded = 0
    failed    = 0

    for row in rows:
        account_id = row["id"]
        username   = row["username"]
        creds      = dict(row.get("credentials_ref") or {})
        password   = creds.get("password", "")

        if not password:
            log.warning("Bulk login: no password in credentials_ref for %s — skipping", username)
            failed += 1
            continue

        try:
            tokens    = await password_grant(username=username, password=password)
            device_id = generate_device_id(tokens.user_id or username)
            loid      = generate_loid(tokens.user_id or username)
            expires_ts = datetime.fromtimestamp(tokens.expires_at, tz=timezone.utc)

            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE accounts
                    SET reddit_access_token     = $1,
                        reddit_refresh_token    = $2,
                        reddit_token_expires_at = $3,
                        reddit_device_id        = CASE WHEN reddit_device_id = '' THEN $4 ELSE reddit_device_id END,
                        reddit_loid             = CASE WHEN reddit_loid = '' THEN $5 ELSE reddit_loid END,
                        status = CASE WHEN status = 'warming' THEN 'active' ELSE status END
                    WHERE id = $6
                """, tokens.access_token, tokens.refresh_token, expires_ts,
                    device_id, loid, account_id)

            succeeded += 1
            log.info("Bulk login: token acquired for u/%s", username)

        except Exception as exc:
            failed += 1
            log.error("Bulk login failed for u/%s: %s", username, exc)

    log.info("Bulk Reddit login complete: %d succeeded, %d failed", succeeded, failed)


# ---------------------------------------------------------------------------
# Phone-backed header extraction endpoints
# ---------------------------------------------------------------------------

class ExtractHeadersRequest(BaseModel):
    package_name: str = "com.reddit.frontpage"


@router.post("/accounts/{account_id}/extract-headers", status_code=202)
async def extract_headers_for_account(
    request:    Request,
    account_id: str,
    body:       ExtractHeadersRequest = ExtractHeadersRequest(),
) -> dict:
    """
    Extract real Reddit device headers (device_id + loid) from the phone
    this account is assigned to, then persist them to the DB.

    The account must have a phone_id set (i.e. assigned to a physical phone).
    If the phone is unreachable, falls back to deterministic seeded generation.

    Returns 202 immediately; extraction runs in background.
    """
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT a.id, a.platform, p.serial AS phone_serial
            FROM accounts a
            LEFT JOIN phones p ON p.id = a.phone_id
            WHERE a.id = $1
        """, account_id)

    if row is None:
        raise HTTPException(404, "Account not found")
    if row["platform"] != "reddit":
        raise HTTPException(400, "Account is not a Reddit account")

    phone_serial = row["phone_serial"]

    async def _bg():
        from ...core.reddit_header_extractor import extract_and_store_reddit_headers
        try:
            if phone_serial:
                result = await extract_and_store_reddit_headers(
                    serial=phone_serial,
                    account_id=account_id,
                    pool=pool,
                    package_name=body.package_name,
                )
            else:
                # No phone assigned — fall back to seeded directly
                from ...core.reddit_oauth import generate_device_id, generate_loid
                did  = generate_device_id(account_id)
                loid = generate_loid(account_id)
                async with pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE accounts
                        SET reddit_device_id      = $1,
                            reddit_loid           = $2,
                            reddit_headers_source = 'seeded'
                        WHERE id = $3
                    """, did, loid, account_id)
                result = {"device_id": did, "loid": loid, "source": "seeded"}
            log.info("Header extraction complete for account %s: source=%s", account_id, result.get("source"))
        except Exception as exc:
            log.error("Header extraction failed for account %s: %s", account_id, exc, exc_info=True)

    asyncio.create_task(_bg())

    return {
        "queued":     True,
        "account_id": account_id,
        "phone":      phone_serial or "none — will use seeded generation",
        "package":    body.package_name,
    }


@router.post("/phones/{serial}/extract-headers", status_code=202)
async def extract_headers_for_phone(
    request: Request,
    serial:  str,
    body:    ExtractHeadersRequest = ExtractHeadersRequest(),
) -> dict:
    """
    Extract Reddit device headers for ALL Reddit accounts on a phone.

    The serial is the ADB serial (e.g. "192.168.1.42:5555").
    Internally calls extract_headers_for_phone() which:
      1. Looks up all Reddit accounts with phone_id → this serial
      2. Calls the Companion APK's /reddit/extract-headers for each
      3. Falls back to seeded generation if APK is unreachable
      4. Persists results to accounts table

    Returns 202 immediately; extraction runs in background.
    """
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    # Quick check: does this serial exist?
    async with pool.acquire() as conn:
        phone_row = await conn.fetchrow(
            "SELECT id FROM phones WHERE serial = $1", serial
        )

    if phone_row is None:
        raise HTTPException(404, f"Phone with serial {serial!r} not found")

    async def _bg():
        from ...core.reddit_header_extractor import extract_headers_for_phone as _extract
        try:
            results = await _extract(
                serial=serial,
                pool=pool,
                package_name=body.package_name,
            )
            log.info(
                "Phone %s header extraction: %d accounts processed "
                "(%d phone, %d seeded)",
                serial,
                len(results),
                sum(1 for r in results if r["source"] == "phone"),
                sum(1 for r in results if r["source"] == "seeded"),
            )
        except Exception as exc:
            log.error("Phone header extraction failed for %s: %s", serial, exc, exc_info=True)

    asyncio.create_task(_bg())

    return {
        "queued":  True,
        "serial":  serial,
        "package": body.package_name,
    }


# ---------------------------------------------------------------------------
# Trigger endpoints — dispatch background tasks via agent mesh
# ---------------------------------------------------------------------------

@router.post("/trigger/karma-farm", status_code=202)
async def trigger_karma_farm(
    request: Request,
    body:    TriggerRequest,
) -> dict:
    """
    Dispatch RedditKarmaFarmingAgent for one account.
    Returns 202 immediately; execution is async.
    """
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        acct = await conn.fetchrow("""
            SELECT id, username, reddit_farming_stage, reddit_cqs,
                   reddit_comment_karma, reddit_account_age_days,
                   reddit_comment_count, reddit_unique_subreddits,
                   reddit_subscribed_subs
            FROM accounts
            WHERE id = $1 AND platform = 'reddit'
        """, body.account_id)

    if acct is None:
        raise HTTPException(404, "Reddit account not found")

    asyncio.create_task(_run_karma_farming_bg(pool, {
        "account_id":        body.account_id,
        "stage":             acct["reddit_farming_stage"],
        "account_age_days":  acct["reddit_account_age_days"],
        "karma_score":       acct["reddit_comment_karma"],
        "comment_count":     acct["reddit_comment_count"],
        "unique_subreddits": acct["reddit_unique_subreddits"],
        "subscribed_subs":   list(acct["reddit_subscribed_subs"] or []),
        "session_cap_min":   body.session_cap_min,
    }))

    return {
        "dispatched":  True,
        "account_id":  body.account_id,
        "stage":       acct["reddit_farming_stage"],
    }


@router.post("/trigger/post", status_code=202)
async def trigger_post_scheduler(
    request: Request,
    body:    PostTriggerRequest,
) -> dict:
    """
    Dispatch RedditPostSchedulerAgent for one account.
    Returns 202 immediately; execution is async.
    """
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        acct = await conn.fetchrow("""
            SELECT id, username, reddit_farming_stage, reddit_cqs, reddit_posts_today
            FROM accounts
            WHERE id = $1 AND platform = 'reddit'
        """, body.account_id)

    if acct is None:
        raise HTTPException(404, "Reddit account not found")

    if acct["reddit_farming_stage"] < 4:
        raise HTTPException(400,
            f"Account is stage {acct['reddit_farming_stage']} — post scheduler requires stage 4")

    if acct["reddit_cqs"] < 500:
        raise HTTPException(400,
            f"CQS {acct['reddit_cqs']} < 500 — cannot post yet")

    # If no pool supplied, pull top 10 active subreddits from library
    subreddit_pool = body.subreddit_pool
    if not subreddit_pool and pool is not None:
        async with pool.acquire() as conn:
            lib_rows = await conn.fetch("""
                SELECT name, nsfw, category
                FROM subreddit_library
                WHERE status = 'active' AND allows_text = true
                ORDER BY activity_score DESC
                LIMIT 10
            """)
            subreddit_pool = [dict(r) for r in lib_rows]

    asyncio.create_task(_run_post_scheduler_bg(pool, {
        "account_id":     body.account_id,
        "stage":          acct["reddit_farming_stage"],
        "cqs":            acct["reddit_cqs"],
        "posts_today":    acct["reddit_posts_today"],
        "subreddit_pool": subreddit_pool,
        "per_day_min":    body.per_day_min,
        "per_day_max":    body.per_day_max,
    }))

    return {
        "dispatched":     True,
        "account_id":     body.account_id,
        "pool_size":      len(subreddit_pool),
        "per_day_target": f"{body.per_day_min}-{body.per_day_max}",
    }


@router.post("/trigger/discover", status_code=202)
async def trigger_subreddit_discovery(
    request: Request,
    body:    DiscoverRequest,
) -> dict:
    """
    Dispatch SubredditDiscoveryAgent.
    Returns 202 immediately; execution is async.
    """
    asyncio.create_task(_run_subreddit_discovery_bg({
        "nsfw_mix": body.nsfw_mix,
        "min_subs": body.min_subs,
        "max_new":  body.max_new,
    }))

    return {
        "dispatched": True,
        "nsfw_mix":   body.nsfw_mix,
        "min_subs":   body.min_subs,
        "max_new":    body.max_new,
    }
