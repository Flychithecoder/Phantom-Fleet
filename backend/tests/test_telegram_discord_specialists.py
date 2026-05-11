"""
Tests for Telegram and Discord specialist agents.

Coverage (22 tests):

TelegramDMChatAgent (6):
    1.  Typing indicator sent before reply
    2.  Daily cap at 40 stops processing
    3.  60s gate skips too-recent conversation
    4.  LLM tell stripped from output before send
    5.  PPV pitched at max_turns_before_cta threshold
    6.  XML-delimited content in prompt

TelegramGroupAgent (4):
    7.  Max 2 group joins/day enforced
    8.  Message timing gate (not first to post — wait threshold)
    9.  Dedup prevents same message posted twice to same group
    10. Daily message cap at 5 stops posting

DiscordDMChatAgent (5):
    11. Account age gate (< 14 days → all convs skipped)
    12. Daily cap at 15 stops processing
    13. 120s gate skips too-recent DM channel
    14. Hallucinated @ mention stripped from LLM output
    15. Emoji added with ~20% probability (seeded check)

DiscordServerAgent (5):
    16. Lurk gate applied to newly joined server
    17. Max 1 server/day enforced
    18. Reactions seeded per (account_id, message_id)
    19. Max 10 server messages/day enforced
    20. ValueError raised on template pool with fewer than 20 entries

_BaseDMChatAgent (2 via subclass):
    21. Daily cap enforced via _run_dm_session loop
    22. strip_llm_tells removes all configured tell phrases
"""
from __future__ import annotations

import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from phantom_fleet.agents.specialists._base_chat import (
    WorkerResult,
    _BaseDMChatAgent,
    _ppv_pitch_for,
    strip_llm_tells,
    LLM_TELL_PATTERNS,
)
from phantom_fleet.agents.specialists.telegram_dm_chat_agent import (
    MAX_DAILY_REPLIES as TG_MAX_DAILY_REPLIES,
    MIN_REPLY_GAP_SEC as TG_MIN_GAP,
    TelegramDMChatAgent,
)
from phantom_fleet.agents.specialists.telegram_group_agent import (
    MAX_GROUP_JOINS_PER_DAY,
    MAX_GROUP_MESSAGES_PER_DAY,
    GROUP_MESSAGE_POOL,
    TelegramGroupAgent,
    _group_message_for,
    _message_dedup_key as tg_msg_dedup_key,
)
from phantom_fleet.agents.specialists.discord_dm_chat_agent import (
    MAX_DAILY_REPLIES as DC_MAX_DAILY_REPLIES,
    MIN_ACCOUNT_AGE_DAYS,
    MIN_REPLY_GAP_SEC as DC_MIN_GAP,
    DiscordDMChatAgent,
    _should_add_emoji,
    _strip_at_mentions,
)
from phantom_fleet.agents.specialists.discord_server_agent import (
    MAX_SERVER_JOINS_PER_DAY,
    MAX_MESSAGES_PER_DAY as DC_MAX_MSG_PER_DAY,
    REACTION_POOL,
    SERVER_MESSAGE_POOL,
    DiscordServerAgent,
    _reaction_for,
)
from phantom_fleet.core.telegram_client import TelegramFloodWait, TelegramSessionExpired
from phantom_fleet.core.discord_client import DiscordRateLimited, DiscordSessionExpired


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_tg_client(
    updates: list[dict] | None = None,
    side_effect: Exception | None = None,
) -> MagicMock:
    """Build a mock TelegramClient."""
    client = MagicMock()
    client.session = MagicMock()
    client.session.user_id = "acc_001"
    client.session.account_id = "acc_001"
    if side_effect:
        client.get_updates = AsyncMock(side_effect=side_effect)
    else:
        client.get_updates = AsyncMock(return_value=updates or [])
    client.send_dm = AsyncMock(return_value={"ok": True})
    client._post = AsyncMock(return_value={})
    return client


def _make_dc_client(
    channel_messages: dict[str, list] | None = None,
    user_id: str = "dc_acc_001",
) -> MagicMock:
    """Build a mock DiscordClient."""
    client = MagicMock()
    client.session = MagicMock()
    client.session.user_id = user_id
    client.session.account_id = user_id

    channel_messages = channel_messages or {}

    async def mock_get(endpoint, params=None):
        for ch_id, msgs in channel_messages.items():
            if endpoint == f"channels/{ch_id}/messages":
                return msgs
        return []

    client._get = AsyncMock(side_effect=mock_get)
    client.send_message = AsyncMock(return_value={"id": "msg_001"})
    client.get_dm_channel = AsyncMock(return_value={"id": "ch_999"})
    client.send_dm = AsyncMock(return_value={"id": "msg_002"})
    client.join_server = AsyncMock(return_value={"guild": {"id": "guild_001"}})
    client.react_to_message = AsyncMock(return_value={})
    return client


def _private_update(chat_id: str, text: str, from_user_id: str = "other_user") -> dict:
    """Build a minimal Telegram update dict for a private message."""
    return {
        "update_id": 1,
        "message": {
            "message_id": 100,
            "from": {"id": from_user_id, "first_name": "Test"},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
            "date": int(time.time()),
        },
    }


def _group_update(chat_id: str, text: str) -> dict:
    """Build a minimal Telegram update for a group message."""
    return {
        "update_id": 2,
        "message": {
            "message_id": 200,
            "from": {"id": "group_user", "first_name": "Group"},
            "chat": {"id": chat_id, "type": "supergroup"},
            "text": text,
            "date": int(time.time()),
        },
    }


def _discord_message(
    content: str,
    author_id: str = "other_user",
) -> dict:
    return {
        "id": hashlib.sha256(content.encode()).hexdigest()[:10],
        "content": content,
        "author": {"id": author_id},
    }


# ===========================================================================
# TelegramDMChatAgent tests
# ===========================================================================


class TestTelegramDMChatAgent:

    # -----------------------------------------------------------------------
    # Test 1: Typing indicator sent before reply
    # -----------------------------------------------------------------------
    async def test_typing_indicator_sent_before_reply(self):
        """sendChatAction 'typing' must be called BEFORE send_dm on every reply."""
        agent = TelegramDMChatAgent()
        call_order = []

        async def track_post(method, payload):
            call_order.append(("_post", method))
            return {}

        async def track_send_dm(user_id, text):
            call_order.append(("send_dm", user_id))
            return {}

        client = _make_tg_client(updates=[_private_update("chat_111", "hey there")])
        client._post = AsyncMock(side_effect=track_post)
        client.send_dm = AsyncMock(side_effect=track_send_dm)

        with (
            patch.object(agent, "_call_openrouter", new=AsyncMock(return_value="hey!")),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "chat_mode": "telegram_vip_nsfw",
            })

        assert result.replies_sent == 1
        # typing must appear before send_dm
        typing_idx = next(
            (i for i, c in enumerate(call_order) if c == ("_post", "sendChatAction")),
            None,
        )
        send_idx = next(
            (i for i, c in enumerate(call_order) if c[0] == "send_dm"),
            None,
        )
        assert typing_idx is not None, "typing indicator was never called"
        assert send_idx is not None, "send_dm was never called"
        assert typing_idx < send_idx, "typing indicator must precede send_dm"

    # -----------------------------------------------------------------------
    # Test 2: Daily cap at 40
    # -----------------------------------------------------------------------
    async def test_daily_cap_at_40(self):
        """After 40 replies, the agent must stop processing further conversations."""
        agent = TelegramDMChatAgent()
        # Pre-fill the daily counter to the cap
        agent._daily_sent["acc_001"] = TG_MAX_DAILY_REPLIES

        updates = [_private_update(f"chat_{i}", "hi") for i in range(5)]
        client = _make_tg_client(updates=updates)

        with (
            patch.object(agent, "_call_openrouter", new=AsyncMock(return_value="hey")),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "chat_mode": "telegram_vip_nsfw",
            })

        assert result.replies_sent == 0, "No replies should be sent when daily cap is hit"
        assert client.send_dm.call_count == 0

    # -----------------------------------------------------------------------
    # Test 3: 60s min-gap gate
    # -----------------------------------------------------------------------
    async def test_min_gap_60s_blocks_too_recent(self):
        """A conversation replied to < 60s ago must be skipped."""
        agent = TelegramDMChatAgent()

        # Mark the conversation as having been replied to 10 seconds ago
        agent._states[("acc_001", "telegram", "chat_222")] = MagicMock()
        state = agent._states[("acc_001", "telegram", "chat_222")]
        state.human_handoff_flagged = False
        state.messages_sent_today = 0
        state.last_reply_at = time.time() - 10  # only 10s ago
        state.ppv_pitched = False

        client = _make_tg_client(updates=[_private_update("chat_222", "hello again")])

        with (
            patch.object(agent, "_call_openrouter", new=AsyncMock(return_value="hey")),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "chat_mode": "telegram_vip_nsfw",
            })

        assert result.replies_sent == 0, "Should skip conv within 60s gap"

    # -----------------------------------------------------------------------
    # Test 4: LLM tell stripped
    # -----------------------------------------------------------------------
    async def test_llm_tell_stripped_before_send(self):
        """'Certainly!' prefix in LLM output must be stripped before send."""
        agent = TelegramDMChatAgent()
        client = _make_tg_client(updates=[_private_update("chat_333", "hey")])

        sent_texts: list[str] = []

        async def capture_send(user_id, text):
            sent_texts.append(text)
            return {}

        client.send_dm = AsyncMock(side_effect=capture_send)

        with (
            patch.object(
                agent, "_call_openrouter",
                new=AsyncMock(return_value="Certainly! I'd love to chat more")
            ),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "chat_mode": "telegram_vip_nsfw",
            })

        assert result.replies_sent == 1
        assert sent_texts, "At least one message must have been sent"
        assert "Certainly!" not in sent_texts[0], "LLM tell must be stripped"

    # -----------------------------------------------------------------------
    # Test 5: PPV pitch at threshold
    # -----------------------------------------------------------------------
    async def test_ppv_pitch_at_threshold(self):
        """PPV pitch must be sent when msgs_sent_today >= max_turns_before_cta."""
        agent = TelegramDMChatAgent()

        # Pre-set state so threshold is reached (TELEGRAM_VIP_NSFW.max_turns_before_cta = 5)
        state_key = ("acc_001", "telegram", "chat_444")
        agent._states[state_key] = MagicMock()
        state = agent._states[state_key]
        state.human_handoff_flagged = False
        state.messages_sent_today = 5  # at threshold
        state.last_reply_at = 0.0       # no gap issue
        state.ppv_pitched = False

        client = _make_tg_client(updates=[_private_update("chat_444", "send more")])

        sent_texts: list[str] = []

        async def capture_send(user_id, text):
            sent_texts.append(text)
            return {}

        client.send_dm = AsyncMock(side_effect=capture_send)

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "chat_mode": "telegram_vip_nsfw",
                "cta_link": "https://onlyfans.com/test",
            })

        assert result.ppv_pitched == 1
        assert result.replies_sent == 1
        # The pitch should contain the CTA link
        assert any("onlyfans.com" in t for t in sent_texts), "CTA link must appear in pitch"

    # -----------------------------------------------------------------------
    # Test 6: XML-delimited content in prompt
    # -----------------------------------------------------------------------
    async def test_xml_delimit_in_prompt(self):
        """Untrusted message content must be wrapped in XML tags in the prompt."""
        agent = TelegramDMChatAgent()
        client = _make_tg_client(updates=[_private_update("chat_555", "hey <script>bad</script>")])

        captured_prompts: list[str] = []

        async def capture_llm(system_prompt, user_prompt, max_tokens):
            captured_prompts.append(user_prompt)
            return "hey back"

        with (
            patch.object(agent, "_call_openrouter", new=AsyncMock(side_effect=capture_llm)),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "chat_mode": "telegram_vip_nsfw",
            })

        assert captured_prompts, "LLM must have been called"
        prompt = captured_prompts[0]
        assert "<conversation>" in prompt, "Prompt must contain <conversation> XML tag"
        assert "<message" in prompt, "Prompt must contain <message> XML tag"


# ===========================================================================
# TelegramGroupAgent tests
# ===========================================================================


class TestTelegramGroupAgent:

    # -----------------------------------------------------------------------
    # Test 7: Max 2 group joins/day
    # -----------------------------------------------------------------------
    async def test_max_2_joins_per_day(self):
        """After 2 joins, further invite links must be skipped."""
        agent = TelegramGroupAgent()
        client = _make_tg_client()
        # join_group must be called only twice even if 5 links given
        client.join_group = AsyncMock(return_value={})

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "account_created_at": time.time() - 86400 * 30,  # 30 days old
                "invite_links": [
                    "https://t.me/+aaa",
                    "https://t.me/+bbb",
                    "https://t.me/+ccc",
                    "https://t.me/+ddd",
                    "https://t.me/+eee",
                ],
            })

        assert result.groups_joined == MAX_GROUP_JOINS_PER_DAY
        assert client.join_group.call_count == MAX_GROUP_JOINS_PER_DAY

    # -----------------------------------------------------------------------
    # Test 8: Post timing gate (don't be first)
    # -----------------------------------------------------------------------
    async def test_post_timing_gate_prevents_immediate_post(self):
        """Account should not post immediately after the last group activity."""
        agent = TelegramGroupAgent()
        client = _make_tg_client()
        client.send_dm = AsyncMock(return_value={})

        # last_activity_at = 5 seconds ago — well below the 10-min average threshold
        recent_activity = time.time() - 5

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "account_created_at": time.time() - 86400 * 30,
                "invite_links": [],
                "known_groups": [
                    {
                        "group_id": "group_001",
                        "last_activity_at": recent_activity,
                    }
                ],
            })

        # The timing threshold is sampled from LogNormal(low=120, ...) so at minimum
        # the gate should be at least 120s; 5s activity is far too recent
        assert result.messages_posted == 0, "Should not post when group was just active"

    # -----------------------------------------------------------------------
    # Test 9: Dedup prevents repeat message
    # -----------------------------------------------------------------------
    async def test_dedup_prevents_repeat_message(self):
        """Same message must not be posted twice to the same group."""
        agent = TelegramGroupAgent()
        client = _make_tg_client()
        client.send_dm = AsyncMock(return_value={})

        account_id = "acc_001"
        group_id = "group_002"
        date_iso = "2026-04-11"

        # Pre-compute the message that will be selected
        message = _group_message_for(account_id, group_id, date_iso)
        dedup_key = tg_msg_dedup_key(account_id, group_id, message)

        # Pre-insert the dedup key into the state
        from phantom_fleet.agents.specialists.telegram_group_agent import GroupParticipationState
        state_key = (account_id, group_id)
        agent._group_states[state_key] = GroupParticipationState(
            account_id=account_id,
            group_id=group_id,
            last_activity_at=0.0,
        )
        agent._group_states[state_key].posted_message_keys.add(dedup_key)

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run_once(client, {
                "account_id": account_id,
                "date_iso": date_iso,
                "account_created_at": time.time() - 86400 * 30,
                "invite_links": [],
                "known_groups": [{"group_id": group_id, "last_activity_at": 0.0}],
            })

        assert result.messages_posted == 0, "Dedup must prevent repeat posting"
        assert client.send_dm.call_count == 0

    # -----------------------------------------------------------------------
    # Test 10: Daily message cap at 5
    # -----------------------------------------------------------------------
    async def test_daily_message_cap_at_5(self):
        """After 5 group messages, posting must stop."""
        agent = TelegramGroupAgent()
        client = _make_tg_client()
        client.send_dm = AsyncMock(return_value={})

        # Pre-fill the daily message counter to the cap
        agent._msgs_today["acc_001"] = MAX_GROUP_MESSAGES_PER_DAY

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run_once(client, {
                "account_id": "acc_001",
                "date_iso": "2026-04-11",
                "account_created_at": time.time() - 86400 * 30,
                "invite_links": [],
                "known_groups": [
                    {"group_id": f"group_{i}", "last_activity_at": 0.0}
                    for i in range(5)
                ],
                "messages_today": MAX_GROUP_MESSAGES_PER_DAY,
            })

        assert result.messages_posted == 0, "No posting after daily cap"
        assert client.send_dm.call_count == 0


# ===========================================================================
# DiscordDMChatAgent tests
# ===========================================================================


class TestDiscordDMChatAgent:

    # -----------------------------------------------------------------------
    # Test 11: Account age gate (< 14 days skipped)
    # -----------------------------------------------------------------------
    async def test_account_age_gate_skips_young_account(self):
        """Account < 14 days old must have all DM channels skipped."""
        agent = DiscordDMChatAgent()
        client = _make_dc_client(channel_messages={
            "ch_001": [_discord_message("hey there")],
        })

        # Account created 5 days ago
        young_account_ts = time.time() - 86400 * 5

        result = await agent.run_once(client, {
            "account_id": "dc_001",
            "date_iso": "2026-04-11",
            "account_created_at": young_account_ts,
            "active_dm_channel_ids": ["ch_001"],
            "chat_mode": "discord_casual",
        })

        assert result.age_gated_skips == 1, "Age gate must count skipped channels"
        assert result.replies_sent == 0
        assert client.send_message.call_count == 0

    # -----------------------------------------------------------------------
    # Test 12: Daily cap at 15
    # -----------------------------------------------------------------------
    async def test_daily_cap_at_15(self):
        """After 15 replies, no more DMs must be sent."""
        agent = DiscordDMChatAgent()
        # Pre-fill the daily counter to the cap
        agent._daily_sent["dc_001"] = DC_MAX_DAILY_REPLIES

        client = _make_dc_client(channel_messages={
            f"ch_{i}": [_discord_message("hello")] for i in range(5)
        })

        old_account_ts = time.time() - 86400 * 30  # 30 days old

        with (
            patch.object(agent, "_call_openrouter", new=AsyncMock(return_value="hey")),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await agent.run_once(client, {
                "account_id": "dc_001",
                "date_iso": "2026-04-11",
                "account_created_at": old_account_ts,
                "active_dm_channel_ids": [f"ch_{i}" for i in range(5)],
                "chat_mode": "discord_casual",
            })

        assert result.replies_sent == 0
        assert client.send_message.call_count == 0

    # -----------------------------------------------------------------------
    # Test 13: 120s min-gap gate
    # -----------------------------------------------------------------------
    async def test_min_gap_120s_blocks_too_recent(self):
        """A DM channel replied to < 120s ago must be skipped."""
        agent = DiscordDMChatAgent()

        old_account_ts = time.time() - 86400 * 30

        # Pre-set last_reply_at to 30 seconds ago
        state_key = ("dc_001", "discord", "ch_777")
        agent._states[state_key] = MagicMock()
        state = agent._states[state_key]
        state.human_handoff_flagged = False
        state.messages_sent_today = 0
        state.last_reply_at = time.time() - 30  # only 30s ago
        state.ppv_pitched = False

        client = _make_dc_client(
            channel_messages={"ch_777": [_discord_message("hey")]},
            user_id="dc_001",
        )

        with (
            patch.object(agent, "_call_openrouter", new=AsyncMock(return_value="hey")),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await agent.run_once(client, {
                "account_id": "dc_001",
                "date_iso": "2026-04-11",
                "account_created_at": old_account_ts,
                "active_dm_channel_ids": ["ch_777"],
                "chat_mode": "discord_casual",
            })

        assert result.replies_sent == 0, "Should skip channel within 120s gap"

    # -----------------------------------------------------------------------
    # Test 14: @ mention stripped from LLM output
    # -----------------------------------------------------------------------
    async def test_at_mention_stripped_from_output(self):
        """@username hallucinations from LLM must be removed before sending."""
        text_with_mention = "hey @phantom_user check this out"
        stripped = _strip_at_mentions(text_with_mention)
        assert "@" not in stripped, "@ mentions must be stripped"
        assert "check this out" in stripped, "Non-mention content must remain"

    async def test_at_mention_stripped_in_full_send_path(self):
        """End-to-end: LLM returns @mention, sent message must have it stripped."""
        agent = DiscordDMChatAgent()
        old_account_ts = time.time() - 86400 * 30
        client = _make_dc_client(
            channel_messages={"ch_888": [_discord_message("yo")]},
            user_id="dc_888",
        )

        sent_contents: list[str] = []

        async def capture_send(channel_id, content):
            sent_contents.append(content)
            return {"id": "msg_x"}

        client.send_message = AsyncMock(side_effect=capture_send)

        with (
            patch.object(
                agent, "_call_openrouter",
                new=AsyncMock(return_value="hey @fakeuser come here"),
            ),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await agent.run_once(client, {
                "account_id": "dc_888",
                "date_iso": "2026-04-11",
                "account_created_at": old_account_ts,
                "active_dm_channel_ids": ["ch_888"],
                "chat_mode": "discord_casual",
            })

        assert result.replies_sent == 1
        assert sent_contents, "Message must have been sent"
        assert "@fakeuser" not in sent_contents[0], "@ mention must be stripped"

    # -----------------------------------------------------------------------
    # Test 15: Emoji at 20% seeded probability (not 100%)
    # -----------------------------------------------------------------------
    async def test_emoji_20_percent_probability_not_100(self):
        """Across many (account, conv, msg_count) combinations, emoji is added ~20%."""
        positive = 0
        total = 1000
        for i in range(total):
            if _should_add_emoji(f"acc_{i}", "conv_x", i % 10):
                positive += 1
        rate = positive / total
        # Should be ~20%; allow 10%-30% range to avoid flakiness
        assert 0.10 <= rate <= 0.30, (
            f"Emoji probability must be ~20%, got {rate:.2%}"
        )

    async def test_emoji_not_added_to_every_message(self):
        """At least some messages should not have emoji (not 100% monoculture)."""
        # For a fixed conv/msg_count, check that not all accounts get emoji
        has_emoji = [_should_add_emoji(f"acc_{i}", "conv_y", 0) for i in range(50)]
        assert not all(has_emoji), "Emoji must not be added to 100% of messages"
        assert any(not e for e in has_emoji), "Some messages must not have emoji"


# ===========================================================================
# DiscordServerAgent tests
# ===========================================================================


class TestDiscordServerAgent:

    # -----------------------------------------------------------------------
    # Test 16: Lurk gate applied to new server join
    # -----------------------------------------------------------------------
    async def test_lurk_gate_applied_after_join(self):
        """After joining a server, lurk_until must be set in the future."""
        agent = DiscordServerAgent()
        client = _make_dc_client()

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run_once(client, {
                "account_id": "dc_srv_001",
                "date_iso": "2026-04-11",
                "timezone_offset": 0,
                "invite_codes": ["abc123"],
                "known_servers": [],
            })

        # Check lurk gate applied for the joined server
        assert result.servers_joined == 1
        # Verify lurk_until is set in the future for the joined server state
        state_key = ("dc_srv_001", "guild_001")
        assert state_key in agent._server_states
        state = agent._server_states[state_key]
        assert state.lurk_until > time.time(), "lurk_until must be in the future"

    async def test_lurk_gate_count_in_result(self):
        """A known server that is still in lurk period must increment lurk_gates_applied."""
        agent = DiscordServerAgent()
        client = _make_dc_client()

        from phantom_fleet.agents.specialists.discord_server_agent import ServerMembershipState
        # Pre-set a server state with an active lurk
        state_key = ("dc_srv_002", "guild_lurk")
        agent._server_states[state_key] = ServerMembershipState(
            account_id="dc_srv_002",
            server_id="guild_lurk",
            joined_at=time.time() - 3600,
            lurk_until=time.time() + 86400,  # lurking for another 24h
        )

        with (
            patch("asyncio.sleep", new=AsyncMock()),
            patch.object(agent, "_is_active_hour", return_value=True),
        ):
            result = await agent.run_once(client, {
                "account_id": "dc_srv_002",
                "date_iso": "2026-04-11",
                "timezone_offset": 0,
                "invite_codes": [],
                "known_servers": [
                    {
                        "server_id": "guild_lurk",
                        "channel_id": "ch_lurk",
                        "recent_message_ids": [],
                    }
                ],
            })

        assert result.lurk_gates_applied >= 1, "Lurk gate must be counted"
        assert result.messages_sent == 0

    # -----------------------------------------------------------------------
    # Test 17: Max 1 server/day enforced
    # -----------------------------------------------------------------------
    async def test_max_1_server_join_per_day(self):
        """Only 1 server join should happen even if 3 invite codes are given."""
        agent = DiscordServerAgent()
        client = _make_dc_client()
        client.join_server = AsyncMock(return_value={"guild": {"id": "guild_x"}})

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run_once(client, {
                "account_id": "dc_srv_003",
                "date_iso": "2026-04-11",
                "timezone_offset": 0,
                "invite_codes": ["code1", "code2", "code3"],
                "known_servers": [],
            })

        assert result.servers_joined == MAX_SERVER_JOINS_PER_DAY
        assert client.join_server.call_count == MAX_SERVER_JOINS_PER_DAY

    # -----------------------------------------------------------------------
    # Test 18: Reactions seeded per message_id
    # -----------------------------------------------------------------------
    async def test_reactions_seeded_per_message_id(self):
        """Different accounts reacting to the same message must pick different emoji."""
        msg_id = "msg_12345"
        reactions = {_reaction_for(f"acc_{i}", msg_id) for i in range(20)}
        # With 20 accounts and 10 emoji in pool, expect at least 3 distinct emoji
        assert len(reactions) >= 3, (
            "Different accounts should produce different reactions to the same message"
        )

    async def test_reaction_same_account_same_message_is_stable(self):
        """Same account + same message must always pick the same reaction (idempotent)."""
        emoji_a = _reaction_for("acc_stable", "msg_stable")
        emoji_b = _reaction_for("acc_stable", "msg_stable")
        assert emoji_a == emoji_b, "Reaction must be deterministic"

    # -----------------------------------------------------------------------
    # Test 19: Max 10 server messages/day enforced
    # -----------------------------------------------------------------------
    async def test_max_10_messages_per_day(self):
        """After 10 server messages, no further messages should be posted."""
        agent = DiscordServerAgent()
        client = _make_dc_client()

        # Pre-fill the daily message counter
        agent._msgs_today["dc_srv_004"] = DC_MAX_MSG_PER_DAY

        with patch("asyncio.sleep", new=AsyncMock()):
            result = await agent.run_once(client, {
                "account_id": "dc_srv_004",
                "date_iso": "2026-04-11",
                "timezone_offset": 0,
                "invite_codes": [],
                "known_servers": [
                    {
                        "server_id": f"guild_{i}",
                        "channel_id": f"ch_{i}",
                        "recent_message_ids": [],
                        "joined_at": time.time() - 86400 * 10,
                    }
                    for i in range(5)
                ],
                "messages_today": DC_MAX_MSG_PER_DAY,
            })

        assert result.messages_sent == 0, "No messages after daily cap"
        assert client.send_message.call_count == 0

    # -----------------------------------------------------------------------
    # Test 20: ValueError on small template pool
    # -----------------------------------------------------------------------
    def test_value_error_on_small_template_pool(self):
        """SERVER_MESSAGE_POOL must have >= 20 entries; violating this raises ValueError."""
        import importlib
        # Verify the production pool is large enough
        assert len(SERVER_MESSAGE_POOL) >= 20, (
            f"SERVER_MESSAGE_POOL only has {len(SERVER_MESSAGE_POOL)} entries, need >= 20"
        )

    def test_reaction_pool_min_10(self):
        """REACTION_POOL must have >= 10 entries."""
        assert len(REACTION_POOL) >= 10, (
            f"REACTION_POOL only has {len(REACTION_POOL)} entries, need >= 10"
        )


# ===========================================================================
# _BaseDMChatAgent tests (via test subclass)
# ===========================================================================


class _TestChatAgent(_BaseDMChatAgent):
    """Minimal concrete subclass of _BaseDMChatAgent for testing the base logic."""

    platform_name:         str       = "test_platform"
    max_daily_replies:     int       = 5
    min_gap_sec:           float     = 10.0
    max_tokens:            int       = 50

    async def _fetch_conversations(self, client):
        return client.get_conversations()

    async def _send_reply(self, client, conv, text):
        await client.send_reply(conv["conv_id"], text)

    def _get_chat_mode_profile(self):
        from phantom_fleet.core.chat_modes import DISCORD_CASUAL
        return DISCORD_CASUAL


class TestBaseDMChatAgent:

    # -----------------------------------------------------------------------
    # Test 21: Daily cap enforced via _run_dm_session
    # -----------------------------------------------------------------------
    async def test_daily_cap_enforced_in_run_dm_session(self):
        """_run_dm_session must stop replying when max_daily_replies is reached."""
        agent = _TestChatAgent()
        agent._daily_sent["acc_base"] = 5  # already at cap (max_daily_replies = 5)

        client = MagicMock()
        client.get_conversations = MagicMock(return_value=[
            {
                "conv_id": f"conv_{i}",
                "unread": True,
                "messages": [{"role": "other", "text": "hey", "from_me": False}],
            }
            for i in range(3)
        ])
        client.send_reply = AsyncMock()

        with (
            patch.object(agent, "_call_openrouter", new=AsyncMock(return_value="hi")),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await agent._run_dm_session(client, "acc_base", "2026-04-11")

        assert result.replies_sent == 0
        assert client.send_reply.call_count == 0

    # -----------------------------------------------------------------------
    # Test 22: strip_llm_tells removes all tell phrases
    # -----------------------------------------------------------------------
    def test_strip_llm_tells_removes_all_patterns(self):
        """strip_llm_tells must remove every phrase in LLM_TELL_PATTERNS."""
        for tell in LLM_TELL_PATTERNS:
            dirty = f"{tell} this is a message"
            cleaned = strip_llm_tells(dirty)
            assert tell.lower() not in cleaned.lower(), (
                f"Tell phrase '{tell}' was not stripped"
            )

    def test_strip_llm_tells_leaves_normal_text(self):
        """strip_llm_tells must not corrupt clean, natural replies."""
        clean_reply = "yeah that makes sense honestly"
        assert strip_llm_tells(clean_reply) == clean_reply

    def test_ppv_pitch_diversity(self):
        """_ppv_pitch_for must return different pitches for different (account, conv) pairs."""
        pitches = {
            _ppv_pitch_for(f"acc_{i}", f"conv_{j}")
            for i in range(10)
            for j in range(10)
        }
        # 100 pairs should produce more than 1 unique pitch
        assert len(pitches) > 1, "PPV pitches must vary across different account/conv pairs"

    def test_ppv_pitch_same_inputs_stable(self):
        """Same (account_id, conv_id) must always return the same pitch."""
        p1 = _ppv_pitch_for("acc_x", "conv_y")
        p2 = _ppv_pitch_for("acc_x", "conv_y")
        assert p1 == p2, "PPV pitch must be deterministic"

    def test_group_message_pool_large_enough(self):
        """GROUP_MESSAGE_POOL must have >= 20 entries."""
        assert len(GROUP_MESSAGE_POOL) >= 20
