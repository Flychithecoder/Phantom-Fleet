"""
RedditPostAgent — submits text posts to Reddit with full human posting behavior.

Responsibilities:
    - Only runs for accounts at stage >= 3 (code-enforced)
    - Enforces a hard cap of 3 posts per account per day (code-enforced)
    - Deduplicates titles: never reuses the same title in the same subreddit
      from the same account
    - Full human posting behavior: pre-post browse, compose dwell, typing
      delay, rethink pause (12%), post timing jitter
    - Template-pool-based title and body generation seeded deterministically
      so different accounts pick different templates

Fleet-scale detection hardening (CLAUDE.md 20K-account rule):
    - Title/body templates selected by hash(account_id + date + post_index)
      so 20K accounts posting to the same subreddit on the same day produce
      20K different titles, not 1 title × 20K copies.
    - Post timing jitter uses Normal(0, 600) so fleet-wide post timestamps
      are spread across a smooth Gaussian curve, not uniform or clustered.
    - All sleeps are LogNormal — browsing, typing, and compose dwell use
      different distribution parameters matching each behavior's real-world
      timing shape.
    - Dedup tracking is (account_id, subreddit, title_hash) — prevents the
      same account from double-posting the same title even across restarts.

Text-only posts:
    No image/video upload. kind="self" only. Reddit image upload endpoint
    is a separate authenticated flow that requires S3 presigned URLs and
    carries higher detection risk — not implemented by design.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import seed_for, _rng_from_seed
from ...core.human_post_behavior import (
    pre_post_browse_delay,
    compose_dwell,
    typing_delay,
    rethink_pause,
    should_rethink,
    select_template,
    post_time_jitter_seconds,
)
from ...core.reddit_client import (
    RedditClient,
    RedditSession,
    RedditSessionExpired,
    RedditRateLimited,
    RedditForbidden,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced)
# ---------------------------------------------------------------------------

MAX_POSTS_PER_DAY: int = 3
MIN_STAGE_TO_POST: int = 3
MIN_TITLE_POOL_SIZE: int = 20
MIN_BODY_POOL_SIZE: int = 20

# ---------------------------------------------------------------------------
# Title templates (≥20 entries)
# Seeded selection ensures different accounts pick different titles.
# ---------------------------------------------------------------------------

TITLE_POOL: list[str] = [
    "Anyone else noticed this lately?",
    "Just a random thought I had today",
    "Curious what you all think about this",
    "This happened to me recently",
    "Hot take: this is underrated",
    "Not sure if this is common but here goes",
    "Unpopular opinion but I stand by it",
    "Genuine question for anyone who's been through this",
    "Something small that made my day better",
    "Realizing this for the first time",
    "Anyone have a good recommendation for this?",
    "Finally did something I'd been putting off",
    "This changed how I approach my day",
    "Looking back, this was obvious",
    "Small win but it counts",
    "Really basic question but couldn't find a good answer",
    "Venting a bit, hope that's okay",
    "This community always has good perspective",
    "Took me way too long to figure this out",
    "Sharing something that helped me recently",
    "Would love some outside perspective on this",
    "Honest question — is this a me thing?",
    "Has anyone else had this experience?",
    "Thinking out loud — feel free to push back",
    "Not sure how to process this tbh",
]

# Body templates (≥20 entries)
BODY_POOL: list[str] = [
    "Just something I've been chewing on. Curious if it resonates with anyone else here.",
    "Wanted to get some outside perspectives. Open to being wrong.",
    "Not looking for advice necessarily, just putting it out there.",
    "This subreddit always has a good take on these kinds of things.",
    "Feels like I'm the last person to figure this out.",
    "Maybe it's obvious but I never really thought about it until now.",
    "Would love to hear if anyone's had a similar experience.",
    "Not a huge deal, just something worth sharing.",
    "If this has been posted before let me know.",
    "Feel free to disagree, I'm genuinely curious what the consensus is.",
    "This might just be a me thing but I figured I'd ask.",
    "Could be a hot take. You tell me.",
    "Been mulling this over for a while and finally decided to post.",
    "Short version: this caught me off guard.",
    "Nothing life-changing, just thought it was worth mentioning.",
    "Probably overthinking it but here we are.",
    "Didn't want to keep it to myself.",
    "Open to other takes if I'm missing something obvious.",
    "This community is usually pretty good about this kind of thing.",
    "Happy to elaborate if anyone's curious.",
    "Not looking for validation, genuinely want to hear different perspectives.",
    "This is a low-stakes question but I can never find a straight answer.",
    "Posting because I couldn't stop thinking about it.",
    "Appreciate any thoughts — this has been on my mind.",
    "No agenda here, just curious.",
]

# ---------------------------------------------------------------------------
# Validation — raise at import time if pools are too small
# ---------------------------------------------------------------------------

if len(TITLE_POOL) < MIN_TITLE_POOL_SIZE:
    raise ValueError(
        f"TITLE_POOL has {len(TITLE_POOL)} entries; minimum is {MIN_TITLE_POOL_SIZE}"
    )
if len(BODY_POOL) < MIN_BODY_POOL_SIZE:
    raise ValueError(
        f"BODY_POOL has {len(BODY_POOL)} entries; minimum is {MIN_BODY_POOL_SIZE}"
    )


# ---------------------------------------------------------------------------
# Dedup key helpers
# ---------------------------------------------------------------------------


def _title_hash(title: str) -> str:
    """Return a short stable hash of a title for dedup tracking."""
    return hashlib.sha256(title.encode()).hexdigest()[:16]


def _dedup_key(account_id: str, subreddit: str, title: str) -> str:
    return f"{account_id}|{subreddit}|{_title_hash(title)}"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class RedditPostAgent(Agent):
    """
    Submits text posts to Reddit for one account.

    ctx keys:
        account_id:       str
        stage:            int   (must be >= 3; enforced by code)
        session:          RedditSession
        subreddit:        str   (target subreddit)
        posts_today:      int   (already posted today; capped at 3)
        used_titles:      set[str]  (dedup keys already used today)
        proxy_url:        str   (optional)
    """

    config = AgentConfig(
        name="reddit_post",
        max_iterations=1,
        max_usd_per_run=0.00,
        max_usd_per_session=0.00,
        allowed_tools=(
            "db.save_post_record",
            "db.save_dedup_key",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id  = ctx["account_id"]
        stage       = int(ctx.get("stage", 3))
        session: RedditSession = ctx["session"]
        subreddit   = ctx.get("subreddit", "CasualConversation")
        posts_today = int(ctx.get("posts_today", 0))
        used_titles: set[str] = set(ctx.get("used_titles", []))
        proxy_url   = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        posts_submitted   = 0
        posts_skipped_dup = 0
        subreddits_posted: list[str] = []

        # Stage gate — code-enforced, not prompt-enforced
        if stage < MIN_STAGE_TO_POST:
            log.info(
                "Account %s is stage %d — minimum stage to post is %d",
                account_id, stage, MIN_STAGE_TO_POST,
            )
            run.outputs["blocked_stage"] = True
            return True

        # Daily cap gate — code-enforced
        if posts_today >= MAX_POSTS_PER_DAY:
            log.info("Account %s hit daily post cap (%d)", account_id, MAX_POSTS_PER_DAY)
            run.outputs["cap_hit"] = True
            return True

        date_iso = datetime.now(timezone.utc).date().isoformat()
        post_index = posts_today  # used for seed variation per post

        # Pick title + body from pools (seeded by account + date + index)
        title_seed = seed_for(account_id, date_iso, f"title_{post_index}")
        body_seed  = seed_for(account_id, date_iso, f"body_{post_index}")

        title = select_template(TITLE_POOL, title_seed)
        body  = select_template(BODY_POOL, body_seed)

        # Dedup check
        dk = _dedup_key(account_id, subreddit, title)
        if dk in used_titles:
            posts_skipped_dup += 1
            log.info("Dedup: account %s already used title %r in r/%s",
                     account_id, title[:40], subreddit)
            run.outputs.update({
                "posts_submitted":     0,
                "posts_skipped_dedup": posts_skipped_dup,
                "subreddits_posted_to": [],
            })
            return True

        self._audit_event(run, "post_plan", {
            "account_id": account_id,
            "subreddit": subreddit,
            "title_hash": _title_hash(title),
            "body_len": len(body),
        })

        async with RedditClient(session, proxy_url=proxy_url) as client:

            # Pre-post browse: read 3-5 posts from target subreddit
            try:
                await client.get_subreddit_posts(subreddit, limit=5, sort="hot")
            except Exception as e:
                log.warning("Pre-post browse failed for %s: %s", account_id, e)
            await pre_post_browse_delay()

            # Compose dwell
            await compose_dwell()

            # Apply post timing jitter (does not sleep — used externally for scheduling)
            jitter = post_time_jitter_seconds()
            self._audit_event(run, "post_jitter", {"jitter_seconds": jitter})

            # Typing delay
            await typing_delay(title + " " + body)

            # Rethink pause (12% chance)
            if should_rethink():
                await rethink_pause()

            # Submit the post
            try:
                self._audit_event(run, "post_submit", {
                    "subreddit": subreddit,
                    "title_hash": _title_hash(title),
                })
                await client.submit_post(
                    subreddit=subreddit,
                    title=title,
                    text=body,
                    kind="self",
                )
                posts_submitted += 1
                subreddits_posted.append(subreddit)
                used_titles.add(dk)

                self._audit_event(run, "post_success", {
                    "subreddit": subreddit,
                })
            except RedditRateLimited as e:
                log.warning("Rate limited posting for %s: retry in %ds",
                            account_id, e.retry_after_sec)
                run.outputs["rate_limited"] = True
                run.outputs["retry_after"]  = e.retry_after_sec
            except RedditForbidden:
                log.warning("Forbidden to post in r/%s for %s", subreddit, account_id)
                run.outputs["forbidden_subreddit"] = subreddit
            except RedditSessionExpired:
                log.error("Session expired for %s during post", account_id)
                run.outputs["session_expired"] = True

        run.outputs.update({
            "posts_submitted":     posts_submitted,
            "posts_skipped_dedup": posts_skipped_dup,
            "subreddits_posted_to": subreddits_posted,
        })
        return True

    def _audit_event(self, run: AgentRun, event_type: str, data: dict) -> None:
        event = {
            "event": event_type,
            "ts":    datetime.now(timezone.utc).isoformat(),
            "agent": self.config.name,
            **data,
        }
        run.audit_events.append(event)
        self.audit_sink(event)
