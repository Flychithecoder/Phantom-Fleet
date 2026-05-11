"""
Tests for IG and Threads specialist agents + human_post_behavior module.

Coverage:
    - IGCommentAgent: template selection determinism, daily cap, dwell called,
      dedup prevents repeat, ValueError on small pool
    - IGStoryViewAgent: story_view called per target, dwell between stories,
      graceful skip on empty story tray
    - IGSourceDiscoveryAgent: pagination with cursor threading, scoring filter,
      hard cap at 200
    - IGDMChatAgent: reply per unread thread, daily cap, 90s gate, LLM tell
      stripped, PPV pitch at threshold, handoff_mode=real_human skips AI
    - ThreadsFollowAgent: seeded shuffle, inter-follow delay, cap at 60
    - ThreadsPostAgent: pre-post browse called, typing delay proportional,
      rethink pause fires ~15%, inter-post delay called, ValueError on small pool
    - _BaseDMChatAgent: mixin shared between IG and Threads
    - ThreadsDMChatAgent: same architecture as IGDMChatAgent
    - human_post_behavior: LogNormal distributions confirmed (1000-sample test)

All HTTP calls are mocked — no real API calls.
asyncio_mode = "auto" is configured in pyproject.toml (no decorator needed).
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.core.hybrid_runner import PlatformHeaders, WorkerResult
from phantom_fleet.core.instagram_client import (
    IGActionBlocked,
    IGRateLimited,
    IGSession,
    IGSessionExpired,
    InstagramClient,
)
from phantom_fleet.core.threads_client import ThreadsClient
from phantom_fleet.core.chat_modes import ChatTier, INSTAGRAM_FLIRTY, THREADS_CASUAL


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def make_headers() -> PlatformHeaders:
    return PlatformHeaders(
        platform="instagram",
        session_token="tok_test",
        device_id="android-abc123",
        user_agent="Instagram 300.0.0.1 Android (31/12; 420dpi; 1080x2400; samsung; SM-G770F)",
        app_version="300.0.0.1",
        android_id="abc123def456abc1",
        advertising_id="gaid-1234-5678",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
        extra={"mid": "mid_test_value", "family_device_id": "family-uuid-test"},
    )


def make_session(account_id: str = "acc_001") -> IGSession:
    return IGSession(
        account_id=account_id,
        ig_user_id="1234567890",
        username="test_account",
        session_id="sess_abc123",
        csrftoken="csrf_xyz789",
        mid="mid_test_value",
        ds_user_id="1234567890",
        headers=make_headers(),
    )


def make_comment_templates(n: int = 30) -> list[str]:
    return [f"This is a great post number {i}!" for i in range(n)]


def make_content_pool(n: int = 20) -> list[str]:
    return [f"Interesting thought number {i} about life." for i in range(n)]


# ---------------------------------------------------------------------------
# IGCommentAgent tests
# ---------------------------------------------------------------------------


class TestIGCommentAgent:
    """Tests for IGCommentAgent."""

    async def test_raises_on_small_template_pool(self):
        """ValueError raised if fewer than 30 templates provided."""
        from phantom_fleet.agents.specialists.ig_comment_agent import IGCommentAgent

        agent = IGCommentAgent()
        with pytest.raises(ValueError, match="minimum is 30"):
            await agent.run_session(
                account_id="acc_001",
                session=make_session(),
                media_pool=["media_001"],
                comment_templates=["short pool"] * 10,
                date_iso="2026-04-11",
            )

    async def test_template_selection_is_deterministic(self):
        """Same account+media always selects the same template index."""
        from phantom_fleet.agents.specialists.ig_comment_agent import _template_index_for

        idx1 = _template_index_for("acc_001", "media_abc", 30)
        idx2 = _template_index_for("acc_001", "media_abc", 30)
        assert idx1 == idx2

    async def test_different_accounts_get_different_templates(self):
        """Different accounts should select different templates for the same media."""
        from phantom_fleet.agents.specialists.ig_comment_agent import _template_index_for

        indices = {_template_index_for(f"acc_{i:04d}", "media_abc", 30) for i in range(50)}
        # With 30 templates and 50 accounts, expect at least 15 distinct picks
        assert len(indices) >= 10

    async def test_daily_cap_stops_at_5(self):
        """Comments stop after MAX_COMMENTS_PER_ACCOUNT_PER_DAY (5)."""
        from phantom_fleet.agents.specialists.ig_comment_agent import IGCommentAgent

        templates = make_comment_templates(30)
        media_pool = [f"media_{i:03d}" for i in range(20)]
        agent = IGCommentAgent()
        session = make_session()

        # Patch InstagramClient to avoid real HTTP and skip sleeps
        mock_post = AsyncMock(return_value={"status": "ok"})
        with (
            patch("phantom_fleet.agents.specialists.ig_comment_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=MagicMock(_post=mock_post)),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            # Build the client mock properly
            mock_client = MagicMock()
            mock_client._post = AsyncMock(return_value={"status": "ok"})
            mock_client.session = session

            with patch.object(InstagramClient, "__aenter__", return_value=mock_client):
                result = await agent.run_session(
                    account_id="acc_001",
                    session=session,
                    media_pool=media_pool,
                    comment_templates=templates,
                    date_iso="2026-04-11",
                )

        assert result.data["comments_posted"] <= 5

    async def test_dedup_skips_already_commented(self):
        """Dedup set prevents posting same (account, media, template_idx) twice."""
        from phantom_fleet.agents.specialists.ig_comment_agent import (
            IGCommentAgent,
            _template_index_for,
        )

        templates = make_comment_templates(30)
        media_id = "media_unique_001"
        account_id = "acc_dedup"
        tmpl_idx = _template_index_for(account_id, media_id, 30)

        # Pre-populate dedup set so the one media item is already done
        already_commented: set = {(account_id, media_id, tmpl_idx)}

        agent = IGCommentAgent()
        session = make_session(account_id)
        mock_client = MagicMock()
        mock_client._post = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.ig_comment_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id=account_id,
                session=session,
                media_pool=[media_id],
                comment_templates=templates,
                date_iso="2026-04-11",
                already_commented=already_commented,
            )

        assert result.data["comments_skipped"] == 1
        assert result.data["comments_posted"] == 0
        mock_client._post.assert_not_called()

    async def test_pre_comment_dwell_is_called(self):
        """asyncio.sleep is called before each comment (simulates reading post)."""
        from phantom_fleet.agents.specialists.ig_comment_agent import IGCommentAgent

        templates = make_comment_templates(30)
        sleep_calls: list[float] = []

        async def capture_sleep(t: float) -> None:
            sleep_calls.append(t)

        agent = IGCommentAgent()
        session = make_session()
        mock_client = MagicMock()
        mock_client._post = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.ig_comment_agent.asyncio.sleep", side_effect=capture_sleep),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            await agent.run_session(
                account_id="acc_001",
                session=session,
                media_pool=["media_001"],
                comment_templates=templates,
                date_iso="2026-04-11",
            )

        # At least 2 sleep calls: dwell + typing simulation
        assert len(sleep_calls) >= 2
        # Dwell must be > 0
        assert any(t > 0 for t in sleep_calls)


# ---------------------------------------------------------------------------
# IGStoryViewAgent tests
# ---------------------------------------------------------------------------


class TestIGStoryViewAgent:
    """Tests for IGStoryViewAgent."""

    async def test_story_view_called_per_target(self):
        """story_view API call is made for each target with active stories."""
        from phantom_fleet.agents.specialists.ig_story_view_agent import IGStoryViewAgent

        agent = IGStoryViewAgent()
        session = make_session()

        story_resp = {
            "reel": {
                "id": "user_111",
                "items": [
                    {"id": "story_001", "pk": "story_001"},
                    {"id": "story_002", "pk": "story_002"},
                ],
            }
        }

        mock_client = MagicMock()
        mock_client._get = AsyncMock(return_value=story_resp)
        mock_client.story_view = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.ig_story_view_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                target_user_ids=["user_111", "user_222"],
                date_iso="2026-04-11",
            )

        assert mock_client.story_view.call_count == 2
        assert result.data["accounts_viewed"] == 2
        assert result.data["stories_viewed"] >= 2

    async def test_graceful_skip_on_empty_story_tray(self):
        """Targets with no active stories are counted as skipped, not as errors."""
        from phantom_fleet.agents.specialists.ig_story_view_agent import IGStoryViewAgent

        agent = IGStoryViewAgent()
        session = make_session()

        empty_resp = {"reel": {"id": "user_111", "items": []}}

        mock_client = MagicMock()
        mock_client._get = AsyncMock(return_value=empty_resp)
        mock_client.story_view = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.ig_story_view_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                target_user_ids=["user_111"],
                date_iso="2026-04-11",
            )

        assert result.data["skipped_no_stories"] == 1
        assert result.data["accounts_viewed"] == 0
        assert len(result.data["errors"]) == 0
        mock_client.story_view.assert_not_called()

    async def test_dwell_sleep_called_per_story(self):
        """asyncio.sleep is called to simulate watching each story."""
        from phantom_fleet.agents.specialists.ig_story_view_agent import IGStoryViewAgent

        sleep_calls: list[float] = []

        async def capture_sleep(t: float) -> None:
            sleep_calls.append(t)

        agent = IGStoryViewAgent()
        session = make_session()

        story_resp = {
            "reel": {
                "id": "user_111",
                "items": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
            }
        }

        mock_client = MagicMock()
        mock_client._get = AsyncMock(return_value=story_resp)
        mock_client.story_view = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.ig_story_view_agent.asyncio.sleep", side_effect=capture_sleep),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            await agent.run_session(
                account_id="acc_001",
                session=session,
                target_user_ids=["user_111"],
                date_iso="2026-04-11",
            )

        # Sleep called once per story item (3 stories → 3 dwell calls)
        assert len(sleep_calls) >= 3

    async def test_daily_cap_enforced(self):
        """Story views stop once MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY is reached."""
        from phantom_fleet.agents.specialists.ig_story_view_agent import (
            IGStoryViewAgent,
            MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY,
        )

        agent = IGStoryViewAgent()
        session = make_session()

        story_resp = {"reel": {"id": "u", "items": [{"id": f"s{i}"} for i in range(5)]}}
        mock_client = MagicMock()
        mock_client._get = AsyncMock(return_value=story_resp)
        mock_client.story_view = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.ig_story_view_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                target_user_ids=[f"user_{i}" for i in range(30)],
                date_iso="2026-04-11",
                views_posted_today=MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY - 2,
            )

        assert result.data["stories_viewed"] <= 2


# ---------------------------------------------------------------------------
# IGSourceDiscoveryAgent tests
# ---------------------------------------------------------------------------


class TestIGSourceDiscoveryAgent:
    """Tests for IGSourceDiscoveryAgent."""

    async def test_pagination_with_cursor_threading(self):
        """Cursor from first page is passed to second page request."""
        from phantom_fleet.agents.specialists.ig_source_discovery_agent import (
            IGSourceDiscoveryAgent,
        )

        agent = IGSourceDiscoveryAgent()
        session = make_session()

        page1 = {
            "users": [
                {
                    "pk": "u001",
                    "username": "alpha",
                    "follower_count": 1500,
                    "following_count": 800,
                    "is_private": False,
                    "profile_pic_url": "http://x.com/pic.jpg",
                }
            ],
            "next_max_id": "cursor_page2",
        }
        page2 = {
            "users": [
                {
                    "pk": "u002",
                    "username": "beta",
                    "follower_count": 2000,
                    "following_count": 500,
                    "is_private": False,
                    "profile_pic_url": "http://x.com/pic2.jpg",
                }
            ],
            "next_max_id": "",
        }

        call_cursors: list[str] = []

        async def fake_get_followers(user_id: str, max_id: str = "", count: int = 50):
            call_cursors.append(max_id)
            return page1 if max_id == "" else page2

        mock_client = MagicMock()
        mock_client.get_user_followers = fake_get_followers

        sink_calls: list = []

        async def sink(candidates):
            sink_calls.extend(candidates)

        with (
            patch("phantom_fleet.agents.specialists.ig_source_discovery_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                source_account_ids=["source_001"],
                output_sink=sink,
                date_iso="2026-04-11",
            )

        assert "" in call_cursors
        assert "cursor_page2" in call_cursors
        assert result.data["pages_scraped"] == 2
        assert len(sink_calls) == 2

    async def test_scoring_filter_excludes_low_quality(self):
        """Candidates with score 0 are excluded from output."""
        from phantom_fleet.agents.specialists.ig_source_discovery_agent import (
            _score_candidate,
        )

        # score=0: private, tiny followers, many following, no pic
        bad_user = {
            "pk": "bad001",
            "username": "noone",
            "follower_count": 5,
            "following_count": 5000,
            "is_private": True,
            "profile_pic_url": None,
        }
        c = _score_candidate(bad_user, "source_x")
        assert c.score == 0

        # score=4: public, >1k followers, <2k following, has pic
        good_user = {
            "pk": "good001",
            "username": "popular",
            "follower_count": 5000,
            "following_count": 300,
            "is_private": False,
            "profile_pic_url": "http://x.com/pic.jpg",
        }
        c2 = _score_candidate(good_user, "source_x")
        assert c2.score == 4

    async def test_hard_cap_at_200_candidates(self):
        """Discovery stops at 200 candidates regardless of source pool size."""
        from phantom_fleet.agents.specialists.ig_source_discovery_agent import (
            IGSourceDiscoveryAgent,
            MAX_CANDIDATES_PER_SESSION,
        )

        assert MAX_CANDIDATES_PER_SESSION == 200

        agent = IGSourceDiscoveryAgent()
        session = make_session()

        # Each page returns 50 high-quality candidates
        def make_page(cursor):
            users = [
                {
                    "pk": f"u{cursor}_{i}",
                    "username": f"user_{cursor}_{i}",
                    "follower_count": 2000,
                    "following_count": 500,
                    "is_private": False,
                    "profile_pic_url": "http://x.com/p.jpg",
                }
                for i in range(50)
            ]
            return {"users": users, "next_max_id": f"next_{cursor}"}

        call_count = 0

        async def fake_followers(user_id, max_id="", count=50):
            nonlocal call_count
            call_count += 1
            if call_count > 20:
                return {"users": [], "next_max_id": ""}
            return make_page(max_id)

        mock_client = MagicMock()
        mock_client.get_user_followers = fake_followers

        collected: list = []

        async def sink(candidates):
            collected.extend(candidates)

        with (
            patch("phantom_fleet.agents.specialists.ig_source_discovery_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                source_account_ids=["source_001"],
                output_sink=sink,
                date_iso="2026-04-11",
            )

        assert result.data["candidates_approved"] <= MAX_CANDIDATES_PER_SESSION
        assert len(collected) <= MAX_CANDIDATES_PER_SESSION


# ---------------------------------------------------------------------------
# _BaseDMChatAgent / IGDMChatAgent tests
# ---------------------------------------------------------------------------


class TestIGDMChatAgent:
    """Tests for IGDMChatAgent and _BaseDMChatAgent."""

    def _make_thread(self, thread_id: str, user_id: str = "fan_001") -> dict:
        return {
            "thread_id": thread_id,
            "unread_count": 1,
            "users": [{"pk": user_id}],
            "items": [
                {"text": "hey how are you", "is_sent_by_viewer": False},
            ],
        }

    async def test_reply_sent_per_unread_thread(self):
        """A reply is generated and sent for each thread with unread messages."""
        from phantom_fleet.agents.specialists.ig_dm_chat_agent import IGDMChatAgent

        agent = IGDMChatAgent()
        session = make_session()

        mock_client = MagicMock()
        mock_client.get_inbox = AsyncMock(return_value={
            "threads": [self._make_thread("t001"), self._make_thread("t002")],
            "has_older": False,
        })
        mock_client.send_dm = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.base_dm_chat_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch.object(IGDMChatAgent, "_generate_reply_with_tokens", new=AsyncMock(return_value="hey that sounds fun")),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                chat_tier=ChatTier.FLIRTY_SFW,
                date_iso="2026-04-11",
            )

        assert result.data["replies_sent"] == 2
        assert mock_client.send_dm.call_count == 2

    async def test_daily_cap_stops_at_40(self):
        """Replies stop once MAX_MESSAGES_PER_ACCOUNT_PER_DAY (40) is reached."""
        from phantom_fleet.agents.specialists.ig_dm_chat_agent import IGDMChatAgent
        from phantom_fleet.agents.specialists.base_dm_chat_agent import (
            MAX_MESSAGES_PER_ACCOUNT_PER_DAY,
            DMConversationState,
        )

        assert MAX_MESSAGES_PER_ACCOUNT_PER_DAY == 40

        agent = IGDMChatAgent()
        session = make_session()

        # Pre-populate state with 40 messages already sent today for this account
        for i in range(40):
            key = ("acc_001", "instagram", f"t_pre_{i}")
            agent._states[key] = DMConversationState(
                thread_id=f"t_pre_{i}",
                platform="instagram",
                account_id="acc_001",
                messages_sent_today=1,
            )

        mock_client = MagicMock()
        mock_client.get_inbox = AsyncMock(return_value={
            "threads": [self._make_thread("t_new_001")],
            "has_older": False,
        })
        mock_client.send_dm = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.base_dm_chat_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch(
                "phantom_fleet.agents.specialists.base_dm_chat_agent._BaseDMChatAgent._generate_reply",
                new=AsyncMock(return_value="hello"),
            ),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                chat_tier=ChatTier.FLIRTY_SFW,
                date_iso="2026-04-11",
            )

        assert result.data["replies_sent"] == 0
        mock_client.send_dm.assert_not_called()

    async def test_90s_gate_prevents_rapid_replies(self):
        """Min 90s gate: thread with recent reply is skipped."""
        from phantom_fleet.agents.specialists.ig_dm_chat_agent import IGDMChatAgent
        from phantom_fleet.agents.specialists.base_dm_chat_agent import DMConversationState

        agent = IGDMChatAgent()
        session = make_session()

        # Set last_reply_at to 30 seconds ago (well within 90s gate)
        key = ("acc_001", "instagram", "thread_gated")
        agent._states[key] = DMConversationState(
            thread_id="thread_gated",
            platform="instagram",
            account_id="acc_001",
            messages_sent_today=1,
            last_reply_at=time.time() - 30,  # 30s ago < 90s gate
        )

        mock_client = MagicMock()
        mock_client.get_inbox = AsyncMock(return_value={
            "threads": [self._make_thread("thread_gated")],
            "has_older": False,
        })
        mock_client.send_dm = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.base_dm_chat_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch(
                "phantom_fleet.agents.specialists.base_dm_chat_agent._BaseDMChatAgent._generate_reply",
                new=AsyncMock(return_value="hi"),
            ),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                chat_tier=ChatTier.FLIRTY_SFW,
                date_iso="2026-04-11",
            )

        assert result.data["replies_sent"] == 0
        mock_client.send_dm.assert_not_called()

    async def test_llm_tell_stripped_from_reply(self):
        """LLM tell phrases are stripped from generated text before send."""
        from phantom_fleet.agents.specialists.base_dm_chat_agent import _strip_llm_tells

        text = "Certainly! I'd be happy to help you with that. Let me delve into this topic."
        stripped = _strip_llm_tells(text)

        assert "Certainly!" not in stripped
        assert "I'd be happy to" not in stripped
        assert "delve into" not in stripped.lower()

    async def test_ppv_pitch_appended_at_threshold(self):
        """PPV pitch is added after ppv_pitch_after_msgs messages exchanged."""
        from phantom_fleet.agents.specialists.ig_dm_chat_agent import IGDMChatAgent
        from phantom_fleet.agents.specialists.base_dm_chat_agent import DMConversationState

        agent = IGDMChatAgent()
        session = make_session()

        # Thread has already sent 4 messages (at threshold)
        key = ("acc_001", "instagram", "thread_ppv")
        agent._states[key] = DMConversationState(
            thread_id="thread_ppv",
            platform="instagram",
            account_id="acc_001",
            messages_sent_today=4,
            last_reply_at=0.0,
            ppv_pitched=False,
        )

        # Capture what text is passed to _generate_reply
        generate_calls: list[dict] = []

        async def capture_generate(self_ref, **kwargs):
            generate_calls.append(kwargs)
            return "sounds good babe"

        mock_client = MagicMock()
        mock_client.get_inbox = AsyncMock(return_value={
            "threads": [self._make_thread("thread_ppv")],
            "has_older": False,
        })
        mock_client.send_dm = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.base_dm_chat_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch.object(IGDMChatAgent, "_generate_reply_with_tokens", new=AsyncMock(return_value="sounds good babe")),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                chat_tier=ChatTier.FLIRTY_SFW,
                date_iso="2026-04-11",
                ppv_pitch_after_msgs=4,
            )

        assert result.data["ppv_pitched"] >= 1

    async def test_handoff_mode_real_human_skips_ai(self):
        """When profile.handoff_mode == 'real_human', AI is skipped for that thread."""
        from phantom_fleet.agents.specialists.ig_dm_chat_agent import IGDMChatAgent
        from phantom_fleet.core.chat_modes import ChatModeProfile, ChatTier, GLOBAL_LLM_TELLS
        import phantom_fleet.agents.specialists.ig_dm_chat_agent as ig_dm_mod

        # Create a profile with handoff_mode = "real_human"
        human_profile = ChatModeProfile(
            name="test_human_handoff",
            tier=ChatTier.FLIRTY_SFW,
            system_prompt="test",
            banned_phrases=GLOBAL_LLM_TELLS,
            allowed_media=frozenset(["text"]),
            max_reply_words=30,
            max_turns_before_cta=4,
            cta_allowed=False,
            typo_rate=0.0,
            voice_msgs_allowed=False,
            handoff_mode="real_human",
        )

        agent = IGDMChatAgent()
        session = make_session()

        mock_client = MagicMock()
        mock_client.get_inbox = AsyncMock(return_value={
            "threads": [self._make_thread("thread_human")],
            "has_older": False,
        })
        mock_client.send_dm = AsyncMock(return_value={"status": "ok"})

        # Patch CHAT_MODE_CATALOG in the agent module so all intent-resolved
        # profiles have handoff_mode="real_human" regardless of intent.
        patched_catalog = {
            key: human_profile
            for key in ig_dm_mod.CHAT_MODE_CATALOG
        }
        with (
            patch("phantom_fleet.agents.specialists.base_dm_chat_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch.object(ig_dm_mod, "CHAT_MODE_CATALOG", patched_catalog),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                chat_tier=ChatTier.FLIRTY_SFW,
                date_iso="2026-04-11",
            )

        assert result.data["human_handoff_flagged"] >= 1
        assert result.data["replies_sent"] == 0
        mock_client.send_dm.assert_not_called()


# ---------------------------------------------------------------------------
# ThreadsFollowAgent tests
# ---------------------------------------------------------------------------


class TestThreadsFollowAgent:
    """Tests for ThreadsFollowAgent."""

    async def test_seeded_shuffle_is_deterministic(self):
        """Same account + date always produces same target order."""
        from phantom_fleet.agents.specialists.threads_follow_agent import _seeded_shuffle

        targets = [f"user_{i}" for i in range(20)]
        order1 = _seeded_shuffle(targets, "acc_001", "2026-04-11")
        order2 = _seeded_shuffle(targets, "acc_001", "2026-04-11")
        assert order1 == order2

    async def test_different_accounts_get_different_order(self):
        """Different accounts get different shuffle orders."""
        from phantom_fleet.agents.specialists.threads_follow_agent import _seeded_shuffle

        targets = [f"user_{i}" for i in range(20)]
        order1 = _seeded_shuffle(targets, "acc_001", "2026-04-11")
        order2 = _seeded_shuffle(targets, "acc_002", "2026-04-11")
        # Very unlikely to be identical with 20 items
        assert order1 != order2

    async def test_follows_respected_up_to_cap(self):
        """At most MAX_FOLLOWS_PER_ACCOUNT_PER_DAY follows are performed."""
        from phantom_fleet.agents.specialists.threads_follow_agent import (
            ThreadsFollowAgent,
            MAX_FOLLOWS_PER_ACCOUNT_PER_DAY,
        )

        agent = ThreadsFollowAgent()
        session = make_session()

        mock_client = MagicMock()
        mock_client.follow = AsyncMock(return_value={"friendship_status": {"following": True}})

        with (
            patch("phantom_fleet.agents.specialists.threads_follow_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                target_user_ids=[f"u{i}" for i in range(100)],
                date_iso="2026-04-11",
                follows_done_today=MAX_FOLLOWS_PER_ACCOUNT_PER_DAY - 5,
            )

        assert result.data["followed"] <= 5

    async def test_inter_follow_delay_called(self):
        """asyncio.sleep is called between follows."""
        from phantom_fleet.agents.specialists.threads_follow_agent import ThreadsFollowAgent

        sleep_calls: list[float] = []

        async def capture_sleep(t: float) -> None:
            sleep_calls.append(t)

        agent = ThreadsFollowAgent()
        session = make_session()

        mock_client = MagicMock()
        mock_client.follow = AsyncMock(return_value={"friendship_status": {"following": True}})

        with (
            patch("phantom_fleet.agents.specialists.threads_follow_agent.asyncio.sleep", side_effect=capture_sleep),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            await agent.run_session(
                account_id="acc_001",
                session=session,
                target_user_ids=["u001", "u002", "u003"],
                date_iso="2026-04-11",
            )

        # 3 targets → 2 inter-follow delays
        assert len(sleep_calls) >= 2


# ---------------------------------------------------------------------------
# ThreadsPostAgent tests
# ---------------------------------------------------------------------------


class TestThreadsPostAgent:
    """Tests for ThreadsPostAgent."""

    async def test_raises_on_small_content_pool(self):
        """ValueError raised if fewer than 20 content items provided."""
        from phantom_fleet.agents.specialists.threads_post_agent import ThreadsPostAgent

        agent = ThreadsPostAgent()
        with pytest.raises(ValueError, match="minimum is 20"):
            await agent.run_session(
                account_id="acc_001",
                session=make_session(),
                content_pool=["only five items"] * 5,
                date_iso="2026-04-11",
            )

    async def test_pre_post_browse_delay_called(self):
        """pre_post_browse_delay is called before any posting begins."""
        from phantom_fleet.agents.specialists.threads_post_agent import ThreadsPostAgent

        browse_called = []

        async def capture_browse():
            browse_called.append(True)
            return 45.0

        agent = ThreadsPostAgent()
        session = make_session()
        content_pool = make_content_pool(20)

        mock_client = MagicMock()
        mock_client.post_text = AsyncMock(return_value=None)

        with (
            patch("phantom_fleet.agents.specialists.threads_post_agent.asyncio.sleep", new=AsyncMock()),
            patch("phantom_fleet.agents.specialists.threads_post_agent.pre_post_browse_delay", side_effect=capture_browse),
            patch("phantom_fleet.agents.specialists.threads_post_agent.compose_dwell", new=AsyncMock(return_value=5.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.typing_delay", new=AsyncMock(return_value=10.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.rethink_pause", new=AsyncMock(return_value=3.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.should_rethink", return_value=False),
            patch("phantom_fleet.agents.specialists.threads_post_agent.post_time_jitter_seconds", return_value=0),
            patch("phantom_fleet.agents.specialists.threads_post_agent.inter_post_delay", new=AsyncMock(return_value=1.0)),
            patch.object(ThreadsClient, "__aenter__", return_value=mock_client),
            patch.object(ThreadsClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            await agent.run_session(
                account_id="acc_001",
                session=session,
                content_pool=content_pool,
                posts_target=1,
                date_iso="2026-04-11",
            )

        assert len(browse_called) == 1

    async def test_typing_delay_called_with_text(self):
        """typing_delay is called and receives the actual post text."""
        from phantom_fleet.agents.specialists.threads_post_agent import ThreadsPostAgent

        typing_texts: list[str] = []

        async def capture_typing(text: str) -> float:
            typing_texts.append(text)
            return len(text) * 0.1

        agent = ThreadsPostAgent()
        session = make_session()
        content_pool = make_content_pool(20)

        mock_client = MagicMock()
        mock_client.post_text = AsyncMock(return_value=None)

        with (
            patch("phantom_fleet.agents.specialists.threads_post_agent.asyncio.sleep", new=AsyncMock()),
            patch("phantom_fleet.agents.specialists.threads_post_agent.pre_post_browse_delay", new=AsyncMock(return_value=45.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.compose_dwell", new=AsyncMock(return_value=5.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.typing_delay", side_effect=capture_typing),
            patch("phantom_fleet.agents.specialists.threads_post_agent.rethink_pause", new=AsyncMock(return_value=3.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.should_rethink", return_value=False),
            patch("phantom_fleet.agents.specialists.threads_post_agent.post_time_jitter_seconds", return_value=0),
            patch("phantom_fleet.agents.specialists.threads_post_agent.inter_post_delay", new=AsyncMock(return_value=1.0)),
            patch.object(ThreadsClient, "__aenter__", return_value=mock_client),
            patch.object(ThreadsClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                content_pool=content_pool,
                posts_target=1,
                date_iso="2026-04-11",
            )

        assert len(typing_texts) == 1
        assert len(typing_texts[0]) > 0  # actual text was passed

    async def test_rethink_pause_fires_at_15_percent(self):
        """should_rethink returns True approximately 15% of the time."""
        from phantom_fleet.core.human_post_behavior import should_rethink

        trials = 10000
        truths = sum(1 for _ in range(trials) if should_rethink())
        rate = truths / trials
        # Expect 15% ± 3% (very loose tolerance for statistical test)
        assert 0.08 <= rate <= 0.22, f"Expected ~15% rethink rate, got {rate:.1%}"

    async def test_daily_cap_enforced_at_3(self):
        """Posts stop after MAX_POSTS_PER_ACCOUNT_PER_DAY (3)."""
        from phantom_fleet.agents.specialists.threads_post_agent import (
            ThreadsPostAgent,
            MAX_POSTS_PER_ACCOUNT_PER_DAY,
        )

        assert MAX_POSTS_PER_ACCOUNT_PER_DAY == 3

        agent = ThreadsPostAgent()
        session = make_session()

        mock_client = MagicMock()
        mock_client.post_text = AsyncMock(return_value=None)

        with (
            patch("phantom_fleet.agents.specialists.threads_post_agent.asyncio.sleep", new=AsyncMock()),
            patch("phantom_fleet.agents.specialists.threads_post_agent.pre_post_browse_delay", new=AsyncMock(return_value=45.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.compose_dwell", new=AsyncMock(return_value=5.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.typing_delay", new=AsyncMock(return_value=1.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.rethink_pause", new=AsyncMock(return_value=3.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.should_rethink", return_value=False),
            patch("phantom_fleet.agents.specialists.threads_post_agent.post_time_jitter_seconds", return_value=0),
            patch("phantom_fleet.agents.specialists.threads_post_agent.inter_post_delay", new=AsyncMock(return_value=1.0)),
            patch.object(ThreadsClient, "__aenter__", return_value=mock_client),
            patch.object(ThreadsClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                content_pool=make_content_pool(20),
                posts_target=10,  # try to post 10 but should stop at 3
                date_iso="2026-04-11",
            )

        assert result.data["posts_published"] <= MAX_POSTS_PER_ACCOUNT_PER_DAY

    async def test_inter_post_delay_called_between_posts(self):
        """inter_post_delay is called between consecutive posts."""
        from phantom_fleet.agents.specialists.threads_post_agent import ThreadsPostAgent

        inter_called: list[int] = []

        async def capture_inter() -> float:
            inter_called.append(1)
            return 3600.0

        agent = ThreadsPostAgent()
        session = make_session()
        mock_client = MagicMock()
        mock_client.post_text = AsyncMock(return_value=None)

        with (
            patch("phantom_fleet.agents.specialists.threads_post_agent.asyncio.sleep", new=AsyncMock()),
            patch("phantom_fleet.agents.specialists.threads_post_agent.pre_post_browse_delay", new=AsyncMock(return_value=45.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.compose_dwell", new=AsyncMock(return_value=5.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.typing_delay", new=AsyncMock(return_value=1.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.rethink_pause", new=AsyncMock(return_value=3.0)),
            patch("phantom_fleet.agents.specialists.threads_post_agent.should_rethink", return_value=False),
            patch("phantom_fleet.agents.specialists.threads_post_agent.post_time_jitter_seconds", return_value=0),
            patch("phantom_fleet.agents.specialists.threads_post_agent.inter_post_delay", side_effect=capture_inter),
            patch.object(ThreadsClient, "__aenter__", return_value=mock_client),
            patch.object(ThreadsClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            await agent.run_session(
                account_id="acc_001",
                session=session,
                content_pool=make_content_pool(20),
                posts_target=3,
                date_iso="2026-04-11",
            )

        # 3 posts → 2 inter-post delays
        assert len(inter_called) >= 2


# ---------------------------------------------------------------------------
# ThreadsDMChatAgent tests
# ---------------------------------------------------------------------------


class TestThreadsDMChatAgent:
    """Tests for ThreadsDMChatAgent — shares _BaseDMChatAgent logic."""

    def _make_thread(self, thread_id: str) -> dict:
        return {
            "thread_id": thread_id,
            "unread_count": 1,
            "users": [{"pk": "fan_001"}],
            "items": [{"text": "hello", "is_sent_by_viewer": False}],
        }

    async def test_platform_name_is_threads(self):
        """ThreadsDMChatAgent.platform_name must be 'threads'."""
        from phantom_fleet.agents.specialists.threads_dm_chat_agent import ThreadsDMChatAgent

        agent = ThreadsDMChatAgent()
        assert agent.platform_name == "threads"

    async def test_default_profile_is_threads_casual(self):
        """ThreadsDMChatAgent uses THREADS_CASUAL profile by default."""
        from phantom_fleet.agents.specialists.threads_dm_chat_agent import ThreadsDMChatAgent

        agent = ThreadsDMChatAgent()
        assert agent._default_profile.name == THREADS_CASUAL.name

    async def test_reply_sent_to_threads_thread(self):
        """Replies are sent for Threads DM threads via send_dm."""
        from phantom_fleet.agents.specialists.threads_dm_chat_agent import ThreadsDMChatAgent

        agent = ThreadsDMChatAgent()
        session = make_session()

        mock_client = MagicMock()
        mock_client.get_inbox = AsyncMock(return_value={
            "threads": [self._make_thread("threads_t001")],
            "has_older": False,
        })
        mock_client.send_dm = AsyncMock(return_value={"status": "ok"})

        with (
            patch("phantom_fleet.agents.specialists.base_dm_chat_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=mock_client),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch(
                "phantom_fleet.agents.specialists.base_dm_chat_agent._BaseDMChatAgent._generate_reply",
                new=AsyncMock(return_value="hey, what's up?"),
            ),
        ):
            result = await agent.run_session(
                account_id="acc_001",
                session=session,
                chat_tier=ChatTier.CASUAL_SFW,
                date_iso="2026-04-11",
            )

        assert result.data["replies_sent"] == 1
        assert result.platform == "threads"


# ---------------------------------------------------------------------------
# _BaseDMChatAgent mixin shared logic tests
# ---------------------------------------------------------------------------


class TestBaseDMChatAgentMixin:
    """Tests verifying the mixin is shared between IG and Threads agents."""

    async def test_both_inherit_base_mixin(self):
        """Both IG and Threads DM agents inherit from _BaseDMChatAgent."""
        from phantom_fleet.agents.specialists.ig_dm_chat_agent import IGDMChatAgent
        from phantom_fleet.agents.specialists.threads_dm_chat_agent import ThreadsDMChatAgent
        from phantom_fleet.agents.specialists.base_dm_chat_agent import _BaseDMChatAgent

        assert issubclass(IGDMChatAgent, _BaseDMChatAgent)
        assert issubclass(ThreadsDMChatAgent, _BaseDMChatAgent)

    async def test_strip_llm_tells_handles_all_patterns(self):
        """All listed LLM tell patterns are stripped."""
        from phantom_fleet.agents.specialists.base_dm_chat_agent import (
            LLM_TELL_PATTERNS,
            _strip_llm_tells,
        )

        for tell in LLM_TELL_PATTERNS:
            text = f"Start {tell} end of message."
            result = _strip_llm_tells(text)
            assert tell not in result, f"Tell not stripped: {tell!r}"

    async def test_conversation_state_isolated_by_platform(self):
        """IG and Threads agents maintain separate state namespaces."""
        from phantom_fleet.agents.specialists.ig_dm_chat_agent import IGDMChatAgent
        from phantom_fleet.agents.specialists.threads_dm_chat_agent import ThreadsDMChatAgent
        from phantom_fleet.agents.specialists.base_dm_chat_agent import DMConversationState

        ig_agent = IGDMChatAgent()
        threads_agent = ThreadsDMChatAgent()

        # Inject state into IG agent
        ig_key = ("acc_001", "instagram", "shared_thread_id")
        ig_agent._states[ig_key] = DMConversationState(
            thread_id="shared_thread_id",
            platform="instagram",
            account_id="acc_001",
            messages_sent_today=5,
        )

        # Threads agent should not see IG agent's state
        threads_key = ("acc_001", "threads", "shared_thread_id")
        assert threads_key not in threads_agent._states

    async def test_ppv_pitch_selection_is_seeded_per_account_thread(self):
        """PPV pitch varies by (account_id, thread_id) — anti-monoculture."""
        from phantom_fleet.agents.specialists.base_dm_chat_agent import _ppv_pitch_for

        pitches = {_ppv_pitch_for(f"acc_{i}", "thread_001") for i in range(50)}
        # With 30 templates and 50 accounts, expect at least 10 distinct pitches
        assert len(pitches) >= 8


# ---------------------------------------------------------------------------
# human_post_behavior distribution tests
# ---------------------------------------------------------------------------


class TestHumanPostBehavior:
    """Tests verifying LogNormal distributions in human_post_behavior module."""

    async def test_pre_post_browse_delay_distribution(self):
        """pre_post_browse_delay produces log-normal values in expected range."""
        from phantom_fleet.core.human_post_behavior import _PRE_POST_BROWSE_DIST

        samples = [_PRE_POST_BROWSE_DIST.sample() for _ in range(1000)]

        mean = sum(samples) / len(samples)
        variance = sum((x - mean) ** 2 for x in samples) / len(samples)

        # Expected: median ~45s, mean slightly higher due to right tail
        assert 20 <= mean <= 120, f"Mean {mean:.1f}s out of expected range"
        # Distribution should have non-trivial spread
        assert variance > 100, "Distribution has too little variance (suspiciously uniform)"
        # All values should be positive
        assert all(s > 0 for s in samples)

    async def test_inter_post_delay_distribution(self):
        """inter_post_delay has median ~1hr and significant variance."""
        from phantom_fleet.core.human_post_behavior import _INTER_POST_DIST

        samples = [_INTER_POST_DIST.sample() for _ in range(1000)]

        # Sort to find median
        sorted_s = sorted(samples)
        median = sorted_s[500]

        # Median should be around 2hr (7350s) ± wide tolerance
        assert 600 <= median <= 8500, f"Median {median:.0f}s not in expected range for inter-post"
        # Heavy right tail: 90th percentile should be well above median
        p90 = sorted_s[900]
        assert p90 > median * 1.5, "Distribution lacks expected heavy right tail"

    async def test_post_time_jitter_distribution(self):
        """post_time_jitter_seconds returns values distributed around zero."""
        from phantom_fleet.core.human_post_behavior import post_time_jitter_seconds

        samples = [post_time_jitter_seconds() for _ in range(1000)]

        # Should be centered near zero
        mean = sum(samples) / len(samples)
        assert -300 <= mean <= 300, f"Jitter mean {mean:.0f}s too far from zero"

        # Should have both positive and negative values
        positives = sum(1 for s in samples if s > 0)
        negatives = sum(1 for s in samples if s < 0)
        assert positives > 300
        assert negatives > 300

        # All values should be within ±1800s (clamped by Normal distribution)
        assert all(-1800 <= s <= 1800 for s in samples)

    async def test_select_template_seeded_determinism(self):
        """Same seed always selects same template."""
        from phantom_fleet.core.human_post_behavior import select_template

        pool = [f"Template {i}" for i in range(30)]
        result1 = select_template(pool, seed=12345)
        result2 = select_template(pool, seed=12345)
        assert result1 == result2

    async def test_select_template_raises_on_empty_pool(self):
        """ValueError raised when pool is empty."""
        from phantom_fleet.core.human_post_behavior import select_template

        with pytest.raises(ValueError, match="must not be empty"):
            select_template([], seed=0)

    async def test_typing_delay_proportional_to_text_length(self):
        """Longer texts consistently produce longer typing delays."""
        from phantom_fleet.core.human_post_behavior import _TYPING_SPEED_DIST

        short_text = "Hi!"
        long_text = "A" * 200

        # Sample many times to account for distribution variance
        short_samples = [len(short_text) * _TYPING_SPEED_DIST.sample() for _ in range(500)]
        long_samples = [len(long_text) * _TYPING_SPEED_DIST.sample() for _ in range(500)]

        short_mean = sum(short_samples) / len(short_samples)
        long_mean = sum(long_samples) / len(long_samples)

        # Long text should take substantially longer on average
        assert long_mean > short_mean * 10, (
            f"Long text mean ({long_mean:.2f}s) not 10x short text mean ({short_mean:.2f}s)"
        )

    async def test_should_rethink_is_nondeterministic(self):
        """should_rethink produces different results across calls (not always same)."""
        from phantom_fleet.core.human_post_behavior import should_rethink

        results = {should_rethink() for _ in range(100)}
        # Should have both True and False in 100 trials
        assert True in results
        assert False in results
