"""
BlueSkyLikeAgent — mass-like with topic-affinity scoring.

Feed sources:
    timeline     (default) — home timeline posts via app.bsky.feed.getTimeline
    search       — search for posts matching topic_affinity keywords
    feed_uri     — a custom feed generator URI (e.g. "what's_hot" AT URI)

Topic affinity scoring:
    A post gets +1 for each affinity keyword found in its text (case-insensitive).
    Only posts scoring above the topic_threshold (default: 0) are liked.
    A zero threshold means all posts from the feed are liked up to the daily cap.
    The threshold lets the agent skip off-topic posts when search is the source.

Fleet-scale hardening (CLAUDE.md 20K-account rule):
    - Feed items fetched from timeline have natural variation per account (each
      account's timeline is unique) so fleet-wide liked-post overlap is low.
    - Inter-like sleep: LogNormal(mean=ln(20), σ=0.4) — log-normal histogram.
    - Scroll simulation: between likes, the agent "reads" 2-5 posts first
      (simulated with a shorter LogNormal sleep) before the like action.
    - Daily cap: 300/day (code-enforced).
    - Already-liked detection: 409 / AlreadyExists response → skip, no error.
    - liked_uris dedup set prevents double-like within one session.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from datetime import date
from typing import Any

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.distributions import LogNormal, seed_for
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# Inter-like sleep: LogNormal median ~20s — more relaxed than X
_INTER_LIKE_DIST = LogNormal(low=5.0, high=90.0, sigma=0.40)

# Pre-like "read" scroll simulation: median ~8s per post read
_READ_DIST = LogNormal(low=2.0, high=40.0, sigma=0.35)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LIKES_PER_DAY    = 300
MIN_READ_POSTS       = 2    # posts "read" before the like action
MAX_READ_POSTS       = 5


# ---------------------------------------------------------------------------
# Topic affinity scorer
# ---------------------------------------------------------------------------


def _topic_score(text: str, topic_affinity: list[str]) -> int:
    """Return count of affinity keywords found in `text` (case-insensitive)."""
    if not topic_affinity:
        return 1   # no filter — every post passes
    lower = text.lower()
    return sum(1 for kw in topic_affinity if kw.lower() in lower)


def _extract_posts_from_feed(feed_resp: dict) -> list[dict]:
    """Normalise a getTimeline / getFeed / searchPosts response to a flat list.

    Each returned dict has at least:
        uri  str  — AT URI of the post
        cid  str  — content ID
        text str  — post text
    """
    posts: list[dict] = []

    # getTimeline / getFeed response shape
    for item in feed_resp.get("feed", []):
        post = item.get("post", item)  # searchPosts wraps differently
        uri  = post.get("uri", "")
        cid  = post.get("cid", "")
        text = (
            post.get("record", {}).get("text", "")
            or post.get("text", "")
        )
        if uri and cid:
            posts.append({"uri": uri, "cid": cid, "text": text})

    # searchPosts response shape
    for item in feed_resp.get("posts", []):
        uri  = item.get("uri", "")
        cid  = item.get("cid", "")
        text = item.get("record", {}).get("text", "") or item.get("text", "")
        if uri and cid:
            posts.append({"uri": uri, "cid": cid, "text": text})

    return posts


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyLikeAgent(Agent):
    """
    Specialist agent: mass-like on BlueSky for one account.

    ctx keys:
        account_id:           str
        session:              BlueSkySession
        target_count:         int           — how many likes to attempt
        feed_source:          str           — "timeline" | "search" | "feed_uri"
        feed_uri:             str           — AT URI (only when feed_source="feed_uri")
        topic_affinity:       list[str]     — keywords to score posts
        topic_threshold:      int           — min score to like (default: 0 = all)
        date_iso:             str
        already_liked_today:  int           — already liked today (cap tracking)
        liked_uris:           set[str]      — session dedup set
        proxy_url:            str

    Outputs (run.outputs):
        result   WorkerResult   — posts_submitted=liked count, errors
    """

    config = AgentConfig(
        name="bluesky_like",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:          str            = ctx["account_id"]
        session:             BlueSkySession = ctx["session"]
        target_count:        int            = int(ctx.get("target_count", 30))
        feed_source:         str            = ctx.get("feed_source", "timeline")
        feed_uri:            str            = ctx.get("feed_uri", "")
        topic_affinity:      list[str]      = ctx.get("topic_affinity") or []
        topic_threshold:     int            = int(ctx.get("topic_threshold", 0))
        date_iso:            str            = ctx.get("date_iso", date.today().isoformat())
        already_liked_today: int            = int(ctx.get("already_liked_today", 0))
        liked_uris:          set[str]       = set(ctx.get("liked_uris") or [])
        proxy_url:           str            = ctx.get("proxy_url", "socks5://127.0.0.1:8089")
        ab_test_id:          str            = ctx.get("ab_test_id", "")
        ab_variant_id:       str            = ctx.get("ab_variant_id", "")

        result = WorkerResult()

        # A/B recording — lazy, only active when test metadata is present
        _ab_mgr = None
        if ab_test_id and ab_variant_id:
            from ...core.bluesky_ab_test import BlueSkyABManager
            _ab_mgr = BlueSkyABManager()

        self._audit({
            "event":               "bluesky_like_session_start",
            "account_id":          account_id,
            "target_count":        target_count,
            "feed_source":         feed_source,
            "topic_affinity":      topic_affinity,
            "already_liked_today": already_liked_today,
        })

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            posts = await self._fetch_posts(
                client, feed_source, feed_uri, topic_affinity, target_count * 3
            )

            # Per-account, per-day shuffle so fleet doesn't like the same
            # posts in the same order
            seed_val = int(hashlib.sha256(
                f"{account_id}|{date_iso}|like_order".encode()
            ).hexdigest()[:8], 16)
            rng = random.Random(seed_val)
            rng.shuffle(posts)

            action_count = 0

            for post in posts:
                # ---- Daily cap ----
                if already_liked_today + action_count >= MAX_LIKES_PER_DAY:
                    log.info(
                        "[bluesky_like/%s] Daily cap %d reached",
                        account_id, MAX_LIKES_PER_DAY,
                    )
                    break

                if action_count >= target_count:
                    break

                uri  = post.get("uri", "")
                cid  = post.get("cid", "")
                text = post.get("text", "")

                if not uri or not cid:
                    continue

                # ---- Topic affinity gate ----
                score = _topic_score(text, topic_affinity)
                if score < topic_threshold:
                    continue

                # ---- Session dedup ----
                if uri in liked_uris:
                    continue

                # ---- Scroll simulation (read 2-5 posts first) ----
                read_count_seed = seed_for(account_id, date_iso, f"read_count_{uri}")
                read_n = MIN_READ_POSTS + (read_count_seed % (MAX_READ_POSTS - MIN_READ_POSTS + 1))
                for _ in range(read_n):
                    read_sleep = _READ_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"read_{uri}",
                    )
                    await asyncio.sleep(read_sleep)

                self._audit({
                    "event":        "bluesky_like_attempt",
                    "account_id":   account_id,
                    "uri":          uri,
                    "topic_score":  score,
                })

                try:
                    await client.like_post(uri=uri, cid=cid)
                    result.posts_submitted += 1  # reuse posts_submitted for likes
                    liked_uris.add(uri)
                    action_count += 1
                    if _ab_mgr:
                        _ab_mgr.record_like(ab_test_id, account_id, ab_variant_id, uri)
                    log.debug("[bluesky_like/%s] Liked %s", account_id, uri)

                except BlueSkySessionExpired:
                    log.warning("[bluesky_like/%s] Session expired — stopping", account_id)
                    result.errors.append("session_expired")
                    break

                except BlueSkyRateLimited as exc:
                    log.warning(
                        "[bluesky_like/%s] Rate limited — backing off %ds",
                        account_id, exc.retry_after_sec,
                    )
                    result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    await asyncio.sleep(min(exc.retry_after_sec, 120))
                    break

                except Exception as exc:
                    err = str(exc).lower()
                    if "alreadyexists" in err or "already" in err or "409" in err:
                        liked_uris.add(uri)  # mark as seen
                        log.debug("[bluesky_like/%s] Already liked %s", account_id, uri)
                    else:
                        result.errors.append(f"like_error:{uri}:{exc}")
                        log.warning("[bluesky_like/%s] Like failed for %s: %s", account_id, uri, exc)

                # ---- Inter-like sleep ----
                sleep_sec = _INTER_LIKE_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"inter_like_{uri}",
                )
                await asyncio.sleep(sleep_sec)

        self._audit({
            "event":      "bluesky_like_session_end",
            "account_id": account_id,
            "liked":      result.posts_submitted,
            "errors":     len(result.errors),
        })

        run.outputs["result"]     = result
        run.outputs["liked_uris"] = liked_uris
        return True

    async def _fetch_posts(
        self,
        client: BlueSkyClient,
        feed_source: str,
        feed_uri: str,
        topic_affinity: list[str],
        limit: int,
    ) -> list[dict]:
        """Fetch candidate posts from the configured source."""
        posts: list[dict] = []
        try:
            if feed_source == "search" and topic_affinity:
                # Combine topic keywords into one search query
                query = " ".join(topic_affinity[:3])
                resp = await client.search_posts(query=query, limit=min(limit, 100))
                posts = _extract_posts_from_feed(resp)

            elif feed_source == "feed_uri" and feed_uri:
                resp = await client.get_feed(feed_uri=feed_uri, limit=min(limit, 100))
                posts = _extract_posts_from_feed(resp)

            else:
                # Default: home timeline
                resp = await client.get_timeline(limit=min(limit, 100))
                posts = _extract_posts_from_feed(resp)

        except (BlueSkySessionExpired, BlueSkyRateLimited):
            raise
        except Exception as exc:
            log.warning("[bluesky_like] Feed fetch failed (%s): %s", feed_source, exc)

        return posts
