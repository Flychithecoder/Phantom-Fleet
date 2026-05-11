"""
Trending discovery routes — multi-source trend collection + Threads post cache.

Sources:
    1. Google Trends RSS (10 geo regions)
    2. Google Trends realtime API
    3. Evergreen hashtags (male-interest targeting pool)

Endpoints:
    POST   /api/trending/discover             — start full discovery job (async, returns jobId)
    GET    /api/trending/discover/{job_id}    — poll job status + partial results
    GET    /api/trending/all                  — mega combined trending list (500+)
    GET    /api/trending/google               — single-geo Google Trends fetch
    GET    /api/trending/evergreen            — evergreen hashtag pool (seeded shuffle)
    GET    /api/trending/posts                — cached trending posts from DB
    DELETE /api/trending/posts                — clear trending posts cache
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.trending")
router = APIRouter()

# ---------------------------------------------------------------------------
# Evergreen hashtags (male-interest targeting)
# ---------------------------------------------------------------------------

EVERGREEN_TAGS = [
    # Lifestyle / general
    "explore","trending","viral","fyp","foryou","lifestyle","motivation","mindset","success",
    "dailylife","goodvibes","positivevibes","blessed","mood","vibes","content",
    # Male-interest (target demographic)
    "gym","fitness","workout","bodybuilding","gains","fitfam","gymlife","shredded",
    "cars","supercar","luxury","wealth","hustle","entrepreneur","crypto","investing",
    "gaming","gamer","esports","twitch","streamer",
    "sneakers","streetwear","fashion","mensfashion","drip",
    "sports","nba","nfl","soccer","mma","ufc","boxing",
    # Model/creator content
    "model","beauty","selfie","ootd","photography","photoshoot","gorgeous","stunning",
    "influencer","contentcreator","socialmedia","follow","followme",
    # Entertainment
    "memes","funny","comedy","tiktok","music","hiphop","rap","newmusic",
    "netflix","movies","anime","manga",
]

# In-memory job tracker (jobs expire after 2h)
_discovery_jobs: dict[str, dict] = {}

GEOS = ["US", "GB", "CA", "AU", "IN", "BR", "DE", "FR", "MX", "PH"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DiscoverRequest(BaseModel):
    top_n: int = 8
    posts_per_trend: int = 20


# ---------------------------------------------------------------------------
# Google Trends fetcher
# ---------------------------------------------------------------------------

async def _fetch_google_trends(geo: str = "US", top_n: int = 10) -> list[str]:
    urls = [
        f"https://trends.google.com/trending/rss?geo={geo}",
        f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}",
        f"https://trends.google.com/trends/api/dailytrends?hl=en-US&tz=-300&geo={geo}&ns=15",
    ]
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with httpx.AsyncClient(timeout=12.0) as client:
        for url in urls:
            try:
                resp = await client.get(url, headers=ua)
                data = resp.text

                # RSS format
                if "<item>" in data:
                    results = []
                    for m in re.finditer(r"<item>([\s\S]*?)</item>", data):
                        title_m = re.search(r"<title>(.*?)</title>", m.group(1))
                        if title_m:
                            t = title_m.group(1).strip()
                            if t and t not in results:
                                results.append(t)
                    if results:
                        return results[:top_n]

                # JSON API format
                if "trendingSearchesDays" in data:
                    import json
                    clean = data.replace(")]}'", "").lstrip("\n")
                    parsed = json.loads(clean)
                    results = []
                    for day in (parsed.get("default", {}).get("trendingSearchesDays") or []):
                        for ts in (day.get("trendingSearches") or []):
                            q = ts.get("title", {}).get("query", "")
                            if q:
                                results.append(q)
                    if results:
                        return results[:top_n]
            except Exception as exc:
                log.debug("Trends %s %s: %s", geo, url[-30:], exc)
    return []


async def _fetch_all_trending(top_n: int = 500) -> list[str]:
    all_topics: set[str] = set()

    # Multi-geo Google Trends
    tasks = [_fetch_google_trends(geo, 50) for geo in GEOS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, list):
            all_topics.update(r)

    # Google realtime trends
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            rt_url = "https://trends.google.com/trends/api/realtimetrends?hl=en-US&tz=-300&cat=all&fi=0&fs=0&geo=US&ri=300&rs=20&sort=0"
            resp = await client.get(rt_url, headers={"User-Agent": "Mozilla/5.0"})
            import json
            rt_data = resp.text.replace(")]}'", "").lstrip("\n")
            parsed = json.loads(rt_data)
            for story in (parsed.get("storySummaries", {}).get("trendingStories") or []):
                if story.get("entityNames"):
                    all_topics.update(story["entityNames"])
                if story.get("title"):
                    all_topics.add(story["title"])
    except Exception:
        pass

    # Add camelCase derivatives for hashtag use
    derivatives = set()
    for topic in all_topics:
        camel = re.sub(r"[^a-zA-Z0-9\s]", "", topic).replace(" ", "")
        if len(camel) > 3:
            derivatives.add(camel)
    all_topics.update(derivatives)

    return list(all_topics)[:top_n]


# ---------------------------------------------------------------------------
# Discovery job runner
# ---------------------------------------------------------------------------

async def _run_discovery(job: dict, pool, top_n: int, posts_per_trend: int) -> None:
    import json
    try:
        job["phase"] = "Fetching trending topics..."
        google_trends = await _fetch_google_trends("US", top_n)

        import random
        shuffled_evergreen = EVERGREEN_TAGS.copy()
        random.shuffle(shuffled_evergreen)
        trend_topics = list(dict.fromkeys(google_trends + shuffled_evergreen))[:max(top_n, 100)]

        job["trends"] = trend_topics
        job["total"] = len(trend_topics)
        job["current"] = 0

        job["phase"] = "Connecting to Threads API..."
        async with pool.acquire() as conn:
            scraper_acc = await conn.fetchrow(
                "SELECT * FROM accounts WHERE status='active' ORDER BY RANDOM() LIMIT 1"
            )
        if not scraper_acc:
            raise RuntimeError("No active accounts — run Mass Login first")

        scraper_acc = dict(scraper_acc)
        from ...core.instagram_client import IGSession
        from ...core.threads_client import ThreadsClient
        from ...core.hybrid_runner import PlatformHeaders

        proxy_url: Optional[str] = None
        if scraper_acc.get("proxy_id"):
            async with pool.acquire() as conn:
                proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", scraper_acc["proxy_id"])
                if proxy:
                    proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"

        session = IGSession(
            account_id=scraper_acc.get("id", ""),
            ig_user_id=scraper_acc.get("user_id", ""),
            username=scraper_acc.get("username", ""),
            session_id=scraper_acc.get("sessionid", ""),
            csrftoken=scraper_acc.get("csrftoken", ""),
            mid=scraper_acc.get("mid", ""),
            ds_user_id=scraper_acc.get("user_id", ""),
            headers=PlatformHeaders(),
        )

        job["phase"] = f"Searching Threads for {len(trend_topics)} trending topics..."
        author_map: dict[str, dict] = {}
        all_posts: list[dict] = []
        sem = asyncio.Semaphore(3)

        async def _search_topic(topic: str, idx: int) -> None:
            async with sem:
                job["active_topic"] = topic
                tag = re.sub(r"[^a-zA-Z0-9]", "", topic)
                if not tag:
                    job["current"] = idx + 1
                    return
                try:
                    async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                        posts = await client.search_hashtag(tag, posts_per_trend)
                    for p in posts:
                        p["topic"] = topic
                        all_posts.append(p)
                        uname = p.get("username", "")
                        if not uname:
                            continue
                        if uname not in author_map:
                            author_map[uname] = {
                                "username": uname,
                                "total_likes": p.get("likes", 0),
                                "total_reposts": p.get("reposts", 0),
                                "top_post": p.get("text", ""),
                                "topic": topic,
                                "post_count": 1,
                            }
                        else:
                            e = author_map[uname]
                            e["total_likes"] += p.get("likes", 0)
                            e["total_reposts"] += p.get("reposts", 0)
                            e["post_count"] += 1
                    job["partial_results"] = sorted(author_map.values(), key=lambda x: -x["total_likes"])
                except Exception as exc:
                    log.debug("Discovery skip '%s': %s", topic, exc)
                job["current"] = idx + 1

        await asyncio.gather(*[_search_topic(t, i) for i, t in enumerate(trend_topics)])

        # Save posts to trending_posts table
        job["phase"] = "Saving posts to cache..."
        async with pool.acquire() as conn:
            async with conn.transaction():
                for p in all_posts:
                    try:
                        await conn.execute(
                            """
                            INSERT INTO trending_posts
                                (media_id, username, user_id, text, topic, likes, reposts, replies)
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                            ON CONFLICT (media_id) DO NOTHING
                            """,
                            str(p.get("pk") or p.get("id") or p.get("media_id") or ""),
                            p.get("username", ""),
                            str(p.get("user_id", "") or ""),
                            (p.get("text") or "")[:500],
                            p.get("topic", ""),
                            int(p.get("likes", 0)),
                            int(p.get("reposts", 0)),
                            int(p.get("replies", 0)),
                        )
                    except Exception:
                        pass

        sorted_authors = sorted(author_map.values(), key=lambda x: -x["total_likes"])
        job["discovered"] = sorted_authors
        job["status"] = "completed"
        job["phase"] = f"Done — {len(all_posts)} posts, {len(sorted_authors)} unique authors found"

        # Auto-expire after 2h
        async def _expire():
            await asyncio.sleep(7200)
            _discovery_jobs.pop(job["id"], None)
        asyncio.create_task(_expire())

    except Exception as exc:
        job["status"] = "failed"
        job["phase"] = f"Error: {exc}"
        log.error("Discovery failed: %s", exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


@router.post("/discover")
async def start_discovery(body: DiscoverRequest, request: Request):
    pool = _pool(request)
    job_id = str(uuid.uuid4())
    job: dict = {
        "id": job_id,
        "status": "running",
        "phase": "Starting...",
        "trends": [],
        "active_topic": "",
        "current": 0,
        "total": body.top_n,
        "discovered": [],
        "partial_results": [],
        "started_at": __import__("datetime").datetime.utcnow().isoformat(),
        "completed_at": None,
    }
    _discovery_jobs[job_id] = job
    asyncio.create_task(_run_discovery(job, pool, body.top_n, body.posts_per_trend))
    return {"job_id": job_id}


@router.get("/discover/{job_id}")
async def get_discovery_job(job_id: str):
    job = _discovery_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found or expired (2h TTL)")
    return job


@router.get("/all")
async def get_all_trending(limit: int = 500):
    trends = await _fetch_all_trending(limit)
    return {
        "trends": [{"title": t, "traffic": "", "news": []} for t in trends],
        "count": len(trends),
        "source": "combined",
    }


@router.get("/google")
async def get_google_trends(geo: str = "US"):
    """Single-geo Google Trends with traffic + news items."""
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    urls = [
        f"https://trends.google.com/trending/rss?geo={geo}",
        f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}",
        f"https://trends.google.com/trends/api/dailytrends?hl=en-US&tz=-300&geo={geo}&ns=15",
    ]
    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in urls:
            try:
                resp = await client.get(url, headers=ua)
                data = resp.text

                if "<item>" in data:
                    trends = []
                    for m in re.finditer(r"<item>([\s\S]*?)</item>", data):
                        block = m.group(1)
                        title_m = re.search(r"<title>(.*?)</title>", block)
                        traffic_m = re.search(r"<ht:approx_traffic>(.*?)</ht:approx_traffic>", block)
                        news = re.findall(r"<ht:news_item_title>(.*?)</ht:news_item_title>", block)[:2]
                        if title_m:
                            trends.append({
                                "title": title_m.group(1),
                                "traffic": traffic_m.group(1) if traffic_m else "",
                                "news": news,
                            })
                    if trends:
                        return {"trends": trends, "geo": geo, "count": len(trends), "source": "rss"}

                if "trendingSearchesDays" in data:
                    import json
                    clean = data.replace(")]}'", "").lstrip("\n")
                    parsed = json.loads(clean)
                    trends = []
                    for day in (parsed.get("default", {}).get("trendingSearchesDays") or []):
                        for ts in (day.get("trendingSearches") or []):
                            trends.append({
                                "title": ts.get("title", {}).get("query", ""),
                                "traffic": ts.get("formattedTraffic", ""),
                                "news": [(a.get("title") or "") for a in ts.get("articles", [])[:2]],
                            })
                    if trends:
                        return {"trends": trends[:20], "geo": geo, "count": len(trends), "source": "api"}
            except Exception:
                pass

    raise HTTPException(503, f"Google Trends unavailable for geo={geo}")


@router.get("/evergreen")
async def get_evergreen():
    import random
    shuffled = EVERGREEN_TAGS.copy()
    random.shuffle(shuffled)
    return {"tags": shuffled, "count": len(shuffled)}


@router.get("/posts")
async def get_trending_posts(
    request: Request,
    topic: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    async with _pool(request).acquire() as conn:
        if topic:
            rows = await conn.fetch(
                "SELECT * FROM trending_posts WHERE topic=$1 ORDER BY likes DESC, created_at DESC LIMIT $2 OFFSET $3",
                topic, limit, offset,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM trending_posts ORDER BY likes DESC, created_at DESC LIMIT $1 OFFSET $2",
                limit, offset,
            )
        total = await conn.fetchval("SELECT COUNT(*) FROM trending_posts")
        return {"posts": [dict(r) for r in rows], "total": total}


@router.delete("/posts")
async def clear_trending_posts(request: Request):
    async with _pool(request).acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM trending_posts")
        await conn.execute("DELETE FROM trending_posts")
        return {"deleted": n}
