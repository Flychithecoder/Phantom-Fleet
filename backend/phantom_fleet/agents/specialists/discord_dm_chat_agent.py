"""
DiscordDMChatAgent — AI-powered DM responder for Discord.

Responsibilities:
    - Fetch recent messages from known DM channel IDs (from task params)
    - Gate on account age (skip if account < 14 days old)
    - Enforce daily DM cap: max 15 replies/account/day (code-enforced)
    - Enforce min gap: 120s between replies in same DM channel
    - Generate AI replies via OpenRouter (claude-haiku-4-5-20251001)
    - Strip LLM tells + strip any @ mentions hallucinated by the LLM
    - Add Discord-native emoji with 20% probability (seeded per account+conv)
    - Send via client.send_dm()
    - PPV pitch at threshold; human handoff support

Discord context:
    - Casual, uses Discord-specific expressions (not formal)
    - Emoji at 20% probability only (not every message — monoculture detection)
    - Strip @ mentions from AI output (LLMs hallucinate Discord usernames)
    - DM rate: max 15/account/day — Discord bans aggressively
    - Account age gate: 14+ days (code-enforced)

Detection hardening (CLAUDE.md fleet-level rules):
    - Inter-conversation sleep: LogNormal(mean=ln(90), sigma=0.5)
    - Daily cap (15) code-enforced
    - Account age gate (14 days) code-enforced
    - Min gap (120s) code-enforced
    - @ mention stripping prevents LLM username hallucination
    - Emoji seeded 20% probability — not hardcoded 100% (that's a detection tell)

Fleet-scale considerations:
    - Emoji probability is seeded per (account_id, conv_id, msg_count) so across
      20K accounts exactly ~20% include emoji, not all-or-none monoculture

Agent audit table (CLAUDE.md):
    ┌────────────────────┬────────────────────────────────────────────────┐
    │ Agent              │ DiscordDMChatAgent                             │
    │ Purpose            │ AI DM reply loop for Discord DM channels       │
    │ Tools              │ None — direct HTTP via DiscordClient           │
    │ Untrusted input    │ Message bodies (XML-delimited in prompts)      │
    │ User isolation     │ Keyed by (account_id, platform, conv_id)       │
    │ Cost cap           │ 0.10 USD/session (from _BaseDMChatAgent)       │
    │ Loop cap           │ max_daily_replies = 15 (code-enforced)         │
    │ Confirmation       │ None (non-destructive messaging)               │
    └────────────────────┴────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any

from ...core.chat_modes import (
    CHAT_MODE_CATALOG,
    DISCORD_CASUAL,
    ChatModeProfile,
    reject_content,
    validate_mode_for_platform,
)
from ...core.discord_client import (
    DiscordClient,
    DiscordRateLimited,
    DiscordSessionExpired,
)
from ...core.distributions import LogNormal
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
# Blast-radius constants (ALL code-enforced)
# ---------------------------------------------------------------------------

MAX_DAILY_REPLIES: int = 15          # Discord bans fast — strict cap
MIN_REPLY_GAP_SEC: float = 120.0    # 2 min minimum between replies to same channel
MIN_ACCOUNT_AGE_DAYS: int = 14       # account age gate
MAX_REPLY_TOKENS: int = 160          # Discord: shorter than Telegram

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# Inter-conversation sleep: mean=ln(90), sigma=0.5 → median≈90s
INTER_CONV_DIST = LogNormal(low=20.0, high=300.0, sigma=0.50)

# ---------------------------------------------------------------------------
# Emoji pool — standard emojis only, added with 20% probability
# Probability seeded per (account_id, conv_id, msg_count) for fleet diversity
# ---------------------------------------------------------------------------

EMOJI_POOL: list[str] = [
    "😂", "😭", "💀", "🔥", "👀", "🤣", "😅", "💯",
    "👍", "🫡", "😮", "🤔", "🫠", "😌", "🫶", "✨",
    "🙃", "😬", "🫣", "🤯",
]

EMOJI_PROBABILITY_THRESHOLD = 51  # ~20% of 256 (0.20 * 256 ≈ 51)


def _should_add_emoji(account_id: str, conv_id: str, msg_count: int) -> bool:
    """
    Deterministically decide if this message should include an emoji.
    ~20% probability, seeded per (account, conv, msg_count).

    Not 100% (that's a detection tell) and not 0% (that's also unnatural).
    Seeded so the fleet-wide emoji rate is exactly ~20%, not clustered.
    """
    key = f"{account_id}|{conv_id}|{msg_count}|emoji_decision"
    digest = hashlib.sha256(key.encode()).digest()
    return digest[0] < EMOJI_PROBABILITY_THRESHOLD


def _emoji_for(account_id: str, conv_id: str, msg_count: int) -> str:
    """Select which emoji to use, seeded per (account, conv, msg_count)."""
    key = f"{account_id}|{conv_id}|{msg_count}|emoji_select"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(EMOJI_POOL)
    return EMOJI_POOL[idx]


def _strip_at_mentions(text: str) -> str:
    """
    Strip @username mentions from AI-generated text.
    LLMs hallucinate Discord usernames — we must remove them before send
    to avoid pinging wrong users or creating detection patterns.
    """
    return re.sub(r"@\w+", "", text).strip()


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class DiscordDMChatAgent(_BaseDMChatAgent):
    """
    AI-powered DM responder for Discord DM channels.

    ctx keys (passed to run_once):
        account_id:              str
        date_iso:                str (YYYY-MM-DD)
        session:                 DiscordSession (pre-built)
        account_created_at:      float — unix timestamp of account creation
        chat_mode:               str — "discord_casual" | "discord_nsfw"
        active_dm_channel_ids:   list[str] — channel IDs to poll for new messages
        cta_link:                str | None
        handoff_mode:            str — "none" | "chat_ai" | "real_human"
    """

    platform_name:         str       = "discord"
    max_daily_replies:     int       = MAX_DAILY_REPLIES
    min_gap_sec:           float     = MIN_REPLY_GAP_SEC
    max_tokens:            int       = MAX_REPLY_TOKENS
    inter_conv_sleep_dist: LogNormal = INTER_CONV_DIST

    # ------------------------------------------------------------------
    # Abstract implementations
    # ------------------------------------------------------------------

    async def _fetch_conversations(self, client: Any) -> list[dict]:
        """
        Fetch messages from known DM channel IDs.

        Discord does not have a single "poll inbox" endpoint for user tokens.
        We track known channel IDs from task params and fetch recent messages
        from each.
        """
        # Called via run_once with channel_ids pre-passed
        # This abstract method is a no-op here; channel fetching is done inline
        return []

    async def _send_reply(self, client: Any, conv: dict, text: str) -> None:
        """Send a message to a Discord DM channel."""
        discord_client: DiscordClient = client
        channel_id: str = conv.get("conv_id", "")
        await discord_client.send_message(channel_id=channel_id, content=text)

    def _get_chat_mode_profile(self) -> ChatModeProfile:
        """Default profile: discord_casual."""
        return DISCORD_CASUAL

    # ------------------------------------------------------------------
    # run_once — entry point for the agent dispatcher
    # ------------------------------------------------------------------

    async def run_once(
        self,
        client: DiscordClient,
        ctx: dict,
    ) -> WorkerResult:
        """
        Execute one DM reply session for one Discord account.

        Returns WorkerResult with replies_sent, dm_channels_touched,
        ppv_pitched, age_gated_skips, errors.
        """
        account_id: str = ctx["account_id"]
        date_iso: str = ctx.get("date_iso", "")
        account_created_at: float = float(ctx.get("account_created_at", 0.0))
        mode_name: str = ctx.get("chat_mode", "discord_casual")
        active_dm_channel_ids: list[str] = ctx.get("active_dm_channel_ids", [])
        cta_link: str | None = ctx.get("cta_link")
        handoff_mode: str = ctx.get("handoff_mode", "chat_ai")

        # Validate mode for platform
        try:
            validate_mode_for_platform("discord", mode_name)
        except Exception as exc:
            log.error("Mode validation failed: %s", exc)
            return WorkerResult(errors=[str(exc)])

        profile = CHAT_MODE_CATALOG.get(mode_name)
        if profile is None:
            err = f"Unknown chat mode: {mode_name}"
            log.error(err)
            return WorkerResult(errors=[err])

        if handoff_mode == "real_human":
            log.info("[discord/%s] real_human mode — skipping AI DM session", account_id)
            return WorkerResult()

        result = WorkerResult()
        result.dm_channels_touched = 0
        result.age_gated_skips = 0

        # ------------------------------------------------------------------
        # Account age gate (code-enforced)
        # ------------------------------------------------------------------
        now = time.time()
        account_age_days = (now - account_created_at) / 86400.0 if account_created_at else 9999

        if account_age_days < MIN_ACCOUNT_AGE_DAYS:
            log.info(
                "[discord/%s] Account age %.1f days < %d — age gate applied",
                account_id, account_age_days, MIN_ACCOUNT_AGE_DAYS,
            )
            result.age_gated_skips = len(active_dm_channel_ids)
            return result

        # Ensure daily counter is initialised
        if account_id not in self._daily_sent:
            self._daily_sent[account_id] = 0

        # ------------------------------------------------------------------
        # Process each known DM channel
        # ------------------------------------------------------------------
        for channel_id in active_dm_channel_ids:
            # Guard: daily account cap (code-enforced)
            if self._daily_sent.get(account_id, 0) >= self.max_daily_replies:
                log.info(
                    "[discord/%s] Daily cap %d reached, stopping",
                    account_id, self.max_daily_replies,
                )
                break

            # Fetch recent messages from this DM channel
            try:
                raw_messages = await client._get(
                    f"channels/{channel_id}/messages",
                    params={"limit": 10},
                )
            except DiscordSessionExpired:
                result.errors.append("session_expired")
                return result
            except DiscordRateLimited as e:
                result.errors.append(f"rate_limited:{e.retry_after_sec}s")
                break
            except Exception as exc:
                result.errors.append(f"fetch_messages:{channel_id}:{exc}")
                continue

            messages = raw_messages if isinstance(raw_messages, list) else []
            if not messages:
                continue

            # Check if the most recent message is from us (user_id match)
            # If the last message is from us, skip (we already replied)
            account_user_id = client.session.user_id
            latest_msg = messages[0]  # Discord returns newest-first
            if str(latest_msg.get("author", {}).get("id", "")) == str(account_user_id):
                continue

            state_key = (account_id, "discord", channel_id)
            if state_key not in self._states:
                self._states[state_key] = ConversationState(
                    account_id=account_id,
                    platform="discord",
                    conversation_id=channel_id,
                )
            state = self._states[state_key]

            # Guard: human handoff
            if state.human_handoff_flagged:
                continue

            # Guard: min gap between replies (code-enforced)
            gap = now - state.last_reply_at
            if state.last_reply_at > 0 and gap < self.min_gap_sec:
                log.debug(
                    "[discord/%s/%s] Gap %.1fs < %.1fs, skipping",
                    account_id, channel_id, gap, self.min_gap_sec,
                )
                continue

            result.dm_channels_touched += 1

            # Normalize messages for prompt (Discord returns newest-first; reverse)
            normalized_msgs = []
            for m in reversed(messages[-10:]):
                is_me = str(m.get("author", {}).get("id", "")) == str(account_user_id)
                normalized_msgs.append({
                    "role": "me" if is_me else "other",
                    "text": m.get("content", ""),
                    "from_me": is_me,
                })

            style_hint = _reply_style_hint(
                account_id, channel_id, state.messages_sent_today
            )
            prompt_user = self._build_prompt(profile, normalized_msgs, style_hint)

            # PPV pitch at threshold
            if (
                not state.ppv_pitched
                and profile.cta_allowed
                and state.messages_sent_today >= profile.max_turns_before_cta
                and cta_link
            ):
                pitch = _ppv_pitch_for(account_id, channel_id)
                pitch_with_link = f"{pitch}\n{cta_link}"
                pitch_clean = _strip_at_mentions(pitch_with_link)
                try:
                    await client.send_message(channel_id=channel_id, content=pitch_clean)
                    state.ppv_pitched = True
                    state.messages_sent_today += 1
                    state.last_reply_at = time.time()
                    self._daily_sent[account_id] = self._daily_sent.get(account_id, 0) + 1
                    result.replies_sent += 1
                    result.ppv_pitched += 1
                except DiscordRateLimited as e:
                    result.errors.append(f"rate_limited:{e.retry_after_sec}s")
                    break
                except DiscordSessionExpired:
                    result.errors.append("session_expired")
                    return result
                except Exception as exc:
                    result.errors.append(f"ppv_pitch_send:{exc}")
                continue

            # LLM reply generation with retries
            reply_text: str | None = None
            for attempt in range(MAX_LLM_RETRIES):
                try:
                    raw = await self._call_openrouter(
                        system_prompt=profile.system_prompt,
                        user_prompt=prompt_user,
                        max_tokens=self.max_tokens,
                    )
                    # Strip LLM tells + @ mention hallucinations
                    cleaned = strip_llm_tells(raw)
                    cleaned = _strip_at_mentions(cleaned)

                    rejected, reason = reject_content(profile, cleaned)
                    if rejected:
                        log.debug(
                            "[discord/%s/%s] Rejected attempt %d: %s",
                            account_id, channel_id, attempt, reason,
                        )
                        continue
                    reply_text = cleaned
                    break
                except Exception as exc:
                    log.warning(
                        "[discord/%s/%s] LLM attempt %d failed: %s",
                        account_id, channel_id, attempt, exc,
                    )

            if not reply_text:
                result.errors.append(f"llm_failed:channel={channel_id}")
                continue

            # Add emoji with 20% seeded probability
            if _should_add_emoji(account_id, channel_id, state.messages_sent_today):
                emoji = _emoji_for(account_id, channel_id, state.messages_sent_today)
                reply_text = f"{reply_text} {emoji}"

            # Send
            try:
                await client.send_message(channel_id=channel_id, content=reply_text)
            except DiscordRateLimited as e:
                result.errors.append(f"rate_limited:{e.retry_after_sec}s")
                break
            except DiscordSessionExpired:
                result.errors.append("session_expired")
                return result
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
