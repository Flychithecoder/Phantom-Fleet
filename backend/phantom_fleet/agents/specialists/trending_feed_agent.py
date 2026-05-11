"""
TrendingFeedAgent — aggregates trending topics from multiple public sources.

Responsibilities:
    - Poll Reddit /r/all/rising and /r/all/hot for rising topics
    - Poll Google Trends daily trending searches (unofficial JSON endpoint)
    - Produce a unified TrendingFeed that ThreadsEngagementAgent consumes
      to find relevant Threads posts to engage with

Design notes:
    - All HTTP requests are unauthenticated — no credentials needed
    - Results are cached for 30 minutes to avoid hammering public APIs from
      the entire fleet simultaneously (one agent per fleet cycle, not per account)
    - Returns raw topic strings + optional hashtag suggestions derived from titles
    - Fetch errors are non-fatal: agent returns whatever sources succeeded

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - TrendingFeedAgent is a FLEET-LEVEL singleton, not per-account. It runs
      once per cycle (e.g., every 30 min) and its output is consumed by all
      ThreadsEngagementAgent instances. This prevents 20K accounts all hitting
      Google Trends / Reddit simultaneously from the fleet's IPs.
    - The feed is passed DOWN to engagement agents as input, so no per-account
      external requests for trend data.
    - Cache TTL (30 min) enforced by code — old results reused within window.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger("phantom_fleet.trending_feed_agent")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CACHE_TTL_SEC = 1800          # 30 minutes
_FETCH_TIMEOUT = 12.0          # seconds per source
_MAX_TOPICS    = 50            # cap topics returned per feed
_MAX_REDDIT_POSTS = 25         # posts pulled from each Reddit endpoint

_GOOGLE_TRENDS_URL = (
    "https://trends.google.com/trends/api/dailytrends"
    "?hl=en-US&tz=-300&geo=US&ns=15"
)
_REDDIT_RISING_URL = "https://www.reddit.com/r/all/rising.json?limit=25"
_REDDIT_HOT_URL    = "https://www.reddit.com/r/all/hot.json?limit=25"

_REDDIT_HEADERS = {
    "User-Agent": "PhantomFleetTrendBot/1.0 (compatible; research bot)",
    "Accept":     "application/json",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TrendingTopic:
    """A single trending topic/keyword."""
    text:    str
    source:  str          # "google_trends" | "reddit_rising" | "reddit_hot"
    score:   float = 0.0  # relative relevance score (higher = trending harder)
    hashtag: str   = ""   # suggested hashtag derived from text


@dataclass
class TrendingFeed:
    """
    Aggregated trending data for one fetch cycle.

    Consumed by ThreadsEngagementAgent to find relevant Threads content.
    """
    topics:     list[TrendingTopic] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)
    sources_ok: list[str] = field(default_factory=list)
    sources_err: list[str] = field(default_factory=list)

    @property
    def top_hashtags(self) -> list[str]:
        """Return top 10 hashtags sorted by score."""
        seen: set[str] = set()
        result: list[str] = []
        for t in sorted(self.topics, key=lambda x: x.score, reverse=True):
            if t.hashtag and t.hashtag not in seen:
                seen.add(t.hashtag)
                result.append(t.hashtag)
            if len(result) >= 10:
                break
        return result

    @property
    def top_keywords(self) -> list[str]:
        """Return top 20 raw topic strings sorted by score."""
        return [
            t.text
            for t in sorted(self.topics, key=lambda x: x.score, reverse=True)
        ][:20]

    def is_fresh(self, ttl_sec: int = _CACHE_TTL_SEC) -> bool:
        return (time.time() - self.fetched_at) < ttl_sec


# ---------------------------------------------------------------------------
# Hashtag derivation
# ---------------------------------------------------------------------------


def _to_hashtag(text: str) -> str:
    """Convert a trending topic text to a camelCase hashtag."""
    import re
    # Remove non-alphanum, title-case each word, join
    words = re.sub(r"[^a-zA-Z0-9\s]", "", text).split()
    if not words:
        return ""
    camel = words[0].lower() + "".join(w.capitalize() for w in words[1:])
    return f"#{camel}" if camel else ""


# ---------------------------------------------------------------------------
# TrendingFeedAgent
# ---------------------------------------------------------------------------


class TrendingFeedAgent:
    """
    Fleet-level singleton that aggregates trending topics from public APIs.

    Usage:
        agent = TrendingFeedAgent()
        feed = await agent.fetch()
        # Returns TrendingFeed with .top_keywords and .top_hashtags

    Cache: repeated calls within 30 minutes return the cached feed without
    re-hitting external APIs.
    """

    def __init__(self, cache_ttl_sec: int = _CACHE_TTL_SEC):
        self._cache_ttl = cache_ttl_sec
        self._cached: Optional[TrendingFeed] = None
        self._lock = asyncio.Lock()

    async def fetch(self, force: bool = False) -> TrendingFeed:
        """
        Return the trending feed. Uses cached result if still fresh.

        Args:
            force: If True, bypass cache and re-fetch even if still fresh.
        """
        async with self._lock:
            if not force and self._cached is not None and self._cached.is_fresh(self._cache_ttl):
                log.debug("TrendingFeedAgent: returning cached feed (%d topics)", len(self._cached.topics))
                return self._cached

            feed = await self._fetch_all()
            self._cached = feed
            log.info(
                "TrendingFeedAgent: fetched %d topics from [%s]",
                len(feed.topics),
                ", ".join(feed.sources_ok),
            )
            return feed

    async def _fetch_all(self) -> TrendingFeed:
        """Fetch all sources concurrently. Errors per-source are non-fatal."""
        feed = TrendingFeed()

        results = await asyncio.gather(
            self._fetch_google_trends(),
            self._fetch_reddit(_REDDIT_RISING_URL, source="reddit_rising", score_base=1.5),
            self._fetch_reddit(_REDDIT_HOT_URL,    source="reddit_hot",    score_base=1.0),
            return_exceptions=True,
        )

        source_names = ["google_trends", "reddit_rising", "reddit_hot"]
        for name, result in zip(source_names, results):
            if isinstance(result, Exception):
                log.warning("TrendingFeedAgent: %s failed: %s", name, result)
                feed.sources_err.append(name)
            else:
                feed.topics.extend(result)
                feed.sources_ok.append(name)

        # Deduplicate and cap
        seen: set[str] = set()
        deduped: list[TrendingTopic] = []
        for t in sorted(feed.topics, key=lambda x: x.score, reverse=True):
            key = t.text.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(t)
            if len(deduped) >= _MAX_TOPICS:
                break

        feed.topics = deduped
        return feed

    async def _fetch_google_trends(self) -> list[TrendingTopic]:
        """Fetch Google Trends daily trending searches for the US."""
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            resp = await client.get(
                _GOOGLE_TRENDS_URL,
                headers={"Accept-Language": "en-US,en;q=0.9"},
                follow_redirects=True,
            )
            resp.raise_for_status()

        # Google Trends returns ")]}'\n{...json...}" — strip the XSSI prefix
        text = resp.text
        prefix = ")]}'"
        if text.startswith(prefix):
            text = text[len(prefix):]

        import json
        data = json.loads(text)
        topics: list[TrendingTopic] = []

        daily = data.get("default", {}).get("trendingSearchesDays", [])
        for day in daily[:1]:  # only today
            searches = day.get("trendingSearches", [])
            for i, item in enumerate(searches[:20]):
                title = item.get("title", {}).get("query", "").strip()
                if not title:
                    continue
                # Score: rank-based decay; top trend = 2.0, last = ~1.0
                score = 2.0 - (i / max(len(searches), 1))
                topics.append(TrendingTopic(
                    text=title,
                    source="google_trends",
                    score=score,
                    hashtag=_to_hashtag(title),
                ))

        return topics

    async def _fetch_reddit(
        self,
        url: str,
        source: str,
        score_base: float,
    ) -> list[TrendingTopic]:
        """Fetch trending posts from a Reddit JSON endpoint."""
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT,
            headers=_REDDIT_HEADERS,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        data = resp.json()
        posts = data.get("data", {}).get("children", [])[:_MAX_REDDIT_POSTS]
        topics: list[TrendingTopic] = []

        for i, post in enumerate(posts):
            pd = post.get("data", {})
            title = pd.get("title", "").strip()
            if not title or len(title) < 5:
                continue

            # Normalise score: top post = score_base + 1, last ≈ score_base
            ups = pd.get("ups", 0)
            score = score_base + min(ups / 50000.0, 1.0)

            topics.append(TrendingTopic(
                text=title,
                source=source,
                score=score,
                hashtag=_to_hashtag(title),
            ))

        return topics
