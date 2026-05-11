"""
ThreadsPostAgent — posts content on Threads with full human posting simulation.

Threads shares IG session/device headers. Posts are made via the Threads
publish endpoint (same infrastructure as IG, different content endpoint).

Human posting behavior simulation (CRITICAL — all timing is LogNormal):
    1. Pre-post browse: LogNormal(mean=ln(45), σ=0.3) — simulate opening
       the app and scrolling the feed before deciding to post
    2. Compose dwell: LogNormal(mean=ln(12), σ=0.4) — pause before typing
    3. Typing delay: len(text) × LogNormal(mean=ln(0.10), σ=0.25) per char
    4. Rethink pause (15% chance): LogNormal(mean=ln(8), σ=0.3) mid-compose
    5. Post time jitter: Normal(0, 900) seconds added to scheduled time
    6. Inter-post delay: LogNormal(mean=ln(3600), σ=0.5) between posts

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Content variation: template picked by hash(account_id + date_iso + post_index)
      so no two accounts post the same template on the same day (anti-monoculture).
    - Post time jitter: ±15 min typical, ±30 min max. Prevents 20K accounts all
      posting at :00 past the hour → timing cluster fingerprint.
    - Rethink pause at ~15% probability means ~3K/20K accounts pause mid-compose
      on any given post. Natural distribution, not a uniform spike at 0% or 100%.
    - Daily cap of 3 posts per account enforced by code.
    - Content pool minimum of 20 items enforced at entry.

Threads post API:
    POST https://i.instagram.com/api/v1/media/configure_text_post_app_feed/
    This is the Threads-specific text post endpoint on IG infrastructure.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from ...core.hybrid_runner import WorkerResult
from ...core.human_post_behavior import (
    compose_dwell,
    inter_post_delay,
    post_time_jitter_seconds,
    pre_post_browse_delay,
    rethink_pause,
    select_template,
    should_rethink,
    typing_delay,
)
from ...core.instagram_client import IGSession
from ...core.threads_client import (
    ThreadsActionBlocked,
    ThreadsClient,
    ThreadsRateLimited,
    ThreadsSessionExpired,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced)
# ---------------------------------------------------------------------------

MAX_POSTS_PER_ACCOUNT_PER_DAY: int = 3
MIN_CONTENT_POOL_SIZE: int = 20


# ---------------------------------------------------------------------------
# Template seed helper
# ---------------------------------------------------------------------------


def _post_seed(account_id: str, date_iso: str, post_index: int) -> int:
    """Return a deterministic integer seed for content template selection."""
    key = f"{account_id}|{date_iso}|post_{post_index}"
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big")


# ---------------------------------------------------------------------------
# ThreadsPostAgent
# ---------------------------------------------------------------------------


@dataclass
class ThreadsPostResult:
    """Detailed result returned alongside WorkerResult."""
    posts_published: int = 0
    posts_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class ThreadsPostAgent:
    """
    Posts content on Threads with full human behavior simulation.

    Usage:
        agent = ThreadsPostAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            content_pool=["caption 1", "caption 2", ...],  # ≥20 items
            posts_target=2,
            date_iso="2026-04-11",
        )

    Returns a WorkerResult with `data` keys:
        posts_published, posts_skipped, errors
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        content_pool: list[str],
        posts_target: int = 1,
        date_iso: Optional[str] = None,
        posts_done_today: int = 0,
        proxy_url: Optional[str] = None,
    ) -> WorkerResult:
        """
        Run one posting session for one account on Threads.

        Args:
            account_id:       Internal account identifier.
            session:          Authenticated IGSession (shared with Threads).
            content_pool:     List of post text templates (min 20 items).
                              Seeded selection ensures per-account variation.
            posts_target:     Number of posts to attempt this session.
            date_iso:         YYYY-MM-DD (defaults to today UTC).
            posts_done_today: Posts already published today (for cap check).
            proxy_url:        Optional SOCKS5 proxy URL for this account.

        Returns:
            WorkerResult with success=True and detailed data dict.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        # Validate content pool (fleet-scale anti-monoculture guard)
        if len(content_pool) < MIN_CONTENT_POOL_SIZE:
            raise ValueError(
                f"ThreadsPostAgent: content_pool has {len(content_pool)} items "
                f"but minimum is {MIN_CONTENT_POOL_SIZE}. Small pools create "
                f"content-duplication clusters detectable at fleet scale."
            )

        detail = ThreadsPostResult()
        task_id = f"{account_id}_threads_post_{date_iso}"
        posts_target = min(posts_target, MAX_POSTS_PER_ACCOUNT_PER_DAY - posts_done_today)

        if posts_target <= 0:
            log.info("[%s/threads] Daily post cap already reached, skipping", account_id)
            return WorkerResult(
                task_id=task_id,
                platform="threads",
                account_id=account_id,
                success=True,
                data={
                    "action":          "threads_post",
                    "posts_published": 0,
                    "posts_skipped":   1,
                    "errors":          ["daily_cap_already_reached"],
                },
            )

        # Pre-post browse: simulate opening app and scrolling before posting
        await pre_post_browse_delay()

        async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
            for post_idx in range(posts_target):
                # Hard daily cap — code enforced
                if posts_done_today >= MAX_POSTS_PER_ACCOUNT_PER_DAY:
                    log.info(
                        "[%s/threads] Daily post cap reached (%d), stopping",
                        account_id, MAX_POSTS_PER_ACCOUNT_PER_DAY,
                    )
                    break

                # Seeded template selection — anti-monoculture
                seed = _post_seed(account_id, date_iso, posts_done_today + post_idx)
                post_text = select_template(content_pool, seed)

                # Compose dwell: pause before typing
                await compose_dwell()

                # Rethink pause (15% chance): mid-compose hesitation
                if should_rethink():
                    log.debug("[%s/threads] Rethink pause mid-compose", account_id)
                    await rethink_pause()

                # Typing simulation: proportional to post length
                await typing_delay(post_text)

                # Post time jitter: actual send time varies ±15 min from "scheduled"
                jitter = post_time_jitter_seconds()
                if jitter > 0:
                    await asyncio.sleep(min(jitter, 1800))  # cap at 30min wait
                elif jitter < 0:
                    # Negative jitter: post "early" — just proceed immediately
                    pass

                # Audit BEFORE execution (CLAUDE.md)
                audit_ts = datetime.now(timezone.utc).isoformat()
                log.info(
                    "[%s/threads] Publishing post %d/%d (len=%d, ts=%s)",
                    account_id, post_idx + 1, posts_target, len(post_text), audit_ts,
                )

                try:
                    await client.post_text(post_text)
                    posts_done_today += 1
                    detail.posts_published += 1

                except ThreadsSessionExpired:
                    log.warning("[%s/threads] Session expired during post", account_id)
                    detail.errors.append(f"session_expired:post_idx={post_idx}")
                    break

                except ThreadsRateLimited:
                    log.warning("[%s/threads] Rate limited during post", account_id)
                    detail.errors.append(f"rate_limited:post_idx={post_idx}")
                    break

                except ThreadsActionBlocked:
                    log.warning("[%s/threads] Post action blocked", account_id)
                    detail.errors.append(f"action_blocked:post_idx={post_idx}")
                    break

                except Exception as exc:
                    log.error("[%s/threads] Post error: %s", account_id, exc)
                    detail.errors.append(f"error:post_idx={post_idx}:{exc}")
                    continue

                # Inter-post delay before next post (if more to come)
                if post_idx < posts_target - 1 and posts_done_today < MAX_POSTS_PER_ACCOUNT_PER_DAY:
                    await inter_post_delay()

        return WorkerResult(
            task_id=task_id,
            platform="threads",
            account_id=account_id,
            success=True,
            data={
                "action":          "threads_post",
                "posts_published": detail.posts_published,
                "posts_skipped":   detail.posts_skipped,
                "errors":          detail.errors,
            },
        )

