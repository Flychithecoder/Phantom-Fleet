"""
_BaseDMChatAgent — shared mixin for IG and Threads AI-powered DM inbox responders.

Both IGDMChatAgent and ThreadsDMChatAgent inherit from this mixin. The mixin
handles all platform-agnostic logic:

    - LLM call via OpenRouter (claude-haiku-4-5-20251001, temp=0.85)
    - LLM tell stripping (unconditional post-processing before send)
    - Conversation state tracking (messages_sent_today, last_reply_at, ppv_pitched)
    - Daily cap enforcement (max 40 messages/day per account, code-enforced)
    - Minimum-gap enforcement (min 90s between replies to same thread, code-enforced)
    - PPV pitch logic (appended at configured message threshold)
    - Human handoff detection and flagging
    - XML-delimited conversation history to prevent prompt injection

Platform-specific subclasses only override:
    _fetch_inbox()   — return list of thread dicts
    _send_reply()    — send one reply to a thread
    platform_name    — string identifier ("instagram" / "threads")

Security notes (CLAUDE.md agent-audit rules):
    - Untrusted input (conversation messages) is XML-delimited in every prompt
      to prevent injection from fan message bodies.
    - API key loaded from os.environ["OPENROUTER_API_KEY"] — never embedded in code.
    - Per-account state is keyed by (account_id, platform, thread_id) so no
      cross-account context leakage.
    - Daily cap and min-gap are code-checked BEFORE the LLM call, so a prompt
      that says "send 1000 messages today" cannot override them.
    - Max 3 LLM retries with hard stop — no unbounded retry loop.
    - Max 20 conversations per session with hard stop — no unbounded inbox scan.

Cost discipline:
    - Model: claude-haiku-4-5-20251001 (cheapest Haiku tier)
    - max_tokens: 120 per call — short replies keep costs tiny
    - At 40 replies/day/account × $0.00025/call ≈ $0.01/account/day
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import httpx

from ...core.chat_modes import (
    CHAT_MODE_CATALOG,
    GLOBAL_LLM_TELLS,
    ChatModeProfile,
    ChatTier,
    INSTAGRAM_FLIRTY,
    THREADS_CASUAL,
    reject_content,
    validate_mode_for_platform,
)
from ...core.distributions import LogNormal
from ...core.voice_style import (
    apply_voice_style,
    build_voice_prefix,
    has_banned_phrases,
    voice_style_score,
    STYLE_RETRY_NUDGE,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (ALL code-enforced, not prompt-enforced)
# ---------------------------------------------------------------------------

MAX_MESSAGES_PER_ACCOUNT_PER_DAY: int = 40
MAX_CONVERSATIONS_PER_SESSION: int = 20
MIN_SECONDS_BETWEEN_REPLIES_SAME_THREAD: float = 90.0
MAX_LLM_RETRIES: int = 3
MAX_CONVERSATION_HISTORY: int = 10

# ---------------------------------------------------------------------------
# LLM config
# ---------------------------------------------------------------------------

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "claude-haiku-4-5-20251001"
OPENROUTER_TEMPERATURE = 0.85
OPENROUTER_MAX_TOKENS = 120

# ---------------------------------------------------------------------------
# LLM tell phrases — stripped from all generated text before send
# ---------------------------------------------------------------------------

LLM_TELL_PATTERNS: list[str] = [
    "Certainly!",
    "Of course!",
    "I'd be happy to",
    "I would be happy to",
    "Delve into",
    "It's worth noting",
    "It is worth noting",
    "In conclusion",
    "As an AI",
    "As an AI language model",
    "I'm just an AI",
    "I am just an AI",
]

# ---------------------------------------------------------------------------
# PPV pitch templates — seeded selection prevents monoculture
# Pool of 30 so hash spread gives ≤1/30 collision risk per (account, thread)
# ---------------------------------------------------------------------------

PPV_PITCH_TEMPLATES: list[str] = [
    "btw i have a private page with a lot more content 👀",
    "if you want to see more of me i've got a vip thing going on 😏",
    "i share a lot more privately, let me know if you're interested",
    "i've got some exclusive stuff if you're curious 😉",
    "not gonna post everything here 😭, got a private side too",
    "you should check out my exclusive page honestly",
    "i keep the good stuff on my private, just saying 😏",
    "theres more where that came from on my vip page 👀",
    "i'm way more open in my private space if you wanna see",
    "got a whole private world, this is just the surface 👀",
    "honestly my vip followers get way better content",
    "if you like this you'd love what's on my exclusive page",
    "the real me is on my private page, not gonna lie",
    "i save the best stuff for my loyal ones 😉",
    "my private page is where i actually express myself",
    "let me know if you want the link to my exclusive content",
    "i don't post everything publicly, got a little secret page 🙈",
    "i'm pretty different in private just so you know 😏",
    "if you're into this vibe check my exclusive content out",
    "my private content is a whole different energy",
    "i share way more behind the scenes if you're interested",
    "got a vip thing for people i actually like talking to",
    "you seem like you'd appreciate my exclusive content 👀",
    "the public stuff is just the preview honestly",
    "my close friends list is where i keep the real content",
    "i've got a private space where i share way more",
    "people are always surprised when they see my private page",
    "if you want the unfiltered version there's a spot for that 😏",
    "i like you, let me send you my exclusive page link",
    "keep it between us but i have a private content page",
]

# ---------------------------------------------------------------------------
# Reply-timing distribution
# ---------------------------------------------------------------------------

# LogNormal(mean=ln(60), σ=0.45) → median ~60s between conversations
_REPLY_TIMING_DIST = LogNormal(low=10.0, high=300.0, sigma=0.45)


# ---------------------------------------------------------------------------
# Conversation state
# ---------------------------------------------------------------------------


@dataclass
class DMConversationState:
    """Per-(account, platform, thread) runtime state for one conversation."""
    thread_id:           str
    platform:            str
    account_id:          str
    messages_sent_today: int   = 0
    last_reply_at:       float = 0.0   # unix timestamp; 0 = never replied
    ppv_pitched:         bool  = False
    human_handoff_flagged: bool = False


# ---------------------------------------------------------------------------
# DM reply record
# ---------------------------------------------------------------------------


@dataclass
class DMReplyRecord:
    """Audit record for one DM reply sent."""
    account_id:  str
    platform:    str
    thread_id:   str
    reply_text:  str
    ppv_pitched: bool
    ts:          str
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Base mixin
# ---------------------------------------------------------------------------


class _BaseDMChatAgent:
    """
    Shared DM chat mixin for IG and Threads inbox responders.

    Concrete subclasses must implement:
        platform_name: str
        async _fetch_inbox(client, cursor) -> list[dict]
        async _send_reply(client, thread_id, recipient_id, text) -> None
        async _build_client(session) -> async context manager

    and set:
        _default_profile: ChatModeProfile
    """

    platform_name: str = "unknown"
    _default_profile: ChatModeProfile = INSTAGRAM_FLIRTY
    ppv_pitch_after_msgs: int = 4

    def __init__(self) -> None:
        # Keyed by (account_id, platform, thread_id)
        self._states: dict[tuple[str, str, str], DMConversationState] = {}

    # ------------------------------------------------------------------
    # Public entry point (called by platform-specific subclass)
    # ------------------------------------------------------------------

    async def _run_inbox(
        self,
        account_id: str,
        session,
        chat_tier: ChatTier,
        date_iso: Optional[str] = None,
        ppv_pitch_after_msgs: Optional[int] = None,
    ) -> dict:
        """
        Process the DM inbox for one account.

        Returns a summary dict with:
            replies_sent, threads_touched, ppv_pitched,
            human_handoff_flagged, errors
        """
        if date_iso is None:
            date_iso = date.today().isoformat()
        if ppv_pitch_after_msgs is not None:
            self.ppv_pitch_after_msgs = ppv_pitch_after_msgs

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            log.error("[%s/%s] OPENROUTER_API_KEY not set", account_id, self.platform_name)

        # Resolve profile for this platform + tier
        profile = self._resolve_profile(chat_tier)

        # Tally sent today across all threads for this account
        total_sent_today = sum(
            s.messages_sent_today
            for s in self._states.values()
            if s.account_id == account_id and s.platform == self.platform_name
        )

        summary = {
            "replies_sent": 0,
            "threads_touched": 0,
            "ppv_pitched": 0,
            "human_handoff_flagged": 0,
            "errors": [],
        }

        threads_processed = 0
        cursor = ""

        async with self._build_client(session) as client:
            while True:
                if total_sent_today >= MAX_MESSAGES_PER_ACCOUNT_PER_DAY:
                    log.info("[%s/%s] Daily cap reached", account_id, self.platform_name)
                    break
                if threads_processed >= MAX_CONVERSATIONS_PER_SESSION:
                    log.info("[%s/%s] Conversation cap reached", account_id, self.platform_name)
                    break

                try:
                    inbox_resp = await self._fetch_inbox(client, cursor)
                except Exception as exc:
                    log.error("[%s/%s] Inbox fetch error: %s", account_id, self.platform_name, exc)
                    summary["errors"].append(f"inbox_fetch:{exc}")
                    break

                threads = inbox_resp.get("threads", [])
                if not threads:
                    break

                for thread in threads:
                    if total_sent_today >= MAX_MESSAGES_PER_ACCOUNT_PER_DAY:
                        break
                    if threads_processed >= MAX_CONVERSATIONS_PER_SESSION:
                        break

                    thread_id = str(
                        thread.get("thread_id") or thread.get("id") or ""
                    )
                    if not thread_id:
                        continue

                    unread_count = thread.get("unread_count", 0)
                    items = thread.get("items", [])
                    if not items and not unread_count:
                        continue

                    # Get or create conversation state
                    state_key = (account_id, self.platform_name, thread_id)
                    if state_key not in self._states:
                        self._states[state_key] = DMConversationState(
                            thread_id=thread_id,
                            platform=self.platform_name,
                            account_id=account_id,
                        )
                    state = self._states[state_key]

                    # Human handoff flag — skip AI entirely for this thread
                    if state.human_handoff_flagged:
                        summary["human_handoff_flagged"] += 1
                        continue

                    # Check handoff mode from profile
                    if profile.handoff_mode == "real_human":
                        state.human_handoff_flagged = True
                        summary["human_handoff_flagged"] += 1
                        log.info(
                            "[%s/%s] Thread %s flagged for human handoff (profile.handoff_mode=real_human)",
                            account_id, self.platform_name, thread_id,
                        )
                        continue

                    # Minimum 90s gate between replies to same thread
                    now = time.time()
                    if state.last_reply_at > 0 and (now - state.last_reply_at) < MIN_SECONDS_BETWEEN_REPLIES_SAME_THREAD:
                        log.debug(
                            "[%s/%s] Thread %s: min-gap not elapsed (%.0fs remaining)",
                            account_id, self.platform_name, thread_id,
                            MIN_SECONDS_BETWEEN_REPLIES_SAME_THREAD - (now - state.last_reply_at),
                        )
                        continue

                    # Build conversation context (last N messages)
                    recent_msgs = items[:MAX_CONVERSATION_HISTORY]
                    conversation_text = self._format_conversation(recent_msgs)

                    # Build LLM prompt with XML-delimited untrusted content
                    recipient_id = _extract_recipient_id(thread)
                    ppv_text = ""
                    if (
                        not state.ppv_pitched
                        and state.messages_sent_today >= self.ppv_pitch_after_msgs
                    ):
                        ppv_text = _ppv_pitch_for(account_id, thread_id)

                    reply_text = await self._generate_reply(
                        account_id=account_id,
                        thread_id=thread_id,
                        profile=profile,
                        conversation_text=conversation_text,
                        ppv_text=ppv_text,
                        api_key=api_key,
                        date_iso=date_iso,
                    )

                    if reply_text is None:
                        summary["errors"].append(f"llm_fail:thread={thread_id}")
                        continue

                    # Audit BEFORE send (CLAUDE.md)
                    audit_ts = datetime.now(timezone.utc).isoformat()
                    log.info(
                        "[%s/%s] Sending reply to thread %s (len=%d, ts=%s)",
                        account_id, self.platform_name, thread_id, len(reply_text), audit_ts,
                    )

                    try:
                        await self._send_reply(client, thread_id, recipient_id, reply_text)
                    except Exception as exc:
                        log.error(
                            "[%s/%s] Send error for thread %s: %s",
                            account_id, self.platform_name, thread_id, exc,
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

                    # Inter-conversation sleep
                    inter_delay = _REPLY_TIMING_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_conv_{thread_id}",
                    )
                    await asyncio.sleep(inter_delay)

                # Advance cursor if available
                next_cursor = inbox_resp.get("oldest_cursor") or inbox_resp.get("cursor") or ""
                if not next_cursor or not inbox_resp.get("has_older", False):
                    break
                cursor = next_cursor

        return summary

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _generate_reply(
        self,
        account_id: str,
        thread_id: str,
        profile: ChatModeProfile,
        conversation_text: str,
        ppv_text: str,
        api_key: str,
        date_iso: str,
    ) -> Optional[str]:
        """
        Call OpenRouter to generate one reply. Returns stripped text or None.

        Conversation history is XML-delimited to prevent prompt injection.
        The profile's system prompt provides platform-specific voice/tone.
        LLM tells are stripped unconditionally before returning.
        """
        ppv_instruction = (
            f"\n\nAfter your reply, also append this exactly: {ppv_text}"
            if ppv_text
            else ""
        )

        # --- Voice style prefix (Gen Z 2026 baseline) ---
        # Prepended to EVERY system prompt BEFORE the ChatModeProfile content.
        # LinkedIn excluded — its professional profile already defines the voice.
        voice_prefix = build_voice_prefix(self.platform_name)
        profile_prompt = profile.system_prompt
        if voice_prefix:
            full_system_prompt = (
                f"{voice_prefix}\n\n"
                f"---\n\n"
                f"{profile_prompt}{ppv_instruction}\n\n"
                f"Keep your reply under {profile.max_reply_words} words."
            )
        else:
            full_system_prompt = (
                f"{profile_prompt}{ppv_instruction}\n\n"
                f"Keep your reply under {profile.max_reply_words} words."
            )

        # XML-delimit untrusted conversation content (CLAUDE.md injection defense)
        user_prompt = (
            f"<conversation>\n{conversation_text}\n</conversation>\n\n"
            f"Reply to the last message from the other person."
        )

        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": full_system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": OPENROUTER_TEMPERATURE,
            "max_tokens":  OPENROUTER_MAX_TOKENS,
        }

        for attempt in range(MAX_LLM_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    resp = await http.post(
                        OPENROUTER_API_URL,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type":  "application/json",
                        },
                        content=json.dumps(payload).encode(),
                    )
                    resp.raise_for_status()
                    data = resp.json()

                raw = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )

                if not raw:
                    log.warning(
                        "[%s/%s] Empty LLM reply on attempt %d",
                        account_id, self.platform_name, attempt + 1,
                    )
                    continue

                # --- Voice style post-processing pipeline ---
                # Step 1: apply regex replacements (lol → 💀, AI tells → removed)
                styled = apply_voice_style(raw)

                # Step 2: check banned phrases on RAW text (apply_voice_style strips
                # them via regex, so checking styled would miss them), then check
                # voice score on the styled text.
                needs_retry = (
                    has_banned_phrases(raw) or voice_style_score(styled) < 0.5
                )
                if needs_retry and attempt < MAX_LLM_RETRIES - 1:
                    # Inject style nudge into next attempt's user prompt
                    log.debug(
                        "[%s/%s] Voice style gate failed on attempt %d "
                        "(banned=%s, score=%.2f) — retrying with nudge",
                        account_id, self.platform_name, attempt + 1,
                        has_banned_phrases(styled), voice_style_score(styled),
                    )
                    payload["messages"][1]["content"] = (
                        f"{user_prompt}\n\n{STYLE_RETRY_NUDGE}"
                    )
                    continue

                # Step 3: strip existing LLM tells (existing gate, belt + suspenders)
                reply = _strip_llm_tells(styled)

                # Step 4: validate against ChatModeProfile rules
                rejected, reason = reject_content(profile, reply)
                if rejected:
                    log.warning(
                        "[%s/%s] Reply rejected (%s) on attempt %d",
                        account_id, self.platform_name, reason, attempt + 1,
                    )
                    continue

                return reply

            except Exception as exc:
                log.error(
                    "[%s/%s] LLM call error (attempt %d): %s",
                    account_id, self.platform_name, attempt + 1, exc,
                )

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_profile(self, chat_tier: ChatTier) -> ChatModeProfile:
        """Return the ChatModeProfile appropriate for this platform and tier."""
        return self._default_profile

    def _format_conversation(self, items: list[dict]) -> str:
        """
        Format a list of IG/Threads message items into a conversation string.
        Speaker labels are normalized to "them:" / "you:" so the LLM understands
        turn-taking without exposing user IDs or platform internals.
        """
        lines = []
        for item in reversed(items):  # oldest first
            text = (
                item.get("text")
                or item.get("like", {}).get("emoji")
                or "[media]"
            )
            # item_type == "text" and user_id matching session identifies our side
            is_self = item.get("is_sent_by_viewer", False)
            speaker = "you" if is_self else "them"
            lines.append(f"{speaker}: {text}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_recipient_id(thread: dict) -> str:
    """Extract the first non-self user ID from a thread dict."""
    users = thread.get("users", [])
    for user in users:
        uid = str(user.get("pk") or user.get("id") or "")
        if uid:
            return uid
    return ""


def _ppv_pitch_for(account_id: str, thread_id: str) -> str:
    """Select a PPV pitch template seeded by (account, thread) for diversity."""
    key = f"{account_id}|{thread_id}|ppv_pitch"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(PPV_PITCH_TEMPLATES)
    return PPV_PITCH_TEMPLATES[idx]


def _strip_llm_tells(text: str) -> str:
    """Remove common LLM tell phrases from generated text (case-insensitive)."""
    for tell in LLM_TELL_PATTERNS:
        # Case-insensitive removal
        lower = text.lower()
        tell_lower = tell.lower()
        pos = lower.find(tell_lower)
        while pos != -1:
            text = text[:pos] + text[pos + len(tell):]
            lower = text.lower()
            pos = lower.find(tell_lower)

    # Also strip from GLOBAL_LLM_TELLS
    for tell in GLOBAL_LLM_TELLS:
        lower = text.lower()
        pos = lower.find(tell.lower())
        while pos != -1:
            text = text[:pos] + text[pos + len(tell):]
            lower = text.lower()
            pos = lower.find(tell.lower())

    return text.strip()
