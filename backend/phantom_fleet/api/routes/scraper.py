"""
Scraper routes — trend scraping → follow-target pool pipeline.

Pipeline:
    1. fetchGoogleTrends (6 regions) + Reddit rising → deduplicated topic list
    2. For each topic: Threads hashtag search → scrape likers + commenters
    3. Quality filter: public, 50–500K followers
    4. Insert into scraped_targets (ON CONFLICT DO NOTHING)

Endpoints:
    POST   /api/scraper/run               — trigger scrape job (background)
    GET    /api/scraper/targets           — list targets by status
    GET    /api/scraper/stats             — status counts
    POST   /api/scraper/follow-from-queue — dispatch follow tasks from pending queue
    POST   /api/scraper/follow-back-check — check which followed accounts followed back
    POST   /api/scraper/auto-unfollow     — unfollow non-converters
    DELETE /api/scraper/targets           — clear targets by status
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.scraper")
router = APIRouter()

REGIONS = ["US", "GB", "CA", "AU", "DE", "FR"]
_GOOGLE_TRENDS_URL = "https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"
_REDDIT_RISING_URL = "https://www.reddit.com/r/all/rising.json?limit=50"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ScrapeRunRequest(BaseModel):
    group_id: Optional[str] = None
    posts_per_trend: int = 3
    max_per_post: int = 150
    concurrency: int = 2

class FollowQueueRequest(BaseModel):
    group_id: Optional[str] = None
    limit: int = 500
    concurrency: int = 10
    max_daily: Optional[int] = None
    delay_min: Optional[int] = None
    delay_max: Optional[int] = None

class FollowBackRequest(BaseModel):
    days_ago: int = 3
    limit: int = 100

class AutoUnfollowRequest(BaseModel):
    group_id: Optional[str] = None
    limit: int = 500

class DeleteTargetsRequest(BaseModel):
    status: str = "pending"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


async def _fetch_google_trends(geo: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                _GOOGLE_TRENDS_URL.format(geo=geo),
                headers={"User-Agent": "Mozilla/5.0"},
            )
            text = resp.text
            # Strip XSSI prefix if present
            if text.startswith(")]}'\n"):
                text = text[5:]
            topics = []
            pattern = re.compile(r"<title><!\[CDATA\[([^\]]+)\]\]><\/title>|<title>([^<]+)<\/title>")
            for m in pattern.finditer(text):
                t = (m.group(1) or m.group(2) or "").strip()
                if t and t != "Daily Search Trends" and t not in topics:
                    topics.append(t)
            return topics[:25]
    except Exception as exc:
        log.warning("Trends %s failed: %s", geo, exc)
        return []


async def _fetch_reddit_trending() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _REDDIT_RISING_URL,
                headers={"User-Agent": "ScalerPro/1.0"},
            )
            data = resp.json()
            return [
                child["data"]["title"]
                for child in (data.get("data", {}).get("children") or [])
                if child.get("data", {}).get("title")
            ][:25]
    except Exception as exc:
        log.warning("Reddit trending failed: %s", exc)
        return []


def _is_quality(user: dict) -> bool:
    if not user.get("username"):
        return False
    if user.get("is_private") or user.get("isPrivate"):
        return False
    fc = user.get("follower_count") or user.get("followers") or 0
    return 50 <= fc <= 500_000


async def _run_scrape_job(pool, group_id: Optional[str], posts_per_trend: int = 3, max_per_post: int = 150) -> dict:
    log.info("Scraper: collecting trends...")

    # Fetch all trend sources concurrently
    tasks = [_fetch_google_trends(geo) for geo in REGIONS]
    tasks.append(_fetch_reddit_trending())
    all_arrays = await asyncio.gather(*tasks, return_exceptions=True)

    seen: set[str] = set()
    topics: list[str] = []
    for arr in all_arrays:
        if isinstance(arr, Exception):
            continue
        for t in arr:
            k = t.lower().strip()
            if k not in seen:
                seen.add(k)
                topics.append(t)

    log.info("Scraper: %d unique trends", len(topics))

    # Get a scraper account
    async with pool.acquire() as conn:
        scraper_acc = await conn.fetchrow(
            "SELECT * FROM accounts WHERE status='active' ORDER BY RANDOM() LIMIT 1"
        )

    if not scraper_acc:
        raise RuntimeError("No active accounts for scraping")

    # Import Threads client
    from ...core.instagram_client import IGSession
    from ...core.threads_client import ThreadsClient
    from ...core.hybrid_runner import PlatformHeaders

    proxy_url = None
    if scraper_acc.get("proxy_id"):
        async with pool.acquire() as conn:
            proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", scraper_acc["proxy_id"])
            if proxy:
                proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"

    session = IGSession(
        account_id=scraper_acc.get("id", ""),
        ig_user_id=scraper_acc.get("user_id", ""),
        username=scraper_acc["username"],
        session_id=scraper_acc.get("sessionid", ""),
        csrftoken=scraper_acc.get("csrftoken", ""),
        mid=scraper_acc.get("mid", ""),
        ds_user_id=scraper_acc.get("user_id", ""),
        headers=PlatformHeaders(),
    )

    total_saved = 0
    semaphore = asyncio.Semaphore(2)

    async def scrape_topic(topic: str) -> int:
        async with semaphore:
            saved = 0
            try:
                tag = re.sub(r"[^a-zA-Z0-9]", "", topic)
                if not tag:
                    return 0
                async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                    posts = await client.search_hashtag(tag, posts_per_trend)
                    for post in posts[:posts_per_trend]:
                        media_id = post.get("pk") or post.get("id") or post.get("mediaId")
                        if not media_id:
                            continue
                        engagers: list[dict] = []
                        try:
                            likers = await client.get_media_likers(str(media_id), 100)
                            engagers.extend(
                                {**u, "source": "liker", "source_post_id": str(media_id), "source_topic": topic}
                                for u in likers if _is_quality(u)
                            )
                        except Exception as e:
                            log.warning("Likers %s: %s", media_id, e)
                        try:
                            commenters = await client.get_media_commenters(str(media_id), 60)
                            engagers.extend(
                                {**u, "source": "commenter", "source_post_id": str(media_id), "source_topic": topic}
                                for u in commenters if _is_quality(u)
                            )
                        except Exception as e:
                            log.warning("Commenters %s: %s", media_id, e)

                        # Save targets
                        async with pool.acquire() as conn:
                            for t in engagers[:max_per_post]:
                                try:
                                    await conn.execute(
                                        """
                                        INSERT INTO scraped_targets
                                            (user_id, username, follower_count, source,
                                             source_post_id, source_topic, group_id)
                                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                                        ON CONFLICT (user_id, group_id) DO NOTHING
                                        """,
                                        str(t.get("userId") or t.get("user_id") or ""),
                                        t.get("username", ""),
                                        int(t.get("follower_count") or t.get("followers") or 0),
                                        t["source"],
                                        t["source_post_id"],
                                        t["source_topic"],
                                        group_id,
                                    )
                                    saved += 1
                                except Exception:
                                    pass

                        await asyncio.sleep(0.8 + 1.5 * __import__("random").random())
            except Exception as exc:
                log.warning("Scrape '%s': %s", topic, exc)
            return saved

    results = await asyncio.gather(*[scrape_topic(t) for t in topics[:100]], return_exceptions=True)
    total_saved = sum(r for r in results if isinstance(r, int))
    log.info("Scraper done: %d targets saved", total_saved)
    return {"topics": len(topics), "targets": total_saved}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/run")
async def run_scrape(body: ScrapeRunRequest, request: Request):
    pool = _pool(request)
    asyncio.create_task(
        _run_scrape_job(pool, body.group_id, body.posts_per_trend, body.max_per_post)
    )
    return {"message": "Scrape job started"}


@router.get("/targets")
async def list_targets(
    request: Request,
    status: str = "pending",
    group_id: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    async with _pool(request).acquire() as conn:
        where = "WHERE status=$1"
        params: list = [status]
        idx = 2
        if group_id:
            where += f" AND group_id=${idx}"
            params.append(group_id)
            idx += 1

        rows = await conn.fetch(
            f"SELECT * FROM scraped_targets {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
            *params, limit, offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM scraped_targets WHERE status=$1", status
        )
        return {"targets": [dict(r) for r in rows], "total": total}


@router.get("/stats")
async def scraper_stats(request: Request):
    async with _pool(request).acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM scraped_targets")
        stats = {"total": total}
        for s in ("pending", "followed", "converted", "unfollowed", "filtered"):
            stats[s] = await conn.fetchval(
                "SELECT COUNT(*) FROM scraped_targets WHERE status=$1", s
            )
        return stats


async def _execute_follows_bg(pool, items: list[dict]) -> None:
    """Background task: execute follow actions for each dispatched item."""
    from ...core.instagram_client import IGSession
    from ...core.threads_client import ThreadsClient
    from ...core.hybrid_runner import PlatformHeaders
    import asyncio as _asyncio

    for item in items:
        try:
            async with pool.acquire() as conn:
                acc = await conn.fetchrow("SELECT * FROM accounts WHERE id=$1", item["account_id"])
            if not acc:
                continue
            acc = dict(acc)
            proxy_url = None
            if acc.get("proxy_id"):
                async with pool.acquire() as conn:
                    proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", acc["proxy_id"])
                    if proxy:
                        proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"
            session = IGSession(
                account_id=acc.get("id", ""),
                ig_user_id=acc.get("user_id", ""),
                username=acc.get("username", ""),
                session_id=acc.get("sessionid", ""),
                csrftoken=acc.get("csrftoken", ""),
                mid=acc.get("mid", ""),
                ds_user_id=acc.get("user_id", ""),
                headers=PlatformHeaders(),
            )
            if not session.session_id:
                continue
            async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                await client.follow(item["target_user_id"])
            await _asyncio.sleep(5.0 + 10.0 * __import__("random").random())
        except Exception as exc:
            log.warning("Follow-bg %s→%s: %s", item["account_id"], item["target_user_id"], exc)


@router.post("/follow-from-queue")
async def follow_from_queue(body: FollowQueueRequest, request: Request):
    """Dispatch warm-and-follow tasks for pending scraped targets."""
    async with _pool(request).acquire() as conn:
        where = "WHERE status='pending'"
        params: list = []
        if body.group_id:
            where += " AND group_id=$1"
            params.append(body.group_id)

        targets = await conn.fetch(
            f"SELECT * FROM scraped_targets {where} ORDER BY source DESC, follower_count DESC LIMIT ${len(params)+1}",
            *params, body.limit,
        )
        if not targets:
            raise HTTPException(400, "No pending targets in queue")

        accs = await conn.fetch("SELECT id FROM accounts WHERE status='active'")
        if not accs:
            raise HTTPException(400, "No active accounts")

    items = []
    for i, t in enumerate(targets):
        items.append({
            "account_id": accs[i % len(accs)]["id"],
            "target_user_id": t["user_id"],
            "scraped_target_id": t["id"],
        })

    # Dispatch warm-and-follow tasks as background asyncio tasks
    dispatched = len(items)
    import asyncio as _asyncio
    _asyncio.create_task(_execute_follows_bg(_pool(request), items))

    # Optimistically mark as 'followed'
    async with _pool(request).acquire() as conn:
        async with conn.transaction():
            for t in targets:
                await conn.execute(
                    "UPDATE scraped_targets SET status='followed', followed_at=now() WHERE id=$1",
                    t["id"],
                )

    return {"dispatched": dispatched, "total": len(items)}


@router.post("/follow-back-check")
async def follow_back_check(body: FollowBackRequest, request: Request):
    """Check which followed accounts followed back."""
    from datetime import timedelta
    cutoff = (__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - timedelta(days=body.days_ago)).isoformat()

    async with _pool(request).acquire() as conn:
        targets = await conn.fetch(
            "SELECT * FROM scraped_targets WHERE status='followed' AND followed_at < $1 LIMIT $2",
            cutoff, body.limit,
        )
        if not targets:
            return {"checked": 0, "converted": 0, "to_unfollow": 0}

        scraper_acc = await conn.fetchrow(
            "SELECT * FROM accounts WHERE status='active' ORDER BY RANDOM() LIMIT 1"
        )
    if not scraper_acc:
        raise HTTPException(400, "No active accounts")

    from ...core.instagram_client import IGSession
    from ...core.threads_client import ThreadsClient
    from ...core.hybrid_runner import PlatformHeaders

    proxy_url = None
    if scraper_acc.get("proxy_id"):
        async with _pool(request).acquire() as conn:
            proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", scraper_acc["proxy_id"])
            if proxy:
                proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"

    session = IGSession(
        account_id=scraper_acc.get("id", ""),
        ig_user_id=scraper_acc.get("user_id", ""),
        username=scraper_acc["username"],
        session_id=scraper_acc.get("sessionid", ""),
        csrftoken=scraper_acc.get("csrftoken", ""),
        mid=scraper_acc.get("mid", ""),
        ds_user_id=scraper_acc.get("user_id", ""),
        headers=PlatformHeaders(),
    )

    converted = 0
    to_unfollow = 0

    async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
        for t in targets:
            try:
                status_resp = await client.get_friendship_status(t["user_id"])
                followed_by = status_resp.get("followed_by", False)
                new_status = "converted" if followed_by else "unfollowed"
                async with _pool(request).acquire() as conn:
                    await conn.execute(
                        "UPDATE scraped_targets SET status=$1, followback=$2, checked_at=now() WHERE id=$3",
                        new_status, followed_by, t["id"],
                    )
                if followed_by:
                    converted += 1
                else:
                    to_unfollow += 1
                await asyncio.sleep(0.6 + 0.9 * __import__("random").random())
            except Exception as exc:
                log.warning("Follow-back check %s: %s", t["username"], exc)

    return {"checked": len(targets), "converted": converted, "to_unfollow": to_unfollow}


async def _execute_unfollows_bg(pool, items: list[dict]) -> None:
    """Background task: execute unfollow actions for each item."""
    from ...core.instagram_client import IGSession
    from ...core.threads_client import ThreadsClient
    from ...core.hybrid_runner import PlatformHeaders
    import asyncio as _asyncio

    for item in items:
        try:
            async with pool.acquire() as conn:
                acc = await conn.fetchrow("SELECT * FROM accounts WHERE id=$1", item["account_id"])
            if not acc:
                continue
            acc = dict(acc)
            proxy_url = None
            if acc.get("proxy_id"):
                async with pool.acquire() as conn:
                    proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", acc["proxy_id"])
                    if proxy:
                        proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"
            session = IGSession(
                account_id=acc.get("id", ""),
                ig_user_id=acc.get("user_id", ""),
                username=acc.get("username", ""),
                session_id=acc.get("sessionid", ""),
                csrftoken=acc.get("csrftoken", ""),
                mid=acc.get("mid", ""),
                ds_user_id=acc.get("user_id", ""),
                headers=PlatformHeaders(),
            )
            if not session.session_id:
                continue
            async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                await client.unfollow(item["target_user_id"])
            await _asyncio.sleep(5.0 + 10.0 * __import__("random").random())
        except Exception as exc:
            log.warning("Unfollow-bg %s→%s: %s", item["account_id"], item["target_user_id"], exc)


@router.post("/auto-unfollow")
async def auto_unfollow(body: AutoUnfollowRequest, request: Request):
    """Dispatch unfollow tasks for non-converters."""
    async with _pool(request).acquire() as conn:
        where = "WHERE status='unfollowed'"
        params: list = []
        if body.group_id:
            where += " AND group_id=$1"
            params.append(body.group_id)

        targets = await conn.fetch(
            f"SELECT * FROM scraped_targets {where} LIMIT ${len(params)+1}",
            *params, body.limit,
        )
        if not targets:
            raise HTTPException(400, "No targets queued for unfollow")

        accs = await conn.fetch("SELECT id FROM accounts WHERE status='active'")
        if not accs:
            raise HTTPException(400, "No active accounts")

    dispatched = len(targets)
    unfollow_items = [
        {"account_id": accs[i % len(accs)]["id"], "target_user_id": t["user_id"], "scraped_target_id": t["id"]}
        for i, t in enumerate(targets)
    ]
    import asyncio as _asyncio
    _asyncio.create_task(_execute_unfollows_bg(_pool(request), unfollow_items))

    return {"dispatched": dispatched, "total": len(targets)}


@router.delete("/targets")
async def delete_targets(body: DeleteTargetsRequest, request: Request):
    async with _pool(request).acquire() as conn:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM scraped_targets WHERE status=$1", body.status
        )
        await conn.execute("DELETE FROM scraped_targets WHERE status=$1", body.status)
        return {"deleted": n}
