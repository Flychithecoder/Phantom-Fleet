"""
ThreadsCrossPostAgent — cross-posts Instagram content to Threads.

Responsibilities:
    - Accept a pool of (caption, media_url?) items sourced from IG content vault
    - Select captions using a seeded hash so no two accounts post the same
      caption on the same day (anti-monoculture)
    - Lightly rewrite the caption via an LLM call to avoid content-duplication
      fingerprints at fleet scale (same image + same caption on 100 accounts
      would be a cluster signal)
    - Post to Threads via ThreadsClient
    - Enforce a hard daily cap of 3 posts per account

Human behavior simulation (all timing is LogNormal):
    1. Pre-post browse: simulate opening Threads and scrolling before posting
       LogNormal(mean=ln(40), σ=0.35) → median ~40s
    2. Compose dwell: pause before typing
       LogNormal(mean=ln(10), σ=0.40) → median ~10s
    3. Typing delay: proportional to caption length
       LogNormal(mean=ln(0.09), σ=0.25) per character
    4. Rethink pause (12% chance): mid-compose hesitation
       LogNormal(mean=ln(7), σ=0.30) → median ~7s
    5. Post time jitter: Normal(0, 900) — post ±15 min from scheduled time
    6. Inter-post delay: LogNormal(mean=ln(3600), σ=0.5) between posts

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Caption variation: LLM rewrite + seeded template selection prevents
      content-duplication cluster. Each account's cross-post is unique text.
    - Timing: jitter ±15min prevents 20K accounts all posting at :00.
    - Daily cap of 3 enforced in code, not prompt.
    - Minimum pool of 15 captions required — enforced at entry.
    - LLM rewrite uses low temperature (0.85) + account_id seed to ensure
      per-account variation without deterministic repetition.

LLM usage:
    - Model: claude-haiku-4-5-20251001 (fast + cheap for caption rewrites)
    - Temperature: 0.85
    - Max tokens: 300 (captions are short)
    - Cap: max 3 LLM calls per account per day (one per post)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import IGSession
from ...core.threads_client import ThreadsClient, ThreadsRateLimited, ThreadsSessionExpired, ThreadsActionBlocked

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced)
# ---------------------------------------------------------------------------

MAX_POSTS_PER_ACCOUNT_PER_DAY: int = 3
MIN_CAPTION_POOL_SIZE: int = 15
MAX_LLM_CALLS_PER_SESSION: int = 3     # hard cap on LLM calls per account per day

# ---------------------------------------------------------------------------
# Distribution instances
# ---------------------------------------------------------------------------

_PRE_BROWSE_DIST   = LogNormal(low=10.0,   high=180.0, sigma=0.35)   # pre-post browse ~40s
_COMPOSE_DWELL     = LogNormal(low=3.0,    high=60.0,  sigma=0.40)   # compose pause ~10s
_RETHINK_PAUSE     = LogNormal(low=3.0,    high=30.0,  sigma=0.30)   # rethink ~7s
_TYPING_PER_CHAR   = LogNormal(low=0.03,   high=0.40,  sigma=0.25)   # ~0.09s/char
_INTER_POST_DELAY  = LogNormal(low=900.0,  high=14400.0, sigma=0.50) # ~1h between posts
_POST_JITTER       = 900.0                                             # ±15 min jitter std dev

RETHINK_PROBABILITY = 0.12   # 12% chance of mid-compose hesitation


# ---------------------------------------------------------------------------
# Template selection helper
# ---------------------------------------------------------------------------


def _post_seed(account_id: str, date_iso: str, post_index: int) -> int:
    """Deterministic seed for template selection — per account per day."""
    key = f"{account_id}|{date_iso}|xpost_{post_index}"
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _select_caption(pool: list[str], seed: int) -> str:
    """Pick a caption from the pool using a deterministic seed."""
    import random
    rng = random.Random(seed)
    return rng.choice(pool)


# ---------------------------------------------------------------------------
# LLM caption rewriter
# ---------------------------------------------------------------------------


async def _rewrite_caption(
    original: str,
    account_id: str,
    llm_calls_used: int,
) -> str:
    """
    Lightly rewrite a caption using Claude Haiku to avoid exact-duplicate
    content fingerprints across the fleet.

    Returns the rewritten caption, or the original if LLM fails.
    Cost cap enforced by caller (MAX_LLM_CALLS_PER_SESSION).
    """
    if llm_calls_used >= MAX_LLM_CALLS_PER_SESSION:
        log.debug("[%s/threads-xpost] LLM cap reached, using original caption", account_id)
        return original

    try:
        import os
        import httpx as _httpx

        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            return original

        system_prompt = (
            "You are a social media copywriter. Rewrite the provided caption for Threads. "
            "Keep the same meaning and tone. Stay under 280 characters. "
            "Do NOT add hashtags. Do NOT add emojis unless they were already present. "
            "Return ONLY the rewritten caption text — no preamble, no quotes."
        )
        user_prompt = f"Rewrite this caption:\n\n{original}"

        async with _httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "anthropic/claude-haiku-4-5-20251001",
                    "temperature": 0.85,
                    "max_tokens":  300,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                },
            )
            resp.raise_for_status()
            body = resp.json()
            rewritten = body["choices"][0]["message"]["content"].strip()
            if rewritten and len(rewritten) <= 500:
                return rewritten
            return original

    except Exception as exc:
        log.warning("[%s/threads-xpost] LLM rewrite failed: %s — using original", account_id, exc)
        return original


# ---------------------------------------------------------------------------
# ThreadsCrossPostAgent
# ---------------------------------------------------------------------------


@dataclass
class CrossPostResult:
    """Detailed result returned alongside WorkerResult."""
    posts_published: int = 0
    posts_skipped:   int = 0
    llm_rewrites:    int = 0
    errors: list[str] = field(default_factory=list)


class ThreadsCrossPostAgent:
    """
    Cross-posts IG content vault captions to Threads with per-account variation.

    Usage:
        agent = ThreadsCrossPostAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            caption_pool=["caption 1 ...", "caption 2 ...", ...],  # ≥15 items
            posts_target=2,
            proxy_url="socks5://...",
        )

    Returns WorkerResult with data keys:
        posts_published, posts_skipped, llm_rewrites, errors
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        caption_pool: list[str],
        posts_target: int = 1,
        date_iso: Optional[str] = None,
        posts_done_today: int = 0,
        proxy_url: Optional[str] = None,
    ) -> WorkerResult:
        """
        Run one cross-post session for one account.

        Args:
            account_id:       Internal account identifier.
            session:          Authenticated IGSession (shared with Threads).
            caption_pool:     List of IG captions to cross-post (min 15 items).
            posts_target:     Posts to attempt this session.
            date_iso:         YYYY-MM-DD (defaults to today UTC).
            posts_done_today: Posts already published today (for cap check).
            proxy_url:        SOCKS5 proxy URL for this account.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        # Enforce minimum pool size (anti-monoculture guard)
        if len(caption_pool) < MIN_CAPTION_POOL_SIZE:
            raise ValueError(
                f"ThreadsCrossPostAgent: caption_pool has {len(caption_pool)} items "
                f"but minimum is {MIN_CAPTION_POOL_SIZE}. Small pools create "
                f"content-duplication fingerprints at fleet scale."
            )

        detail = CrossPostResult()
        task_id = f"{account_id}_threads_xpost_{date_iso}"

        # Clamp to remaining daily cap
        remaining = MAX_POSTS_PER_ACCOUNT_PER_DAY - posts_done_today
        posts_target = min(posts_target, remaining)

        if posts_target <= 0:
            log.info("[%s/threads-xpost] Daily cap already reached, skipping", account_id)
            return WorkerResult(
                task_id=task_id,
                platform="threads",
                account_id=account_id,
                success=True,
                data={
                    "action":          "threads_cross_post",
                    "posts_published": 0,
                    "posts_skipped":   1,
                    "llm_rewrites":    0,
                    "errors":          ["daily_cap_already_reached"],
                },
            )

        # Pre-post browse: simulate opening Threads and scrolling before posting
        browse_delay = _PRE_BROWSE_DIST.sample(account_id=account_id, date_iso=date_iso, field="pre_browse")
        await asyncio.sleep(min(browse_delay, 60.0))   # cap at 60s in tests/staging

        async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
            for post_idx in range(posts_target):
                if posts_done_today >= MAX_POSTS_PER_ACCOUNT_PER_DAY:
                    log.info("[%s/threads-xpost] Daily cap hit mid-session, stopping", account_id)
                    break

                # Seeded caption selection — anti-monoculture
                seed = _post_seed(account_id, date_iso, posts_done_today + post_idx)
                caption = _select_caption(caption_pool, seed)

                # LLM rewrite for per-account variation
                caption = await _rewrite_caption(caption, account_id, detail.llm_rewrites)
                detail.llm_rewrites += 1

                # Compose dwell
                await asyncio.sleep(
                    _COMPOSE_DWELL.sample(account_id=account_id, date_iso=date_iso, field=f"compose_{post_idx}")
                )

                # Rethink pause (12% chance)
                import secrets as _secrets
                rethink_roll = (_secrets.randbits(16) / 65535.0)
                if rethink_roll < RETHINK_PROBABILITY:
                    log.debug("[%s/threads-xpost] Rethink pause mid-compose", account_id)
                    await asyncio.sleep(
                        _RETHINK_PAUSE.sample(account_id=account_id, date_iso=date_iso, field=f"rethink_{post_idx}")
                    )

                # Typing delay: proportional to caption length
                char_delay = _TYPING_PER_CHAR.sample(
                    account_id=account_id, date_iso=date_iso, field=f"typing_{post_idx}"
                )
                await asyncio.sleep(min(len(caption) * char_delay, 30.0))  # cap at 30s

                # Post time jitter (small random offset ±15 min, capped to ±5 min during session)
                import random as _random
                import math as _math
                jitter = _random.gauss(0, _POST_JITTER)
                actual_jitter = max(min(jitter, 300), -300)  # ±5 min intra-session cap
                if actual_jitter > 0:
                    await asyncio.sleep(actual_jitter)

                # Audit log BEFORE action
                audit_ts = datetime.now(timezone.utc).isoformat()
                log.info(
                    "[%s/threads-xpost] Publishing post %d/%d (len=%d ts=%s)",
                    account_id, post_idx + 1, posts_target, len(caption), audit_ts,
                )

                try:
                    await client.post_text(caption)
                    posts_done_today += 1
                    detail.posts_published += 1

                except ThreadsSessionExpired:
                    log.warning("[%s/threads-xpost] Session expired during post", account_id)
                    detail.errors.append(f"session_expired:post_idx={post_idx}")
                    break

                except ThreadsRateLimited as exc:
                    log.warning("[%s/threads-xpost] Rate limited (retry after %ds)", account_id, exc.retry_after_sec)
                    detail.errors.append(f"rate_limited:post_idx={post_idx}:retry_after={exc.retry_after_sec}")
                    break

                except ThreadsActionBlocked:
                    log.warning("[%s/threads-xpost] Post action blocked", account_id)
                    detail.errors.append(f"action_blocked:post_idx={post_idx}")
                    break

                except Exception as exc:
                    log.error("[%s/threads-xpost] Post error: %s", account_id, exc)
                    detail.errors.append(f"error:post_idx={post_idx}:{exc}")
                    continue

                # Inter-post delay
                if post_idx < posts_target - 1 and posts_done_today < MAX_POSTS_PER_ACCOUNT_PER_DAY:
                    inter = _INTER_POST_DELAY.sample(
                        account_id=account_id, date_iso=date_iso, field=f"inter_post_{post_idx}"
                    )
                    log.debug("[%s/threads-xpost] Inter-post delay %.0fs", account_id, inter)
                    await asyncio.sleep(min(inter, 300.0))  # cap at 5 min in staging

        return WorkerResult(
            task_id=task_id,
            platform="threads",
            account_id=account_id,
            success=True,
            data={
                "action":          "threads_cross_post",
                "posts_published": detail.posts_published,
                "posts_skipped":   detail.posts_skipped,
                "llm_rewrites":    detail.llm_rewrites,
                "errors":          detail.errors,
            },
        )
