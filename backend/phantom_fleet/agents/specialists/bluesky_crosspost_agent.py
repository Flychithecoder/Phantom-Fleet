"""
BlueSkyCrossPostAgent — adapt and publish content from IG / X / Threads to BlueSky.

Why cross-posting matters for BlueSky:
    - BlueSky's AT Protocol has zero re-engineering cost — custom clients are legal.
    - "Twitter refugees" are high-value followers who actively seek creator content.
    - Cross-posting from IG/X/Threads multiplies reach of existing content for free.
    - BlueSky's 300-char limit requires non-trivial adaptation — just truncating
      is detectable (posts ending mid-sentence are unnatural). This agent adapts.

Adaptation pipeline (per post):
    1. Strip hashtags (BlueSky culture: no hashtag spam outside niche communities).
       The post_agent handles hashtag injection on native posts — cross-posts
       get different hashtag treatment (see _should_add_hashtags).
    2. Strip @mentions that won't resolve on BlueSky (IG/X handles ≠ AT Protocol handles).
    3. Truncate to 300 chars at a sentence/word boundary (not mid-word).
    4. Apply post dedup (content hash against posted_hashes — cross-platform).
    5. Simulate human compose behavior (browse timeline → compose dwell → type → post).

Content dedup (cross-platform):
    posted_hashes is keyed by (account_id, text_hash). Since the same content
    could be posted on X AND BlueSky by the same persona, the caller must pass
    the unified dedup set. This prevents duplicate content even across platforms.

Fleet-scale hardening (CLAUDE.md 20K-account rule):
    - Source post list is shuffled per (account_id, date_iso) so different
      accounts post the same content pool in different orders — no synchronized
      fleet-wide posting order.
    - Hashtag injection (15% of cross-posts) seeded per (account_id, post_idx)
      to avoid the all-or-nothing monoculture.
    - Post timing jitter: Normal(0, 600) — fleet post timestamps are smooth
      Gaussian, not synchronized at :00.
    - Daily cap: same as native post cap (8/day) shared with BlueSkyPostAgent.
      The caller tracks already_posted_today across both agents.

Blast-radius caps:
    MAX_POSTS_PER_DAY = 8   (shared with BlueSkyPostAgent, code-enforced)
    MAX_SOURCE_POSTS  = 50  (prevents runaway loop on huge source lists)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
import secrets
from datetime import date
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.distributions import LogNormal, Normal, seed_for
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BlueSky constraints
# ---------------------------------------------------------------------------

BLUESKY_CHAR_LIMIT = 300

# ---------------------------------------------------------------------------
# Timing distributions (reuse bluesky_post_agent parameters)
# ---------------------------------------------------------------------------

_PRE_POST_READ_DIST  = LogNormal(low=6.0,  high=120.0, sigma=0.30)
_COMPOSE_DWELL_DIST  = LogNormal(low=3.0,  high=50.0,  sigma=0.40)
_TYPING_SPEED_DIST   = LogNormal(low=0.03, high=0.50,  sigma=0.20)
_RETHINK_PAUSE_DIST  = LogNormal(low=2.0,  high=35.0,  sigma=0.30)
_JITTER_DIST         = Normal(mean=0.0, std=600.0, low=-1500.0, high=1500.0)

# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------

MAX_POSTS_PER_DAY = 8   # shared with BlueSkyPostAgent
MAX_SOURCE_POSTS  = 50

# Rethink probability: ~14% (36/256)
_RETHINK_PROBABILITY_BYTE = 36

# Hashtag injection on cross-posts: ~15% (38/256)
_CROSSPOST_HASHTAG_PROBABILITY = 0.15

# Generic cross-post hashtag options (minimal, not spammy)
_CROSSPOST_HASHTAGS: list[list[str]] = [
    ["#bluesky"],
    ["#art"],
    ["#creator"],
    ["#content"],
    ["#lifestyle"],
]


# ---------------------------------------------------------------------------
# Text adaptation helpers
# ---------------------------------------------------------------------------


_MENTION_RE = re.compile(r"@\S+")
_HASHTAG_RE = re.compile(r"#\S+")
_URL_RE      = re.compile(r"https?://\S+")


def _strip_mentions(text: str) -> str:
    """Remove @mentions that don't resolve on BlueSky."""
    return _MENTION_RE.sub("", text).strip()


def _strip_hashtags(text: str) -> str:
    """Remove all hashtags (BlueSky culture: hashtags are optional + platform-specific)."""
    return _HASHTAG_RE.sub("", text).strip()


def _strip_platform_urls(text: str) -> str:
    """Remove link.tree / linktree / bio.site links — they're useless on BlueSky."""
    return _URL_RE.sub("", text).strip()


def _truncate_natural(text: str, limit: int = BLUESKY_CHAR_LIMIT) -> str:
    """
    Truncate text to `limit` characters at the nearest sentence or word boundary.

    Prefers truncating at a sentence end (.!?), falls back to the last space,
    then hard-truncates as a last resort. Appends "…" when truncated.
    """
    if len(text) <= limit:
        return text

    budget = limit - 1  # leave room for "…"

    # Try sentence boundary
    for ch in (".", "!", "?"):
        idx = text.rfind(ch, 0, budget)
        if idx > budget // 2:
            return text[: idx + 1] + "…"

    # Fall back to word boundary
    idx = text.rfind(" ", 0, budget)
    if idx > 0:
        return text[:idx] + "…"

    # Hard truncate
    return text[:budget] + "…"


def _adapt_text(text: str) -> str:
    """Full adaptation pipeline for a cross-post source."""
    text = _strip_mentions(text)
    text = _strip_hashtags(text)
    # Normalize excess whitespace introduced by stripping
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = _truncate_natural(text, BLUESKY_CHAR_LIMIT)
    return text


def _content_hash(account_id: str, text: str) -> str:
    return hashlib.sha256(f"{account_id}|{text}".encode("utf-8")).hexdigest()[:16]


def _should_rethink() -> bool:
    return secrets.token_bytes(1)[0] < _RETHINK_PROBABILITY_BYTE


def _should_add_hashtags(account_id: str, post_index: int) -> bool:
    key = f"{account_id}|crosspost_hashtag|{post_index}"
    digest = hashlib.sha256(key.encode()).digest()
    roll = int.from_bytes(digest[:4], "big")
    return roll < int(_CROSSPOST_HASHTAG_PROBABILITY * (2 ** 32))


def _pick_hashtag(account_id: str, post_index: int) -> str:
    key = f"{account_id}|crosspost_hashtag_pick|{post_index}"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(_CROSSPOST_HASHTAGS)
    return " ".join(_CROSSPOST_HASHTAGS[idx])


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyCrossPostAgent(Agent):
    """
    Adapt and publish content from IG / X / Threads to BlueSky.

    ctx keys:
        account_id:           str
        session:              BlueSkySession
        source_posts:         list[dict]    — pre-fetched from other platform DBs
                                              each: {text, source_platform, source_id}
        max_per_day:          int           — target posts this run (≤ 8)
        already_posted_today: int           — posts already made today (cap tracking)
        posted_hashes:        set[str]      — (account_id, content_hash) dedup set
        date_iso:             str
        proxy_url:            str

    Outputs (run.outputs):
        result:    WorkerResult   — posts_submitted, skipped_dedup, errors
    """

    config = AgentConfig(
        name="bluesky_crosspost",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:           str            = ctx["account_id"]
        session:              BlueSkySession = ctx["session"]
        source_posts:         list[dict]     = (ctx.get("source_posts") or [])[:MAX_SOURCE_POSTS]
        max_per_day:          int            = min(int(ctx.get("max_per_day", 3)), MAX_POSTS_PER_DAY)
        already_posted_today: int            = int(ctx.get("already_posted_today", 0))
        posted_hashes:        set[str]       = set(ctx.get("posted_hashes") or [])
        date_iso:             str            = ctx.get("date_iso", date.today().isoformat())
        proxy_url:            str            = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        result = WorkerResult()

        self._audit({
            "event":               "bluesky_crosspost_session_start",
            "account_id":          account_id,
            "source_count":        len(source_posts),
            "max_per_day":         max_per_day,
            "already_posted_today": already_posted_today,
        })

        # ---- Per-account source shuffle (no synchronized fleet order) ----
        seed_val = seed_for(account_id, date_iso, "crosspost_source_shuffle")
        rng = random.Random(seed_val)
        shuffled_sources = list(source_posts)
        rng.shuffle(shuffled_sources)

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            for post_idx, source in enumerate(shuffled_sources):
                # ---- Daily cap ----
                if already_posted_today + result.posts_submitted >= MAX_POSTS_PER_DAY:
                    log.info(
                        "[bluesky_crosspost/%s] Daily cap %d reached",
                        account_id, MAX_POSTS_PER_DAY,
                    )
                    break

                if result.posts_submitted >= max_per_day:
                    break

                raw_text = source.get("text", "").strip()
                if not raw_text:
                    continue

                # ---- Adapt text ----
                adapted = _adapt_text(raw_text)
                if not adapted:
                    continue

                # ---- Optional hashtag injection (~15%, seeded) ----
                if _should_add_hashtags(account_id, post_idx):
                    tag = _pick_hashtag(account_id, post_idx)
                    candidate = f"{adapted} {tag}"
                    adapted = _truncate_natural(candidate, BLUESKY_CHAR_LIMIT)

                # ---- Cross-platform dedup ----
                chash = _content_hash(account_id, adapted)
                if chash in posted_hashes:
                    result.skipped_dedup += 1
                    log.debug("[bluesky_crosspost/%s] Dedup skip (hash %s)", account_id, chash)
                    continue
                posted_hashes.add(chash)

                # ---- Human pre-post behavior ----
                try:
                    timeline = await client.get_timeline(limit=8)
                except Exception:
                    timeline = {}

                posts_in_feed = min(5, max(2, len(timeline.get("feed", []))))
                for _ in range(posts_in_feed):
                    read_sleep = _PRE_POST_READ_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"crosspost_read_{post_idx}",
                    )
                    await asyncio.sleep(read_sleep)

                compose_sleep = _COMPOSE_DWELL_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"crosspost_compose_{post_idx}",
                )
                await asyncio.sleep(compose_sleep)

                per_char = _TYPING_SPEED_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"crosspost_type_{post_idx}",
                )
                await asyncio.sleep(len(adapted) * per_char)

                if _should_rethink():
                    rethink_sleep = _RETHINK_PAUSE_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"crosspost_rethink_{post_idx}",
                    )
                    await asyncio.sleep(rethink_sleep)

                # ---- Audit BEFORE posting ----
                self._audit({
                    "event":           "bluesky_crosspost_attempt",
                    "account_id":      account_id,
                    "source_platform": source.get("source_platform", "unknown"),
                    "source_id":       source.get("source_id", ""),
                    "adapted_len":     len(adapted),
                    "content_hash":    chash,
                })

                # ---- Post ----
                try:
                    await client.create_post(text=adapted)
                    result.posts_submitted += 1
                    log.debug(
                        "[bluesky_crosspost/%s] Posted cross-post %d/%d (len=%d, src=%s)",
                        account_id, post_idx + 1, len(shuffled_sources),
                        len(adapted), source.get("source_platform"),
                    )

                except BlueSkySessionExpired:
                    log.warning("[bluesky_crosspost/%s] Session expired — stopping", account_id)
                    result.errors.append("session_expired")
                    break

                except BlueSkyRateLimited as exc:
                    log.warning(
                        "[bluesky_crosspost/%s] Rate limited — backing off %ds",
                        account_id, exc.retry_after_sec,
                    )
                    result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    await asyncio.sleep(min(exc.retry_after_sec, 120))
                    break

                except Exception as exc:
                    result.errors.append(f"post_error:{exc}")
                    log.error("[bluesky_crosspost/%s] Cross-post failed: %s", account_id, exc)
                    continue

        self._audit({
            "event":           "bluesky_crosspost_session_end",
            "account_id":      account_id,
            "posts_submitted": result.posts_submitted,
            "skipped_dedup":   result.skipped_dedup,
            "errors":          len(result.errors),
        })

        run.outputs["result"] = result
        return True


# Public alias matching the manager dispatch key
BlueSkyCrossPostAgent.__name__ = "BlueSkyCrossPostAgent"
