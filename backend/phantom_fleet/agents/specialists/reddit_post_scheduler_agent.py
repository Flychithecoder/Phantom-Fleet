"""
RedditPostSchedulerAgent — Stage 4 full-activity post scheduler.

Dispatched by RedditAgentManager for accounts that have cleared the karma gate
(CQS >= 500, farming_stage >= 4). Posts OF-funnel content to the subreddit pool
assigned by the manager.

Stage 4 posting strategy:
    - of_advice subreddits   → Creator discussion posts (SFW, career-framing)
    - nsfw_content subreddits→ Tease introduction posts with bio-link CTA
    - sfw_niche subreddits   → Casual posts that grow CQS without funnel CTA

Content safety rules:
    - Never mention "OnlyFans", "Fanvue", or platform brand names on
      non-OF-specific subreddits (triggers automod spam filters).
    - On of_advice subreddits: use platform names freely (expected in context).
    - Bio link is the CTA anchor; post body says "link in bio" or
      "check my profile" — never a raw URL in the post body.
    - Hashtags: never. Reddit automod flags hashtag spam.
    - LLM detection tells: banned (no em-dashes, no "elevate", no "resonates").

Blast-radius constants (code-enforced):
    MAX_POSTS_PER_DAY:  3   — never more than 3 posts per account per day
    MIN_CQS_TO_POST:    500 — karma gate, not negotiable
    MIN_STAGE_TO_POST:  4   — stage gate, not negotiable
    MIN_TITLE_POOL_SIZE: 25 — pool diversity guard

Fleet-scale hardening (CLAUDE.md 20K-account rule):
    - Title and body selected by hash(account_id + date_iso + post_index)
      so 20K accounts posting to the same subreddit on the same day
      produce 20K different titles, not 1 title × 20K accounts.
    - Subreddit selection within the assigned pool is seeded-shuffled
      by hash(account_id + date_iso + "sub_order") so no two accounts
      hit the same subreddit in the same order.
    - Post timing offset uses Normal(0, 900) so fleet timestamps are
      spread across a ±15-minute Gaussian, not uniform.
    - All sleep values are LogNormal — never uniform or fixed.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import LogNormal, seed_for, _rng_from_seed
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

MAX_POSTS_PER_DAY:   int = 3
MIN_CQS_TO_POST:     int = 500
MIN_STAGE_TO_POST:   int = 4
MIN_TITLE_POOL_SIZE: int = 25
MIN_BODY_POOL_SIZE:  int = 25

# ---------------------------------------------------------------------------
# Inter-post delay: LogNormal so no two accounts share a uniform gap
# Median ~45 min between posts, σ=0.40
# ---------------------------------------------------------------------------
INTER_POST_SLEEP_DIST = LogNormal(low=900.0, high=7200.0, sigma=0.40)


# ---------------------------------------------------------------------------
# Title pools — per-category, ≥25 entries each
# Selection seeded by hash(account_id + date_iso + post_index) for diversity.
# ---------------------------------------------------------------------------

# For of_advice subreddits (r/onlyfansadvice, r/OnlyFans101, etc.)
# SFW creator-discussion framing — OF/Fanvue brand names allowed here.
OF_ADVICE_TITLE_POOL: list[str] = [
    "What's actually working for you right now in terms of organic reach?",
    "How are you structuring your posting schedule these days?",
    "Anyone else finding that consistency matters more than volume?",
    "What do you wish you knew before you started?",
    "How long before you started seeing real momentum?",
    "Is Reddit still worth it in 2025 or has the algo changed?",
    "What's your take on the bio link strategy — one link or multiple?",
    "How do you handle the slow months without burning out?",
    "Anyone switched platforms recently — what was the trigger?",
    "What's your ratio of free content to paid right now?",
    "How do you approach pricing when you're still building?",
    "Genuine question: do you respond to every DM or triage?",
    "What's been your best performing content type lately?",
    "How are you dealing with content theft without losing your mind?",
    "Any tools or workflows that saved you serious time?",
    "How much do you front-load vs stay reactive with your content?",
    "What changed the most for you between month 1 and month 6?",
    "Is cross-posting to multiple platforms worth the extra effort?",
    "How do you decide what goes free vs paid?",
    "What's your approach to building a core fan base vs broad reach?",
    "Anyone else experimenting with longer captions recently?",
    "How do you stay motivated when engagement dips?",
    "What would you tell yourself at the very beginning?",
    "How are you thinking about the long game on this?",
    "What metrics actually tell you something useful vs just noise?",
    "How do you handle the creative side when you're not feeling it?",
    "What's one thing you stopped doing that made your numbers better?",
]

# For nsfw_content subreddits (r/gonewild, r/amateur, r/SFWNextDoor, etc.)
# Introduction / tease format with bio-link CTA at end.
# Safe language: "my profile", "link in bio", "full set on my page"
NSFW_INTRO_TITLE_POOL: list[str] = [
    "New here and figured I'd finally post",
    "First post — hope this fits the vibe here",
    "Decided to finally stop lurking",
    "Been meaning to post for a while",
    "New here — hi",
    "First time posting, curious what you think",
    "Finally took the leap and posted",
    "Just found this sub and wanted to say hi properly",
    "Nervous to post but here we go",
    "New member checking in",
    "Long time lurker first time poster",
    "Hi from a new face here",
    "Took me a while but I finally posted",
    "Just joined and wanted to introduce myself",
    "First post — feedback welcome",
    "Started here today",
    "Figured this was the right place to share",
    "New here — testing the waters",
    "First post on this sub",
    "Hi everyone, new here",
    "Finally posting",
    "Jumping in for the first time",
    "New member — hello",
    "First time here, hope this works",
    "Just joined this community",
    "Finally made an account to post here",
    "Been watching this sub for a while",
    "New here and excited to be part of this",
]

assert len(OF_ADVICE_TITLE_POOL) >= MIN_TITLE_POOL_SIZE, \
    f"OF_ADVICE_TITLE_POOL needs >= {MIN_TITLE_POOL_SIZE} entries"
assert len(NSFW_INTRO_TITLE_POOL) >= MIN_TITLE_POOL_SIZE, \
    f"NSFW_INTRO_TITLE_POOL needs >= {MIN_TITLE_POOL_SIZE} entries"


# ---------------------------------------------------------------------------
# Body pools — per-category, ≥25 entries each
# ---------------------------------------------------------------------------

# of_advice body templates — discussion-expanding, open-ended
OF_ADVICE_BODY_POOL: list[str] = [
    "Just something I've been thinking about and wanted to hear different perspectives. Curious what's actually worked for people who are further along than I am.",
    "I keep reading conflicting things and I'm trying to figure out what actually applies in practice vs what sounds good in theory.",
    "Would love to hear from people who are past the early stages. What would you do differently if you were starting fresh with what you know now?",
    "Not looking for a magic answer, just trying to get a feel for what realistic expectations look like. What was your actual timeline?",
    "I've been experimenting with a few different approaches and honestly not sure what's moving the needle. Would love some honest feedback.",
    "The advice out there is pretty scattered and it's hard to know what's still relevant. What's been true for you recently?",
    "I'm past the very beginning but not where I want to be yet. Trying to figure out if I'm doing something wrong or if this is just the process.",
    "Not asking for specifics, just general direction from people who have been at this longer than I have.",
    "Happy to share what's working or not working on my end if that makes this a two-way conversation.",
    "I ask because the standard advice feels generic and I'm looking for something more grounded in actual experience.",
    "Would really appreciate hearing from people who've figured this out, even if it took a while.",
    "I've been at this for a few months and I'm still figuring out what's sustainable vs what burns people out.",
    "Honest question with no agenda. Just want to understand what the path actually looks like.",
    "Been overthinking this and figured it was better to just ask people who actually know.",
    "I'm trying to build something that lasts rather than just chase short-term numbers. Curious if that framing resonates.",
    "Would genuinely appreciate any perspective even if it's 'that's not how it works' — helpful to hear either way.",
    "Starting to feel like I need to commit to a direction and I want to make sure I'm thinking about this correctly first.",
    "Not overthinking it but also don't want to miss something obvious that everyone else already knows.",
    "I think I know the answer but I keep second-guessing myself. Useful to hear it from someone who's been there.",
    "Curious if this is a universal experience or just me.",
    "The more I learn the more questions I have. Trying to narrow it down to the things that actually matter.",
    "Would love a reality check from people who are past where I am right now.",
    "Hoping this is a good place to ask this without getting the usual copy-paste answers.",
    "Just want to hear what people actually did rather than what the advice says to do.",
    "Open to any takes including the ones that push back on what I said.",
    "Happy to share more context if it helps get a better answer.",
    "Figured this community would have the most honest take on this.",
]

# nsfw_content body templates — short, casual, bio-link CTA
# Rule: no raw URLs. "my profile" / "link in bio" only.
NSFW_INTRO_BODY_POOL: list[str] = [
    "Finally decided to stop lurking and actually post. More on my profile if you want to see more.",
    "Not sure what took me so long. More content on my page if this lands.",
    "Testing the waters here. Full stuff is on my profile.",
    "This felt like the right place. More on my page — link in my profile.",
    "Been thinking about posting here for a while. More on my profile.",
    "Figured I'd just go for it. Check my profile if you want more.",
    "Hi from a new face. More where this came from — link in my bio.",
    "Nervous but here we are. More content available on my profile.",
    "First post felt like the hardest part. More on my page.",
    "Finally took the step. Full content lives on my profile.",
    "Thought this was a good place to start. Check my profile for more.",
    "New here but not new to posting. More on my profile.",
    "Figured this was the right community. More stuff on my page — bio link.",
    "Here we go. More where this came from on my profile.",
    "Long time lurker, first time poster. More on my page if you like this.",
    "Said I'd post and here I am. More on my profile.",
    "Wanted to say hi properly. More content on my page — bio link.",
    "Taking the plunge. More on my profile.",
    "First but definitely not last. Check my profile.",
    "Hi. More on my page if you're interested.",
    "Finally. More on my profile.",
    "Decided today was the day. More content linked in my bio.",
    "Better late than never I guess. More on my profile page.",
    "Hello from a new member. More on my page — profile link.",
    "This is me posting for the first time. More where this came from.",
    "Jumping in. Check my profile for more.",
    "New here. More on my page.",
]

assert len(OF_ADVICE_BODY_POOL) >= MIN_BODY_POOL_SIZE, \
    f"OF_ADVICE_BODY_POOL needs >= {MIN_BODY_POOL_SIZE} entries"
assert len(NSFW_INTRO_BODY_POOL) >= MIN_BODY_POOL_SIZE, \
    f"NSFW_INTRO_BODY_POOL needs >= {MIN_BODY_POOL_SIZE} entries"


# ---------------------------------------------------------------------------
# Subreddit pool item — passed in from manager
# ---------------------------------------------------------------------------

@dataclass
class SubredditTarget:
    name:      str
    nsfw:      bool
    category:  str   # of_advice / nsfw_content / sfw_niche / general


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _title_hash(title: str) -> str:
    return hashlib.sha256(title.encode()).hexdigest()[:16]


def _dedup_key(account_id: str, subreddit: str, title: str) -> str:
    return f"{account_id}|{subreddit}|{_title_hash(title)}"


def _pick_pools(category: str) -> tuple[list[str], list[str]]:
    """Return (title_pool, body_pool) appropriate for the subreddit category."""
    if category in ("of_advice",):
        return OF_ADVICE_TITLE_POOL, OF_ADVICE_BODY_POOL
    # nsfw_content, sfw_niche, general → intro-style
    return NSFW_INTRO_TITLE_POOL, NSFW_INTRO_BODY_POOL


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class RedditPostSchedulerAgent(Agent):
    """
    Stage 4 NSFW/OF funnel post scheduler.

    ctx keys:
        account_id:      str
        stage:           int   (must be >= 4)
        cqs:             int   (must be >= 500)
        session:         RedditSession
        subreddit_pool:  list[dict]  each has {name, nsfw, category}
        posts_today:     int   (already posted today)
        used_titles:     list[str]  (dedup keys already used today)
        per_day_min:     int   (minimum posts target; default 1)
        per_day_max:     int   (maximum posts target; default 3)
        proxy_url:       str   (optional)
    """

    config = AgentConfig(
        name="reddit_post_scheduler",
        max_iterations=1,
        max_usd_per_run=0.00,
        max_usd_per_session=0.00,
        allowed_tools=(
            "db.save_post_record",
            "db.save_dedup_key",
            "db.update_reddit_farming_state",
            "db.increment_posts_today",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:  # noqa: C901
        account_id     = ctx["account_id"]
        stage          = int(ctx.get("stage", 4))
        cqs            = int(ctx.get("cqs", 0))
        session: RedditSession = ctx["session"]
        raw_pool       = ctx.get("subreddit_pool", [])
        posts_today    = int(ctx.get("posts_today", 0))
        used_titles: set[str] = set(ctx.get("used_titles", []))
        per_day_min    = int(ctx.get("per_day_min", 1))
        per_day_max    = int(ctx.get("per_day_max", 3))
        proxy_url      = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        # ------------------------------------------------------------------
        # Hard gates — code-enforced, never bypass
        # ------------------------------------------------------------------
        if stage < MIN_STAGE_TO_POST:
            log.info("Account %s is stage %d — minimum to post is %d",
                     account_id, stage, MIN_STAGE_TO_POST)
            run.outputs["blocked_stage"] = True
            return True

        if cqs < MIN_CQS_TO_POST:
            log.info("Account %s has CQS %d — minimum is %d",
                     account_id, cqs, MIN_CQS_TO_POST)
            run.outputs["blocked_cqs"] = True
            run.outputs["cqs_current"] = cqs
            return True

        if posts_today >= MAX_POSTS_PER_DAY:
            log.info("Account %s hit daily post cap (%d)", account_id, MAX_POSTS_PER_DAY)
            run.outputs["cap_hit"] = True
            return True

        if not raw_pool:
            log.warning("Account %s has no subreddit pool assigned", account_id)
            run.outputs["no_pool"] = True
            return True

        # ------------------------------------------------------------------
        # Build SubredditTarget list from pool
        # ------------------------------------------------------------------
        pool: list[SubredditTarget] = [
            SubredditTarget(
                name=s["name"],
                nsfw=bool(s.get("nsfw", False)),
                category=s.get("category", "general"),
            )
            for s in raw_pool
            if s.get("name")
        ]

        # ------------------------------------------------------------------
        # Determine target post count for today
        # cap_min..cap_max, sampled per (account, date)
        # ------------------------------------------------------------------
        date_iso    = datetime.now(timezone.utc).date().isoformat()
        target_seed = seed_for(account_id, date_iso, "posts_target")
        rng         = _rng_from_seed(target_seed)
        per_day_max = min(per_day_max, MAX_POSTS_PER_DAY)
        per_day_min = min(per_day_min, per_day_max)
        target_posts = rng.randint(per_day_min, per_day_max)
        remaining    = target_posts - posts_today

        if remaining <= 0:
            run.outputs["cap_hit"] = True
            return True

        # ------------------------------------------------------------------
        # Seeded-shuffle the subreddit pool so every account hits subs
        # in a different order (no fleet-wide synchronized post order).
        # ------------------------------------------------------------------
        sub_seed = seed_for(account_id, date_iso, "sub_order")
        sub_rng  = _rng_from_seed(sub_seed)
        sub_rng.shuffle(pool)

        self._audit_event(run, "scheduler_start", {
            "account_id":    account_id,
            "stage":         stage,
            "cqs":           cqs,
            "posts_today":   posts_today,
            "target_posts":  target_posts,
            "pool_size":     len(pool),
        })

        posts_submitted    = 0
        posts_skipped_dup  = 0
        subreddits_posted: list[str] = []
        errors: list[str]  = []

        async with RedditClient(session, proxy_url=proxy_url) as client:

            for sub in pool:
                if posts_submitted >= remaining:
                    break
                if posts_today + posts_submitted >= MAX_POSTS_PER_DAY:
                    break

                post_index = posts_today + posts_submitted
                title_pool, body_pool = _pick_pools(sub.category)

                # Pick title + body seeded per (account, date, post_index)
                title_seed = seed_for(account_id, date_iso, f"title_{post_index}_{sub.name}")
                body_seed  = seed_for(account_id, date_iso, f"body_{post_index}_{sub.name}")
                title      = select_template(title_pool, title_seed)
                body       = select_template(body_pool, body_seed)

                # Dedup check
                dk = _dedup_key(account_id, sub.name, title)
                if dk in used_titles:
                    posts_skipped_dup += 1
                    log.info("Dedup: %s already used title %r in r/%s",
                             account_id, title[:40], sub.name)
                    continue

                self._audit_event(run, "post_plan", {
                    "subreddit":   sub.name,
                    "nsfw":        sub.nsfw,
                    "category":    sub.category,
                    "title_hash":  _title_hash(title),
                    "body_len":    len(body),
                })

                # Pre-post browse (reads 5 hot posts from the target sub)
                try:
                    await client.get_subreddit_posts(sub.name, limit=5, sort="hot")
                except Exception as e:
                    log.warning("Pre-post browse failed for %s in r/%s: %s",
                                account_id, sub.name, e)
                await pre_post_browse_delay()

                # Compose dwell
                await compose_dwell()

                # Typing delay (title + body character count)
                await typing_delay(title + " " + body)

                # Rethink pause (12% chance)
                if should_rethink():
                    await rethink_pause()

                # Post timing jitter (not a sleep — logged for audit)
                jitter = post_time_jitter_seconds()
                self._audit_event(run, "post_jitter", {"jitter_seconds": jitter})

                post_url      = ""
                post_id       = ""
                _post_success = False

                try:
                    self._audit_event(run, "post_submit", {
                        "subreddit":  sub.name,
                        "nsfw":       sub.nsfw,
                        "title_hash": _title_hash(title),
                    })
                    result = await client.submit_post(
                        subreddit=sub.name,
                        title=title,
                        text=body,
                        kind="self",
                        nsfw=sub.nsfw,
                    )
                    posts_submitted += 1
                    subreddits_posted.append(sub.name)
                    used_titles.add(dk)

                    post_url = (
                        result.get("json", {})
                              .get("data", {})
                              .get("url", "")
                    )
                    post_id  = (
                        result.get("json", {})
                              .get("data", {})
                              .get("id", "")
                    )
                    _post_success = True

                    self._audit_event(run, "post_success", {
                        "subreddit": sub.name,
                        "post_url":  post_url,
                        "post_id":   post_id,
                    })

                except RedditRateLimited as e:
                    log.warning("Rate limited posting for %s in r/%s: retry %ds",
                                account_id, sub.name, e.retry_after_sec)
                    run.outputs["rate_limited"]  = True
                    run.outputs["retry_after"]   = e.retry_after_sec
                    errors.append(f"rate_limited:{sub.name}")
                    break   # stop for this session; agent will retry later

                except RedditForbidden:
                    log.warning("Forbidden to post in r/%s for %s", sub.name, account_id)
                    errors.append(f"forbidden:{sub.name}")
                    # Don't break — try the next subreddit

                except RedditSessionExpired:
                    log.error("Session expired for %s during post scheduler", account_id)
                    run.outputs["session_expired"] = True
                    return True

                except Exception as e:
                    log.error("Unexpected error posting for %s in r/%s: %s",
                              account_id, sub.name, e)
                    errors.append(f"error:{sub.name}:{type(e).__name__}")

                # DB persistence — outside Reddit error scope so ToolNotAllowed
                # propagates instead of being silently caught as a posting error.
                if _post_success:
                    await self.tool("db.save_post_record", {
                        "account_id": account_id,
                        "subreddit":  sub.name,
                        "title_hash": _title_hash(title),
                        "title":      title,
                        "post_url":   post_url,
                        "post_id":    post_id,
                        "nsfw":       sub.nsfw,
                        "category":   sub.category,
                    })
                    await self.tool("db.save_dedup_key", dk)

                # Inter-post sleep: only if more posts remain
                if posts_submitted < remaining and posts_today + posts_submitted < MAX_POSTS_PER_DAY:
                    sleep_s = INTER_POST_SLEEP_DIST.sample()
                    log.debug("Inter-post sleep: %.1fs for %s", sleep_s, account_id)
                    await asyncio.sleep(sleep_s)

        # ------------------------------------------------------------------
        # Update daily counter via DB tool
        # ------------------------------------------------------------------
        if posts_submitted > 0:
            await self.tool("db.increment_posts_today", {
                "account_id": account_id,
                "increment":  posts_submitted,
            })
            await self.tool("db.update_reddit_farming_state", {
                "account_id":       account_id,
                "posts_submitted":  posts_submitted,
            })

        run.outputs.update({
            "posts_submitted":      posts_submitted,
            "posts_skipped_dedup":  posts_skipped_dup,
            "subreddits_posted_to": subreddits_posted,
            "errors":               errors,
        })

        self._audit_event(run, "scheduler_end", {
            "posts_submitted":     posts_submitted,
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
