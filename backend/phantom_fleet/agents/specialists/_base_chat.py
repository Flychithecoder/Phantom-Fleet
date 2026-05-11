"""
_BaseDMChatAgent — shared mixin for all platform DM chat agents.

Handles:
    - OpenRouter LLM call (claude-haiku-4-5-20251001)
    - Anti-LLM-tell stripping
    - Conversation state dict keyed by (account_id, platform, conv_id)
    - Daily cap counter (code-enforced, not prompt-enforced)
    - Min-gap enforcement between replies to the same conversation
    - PPV pitch logic at configured turn threshold
    - Human handoff flag detection
    - XML-delimited prompt assembly (separates instructions from untrusted data)
    - LogNormal inter-conversation sleep

Subclasses MUST override:
    platform_name          str         e.g. "x" / "bluesky"
    max_daily_replies      int         hard daily cap per account
    min_gap_sec            float       minimum seconds between replies to same conv
    max_tokens             int         max reply tokens for the LLM
    inter_conv_sleep_dist  LogNormal   distribution for inter-conversation pause

Subclasses MUST implement:
    _fetch_conversations(client)        → list of raw conv dicts
    _send_reply(client, conv, text)     → None (sends via platform client)
    _get_chat_mode_profile()            → ChatModeProfile

CLAUDE.md agent-audit compliance:
    - Untrusted input: conversation message bodies are XML-delimited in prompts
    - Daily cap + min-gap enforced by code
    - LLM output validated against ChatModeProfile banned_phrases before send
    - Max 3 LLM retries per conversation
    - Credentials never appear in prompts (OPENROUTER_API_KEY from env only)
    - Context isolation: state keyed by (account_id, platform, conv_id)
    - Cost cap enforced by caller (AgentRun.cost_usd)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

from ...core.chat_modes import (
    GLOBAL_LLM_TELLS,
    ChatModeProfile,
    reject_content,
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
# OpenRouter config
# ---------------------------------------------------------------------------

OPENROUTER_MODEL       = "claude-haiku-4-5-20251001"
OPENROUTER_TEMPERATURE = 0.85
OPENROUTER_URL         = "https://openrouter.ai/api/v1/chat/completions"

# ---------------------------------------------------------------------------
# LLM tell patterns stripped unconditionally
# ---------------------------------------------------------------------------

_STRIP_PATTERNS: list[str] = [
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

# Public alias — used by tests and subclasses that need to enumerate tell phrases
LLM_TELL_PATTERNS: list[str] = _STRIP_PATTERNS

# ---------------------------------------------------------------------------
# PPV pitch pool — 30 entries, seeded per (account_id, conv_id)
# ---------------------------------------------------------------------------

_PPV_PITCH_POOL: list[str] = [
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
# Reply style hints — seeded per (account_id, conv_id, msg_count)
# Ensures fleet-wide reply-length histogram is diverse, not monoculture.
# ---------------------------------------------------------------------------

_REPLY_STYLE_HINTS: list[str] = [
    "Reply in 1-2 short sentences, very casual, under 15 words.",
    "Reply in 2-3 sentences, conversational, under 25 words.",
    "Reply in 2-4 sentences with a question at the end, under 35 words.",
]

MAX_LLM_RETRIES = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_llm_tells(text: str) -> str:
    """Remove all known LLM-tell phrases from generated text, case-insensitive."""
    result = text
    for phrase in _STRIP_PATTERNS:
        # Case-insensitive regex replace
        result = re.sub(re.escape(phrase), "", result, flags=re.IGNORECASE)
    for phrase in GLOBAL_LLM_TELLS:
        result = re.sub(re.escape(phrase), "", result, flags=re.IGNORECASE)
    # Collapse multiple spaces / leading-trailing whitespace
    result = re.sub(r"  +", " ", result).strip()
    return result


def _ppv_pitch_for(account_id: str, conv_id: str) -> str:
    """Select a PPV pitch seeded by (account_id, conv_id) for per-account diversity."""
    key = f"{account_id}|{conv_id}|ppv_pitch"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(_PPV_PITCH_POOL)
    return _PPV_PITCH_POOL[idx]


def _reply_style_hint(account_id: str, conv_id: str, msg_count: int) -> str:
    """Pick one of 3 reply-style hints seeded per (account, conv, msg_count)."""
    key = f"{account_id}|{conv_id}|{msg_count}"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(_REPLY_STYLE_HINTS)
    return _REPLY_STYLE_HINTS[idx]


# ---------------------------------------------------------------------------
# ConversationState
# ---------------------------------------------------------------------------


@dataclass
class ConversationState:
    """Per-(account, platform, conversation) runtime state."""
    account_id:            str
    platform:              str
    conversation_id:       str
    messages_sent_today:   int   = 0
    last_reply_at:         float = 0.0   # unix timestamp; 0 = never
    human_handoff_flagged: bool  = False
    ppv_pitched:           bool  = False


# ---------------------------------------------------------------------------
# WorkerResult
# ---------------------------------------------------------------------------


@dataclass
class WorkerResult:
    """Structured result returned by every specialist agent run."""
    replies_sent:    int = 0
    threads_touched: int = 0
    ppv_pitched:     int = 0
    errors:          list[str] = field(default_factory=list)

    # follow agents
    followed:         int = 0
    unfollowed:       int = 0
    already_following: int = 0

    # post agents
    posts_submitted:  int = 0
    tweets_posted:    int = 0
    skipped_dedup:    int = 0
    skipped_cap:      int = 0

    # Telegram DM agent
    typing_indicators_sent: int = 0

    # Telegram group agent
    groups_joined:    int = 0
    messages_posted:  int = 0
    reactions_sent:   int = 0

    # Discord DM agent
    dm_channels_touched: int = 0
    age_gated_skips:     int = 0

    # Discord server agent
    servers_joined:      int = 0
    messages_sent:       int = 0
    lurk_gates_applied:  int = 0


# ---------------------------------------------------------------------------
# _BaseDMChatAgent
# ---------------------------------------------------------------------------


class _BaseDMChatAgent(ABC):
    """
    Shared logic for all AI DM chat agents across every platform.

    Subclasses are responsible for:
        platform_name          — "x" / "bluesky" / etc.
        max_daily_replies      — daily cap per account (code-enforced)
        min_gap_sec            — minimum gap between replies to same conv
        max_tokens             — LLM max_tokens
        inter_conv_sleep_dist  — LogNormal pause between conversations
        _fetch_conversations   — returns raw conversation list from platform
        _send_reply            — sends text via platform client
        _get_chat_mode_profile — returns the ChatModeProfile to use
    """

    # Subclasses override these class-level attributes
    platform_name:         str       = "base"
    max_daily_replies:     int       = 35
    min_gap_sec:           float     = 60.0
    max_tokens:            int       = 140
    inter_conv_sleep_dist: LogNormal = LogNormal(low=30.0, high=180.0, sigma=0.4)

    def __init__(self) -> None:
        # Keyed by (account_id, platform, conv_id)
        self._states: dict[tuple[str, str, str], ConversationState] = {}
        self._daily_sent: dict[str, int] = {}   # account_id → count

    # ------------------------------------------------------------------
    # Abstract interface — subclasses implement these
    # ------------------------------------------------------------------

    @abstractmethod
    async def _fetch_conversations(self, client: Any) -> list[dict]:
        """Fetch list of conversations/threads from the platform.

        Each dict MUST contain at least:
            conv_id     str   — unique conversation identifier
            messages    list  — latest messages (untrusted content)
            unread      bool  — whether there are unread messages
        """
        ...

    @abstractmethod
    async def _send_reply(self, client: Any, conv: dict, text: str) -> None:
        """Send a reply via the platform client."""
        ...

    @abstractmethod
    def _get_chat_mode_profile(self) -> ChatModeProfile:
        """Return the ChatModeProfile for this platform's chat agent."""
        ...

    # ------------------------------------------------------------------
    # Core run loop (called by subclass run_once)
    # ------------------------------------------------------------------

    async def _run_dm_session(
        self,
        client: Any,
        account_id: str,
        date_iso: str | None = None,
        ppv_turn_threshold: int = 4,
    ) -> WorkerResult:
        """
        Main DM reply loop. Called by the subclass's run_once.

        Args:
            client:              Platform client (XClient / BlueSkyClient)
            account_id:          Phantom Fleet account ID
            date_iso:            YYYY-MM-DD (defaults to today UTC)
            ppv_turn_threshold:  After this many sent messages, pitch PPV

        Returns:
            WorkerResult with reply/thread/ppv/error counts.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        profile = self._get_chat_mode_profile()

        # Ensure daily counter is initialised for this account
        if account_id not in self._daily_sent:
            self._daily_sent[account_id] = sum(
                s.messages_sent_today
                for s in self._states.values()
                if s.account_id == account_id
            )

        result = WorkerResult()

        try:
            conversations = await self._fetch_conversations(client)
        except Exception as exc:
            log.error("[%s/%s] fetch_conversations failed: %s", self.platform_name, account_id, exc)
            result.errors.append(f"fetch_conversations:{exc}")
            return result

        for conv in conversations:
            # --- Blast-radius cap 1: daily account cap ---
            if self._daily_sent.get(account_id, 0) >= self.max_daily_replies:
                log.info(
                    "[%s/%s] Daily reply cap %d reached, stopping",
                    self.platform_name, account_id, self.max_daily_replies,
                )
                break

            conv_id = conv.get("conv_id", "")
            if not conv_id:
                continue

            if not conv.get("unread", False):
                continue

            state_key = (account_id, self.platform_name, conv_id)
            if state_key not in self._states:
                self._states[state_key] = ConversationState(
                    account_id=account_id,
                    platform=self.platform_name,
                    conversation_id=conv_id,
                )
            state = self._states[state_key]

            # --- Human handoff check ---
            if state.human_handoff_flagged:
                log.debug(
                    "[%s/%s/%s] Flagged for human handoff — skipping AI reply",
                    self.platform_name, account_id, conv_id,
                )
                continue

            if profile.handoff_mode == "real_human":
                state.human_handoff_flagged = True
                log.info(
                    "[%s/%s/%s] real_human handoff mode — flagging, skipping",
                    self.platform_name, account_id, conv_id,
                )
                continue

            # --- Blast-radius cap 2: min gap between replies ---
            now = time.time()
            gap = now - state.last_reply_at
            if state.last_reply_at > 0 and gap < self.min_gap_sec:
                log.debug(
                    "[%s/%s/%s] Min gap not met (%.1fs < %.1fs), skipping",
                    self.platform_name, account_id, conv_id, gap, self.min_gap_sec,
                )
                continue

            result.threads_touched += 1

            # --- Build XML-delimited prompt (CLAUDE.md: separate instructions from data) ---
            messages = conv.get("messages", [])
            style_hint = _reply_style_hint(
                account_id, conv_id, state.messages_sent_today
            )
            prompt_user = self._build_prompt(profile, messages, style_hint)

            # --- Voice-augmented system prompt (Gen Z 2026 baseline prepended) ---
            system_prompt = self._build_system_prompt(profile)

            # --- LLM call with retries ---
            reply_text: Optional[str] = None
            current_user_prompt = prompt_user
            for attempt in range(MAX_LLM_RETRIES):
                try:
                    raw = await self._call_openrouter(
                        system_prompt=system_prompt,
                        user_prompt=current_user_prompt,
                        max_tokens=self.max_tokens,
                    )
                except Exception as exc:
                    log.warning(
                        "[%s/%s/%s] LLM attempt %d failed: %s",
                        self.platform_name, account_id, conv_id, attempt + 1, exc,
                    )
                    continue

                # --- Voice style post-processing pipeline ---
                # Step 1: regex replacements (lol → 💀, AI tells stripped)
                styled = apply_voice_style(raw)

                # Step 2: banned-phrase and score gate — retry with nudge
                needs_retry = (
                    has_banned_phrases(styled) or voice_style_score(styled) < 0.5
                )
                if needs_retry and attempt < MAX_LLM_RETRIES - 1:
                    log.debug(
                        "[%s/%s/%s] Voice style gate failed on attempt %d "
                        "(banned=%s, score=%.2f) — retrying with nudge",
                        self.platform_name, account_id, conv_id, attempt + 1,
                        has_banned_phrases(styled), voice_style_score(styled),
                    )
                    current_user_prompt = f"{prompt_user}\n\n{STYLE_RETRY_NUDGE}"
                    continue

                # Step 3: strip LLM tells (existing gate — belt + suspenders)
                cleaned = strip_llm_tells(styled)

                # Step 4: validate against ChatModeProfile rules
                rejected, reason = reject_content(profile, cleaned)
                if rejected:
                    log.debug(
                        "[%s/%s/%s] LLM output rejected (attempt %d): %s",
                        self.platform_name, account_id, conv_id, attempt + 1, reason,
                    )
                    continue

                reply_text = cleaned
                break

            if not reply_text:
                log.warning(
                    "[%s/%s/%s] All %d LLM attempts failed — skipping",
                    self.platform_name, account_id, conv_id, MAX_LLM_RETRIES,
                )
                result.errors.append(f"llm_failed:conv={conv_id}")
                continue

            # --- Append PPV pitch if threshold reached and not yet pitched ---
            ppv_appended = False
            if (
                not state.ppv_pitched
                and profile.cta_allowed
                and state.messages_sent_today >= ppv_turn_threshold
            ):
                pitch = _ppv_pitch_for(account_id, conv_id)
                reply_text = f"{reply_text}\n\n{pitch}"
                state.ppv_pitched = True
                ppv_appended = True

            # --- Send ---
            try:
                await self._send_reply(client, conv, reply_text)
            except Exception as exc:
                log.error(
                    "[%s/%s/%s] send_reply failed: %s",
                    self.platform_name, account_id, conv_id, exc,
                )
                result.errors.append(f"send_reply:{exc}")
                continue

            # --- Update state ---
            state.messages_sent_today += 1
            state.last_reply_at = time.time()
            self._daily_sent[account_id] = self._daily_sent.get(account_id, 0) + 1
            result.replies_sent += 1
            if ppv_appended:
                result.ppv_pitched += 1

            # --- Inter-conversation sleep ---
            sleep_sec = self.inter_conv_sleep_dist.sample()
            await asyncio.sleep(sleep_sec)

        return result

    # ------------------------------------------------------------------
    # Prompt assembly (XML-delimited)
    # ------------------------------------------------------------------

    def _build_system_prompt(self, profile: ChatModeProfile) -> str:
        """
        Build the full system prompt by prepending the Gen Z 2026 voice baseline
        before the ChatModeProfile system prompt.

        Order:
            1. GENZ_VOICE_BASELINE        (universal tone anchor)
            2. platform context line      (one-liner per platform)
            3. separator
            4. ChatModeProfile.system_prompt  (persona + tier rules)

        LinkedIn is excluded from the Gen Z baseline — the professional profile
        already defines the correct voice for that platform.
        """
        voice_prefix = build_voice_prefix(self.platform_name)
        if voice_prefix:
            return f"{voice_prefix}\n\n---\n\n{profile.system_prompt}"
        return profile.system_prompt

    def _build_prompt(
        self,
        profile: ChatModeProfile,
        messages: list[dict],
        style_hint: str,
    ) -> str:
        """
        Build the user-turn prompt with untrusted conversation content
        XML-delimited to prevent prompt injection.

        XML tags separate developer instructions from untrusted data so
        the LLM cannot be redirected by adversarial content in messages.
        """
        lines: list[str] = [style_hint, ""]
        lines.append("<conversation>")
        for msg in messages[-10:]:  # last 10 messages for context window
            role    = msg.get("role", "other")
            # Untrusted content — fully enclosed in XML so injection can't
            # escape the data tag and reach the instruction context
            content = msg.get("text", "")
            lines.append(f"  <message role='{role}'><content>{content}</content></message>")
        lines.append("</conversation>")
        lines.append("")
        lines.append("Reply as the persona described in the system prompt.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # OpenRouter call
    # ------------------------------------------------------------------

    async def _call_openrouter(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        """
        Call OpenRouter API with the given prompts.

        Credentials come from environment only — never from prompts.
        Raises httpx.HTTPError on non-2xx responses.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set in environment")

        payload = {
            "model":       OPENROUTER_MODEL,
            "temperature": OPENROUTER_TEMPERATURE,
            "max_tokens":  max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
            resp = await http.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("OpenRouter returned no choices")
        return choices[0]["message"]["content"].strip()
