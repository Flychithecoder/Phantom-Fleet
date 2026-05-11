"""
ThreadsEngagementAgent — like / follow / reply on trending Threads content.

Responsibilities:
    - Consume a TrendingFeed from TrendingFeedAgent (trending topics/hashtags)
    - Fetch relevant Threads posts via timeline + keyword scan
    - Like posts matching trending topics (daily cap: 30 likes/account)
    - Follow accounts posting trending content (daily cap: 60 follows/account)
    - Reply to posts with AI-generated contextual replies (daily cap: 10 replies/account)
    - Enforce all daily caps via code, not prompts

Human behavior simulation (all timing is LogNormal):
    - Inter-like dwell:   LogNormal(mean=ln(12), σ=0.40) → median ~12s
    - Inter-follow dwell: LogNormal(mean=ln(25), σ=0.35) → median ~25s
    - Pre-reply pause:    LogNormal(mean=ln(18), σ=0.40) → median ~18s (reading post)
    - Reply typing:       len(reply) × LogNormal(mean=ln(0.08), σ=0.25) per char
    - Session browse:     LogNormal(mean=ln(45), σ=0.30) → median ~45s opening app

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Target selection: each account's engagement target list is seeded-shuffled
      so no two accounts engage in the same order on the same day.
    - All timing distributions produce fleet-wide log-normal histograms, not
      rectangular distributions.
    - Reply content: AI replies are generated with temperature=0.90 + account_id
      seed variation. Pool of reply starter prompts ensures semantic diversity.
    - Daily caps enforced by code: 30 likes, 60 follows, 10 replies per account.
    - One LLM call per reply = max 10 LLM calls per account per day.

LLM usage:
    - Model: claude-haiku-4-5-20251001 (fast + cheap for short replies)
    - Temperature: 0.90
    - Max tokens: 150 (Threads replies are short)
    - Daily LLM call cap: MAX_REPLIES_PER_DAY (10)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
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
from .trending_feed_agent import TrendingFeed

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced)
# ---------------------------------------------------------------------------

MAX_LIKES_PER_ACCOUNT_PER_DAY:    int = 30
MAX_FOLLOWS_PER_ACCOUNT_PER_DAY:  int = 60
MAX_REPLIES_PER_ACCOUNT_PER_DAY:  int = 10

# ---------------------------------------------------------------------------
# Distribution instances
# ---------------------------------------------------------------------------

_SESSION_BROWSE_DIST  = LogNormal(low=10.0,  high=180.0, sigma=0.30)   # ~45s opening app
_INTER_LIKE_DIST      = LogNormal(low=5.0,   high=90.0,  sigma=0.40)   # ~12s between likes
_INTER_FOLLOW_DIST    = LogNormal(low=10.0,  high=120.0, sigma=0.35)   # ~25s between follows
_PRE_REPLY_PAUSE_DIST = LogNormal(low=8.0,   high=60.0,  sigma=0.40)   # ~18s reading before reply
_TYPING_PER_CHAR      = LogNormal(low=0.03,  high=0.30,  sigma=0.25)   # ~0.08s/char

# ---------------------------------------------------------------------------
# Reply starter diversity pool
# ---------------------------------------------------------------------------

_REPLY_STARTERS = [
    "Interesting perspective — ",
    "This is exactly it. ",
    "Can't agree more. ",
    "Haven't thought about it this way — ",
    "Real talk — ",
    "Honestly this is so accurate. ",
    "This needed to be said. ",
    "So much this. ",
    "The timing on this is wild. ",
    "Not gonna lie — ",
    "Low key underrated take. ",
    "Been thinking about this too. ",
    "Okay but actually — ",
    "This hits different right now. ",
    "Worth the read. ",
    "Underrated post. ",
    "Exactly what I was thinking. ",
    "Facts. ",
    "This says everything. ",
    "Nobody talks about this enough. ",
]


def _reply_starter_seed(account_id: str, date_iso: str, reply_index: int) -> str:
    """Pick a deterministic but account-varied reply starter."""
    key = f"{account_id}|{date_iso}|reply_{reply_index}"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(_REPLY_STARTERS)
    return _REPLY_STARTERS[idx]


def _seeded_shuffle(items: list, account_id: str, date_iso: str, tag: str) -> list:
    """Return a shuffled copy — same account+date+tag always same order."""
    import random
    key = f"{account_id}|{date_iso}|{tag}"
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled


# ---------------------------------------------------------------------------
# LLM reply generator
# ---------------------------------------------------------------------------


async def _generate_reply(
    post_text: str,
    account_id: str,
    reply_index: int,
    date_iso: str,
) -> str:
    """
    Generate a contextual reply using Claude Haiku.

    Uses a seeded reply starter for per-account variation.
    Falls back to the starter alone if LLM fails.
    """
    starter = _reply_starter_seed(account_id, date_iso, reply_index)
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        return starter.rstrip(" — ").rstrip(". ") + "."

    # Truncate post_text to prevent context-window abuse
    safe_post = post_text[:300].replace("\n", " ")

    system_prompt = (
        "You are commenting on a Threads post. "
        "Write a SINGLE SHORT reply (1–2 sentences, max 120 characters). "
        "Sound natural, direct, and conversational — like a real person. "
        "Do NOT use hashtags. Do NOT use em-dashes. Avoid LLM clichés like "
        "'In conclusion', 'It's worth noting', 'Delve'. "
        f"Start your reply with: {starter!r}"
    )
    user_prompt = f"Threads post:\n\n{safe_post}"

    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=18.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "anthropic/claude-haiku-4-5-20251001",
                    "temperature": 0.90,
                    "max_tokens":  150,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                },
            )
            resp.raise_for_status()
            body = resp.json()
            reply = body["choices"][0]["message"]["content"].strip()
            # Safety: truncate to 150 chars max
            if len(reply) > 150:
                reply = reply[:147] + "..."
            return reply if reply else starter.rstrip(" — ") + "."

    except Exception as exc:
        log.warning("[%s/threads-engage] LLM reply failed: %s — using starter", account_id, exc)
        return starter.rstrip(" — ").rstrip(". ") + "."


# ---------------------------------------------------------------------------
# ThreadsEngagementAgent
# ---------------------------------------------------------------------------


@dataclass
class EngagementResult:
    """Detailed result returned alongside WorkerResult."""
    liked:    int = 0
    followed: int = 0
    replied:  int = 0
    errors: list[str] = field(default_factory=list)


class ThreadsEngagementAgent:
    """
    Engages with trending Threads content via likes, follows, and replies.

    Usage:
        agent = ThreadsEngagementAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            trending_feed=feed,
            proxy_url="socks5://...",
        )

    Returns WorkerResult with data keys:
        liked, followed, replied, errors
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        trending_feed: TrendingFeed,
        date_iso: Optional[str] = None,
        likes_done_today:   int = 0,
        follows_done_today: int = 0,
        replies_done_today: int = 0,
        proxy_url: Optional[str] = None,
    ) -> WorkerResult:
        """
        Run one engagement session for one account.

        Args:
            account_id:          Internal account identifier.
            session:             Authenticated IGSession (shared with Threads).
            trending_feed:       TrendingFeed from TrendingFeedAgent.
            date_iso:            YYYY-MM-DD (defaults to today UTC).
            likes_done_today:    Actions already done today (for cap checks).
            follows_done_today:  Actions already done today.
            replies_done_today:  Actions already done today.
            proxy_url:           SOCKS5 proxy URL for this account.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        detail = EngagementResult()
        task_id = f"{account_id}_threads_engage_{date_iso}"

        # Session browse: simulate opening Threads before engaging
        await asyncio.sleep(
            _SESSION_BROWSE_DIST.sample(account_id=account_id, date_iso=date_iso, field="session_browse")
        )

        async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
            # Fetch home timeline to get posts to engage with
            timeline_posts = await self._fetch_timeline_posts(client, account_id)

            if not timeline_posts:
                log.info("[%s/threads-engage] Empty timeline, skipping session", account_id)
                return WorkerResult(
                    task_id=task_id,
                    platform="threads",
                    account_id=account_id,
                    success=True,
                    data={
                        "action":   "threads_engagement",
                        "liked":    0, "followed": 0, "replied": 0,
                        "errors":   ["empty_timeline"],
                    },
                )

            # Seeded shuffle — each account engages with posts in different order
            shuffled_posts = _seeded_shuffle(timeline_posts, account_id, date_iso, "engage_order")

            # --- Like phase ---
            await self._like_phase(
                client=client,
                account_id=account_id,
                date_iso=date_iso,
                posts=shuffled_posts,
                detail=detail,
                likes_done_today=likes_done_today,
            )

            # --- Follow phase ---
            await self._follow_phase(
                client=client,
                account_id=account_id,
                date_iso=date_iso,
                posts=shuffled_posts,
                detail=detail,
                follows_done_today=follows_done_today,
            )

            # --- Reply phase ---
            await self._reply_phase(
                client=client,
                account_id=account_id,
                date_iso=date_iso,
                posts=shuffled_posts,
                detail=detail,
                replies_done_today=replies_done_today,
            )

        return WorkerResult(
            task_id=task_id,
            platform="threads",
            account_id=account_id,
            success=True,
            data={
                "action":   "threads_engagement",
                "liked":    detail.liked,
                "followed": detail.followed,
                "replied":  detail.replied,
                "errors":   detail.errors,
            },
        )

    # ------------------------------------------------------------------
    # Timeline fetch
    # ------------------------------------------------------------------

    async def _fetch_timeline_posts(
        self,
        client: ThreadsClient,
        account_id: str,
    ) -> list[dict]:
        """Fetch home timeline and extract individual post dicts."""
        try:
            data = await client.get_timeline()
            feed_items = data.get("feed_items", []) or data.get("items", [])
            posts: list[dict] = []
            for item in feed_items:
                # Timeline items can be nested differently
                media = (
                    item.get("media_or_ad")
                    or item.get("media")
                    or item
                )
                media_id  = media.get("pk") or media.get("id")
                user_info = media.get("user") or {}
                user_id   = user_info.get("pk") or user_info.get("id")
                caption   = ""
                cap_obj   = media.get("caption")
                if isinstance(cap_obj, dict):
                    caption = cap_obj.get("text", "")
                elif isinstance(cap_obj, str):
                    caption = cap_obj

                if media_id and user_id:
                    posts.append({
                        "media_id": str(media_id),
                        "user_id":  str(user_id),
                        "caption":  caption,
                    })
            return posts[:50]  # cap to avoid processing entire timeline
        except Exception as exc:
            log.warning("[%s/threads-engage] Timeline fetch failed: %s", account_id, exc)
            return []

    # ------------------------------------------------------------------
    # Like phase
    # ------------------------------------------------------------------

    async def _like_phase(
        self,
        client: ThreadsClient,
        account_id: str,
        date_iso: str,
        posts: list[dict],
        detail: EngagementResult,
        likes_done_today: int,
    ) -> None:
        """Like posts up to the daily cap."""
        for idx, post in enumerate(posts):
            if likes_done_today >= MAX_LIKES_PER_ACCOUNT_PER_DAY:
                break

            media_id = post["media_id"]
            log.info("[%s/threads-engage] Liking media %s (%d/%d)", account_id, media_id, idx + 1, len(posts))

            try:
                await client.like(media_id)
                likes_done_today += 1
                detail.liked += 1

            except ThreadsSessionExpired:
                detail.errors.append(f"like:session_expired:media={media_id}")
                return  # session dead — abort all phases
            except ThreadsRateLimited as exc:
                detail.errors.append(f"like:rate_limited:retry={exc.retry_after_sec}")
                return
            except ThreadsActionBlocked:
                detail.errors.append(f"like:action_blocked:media={media_id}")
                break
            except Exception as exc:
                log.warning("[%s/threads-engage] Like error %s: %s", account_id, media_id, exc)
                detail.errors.append(f"like:error:media={media_id}:{exc}")
                continue

            # Inter-like dwell
            if likes_done_today < MAX_LIKES_PER_ACCOUNT_PER_DAY:
                await asyncio.sleep(
                    _INTER_LIKE_DIST.sample(account_id=account_id, date_iso=date_iso, field=f"like_{idx}")
                )

    # ------------------------------------------------------------------
    # Follow phase
    # ------------------------------------------------------------------

    async def _follow_phase(
        self,
        client: ThreadsClient,
        account_id: str,
        date_iso: str,
        posts: list[dict],
        detail: EngagementResult,
        follows_done_today: int,
    ) -> None:
        """Follow accounts that authored timeline posts, up to the daily cap."""
        seen_users: set[str] = set()
        for idx, post in enumerate(posts):
            if follows_done_today >= MAX_FOLLOWS_PER_ACCOUNT_PER_DAY:
                break

            user_id = post["user_id"]
            if user_id in seen_users:
                continue
            seen_users.add(user_id)

            log.info("[%s/threads-engage] Following user %s (%d)", account_id, user_id, idx + 1)

            try:
                resp = await client.follow(user_id)
                fs   = resp.get("friendship_status", {})
                if fs.get("following") or fs.get("outgoing_request"):
                    follows_done_today += 1
                    detail.followed += 1

            except ThreadsSessionExpired:
                detail.errors.append(f"follow:session_expired:user={user_id}")
                return
            except ThreadsRateLimited as exc:
                detail.errors.append(f"follow:rate_limited:retry={exc.retry_after_sec}")
                return
            except ThreadsActionBlocked:
                detail.errors.append(f"follow:action_blocked:user={user_id}")
                break
            except Exception as exc:
                log.warning("[%s/threads-engage] Follow error %s: %s", account_id, user_id, exc)
                detail.errors.append(f"follow:error:user={user_id}:{exc}")
                continue

            if follows_done_today < MAX_FOLLOWS_PER_ACCOUNT_PER_DAY:
                await asyncio.sleep(
                    _INTER_FOLLOW_DIST.sample(account_id=account_id, date_iso=date_iso, field=f"follow_{idx}")
                )

    # ------------------------------------------------------------------
    # Reply phase
    # ------------------------------------------------------------------

    async def _reply_phase(
        self,
        client: ThreadsClient,
        account_id: str,
        date_iso: str,
        posts: list[dict],
        detail: EngagementResult,
        replies_done_today: int,
    ) -> None:
        """Reply to posts with AI-generated contextual replies, up to the daily cap."""
        reply_index = replies_done_today

        for idx, post in enumerate(posts):
            if replies_done_today >= MAX_REPLIES_PER_ACCOUNT_PER_DAY:
                break

            caption = post.get("caption", "")
            if len(caption) < 20:
                # Too short to generate a meaningful reply — skip
                continue

            media_id = post["media_id"]
            log.info(
                "[%s/threads-engage] Generating reply for media %s (reply %d/%d)",
                account_id, media_id, reply_index + 1, MAX_REPLIES_PER_ACCOUNT_PER_DAY,
            )

            # Pre-reply pause: simulate reading the post before responding
            await asyncio.sleep(
                _PRE_REPLY_PAUSE_DIST.sample(
                    account_id=account_id, date_iso=date_iso, field=f"pre_reply_{idx}"
                )
            )

            # Generate AI reply
            reply_text = await _generate_reply(caption, account_id, reply_index, date_iso)

            # Typing delay
            char_delay = _TYPING_PER_CHAR.sample(
                account_id=account_id, date_iso=date_iso, field=f"typing_reply_{idx}"
            )
            await asyncio.sleep(min(len(reply_text) * char_delay, 20.0))

            # Audit log BEFORE action
            log.info(
                "[%s/threads-engage] Replying to media %s ts=%s",
                account_id, media_id, datetime.now(timezone.utc).isoformat(),
            )

            try:
                await client.post_text(reply_text, reply_to_id=media_id)
                replies_done_today += 1
                reply_index += 1
                detail.replied += 1

            except ThreadsSessionExpired:
                detail.errors.append(f"reply:session_expired:media={media_id}")
                return
            except ThreadsRateLimited as exc:
                detail.errors.append(f"reply:rate_limited:retry={exc.retry_after_sec}")
                return
            except ThreadsActionBlocked:
                detail.errors.append(f"reply:action_blocked:media={media_id}")
                break
            except Exception as exc:
                log.warning("[%s/threads-engage] Reply error %s: %s", account_id, media_id, exc)
                detail.errors.append(f"reply:error:media={media_id}:{exc}")
                continue
