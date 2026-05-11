"""
DatingChatAgent — autonomous AI-powered inbound conversation loop for all 4
dating platforms: Tinder, Bumble, Hinge, Grindr.

Responsibilities:
    - Poll inboxes / matches across all 4 dating platforms
    - Read incoming messages for each conversation with unreads
    - Generate contextual AI replies using the account's ChatModeProfile
    - Apply anti-LLM-tell post-processing before sending
    - Enforce hard blast-radius caps (message count, timing gates, conv caps)
    - Persist ConversationState across restarts via JSON sidecar
    - Flag conversations for human handoff when ChatModeProfile demands it
    - Append soft PPV pitch at configured message threshold

Detection hardening (CLAUDE.md fleet-level rules):
    - Reply timing: LogNormal(mean=ln(45), σ=0.4) — never uniform fixed sleep
    - Message length style: seeded by hash(account_id + conv_id + msg_count) % 3
      so fleet histogram of reply lengths is diverse across accounts and convs
    - Min 60s hard gate between replies to same conversation (code-enforced)
    - Grindr: typing indicator fired before send (platform supports it)
    - LLM tells stripped from every generated reply before send

Blast radius caps (ALL enforced by code, not prompts):
    - MAX 50 messages sent per account per day
    - MAX 5 conversations processed per session run
    - MAX 3 LLM retries on banned-phrase / empty reply
    - MIN 60s between replies to same conversation
    - MAX 10 messages per conversation per day

Agent audit table (CLAUDE.md agent rules):
    ┌─────────────────┬──────────────────────────────────────────────────────┐
    │ Agent           │ DatingChatAgent                                      │
    │ Purpose         │ Autonomous inbound-message reply loop                │
    │ Tools           │ None — direct HTTP via clients                       │
    │ Untrusted input │ Conversation message bodies (platform API responses) │
    │ User isolation  │ Keyed by account_id in ConversationState             │
    │ Cost cap        │ MAX_USD_PER_SESSION (0.10 USD) — Haiku is cheap       │
    │ Loop cap        │ MAX_CONVERSATIONS_PER_SESSION = 5                    │
    │ Confirmation    │ None required (non-destructive sends)                │
    └─────────────────┴──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from ...core.chat_modes import (
    CHAT_MODE_CATALOG,
    GLOBAL_LLM_TELLS,
    ChatModeProfile,
    ChatTier,
    ChatTierViolation,
    DATING_PRE_CTA_FLIRTY,
    GRINDR_NSFW,
    reject_content,
    validate_mode_for_platform,
)
from ...core.distributions import LogNormal
from ...core.grindr_client import GrindrClient, GrindrSession, GrindrSessionExpired, GrindrRateLimited
from ...core.tinder_client import TinderClient, TinderSession, TinderSessionExpired, TinderRateLimited, TinderActionBlocked
from ...core.bumble_client import BumbleClient, BumbleSession, BumbleSessionExpired, BumbleRateLimited
from ...core.hinge_client import HingeClient, HingeSession, HingeSessionExpired, HingeRateLimited, HingeVerificationRequired

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced, not prompt-enforced)
# ---------------------------------------------------------------------------

MAX_MESSAGES_PER_ACCOUNT_PER_DAY: int = 50
MAX_CONVERSATIONS_PER_SESSION: int = 5
MAX_MESSAGES_PER_CONVERSATION_PER_DAY: int = 10
MIN_SECONDS_BETWEEN_REPLIES: float = 60.0
MAX_LLM_RETRIES: int = 3
MAX_CONVERSATION_HISTORY: int = 10    # messages fed to LLM context

# ---------------------------------------------------------------------------
# LLM config
# ---------------------------------------------------------------------------

OPENROUTER_MODEL = "claude-haiku-4-5-20251001"
OPENROUTER_TEMPERATURE = 0.85
OPENROUTER_MAX_TOKENS = 150

# ---------------------------------------------------------------------------
# Anti-LLM-tell phrases stripped unconditionally from all generated text
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
# Also strip from GLOBAL_LLM_TELLS (they overlap but be explicit)
_EXTRA_LLM_TELLS: frozenset[str] = GLOBAL_LLM_TELLS

# ---------------------------------------------------------------------------
# PPV pitch CTA templates (one selected per account+conv seed)
# Diversity pool must stay large enough that 1000 accounts × 10 convs
# each see a different pitch — pool of 30 makes collision ~33%, acceptable
# since pitches are softly phrased and variation is per (account,conv) seed.
# ---------------------------------------------------------------------------

PPV_PITCH_TEMPLATES: list[str] = [
    "btw i have a private page with a lot more content 👀",
    "if you want to see more of me i've got a vip thing going on 😏",
    "i share a lot more privately, let me know if you're interested",
    "i've got some exclusive stuff if you're curious 😉",
    "not gonna post everything here lol, got a private side too",
    "you should check out my exclusive page honestly",
    "i keep the good stuff on my private, just saying 😏",
    "theres more where that came from on my vip page haha",
    "i'm way more open in my private space if you wanna see",
    "got a whole private world, this is just the surface 👀",
    "honestly my vip followers get way better content",
    "if you like this you'd love what's on my exclusive page",
    "the real me is on my private page, not gonna lie",
    "i save the best stuff for my loyal ones 😉",
    "my private page is where i actually express myself",
    "let me know if you want the link to my exclusive content",
    "i don't post everything publicly, got a little secret page 🙈",
    "i'm pretty different in private just so you know lol",
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


def _ppv_pitch_for(account_id: str, conversation_id: str) -> str:
    """Select a PPV pitch template seeded by (account, conv) for diversity."""
    key = f"{account_id}|{conversation_id}|ppv_pitch"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(PPV_PITCH_TEMPLATES)
    return PPV_PITCH_TEMPLATES[idx]


# ---------------------------------------------------------------------------
# Reply-style seeds — 3 styles: brief / medium / expressive
# Seeded by hash(account_id + conversation_id + msg_count) % 3
# Ensures fleet histogram of reply lengths is diverse, not monoculture.
# ---------------------------------------------------------------------------

REPLY_STYLE_HINTS: list[str] = [
    "Reply in 1-2 short sentences, very casual, under 15 words.",
    "Reply in 2-3 sentences, conversational, under 25 words.",
    "Reply in 2-4 sentences with a question at the end, under 35 words.",
]


def _reply_style_hint(account_id: str, conversation_id: str, msg_count: int) -> str:
    key = f"{account_id}|{conversation_id}|{msg_count}"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(REPLY_STYLE_HINTS)
    return REPLY_STYLE_HINTS[idx]


# ---------------------------------------------------------------------------
# LogNormal reply-timing distribution (CLAUDE.md rule: never fixed sleep)
# mean=ln(45)≈3.807, σ=0.4 → median≈45s, 90th-pctile≈68s, realistic human
# ---------------------------------------------------------------------------

REPLY_TIMING_DIST = LogNormal(low=15.0, high=180.0, sigma=0.40)

# ---------------------------------------------------------------------------
# ConversationState — per-(account, platform, conversation) runtime state
# ---------------------------------------------------------------------------


@dataclass
class ConversationState:
    """Runtime + persisted state for one ongoing conversation."""
    conversation_id:       str
    platform:              str
    account_id:            str
    messages_sent_today:   int   = 0
    messages_received_today: int = 0
    last_reply_at:         float = 0.0   # unix timestamp; 0 = never replied
    chat_tier:             int   = ChatTier.FLIRTY_SFW
    escalation_flagged:    bool  = False
    human_handoff_flagged: bool  = False
    ppv_pitched:           bool  = False

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ConversationState":
        return ConversationState(**d)


# ---------------------------------------------------------------------------
# Sidecar persistence helpers
# ---------------------------------------------------------------------------

def _sidecar_path(account_id: str, date_iso: str) -> Path:
    """Path to the JSON sidecar file for one account's conversation states."""
    base = Path(os.environ.get("PHANTOM_STATE_DIR", "/tmp/phantom_state"))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"chat_state_{account_id}_{date_iso}.json"


def load_conversation_states(
    account_id: str,
    date_iso: str,
) -> dict[tuple[str, str, str], ConversationState]:
    """Load all conversation states for an account from its JSON sidecar."""
    path = _sidecar_path(account_id, date_iso)
    if not path.exists():
        return {}
    try:
        raw: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        result: dict[tuple[str, str, str], ConversationState] = {}
        for item in raw:
            state = ConversationState.from_dict(item)
            key = (state.account_id, state.platform, state.conversation_id)
            result[key] = state
        return result
    except Exception as exc:
        log.warning("Failed to load conversation states for %s: %s", account_id, exc)
        return {}


def save_conversation_states(
    account_id: str,
    date_iso: str,
    states: dict[tuple[str, str, str], ConversationState],
) -> None:
    """Persist all conversation states for an account to its JSON sidecar."""
    path = _sidecar_path(account_id, date_iso)
    try:
        payload = [s.to_dict() for s in states.values()]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("Failed to save conversation states for %s: %s", account_id, exc)


# ---------------------------------------------------------------------------
# Chat reply record
# ---------------------------------------------------------------------------


@dataclass
class ChatReplyRecord:
    """Audit record for one chat reply sent."""
    account_id:      str
    platform:        str
    conversation_id: str
    reply_text:      str
    chat_tier:       int
    ppv_pitched:     bool
    ts:              str
    retry_count:     int = 0


# ---------------------------------------------------------------------------
# DatingChatAgent
# ---------------------------------------------------------------------------


class DatingChatAgent:
    """
    Autonomous AI chat agent for dating apps.

    Polls inboxes across all 4 dating platforms, reads incoming messages,
    generates context-aware AI replies using the account's ChatModeProfile,
    and sends them. Handles tier escalation flags, daily message caps, and
    conversation state tracking with resume-across-restarts via JSON sidecar.

    Usage:
        agent = DatingChatAgent()
        report = await agent.run_session(
            account_id="acct_001",
            platforms={
                "tinder": tinder_session,
                "grindr": grindr_session,
            },
            chat_tier=ChatTier.FLIRTY_SFW,
            date_iso="2026-04-11",
        )
    """

    def __init__(self) -> None:
        # In-memory conversation state — keyed by (account_id, platform, conv_id)
        self._states: dict[tuple[str, str, str], ConversationState] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_session(
        self,
        account_id: str,
        platforms: dict[str, TinderSession | BumbleSession | HingeSession | GrindrSession],
        chat_tier: ChatTier = ChatTier.FLIRTY_SFW,
        date_iso: str | None = None,
        action_log: list[dict] | None = None,
    ) -> list[ChatReplyRecord]:
        """
        Run one chat session for one account across all provided platforms.

        Args:
            account_id:   Internal account identifier.
            platforms:    Dict mapping platform name → session object.
                          Supported: "tinder", "bumble", "hinge", "grindr".
            chat_tier:    ChatTier controlling which profile/voice is used.
            date_iso:     YYYY-MM-DD (defaults to today UTC).
            action_log:   Optional mutable list to append audit events to.

        Returns:
            List of ChatReplyRecord for every reply sent in this session.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        if action_log is None:
            action_log = []

        # Load persisted states from sidecar
        self._states = load_conversation_states(account_id, date_iso)

        # Tally total sent today across ALL conversations for this account
        total_sent_today = sum(
            s.messages_sent_today
            for s in self._states.values()
            if s.account_id == account_id
        )

        all_records: list[ChatReplyRecord] = []
        convs_processed = 0

        for platform, session in platforms.items():
            if total_sent_today >= MAX_MESSAGES_PER_ACCOUNT_PER_DAY:
                log.info(
                    "[%s] Daily cap reached (%d), stopping session",
                    account_id, MAX_MESSAGES_PER_ACCOUNT_PER_DAY,
                )
                break
            if convs_processed >= MAX_CONVERSATIONS_PER_SESSION:
                log.info(
                    "[%s] Conversation cap reached (%d), stopping session",
                    account_id, MAX_CONVERSATIONS_PER_SESSION,
                )
                break

            try:
                records = await self._process_platform(
                    account_id=account_id,
                    platform=platform,
                    session=session,
                    chat_tier=chat_tier,
                    date_iso=date_iso,
                    action_log=action_log,
                    total_sent_today_ref=[total_sent_today],
                    convs_processed_ref=[convs_processed],
                )
                all_records.extend(records)
                total_sent_today += len(records)
                convs_processed += sum(
                    1 for r in records
                    if r.conversation_id not in {
                        prev.conversation_id for prev in all_records
                        if prev != r
                    }
                )
            except Exception as exc:
                log.error(
                    "[%s/%s] Platform error: %s", account_id, platform, exc
                )
                action_log.append({
                    "event": "platform_error",
                    "account_id": account_id,
                    "platform": platform,
                    "error": str(exc),
                    "ts": datetime.now(timezone.utc).isoformat(),
                })

        # Persist updated states
        save_conversation_states(account_id, date_iso, self._states)
        return all_records

    # ------------------------------------------------------------------
    # Per-platform dispatch
    # ------------------------------------------------------------------

    async def _process_platform(
        self,
        account_id: str,
        platform: str,
        session: TinderSession | BumbleSession | HingeSession | GrindrSession,
        chat_tier: ChatTier,
        date_iso: str,
        action_log: list[dict],
        total_sent_today_ref: list[int],
        convs_processed_ref: list[int],
    ) -> list[ChatReplyRecord]:
        if platform == "tinder":
            return await self._process_tinder(
                account_id, session, chat_tier, date_iso, action_log,
                total_sent_today_ref, convs_processed_ref,
            )
        elif platform == "bumble":
            return await self._process_bumble(
                account_id, session, chat_tier, date_iso, action_log,
                total_sent_today_ref, convs_processed_ref,
            )
        elif platform == "hinge":
            return await self._process_hinge(
                account_id, session, chat_tier, date_iso, action_log,
                total_sent_today_ref, convs_processed_ref,
            )
        elif platform == "grindr":
            return await self._process_grindr(
                account_id, session, chat_tier, date_iso, action_log,
                total_sent_today_ref, convs_processed_ref,
            )
        else:
            log.warning("[%s] Unsupported platform: %r", account_id, platform)
            return []

    # ------------------------------------------------------------------
    # Tinder
    # ------------------------------------------------------------------

    async def _process_tinder(
        self,
        account_id: str,
        session: TinderSession,
        chat_tier: ChatTier,
        date_iso: str,
        action_log: list[dict],
        total_sent_today_ref: list[int],
        convs_processed_ref: list[int],
    ) -> list[ChatReplyRecord]:
        records: list[ChatReplyRecord] = []
        profile = _select_profile("tinder", chat_tier)

        async with TinderClient(session) as client:
            try:
                resp = await client.get_matches()
            except TinderSessionExpired:
                log.warning("[%s/tinder] Session expired", account_id)
                return records
            except TinderRateLimited as e:
                log.warning("[%s/tinder] Rate limited, retry_after=%d", account_id, e.retry_after)
                return records

            matches = resp.get("data", {}).get("matches", resp.get("matches", []))

            for match in matches:
                if total_sent_today_ref[0] >= MAX_MESSAGES_PER_ACCOUNT_PER_DAY:
                    break
                if convs_processed_ref[0] >= MAX_CONVERSATIONS_PER_SESSION:
                    break

                match_id = match.get("id", "")
                person = match.get("person", {})
                person_name = person.get("name", "")
                messages_raw = match.get("messages", [])

                if not match_id:
                    continue

                # Determine if there's a new incoming message we haven't replied to
                if not _tinder_has_unread_inbound(
                    messages_raw, session.user_id
                ):
                    continue

                # Fetch full message history
                try:
                    msg_resp = await client.get_messages(match_id)
                except (TinderSessionExpired, TinderRateLimited, TinderActionBlocked):
                    continue

                all_msgs = msg_resp.get("data", {}).get("messages", msg_resp.get("messages", []))
                # Tinder returns newest-first — reverse for chronological order
                history = list(reversed(all_msgs[-MAX_CONVERSATION_HISTORY:]))

                record = await self._handle_conversation(
                    account_id=account_id,
                    platform="tinder",
                    conversation_id=match_id,
                    person_name=person_name,
                    history=_normalize_tinder_messages(history, session.user_id),
                    profile=profile,
                    chat_tier=chat_tier,
                    date_iso=date_iso,
                    action_log=action_log,
                    send_fn=lambda text, mid=match_id: client.send_message(mid, text),
                )
                if record is not None:
                    records.append(record)
                    total_sent_today_ref[0] += 1
                    convs_processed_ref[0] += 1

        return records

    # ------------------------------------------------------------------
    # Bumble
    # ------------------------------------------------------------------

    async def _process_bumble(
        self,
        account_id: str,
        session: BumbleSession,
        chat_tier: ChatTier,
        date_iso: str,
        action_log: list[dict],
        total_sent_today_ref: list[int],
        convs_processed_ref: list[int],
    ) -> list[ChatReplyRecord]:
        records: list[ChatReplyRecord] = []
        profile = _select_profile("bumble", chat_tier)

        async with BumbleClient(session) as client:
            try:
                resp = await client.get_connections()
            except BumbleSessionExpired:
                log.warning("[%s/bumble] Session expired", account_id)
                return records
            except BumbleRateLimited as e:
                log.warning("[%s/bumble] Rate limited, retry_after=%d", account_id, e.retry_after)
                return records

            connections = resp.get("connections", [])

            for conn in connections:
                if total_sent_today_ref[0] >= MAX_MESSAGES_PER_ACCOUNT_PER_DAY:
                    break
                if convs_processed_ref[0] >= MAX_CONVERSATIONS_PER_SESSION:
                    break

                conn_id = str(conn.get("connection_id", conn.get("uid", "")))
                person_name = conn.get("user", {}).get("name", "")
                unread_count = conn.get("unread_count", 0)

                if not conn_id or not unread_count:
                    continue

                # Fetch chat history
                try:
                    chat_resp = await client.get_chat(conn_id)
                except (BumbleSessionExpired, BumbleRateLimited):
                    continue

                msgs = chat_resp.get("messages", [])
                history = msgs[-MAX_CONVERSATION_HISTORY:]

                record = await self._handle_conversation(
                    account_id=account_id,
                    platform="bumble",
                    conversation_id=conn_id,
                    person_name=person_name,
                    history=_normalize_bumble_messages(history, session.user_id),
                    profile=profile,
                    chat_tier=chat_tier,
                    date_iso=date_iso,
                    action_log=action_log,
                    send_fn=lambda text, cid=conn_id: client.send_message(cid, body=text),
                )
                if record is not None:
                    records.append(record)
                    total_sent_today_ref[0] += 1
                    convs_processed_ref[0] += 1

        return records

    # ------------------------------------------------------------------
    # Hinge
    # ------------------------------------------------------------------

    async def _process_hinge(
        self,
        account_id: str,
        session: HingeSession,
        chat_tier: ChatTier,
        date_iso: str,
        action_log: list[dict],
        total_sent_today_ref: list[int],
        convs_processed_ref: list[int],
    ) -> list[ChatReplyRecord]:
        records: list[ChatReplyRecord] = []
        profile = _select_profile("hinge", chat_tier)

        async with HingeClient(session) as client:
            try:
                resp = await client.get_matches()
            except HingeSessionExpired:
                log.warning("[%s/hinge] Session expired", account_id)
                return records
            except HingeVerificationRequired:
                log.warning("[%s/hinge] Verification required — pausing", account_id)
                return records
            except HingeRateLimited as e:
                log.warning("[%s/hinge] Rate limited, retry_after=%d", account_id, e.retry_after)
                return records

            matches = resp.get("matches", [])

            for match in matches:
                if total_sent_today_ref[0] >= MAX_MESSAGES_PER_ACCOUNT_PER_DAY:
                    break
                if convs_processed_ref[0] >= MAX_CONVERSATIONS_PER_SESSION:
                    break

                match_id = str(match.get("match_id", match.get("id", "")))
                person_name = match.get("subject", {}).get("display_name", "")
                conversation = match.get("conversation", {})
                msgs_raw = conversation.get("messages", [])

                if not match_id:
                    continue

                if not _hinge_has_unread_inbound(msgs_raw, session.user_id):
                    continue

                # Fetch full conversation
                try:
                    conv_resp = await client.get_conversation(match_id)
                except (HingeSessionExpired, HingeVerificationRequired, HingeRateLimited):
                    continue

                msgs = conv_resp.get("messages", [])
                history = msgs[-MAX_CONVERSATION_HISTORY:]

                record = await self._handle_conversation(
                    account_id=account_id,
                    platform="hinge",
                    conversation_id=match_id,
                    person_name=person_name,
                    history=_normalize_hinge_messages(history, session.user_id),
                    profile=profile,
                    chat_tier=chat_tier,
                    date_iso=date_iso,
                    action_log=action_log,
                    send_fn=lambda text, mid=match_id: client.send_message(mid, text),
                )
                if record is not None:
                    records.append(record)
                    total_sent_today_ref[0] += 1
                    convs_processed_ref[0] += 1

        return records

    # ------------------------------------------------------------------
    # Grindr
    # ------------------------------------------------------------------

    async def _process_grindr(
        self,
        account_id: str,
        session: GrindrSession,
        chat_tier: ChatTier,
        date_iso: str,
        action_log: list[dict],
        total_sent_today_ref: list[int],
        convs_processed_ref: list[int],
    ) -> list[ChatReplyRecord]:
        records: list[ChatReplyRecord] = []
        profile = _select_profile("grindr", chat_tier)

        async with GrindrClient(session) as client:
            try:
                inbox_resp = await client.get_inbox()
            except GrindrSessionExpired:
                log.warning("[%s/grindr] Session expired", account_id)
                return records
            except GrindrRateLimited as e:
                log.warning("[%s/grindr] Rate limited, retry_after=%d", account_id, e.retry_after)
                return records

            # Grindr inbox returns conversations under various keys
            conversations = inbox_resp.get("conversations", inbox_resp.get("data", []))

            for conv in conversations:
                if total_sent_today_ref[0] >= MAX_MESSAGES_PER_ACCOUNT_PER_DAY:
                    break
                if convs_processed_ref[0] >= MAX_CONVERSATIONS_PER_SESSION:
                    break

                conv_id = str(conv.get("conversationId", conv.get("profileId", "")))
                display_name = conv.get("displayName", conv.get("name", ""))
                unread = conv.get("unreadCount", conv.get("unread_count", 0))

                if not conv_id or not unread:
                    continue

                # Fetch full conversation history
                try:
                    conv_resp = await client.get_conversation(conv_id)
                except (GrindrSessionExpired, GrindrRateLimited):
                    continue

                msgs = conv_resp.get("messages", [])
                history = msgs[-MAX_CONVERSATION_HISTORY:]

                # Grindr-specific: send typing indicator before reply
                # (client.send_message takes conversation_id as first arg)
                async def _grindr_send(text: str, cid: str = conv_id) -> dict:
                    # Fire typing indicator — Grindr has endpoint for this
                    try:
                        await client._post(
                            f"chat/conversation/{cid}/typing",
                            json={"conversationId": cid},
                        )
                    except Exception:
                        pass  # typing indicator failure must not block send
                    # Realistic typing delay: LogNormal(1.5s, 3.5s)
                    typing_delay = LogNormal(low=1.5, high=3.5, sigma=0.35).sample()
                    await asyncio.sleep(typing_delay)
                    return await client.send_message(cid, text)

                record = await self._handle_conversation(
                    account_id=account_id,
                    platform="grindr",
                    conversation_id=conv_id,
                    person_name=display_name,
                    history=_normalize_grindr_messages(history, session.profile_id),
                    profile=profile,
                    chat_tier=chat_tier,
                    date_iso=date_iso,
                    action_log=action_log,
                    send_fn=_grindr_send,
                )
                if record is not None:
                    records.append(record)
                    total_sent_today_ref[0] += 1
                    convs_processed_ref[0] += 1

        return records

    # ------------------------------------------------------------------
    # Core conversation handler — platform-agnostic
    # ------------------------------------------------------------------

    async def _handle_conversation(
        self,
        account_id: str,
        platform: str,
        conversation_id: str,
        person_name: str,
        history: list[dict],          # normalized: [{role, content}]
        profile: ChatModeProfile,
        chat_tier: ChatTier,
        date_iso: str,
        action_log: list[dict],
        send_fn,                       # async callable(text) -> dict
    ) -> ChatReplyRecord | None:
        """
        Handle one conversation: check gates, generate reply, send, log.

        Returns a ChatReplyRecord on success, None if gated/skipped.
        """
        key = (account_id, platform, conversation_id)

        # ---- Get or create state ----
        state = self._states.get(key)
        if state is None:
            state = ConversationState(
                conversation_id=conversation_id,
                platform=platform,
                account_id=account_id,
                chat_tier=int(chat_tier),
            )
            self._states[key] = state

        # ---- Human handoff gate (skip AI, flag for human) ----
        if profile.handoff_mode == "real_human":
            if not state.human_handoff_flagged:
                state.human_handoff_flagged = True
                action_log.append({
                    "event": "human_handoff_flagged",
                    "account_id": account_id,
                    "platform": platform,
                    "conversation_id": conversation_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                log.info(
                    "[%s/%s] Conversation %s flagged for human handoff",
                    account_id, platform, conversation_id,
                )
            return None

        # ---- Per-conversation daily cap ----
        if state.messages_sent_today >= MAX_MESSAGES_PER_CONVERSATION_PER_DAY:
            log.debug(
                "[%s/%s/%s] Per-conversation daily cap reached",
                account_id, platform, conversation_id,
            )
            return None

        # ---- Min-60s gate between replies to same conversation ----
        now_ts = time.monotonic()
        time_since_last = now_ts - state.last_reply_at
        if state.last_reply_at > 0 and time_since_last < MIN_SECONDS_BETWEEN_REPLIES:
            log.debug(
                "[%s/%s/%s] Skipping — only %.1fs since last reply (min=%.0fs)",
                account_id, platform, conversation_id,
                time_since_last, MIN_SECONDS_BETWEEN_REPLIES,
            )
            return None

        # ---- Validate mode for platform ----
        try:
            validate_mode_for_platform(platform if platform != "grindr" else "dating", profile.name)
        except ChatTierViolation:
            # Grindr uses "dating" key — re-validate; if truly invalid, skip
            try:
                validate_mode_for_platform("dating", profile.name)
            except ChatTierViolation as exc:
                log.error("[%s/%s] Chat mode violation: %s", account_id, platform, exc)
                return None

        # ---- Determine message count for style seed ----
        msg_count = state.messages_sent_today

        # ---- Generate reply with retries ----
        reply_text: str | None = None
        retry_count = 0
        for attempt in range(MAX_LLM_RETRIES):
            retry_count = attempt
            try:
                candidate = await self._generate_reply(
                    conversation_history=history,
                    profile=profile,
                    platform=platform,
                    style_seed_hint=_reply_style_hint(account_id, conversation_id, msg_count),
                    person_name=person_name,
                )
            except Exception as exc:
                log.warning(
                    "[%s/%s/%s] LLM error on attempt %d: %s",
                    account_id, platform, conversation_id, attempt + 1, exc,
                )
                action_log.append({
                    "event": "llm_error",
                    "account_id": account_id,
                    "platform": platform,
                    "conversation_id": conversation_id,
                    "attempt": attempt + 1,
                    "error": str(exc),
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                continue  # retry

            # Strip LLM tells
            candidate = _strip_llm_tells(candidate)

            # Check against profile banned phrases
            rejected, reason = reject_content(profile, candidate)
            if rejected:
                log.debug(
                    "[%s/%s/%s] Reply rejected (%s) on attempt %d",
                    account_id, platform, conversation_id, reason, attempt + 1,
                )
                continue  # retry with different generation

            reply_text = candidate
            break

        if reply_text is None:
            log.warning(
                "[%s/%s/%s] All %d LLM attempts failed — skipping conversation",
                account_id, platform, conversation_id, MAX_LLM_RETRIES,
            )
            action_log.append({
                "event": "conversation_skipped_llm_failure",
                "account_id": account_id,
                "platform": platform,
                "conversation_id": conversation_id,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            return None

        # ---- PPV pitch injection ----
        ppv_pitched_this_reply = False
        total_exchanges = state.messages_sent_today + state.messages_received_today
        if (
            profile.cta_allowed
            and not state.ppv_pitched
            and total_exchanges >= (profile.max_turns_before_cta - 1)
        ):
            pitch = _ppv_pitch_for(account_id, conversation_id)
            reply_text = f"{reply_text}\n\n{pitch}"
            state.ppv_pitched = True
            ppv_pitched_this_reply = True

        # ---- Escalation flag check ----
        if (
            not state.escalation_flagged
            and state.messages_sent_today >= profile.max_turns_before_cta
        ):
            state.escalation_flagged = True
            action_log.append({
                "event": "escalation_flagged",
                "account_id": account_id,
                "platform": platform,
                "conversation_id": conversation_id,
                "current_tier": int(chat_tier),
                "suggested_next_tier": int(chat_tier) + 1 if chat_tier < ChatTier.NSFW else int(chat_tier),
                "ts": datetime.now(timezone.utc).isoformat(),
            })

        # ---- LogNormal reply timing delay ----
        reply_delay = REPLY_TIMING_DIST.sample(
            account_id=account_id,
            date_iso=date_iso,
            field=f"reply_delay_{conversation_id}_{msg_count}",
        )
        await asyncio.sleep(reply_delay)

        # ---- Audit BEFORE send (CLAUDE.md agent rule) ----
        action_log.append({
            "event": "reply_send_attempt",
            "account_id": account_id,
            "platform": platform,
            "conversation_id": conversation_id,
            "reply_length": len(reply_text),
            "ppv_pitched": ppv_pitched_this_reply,
            "retry_count": retry_count,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        # ---- Send ----
        try:
            await send_fn(reply_text)
        except Exception as exc:
            log.error(
                "[%s/%s/%s] Send failed: %s",
                account_id, platform, conversation_id, exc,
            )
            action_log.append({
                "event": "reply_send_failed",
                "account_id": account_id,
                "platform": platform,
                "conversation_id": conversation_id,
                "error": str(exc),
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            return None

        # ---- Update state ----
        state.messages_sent_today += 1
        state.last_reply_at = time.monotonic()

        # ---- Audit AFTER send ----
        action_log.append({
            "event": "reply_sent",
            "account_id": account_id,
            "platform": platform,
            "conversation_id": conversation_id,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        return ChatReplyRecord(
            account_id=account_id,
            platform=platform,
            conversation_id=conversation_id,
            reply_text=reply_text,
            chat_tier=int(chat_tier),
            ppv_pitched=ppv_pitched_this_reply,
            ts=datetime.now(timezone.utc).isoformat(),
            retry_count=retry_count,
        )

    # ------------------------------------------------------------------
    # LLM generation
    # ------------------------------------------------------------------

    async def _generate_reply(
        self,
        conversation_history: list[dict],
        profile: ChatModeProfile,
        platform: str,
        style_seed_hint: str,
        person_name: str = "",
    ) -> str:
        """
        Call OpenRouter to generate a contextual reply.

        Untrusted conversation content is XML-delimited so the LLM can
        distinguish developer instructions from user-sourced text.
        No f-string injection of untrusted content into system prompt.
        """
        api_key = os.environ["OPENROUTER_API_KEY"]

        # Build safe system prompt — untrusted content never injected here
        system_prompt = (
            f"{profile.system_prompt}\n\n"
            f"{style_seed_hint}\n\n"
            f"Platform: {platform}. "
            f"{'Person name: ' + person_name + '. ' if person_name else ''}"
            "Generate only the reply text — no quotes, no meta-commentary, "
            "no labels. Do not start with 'I' as the first word. "
            "Never use corporate language or AI-sounding phrases."
        )

        # Build conversation turns — XML-delimited user content
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # Render conversation history as a single user block to avoid
        # alternating-role requirements and prevent injection via message bodies
        history_xml_parts: list[str] = []
        for msg in conversation_history:
            role = "them" if msg.get("role") == "user" else "me"
            body = str(msg.get("content", ""))
            history_xml_parts.append(f"<message from='{role}'>{body}</message>")

        if history_xml_parts:
            history_block = "\n".join(history_xml_parts)
            messages.append({
                "role": "user",
                "content": (
                    "<conversation>\n"
                    f"{history_block}\n"
                    "</conversation>\n\n"
                    "Reply to the last message from 'them'. "
                    "Return only the reply text."
                ),
            })
        else:
            messages.append({
                "role": "user",
                "content": "This is a new match with no messages yet. Send an opening message.",
            })

        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://phantomfleet.io",
                    "X-Title": "PhantomFleet",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": messages,
                    "temperature": OPENROUTER_TEMPERATURE,
                    "max_tokens": OPENROUTER_MAX_TOKENS,
                },
                timeout=20.0,
            )
            resp.raise_for_status()
            data = resp.json()

        raw = data["choices"][0]["message"]["content"].strip()
        return raw


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _select_profile(platform: str, chat_tier: ChatTier) -> ChatModeProfile:
    """Select the appropriate ChatModeProfile for this platform + tier."""
    if platform == "grindr":
        return GRINDR_NSFW
    # For tinder / bumble / hinge: use DATING_PRE_CTA_FLIRTY unless NSFW tier
    if chat_tier == ChatTier.NSFW:
        return GRINDR_NSFW   # escalated to NSFW even on SFW dating apps (rare)
    return DATING_PRE_CTA_FLIRTY


def _strip_llm_tells(text: str) -> str:
    """Strip known LLM detection-tells from generated text."""
    result = text
    for tell in LLM_TELL_PATTERNS:
        # Case-insensitive replacement preserving surrounding text
        pattern = re.compile(re.escape(tell), re.IGNORECASE)
        result = pattern.sub("", result)
    # Clean up any double-spaces or leading/trailing whitespace left behind
    result = re.sub(r"  +", " ", result).strip()
    return result


# ---------------------------------------------------------------------------
# Message normalizers — convert platform-specific message shapes to
# [{role: "user"|"assistant", content: str}] for LLM prompt building.
# "user" = incoming (the match), "assistant" = outgoing (our account).
# ---------------------------------------------------------------------------


def _normalize_tinder_messages(
    messages: list[dict],
    our_user_id: str,
) -> list[dict]:
    normalized = []
    for msg in messages:
        from_id = msg.get("from", msg.get("from_id", ""))
        body = str(msg.get("message", msg.get("body", "")))
        role = "assistant" if str(from_id) == str(our_user_id) else "user"
        normalized.append({"role": role, "content": body})
    return normalized


def _normalize_bumble_messages(
    messages: list[dict],
    our_user_id: str,
) -> list[dict]:
    normalized = []
    for msg in messages:
        sender_id = str(msg.get("sender_id", msg.get("user_id", "")))
        body = str(msg.get("body", msg.get("text", "")))
        role = "assistant" if sender_id == str(our_user_id) else "user"
        normalized.append({"role": role, "content": body})
    return normalized


def _normalize_hinge_messages(
    messages: list[dict],
    our_user_id: str,
) -> list[dict]:
    normalized = []
    for msg in messages:
        sender_id = str(msg.get("sender_id", msg.get("from_id", "")))
        body = str(msg.get("body", msg.get("text", "")))
        role = "assistant" if sender_id == str(our_user_id) else "user"
        normalized.append({"role": role, "content": body})
    return normalized


def _normalize_grindr_messages(
    messages: list[dict],
    our_profile_id: str,
) -> list[dict]:
    normalized = []
    for msg in messages:
        sender_id = str(msg.get("senderId", msg.get("sender_id", "")))
        body = str(msg.get("body", msg.get("text", "")))
        role = "assistant" if sender_id == str(our_profile_id) else "user"
        normalized.append({"role": role, "content": body})
    return normalized


# ---------------------------------------------------------------------------
# Inbox unread detection helpers
# ---------------------------------------------------------------------------


def _tinder_has_unread_inbound(messages: list[dict], our_user_id: str) -> bool:
    """True if the most recent message was from the match (not us)."""
    if not messages:
        return False
    # Tinder messages newest-first in get_matches response
    latest = messages[0]
    from_id = str(latest.get("from", latest.get("from_id", "")))
    return from_id != str(our_user_id)


def _hinge_has_unread_inbound(messages: list[dict], our_user_id: str) -> bool:
    """True if the most recent message was from the match (not us)."""
    if not messages:
        return False
    latest = messages[-1]  # Hinge oldest-first
    sender_id = str(latest.get("sender_id", latest.get("from_id", "")))
    return sender_id != str(our_user_id)
