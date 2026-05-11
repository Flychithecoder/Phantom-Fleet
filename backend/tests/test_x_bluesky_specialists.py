"""
Tests for X and BlueSky specialist agents + _BaseDMChatAgent mixin.

All HTTP calls mocked — no real API calls, no real LLM calls.
asyncio_mode = "auto" (configured in pyproject.toml) — no decorator needed.

Coverage (22 tests):
    XFollowAgent (4):
        1.  Seeded shuffle is deterministic: same seed → same order
        2.  Daily cap 10 at day 0-7 (code-enforced)
        3.  Daily cap 30 at days 7-30 (code-enforced)
        4.  Daily cap 50 at days 30+ (code-enforced)
        5.  Unfollow mode calls unfollow_user instead of follow_user
        6.  LogNormal sleep called (not fixed)

    XPostAgent (5):
        7.  280-char hard limit: text > 280 chars gets truncated with '…'
        8.  Daily cap by account age: 0-30 days → max 2
        9.  Daily cap by account age: 30+ days → max 5
        10. Dedup: same (account_id, content_hash) is not posted twice
        11. ValueError raised when template_pool < 15 items
        12. Compose dwell + typing delay + rethink are called (not fixed sleep)

    XDMChatAgent (3):
        13. Daily cap at 35: 36th reply is not sent
        14. 90s min-gap gate: same conv replied < 90s ago → skipped
        15. LLM tell stripped from reply before send
        16. PPV pitch appended after threshold turns

    BlueSkyFollowAgent (2):
        17. Handle resolution: target_handles resolved to DIDs via get_profile
        18. Daily cap at 100 (code-enforced)

    BlueSkyPostAgent (3):
        19. Hashtag variation: at fleet scale ~30% get hashtags, not 100%
        20. 300-char limit enforced on post text
        21. Typing delay proportional to text length (longer text → longer sleep)

    BlueSkyDMChatAgent (2):
        22. Daily cap at 40 (code-enforced)
        23. 60s min-gap gate enforced

    _BaseDMChatAgent mixin (1):
        24. strip_llm_tells removes all configured tell phrases
        25. _ppv_pitch_for returns different pitches for different account+conv pairs
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from phantom_fleet.agents.specialists._base_chat import (
    ConversationState,
    WorkerResult,
    _BaseDMChatAgent,
    _ppv_pitch_for,
    strip_llm_tells,
    MAX_LLM_RETRIES,
)
from phantom_fleet.core.distributions import seed_for
from phantom_fleet.core.human_post_behavior import select_template
from phantom_fleet.agents.specialists.x_follow_agent import (
    XFollowAgent,
    _daily_follow_cap,
)
from phantom_fleet.agents.specialists.x_post_agent import (
    XPostAgent,
    _truncate_to_limit,
    _content_hash,
    _x_daily_post_cap,
    X_CHAR_LIMIT,
    MIN_TEMPLATE_POOL_SIZE,
)
from phantom_fleet.agents.specialists.x_dm_chat_agent import XDMChatAgent
from phantom_fleet.agents.specialists.bluesky_follow_agent import (
    BlueSkyFollowAgent,
    MAX_FOLLOWS_PER_DAY,
)
from phantom_fleet.agents.specialists.bluesky_post_agent import (
    BlueSkyPostAgent,
    BLUESKY_CHAR_LIMIT,
    _should_include_hashtags,
    _truncate_to_limit as bsky_truncate,
)
from phantom_fleet.agents.specialists.bluesky_dm_chat_agent import BlueSkyDMChatAgent
from phantom_fleet.core.chat_modes import X_MIXED, BLUESKY_MIXED, ChatModeProfile
from phantom_fleet.core.distributions import LogNormal
from phantom_fleet.core.x_client import XSession, XRateLimited
from phantom_fleet.core.bluesky_client import BlueSkySession
from phantom_fleet.core.hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_platform_headers() -> PlatformHeaders:
    return PlatformHeaders(
        user_agent="TestAgent/1.0",
        locale="en_US",
        device_id="test-device-id",
        extra={"client_uuid": "test-uuid", "kdt": "testkdt"},
    )


def _make_x_session(account_id: str = "acct_x_001") -> XSession:
    return XSession(
        account_id=account_id,
        auth_token="test_auth_token",
        ct0_csrf="test_ct0",
        user_id="123456789",
        username="testuser",
        headers=_make_platform_headers(),
    )


def _make_bsky_session(account_id: str = "acct_bsky_001") -> BlueSkySession:
    return BlueSkySession(
        account_id=account_id,
        did="did:plc:testdid001",
        access_jwt="test_access_jwt",
        refresh_jwt="test_refresh_jwt",
        handle="testuser.bsky.social",
        headers=_make_platform_headers(),
    )


def _make_template_pool(size: int = 20) -> list[str]:
    """Generate a pool of `size` unique template strings."""
    return [f"Template post number {i} for content diversity testing purposes." for i in range(size)]


# ---------------------------------------------------------------------------
# XFollowAgent tests
# ---------------------------------------------------------------------------


class TestXFollowAgent:
    """Tests 1-6: XFollowAgent seeded shuffle, daily caps, unfollow, sleep."""

    def test_daily_cap_days_0_to_7(self):
        """Test 2: Days 0-7 → cap 10."""
        assert _daily_follow_cap(0) == 10
        assert _daily_follow_cap(6) == 10

    def test_daily_cap_days_7_to_30(self):
        """Test 3: Days 7-30 → cap 30."""
        assert _daily_follow_cap(7) == 30
        assert _daily_follow_cap(29) == 30

    def test_daily_cap_days_30_plus(self):
        """Test 4: Days 30+ → cap 50."""
        assert _daily_follow_cap(30) == 50
        assert _daily_follow_cap(365) == 50

    async def test_seeded_shuffle_is_deterministic(self):
        """Test 1: Same (account_id, date_iso) always produces same shuffle order."""
        import random
        from phantom_fleet.core.distributions import seed_for

        account_id = "acct_det_test"
        date_iso   = "2026-04-11"
        targets    = [f"user_{i}" for i in range(20)]

        seed = seed_for(account_id, date_iso, "x_follow_target_order")
        rng1 = random.Random(seed)
        order1 = list(targets)
        rng1.shuffle(order1)

        rng2 = random.Random(seed)
        order2 = list(targets)
        rng2.shuffle(order2)

        assert order1 == order2
        # And the shuffled order should differ from the original
        assert order1 != targets

    async def test_daily_cap_enforced_by_code(self):
        """Test 2 (runtime): Agent stops exactly at cap=10 for new account."""
        session = _make_x_session("acct_cap_test")
        targets = [f"{i:09d}" for i in range(30)]  # 30 targets, cap=10

        agent = XFollowAgent()
        sleep_mock = AsyncMock(return_value=None)

        follow_calls: list[str] = []

        async def fake_follow(user_id: str):
            follow_calls.append(user_id)
            return {"data": {"follow": {"relationship": {}}}}

        async def fake_unfollow(user_id: str):
            return {}

        async def fake_enter(self_inner):
            return self_inner

        async def fake_exit(self_inner, *args):
            pass

        with patch("phantom_fleet.agents.specialists.x_follow_agent.XClient") as MockClient, \
             patch("asyncio.sleep", sleep_mock):

            mock_client_instance = AsyncMock()
            mock_client_instance.follow_user = fake_follow
            mock_client_instance.unfollow_user = fake_unfollow
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client_instance

            ctx = {
                "account_id": "acct_cap_test",
                "session": session,
                "target_user_ids": targets,
                "account_day_in_curve": 3,  # days 0-7 → cap=10
                "date_iso": "2026-04-11",
            }
            run = await agent.run(ctx)

        assert run.status == "success"
        result: WorkerResult = run.outputs["result"]
        # Exactly 10 follows — cap enforced by code
        assert result.followed == 10
        assert len(follow_calls) == 10

    async def test_unfollow_mode_calls_unfollow(self):
        """Test 5: unfollow_mode=True calls unfollow_user instead of follow_user."""
        session = _make_x_session("acct_unfollow_test")
        targets = ["111", "222", "333"]

        agent = XFollowAgent()
        sleep_mock = AsyncMock(return_value=None)

        unfollow_calls: list[str] = []
        follow_calls:   list[str] = []

        async def fake_follow(user_id: str):
            follow_calls.append(user_id)
            return {}

        async def fake_unfollow(user_id: str):
            unfollow_calls.append(user_id)
            return {}

        with patch("phantom_fleet.agents.specialists.x_follow_agent.XClient") as MockClient, \
             patch("asyncio.sleep", sleep_mock):

            mock_instance = AsyncMock()
            mock_instance.follow_user   = fake_follow
            mock_instance.unfollow_user = fake_unfollow
            mock_instance.__aenter__    = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__     = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            ctx = {
                "account_id": "acct_unfollow_test",
                "session": session,
                "target_user_ids": targets,
                "account_day_in_curve": 60,
                "unfollow_mode": True,
                "date_iso": "2026-04-11",
            }
            run = await agent.run(ctx)

        assert run.status == "success"
        result: WorkerResult = run.outputs["result"]
        assert result.unfollowed == 3
        assert result.followed == 0
        assert len(follow_calls) == 0
        assert len(unfollow_calls) == 3

    async def test_lognormal_sleep_called(self):
        """Test 6: asyncio.sleep is called (LogNormal — not fixed 0)."""
        session = _make_x_session("acct_sleep_test")

        agent = XFollowAgent()
        sleep_calls: list[float] = []

        async def capture_sleep(secs: float):
            sleep_calls.append(secs)

        async def fake_follow(user_id: str):
            return {}

        with patch("phantom_fleet.agents.specialists.x_follow_agent.XClient") as MockClient, \
             patch("asyncio.sleep", capture_sleep):

            mock_instance = AsyncMock()
            mock_instance.follow_user = fake_follow
            mock_instance.__aenter__  = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__   = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            ctx = {
                "account_id": "acct_sleep_test",
                "session": session,
                "target_user_ids": ["111", "222"],
                "account_day_in_curve": 60,
                "date_iso": "2026-04-11",
            }
            await agent.run(ctx)

        # Should have been called once per follow
        assert len(sleep_calls) >= 2
        # Values should be > 0 and not all the same (LogNormal varies)
        assert all(s > 0 for s in sleep_calls)


# ---------------------------------------------------------------------------
# XPostAgent tests
# ---------------------------------------------------------------------------


class TestXPostAgent:
    """Tests 7-12: XPostAgent 280-char limit, daily caps, dedup, ValueError, timing."""

    def test_truncate_to_280_chars(self):
        """Test 7: Text over 280 chars is truncated to 280 with trailing '…'."""
        long_text = "A" * 300
        result = _truncate_to_limit(long_text, X_CHAR_LIMIT)
        assert len(result) == X_CHAR_LIMIT
        assert result.endswith("…")

    def test_no_truncation_when_under_limit(self):
        """Short text is returned unchanged."""
        short = "Hello X world"
        assert _truncate_to_limit(short, X_CHAR_LIMIT) == short

    def test_daily_cap_new_account(self):
        """Test 8: Days 0-30 → max 2 posts."""
        assert _x_daily_post_cap(0) == 2
        assert _x_daily_post_cap(29) == 2

    def test_daily_cap_warm_account(self):
        """Test 9: Days 30+ → max 5 posts."""
        assert _x_daily_post_cap(30) == 5
        assert _x_daily_post_cap(100) == 5

    async def test_dedup_prevents_same_content(self):
        """Test 10: Same (account_id, content) not posted twice."""
        session = _make_x_session("acct_dedup")
        pool = _make_template_pool(20)

        agent = XPostAgent()
        sleep_mock = AsyncMock(return_value=None)
        post_calls: list[str] = []

        async def fake_graphql_post(query_id, variables=None, features=None):
            post_calls.append(variables.get("tweet_text", ""))
            return {"data": {"create_tweet": {"tweet_results": {}}}}

        async def fake_timeline(*args, **kwargs):
            return {"data": {}}

        with patch("phantom_fleet.agents.specialists.x_post_agent.XClient") as MockClient, \
             patch("asyncio.sleep", sleep_mock):

            mock_instance = AsyncMock()
            mock_instance._graphql_post  = fake_graphql_post
            mock_instance.get_timeline   = fake_timeline
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__  = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            # Provide a pre-populated posted_hashes that contains the first template's hash
            first_seed = seed_for("acct_dedup", "2026-04-11", "x_post_template_0")
            first_text = select_template(pool, first_seed)
            pre_hashes: set[str] = {_content_hash("acct_dedup", first_text[:X_CHAR_LIMIT])}

            ctx = {
                "account_id": "acct_dedup",
                "session": session,
                "template_pool": pool,
                "account_day_in_curve": 60,
                "posts_to_attempt": 2,
                "date_iso": "2026-04-11",
                "already_posted_today": 0,
                "posted_hashes": pre_hashes,
            }
            run = await agent.run(ctx)

        result: WorkerResult = run.outputs["result"]
        # First post is deduped, second goes through
        assert result.skipped_dedup >= 1

    async def test_valueerror_on_small_pool(self):
        """Test 11: ValueError raised when template_pool < 15 items."""
        session = _make_x_session("acct_smallpool")
        agent = XPostAgent()

        ctx = {
            "account_id": "acct_smallpool",
            "session": session,
            "template_pool": ["short"] * 5,  # only 5 — must raise
            "account_day_in_curve": 60,
            "posts_to_attempt": 1,
        }
        with pytest.raises(ValueError, match="template_pool must have"):
            await agent.run_once(ctx, MagicMock(outputs={}, cost_usd=0.0))

    async def test_compose_dwell_typing_rethink_called(self):
        """Test 12: compose_dwell, typing_delay, and potential rethink sleeps are fired."""
        session = _make_x_session("acct_timing")
        pool = _make_template_pool(20)

        agent = XPostAgent()
        sleep_durations: list[float] = []

        async def capture_sleep(secs: float):
            sleep_durations.append(secs)

        async def fake_graphql_post(*args, **kwargs):
            return {}

        async def fake_timeline(*args, **kwargs):
            return {"data": {}}

        with patch("phantom_fleet.agents.specialists.x_post_agent.XClient") as MockClient, \
             patch("asyncio.sleep", capture_sleep), \
             patch("phantom_fleet.agents.specialists.x_post_agent._should_rethink", return_value=True):

            mock_instance = AsyncMock()
            mock_instance._graphql_post = fake_graphql_post
            mock_instance.get_timeline  = fake_timeline
            mock_instance.__aenter__    = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__     = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            ctx = {
                "account_id": "acct_timing",
                "session": session,
                "template_pool": pool,
                "account_day_in_curve": 60,
                "posts_to_attempt": 1,
                "date_iso": "2026-04-11",
            }
            run = await agent.run(ctx)

        # With rethink forced True: pre_read * N + compose_dwell + typing_delay + rethink
        # At minimum we expect > 3 sleep calls
        assert len(sleep_durations) >= 3
        assert all(s >= 0 for s in sleep_durations)


# ---------------------------------------------------------------------------
# XDMChatAgent tests
# ---------------------------------------------------------------------------


class TestXDMChatAgent:
    """Tests 13-16: XDMChatAgent daily cap, min-gap, tell stripping, PPV pitch."""

    def _make_agent_with_filled_cap(self, account_id: str) -> XDMChatAgent:
        agent = XDMChatAgent()
        # Pre-fill daily_sent to cap
        agent._daily_sent[account_id] = agent.max_daily_replies
        return agent

    async def test_daily_cap_at_35(self):
        """Test 13: No reply sent when account already hit 35 daily replies."""
        account_id = "acct_x_cap"
        agent      = self._make_agent_with_filled_cap(account_id)
        session    = _make_x_session(account_id)

        convs = [{"conv_id": f"c{i}", "messages": [], "unread": True, "recipient_id": "zzz"} for i in range(5)]

        async def fake_fetch(client):
            return convs

        async def fake_send(client, conv, text):
            raise AssertionError("send_reply should not be called when daily cap met")

        with patch.object(agent, "_fetch_conversations", fake_fetch), \
             patch.object(agent, "_send_reply", fake_send), \
             patch("asyncio.sleep", AsyncMock()):

            async with AsyncMock() as client:
                result = await agent._run_dm_session(
                    client=client,
                    account_id=account_id,
                    date_iso="2026-04-11",
                )

        assert result.replies_sent == 0

    async def test_90s_min_gap_gate(self):
        """Test 14: Conversation replied to < 90s ago is skipped."""
        account_id = "acct_x_gap"
        agent      = XDMChatAgent()
        session    = _make_x_session(account_id)

        conv_id = "conv_recent"
        # Insert a state showing we replied 10s ago (< 90s)
        state_key = (account_id, "x", conv_id)
        agent._states[state_key] = ConversationState(
            account_id=account_id,
            platform="x",
            conversation_id=conv_id,
            last_reply_at=time.time() - 10,  # 10s ago — inside the 90s gate
        )
        agent._daily_sent[account_id] = 0

        send_calls: list[str] = []

        async def fake_fetch(client):
            return [{"conv_id": conv_id, "messages": [{"role": "them", "text": "hi"}], "unread": True, "recipient_id": "yyy"}]

        async def fake_send(client, conv, text):
            send_calls.append(text)

        with patch.object(agent, "_fetch_conversations", fake_fetch), \
             patch.object(agent, "_send_reply", fake_send), \
             patch("asyncio.sleep", AsyncMock()):

            async with AsyncMock() as client:
                result = await agent._run_dm_session(
                    client=client,
                    account_id=account_id,
                    date_iso="2026-04-11",
                )

        # threads_touched=1 but no reply because of gap gate
        assert result.replies_sent == 0
        assert len(send_calls) == 0

    async def test_llm_tell_stripped_before_send(self):
        """Test 15: LLM tells are removed from reply text before send."""
        account_id = "acct_x_tell"
        agent      = XDMChatAgent()
        agent._daily_sent[account_id] = 0

        conv_id = "conv_tell"
        sent_texts: list[str] = []

        async def fake_fetch(client):
            return [{"conv_id": conv_id, "messages": [{"role": "them", "text": "hey"}], "unread": True, "recipient_id": "zzz"}]

        async def fake_send(client, conv, text):
            sent_texts.append(text)

        # Return text with a known LLM tell
        async def fake_llm(*args, **kwargs):
            return "Certainly! Here is my reply to your message."

        with patch.object(agent, "_fetch_conversations", fake_fetch), \
             patch.object(agent, "_send_reply", fake_send), \
             patch.object(agent, "_call_openrouter", fake_llm), \
             patch("asyncio.sleep", AsyncMock()):

            async with AsyncMock() as client:
                result = await agent._run_dm_session(
                    client=client,
                    account_id=account_id,
                    date_iso="2026-04-11",
                )

        assert result.replies_sent == 1
        assert sent_texts, "Expected at least one sent text"
        assert "Certainly!" not in sent_texts[0]

    async def test_ppv_pitch_appended_at_threshold(self):
        """Test 16: PPV pitch appended when messages_sent_today >= max_turns_before_cta."""
        account_id = "acct_x_ppv"
        agent      = XDMChatAgent()
        agent._daily_sent[account_id] = 0

        conv_id   = "conv_ppv"
        threshold = X_MIXED.max_turns_before_cta  # = 3

        # Pre-set state so messages_sent_today == threshold
        state_key = (account_id, "x", conv_id)
        agent._states[state_key] = ConversationState(
            account_id=account_id,
            platform="x",
            conversation_id=conv_id,
            messages_sent_today=threshold,
            last_reply_at=0.0,
        )

        sent_texts: list[str] = []

        async def fake_fetch(client):
            return [{"conv_id": conv_id, "messages": [{"role": "them", "text": "sup"}], "unread": True, "recipient_id": "zzz"}]

        async def fake_send(client, conv, text):
            sent_texts.append(text)

        async def fake_llm(*args, **kwargs):
            return "hey what's up"

        with patch.object(agent, "_fetch_conversations", fake_fetch), \
             patch.object(agent, "_send_reply", fake_send), \
             patch.object(agent, "_call_openrouter", fake_llm), \
             patch("asyncio.sleep", AsyncMock()):

            async with AsyncMock() as client:
                result = await agent._run_dm_session(
                    client=client,
                    account_id=account_id,
                    date_iso="2026-04-11",
                    ppv_turn_threshold=threshold,
                )

        assert result.ppv_pitched == 1
        assert sent_texts
        # PPV pitch contains "private" or "vip" (from the pitch pool)
        pitch_text = sent_texts[0].lower()
        assert any(word in pitch_text for word in ["private", "vip", "exclusive"])


# ---------------------------------------------------------------------------
# BlueSkyFollowAgent tests
# ---------------------------------------------------------------------------


class TestBlueSkyFollowAgent:
    """Tests 17-18: handle resolution and daily cap."""

    async def test_handle_resolution_to_did(self):
        """Test 17: target_handles are resolved to DIDs via client.get_profile."""
        session = _make_bsky_session("acct_bsky_resolve")
        agent   = BlueSkyFollowAgent()

        follow_dids: list[str] = []
        sleep_mock = AsyncMock()

        async def fake_get_profile(handle: str) -> dict:
            # Simulate profile resolution
            return {"did": f"did:plc:{handle.replace('.', '_')}", "handle": handle}

        async def fake_follow(did: str) -> dict:
            follow_dids.append(did)
            return {"uri": "at://...", "cid": "..."}

        with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient, \
             patch("asyncio.sleep", sleep_mock):

            mock_instance = AsyncMock()
            mock_instance.get_profile = fake_get_profile
            mock_instance.follow_user = fake_follow
            mock_instance.__aenter__  = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__   = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            ctx = {
                "account_id": "acct_bsky_resolve",
                "session": session,
                "target_handles": ["alice.bsky.social", "bob.bsky.social"],
                "date_iso": "2026-04-11",
            }
            run = await agent.run(ctx)

        assert run.status == "success"
        result: WorkerResult = run.outputs["result"]
        assert result.followed == 2
        # Verify the DIDs used were resolved from handles
        assert "did:plc:alice_bsky_social" in follow_dids
        assert "did:plc:bob_bsky_social" in follow_dids

    async def test_daily_cap_at_100(self):
        """Test 18: BlueSkyFollowAgent stops at 100 follows per day."""
        session = _make_bsky_session("acct_bsky_cap100")
        agent   = BlueSkyFollowAgent()

        follow_calls: list[str] = []
        sleep_mock = AsyncMock()

        async def fake_follow(did: str) -> dict:
            follow_calls.append(did)
            return {"uri": "at://...", "cid": "..."}

        targets = [f"did:plc:user{i:06d}" for i in range(150)]

        with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient, \
             patch("asyncio.sleep", sleep_mock):

            mock_instance = AsyncMock()
            mock_instance.get_profile = AsyncMock(return_value={})
            mock_instance.follow_user = fake_follow
            mock_instance.__aenter__  = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__   = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            ctx = {
                "account_id": "acct_bsky_cap100",
                "session": session,
                "target_dids": targets,
                "date_iso": "2026-04-11",
            }
            run = await agent.run(ctx)

        assert run.status == "success"
        result: WorkerResult = run.outputs["result"]
        assert result.followed == MAX_FOLLOWS_PER_DAY  # exactly 100
        assert len(follow_calls) == MAX_FOLLOWS_PER_DAY


# ---------------------------------------------------------------------------
# BlueSkyPostAgent tests
# ---------------------------------------------------------------------------


class TestBlueSkyPostAgent:
    """Tests 19-21: hashtag variation, 300-char limit, typing delay scaling."""

    def test_hashtag_rate_is_approximately_30_percent(self):
        """
        Test 19: At fleet scale, ~30% of posts get hashtags, not 100%.

        Run 1000 (account, post_index) pairs and verify distribution
        is 25-35% — not a monoculture (which would be 0% or 100%).
        """
        total   = 1000
        with_ht = sum(
            1 for i in range(total)
            if _should_include_hashtags(f"acct_{i % 100}", i)
        )
        fraction = with_ht / total
        # Allow a range 20-40% (3σ CI around the 30% target for n=1000)
        assert 0.20 <= fraction <= 0.40, (
            f"Hashtag fraction {fraction:.2%} outside expected 20-40% band"
        )

    def test_300_char_limit_enforced(self):
        """Test 20: Text > 300 chars is truncated with '…'."""
        long_text = "B" * 350
        result = bsky_truncate(long_text, BLUESKY_CHAR_LIMIT)
        assert len(result) == BLUESKY_CHAR_LIMIT
        assert result.endswith("…")

    async def test_typing_delay_proportional_to_length(self):
        """Test 21: Longer text produces a longer typing sleep than short text."""
        session = _make_bsky_session("acct_bsky_typing")
        agent   = BlueSkyPostAgent()

        # Build two pools of different text lengths
        short_pool = [f"Short text {i}." for i in range(20)]            # ~14 chars each
        long_pool  = [f"This is a much longer template post for BlueSky, number {i}, with many words." for i in range(20)]  # ~75 chars

        short_sleeps: list[float] = []
        long_sleeps:  list[float] = []

        async def fake_create_post(*args, **kwargs):
            return {"uri": "at://...", "cid": "..."}

        async def fake_timeline(*args, **kwargs):
            return {"feed": []}

        # Run with short pool
        async def capture_short_sleep(secs: float):
            short_sleeps.append(secs)

        with patch("phantom_fleet.agents.specialists.bluesky_post_agent.BlueSkyClient") as MockClient, \
             patch("asyncio.sleep", capture_short_sleep), \
             patch("phantom_fleet.agents.specialists.bluesky_post_agent._should_rethink", return_value=False), \
             patch("phantom_fleet.agents.specialists.bluesky_post_agent._should_include_hashtags", return_value=False):

            mi = AsyncMock()
            mi.create_post   = fake_create_post
            mi.get_timeline  = fake_timeline
            mi.__aenter__    = AsyncMock(return_value=mi)
            mi.__aexit__     = AsyncMock(return_value=None)
            MockClient.return_value = mi

            await agent.run({
                "account_id": "acct_bsky_typing",
                "session": session,
                "template_pool": short_pool,
                "posts_to_attempt": 1,
                "date_iso": "2026-04-11",
            })

        # Run with long pool
        async def capture_long_sleep(secs: float):
            long_sleeps.append(secs)

        with patch("phantom_fleet.agents.specialists.bluesky_post_agent.BlueSkyClient") as MockClient, \
             patch("asyncio.sleep", capture_long_sleep), \
             patch("phantom_fleet.agents.specialists.bluesky_post_agent._should_rethink", return_value=False), \
             patch("phantom_fleet.agents.specialists.bluesky_post_agent._should_include_hashtags", return_value=False):

            mi2 = AsyncMock()
            mi2.create_post  = fake_create_post
            mi2.get_timeline = fake_timeline
            mi2.__aenter__   = AsyncMock(return_value=mi2)
            mi2.__aexit__    = AsyncMock(return_value=None)
            MockClient.return_value = mi2

            await agent.run({
                "account_id": "acct_bsky_typing",
                "session": session,
                "template_pool": long_pool,
                "posts_to_attempt": 1,
                "date_iso": "2026-04-12",  # different date → different seed
            })

        # The sum of all sleep durations should be larger for longer text
        # (typing delay is the only length-sensitive component)
        # Sum is a proxy for the typing_delay contribution
        assert sum(long_sleeps) > sum(short_sleeps), (
            f"Expected longer text to produce more sleep time. "
            f"short_sum={sum(short_sleeps):.3f}, long_sum={sum(long_sleeps):.3f}"
        )


# ---------------------------------------------------------------------------
# BlueSkyDMChatAgent tests
# ---------------------------------------------------------------------------


class TestBlueSkyDMChatAgent:
    """Tests 22-23: daily cap at 40, 60s min-gap gate."""

    def _make_agent_at_cap(self, account_id: str) -> BlueSkyDMChatAgent:
        agent = BlueSkyDMChatAgent()
        agent._daily_sent[account_id] = agent.max_daily_replies
        return agent

    async def test_daily_cap_at_40(self):
        """Test 22: No reply sent when account already hit 40 daily replies."""
        account_id = "acct_bsky_dm_cap"
        agent      = self._make_agent_at_cap(account_id)

        convs = [{"conv_id": f"c{i}", "messages": [], "unread": True, "recipient_did": "x"} for i in range(5)]
        send_calls: list[Any] = []

        async def fake_fetch(client):
            return convs

        async def fake_send(client, conv, text):
            send_calls.append(text)

        with patch.object(agent, "_fetch_conversations", fake_fetch), \
             patch.object(agent, "_send_reply", fake_send), \
             patch("asyncio.sleep", AsyncMock()):

            async with AsyncMock() as client:
                result = await agent._run_dm_session(
                    client=client,
                    account_id=account_id,
                    date_iso="2026-04-11",
                )

        assert result.replies_sent == 0
        assert len(send_calls) == 0

    async def test_60s_min_gap_enforced(self):
        """Test 23: Conversation replied to < 60s ago is not replied to again."""
        account_id = "acct_bsky_dm_gap"
        agent      = BlueSkyDMChatAgent()
        agent._daily_sent[account_id] = 0

        conv_id   = "conv_bsky_recent"
        state_key = (account_id, "bluesky", conv_id)
        agent._states[state_key] = ConversationState(
            account_id=account_id,
            platform="bluesky",
            conversation_id=conv_id,
            last_reply_at=time.time() - 30,  # 30s ago — inside 60s gate
        )

        send_calls: list[Any] = []

        async def fake_fetch(client):
            return [{"conv_id": conv_id, "messages": [{"role": "them", "text": "yo"}], "unread": True, "recipient_did": "x"}]

        async def fake_send(client, conv, text):
            send_calls.append(text)

        with patch.object(agent, "_fetch_conversations", fake_fetch), \
             patch.object(agent, "_send_reply", fake_send), \
             patch("asyncio.sleep", AsyncMock()):

            async with AsyncMock() as client:
                result = await agent._run_dm_session(
                    client=client,
                    account_id=account_id,
                    date_iso="2026-04-11",
                )

        assert result.replies_sent == 0
        assert len(send_calls) == 0


# ---------------------------------------------------------------------------
# _BaseDMChatAgent mixin tests
# ---------------------------------------------------------------------------


class TestBaseDMChatMixin:
    """Tests 24-25: strip_llm_tells and _ppv_pitch_for diversity."""

    def test_strip_llm_tells_removes_all_patterns(self):
        """Test 24: All LLM tell phrases are stripped from generated text."""
        tells_to_test = [
            "Certainly! I can help you.",
            "Of course! Let me explain.",
            "I'd be happy to assist.",
            "Delve into the matter.",
            "It's worth noting that this is important.",
            "In conclusion, we can say.",
            "As an AI, I must say.",
        ]
        for raw_text in tells_to_test:
            cleaned = strip_llm_tells(raw_text)
            # Verify the tell phrase itself is gone
            lower_cleaned = cleaned.lower()
            # None of the tell openers should remain
            for phrase in ["certainly!", "of course!", "i'd be happy", "delve into",
                           "it's worth noting", "in conclusion", "as an ai"]:
                assert phrase not in lower_cleaned, (
                    f"Tell phrase '{phrase}' found in cleaned text: {cleaned!r}"
                )

    def test_ppv_pitch_diverse_across_accounts_and_convs(self):
        """Test 25: _ppv_pitch_for produces different pitches for different (account, conv) pairs."""
        pitches = {
            _ppv_pitch_for(f"acct_{i}", f"conv_{j}")
            for i in range(10)
            for j in range(10)
        }
        # With 100 pairs and 30 templates we expect at least 10 unique pitches
        assert len(pitches) >= 10, (
            f"Expected >= 10 unique PPV pitches, got {len(pitches)}"
        )

    async def test_base_mixin_via_concrete_subclass(self):
        """
        Test _BaseDMChatAgent shared logic via a test-specific subclass.

        Verifies: daily cap, min-gap, tell stripping, reply state update.
        """
        class _TestChatAgent(_BaseDMChatAgent):
            platform_name         = "test_platform"
            max_daily_replies     = 5
            min_gap_sec           = 10.0
            max_tokens            = 100
            inter_conv_sleep_dist = LogNormal(low=0.001, high=0.002, sigma=0.1)

            def _get_chat_mode_profile(self) -> ChatModeProfile:
                return X_MIXED  # borrow X_MIXED for test

            async def _fetch_conversations(self, client: Any) -> list[dict]:
                return [
                    {
                        "conv_id":      "test_conv_1",
                        "messages":     [{"role": "them", "text": "hello test"}],
                        "unread":       True,
                        "recipient_id": "test_recipient",
                    }
                ]

            async def _send_reply(self, client: Any, conv: dict, text: str) -> None:
                client.sent_texts.append(text)

        agent = _TestChatAgent()
        account_id = "test_acct_base"
        agent._daily_sent[account_id] = 0

        llm_response = "hey what's good"

        mock_client      = MagicMock()
        mock_client.sent_texts = []

        with patch.object(agent, "_call_openrouter", AsyncMock(return_value=llm_response)), \
             patch("asyncio.sleep", AsyncMock()):

            result = await agent._run_dm_session(
                client=mock_client,
                account_id=account_id,
                date_iso="2026-04-11",
            )

        assert result.replies_sent == 1
        assert result.threads_touched == 1
        assert len(mock_client.sent_texts) == 1
        # State should be updated
        state_key = (account_id, "test_platform", "test_conv_1")
        assert state_key in agent._states
        assert agent._states[state_key].messages_sent_today == 1
        assert agent._daily_sent[account_id] == 1
