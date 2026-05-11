"""
RedditKarmaFarmingAgent — advances one Reddit account through the 4-stage
lurk→comment→post→full farming pipeline.

Stage definitions:
    Stage 1 — Lurk  (days 0-7):   Subscribe to 3-5 subreddits, upvote 5-15
                                    posts. NO comments, NO posts.
    Stage 2 — Comment (days 7-21): Add 1-3 comments on SAFE subreddits. Still
                                    no posts.
    Stage 3 — Post  (days 21-45):  1 text post to a low-competition subreddit.
                                    Mix of SFW only. No NSFW.
    Stage 4 — Full  (days 45+):    Dispatched by manager's post_scheduler.
                                    This agent does not run in stage 4 mode.

CQS (Community Quality Score):
    karma_score + (account_age_days * 2) + (unique_subreddits_active * 5)
    Minimum 500 before stage 4 posting is unlocked.

Graduation gates (code-enforced):
    Stage 1 → 2: account_age_days >= 7
    Stage 2 → 3: total lifetime comment_count >= 20
    Stage 3 → 4: CQS >= 500

Fleet-scale notes (CLAUDE.md 20K-account rule):
    - Upvote count is sampled from LogNormal, not uniform, so fleet histogram
      is log-normal.
    - Inter-upvote sleep is LogNormal(mean=ln(45), σ=0.4) — realistic human
      browsing cadence.
    - Comment selection is seeded by hash(account_id + post_id) % pool_size
      so different accounts commenting on the same post pick different comments.
    - Subreddit subscription count is sampled per-account per-session.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import LogNormal, seed_for, _rng_from_seed
from ...core.reddit_client import (
    RedditClient,
    RedditSession,
    RedditSessionExpired,
    RedditRateLimited,
    RedditForbidden,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Distribution constants (LogNormal everywhere — no uniform)
# ---------------------------------------------------------------------------

# Number of upvotes per session: LogNormal, median ~10
UPVOTE_COUNT_DIST = LogNormal(low=5.0, high=15.0, sigma=0.35)

# Inter-upvote sleep: LogNormal(mean=ln(45), σ=0.4)
UPVOTE_SLEEP_DIST = LogNormal(low=8.0, high=180.0, sigma=0.40)

# Number of subreddits to subscribe in one session
SUB_COUNT_DIST = LogNormal(low=3.0, high=5.0, sigma=0.20)

# Number of comments per stage-2 session: 1-3
COMMENT_COUNT_DIST = LogNormal(low=1.0, high=3.0, sigma=0.30)

# Inter-comment sleep: longer than upvote to look human
COMMENT_SLEEP_DIST = LogNormal(low=30.0, high=300.0, sigma=0.45)

# ---------------------------------------------------------------------------
# Safe subreddit pool for stage 1 (30 entries)
# ---------------------------------------------------------------------------

SAFE_SUBSCRIBE_POOL: list[str] = [
    "funny", "gaming", "aww", "pics", "worldnews",
    "science", "technology", "movies", "music", "books",
    "food", "Fitness", "photography", "travel", "DIY",
    "AskReddit", "LifeProTips", "todayilearned", "explainlikeimfive",
    "mildlyinteresting", "nottheonion", "dataisbeautiful", "history",
    "personalfinance", "cooking", "gardening", "Art", "space",
    "nature", "dogs",
]

# Stage-2 comment subreddits (never OFM-adjacent)
SAFE_COMMENT_SUBREDDITS: list[str] = [
    "gaming", "Fitness", "AskReddit", "mildlyinteresting", "todayilearned",
    "funny", "movies", "books", "cooking", "science",
]

# ---------------------------------------------------------------------------
# Stage-2 generic comment pool (≥40 entries, nothing OFM-adjacent)
# Selection seeded by hash(account_id + post_id) % pool_size
# ---------------------------------------------------------------------------

COMMENT_POOL: list[str] = [
    "This is pretty interesting.",
    "Haven't seen this take before.",
    "Good points here.",
    "This actually makes a lot of sense.",
    "Appreciate you sharing this.",
    "I've been thinking about this lately too.",
    "Didn't know that, thanks.",
    "This changed how I think about it.",
    "Pretty solid breakdown.",
    "Same experience on my end.",
    "Honestly surprised this doesn't get more attention.",
    "This checks out.",
    "That's a fair point.",
    "Makes sense when you put it that way.",
    "Couldn't agree more.",
    "This is the kind of content I come here for.",
    "Well said.",
    "That's a good way to look at it.",
    "Interesting perspective.",
    "Never thought about it from this angle.",
    "I've heard similar things.",
    "This deserves more upvotes.",
    "Solid post.",
    "You're not wrong.",
    "This hits different.",
    "I was just wondering about this.",
    "Really useful, thanks.",
    "This is underrated.",
    "That's actually really helpful.",
    "Hadn't considered that.",
    "This is exactly right.",
    "Good to know.",
    "Came here to say the same thing.",
    "Yep, experienced the same.",
    "This needs to be higher up.",
    "Hard to argue with that.",
    "Valid.",
    "Genuinely helpful comment.",
    "This saved me some time, thanks.",
    "Legit useful info.",
    "Bookmarking this.",
    "Didn't realize that, cool.",
    "This resonates.",
    "Appreciate the detail.",
]

assert len(COMMENT_POOL) >= 40, "COMMENT_POOL must have at least 40 entries"


def _comment_for(account_id: str, post_id: str) -> str:
    """Deterministically select a comment seeded by (account_id, post_id)."""
    key = f"{account_id}|{post_id}"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(COMMENT_POOL)
    return COMMENT_POOL[idx]


# ---------------------------------------------------------------------------
# CQS calculation
# ---------------------------------------------------------------------------


def compute_cqs(
    karma_score: int,
    account_age_days: int,
    unique_subreddits_active: int,
) -> int:
    """
    CQS = karma_score + (account_age_days * 2) + (unique_subreddits_active * 5)
    """
    return karma_score + (account_age_days * 2) + (unique_subreddits_active * 5)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class RedditKarmaFarmingAgent(Agent):
    """
    Advances one Reddit account through the 4-stage karma farming pipeline.

    ctx keys:
        account_id:          str
        stage:               int (1-4)
        session:             RedditSession
        account_age_days:    int
        karma_score:         int
        comment_count:       int   (lifetime, from DB)
        unique_subreddits:   int   (lifetime unique subs active)
        session_cap_min:     int   (max session duration in minutes)
        subscribed_subs:     list[str]  (already subscribed, avoid repeats)
    """

    config = AgentConfig(
        name="reddit_karma_farming",
        max_iterations=1,
        max_usd_per_run=0.00,
        max_usd_per_session=0.00,
        allowed_tools=(
            "db.save_karma_farming_result",
            "db.mark_account_graduation_ready",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id      = ctx["account_id"]
        stage           = int(ctx.get("stage", 1))
        session: RedditSession = ctx["session"]
        account_age_days = int(ctx.get("account_age_days", 0))
        karma_score     = int(ctx.get("karma_score", 0))
        comment_count   = int(ctx.get("comment_count", 0))
        unique_subs     = int(ctx.get("unique_subreddits", 0))
        subscribed_subs = set(ctx.get("subscribed_subs", []))

        actions_taken: list[str] = []
        upvotes_cast    = 0
        comments_posted = 0
        posts_submitted = 0
        errors: list[str] = []

        self._audit_event(run, "farming_session_start", {
            "account_id": account_id,
            "stage": stage,
            "account_age_days": account_age_days,
            "karma_score": karma_score,
        })

        # Stage 4 accounts are handled by post_scheduler, not here
        if stage >= 4:
            log.info("Account %s is stage 4 — skipped by karma farming agent", account_id)
            run.outputs["skipped_stage_4"] = True
            return True

        async with RedditClient(session, proxy_url=ctx.get("proxy_url", "socks5://127.0.0.1:8089")) as client:

            # ------------------------------------------------------------------
            # Stage 1: Subscribe + upvote, NO comments
            # ------------------------------------------------------------------
            if stage >= 1:
                # Subscribe to 3-5 new subreddits
                n_subs = SUB_COUNT_DIST.sample_int(
                    account_id=account_id,
                    date_iso=datetime.now(timezone.utc).date().isoformat(),
                    field="sub_count",
                )
                available = [s for s in SAFE_SUBSCRIBE_POOL if s not in subscribed_subs]
                # Shuffle available pool deterministically per account+day
                rng = _rng_from_seed(seed_for(
                    account_id,
                    datetime.now(timezone.utc).date().isoformat(),
                    "sub_shuffle",
                ))
                rng.shuffle(available)
                to_subscribe = available[:n_subs]

                for sub in to_subscribe:
                    try:
                        self._audit_event(run, "subscribe_attempt", {"subreddit": sub})
                        await client.subscribe_subreddit(sub)
                        subscribed_subs.add(sub)
                        unique_subs += 1
                        actions_taken.append(f"subscribed:{sub}")
                    except RedditRateLimited as e:
                        log.warning("Rate limited subscribing %s for %s; sleeping %ds",
                                    sub, account_id, e.retry_after_sec)
                        await asyncio.sleep(min(e.retry_after_sec, 120))
                    except RedditForbidden:
                        log.warning("Forbidden to subscribe %s for %s", sub, account_id)
                    except RedditSessionExpired:
                        log.error("Session expired for %s during subscribe", account_id)
                        run.outputs["session_expired"] = True
                        return True

                # Upvote 5-15 posts from r/all feed
                n_upvotes = UPVOTE_COUNT_DIST.sample_int(
                    account_id=account_id,
                    date_iso=datetime.now(timezone.utc).date().isoformat(),
                    field="upvote_count",
                )
                n_upvotes = max(5, min(15, n_upvotes))

                try:
                    feed = await client.get_subreddit_posts("all", limit=25, sort="hot")
                except (RedditSessionExpired, RedditRateLimited, RedditForbidden) as e:
                    log.warning("Could not fetch feed for %s: %s", account_id, e)
                    errors.append(str(e))
                    feed = {}

                posts = feed.get("data", {}).get("children", [])[:n_upvotes]
                for post_item in posts:
                    post_data = post_item.get("data", {})
                    post_id   = post_data.get("name", "")  # e.g. "t3_abc123"
                    if not post_id:
                        continue

                    try:
                        self._audit_event(run, "upvote_attempt", {"post_id": post_id})
                        await client.upvote(post_id, direction=1)
                        upvotes_cast += 1
                        karma_score += 1  # approximate
                        actions_taken.append(f"upvoted:{post_id}")
                    except RedditRateLimited as e:
                        await asyncio.sleep(min(e.retry_after_sec, 120))
                        break
                    except (RedditSessionExpired, RedditForbidden) as e:
                        log.warning("Upvote failed for %s: %s", account_id, e)
                        break

                    # Inter-upvote sleep: LogNormal(mean=ln(45), σ=0.4)
                    sleep_s = UPVOTE_SLEEP_DIST.sample()
                    await asyncio.sleep(sleep_s)

            # ------------------------------------------------------------------
            # Stage 2: Additionally comment on 1-3 posts from SAFE subreddits
            # ------------------------------------------------------------------
            if stage >= 2:
                n_comments = COMMENT_COUNT_DIST.sample_int(
                    account_id=account_id,
                    date_iso=datetime.now(timezone.utc).date().isoformat(),
                    field="comment_count_session",
                )
                n_comments = max(1, min(3, n_comments))

                # Pick a safe subreddit to comment in
                sub_rng = _rng_from_seed(seed_for(
                    account_id,
                    datetime.now(timezone.utc).date().isoformat(),
                    "comment_sub_pick",
                ))
                comment_sub = sub_rng.choice(SAFE_COMMENT_SUBREDDITS)

                # Stage 2: prefer rising posts for commenting — they have less
                # competition, comments land higher, and early karma accumulates faster.
                try:
                    sub_feed = await client.get_subreddit_posts(comment_sub, limit=10, sort="rising")
                except (RedditSessionExpired, RedditRateLimited) as e:
                    log.warning("Could not fetch rising feed for comment: %s", e)
                    # Fallback to hot if rising fails
                    try:
                        sub_feed = await client.get_subreddit_posts(comment_sub, limit=10, sort="hot")
                    except Exception:
                        sub_feed = {}

                comment_posts = sub_feed.get("data", {}).get("children", [])[:n_comments * 2]

                commented = 0
                for post_item in comment_posts:
                    if commented >= n_comments:
                        break
                    post_data = post_item.get("data", {})
                    post_id   = post_data.get("name", "")
                    if not post_id:
                        continue

                    comment_text = _comment_for(account_id, post_id)

                    try:
                        self._audit_event(run, "comment_attempt", {
                            "post_id": post_id,
                            "subreddit": comment_sub,
                        })
                        await client.comment(post_id, comment_text)
                        commented += 1
                        comment_count += 1
                        comments_posted += 1
                        actions_taken.append(f"commented:{post_id}")
                    except RedditRateLimited as e:
                        await asyncio.sleep(min(e.retry_after_sec, 120))
                        break
                    except (RedditSessionExpired, RedditForbidden) as e:
                        log.warning("Comment failed for %s: %s", account_id, e)
                        break

                    sleep_s = COMMENT_SLEEP_DIST.sample()
                    await asyncio.sleep(sleep_s)

            # ------------------------------------------------------------------
            # Stage 3: Submit 1 text post with HumanPostBehavior
            # ------------------------------------------------------------------
            if stage >= 3:
                from ...core.human_post_behavior import (
                    pre_post_browse_delay,
                    compose_dwell,
                    typing_delay,
                    rethink_pause,
                    should_rethink,
                    select_template,
                )

                target_sub = "CasualConversation"  # low-competition default

                # Pre-post browse: read 3-5 posts first
                try:
                    browse_feed = await client.get_subreddit_posts(target_sub, limit=5, sort="hot")
                except Exception:
                    browse_feed = {}

                await pre_post_browse_delay()

                # Compose dwell
                await compose_dwell()

                # Build title + body from templates
                title_pool = [
                    "Anyone else noticed this lately?",
                    "Just a random thought I had today",
                    "Curious what you all think about this",
                    "This happened to me recently and I don't know how to feel",
                    "Hot take: this is underrated",
                    "Not sure if this is common but here goes",
                    "Unpopular opinion maybe but I stand by this",
                    "Genuine question for anyone who's been through this",
                    "Something small that made my day better",
                    "Realizing this for the first time at my age",
                    "Anyone have a good recommendation for this?",
                    "Finally did something I've been putting off forever",
                    "This changed how I approach my day",
                    "Looking back, this was obvious",
                    "Small win but it counts",
                    "Really basic question but I can't find a good answer",
                    "Venting a bit, hope that's okay",
                    "This community always has good perspective on stuff like this",
                    "Took me way too long to figure this out",
                    "Sharing something that helped me recently",
                ]
                body_pool = [
                    "Just something I've been chewing on. Curious if it resonates with anyone else here.",
                    "Wanted to get some outside perspectives on this. Open to being wrong.",
                    "Not looking for advice necessarily, just putting it out there.",
                    "This subreddit always has a good take on these kinds of things.",
                    "Feels like I'm the last person to figure this out but better late than never.",
                    "Maybe it's obvious but I never really thought about it until now.",
                    "Would love to hear if anyone's had a similar experience.",
                    "Not a huge deal, just something worth sharing.",
                    "If this has been posted before let me know, didn't want to search too hard.",
                    "Feel free to disagree, I'm genuinely curious what the consensus is.",
                    "This might just be a me thing but I figured I'd ask.",
                    "Could be a hot take, could be common knowledge. You tell me.",
                    "Been mulling this over for a while and finally decided to post.",
                    "Short version: this caught me off guard.",
                    "Nothing life-changing, just thought it was worth mentioning.",
                    "Probably overthinking it but here we are.",
                    "Didn't want to keep it to myself.",
                    "Open to other takes if I'm missing something obvious.",
                    "This community is usually pretty good about this kind of thing.",
                    "Happy to elaborate if anyone's curious.",
                ]

                if len(title_pool) < 20:
                    raise ValueError("title_pool must have at least 20 entries")
                if len(body_pool) < 20:
                    raise ValueError("body_pool must have at least 20 entries")

                title_seed = seed_for(
                    account_id,
                    datetime.now(timezone.utc).date().isoformat(),
                    "post_title",
                )
                body_seed = seed_for(
                    account_id,
                    datetime.now(timezone.utc).date().isoformat(),
                    "post_body",
                )
                title = select_template(title_pool, title_seed)
                body  = select_template(body_pool, body_seed)

                # Typing delay
                await typing_delay(title + " " + body)

                # Rethink pause (12% chance)
                if should_rethink():
                    await rethink_pause()

                try:
                    self._audit_event(run, "post_attempt", {
                        "subreddit": target_sub,
                        "title_hash": hashlib.sha256(title.encode()).hexdigest()[:8],
                    })
                    await client.submit_post(
                        subreddit=target_sub,
                        title=title,
                        text=body,
                        kind="self",
                    )
                    posts_submitted += 1
                    karma_score += 5  # approximate post karma
                    actions_taken.append(f"posted:{target_sub}")
                except (RedditRateLimited, RedditForbidden, RedditSessionExpired) as e:
                    log.warning("Post failed for %s: %s", account_id, e)
                    errors.append(str(e))

        # ------------------------------------------------------------------
        # CQS calculation
        # ------------------------------------------------------------------
        cqs_current = compute_cqs(karma_score, account_age_days, unique_subs)

        # ------------------------------------------------------------------
        # Graduation check (code-enforced thresholds)
        # ------------------------------------------------------------------
        graduation_ready = False
        if stage == 1 and account_age_days >= 7:
            graduation_ready = True
        elif stage == 2 and comment_count >= 20:
            graduation_ready = True
        elif stage == 3 and cqs_current >= 500:
            graduation_ready = True

        run.outputs.update({
            "actions_taken":    actions_taken,
            "upvotes_cast":     upvotes_cast,
            "comments_posted":  comments_posted,
            "posts_submitted":  posts_submitted,
            "cqs_current":      cqs_current,
            "graduation_ready": graduation_ready,
            "errors":           errors,
        })

        self._audit_event(run, "farming_session_end", {
            "cqs_current": cqs_current,
            "graduation_ready": graduation_ready,
            "upvotes_cast": upvotes_cast,
            "comments_posted": comments_posted,
        })

        return True

    def _audit_event(self, run: AgentRun, event_type: str, data: dict) -> None:
        event = {
            "event":  event_type,
            "ts":     datetime.now(timezone.utc).isoformat(),
            "agent":  self.config.name,
            **data,
        }
        run.audit_events.append(event)
        self.audit_sink(event)
