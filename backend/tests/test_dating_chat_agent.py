"""
Tests for DatingChatAgent and DatingChatSessionManager.

All HTTP calls mocked — no real LLM calls, no real dating API calls.

Coverage:
    1.  Tinder happy path: inbox → conversation → reply sent
    2.  Bumble happy path: connections → chat → reply sent
    3.  Hinge happy path: matches → conversation → reply sent
    4.  Grindr happy path: inbox → conversation → reply sent (typing indicator)
    5.  Daily account cap (50 msgs) stops processing
    6.  Per-conversation daily cap (10 msgs) skips conversation
    7.  Min 60s gate between replies to same conversation
    8.  Banned phrase in LLM output → retry with new reply
    9.  handoff_mode == "real_human" → AI skipped, conversation flagged
    10. PPV pitch appended at correct message threshold
    11. LLM error all 3 attempts → skip conversation, log error, no crash
    12. Anti-LLM-tell stripping ("Certainly!" removed from output)
    13. ConversationState save + load JSON sidecar round-trip
    14. ChatSessionReport totals are correct across accounts
    15. LogNormal sleep called (not asyncio.sleep with fixed arg)
    16. Concurrent semaphore limits to 3 simultaneous accounts
    17. Per-account style seed produces style-hint variation
    18. Escalation flag set at correct message threshold
    19. Grindr typing indicator endpoint called before send
    20. No crash when platform session raises SessionExpired
    21. Tinder: no reply sent when latest message is from our account
    22. Hinge: verification required → no crash, returns empty records
    23. _strip_llm_tells removes all configured tells
    24. _ppv_pitch_for returns diverse pitches across different account+conv pairs
    25. ChatSessionReport per_account dict populated correctly
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from phantom_fleet.agents.specialists.dating_chat_agent import (
    MAX_MESSAGES_PER_ACCOUNT_PER_DAY,
    MAX_MESSAGES_PER_CONVERSATION_PER_DAY,
    MIN_SECONDS_BETWEEN_REPLIES,
    ConversationState,
    DatingChatAgent,
    ChatReplyRecord,
    LLM_TELL_PATTERNS,
    _normalize_tinder_messages,
    _normalize_bumble_messages,
    _normalize_hinge_messages,
    _normalize_grindr_messages,
    _ppv_pitch_for,
    _strip_llm_tells,
    _tinder_has_unread_inbound,
    _hinge_has_unread_inbound,
    load_conversation_states,
    save_conversation_states,
    _sidecar_path,
)
from phantom_fleet.agents.specialists.dating_chat_session_manager import (
    ChatSessionReport,
    DatingChatSessionManager,
    MAX_CONCURRENT_ACCOUNTS,
)
from phantom_fleet.core.chat_modes import (
    DATING_PRE_CTA_FLIRTY,
    GRINDR_NSFW,
    ChatTier,
)
from phantom_fleet.core.grindr_client import GrindrSessionExpired
from phantom_fleet.core.tinder_client import TinderSessionExpired
from phantom_fleet.core.hinge_client import HingeVerificationRequired
from phantom_fleet.core.bumble_client import BumbleSessionExpired


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def set_openrouter_key(monkeypatch):
    """All tests in this module mock HTTP but still need the env var set."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")


def _make_tinder_session(user_id: str = "tinder_user_001") -> MagicMock:
    sess = MagicMock()
    sess.user_id = user_id
    sess.auth_token = "tok_tinder"
    sess.account_id = "acct_001"
    sess.is_valid = True
    sess.headers = MagicMock()
    return sess


def _make_bumble_session(user_id: str = "bumble_user_001") -> MagicMock:
    sess = MagicMock()
    sess.user_id = user_id
    sess.token = "tok_bumble"
    sess.account_id = "acct_001"
    sess.is_valid = True
    sess.headers = MagicMock()
    return sess


def _make_hinge_session(user_id: str = "hinge_user_001") -> MagicMock:
    sess = MagicMock()
    sess.user_id = user_id
    sess.auth_token = "tok_hinge"
    sess.account_id = "acct_001"
    sess.is_valid = True
    sess.headers = MagicMock()
    return sess


def _make_grindr_session(profile_id: str = "grindr_profile_001") -> MagicMock:
    sess = MagicMock()
    sess.profile_id = profile_id
    sess.user_id = profile_id
    sess.auth_token = "tok_grindr"
    sess.account_id = "acct_001"
    sess.is_valid = True
    sess.headers = MagicMock()
    return sess


def _fake_openrouter_response(reply: str = "hey how's it going?") -> MagicMock:
    """Return a mock httpx response that looks like an OpenRouter response."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": reply}}]
    }
    return mock_resp


# ---------------------------------------------------------------------------
# 1. Tinder happy path
# ---------------------------------------------------------------------------


async def test_tinder_happy_path_reply_sent(tmp_path, monkeypatch):
    """Tinder: inbox → conversation → reply sent successfully."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_tinder_session(user_id="me_001")
    agent = DatingChatAgent()

    matches_resp = {
        "data": {
            "matches": [{
                "id": "match_abc",
                "person": {"name": "Alex", "_id": "them_001"},
                "messages": [
                    {"from": "them_001", "message": "hey there!"},
                ],
            }]
        }
    }
    messages_resp = {
        "data": {
            "messages": [
                {"from_id": "them_001", "message": "hey there!"},
            ]
        }
    }

    mock_openrouter_resp = _fake_openrouter_response("hey! how are you?")

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_matches = AsyncMock(return_value=matches_resp)
        mock_client.get_messages = AsyncMock(return_value=messages_resp)
        mock_client.send_message = AsyncMock(return_value={"id": "msg_001"})
        MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_001",
            platforms={"tinder": session},
            date_iso="2026-04-11",
        )

    assert len(records) == 1
    assert records[0].platform == "tinder"
    assert records[0].conversation_id == "match_abc"
    assert records[0].reply_text == "hey! how are you?"
    mock_client.send_message.assert_awaited_once_with("match_abc", "hey! how are you?")


# ---------------------------------------------------------------------------
# 2. Bumble happy path
# ---------------------------------------------------------------------------


async def test_bumble_happy_path_reply_sent(tmp_path, monkeypatch):
    """Bumble: connections → chat → reply sent."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_bumble_session(user_id="me_bumble")
    agent = DatingChatAgent()

    connections_resp = {
        "connections": [{
            "connection_id": "conn_bb1",
            "uid": "conn_bb1",
            "unread_count": 1,
            "user": {"name": "Jordan"},
        }]
    }
    chat_resp = {
        "messages": [
            {"sender_id": "them_bb", "body": "hi! saw your profile"},
        ]
    }
    mock_openrouter_resp = _fake_openrouter_response("thanks, you look fun too")

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.BumbleClient") as MockBumble,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_connections = AsyncMock(return_value=connections_resp)
        mock_client.get_chat = AsyncMock(return_value=chat_resp)
        mock_client.send_message = AsyncMock(return_value={"id": "msg_bumble_001"})
        MockBumble.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockBumble.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_001",
            platforms={"bumble": session},
            date_iso="2026-04-11",
        )

    assert len(records) == 1
    assert records[0].platform == "bumble"
    assert records[0].conversation_id == "conn_bb1"


# ---------------------------------------------------------------------------
# 3. Hinge happy path
# ---------------------------------------------------------------------------


async def test_hinge_happy_path_reply_sent(tmp_path, monkeypatch):
    """Hinge: matches → conversation → reply sent."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_hinge_session(user_id="me_hinge")
    agent = DatingChatAgent()

    matches_resp = {
        "matches": [{
            "match_id": "hmatch_001",
            "subject": {"display_name": "Sam"},
            "conversation": {
                "messages": [
                    {"sender_id": "them_hinge", "body": "love your prompt answer"},
                ]
            },
        }]
    }
    conv_resp = {
        "messages": [
            {"sender_id": "them_hinge", "body": "love your prompt answer"},
        ]
    }
    mock_openrouter_resp = _fake_openrouter_response("aww thanks! what made you swipe?")

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.HingeClient") as MockHinge,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_matches = AsyncMock(return_value=matches_resp)
        mock_client.get_conversation = AsyncMock(return_value=conv_resp)
        mock_client.send_message = AsyncMock(return_value={"message_id": "hmsg_001"})
        MockHinge.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockHinge.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_001",
            platforms={"hinge": session},
            date_iso="2026-04-11",
        )

    assert len(records) == 1
    assert records[0].platform == "hinge"
    assert records[0].conversation_id == "hmatch_001"


# ---------------------------------------------------------------------------
# 4. Grindr happy path + typing indicator
# ---------------------------------------------------------------------------


async def test_grindr_happy_path_and_typing_indicator(tmp_path, monkeypatch):
    """Grindr: inbox → conversation → typing indicator fired → reply sent."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_grindr_session(profile_id="me_grindr")
    agent = DatingChatAgent()

    inbox_resp = {
        "conversations": [{
            "conversationId": "gconv_001",
            "displayName": "Marco",
            "unreadCount": 1,
        }]
    }
    conv_resp = {
        "messages": [
            {"senderId": "them_grindr", "body": "sup"},
        ]
    }
    mock_openrouter_resp = _fake_openrouter_response("not much, you?")
    typing_resp: dict = {}

    typing_call_count = []

    async def _mock_post(endpoint, json=None, v4=False):
        if "typing" in endpoint:
            typing_call_count.append(1)
            return typing_resp
        return {"id": "gmsg_001"}

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.GrindrClient") as MockGrindr,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_inbox = AsyncMock(return_value=inbox_resp)
        mock_client.get_conversation = AsyncMock(return_value=conv_resp)
        mock_client.send_message = AsyncMock(return_value={"id": "gmsg_001"})
        mock_client._post = AsyncMock(side_effect=_mock_post)
        MockGrindr.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockGrindr.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_001",
            platforms={"grindr": session},
            date_iso="2026-04-11",
        )

    assert len(records) == 1
    assert records[0].platform == "grindr"
    # Typing indicator must have been called
    assert len(typing_call_count) >= 1, "Typing indicator was not called"


# ---------------------------------------------------------------------------
# 5. Daily account cap enforcement
# ---------------------------------------------------------------------------


async def test_daily_account_cap_stops_at_50(tmp_path, monkeypatch):
    """Hard cap: no more than 50 messages sent per account per day."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    # Pre-populate state: already sent 50 messages today across existing convs
    date_iso = "2026-04-11"
    account_id = "acct_cap"
    state = ConversationState(
        conversation_id="conv_existing",
        platform="tinder",
        account_id=account_id,
        messages_sent_today=50,
    )
    sidecar: dict = {("acct_cap", "tinder", "conv_existing"): state}

    with patch(
        "phantom_fleet.agents.specialists.dating_chat_agent.load_conversation_states",
        return_value=sidecar,
    ):
        session = _make_tinder_session()
        agent = DatingChatAgent()

        with (
            patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
            patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        ):
            mock_client = AsyncMock()
            mock_client.get_matches = AsyncMock(return_value={"data": {"matches": []}})
            MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

            records = await agent.run_session(
                account_id=account_id,
                platforms={"tinder": session},
                date_iso=date_iso,
            )

    # Cap was already reached — no new sends
    assert len(records) == 0
    mock_client.get_matches.assert_not_awaited()


# ---------------------------------------------------------------------------
# 6. Per-conversation daily cap
# ---------------------------------------------------------------------------


async def test_per_conversation_daily_cap_skips(tmp_path, monkeypatch):
    """Per-conversation cap of 10 msgs/day: skip when already at cap."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    date_iso = "2026-04-11"
    account_id = "acct_conv_cap"
    match_id = "match_at_cap"

    state = ConversationState(
        conversation_id=match_id,
        platform="tinder",
        account_id=account_id,
        messages_sent_today=MAX_MESSAGES_PER_CONVERSATION_PER_DAY,
    )

    with patch(
        "phantom_fleet.agents.specialists.dating_chat_agent.load_conversation_states",
        return_value={(account_id, "tinder", match_id): state},
    ):
        session = _make_tinder_session(user_id="me_001")
        agent = DatingChatAgent()

        matches_resp = {
            "data": {
                "matches": [{
                    "id": match_id,
                    "person": {"name": "Pat", "_id": "them_001"},
                    "messages": [{"from": "them_001", "message": "hello again"}],
                }]
            }
        }
        messages_resp = {
            "data": {"messages": [{"from_id": "them_001", "message": "hello again"}]}
        }

        with (
            patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
            patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
            patch("httpx.AsyncClient"),
        ):
            mock_client = AsyncMock()
            mock_client.get_matches = AsyncMock(return_value=matches_resp)
            mock_client.get_messages = AsyncMock(return_value=messages_resp)
            mock_client.send_message = AsyncMock()
            MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

            records = await agent.run_session(
                account_id=account_id,
                platforms={"tinder": session},
                date_iso=date_iso,
            )

    assert len(records) == 0
    mock_client.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# 7. Min 60s gate between replies
# ---------------------------------------------------------------------------


async def test_min_60s_gate_between_replies(tmp_path, monkeypatch):
    """A conversation replied to 30s ago must be skipped."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    date_iso = "2026-04-11"
    account_id = "acct_gate"
    match_id = "match_gate"

    # last_reply_at set to 30s ago (well under 60s minimum)
    recent_reply_ts = time.monotonic() - 30.0
    state = ConversationState(
        conversation_id=match_id,
        platform="tinder",
        account_id=account_id,
        messages_sent_today=1,
        last_reply_at=recent_reply_ts,
    )

    with patch(
        "phantom_fleet.agents.specialists.dating_chat_agent.load_conversation_states",
        return_value={(account_id, "tinder", match_id): state},
    ):
        session = _make_tinder_session(user_id="me_001")
        agent = DatingChatAgent()

        matches_resp = {
            "data": {
                "matches": [{
                    "id": match_id,
                    "person": {"name": "Sam", "_id": "them_001"},
                    "messages": [{"from": "them_001", "message": "hi"}],
                }]
            }
        }
        messages_resp = {
            "data": {"messages": [{"from_id": "them_001", "message": "hi"}]}
        }

        with (
            patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
            patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
            patch("httpx.AsyncClient"),
        ):
            mock_client = AsyncMock()
            mock_client.get_matches = AsyncMock(return_value=matches_resp)
            mock_client.get_messages = AsyncMock(return_value=messages_resp)
            mock_client.send_message = AsyncMock()
            MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

            records = await agent.run_session(
                account_id=account_id,
                platforms={"tinder": session},
                date_iso=date_iso,
            )

    assert len(records) == 0
    mock_client.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# 8. Banned phrase detection → retry
# ---------------------------------------------------------------------------


async def test_banned_phrase_triggers_retry(tmp_path, monkeypatch):
    """LLM output containing a banned phrase triggers a retry; clean reply succeeds."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_tinder_session(user_id="me_001")
    agent = DatingChatAgent()

    matches_resp = {
        "data": {
            "matches": [{
                "id": "match_ban",
                "person": {"name": "Jo"},
                "messages": [{"from": "them_001", "message": "sup"}],
            }]
        }
    }
    messages_resp = {"data": {"messages": [{"from_id": "them_001", "message": "sup"}]}}

    # First call returns a banned phrase; second call returns a clean reply
    banned_resp = _fake_openrouter_response("hey, let's sext sometime")  # "sext" is banned
    clean_resp = _fake_openrouter_response("not much, you?")

    call_count = []

    async def _mock_post(*args, **kwargs):
        call_count.append(1)
        if len(call_count) == 1:
            return banned_resp
        return clean_resp

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_matches = AsyncMock(return_value=matches_resp)
        mock_client.get_messages = AsyncMock(return_value=messages_resp)
        mock_client.send_message = AsyncMock(return_value={"id": "msg_ok"})
        MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock(side_effect=_mock_post)
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_ban",
            platforms={"tinder": session},
            date_iso="2026-04-11",
        )

    # Clean reply was sent after retry
    assert len(records) == 1
    assert records[0].reply_text == "not much, you?"
    assert len(call_count) == 2  # two LLM calls made


# ---------------------------------------------------------------------------
# 9. handoff_mode == "real_human" → skip AI, flag conversation
# ---------------------------------------------------------------------------


async def test_human_handoff_skips_ai_and_flags_conversation(tmp_path, monkeypatch):
    """When profile.handoff_mode == 'real_human', no LLM call is made."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    # Patch DATING_PRE_CTA_FLIRTY to have handoff_mode = "real_human"
    from phantom_fleet.core.chat_modes import DATING_PRE_CTA_FLIRTY as base_profile
    from dataclasses import replace

    human_profile = replace(base_profile, handoff_mode="real_human")

    session = _make_tinder_session(user_id="me_001")
    agent = DatingChatAgent()
    action_log: list[dict] = []

    matches_resp = {
        "data": {
            "matches": [{
                "id": "match_handoff",
                "person": {"name": "Casey"},
                "messages": [{"from": "them_001", "message": "hi"}],
            }]
        }
    }
    messages_resp = {"data": {"messages": [{"from_id": "them_001", "message": "hi"}]}}

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
        patch("phantom_fleet.agents.specialists.dating_chat_agent._select_profile", return_value=human_profile),
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_matches = AsyncMock(return_value=matches_resp)
        mock_client.get_messages = AsyncMock(return_value=messages_resp)
        mock_client.send_message = AsyncMock()
        MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_handoff",
            platforms={"tinder": session},
            date_iso="2026-04-11",
            action_log=action_log,
        )

    assert len(records) == 0
    mock_client.send_message.assert_not_awaited()
    mock_http_instance.post.assert_not_awaited()

    handoff_events = [e for e in action_log if e.get("event") == "human_handoff_flagged"]
    assert len(handoff_events) == 1
    assert handoff_events[0]["conversation_id"] == "match_handoff"


# ---------------------------------------------------------------------------
# 10. PPV pitch at correct threshold
# ---------------------------------------------------------------------------


async def test_ppv_pitch_appended_at_threshold(tmp_path, monkeypatch):
    """PPV pitch is appended once max_turns_before_cta threshold is reached."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    date_iso = "2026-04-11"
    account_id = "acct_ppv"
    match_id = "match_ppv"

    # DATING_PRE_CTA_FLIRTY.max_turns_before_cta == 4
    # Set messages_sent_today to 3 + messages_received to 0 → total_exchanges=3 → threshold met
    state = ConversationState(
        conversation_id=match_id,
        platform="tinder",
        account_id=account_id,
        messages_sent_today=3,
        messages_received_today=0,
    )

    with patch(
        "phantom_fleet.agents.specialists.dating_chat_agent.load_conversation_states",
        return_value={(account_id, "tinder", match_id): state},
    ):
        session = _make_tinder_session(user_id="me_001")
        agent = DatingChatAgent()

        matches_resp = {
            "data": {
                "matches": [{
                    "id": match_id,
                    "person": {"name": "Drew"},
                    "messages": [{"from": "them_001", "message": "you seem fun"}],
                }]
            }
        }
        messages_resp = {"data": {"messages": [{"from_id": "them_001", "message": "you seem fun"}]}}

        mock_openrouter_resp = _fake_openrouter_response("thanks, you too!")

        with (
            patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
            patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
            patch("httpx.AsyncClient") as MockHTTP,
        ):
            mock_client = AsyncMock()
            mock_client.get_matches = AsyncMock(return_value=matches_resp)
            mock_client.get_messages = AsyncMock(return_value=messages_resp)
            mock_client.send_message = AsyncMock(return_value={"id": "msg_ppv"})
            MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

            records = await agent.run_session(
                account_id=account_id,
                platforms={"tinder": session},
                date_iso=date_iso,
            )

    assert len(records) == 1
    assert records[0].ppv_pitched is True
    # The sent text should contain the AI reply + a PPV pitch
    sent_args = mock_client.send_message.call_args[0]
    sent_text = sent_args[1]
    assert "thanks, you too!" in sent_text
    # PPV pitch is one of the templates — verify a newline separator
    assert "\n\n" in sent_text


# ---------------------------------------------------------------------------
# 11. LLM error all 3 attempts → skip conversation, log error, no crash
# ---------------------------------------------------------------------------


async def test_llm_all_retries_fail_skips_and_logs(tmp_path, monkeypatch):
    """When all 3 LLM attempts raise, conversation is skipped cleanly."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_tinder_session(user_id="me_001")
    agent = DatingChatAgent()
    action_log: list[dict] = []

    matches_resp = {
        "data": {
            "matches": [{
                "id": "match_fail",
                "person": {"name": "Lex"},
                "messages": [{"from": "them_001", "message": "hi"}],
            }]
        }
    }
    messages_resp = {"data": {"messages": [{"from_id": "them_001", "message": "hi"}]}}

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_matches = AsyncMock(return_value=matches_resp)
        mock_client.get_messages = AsyncMock(return_value=messages_resp)
        mock_client.send_message = AsyncMock()
        MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock(side_effect=Exception("LLM timeout"))
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        # Should not raise
        records = await agent.run_session(
            account_id="acct_fail",
            platforms={"tinder": session},
            date_iso="2026-04-11",
            action_log=action_log,
        )

    assert len(records) == 0
    mock_client.send_message.assert_not_awaited()

    skip_events = [e for e in action_log if e.get("event") == "conversation_skipped_llm_failure"]
    assert len(skip_events) == 1

    llm_errors = [e for e in action_log if e.get("event") == "llm_error"]
    assert len(llm_errors) == 3  # one per retry attempt


# ---------------------------------------------------------------------------
# 12. Anti-LLM-tell stripping
# ---------------------------------------------------------------------------


def test_strip_llm_tells_removes_all_tells():
    """All LLM detection tells must be stripped from generated text."""
    raw = "Certainly! I'd be happy to help. Delve into what's happening with you?"
    stripped = _strip_llm_tells(raw)

    assert "Certainly!" not in stripped
    assert "I'd be happy to" not in stripped
    assert "Delve into" not in stripped
    # Actual content should remain
    assert "help" in stripped or "happening" in stripped


def test_strip_llm_tells_case_insensitive():
    """Tell stripping must be case-insensitive."""
    raw = "of course! As an AI, in conclusion I would say hi"
    stripped = _strip_llm_tells(raw)
    assert "of course!" not in stripped.lower()
    assert "as an ai" not in stripped.lower()
    assert "in conclusion" not in stripped.lower()


# ---------------------------------------------------------------------------
# 13. ConversationState persistence — save/load JSON sidecar
# ---------------------------------------------------------------------------


def test_conversation_state_save_and_load(tmp_path, monkeypatch):
    """States saved to sidecar must be loadable and equal."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    account_id = "acct_persist"
    date_iso = "2026-04-11"

    original_states: dict = {
        (account_id, "tinder", "match_aaa"): ConversationState(
            conversation_id="match_aaa",
            platform="tinder",
            account_id=account_id,
            messages_sent_today=3,
            messages_received_today=2,
            last_reply_at=1234567890.0,
            chat_tier=ChatTier.FLIRTY_SFW,
            ppv_pitched=True,
        ),
        (account_id, "grindr", "gconv_bbb"): ConversationState(
            conversation_id="gconv_bbb",
            platform="grindr",
            account_id=account_id,
            messages_sent_today=7,
            chat_tier=ChatTier.NSFW,
        ),
    }

    save_conversation_states(account_id, date_iso, original_states)
    loaded = load_conversation_states(account_id, date_iso)

    assert len(loaded) == 2

    tinder_key = (account_id, "tinder", "match_aaa")
    assert tinder_key in loaded
    s = loaded[tinder_key]
    assert s.messages_sent_today == 3
    assert s.ppv_pitched is True
    assert s.last_reply_at == 1234567890.0

    grindr_key = (account_id, "grindr", "gconv_bbb")
    assert grindr_key in loaded
    assert loaded[grindr_key].chat_tier == ChatTier.NSFW


# ---------------------------------------------------------------------------
# 14. ChatSessionReport totals correct
# ---------------------------------------------------------------------------


async def test_chat_session_report_totals(tmp_path, monkeypatch):
    """Manager aggregates per-account results into correct report totals."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    manager = DatingChatSessionManager()

    # Patch run_session to return known records for each account
    async def _fake_run_session(account_id, platforms, chat_tier, date_iso, action_log):
        if account_id == "acct_a":
            return [
                ChatReplyRecord("acct_a", "tinder", "conv_1", "hey", 3, False, "2026-04-11T00:00:00+00:00"),
                ChatReplyRecord("acct_a", "tinder", "conv_2", "sup", 3, True, "2026-04-11T00:00:01+00:00"),
            ]
        elif account_id == "acct_b":
            return [
                ChatReplyRecord("acct_b", "bumble", "conv_3", "hi", 3, False, "2026-04-11T00:00:02+00:00"),
            ]
        return []

    with patch.object(DatingChatAgent, "run_session", side_effect=_fake_run_session):
        report = await manager.run_all_accounts(
            accounts=[
                {"account_id": "acct_a", "chat_tier": ChatTier.FLIRTY_SFW, "sessions": {"tinder": MagicMock()}},
                {"account_id": "acct_b", "chat_tier": ChatTier.FLIRTY_SFW, "sessions": {"bumble": MagicMock()}},
            ],
            date_iso="2026-04-11",
        )

    assert report.accounts_processed == 2
    assert report.total_replies_sent == 3
    assert report.ppv_pitches_made == 1
    assert report.total_conversations_touched == 3
    assert len(report.errors) == 0


# ---------------------------------------------------------------------------
# 15. LogNormal sleep called (not fixed sleep)
# ---------------------------------------------------------------------------


async def test_reply_uses_lognormal_sleep_not_fixed(tmp_path, monkeypatch):
    """asyncio.sleep must be called with a non-zero value sampled from LogNormal."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_tinder_session(user_id="me_001")
    agent = DatingChatAgent()

    sleep_values: list[float] = []

    async def _capture_sleep(delay):
        sleep_values.append(delay)

    matches_resp = {
        "data": {
            "matches": [{
                "id": "match_sleep",
                "person": {"name": "Jo"},
                "messages": [{"from": "them_001", "message": "hey"}],
            }]
        }
    }
    messages_resp = {"data": {"messages": [{"from_id": "them_001", "message": "hey"}]}}
    mock_openrouter_resp = _fake_openrouter_response("hey back")

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep", side_effect=_capture_sleep),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_matches = AsyncMock(return_value=matches_resp)
        mock_client.get_messages = AsyncMock(return_value=messages_resp)
        mock_client.send_message = AsyncMock(return_value={"id": "msg_sleep"})
        MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        await agent.run_session(
            account_id="acct_sleep",
            platforms={"tinder": session},
            date_iso="2026-04-11",
        )

    # At least one sleep call should have occurred
    assert len(sleep_values) >= 1
    # All sleep values must be > 0 (never fixed zero sleep)
    for v in sleep_values:
        assert v > 0.0, f"Sleep value {v} is not positive — fixed zero sleep detected"
    # The reply timing sleep should be in a plausible range (15s to 180s per distribution)
    # At least one sleep in that range must exist
    timing_sleeps = [v for v in sleep_values if 1.0 < v < 200.0]
    assert len(timing_sleeps) >= 1


# ---------------------------------------------------------------------------
# 16. Concurrent semaphore limits to 3 simultaneous accounts
# ---------------------------------------------------------------------------


async def test_semaphore_limits_concurrency_to_3(tmp_path, monkeypatch):
    """Session manager never runs more than 3 accounts simultaneously."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    concurrent_count = [0]
    max_observed = [0]

    async def _slow_run_session(account_id, platforms, chat_tier, date_iso, action_log):
        concurrent_count[0] += 1
        max_observed[0] = max(max_observed[0], concurrent_count[0])
        await asyncio.sleep(0.01)  # tiny real sleep to let others start
        concurrent_count[0] -= 1
        return []

    manager = DatingChatSessionManager()
    accounts = [
        {"account_id": f"acct_{i}", "chat_tier": ChatTier.FLIRTY_SFW, "sessions": {"tinder": MagicMock()}}
        for i in range(8)
    ]

    with patch.object(DatingChatAgent, "run_session", side_effect=_slow_run_session):
        await manager.run_all_accounts(accounts, date_iso="2026-04-11")

    assert max_observed[0] <= MAX_CONCURRENT_ACCOUNTS, (
        f"Concurrency exceeded {MAX_CONCURRENT_ACCOUNTS}: observed {max_observed[0]}"
    )


# ---------------------------------------------------------------------------
# 17. Per-account style seed produces different reply styles
# ---------------------------------------------------------------------------


def test_reply_style_seed_varies_by_account_and_conv():
    """Different (account, conv, count) triples must produce diverse style hints."""
    from phantom_fleet.agents.specialists.dating_chat_agent import _reply_style_hint

    hints = set()
    for acct in ["acct_001", "acct_002", "acct_003"]:
        for conv in ["conv_aaa", "conv_bbb", "conv_ccc"]:
            for count in [0, 1, 2, 5, 10]:
                hints.add(_reply_style_hint(acct, conv, count))

    # Across 45 combinations, we should see multiple distinct style hints
    assert len(hints) >= 2, "Style hint is not varying across (account, conv, count) combos"


# ---------------------------------------------------------------------------
# 18. Escalation flag set at correct threshold
# ---------------------------------------------------------------------------


async def test_escalation_flag_set_at_threshold(tmp_path, monkeypatch):
    """Escalation flag is logged when messages_sent_today reaches max_turns_before_cta."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    date_iso = "2026-04-11"
    account_id = "acct_esc"
    match_id = "match_esc"

    # DATING_PRE_CTA_FLIRTY.max_turns_before_cta == 4
    # Set messages_sent_today to exactly 4 so on THIS message we cross the threshold
    state = ConversationState(
        conversation_id=match_id,
        platform="tinder",
        account_id=account_id,
        messages_sent_today=4,
    )

    with patch(
        "phantom_fleet.agents.specialists.dating_chat_agent.load_conversation_states",
        return_value={(account_id, "tinder", match_id): state},
    ):
        session = _make_tinder_session(user_id="me_001")
        agent = DatingChatAgent()
        action_log: list[dict] = []

        matches_resp = {
            "data": {
                "matches": [{
                    "id": match_id,
                    "person": {"name": "Taylor"},
                    "messages": [{"from": "them_001", "message": "still around?"}],
                }]
            }
        }
        messages_resp = {"data": {"messages": [{"from_id": "them_001", "message": "still around?"}]}}
        mock_openrouter_resp = _fake_openrouter_response("yeah! what's up")

        with (
            patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
            patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
            patch("httpx.AsyncClient") as MockHTTP,
        ):
            mock_client = AsyncMock()
            mock_client.get_matches = AsyncMock(return_value=matches_resp)
            mock_client.get_messages = AsyncMock(return_value=messages_resp)
            mock_client.send_message = AsyncMock(return_value={"id": "msg_esc"})
            MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

            await agent.run_session(
                account_id=account_id,
                platforms={"tinder": session},
                date_iso=date_iso,
                action_log=action_log,
            )

    escalation_events = [e for e in action_log if e.get("event") == "escalation_flagged"]
    assert len(escalation_events) >= 1
    assert escalation_events[0]["current_tier"] == int(ChatTier.FLIRTY_SFW)


# ---------------------------------------------------------------------------
# 19. Grindr typing indicator called before send (dedicated test)
# ---------------------------------------------------------------------------


async def test_grindr_typing_indicator_called_before_send(tmp_path, monkeypatch):
    """Grindr typing indicator endpoint must be called before send_message."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_grindr_session(profile_id="me_g")
    agent = DatingChatAgent()

    inbox_resp = {
        "conversations": [{
            "conversationId": "gconv_typing",
            "displayName": "Ryan",
            "unreadCount": 1,
        }]
    }
    conv_resp = {"messages": [{"senderId": "them_g", "body": "hey"}]}
    mock_openrouter_resp = _fake_openrouter_response("hey!")

    call_order: list[str] = []

    async def _tracked_post(endpoint, json=None, v4=False):
        if "typing" in endpoint:
            call_order.append("typing")
            return {}
        return {"id": "gmsg_typing"}

    async def _tracked_send_message(conv_id, text, msg_type="Text"):
        call_order.append("send")
        return {"id": "gmsg_typing"}

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.GrindrClient") as MockGrindr,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
        patch("httpx.AsyncClient") as MockHTTP,
    ):
        mock_client = AsyncMock()
        mock_client.get_inbox = AsyncMock(return_value=inbox_resp)
        mock_client.get_conversation = AsyncMock(return_value=conv_resp)
        mock_client._post = AsyncMock(side_effect=_tracked_post)
        mock_client.send_message = AsyncMock(side_effect=_tracked_send_message)
        MockGrindr.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockGrindr.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = AsyncMock()
        mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
        MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
        MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_gtyping",
            platforms={"grindr": session},
            date_iso="2026-04-11",
        )

    assert len(records) == 1
    # typing must appear before send in call order
    assert "typing" in call_order
    assert "send" in call_order
    typing_idx = call_order.index("typing")
    send_idx = call_order.index("send")
    assert typing_idx < send_idx, "typing indicator was not called before send_message"


# ---------------------------------------------------------------------------
# 20. SessionExpired → no crash, returns empty records
# ---------------------------------------------------------------------------


async def test_tinder_session_expired_no_crash(tmp_path, monkeypatch):
    """TinderSessionExpired during get_matches must be caught gracefully."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_tinder_session()
    agent = DatingChatAgent()

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.TinderClient") as MockTinder,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
    ):
        mock_client = AsyncMock()
        mock_client.get_matches = AsyncMock(side_effect=TinderSessionExpired("expired"))
        MockTinder.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockTinder.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_expired",
            platforms={"tinder": session},
            date_iso="2026-04-11",
        )

    assert records == []


# ---------------------------------------------------------------------------
# 21. Tinder: no reply when latest message is from our account
# ---------------------------------------------------------------------------


def test_tinder_has_unread_inbound_false_when_last_msg_is_ours():
    """_tinder_has_unread_inbound returns False when we sent the last message."""
    messages = [
        {"from": "me_001", "message": "hey back!"},        # newest-first
        {"from": "them_001", "message": "hey"},
    ]
    assert _tinder_has_unread_inbound(messages, our_user_id="me_001") is False


def test_tinder_has_unread_inbound_true_when_last_msg_is_theirs():
    """_tinder_has_unread_inbound returns True when the match sent the last message."""
    messages = [
        {"from": "them_001", "message": "still there?"},   # newest-first
        {"from": "me_001", "message": "hey"},
    ]
    assert _tinder_has_unread_inbound(messages, our_user_id="me_001") is True


# ---------------------------------------------------------------------------
# 22. Hinge verification required → no crash, empty records
# ---------------------------------------------------------------------------


async def test_hinge_verification_required_no_crash(tmp_path, monkeypatch):
    """HingeVerificationRequired on get_matches must be caught gracefully."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    session = _make_hinge_session()
    agent = DatingChatAgent()

    with (
        patch("phantom_fleet.agents.specialists.dating_chat_agent.HingeClient") as MockHinge,
        patch("phantom_fleet.agents.specialists.dating_chat_agent.asyncio.sleep"),
    ):
        mock_client = AsyncMock()
        mock_client.get_matches = AsyncMock(side_effect=HingeVerificationRequired("verify required"))
        MockHinge.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockHinge.return_value.__aexit__ = AsyncMock(return_value=None)

        records = await agent.run_session(
            account_id="acct_hingevfy",
            platforms={"hinge": session},
            date_iso="2026-04-11",
        )

    assert records == []


# ---------------------------------------------------------------------------
# 23. _strip_llm_tells removes all configured tells individually
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tell", LLM_TELL_PATTERNS)
def test_strip_llm_tells_removes_each_tell(tell):
    """Each configured tell must be stripped individually."""
    text = f"{tell} this is a normal message"
    result = _strip_llm_tells(text)
    assert tell.lower() not in result.lower(), (
        f"Tell '{tell}' was not stripped from: {result!r}"
    )


# ---------------------------------------------------------------------------
# 24. _ppv_pitch_for returns diverse pitches
# ---------------------------------------------------------------------------


def test_ppv_pitch_diverse_across_accounts_and_convs():
    """Different (account, conv) pairs must yield diverse PPV pitches at scale."""
    pitches = set()
    for i in range(30):
        pitches.add(_ppv_pitch_for(f"acct_{i:03d}", f"conv_{i:03d}"))

    # With 30 templates and hash-based selection across 30 unique pairs,
    # we expect at least 10 distinct pitches
    assert len(pitches) >= 10, (
        f"PPV pitch diversity is too low: only {len(pitches)} distinct pitches across 30 pairs"
    )


# ---------------------------------------------------------------------------
# 25. ChatSessionReport per_account dict populated correctly
# ---------------------------------------------------------------------------


async def test_chat_session_report_per_account_populated(tmp_path, monkeypatch):
    """per_account dict must have an entry per processed account."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    manager = DatingChatSessionManager()

    async def _fake_run(account_id, platforms, chat_tier, date_iso, action_log):
        return [
            ChatReplyRecord(account_id, "tinder", "conv_x", "hi", 3, True, "2026-04-11T00:00:00+00:00"),
        ]

    with patch.object(DatingChatAgent, "run_session", side_effect=_fake_run):
        report = await manager.run_all_accounts(
            accounts=[
                {"account_id": "acct_x", "chat_tier": ChatTier.FLIRTY_SFW, "sessions": {"tinder": MagicMock()}},
                {"account_id": "acct_y", "chat_tier": ChatTier.FLIRTY_SFW, "sessions": {"tinder": MagicMock()}},
            ],
            date_iso="2026-04-11",
        )

    assert "acct_x" in report.per_account
    assert "acct_y" in report.per_account
    assert report.per_account["acct_x"]["replies_sent"] == 1
    assert report.per_account["acct_x"]["ppv_pitches_made"] == 1
    assert report.ppv_pitches_made == 2
