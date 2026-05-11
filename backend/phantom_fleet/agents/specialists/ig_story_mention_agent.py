"""
IGStoryMentionAgent — Monitors for story mentions and auto-reposts them.

When a fan tags the creator in their own story, Instagram sends a notification.
This agent monitors those mentions and reposts them as the creator's own story,
adding a thank-you overlay. The repost creates a positive interaction loop:
fans see their mention get reshared → more fans mention the creator.

Design decisions (CLAUDE.md fleet-scale audit):

    Follower count filter (>= 100):
        Prevents reposts from bots or empty accounts. A 0-follower account
        tagging us is almost certainly spam or a test account.

    Dedup by story_pk:
        Every mention is uniquely identified by the story's primary key.
        We never repost the same story twice even if the monitor runs
        multiple times (e.g. after a restart).

    Thank-you overlay selection:
        Seeded by hash(account_id + mentioner_id) so:
        - Same creator always uses same overlay for same mentioner (stable)
        - Different mentioners get different overlays (variety)
        - Fleet-wide distribution across the 10-template pool is uniform

    Daily cap 10/day:
        Code-enforced. Too many reposts in one day looks spammy and
        over-saturates the creator's story feed.

    Between-repost stagger:
        LogNormal(mean=ln(60), sigma=0.4) — median ~60s, tail to ~300s.
        Prevents a burst of 10 reposts in under a minute (clustering).

Agent audit table (CLAUDE.md):
    ┌─────────────────┬──────────────────────────────────────────────────────┐
    │ Agent           │ IGStoryMentionAgent                                  │
    │ Purpose         │ Monitor story mentions + repost with thank-you       │
    │ Tools           │ None — direct HTTP via InstagramClient               │
    │ Untrusted input │ Mentioner user data from IG API (display-only)       │
    │ User isolation  │ Keyed by account_id — no shared state                │
    │ Cost cap        │ No LLM — zero per-run LLM cost                       │
    │ Loop cap        │ 10 reposts/day (code-enforced)                       │
    │ Confirmation    │ None required                                        │
    └─────────────────┴──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import IGSession, InstagramClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Daily hard cap — code-enforced
# ---------------------------------------------------------------------------

_DAILY_REPOST_CAP: int = 10

# ---------------------------------------------------------------------------
# Mentioner quality filter
# ---------------------------------------------------------------------------

_MIN_MENTIONER_FOLLOWERS: int = 100   # ignore bots / empty accounts

# ---------------------------------------------------------------------------
# Stagger between reposts
# LogNormal(mean=ln(60), sigma=0.4) → median ~60s, tail to ~300s
# ---------------------------------------------------------------------------

_REPOST_STAGGER_DIST = LogNormal(low=10.0, high=300.0, sigma=0.40)

# ---------------------------------------------------------------------------
# Thank-you overlay pool — minimum 10 entries
# Seeded per (account_id, mentioner_id) for stable-but-varied assignment
# ---------------------------------------------------------------------------

THANK_YOU_OVERLAYS: list[str] = [
    "love you for this 🫶",
    "you're everything 💜",
    "thank you babe 🥺",
    "this made my day ✨",
    "you're so sweet 💋",
    "omg I love this 🥹",
    "you're the reason I do this 🌙",
    "forever grateful for you 🤍",
    "this literally made me smile 💜",
    "can't get over how sweet this is 🫶",
    "you always know how to make my day ✨",
    "honestly thank you so much 💋",
]


# ---------------------------------------------------------------------------
# Task type
# ---------------------------------------------------------------------------

@dataclass
class IGStoryMentionTask:
    """Input for one IGStoryMentionAgent monitor run."""
    account_id:        str
    ig_session:        IGSession
    already_reposted:  set[str] = field(default_factory=set)   # story_pk strings
    reposts_today:     int      = 0
    proxy_url:         str      = "socks5://127.0.0.1:8089"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IGStoryMentionAgent:
    """
    Monitors for story mentions (when fans tag our account) and
    auto-reposts them as our own story.

    Fan mentions are social proof — reposts them + thank-you overlay
    creates a positive interaction loop and encourages more mentions.
    """

    def __init__(self) -> None:
        pass

    async def monitor_and_repost(
        self,
        task: IGStoryMentionTask,
    ) -> WorkerResult:
        """
        Fetch all recent story mentions, filter qualified ones, and repost.

        Steps:
            1. Fetch mentions via client.get_story_mentions()
            2. Filter: mentioner.follower_count >= 100
            3. Filter: not already reposted (dedup by story_pk)
            4. Enforce daily cap (10 reposts/day, code-enforced)
            5. For each qualified mention:
               a. Select thank-you overlay (seeded per mentioner)
               b. Repost via client.repost_story_mention()
               c. Add story_pk to dedup set
               d. LogNormal stagger before next repost
            6. Return WorkerResult with per-mention audit log
        """
        errors:   list[str] = []
        reposted: list[dict] = []
        skipped:  list[dict] = []

        async with InstagramClient(task.ig_session, proxy_url=task.proxy_url) as client:
            # Step 1: fetch mentions
            try:
                mentions = await client.get_story_mentions()
            except Exception as exc:
                err = f"get_story_mentions_failed:{type(exc).__name__}:{exc}"
                log.error("[%s] %s", task.account_id, err)
                return _failure_result(task, [err])

            log.debug(
                "[%s] fetched %d story mention(s)",
                task.account_id, len(mentions),
            )

            reposts_this_run = 0

            for mention in mentions:
                story_pk       = mention.get("story_pk", "")
                mentioner_id   = mention.get("mentioner_user_id", "")
                mentioner_name = mention.get("mentioner_username", "")
                follower_count = int(mention.get("mentioner_follower_count", 0))

                # Step 2: follower count filter
                if follower_count < _MIN_MENTIONER_FOLLOWERS:
                    log.debug(
                        "[%s] skipping mention by @%s (followers=%d < %d)",
                        task.account_id, mentioner_name,
                        follower_count, _MIN_MENTIONER_FOLLOWERS,
                    )
                    skipped.append({
                        "reason": "follower_count_too_low",
                        "mentioner": mentioner_name,
                        "follower_count": follower_count,
                    })
                    continue

                # Step 3: dedup check
                if story_pk in task.already_reposted:
                    log.debug(
                        "[%s] skipping already-reposted story_pk=%s",
                        task.account_id, story_pk,
                    )
                    skipped.append({
                        "reason": "already_reposted",
                        "story_pk": story_pk,
                        "mentioner": mentioner_name,
                    })
                    continue

                # Step 4: daily cap check
                total_reposts = task.reposts_today + reposts_this_run
                if total_reposts >= _DAILY_REPOST_CAP:
                    log.info(
                        "[%s] daily repost cap reached (%d/%d), stopping",
                        task.account_id, total_reposts, _DAILY_REPOST_CAP,
                    )
                    break

                # Step 5a: select thank-you overlay
                overlay = select_thank_you_overlay(
                    THANK_YOU_OVERLAYS,
                    task.account_id,
                    mentioner_id,
                )

                # Step 5b: repost
                try:
                    ok = await client.repost_story_mention(story_pk, overlay)
                except Exception as exc:
                    err = (
                        f"repost_failed:"
                        f"story_pk={story_pk}:"
                        f"mentioner={mentioner_name}:"
                        f"{type(exc).__name__}:{exc}"
                    )
                    log.error("[%s] %s", task.account_id, err)
                    errors.append(err)
                    continue

                if not ok:
                    err = f"repost_not_ok:story_pk={story_pk}"
                    log.warning("[%s] %s", task.account_id, err)
                    errors.append(err)
                    continue

                # Step 5c: mark as reposted
                task.already_reposted.add(story_pk)
                reposts_this_run += 1

                reposted.append({
                    "story_pk":       story_pk,
                    "mentioner_id":   mentioner_id,
                    "mentioner_name": mentioner_name,
                    "follower_count": follower_count,
                    "overlay":        overlay,
                })
                log.info(
                    "[%s] reposted mention from @%s (followers=%d) with overlay=%r",
                    task.account_id, mentioner_name, follower_count, overlay,
                )

                # Step 5d: stagger before next repost
                if reposts_this_run < _DAILY_REPOST_CAP:
                    gap = _REPOST_STAGGER_DIST.sample()
                    await asyncio.sleep(gap)

        return WorkerResult(
            task_id    = f"ig_story_mention_{task.account_id}",
            platform   = "instagram",
            account_id = task.account_id,
            success    = True,
            error      = "; ".join(errors) if errors else None,
            data       = {
                "reposted_count": reposts_this_run,
                "reposted":       reposted,
                "skipped":        skipped,
                "errors":         errors,
            },
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def select_thank_you_overlay(
    pool: list[str],
    account_id: str,
    mentioner_id: str,
) -> str:
    """
    Select a thank-you overlay from the pool using a deterministic seed.

    Seed = hash(account_id + mentioner_id) so:
    - Same creator always uses the same overlay for the same mentioner (stable)
    - Different mentioners receive different overlays (variety at fleet scale)
    """
    if not pool:
        raise ValueError("thank-you overlay pool must not be empty")
    seed_input = (account_id + mentioner_id).encode("utf-8")
    seed = int(hashlib.sha256(seed_input).hexdigest(), 16)
    idx = seed % len(pool)
    return pool[idx]


def _failure_result(task: IGStoryMentionTask, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id    = f"ig_story_mention_{task.account_id}",
        platform   = "instagram",
        account_id = task.account_id,
        success    = False,
        error      = "; ".join(errors),
        data       = {
            "reposted_count": 0,
            "errors":         errors,
        },
    )
