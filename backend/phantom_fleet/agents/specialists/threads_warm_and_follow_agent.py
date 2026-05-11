"""
ThreadsWarmAndFollowAgent — multi-step engagement sequence before following.

Instead of raw-following (which is obvious bot behavior), this agent:
    1. Views the target's profile
    2. Likes 1-2 of their recent posts (configurable)
    3. Optionally replies to one post with an AI-generated comment
    4. Waits a realistic dwell time
    5. Follows

This sequence mimics how a real person discovers someone and decides to follow:
they look at posts first, interact, then follow. Raw following with no prior
interaction is the #1 follow-bot signal on IG/Threads.

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Likes-before-follow count: LogNormal(mean=ln(1.5), σ=0.4) → 1 or 2 likes
      (not a fixed 2 for every account — fleet histogram must be natural).
    - Reply probability: 25% of warm-and-follow sequences include a reply.
      This means 5K/20K accounts reply before following → natural distribution.
    - Dwell between like and follow: LogNormal(mean=ln(18), σ=0.35) → median ~18s
    - Target order: seeded shuffle per account+date so fleet follow-graph edges
      don't all point in the same direction.
    - Daily cap: 30 warm-and-follow sequences per account (half the raw follow cap).
      Each sequence = 3-5 actions, so total action count is similar.

LLM (replies, 25% of sequences):
    - Model: claude-haiku-4-5-20251001
    - Temperature: 0.90
    - Max tokens: 100
    - Daily cap: 10 replies max (even if 30 warm sequences are run)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
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

MAX_SEQUENCES_PER_DAY: int = 30     # warm-and-follow sequences
MAX_REPLIES_PER_DAY:   int = 10     # even within warm sequences

REPLY_PROBABILITY = 0.25            # 25% of sequences include a reply

# ---------------------------------------------------------------------------
# Distribution instances
# ---------------------------------------------------------------------------

_PROFILE_DWELL    = LogNormal(low=4.0,   high=30.0,  sigma=0.35)   # viewing profile ~8s
_INTER_LIKE_DWELL = LogNormal(low=3.0,   high=20.0,  sigma=0.35)   # between likes ~6s
_PRE_FOLLOW_DWELL = LogNormal(low=8.0,   high=60.0,  sigma=0.35)   # before following ~18s
_INTER_SEQ_DWELL  = LogNormal(low=30.0,  high=300.0, sigma=0.50)   # between sequences ~60s


# ---------------------------------------------------------------------------
# Seeded helpers
# ---------------------------------------------------------------------------


def _seeded_shuffle(items: list, account_id: str, date_iso: str) -> list:
    import random
    seed = int.from_bytes(
        hashlib.sha256(f"{account_id}|{date_iso}|waf_order".encode()).digest()[:8], "big"
    )
    rng = random.Random(seed)
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled


def _likes_count(account_id: str, date_iso: str, seq_idx: int) -> int:
    """
    How many posts to like before following this target.
    LogNormal(mean=ln(1.5), σ=0.4) → mostly 1 or 2.
    """
    dist = LogNormal(low=1.0, high=3.0, sigma=0.40)
    raw = dist.sample(account_id=account_id, date_iso=date_iso, field=f"likes_count_{seq_idx}")
    return max(1, min(3, round(raw)))


def _should_reply(account_id: str, date_iso: str, seq_idx: int) -> bool:
    """25% chance of including a reply in this sequence (seeded, not truly random)."""
    key = f"{account_id}|{date_iso}|reply_roll_{seq_idx}"
    digest = hashlib.sha256(key.encode()).digest()
    value = int.from_bytes(digest[:4], "big") / (2**32)
    return value < REPLY_PROBABILITY


# ---------------------------------------------------------------------------
# AI reply generation
# ---------------------------------------------------------------------------


async def _generate_reply(post_caption: str, account_id: str) -> str:
    """Generate a short, natural reply to a Threads post."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        return "this is so good 🔥"

    safe_caption = post_caption[:200].replace("\n", " ")
    system = (
        "Write a short, natural reply to a Threads post. "
        "1-2 sentences max. Sound like a real person, not a bot. "
        "No hashtags. No em-dashes. No generic AI phrases. "
        "Don't start with 'I' every time."
    )
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "anthropic/claude-haiku-4-5-20251001",
                    "temperature": 0.90,
                    "max_tokens":  100,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": f"Post: {safe_caption}\n\nReply:"},
                    ],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()[:150]
    except Exception as exc:
        log.warning("[%s/waf] Reply LLM failed: %s", account_id, exc)
        return "this is actually so real 💀"


# ---------------------------------------------------------------------------
# ThreadsWarmAndFollowAgent
# ---------------------------------------------------------------------------


@dataclass
class WarmAndFollowResult:
    sequences_completed: int = 0
    likes_given:         int = 0
    replies_given:       int = 0
    follows_given:       int = 0
    errors: list[str] = field(default_factory=list)


class ThreadsWarmAndFollowAgent:
    """
    Multi-step warm-and-follow sequence on Threads.

    For each target:
        1. Like 1-2 of their posts
        2. Optionally reply to one (25% probability)
        3. Dwell (LogNormal ~18s)
        4. Follow

    Usage:
        agent = ThreadsWarmAndFollowAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            target_user_ids=["111", "222", ...],
            proxy_url="socks5://...",
        )
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        target_user_ids: list[str],
        date_iso: Optional[str] = None,
        sequences_done_today: int = 0,
        replies_done_today:   int = 0,
        proxy_url: Optional[str] = None,
    ) -> WorkerResult:
        if date_iso is None:
            date_iso = date.today().isoformat()

        shuffled = _seeded_shuffle(target_user_ids, account_id, date_iso)
        detail   = WarmAndFollowResult()
        task_id  = f"{account_id}_threads_waf_{date_iso}"

        async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
            for seq_idx, user_id in enumerate(shuffled):
                if sequences_done_today >= MAX_SEQUENCES_PER_DAY:
                    log.info("[%s/waf] Daily sequence cap (%d), stopping", account_id, MAX_SEQUENCES_PER_DAY)
                    break

                log.info(
                    "[%s/waf] Sequence %d/%d for user %s",
                    account_id, seq_idx + 1, len(shuffled), user_id,
                )

                seq_ok = await self._run_one_sequence(
                    client=client,
                    account_id=account_id,
                    user_id=user_id,
                    date_iso=date_iso,
                    seq_idx=seq_idx,
                    detail=detail,
                    replies_done_today=replies_done_today,
                )

                if seq_ok:
                    sequences_done_today += 1
                    replies_done_today = replies_done_today + (1 if detail.replies_given > 0 else 0)

                # Break on session-level errors
                if any("session_expired" in e or "rate_limited" in e for e in detail.errors[-3:]):
                    break

                # Inter-sequence dwell
                if seq_idx < len(shuffled) - 1 and sequences_done_today < MAX_SEQUENCES_PER_DAY:
                    await asyncio.sleep(
                        _INTER_SEQ_DWELL.sample(account_id=account_id, date_iso=date_iso, field=f"inter_seq_{seq_idx}")
                    )

        return WorkerResult(
            task_id=task_id,
            platform="threads",
            account_id=account_id,
            success=True,
            data={
                "action":               "warm_and_follow",
                "sequences_completed":  detail.sequences_completed,
                "likes_given":          detail.likes_given,
                "replies_given":        detail.replies_given,
                "follows_given":        detail.follows_given,
                "errors":               detail.errors,
            },
        )

    async def _run_one_sequence(
        self,
        client: ThreadsClient,
        account_id: str,
        user_id: str,
        date_iso: str,
        seq_idx: int,
        detail: WarmAndFollowResult,
        replies_done_today: int,
    ) -> bool:
        """
        Run one warm-and-follow sequence for one target.
        Returns True if the follow completed successfully.
        """
        # -- Profile dwell (simulate looking at their profile) --
        await asyncio.sleep(
            _PROFILE_DWELL.sample(account_id=account_id, date_iso=date_iso, field=f"profile_{seq_idx}")
        )

        # -- Fetch their recent posts --
        try:
            feed = await client.get_user_feed(user_id)
            feed_items = feed.get("items", []) or feed.get("feed_items", [])
        except (ThreadsSessionExpired, ThreadsRateLimited, ThreadsActionBlocked) as exc:
            detail.errors.append(f"feed_fetch:user={user_id}:{type(exc).__name__}")
            return False
        except Exception as exc:
            detail.errors.append(f"feed_fetch:user={user_id}:{exc}")
            return False

        # -- Like 1-2 posts --
        likes_target = _likes_count(account_id, date_iso, seq_idx)
        liked_media_ids: list[str] = []
        liked_captions:  list[str] = []

        for item in feed_items[:likes_target + 2]:  # try a few more in case some fail
            if len(liked_media_ids) >= likes_target:
                break
            media = item.get("media_or_ad") or item.get("media") or item
            media_id = media.get("pk") or media.get("id")
            if not media_id:
                continue
            cap_obj = media.get("caption")
            caption = ""
            if isinstance(cap_obj, dict):
                caption = cap_obj.get("text", "")
            elif isinstance(cap_obj, str):
                caption = cap_obj

            try:
                await client.like(str(media_id))
                liked_media_ids.append(str(media_id))
                liked_captions.append(caption)
                detail.likes_given += 1

                # Dwell between likes
                await asyncio.sleep(
                    _INTER_LIKE_DWELL.sample(account_id=account_id, date_iso=date_iso, field=f"like_dwell_{seq_idx}_{len(liked_media_ids)}")
                )
            except (ThreadsSessionExpired, ThreadsRateLimited) as exc:
                detail.errors.append(f"like:user={user_id}:{type(exc).__name__}")
                return False
            except Exception as exc:
                detail.errors.append(f"like:media={media_id}:{exc}")
                continue

        # -- Optional reply (25% chance, capped at MAX_REPLIES_PER_DAY) --
        if (
            liked_captions
            and replies_done_today < MAX_REPLIES_PER_DAY
            and _should_reply(account_id, date_iso, seq_idx)
        ):
            caption = next((c for c in liked_captions if len(c) >= 20), None)
            if caption and liked_media_ids:
                reply_text = await _generate_reply(caption, account_id)
                try:
                    await client.post_text(reply_text, reply_to_id=liked_media_ids[0])
                    detail.replies_given += 1
                    log.info("[%s/waf] Reply sent to media %s", account_id, liked_media_ids[0])
                except (ThreadsSessionExpired, ThreadsRateLimited) as exc:
                    detail.errors.append(f"reply:user={user_id}:{type(exc).__name__}")
                    return False
                except Exception as exc:
                    detail.errors.append(f"reply:media={liked_media_ids[0]}:{exc}")
                    # Non-fatal — still follow

        # -- Pre-follow dwell --
        await asyncio.sleep(
            _PRE_FOLLOW_DWELL.sample(account_id=account_id, date_iso=date_iso, field=f"pre_follow_{seq_idx}")
        )

        # -- Follow --
        try:
            resp = await client.follow(user_id)
            fs   = resp.get("friendship_status", {})
            if fs.get("following") or fs.get("outgoing_request"):
                detail.follows_given += 1
                detail.sequences_completed += 1
                log.info("[%s/waf] Followed user %s (seq %d done)", account_id, user_id, seq_idx + 1)
                return True
            else:
                # Might already be following
                detail.sequences_completed += 1
                return True
        except (ThreadsSessionExpired, ThreadsRateLimited) as exc:
            detail.errors.append(f"follow:user={user_id}:{type(exc).__name__}")
            return False
        except ThreadsActionBlocked:
            detail.errors.append(f"follow:user={user_id}:action_blocked")
            return False
        except Exception as exc:
            detail.errors.append(f"follow:user={user_id}:{exc}")
            return False
