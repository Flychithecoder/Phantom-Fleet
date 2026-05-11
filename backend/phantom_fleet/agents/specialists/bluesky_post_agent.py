"""
BlueSkyPostAgent — post content on BlueSky with human posting behaviour.

BlueSky-specific notes:
    - 300 character limit (AT Protocol app.bsky.feed.post)
    - Hashtag behaviour: 30% of posts include 1-2 hashtags — NOT every post.
      Monoculture detection: all posts with hashtags is a cluster fingerprint.
      Decision seeded per (account_id, post_index) for per-account variation.
    - Daily cap: 8 posts/day (BlueSky is more lenient; AT Protocol has no
      aggressive rate limiting in 2026)
    - Template pool >= 15 required (code-enforced)

Fleet-scale hardening (CLAUDE.md 20K account rule):
    - All timing distributions are LogNormal — fleet-wide histograms are
      log-normal, not rectangular.
    - Pre-post scroll: LogNormal(mean=ln(25), σ=0.3) per post read
    - Compose dwell: LogNormal(mean=ln(10), σ=0.4)
    - Typing delay: len(text) × LogNormal(mean=ln(0.1), σ=0.2)
    - Rethink pause (14%): LogNormal
    - Post timing jitter: Normal(0, 600) seconds
    - Hashtag decision seeded per (account_id, post_index) — ~30% of posts
      get hashtags, but the distribution varies per account
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from datetime import date

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.distributions import LogNormal, Normal, seed_for
from ...core.human_post_behavior import select_template
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BlueSky character limit
# ---------------------------------------------------------------------------

BLUESKY_CHAR_LIMIT = 300

# ---------------------------------------------------------------------------
# Human posting timing distributions
# ---------------------------------------------------------------------------

# Pre-post timeline scroll: median ~25s per post read
_PRE_POST_READ_DIST = LogNormal(low=6.0, high=120.0, sigma=0.30)

# Compose dwell: median ~10s
_COMPOSE_DWELL_DIST = LogNormal(low=3.0, high=50.0, sigma=0.40)

# Per-character typing speed: median ~0.1s/char
_TYPING_SPEED_DIST = LogNormal(low=0.03, high=0.50, sigma=0.20)

# Rethink pause: median ~8s
_RETHINK_PAUSE_DIST = LogNormal(low=2.0, high=35.0, sigma=0.30)

# Post timing jitter: Normal(0, 600) → ±10 min typical
_JITTER_DIST = Normal(mean=0.0, std=600.0, low=-1500.0, high=1500.0)

# ---------------------------------------------------------------------------
# Daily cap and other constants
# ---------------------------------------------------------------------------

MAX_POSTS_PER_DAY = 8
MIN_TEMPLATE_POOL_SIZE = 15

# Rethink probability: 14% (14/100 → threshold byte = 36, 36/256 ≈ 14%)
_RETHINK_PROBABILITY_BYTE = 36

# Hashtag inclusion: ~30% of posts (77/256 ≈ 30%)
_HASHTAG_PROBABILITY = 0.30

# Curated hashtag pool — used when hashtag inclusion is seeded as True
_HASHTAG_POOL: list[list[str]] = [
    ["#trending"],
    ["#lifestyle"],
    ["#vibes"],
    ["#content"],
    ["#mood"],
    ["#creator"],
    ["#explore"],
    ["#viral"],
    ["#art"],
    ["#photography"],
    ["#music"],
    ["#travel"],
    ["#fitness"],
    ["#fashion"],
    ["#food"],
    ["#beauty"],
    ["#motivation"],
    ["#tech"],
    ["#design"],
    ["#culture"],
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_to_limit(text: str, limit: int = BLUESKY_CHAR_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _content_hash(account_id: str, text: str) -> str:
    payload = f"{account_id}|{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _should_rethink() -> bool:
    """Non-deterministic ~14% rethink trigger."""
    return secrets.token_bytes(1)[0] < _RETHINK_PROBABILITY_BYTE


def _should_include_hashtags(account_id: str, post_index: int) -> bool:
    """
    Seeded decision: ~30% of posts for this account get hashtags.

    Seeded so that whether THIS account's post gets a hashtag is stable
    on retry but varies across accounts and post positions. At fleet scale
    the fraction converges to ~30% without being a flat 30% monoculture.
    """
    key = f"{account_id}|hashtag_decision|{post_index}"
    digest = hashlib.sha256(key.encode()).digest()
    # Use first 4 bytes as a uniform [0, 2^32) random — compare to 30% threshold
    roll = int.from_bytes(digest[:4], "big")
    return roll < int(0.30 * (2**32))


def _select_hashtags(account_id: str, post_index: int) -> list[str]:
    """Select 1-2 hashtags from the pool, seeded per (account_id, post_index)."""
    key = f"{account_id}|hashtag_select|{post_index}"
    digest = hashlib.sha256(key.encode()).digest()
    idx1 = int.from_bytes(digest[:4], "big") % len(_HASHTAG_POOL)
    # 50% chance of a second hashtag (seeded)
    include_second = digest[4] < 128
    if include_second:
        idx2 = int.from_bytes(digest[4:8], "big") % len(_HASHTAG_POOL)
        if idx2 != idx1:
            return _HASHTAG_POOL[idx1] + _HASHTAG_POOL[idx2]
    return _HASHTAG_POOL[idx1]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyPostAgent(Agent):
    """
    Specialist agent: post content on BlueSky for one account.

    ctx keys:
        account_id           (str)             — Phantom Fleet account ID
        session              (BlueSkySession)  — pre-built session
        template_pool        (list[str])       — post templates (>= 15 required)
        posts_to_attempt     (int)             — how many posts to publish
        date_iso             (str)             — YYYY-MM-DD (defaults to today)
        already_posted_today (int)             — posts already made today
        posted_hashes        (set[str])        — (account_id, content_hash) dedup set
        proxy_url            (str)             — SOCKS5 proxy (optional)

    Outputs (run.outputs):
        result   (WorkerResult)   — posts_submitted, skipped_dedup, errors
    """

    config = AgentConfig(
        name="bluesky_post",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:           str              = ctx["account_id"]
        session:              BlueSkySession   = ctx["session"]
        template_pool:        list[str]        = ctx["template_pool"]
        posts_to_attempt:     int              = ctx.get("posts_to_attempt", 1)
        date_iso:             str              = ctx.get("date_iso", date.today().isoformat())
        already_posted_today: int              = ctx.get("already_posted_today", 0)
        posted_hashes:        set[str]         = ctx.get("posted_hashes") or set()
        proxy_url:            str              = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        # ---- Template pool validation ----
        if len(template_pool) < MIN_TEMPLATE_POOL_SIZE:
            raise ValueError(
                f"BlueSkyPostAgent: template_pool must have >= {MIN_TEMPLATE_POOL_SIZE} items, "
                f"got {len(template_pool)}"
            )

        result = WorkerResult()

        self._audit({
            "event": "bluesky_post_session_start",
            "account_id": account_id,
            "posts_to_attempt": posts_to_attempt,
            "already_posted_today": already_posted_today,
        })

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            for post_idx in range(posts_to_attempt):
                # ---- Hard daily cap ----
                if already_posted_today + result.posts_submitted >= MAX_POSTS_PER_DAY:
                    log.info(
                        "[bluesky_post/%s] Daily cap %d reached, stopping",
                        account_id, MAX_POSTS_PER_DAY,
                    )
                    break

                # ---- Template selection (seeded per account+date+index) ----
                seed = seed_for(account_id, date_iso, f"bluesky_post_template_{post_idx}")
                text = select_template(template_pool, seed)

                # ---- 300-char validation + truncation ----
                text = _truncate_to_limit(text, BLUESKY_CHAR_LIMIT)

                # ---- Hashtag injection (~30%, seeded per account+index) ----
                if _should_include_hashtags(account_id, post_idx):
                    hashtags = _select_hashtags(account_id, post_idx)
                    suffix = " " + " ".join(hashtags)
                    # Re-truncate with hashtags included
                    candidate = text + suffix
                    text = _truncate_to_limit(candidate, BLUESKY_CHAR_LIMIT)

                # ---- Dedup check ----
                chash = _content_hash(account_id, text)
                if chash in posted_hashes:
                    log.debug(
                        "[bluesky_post/%s] Dedup skip for hash %s", account_id, chash
                    )
                    result.skipped_dedup += 1
                    continue
                posted_hashes.add(chash)

                # ---- Post timing jitter ----
                jitter = int(_JITTER_DIST.sample())

                # ---- Human pre-post behaviour ----
                # 1. Fetch timeline + simulate reading posts
                try:
                    timeline = await client.get_timeline(limit=10)
                except Exception:
                    timeline = {}

                posts_in_feed = min(5, max(3, len(timeline.get("feed", []))))
                for _ in range(posts_in_feed):
                    read_dur = _PRE_POST_READ_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"pre_read_{post_idx}",
                    )
                    await asyncio.sleep(read_dur)

                # 2. Compose dwell
                compose_dur = _COMPOSE_DWELL_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"compose_dwell_{post_idx}",
                )
                await asyncio.sleep(compose_dur)

                # 3. Typing delay (proportional to text length)
                per_char = _TYPING_SPEED_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"typing_speed_{post_idx}",
                )
                typing_dur = len(text) * per_char
                await asyncio.sleep(typing_dur)

                # 4. Rethink pause (14% chance)
                if _should_rethink():
                    rethink_dur = _RETHINK_PAUSE_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"rethink_{post_idx}",
                    )
                    await asyncio.sleep(rethink_dur)

                # ---- Audit BEFORE posting ----
                self._audit({
                    "event": "bluesky_post_attempt",
                    "account_id": account_id,
                    "text_length": len(text),
                    "content_hash": chash,
                    "jitter_sec": jitter,
                    "post_idx": post_idx,
                })

                # ---- Post ----
                try:
                    await client.create_post(text=text)
                    result.posts_submitted += 1
                    log.debug(
                        "[bluesky_post/%s] Posted %d/%d (len=%d)",
                        account_id, post_idx + 1, posts_to_attempt, len(text),
                    )

                except BlueSkySessionExpired:
                    log.warning("[bluesky_post/%s] Session expired — stopping", account_id)
                    result.errors.append("session_expired")
                    break

                except BlueSkyRateLimited as exc:
                    log.warning(
                        "[bluesky_post/%s] Rate limited — backing off %ds",
                        account_id, exc.retry_after_sec,
                    )
                    result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    await asyncio.sleep(min(exc.retry_after_sec, 120))
                    break

                except Exception as exc:
                    result.errors.append(f"post_error:{exc}")
                    log.error("[bluesky_post/%s] Post failed: %s", account_id, exc)
                    continue

        self._audit({
            "event": "bluesky_post_session_end",
            "account_id": account_id,
            "posts_submitted": result.posts_submitted,
            "skipped_dedup": result.skipped_dedup,
            "errors": len(result.errors),
        })

        run.outputs["result"] = result
        return True
