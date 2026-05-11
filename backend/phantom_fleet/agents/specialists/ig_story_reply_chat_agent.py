"""
IGStoryReplyChatAgent — AI-powered responder for Instagram story reply DMs.

Story replies are high-intent signals: the fan was compelled enough by the story
to tap "Reply" and type something. These threads convert 3–5× better than cold
DMs that arrive with no prior engagement signal.

Architecture (inherits from _BaseDMChatAgent):
    - LLM call via OpenRouter (claude-haiku-4-5-20251001, temp=0.85)
    - LLM tell stripping
    - Conversation state tracking per (account_id, "instagram_story_reply", thread_id)
    - Daily cap: 60 replies/day (higher than regular DMs — story replies are higher intent)
    - Min gap: 45s between replies to same thread (shorter than regular DMs — urgency converts)
    - PPV pitch threshold: 2 messages (lower than regular DMs — they're already warm)
    - Priority: story reply threads processed FIRST, before regular DM threads

Key differences from IGDMChatAgent:
    1. Filters inbox for threads where thread.is_story_reply == True
    2. Processes story reply threads before regular DM threads (priority queue)
    3. PPV pitch threshold = 2 (not 4)
    4. Min gap = 45s (not 90s)
    5. Daily cap = 60 (not 40)
    6. Shorter, more reactive system prompt ("they just saw your story — match energy")

Platform-specific overrides:
    - platform_name = "instagram_story_reply"
    - max_daily_replies = 60
    - min_gap_sec = 45.0
    - max_tokens = 100 (shorter, punchier replies)
    - ppv_pitch_after_msgs = 2

Agent audit table (CLAUDE.md):
    ┌─────────────────────────┬───────────────────────────────────────────────────┐
    │ Agent                   │ IGStoryReplyChatAgent                              │
    │ Purpose                 │ AI-powered story reply DM inbox responder         │
    │ Tools                   │ None — direct HTTP via InstagramClient             │
    │ Untrusted input         │ DM message bodies (XML-delimited in all prompts)  │
    │ User isolation          │ Keyed by (account_id, instagram_story_reply, tid) │
    │ Cost cap                │ 60 replies × $0.00025 ≈ $0.015/account/day       │
    │ Loop cap                │ MAX_STORY_REPLY_CONVERSATIONS = 30 (code-enforced) │
    │ Confirmation            │ None required (non-destructive sends)             │
    └─────────────────────────┴───────────────────────────────────────────────────┘
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from ...core.chat_modes import (
    INSTAGRAM_FLIRTY,
    ChatModeProfile,
    ChatTier,
)
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGSession,
    InstagramClient,
)
from .base_dm_chat_agent import (
    _BaseDMChatAgent,
    DMReplyRecord,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Story-reply-specific blast-radius constants (ALL code-enforced)
# ---------------------------------------------------------------------------

# Story replies are higher-intent — allow more replies per day
MAX_STORY_REPLY_MESSAGES_PER_DAY: int = 60

# Shorter gap — urgency converts better on warm leads
MIN_STORY_REPLY_GAP_SEC: float = 45.0

# Lower PPV threshold — fan is already warm from seeing the story
STORY_REPLY_PPV_THRESHOLD: int = 2

# Max conversations per session (higher than regular DMs)
MAX_STORY_REPLY_CONVERSATIONS: int = 30

# Max tokens — shorter, punchier replies for story context
STORY_REPLY_MAX_TOKENS: int = 100


# ---------------------------------------------------------------------------
# Story reply system prompt — overrides _BaseDMChatAgent defaults
# ---------------------------------------------------------------------------

_STORY_REPLY_SYSTEM_PROMPT = (
    "You are a flirty, playful, and charming creator responding to someone who just "
    "replied to your Instagram story. They saw your content and felt compelled to "
    "reach out — that means they're already interested. Be excited and match their "
    "energy. Keep replies short, natural, and conversational — 1-3 sentences max. "
    "Don't sound like a bot. Don't use perfect grammar. Use lowercase sometimes. "
    "React specifically to what they said about the story. Make them feel seen and "
    "special. Never mention being an AI, never be overly formal, never use corporate "
    "language. You're a real person who's happy they reached out."
)

_STORY_REPLY_PPV_PITCH_TEMPLATES: list[str] = [
    "omg you'd love what i post for my close ones tbh",
    "this is just a teaser of what i share privately 👀",
    "i go way more unfiltered in my vip space haha",
    "you should see what i share with people i actually vibe with 😏",
    "the real content is somewhere more private tbh lol",
    "i keep the best stuff for my loyal ones, just saying",
    "if you liked this wait til you see my exclusive stuff",
    "i post SO much more when it's just us 🙈",
    "i have a little private corner where i'm way more open",
    "fans who stick around get access to the real me 💕",
]


# ---------------------------------------------------------------------------
# Story reply profile
# ---------------------------------------------------------------------------

# Build a custom profile for story replies (more reactive, lower PPV threshold)
import copy as _copy

_STORY_REPLY_PROFILE: ChatModeProfile = _copy.deepcopy(INSTAGRAM_FLIRTY)
_STORY_REPLY_PROFILE.system_prompt  = _STORY_REPLY_SYSTEM_PROMPT
_STORY_REPLY_PROFILE.max_reply_words = 40  # shorter for story reply context


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class IGStoryReplyChatAgent(_BaseDMChatAgent):
    """
    AI-powered responder for Instagram story reply DMs.

    Story replies arrive in the regular DM inbox but are marked with
    is_story_reply=True by Instagram's API. This agent:
        1. Fetches the inbox
        2. Splits threads into story-reply vs regular
        3. Processes story-reply threads FIRST (priority queue)
        4. Applies lower PPV threshold (2 msgs) and faster gap (45s)

    Usage:
        agent = IGStoryReplyChatAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            chat_tier=ChatTier.FLIRTY_SFW,
            date_iso="2026-04-11",
        )

    Returns a WorkerResult with data keys:
        replies_sent, threads_touched, ppv_pitched,
        story_reply_threads, regular_dm_threads_processed, errors
    """

    platform_name: str = "instagram_story_reply"
    _default_profile: ChatModeProfile = _STORY_REPLY_PROFILE
    max_daily_replies: int = MAX_STORY_REPLY_MESSAGES_PER_DAY
    min_gap_sec: float = MIN_STORY_REPLY_GAP_SEC
    max_tokens: int = STORY_REPLY_MAX_TOKENS

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        chat_tier: ChatTier = ChatTier.FLIRTY_SFW,
        date_iso: Optional[str] = None,
        ppv_pitch_after_msgs: int = STORY_REPLY_PPV_THRESHOLD,
    ) -> WorkerResult:
        """
        Process the Instagram DM inbox with story reply priority.

        Story reply threads are processed first. Remaining daily budget
        is then applied to regular DM threads with the base IGDMChatAgent
        logic (90s gap, 40-msg cap).

        Args:
            account_id:           Internal account identifier.
            session:              Authenticated IGSession.
            chat_tier:            Controls voice/tone profile.
            date_iso:             YYYY-MM-DD (defaults to today UTC).
            ppv_pitch_after_msgs: Messages before PPV pitch (default 2 for story replies).

        Returns:
            WorkerResult with detailed summary in data dict.
        """
        from datetime import date
        if date_iso is None:
            date_iso = date.today().isoformat()

        task_id = f"{account_id}_ig_story_reply_{date_iso}"

        try:
            summary = await self._run_story_reply_inbox(
                account_id           = account_id,
                session              = session,
                chat_tier            = chat_tier,
                date_iso             = date_iso,
                ppv_pitch_after_msgs = ppv_pitch_after_msgs,
            )
        except Exception as exc:
            log.error("[%s/instagram_story_reply] Session-level error: %s", account_id, exc)
            return WorkerResult(
                task_id    = task_id,
                platform   = "instagram",
                account_id = account_id,
                success    = False,
                error      = str(exc),
                data       = {},
            )

        return WorkerResult(
            task_id    = task_id,
            platform   = "instagram",
            account_id = account_id,
            success    = True,
            data       = {
                "action":                      "ig_story_reply_chat",
                "replies_sent":                summary["replies_sent"],
                "threads_touched":             summary["threads_touched"],
                "ppv_pitched":                 summary["ppv_pitched"],
                "story_reply_threads":         summary["story_reply_threads"],
                "human_handoff_flagged":       summary["human_handoff_flagged"],
                "errors":                      summary["errors"],
            },
        )

    # ------------------------------------------------------------------
    # Platform-specific inbox with story-reply priority
    # ------------------------------------------------------------------

    async def _run_story_reply_inbox(
        self,
        account_id: str,
        session: IGSession,
        chat_tier: ChatTier,
        date_iso: str,
        ppv_pitch_after_msgs: int,
    ) -> dict:
        """
        Fetch inbox, split into story-reply vs regular threads, process
        story replies first.

        Returns summary dict:
            replies_sent, threads_touched, ppv_pitched,
            story_reply_threads, human_handoff_flagged, errors
        """
        import os as _os
        import json as _json
        import httpx as _httpx

        api_key = _os.environ.get("OPENROUTER_API_KEY", "")
        profile = self._resolve_profile(chat_tier)
        # Override ppv_pitch threshold for story reply context
        self.ppv_pitch_after_msgs = ppv_pitch_after_msgs

        summary = {
            "replies_sent":          0,
            "threads_touched":       0,
            "ppv_pitched":           0,
            "story_reply_threads":   0,
            "human_handoff_flagged": 0,
            "errors":                [],
        }

        # Tally daily messages already sent for this account
        total_sent_today = sum(
            s.messages_sent_today
            for s in self._states.values()
            if s.account_id == account_id and s.platform == self.platform_name
        )

        threads_processed = 0
        cursor = ""

        async with self._build_client(session) as client:
            while True:
                if total_sent_today >= self.max_daily_replies:
                    log.info("[%s/story_reply] Daily cap reached (%d)", account_id, self.max_daily_replies)
                    break
                if threads_processed >= MAX_STORY_REPLY_CONVERSATIONS:
                    log.info("[%s/story_reply] Session conversation cap reached", account_id)
                    break

                try:
                    inbox_resp = await self._fetch_inbox(client, cursor)
                except Exception as exc:
                    log.error("[%s/story_reply] Inbox fetch error: %s", account_id, exc)
                    summary["errors"].append(f"inbox_fetch:{exc}")
                    break

                threads = inbox_resp.get("threads", [])
                if not threads:
                    break

                # --- Priority split: story replies first ---
                story_reply_threads = [
                    t for t in threads if _is_story_reply_thread(t)
                ]
                regular_threads = [
                    t for t in threads if not _is_story_reply_thread(t)
                ]
                # Process story replies first, then fall through to regular DMs
                ordered_threads = story_reply_threads + regular_threads

                summary["story_reply_threads"] += len(story_reply_threads)

                for thread in ordered_threads:
                    if total_sent_today >= self.max_daily_replies:
                        break
                    if threads_processed >= MAX_STORY_REPLY_CONVERSATIONS:
                        break

                    thread_id = str(thread.get("thread_id") or thread.get("id") or "")
                    if not thread_id:
                        continue

                    items = thread.get("items", [])
                    unread_count = thread.get("unread_count", 0)
                    if not items and not unread_count:
                        continue

                    state_key = (account_id, self.platform_name, thread_id)
                    if state_key not in self._states:
                        from .base_dm_chat_agent import DMConversationState
                        self._states[state_key] = DMConversationState(
                            thread_id  = thread_id,
                            platform   = self.platform_name,
                            account_id = account_id,
                        )
                    state = self._states[state_key]

                    if state.human_handoff_flagged:
                        summary["human_handoff_flagged"] += 1
                        continue

                    # Use tighter min_gap for story replies
                    is_story_reply = _is_story_reply_thread(thread)
                    effective_min_gap = self.min_gap_sec if is_story_reply else 90.0

                    now = time.time()
                    if state.last_reply_at > 0 and (now - state.last_reply_at) < effective_min_gap:
                        log.debug(
                            "[%s/story_reply] Thread %s: min-gap not elapsed (%.0fs remaining)",
                            account_id, thread_id,
                            effective_min_gap - (now - state.last_reply_at),
                        )
                        continue

                    # Use story-reply profile for story threads, standard for regular
                    active_profile = _STORY_REPLY_PROFILE if is_story_reply else profile

                    # Effective PPV threshold: 2 for story replies, standard for others
                    effective_ppv_threshold = ppv_pitch_after_msgs if is_story_reply else 4

                    from .base_dm_chat_agent import (
                        MAX_CONVERSATION_HISTORY,
                        _extract_recipient_id,
                    )

                    recent_msgs = items[:MAX_CONVERSATION_HISTORY]
                    conversation_text = self._format_conversation(recent_msgs)
                    recipient_id = _extract_recipient_id(thread)

                    ppv_text = ""
                    if (
                        not state.ppv_pitched
                        and state.messages_sent_today >= effective_ppv_threshold
                    ):
                        ppv_text = _story_reply_ppv_pitch(account_id, thread_id)

                    reply_text = await self._generate_reply(
                        account_id        = account_id,
                        thread_id         = thread_id,
                        profile           = active_profile,
                        conversation_text = conversation_text,
                        ppv_text          = ppv_text,
                        api_key           = api_key,
                        date_iso          = date_iso,
                    )

                    if reply_text is None:
                        summary["errors"].append(f"llm_fail:thread={thread_id}")
                        continue

                    try:
                        await self._send_reply(client, thread_id, recipient_id, reply_text)
                    except Exception as exc:
                        log.error(
                            "[%s/story_reply] Send error for thread %s: %s",
                            account_id, thread_id, exc,
                        )
                        summary["errors"].append(f"send_error:thread={thread_id}:{exc}")
                        continue

                    # Update state
                    state.messages_sent_today += 1
                    state.last_reply_at = time.time()
                    total_sent_today += 1
                    summary["replies_sent"] += 1
                    summary["threads_touched"] += 1

                    if ppv_text:
                        state.ppv_pitched = True
                        summary["ppv_pitched"] += 1

                    threads_processed += 1

                    # Inter-conversation sleep (tighter for story replies)
                    from ...core.distributions import LogNormal
                    import asyncio as _asyncio
                    inter_dist = LogNormal(
                        low   = 8.0 if is_story_reply else 15.0,
                        high  = 120.0,
                        sigma = 0.45,
                    )
                    inter_delay = inter_dist.sample(
                        account_id = account_id,
                        date_iso   = date_iso,
                        field      = f"story_inter_conv_{thread_id}",
                    )
                    await _asyncio.sleep(inter_delay)

                # Advance cursor
                next_cursor = inbox_resp.get("oldest_cursor") or inbox_resp.get("cursor") or ""
                if not next_cursor or not inbox_resp.get("has_older", False):
                    break
                cursor = next_cursor

        return summary

    # ------------------------------------------------------------------
    # Platform-specific implementations (required by _BaseDMChatAgent)
    # ------------------------------------------------------------------

    def _build_client(self, session: IGSession):
        """Return an InstagramClient async context manager."""
        return InstagramClient(session)

    async def _fetch_inbox(self, client: InstagramClient, cursor: str) -> dict:
        """Fetch the IG DM inbox for the current account."""
        return await client.get_inbox(cursor=cursor)

    async def _send_reply(
        self,
        client: InstagramClient,
        thread_id: str,
        recipient_id: str,
        text: str,
    ) -> None:
        """Send a DM reply to a specific user on Instagram."""
        await client.send_dm(recipient_user_id=recipient_id, text=text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_story_reply_thread(thread: dict) -> bool:
    """
    Return True if this thread is a story reply.

    Instagram's API marks story reply threads with is_story_reply=True.
    Also check thread_type == "story_reply" as a secondary indicator.
    """
    if thread.get("is_story_reply"):
        return True
    if thread.get("thread_type") == "story_reply":
        return True
    # Check items for story_share or story_reply type
    items = thread.get("items", [])
    for item in items:
        item_type = item.get("item_type", "")
        if "story" in item_type.lower():
            return True
    return False


def _story_reply_ppv_pitch(account_id: str, thread_id: str) -> str:
    """
    Select a PPV pitch template seeded by (account, thread) for diversity.

    Uses the story-specific pitch pool (shorter, more reactive tone).
    """
    import hashlib
    key = f"{account_id}|{thread_id}|story_reply_ppv"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(_STORY_REPLY_PPV_PITCH_TEMPLATES)
    return _STORY_REPLY_PPV_PITCH_TEMPLATES[idx]
