"""
TelegramDMChatAgent — AI-powered DM responder for Telegram.

Responsibilities:
    - Poll new updates via client.get_updates()
    - Filter for private chat messages (not group messages)
    - For each unread DM: check caps → fire typing indicator → generate AI reply → send
    - Enforce hard blast-radius caps (40 replies/account/day, 60s min gap)
    - PPV pitch at configured turn threshold
    - Human handoff for real_human mode

Telegram context:
    - More casual/intimate than IG; longer replies acceptable (max 180 tokens)
    - Supports typing indicator via sendChatAction — fired before every send
    - Typing delay sampled from LogNormal(mean=ln(4), sigma=0.35) to simulate typing
    - Inter-conversation sleep: LogNormal(mean=ln(50), sigma=0.4)

Detection hardening:
    - Typing indicator + realistic typing delay (not fixed) before every send
    - Inter-conversation sleep is LogNormal, never fixed
    - Reply gap gate (60s) enforced by code
    - Daily cap (40) enforced by code
    - LLM tells stripped from all generated text

Agent audit table (CLAUDE.md):
    ┌───────────────────┬──────────────────────────────────────────────┐
    │ Agent             │ TelegramDMChatAgent                          │
    │ Purpose           │ AI DM reply loop for Telegram private chats  │
    │ Tools             │ None — direct HTTP via TelegramClient        │
    │ Untrusted input   │ Message bodies (XML-delimited in prompts)    │
    │ User isolation    │ Keyed by (account_id, platform, conv_id)     │
    │ Cost cap          │ 0.10 USD/session (from _BaseDMChatAgent)     │
    │ Loop cap          │ max_daily_replies = 40 (code-enforced)       │
    │ Confirmation      │ None (non-destructive messaging)             │
    └───────────────────┴──────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...core.chat_modes import (
    CHAT_MODE_CATALOG,
    TELEGRAM_VIP_NSFW,
    ChatModeProfile,
    reject_content,
    validate_mode_for_platform,
)
from ...core.distributions import LogNormal
from ...core.telegram_client import TelegramClient, TelegramFloodWait, TelegramSessionExpired
from ._base_chat import (
    ConversationState,
    MAX_LLM_RETRIES,
    WorkerResult,
    _BaseDMChatAgent,
    _ppv_pitch_for,
    _reply_style_hint,
    strip_llm_tells,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (ALL code-enforced — not prompt-enforced)
# ---------------------------------------------------------------------------

MAX_DAILY_REPLIES: int = 40          # hard DM reply cap per account per day
MIN_REPLY_GAP_SEC: float = 60.0     # minimum seconds between replies to same chat_id
MAX_REPLY_TOKENS: int = 180          # Telegram supports longer replies than IG

# ---------------------------------------------------------------------------
# Timing distributions (LogNormal — never fixed)
# ---------------------------------------------------------------------------

# Inter-conversation sleep: mean=ln(50)≈3.91, sigma=0.4 → median≈50s
INTER_CONV_DIST = LogNormal(low=15.0, high=180.0, sigma=0.40)

# Typing indicator delay: mean=ln(4)≈1.39, sigma=0.35 → median≈4s
TYPING_DELAY_DIST = LogNormal(low=1.5, high=12.0, sigma=0.35)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class TelegramDMChatAgent(_BaseDMChatAgent):
    """
    AI-powered DM responder for Telegram private chats.

    ctx keys (passed to run_once):
        account_id:   str
        date_iso:     str (YYYY-MM-DD)
        session:      TelegramSession (pre-built)
        chat_mode:    str — key into CHAT_MODE_CATALOG
                      must be one of ("telegram_vip_nsfw", "telegram_public_mixed")
        cta_link:     str | None
        handoff_mode: str — "none" | "chat_ai" | "real_human"
        update_offset: int (Telegram getUpdates offset, defaults 0)
    """

    platform_name:         str       = "telegram"
    max_daily_replies:     int       = MAX_DAILY_REPLIES
    min_gap_sec:           float     = MIN_REPLY_GAP_SEC
    max_tokens:            int       = MAX_REPLY_TOKENS
    inter_conv_sleep_dist: LogNormal = INTER_CONV_DIST

    # ------------------------------------------------------------------
    # Abstract implementations
    # ------------------------------------------------------------------

    async def _fetch_conversations(self, client: Any) -> list[dict]:
        """
        Fetch unread private DMs via getUpdates.

        Returns a list of conversation dicts keyed by chat_id.
        Filters out group messages (chat.type != "private").
        """
        tg_client: TelegramClient = client
        updates = await tg_client.get_updates(limit=20)
        conversations: dict[str, dict] = {}

        for update in updates:
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue

            chat = message.get("chat", {})
            # Only private (1-on-1) DMs — group messages handled by TelegramGroupAgent
            if chat.get("type") != "private":
                continue

            chat_id = str(chat.get("id", ""))
            if not chat_id:
                continue

            sender = message.get("from", {})
            sender_id = str(sender.get("id", ""))
            text = message.get("text", "")
            date_ts = float(message.get("date", 0))

            if chat_id not in conversations:
                conversations[chat_id] = {
                    "conv_id": chat_id,
                    "sender_id": sender_id,
                    "messages": [],
                    "unread": True,
                }

            conversations[chat_id]["messages"].append({
                "role": "other",
                "text": text,
                "ts": date_ts,
                "from_me": False,
            })

        return list(conversations.values())

    async def _send_reply(self, client: Any, conv: dict, text: str) -> None:
        """Send a DM via TelegramClient.send_dm."""
        tg_client: TelegramClient = client
        conv_id: str = conv.get("conv_id", "")
        await tg_client.send_dm(user_id=conv_id, text=text)

    def _get_chat_mode_profile(self) -> ChatModeProfile:
        """Default profile: telegram_vip_nsfw. Overridden per account if needed."""
        return TELEGRAM_VIP_NSFW

    # ------------------------------------------------------------------
    # Typing indicator hook (Telegram-specific)
    # ------------------------------------------------------------------

    async def _fire_typing_indicator(
        self, client: TelegramClient, chat_id: str
    ) -> None:
        """
        Send a 'typing' chat action then sleep a LogNormal delay to simulate
        the account actually composing the message.

        Called before every send (both AI replies and PPV pitches).
        """
        try:
            await client._post("sendChatAction", {
                "chat_id": chat_id,
                "action": "typing",
            })
        except Exception as exc:
            # Non-fatal: if the indicator fails, still send the message
            log.debug("Typing indicator failed for chat_id=%s: %s", chat_id, exc)

        # Simulate typing duration (LogNormal, not fixed)
        delay = TYPING_DELAY_DIST.sample()
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # run_once — entry point for the agent dispatcher
    # ------------------------------------------------------------------

    async def run_once(
        self,
        client: TelegramClient,
        ctx: dict,
    ) -> WorkerResult:
        """
        Execute one DM reply session for one Telegram account.

        Overrides _BaseDMChatAgent._run_dm_session with Telegram-specific
        typing indicator injection before every send.

        Returns WorkerResult with replies_sent, threads_touched, ppv_pitched,
        typing_indicators_sent, errors.
        """
        account_id = ctx["account_id"]
        date_iso = ctx.get("date_iso", "")
        mode_name = ctx.get("chat_mode", "telegram_vip_nsfw")
        cta_link: str | None = ctx.get("cta_link")
        handoff_mode: str = ctx.get("handoff_mode", "chat_ai")

        # Validate mode is allowed on this platform
        try:
            validate_mode_for_platform("telegram", mode_name)
        except Exception as exc:
            log.error("Mode validation failed: %s", exc)
            return WorkerResult(errors=[str(exc)])

        profile = CHAT_MODE_CATALOG.get(mode_name)
        if profile is None:
            err = f"Unknown chat mode: {mode_name}"
            log.error(err)
            return WorkerResult(errors=[err])

        if handoff_mode == "real_human":
            log.info("[telegram/%s] real_human mode — skipping AI DM session", account_id)
            return WorkerResult()

        result = WorkerResult()

        # Ensure daily counter is initialised
        if account_id not in self._daily_sent:
            self._daily_sent[account_id] = 0

        # Fetch unread DMs
        try:
            conversations = await self._fetch_conversations(client)
        except TelegramSessionExpired:
            log.warning("[telegram/%s] Session expired", account_id)
            return WorkerResult(errors=["session_expired"])
        except TelegramFloodWait as e:
            log.warning("[telegram/%s] Flood wait %ds", account_id, e.retry_after_sec)
            return WorkerResult(errors=[f"flood_wait:{e.retry_after_sec}s"])
        except Exception as exc:
            err = f"fetch_conversations failed: {exc}"
            log.error("[telegram/%s] %s", account_id, err)
            return WorkerResult(errors=[err])

        for conv in conversations:
            # Guard: daily account cap (code-enforced)
            if self._daily_sent.get(account_id, 0) >= self.max_daily_replies:
                log.info(
                    "[telegram/%s] Daily cap %d reached, stopping",
                    account_id, self.max_daily_replies,
                )
                break

            conv_id: str = conv.get("conv_id", "")
            if not conv_id or not conv.get("unread", False):
                continue

            state_key = (account_id, "telegram", conv_id)
            if state_key not in self._states:
                self._states[state_key] = ConversationState(
                    account_id=account_id,
                    platform="telegram",
                    conversation_id=conv_id,
                )
            state = self._states[state_key]

            # Guard: human handoff
            if state.human_handoff_flagged:
                continue

            # Guard: min gap between replies (code-enforced)
            import time
            now = time.time()
            gap = now - state.last_reply_at
            if state.last_reply_at > 0 and gap < self.min_gap_sec:
                log.debug(
                    "[telegram/%s/%s] Gap %.1fs < %.1fs, skipping",
                    account_id, conv_id, gap, self.min_gap_sec,
                )
                continue

            result.threads_touched += 1

            messages = conv.get("messages", [])
            style_hint = _reply_style_hint(
                account_id, conv_id, state.messages_sent_today
            )
            prompt_user = self._build_prompt(profile, messages, style_hint)

            # PPV pitch at threshold
            ppv_appended = False
            if (
                not state.ppv_pitched
                and profile.cta_allowed
                and state.messages_sent_today >= profile.max_turns_before_cta
                and cta_link
            ):
                pitch = _ppv_pitch_for(account_id, conv_id)
                pitch_with_link = f"{pitch}\n{cta_link}"
                try:
                    await self._fire_typing_indicator(client, conv_id)
                    result.typing_indicators_sent += 1
                    await client.send_dm(user_id=conv_id, text=pitch_with_link)
                    state.ppv_pitched = True
                    state.messages_sent_today += 1
                    state.last_reply_at = time.time()
                    self._daily_sent[account_id] = self._daily_sent.get(account_id, 0) + 1
                    result.replies_sent += 1
                    result.ppv_pitched += 1
                except TelegramFloodWait as e:
                    result.errors.append(f"flood_wait:{e.retry_after_sec}s")
                    break
                except Exception as exc:
                    result.errors.append(f"ppv_pitch_send:{exc}")
                continue  # don't also send AI reply this round

            # LLM reply generation with retries (max 3)
            reply_text: str | None = None
            for attempt in range(MAX_LLM_RETRIES):
                try:
                    raw = await self._call_openrouter(
                        system_prompt=profile.system_prompt,
                        user_prompt=prompt_user,
                        max_tokens=self.max_tokens,
                    )
                    cleaned = strip_llm_tells(raw)
                    rejected, reason = reject_content(profile, cleaned)
                    if rejected:
                        log.debug(
                            "[telegram/%s/%s] Rejected attempt %d: %s",
                            account_id, conv_id, attempt, reason,
                        )
                        continue
                    reply_text = cleaned
                    break
                except Exception as exc:
                    log.warning(
                        "[telegram/%s/%s] LLM attempt %d failed: %s",
                        account_id, conv_id, attempt, exc,
                    )

            if not reply_text:
                result.errors.append(f"llm_failed:conv={conv_id}")
                continue

            # Send with typing indicator (Telegram-specific)
            try:
                await self._fire_typing_indicator(client, conv_id)
                result.typing_indicators_sent += 1
                await client.send_dm(user_id=conv_id, text=reply_text)
            except TelegramFloodWait as e:
                result.errors.append(f"flood_wait:{e.retry_after_sec}s")
                break
            except TelegramSessionExpired:
                result.errors.append("session_expired")
                break
            except Exception as exc:
                result.errors.append(f"send_reply:{exc}")
                continue

            state.messages_sent_today += 1
            state.last_reply_at = time.time()
            self._daily_sent[account_id] = self._daily_sent.get(account_id, 0) + 1
            result.replies_sent += 1

            # Inter-conversation sleep (LogNormal — never fixed)
            sleep_s = self.inter_conv_sleep_dist.sample()
            await asyncio.sleep(sleep_s)

        return result
