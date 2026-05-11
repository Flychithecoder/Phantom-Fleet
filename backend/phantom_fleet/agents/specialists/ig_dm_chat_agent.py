"""
IGDMChatAgent — AI-powered DM inbox responder for Instagram.

Inherits all core logic from _BaseDMChatAgent:
    - LLM reply generation (claude-haiku-4-5-20251001)
    - LLM tell stripping
    - Conversation state tracking
    - Daily cap enforcement (40 msgs/day, code-enforced)
    - Min 90s gate between replies to same thread (code-enforced)
    - PPV pitch at configured message threshold
    - Human handoff flagging
    - XML-delimited prompt construction

Platform-specific overrides:
    - _fetch_inbox() → client.get_inbox()
    - _send_reply()  → client.send_dm()
    - _build_client() → InstagramClient context manager
    - platform_name = "instagram"
    - _default_profile = INSTAGRAM_FLIRTY (ChatTier.FLIRTY_SFW)

Intent classification (NEW):
    Before generating each reply, DMIntentClassifier classifies the thread:
        - STORY_REPLY / ENGAGED_FAN → INSTAGRAM_FLIRTY_SFW profile
        - NEW_FAN                   → INSTAGRAM_CASUAL_SFW profile
        - LOW_INTENT / NEGATIVE     → thread skipped, no LLM call, $0 cost

    Intent classification is logged in WorkerResult["intent_log"] for
    analytics and cost attribution.

Agent audit table (CLAUDE.md):
    ┌─────────────────┬──────────────────────────────────────────────────────┐
    │ Agent           │ IGDMChatAgent                                        │
    │ Purpose         │ AI-powered Instagram DM inbox responder              │
    │ Tools           │ None — direct HTTP via InstagramClient               │
    │ Untrusted input │ DM message bodies (XML-delimited in all prompts)     │
    │ User isolation  │ Keyed by (account_id, "instagram", thread_id)        │
    │ Cost cap        │ 40 replies × $0.00025 ≈ $0.01/account/day           │
    │ Loop cap        │ MAX_CONVERSATIONS_PER_SESSION = 20 (code-enforced)   │
    │ Confirmation    │ None required (non-destructive sends)                │
    └─────────────────┴──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import contextlib
import logging
import time
from typing import Optional

from ...core.chat_modes import (
    CHAT_MODE_CATALOG,
    INSTAGRAM_CASUAL_SFW,
    INSTAGRAM_FLIRTY,
    INSTAGRAM_FLIRTY_SFW,
    INSTAGRAM_NSFW,
    ChatModeProfile,
    ChatTier,
)
from ...core.voice_style import (
    apply_voice_style,
    build_voice_prefix,
    has_banned_phrases,
    voice_style_score,
    STYLE_RETRY_NUDGE,
)
from ...core.dm_intent_classifier import (
    CLASSIFIER,
    DMIntent,
    INTENT_MAX_TOKENS,
    INTENT_PROFILE_MAP,
)
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGSession,
    InstagramClient,
)
from .base_dm_chat_agent import (
    MAX_MESSAGES_PER_ACCOUNT_PER_DAY,
    MAX_CONVERSATIONS_PER_SESSION,
    MIN_SECONDS_BETWEEN_REPLIES_SAME_THREAD,
    OPENROUTER_MAX_TOKENS,
    _BaseDMChatAgent,
    DMConversationState,
    DMReplyRecord,
    _extract_recipient_id,
    _ppv_pitch_for,
    _strip_llm_tells,
)

log = logging.getLogger(__name__)


class IGDMChatAgent(_BaseDMChatAgent):
    """
    AI-powered Instagram DM inbox responder with intent-based routing.

    Usage:
        agent = IGDMChatAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            chat_tier=ChatTier.FLIRTY_SFW,
            date_iso="2026-04-11",
            ppv_pitch_after_msgs=4,
        )

    Returns a WorkerResult with `data` keys:
        replies_sent, threads_touched, ppv_pitched,
        human_handoff_flagged, errors, intent_log
    """

    platform_name: str = "instagram"
    _default_profile: ChatModeProfile = INSTAGRAM_FLIRTY

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        chat_tier: ChatTier = ChatTier.FLIRTY_SFW,
        date_iso: Optional[str] = None,
        ppv_pitch_after_msgs: int = 4,
    ) -> WorkerResult:
        """
        Process the Instagram DM inbox for one account.

        Args:
            account_id:           Internal account identifier.
            session:              Authenticated IGSession.
            chat_tier:            ChatTier controlling the fallback profile voice.
                                  Intent routing may override this per-thread.
            date_iso:             YYYY-MM-DD (defaults to today UTC).
            ppv_pitch_after_msgs: Messages sent before injecting a PPV pitch.

        Returns:
            WorkerResult with detailed summary in data dict.
        """
        task_id = f"{account_id}_ig_dm_{date_iso or 'today'}"

        try:
            summary = await self._run_inbox_with_intent(
                account_id=account_id,
                session=session,
                chat_tier=chat_tier,
                date_iso=date_iso,
                ppv_pitch_after_msgs=ppv_pitch_after_msgs,
            )
        except Exception as exc:
            log.error("[%s/instagram] Session-level error: %s", account_id, exc)
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=False,
                error=str(exc),
                data={},
            )

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":                "ig_dm_chat",
                "replies_sent":          summary["replies_sent"],
                "threads_touched":       summary["threads_touched"],
                "ppv_pitched":           summary["ppv_pitched"],
                "human_handoff_flagged": summary["human_handoff_flagged"],
                "errors":                summary["errors"],
                # Intent log: list of {thread_id, intent, profile, skipped}
                "intent_log":            summary.get("intent_log", []),
            },
        )

    # ------------------------------------------------------------------
    # Intent-aware inbox processing
    # ------------------------------------------------------------------

    async def _run_inbox_with_intent(
        self,
        account_id: str,
        session: IGSession,
        chat_tier: ChatTier,
        date_iso: Optional[str],
        ppv_pitch_after_msgs: int,
    ) -> dict:
        """
        Extended inbox loop that runs intent classification before each LLM call.

        For each thread:
          1. Classify intent (rule-based, no LLM cost)
          2. Look up profile from INTENT_PROFILE_MAP
          3. If None (LOW_INTENT / NEGATIVE) → skip thread, log, continue
          4. Look up intent-specific max_tokens budget
          5. Generate reply using that profile and budget
          6. Log classification in intent_log
        """
        import asyncio
        import json
        import os
        from datetime import date, datetime, timezone

        from ...core.chat_modes import reject_content, validate_mode_for_platform

        if date_iso is None:
            date_iso = date.today().isoformat()
        self.ppv_pitch_after_msgs = ppv_pitch_after_msgs

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            log.error("[%s/instagram] OPENROUTER_API_KEY not set", account_id)

        total_sent_today = sum(
            s.messages_sent_today
            for s in self._states.values()
            if s.account_id == account_id and s.platform == self.platform_name
        )

        summary = {
            "replies_sent":          0,
            "threads_touched":       0,
            "ppv_pitched":           0,
            "human_handoff_flagged": 0,
            "errors":                [],
            "intent_log":            [],
        }

        threads_processed = 0
        cursor = ""

        async with self._build_client(session) as client:
            while True:
                if total_sent_today >= MAX_MESSAGES_PER_ACCOUNT_PER_DAY:
                    log.info("[%s/instagram] Daily cap reached", account_id)
                    break
                if threads_processed >= MAX_CONVERSATIONS_PER_SESSION:
                    log.info("[%s/instagram] Conversation cap reached", account_id)
                    break

                try:
                    inbox_resp = await self._fetch_inbox(client, cursor)
                except Exception as exc:
                    log.error("[%s/instagram] Inbox fetch error: %s", account_id, exc)
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

                    # ---------------------------------------------------------
                    # Intent classification (no LLM cost)
                    # ---------------------------------------------------------

                    # Latest inbound message text for keyword matching
                    latest_msg = ""
                    recent_target_msgs: list[str] = []
                    for item in items:
                        if not item.get("is_sent_by_viewer", False):
                            text = item.get("text") or item.get("like", {}).get("emoji") or ""
                            recent_target_msgs.append(text)
                            if not latest_msg:
                                latest_msg = text

                    # Get or create state for this thread
                    state_key = (account_id, self.platform_name, thread_id)
                    if state_key not in self._states:
                        self._states[state_key] = DMConversationState(
                            thread_id=thread_id,
                            platform=self.platform_name,
                            account_id=account_id,
                        )
                    state = self._states[state_key]

                    # Build account_state for the classifier from per-thread state
                    acct_state = {
                        "past_purchases": getattr(state, "past_purchases", 0),
                    }

                    # Build thread metadata expected by classifier
                    classifier_thread = {
                        "thread_id":      thread_id,
                        "is_story_reply": thread.get("is_story_reply", False),
                        # message_count covers all exchanges in this thread
                        "message_count":  len(items),
                    }

                    intent: DMIntent = CLASSIFIER.classify(
                        message=latest_msg,
                        thread=classifier_thread,
                        account_state=acct_state,
                        recent_target_messages=recent_target_msgs[:3],
                    )

                    # Look up profile and limits for this intent
                    profile_name: Optional[str] = INTENT_PROFILE_MAP.get(intent)
                    intent_max_tokens: int = INTENT_MAX_TOKENS.get(intent, OPENROUTER_MAX_TOKENS)

                    # Build log entry (before possible skip so skips are recorded too)
                    intent_entry = {
                        "thread_id":  thread_id,
                        "intent":     intent.value,
                        "profile":    profile_name,
                        "max_tokens": intent_max_tokens,
                        "skipped":    profile_name is None,
                    }
                    summary["intent_log"].append(intent_entry)

                    log.info(
                        "[%s/instagram] thread=%s intent=%s profile=%s skipped=%s",
                        account_id, thread_id, intent.value, profile_name, profile_name is None,
                    )

                    # LOW_INTENT or NEGATIVE → skip without LLM call
                    if profile_name is None:
                        continue

                    # Resolve the ChatModeProfile object
                    profile: ChatModeProfile = CHAT_MODE_CATALOG.get(
                        profile_name, self._default_profile
                    )

                    # ---------------------------------------------------------
                    # State + guard checks (same as _BaseDMChatAgent)
                    # ---------------------------------------------------------

                    if state.human_handoff_flagged:
                        summary["human_handoff_flagged"] += 1
                        continue

                    if profile.handoff_mode == "real_human":
                        state.human_handoff_flagged = True
                        summary["human_handoff_flagged"] += 1
                        continue

                    now = time.time()
                    if (
                        state.last_reply_at > 0
                        and (now - state.last_reply_at) < MIN_SECONDS_BETWEEN_REPLIES_SAME_THREAD
                    ):
                        log.debug(
                            "[%s/instagram] Thread %s: min-gap not elapsed",
                            account_id, thread_id,
                        )
                        continue

                    # ---------------------------------------------------------
                    # Build conversation and PPV text
                    # ---------------------------------------------------------

                    from .base_dm_chat_agent import MAX_CONVERSATION_HISTORY
                    recent_msgs_slice = items[:MAX_CONVERSATION_HISTORY]

                    # Use parent _format_conversation helper
                    conversation_text = self._format_conversation(recent_msgs_slice)

                    recipient_id = _extract_recipient_id(thread)

                    ppv_text = ""
                    if (
                        not state.ppv_pitched
                        and state.messages_sent_today >= ppv_pitch_after_msgs
                    ):
                        ppv_text = _ppv_pitch_for(account_id, thread_id)

                    # ---------------------------------------------------------
                    # LLM call — pass intent-specific max_tokens
                    # ---------------------------------------------------------

                    reply_text = await self._generate_reply_with_tokens(
                        account_id=account_id,
                        thread_id=thread_id,
                        profile=profile,
                        conversation_text=conversation_text,
                        ppv_text=ppv_text,
                        api_key=api_key,
                        date_iso=date_iso,
                        max_tokens=intent_max_tokens,
                    )

                    if reply_text is None:
                        summary["errors"].append(f"llm_fail:thread={thread_id}")
                        continue

                    # Audit BEFORE send
                    audit_ts = datetime.now(timezone.utc).isoformat()
                    log.info(
                        "[%s/instagram] Sending reply to thread %s (len=%d intent=%s ts=%s)",
                        account_id, thread_id, len(reply_text), intent.value, audit_ts,
                    )

                    try:
                        await self._send_reply(client, thread_id, recipient_id, reply_text)
                    except Exception as exc:
                        log.error(
                            "[%s/instagram] Send error for thread %s: %s",
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

                    # Inter-conversation sleep
                    from .base_dm_chat_agent import _REPLY_TIMING_DIST
                    inter_delay = _REPLY_TIMING_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_conv_{thread_id}",
                    )
                    await asyncio.sleep(inter_delay)

                # Advance cursor
                next_cursor = (
                    inbox_resp.get("oldest_cursor")
                    or inbox_resp.get("cursor")
                    or ""
                )
                if not next_cursor or not inbox_resp.get("has_older", False):
                    break
                cursor = next_cursor

        return summary

    # ------------------------------------------------------------------
    # LLM call with explicit max_tokens override
    # ------------------------------------------------------------------

    async def _generate_reply_with_tokens(
        self,
        account_id: str,
        thread_id: str,
        profile: ChatModeProfile,
        conversation_text: str,
        ppv_text: str,
        api_key: str,
        date_iso: str,
        max_tokens: int,
    ) -> Optional[str]:
        """
        Identical to _BaseDMChatAgent._generate_reply but accepts an explicit
        max_tokens parameter so intent-specific budgets are respected.
        """
        import json
        import httpx
        from ...core.chat_modes import reject_content  # noqa: PLC0415 (deferred)
        from .base_dm_chat_agent import (
            OPENROUTER_API_URL,
            OPENROUTER_MODEL,
            OPENROUTER_TEMPERATURE,
            MAX_LLM_RETRIES,
        )

        ppv_instruction = (
            f"\n\nAfter your reply, also append this exactly: {ppv_text}"
            if ppv_text
            else ""
        )

        # --- Voice style prefix (Gen Z 2026 baseline) ---
        voice_prefix = build_voice_prefix(self.platform_name)
        if voice_prefix:
            full_system_prompt = (
                f"{voice_prefix}\n\n"
                f"---\n\n"
                f"{profile.system_prompt}{ppv_instruction}\n\n"
                f"Keep your reply under {profile.max_reply_words} words."
            )
        else:
            full_system_prompt = (
                f"{profile.system_prompt}{ppv_instruction}\n\n"
                f"Keep your reply under {profile.max_reply_words} words."
            )

        base_user_prompt = (
            f"<conversation>\n{conversation_text}\n</conversation>\n\n"
            f"Reply to the last message from the other person."
        )

        payload = {
            "model":       OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": full_system_prompt},
                {"role": "user",   "content": base_user_prompt},
            ],
            "temperature": OPENROUTER_TEMPERATURE,
            "max_tokens":  max_tokens,
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
                        "[%s/instagram] Empty LLM reply on attempt %d",
                        account_id, attempt + 1,
                    )
                    continue

                # --- Voice style post-processing pipeline ---
                styled = apply_voice_style(raw)

                needs_retry = (
                    has_banned_phrases(styled) or voice_style_score(styled) < 0.5
                )
                if needs_retry and attempt < MAX_LLM_RETRIES - 1:
                    log.debug(
                        "[%s/instagram] Voice style gate failed on attempt %d "
                        "(banned=%s, score=%.2f) — retrying with nudge",
                        account_id, attempt + 1,
                        has_banned_phrases(styled), voice_style_score(styled),
                    )
                    payload["messages"][1]["content"] = (
                        f"{base_user_prompt}\n\n{STYLE_RETRY_NUDGE}"
                    )
                    continue

                reply = _strip_llm_tells(styled)

                rejected, reason = reject_content(profile, reply)
                if rejected:
                    log.warning(
                        "[%s/instagram] Reply rejected (%s) on attempt %d",
                        account_id, reason, attempt + 1,
                    )
                    continue

                return reply

            except Exception as exc:
                log.error(
                    "[%s/instagram] LLM call error (attempt %d): %s",
                    account_id, attempt + 1, exc,
                )

        return None

    # ------------------------------------------------------------------
    # Platform-specific implementations
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
