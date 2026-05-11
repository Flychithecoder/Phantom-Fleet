"""
Tests for:
    - IGNotesAgent        (ig_notes_agent.py)
    - IGBroadcastAgent    (ig_broadcast_agent.py)
    - IGStoryMentionAgent (ig_story_mention_agent.py)
    - IGStoryRecyclerAgent (ig_story_recycler_agent.py)

All HTTP calls and asyncio.sleep are mocked.
asyncio_mode = "auto" (configured in pyproject.toml) — no @pytest.mark.asyncio needed.

Coverage:
    IGNotesAgent (5 tests):
        - delete called before set
        - selection seeded (same account+date = same note)
        - different accounts on same date get different notes
        - 60-char hard limit enforced
        - ValueError on pool < 30

    IGBroadcastAgent (5 tests):
        - invite cap enforced at 50/day
        - invite stagger is LogNormal (sleep called between invites)
        - broadcast cap enforced at 2/day
        - message length > 500 chars rejected
        - weekly recap calls OpenRouter

    IGStoryMentionAgent (5 tests):
        - mentioner follower_count < 100 skipped
        - already_reposted dedup by story_pk
        - daily cap at 10 enforced
        - thank-you overlay seeded per mentioner (stable + distinct)
        - repost_story_mention called for qualified mention

    IGStoryRecyclerAgent (5 tests):
        - only recycles if days_since >= 7
        - reposted_count < 3 enforced
        - transform called with unique seed per recycle
        - daily cap at 2 enforced
        - sorted by view_count descending (best first)

Total: 20 tests
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call as mock_call

import pytest
import httpx

from phantom_fleet.core.hybrid_runner import PlatformHeaders, WorkerResult
from phantom_fleet.core.instagram_client import IGSession

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _make_headers() -> PlatformHeaders:
    return PlatformHeaders(
        platform="instagram",
        session_token="tok_test",
        device_id="android-test-device",
        user_agent="Instagram 300.0.0.1 Android (31/12; 420dpi; 1080x2400; samsung; SM-G770F; x1s; exynos9610; en_US; 480028919)",
        app_version="300.0.0.1",
        android_id="abc123def456abc1",
        advertising_id="gaid-1234-5678",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
        extra={"mid": "mid_val", "family_device_id": "fam-uuid"},
    )


def _make_session(account_id: str = "acc_001") -> IGSession:
    return IGSession(
        account_id=account_id,
        ig_user_id="1234567890",
        username=f"user_{account_id}",
        session_id="sess_abc",
        csrftoken="csrf_xyz",
        mid="mid_val",
        ds_user_id="1234567890",
        headers=_make_headers(),
    )


# ===========================================================================
# IGNotesAgent tests
# ===========================================================================

class TestIGNotesAgent:

    # -----------------------------------------------------------------------
    # Test 1: delete is called before set
    # -----------------------------------------------------------------------
    async def test_delete_called_before_set(self):
        """delete_note() must be called before set_note() in every rotation."""
        from phantom_fleet.agents.specialists.ig_notes_agent import (
            IGNotesAgent, IGNotesTask, DEFAULT_NOTE_POOL,
        )

        task = IGNotesTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            date_iso="2026-04-11",
            note_pool=list(DEFAULT_NOTE_POOL),
            rotations_today=0,
        )

        call_order: list[str] = []

        async def fake_delete_note():
            call_order.append("delete")
            return True

        async def fake_create_note(text: str, audience: int = 1):
            call_order.append("set")
            return True

        with (
            patch(
                "phantom_fleet.agents.specialists.ig_notes_agent.InstagramClient"
            ) as MockClient,
            patch("phantom_fleet.agents.specialists.ig_notes_agent.asyncio.sleep"),
        ):
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.delete_note = fake_delete_note
            mock_instance.create_note = fake_create_note
            MockClient.return_value = mock_instance

            agent = IGNotesAgent()
            result = await agent.run_daily_rotation(task)

        assert result.success is True
        assert call_order.index("delete") < call_order.index("set"), (
            "delete_note must be called before set_note"
        )

    # -----------------------------------------------------------------------
    # Test 2: same account + same date always selects the same note
    # -----------------------------------------------------------------------
    async def test_selection_seeded_same_account_same_date(self):
        """select_note() must return the same note for same account+date (stable)."""
        from phantom_fleet.agents.specialists.ig_notes_agent import (
            select_note, DEFAULT_NOTE_POOL,
        )

        pool = list(DEFAULT_NOTE_POOL)
        note_a = select_note(pool, "acc_001", "2026-04-11")
        note_b = select_note(pool, "acc_001", "2026-04-11")
        assert note_a == note_b, (
            "Same account + same date must always yield the same note"
        )

    # -----------------------------------------------------------------------
    # Test 3: different accounts on same date get different notes
    # -----------------------------------------------------------------------
    async def test_different_accounts_get_different_notes(self):
        """Different accounts on the same date must not all pick the same note."""
        from phantom_fleet.agents.specialists.ig_notes_agent import (
            select_note, DEFAULT_NOTE_POOL,
        )

        pool = list(DEFAULT_NOTE_POOL)
        date_iso = "2026-04-11"
        # Test 10 different accounts — at least some must differ
        notes = {
            select_note(pool, f"acc_{i:03d}", date_iso)
            for i in range(10)
        }
        assert len(notes) > 1, (
            "Different accounts on the same date must select different notes "
            f"(got only 1 unique note out of 10 accounts: {notes})"
        )

    # -----------------------------------------------------------------------
    # Test 4: 60-char hard limit enforced by select_note
    # -----------------------------------------------------------------------
    async def test_60_char_hard_limit_enforced(self):
        """Notes longer than 60 chars must be truncated to <= 60 chars with '...'."""
        from phantom_fleet.agents.specialists.ig_notes_agent import (
            select_note, NOTE_MAX_CHARS,
        )

        # Build a pool of 30 entries where every entry is long
        pool = [f"This is a very long note that definitely exceeds 60 chars and should be truncated entry #{i}" for i in range(30)]
        note = select_note(pool, "acc_001", "2026-04-11")
        assert len(note) <= NOTE_MAX_CHARS, (
            f"Note must be <= {NOTE_MAX_CHARS} chars, got {len(note)}: {note!r}"
        )
        assert note.endswith("..."), (
            f"Truncated note must end with '...', got: {note!r}"
        )

    # -----------------------------------------------------------------------
    # Test 5: ValueError raised when pool has fewer than 30 entries
    # -----------------------------------------------------------------------
    async def test_valueerror_on_pool_smaller_than_30(self):
        """IGNotesAgent must raise ValueError if pool has < 30 entries."""
        from phantom_fleet.agents.specialists.ig_notes_agent import (
            IGNotesAgent, IGNotesTask,
        )

        task = IGNotesTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            date_iso="2026-04-11",
            note_pool=["short pool"] * 5,  # only 5 entries
            rotations_today=0,
        )

        agent = IGNotesAgent()
        result = await agent.run_daily_rotation(task)

        assert result.success is False
        assert "at least 120" in (result.error or ""), (
            f"Error message should mention '120', got: {result.error!r}"
        )


# ===========================================================================
# IGBroadcastAgent tests
# ===========================================================================

class TestIGBroadcastAgent:

    # -----------------------------------------------------------------------
    # Test 6: invite cap enforced at 50/day
    # -----------------------------------------------------------------------
    async def test_invite_cap_enforced_at_50(self):
        """invite_new_followers() must refuse when invites_today >= 50."""
        from phantom_fleet.agents.specialists.ig_broadcast_agent import (
            IGBroadcastAgent, IGBroadcastInviteTask,
        )

        task = IGBroadcastInviteTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            channel_id="chan_001",
            new_follower_ids=["user_1", "user_2"],
            invites_today=50,   # already at cap
        )

        agent = IGBroadcastAgent()
        result = await agent.invite_new_followers(task)

        assert result.success is False
        assert "daily_invite_cap_reached" in (result.error or "")

    # -----------------------------------------------------------------------
    # Test 7: invite stagger — asyncio.sleep called between invites
    # -----------------------------------------------------------------------
    async def test_invite_stagger_sleep_called_between_invites(self):
        """A sleep must occur between each pair of invites (LogNormal stagger)."""
        from phantom_fleet.agents.specialists.ig_broadcast_agent import (
            IGBroadcastAgent, IGBroadcastInviteTask,
        )

        task = IGBroadcastInviteTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            channel_id="chan_001",
            new_follower_ids=["user_1", "user_2", "user_3"],
            invites_today=0,
        )

        with (
            patch(
                "phantom_fleet.agents.specialists.ig_broadcast_agent.InstagramClient"
            ) as MockClient,
            patch(
                "phantom_fleet.agents.specialists.ig_broadcast_agent.asyncio.sleep"
            ) as mock_sleep,
        ):
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.invite_to_broadcast = AsyncMock(return_value=True)
            MockClient.return_value = mock_instance

            agent = IGBroadcastAgent()
            result = await agent.invite_new_followers(task)

        # 3 invites → 2 sleeps (no sleep after the last one)
        assert mock_sleep.call_count == 2, (
            f"Expected 2 sleep calls for 3 invites, got {mock_sleep.call_count}"
        )
        assert result.data["invited_count"] == 3

    # -----------------------------------------------------------------------
    # Test 8: broadcast cap enforced at 2/day
    # -----------------------------------------------------------------------
    async def test_broadcast_cap_enforced_at_2(self):
        """send_content_drop() must refuse when broadcasts_today >= 2."""
        from phantom_fleet.agents.specialists.ig_broadcast_agent import (
            IGBroadcastAgent, IGBroadcastDropTask,
        )

        task = IGBroadcastDropTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            channel_id="chan_001",
            message="A perfectly good message",
            broadcasts_today=2,   # already at cap
        )

        agent = IGBroadcastAgent()
        result = await agent.send_content_drop(task)

        assert result.success is False
        assert "daily_broadcast_cap_reached" in (result.error or "")

    # -----------------------------------------------------------------------
    # Test 9: message > 500 chars is rejected
    # -----------------------------------------------------------------------
    async def test_message_too_long_rejected(self):
        """send_content_drop() must reject messages longer than 500 chars."""
        from phantom_fleet.agents.specialists.ig_broadcast_agent import (
            IGBroadcastAgent, IGBroadcastDropTask,
        )

        long_message = "x" * 501  # 501 chars

        task = IGBroadcastDropTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            channel_id="chan_001",
            message=long_message,
            broadcasts_today=0,
        )

        agent = IGBroadcastAgent()
        result = await agent.send_content_drop(task)

        assert result.success is False
        assert "message_too_long" in (result.error or ""), (
            f"Expected message_too_long error, got: {result.error!r}"
        )

    # -----------------------------------------------------------------------
    # Test 10: weekly recap calls OpenRouter
    # -----------------------------------------------------------------------
    async def test_weekly_recap_calls_openrouter(self):
        """send_weekly_recap() must call OpenRouter to generate the recap text."""
        from phantom_fleet.agents.specialists.ig_broadcast_agent import (
            IGBroadcastAgent, IGWeeklyRecapTask,
        )

        task = IGWeeklyRecapTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            channel_id="chan_001",
            content_items=["hot new photo set", "behind the scenes video", "Q&A session"],
            broadcasts_today=0,
        )

        openrouter_response = {
            "choices": [{"message": {"content": "What a week 🔥 Three drops, each wilder than the last."}}]
        }

        with (
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}),
            patch(
                "phantom_fleet.agents.specialists.ig_broadcast_agent.InstagramClient"
            ) as MockClient,
            patch("httpx.AsyncClient") as MockHTTP,
        ):
            # Mock the OpenRouter HTTP call
            mock_http_instance = AsyncMock()
            mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http_instance.__aexit__ = AsyncMock(return_value=False)
            mock_openrouter_resp = MagicMock()
            mock_openrouter_resp.raise_for_status = MagicMock()
            mock_openrouter_resp.json = MagicMock(return_value=openrouter_response)
            mock_http_instance.post = AsyncMock(return_value=mock_openrouter_resp)
            MockHTTP.return_value = mock_http_instance

            # Mock InstagramClient
            mock_ig = AsyncMock()
            mock_ig.__aenter__ = AsyncMock(return_value=mock_ig)
            mock_ig.__aexit__ = AsyncMock(return_value=False)
            mock_ig.send_broadcast_message = AsyncMock(return_value=True)
            MockClient.return_value = mock_ig

            agent = IGBroadcastAgent()
            result = await agent.send_weekly_recap(task)

        assert result.success is True
        assert "week" in result.data.get("recap", "").lower() or len(result.data.get("recap", "")) > 0


# ===========================================================================
# IGStoryMentionAgent tests
# ===========================================================================

class TestIGStoryMentionAgent:

    def _make_mention(
        self,
        story_pk: str = "story_001",
        mentioner_id: str = "usr_111",
        username: str = "fan_user",
        follower_count: int = 500,
    ) -> dict:
        return {
            "story_pk":                story_pk,
            "mentioner_user_id":       mentioner_id,
            "mentioner_username":      username,
            "mentioner_follower_count": follower_count,
            "media_url":               "https://cdn.ig.com/story_001.jpg",
        }

    # -----------------------------------------------------------------------
    # Test 11: mentions from accounts with < 100 followers are skipped
    # -----------------------------------------------------------------------
    async def test_low_follower_mentioner_skipped(self):
        """Mentions from accounts with follower_count < 100 must be skipped."""
        from phantom_fleet.agents.specialists.ig_story_mention_agent import (
            IGStoryMentionAgent, IGStoryMentionTask,
        )

        task = IGStoryMentionTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            already_reposted=set(),
            reposts_today=0,
        )

        low_follower_mention = self._make_mention(follower_count=50)

        with patch(
            "phantom_fleet.agents.specialists.ig_story_mention_agent.InstagramClient"
        ) as MockClient:
            mock_ig = AsyncMock()
            mock_ig.__aenter__ = AsyncMock(return_value=mock_ig)
            mock_ig.__aexit__ = AsyncMock(return_value=False)
            mock_ig.get_story_mentions = AsyncMock(return_value=[low_follower_mention])
            mock_ig.repost_story_mention = AsyncMock(return_value=True)
            MockClient.return_value = mock_ig

            agent = IGStoryMentionAgent()
            result = await agent.monitor_and_repost(task)

        assert result.data["reposted_count"] == 0
        assert len(result.data["skipped"]) == 1
        assert result.data["skipped"][0]["reason"] == "follower_count_too_low"
        mock_ig.repost_story_mention.assert_not_called()

    # -----------------------------------------------------------------------
    # Test 12: already-reposted story_pk is not reposted again
    # -----------------------------------------------------------------------
    async def test_dedup_by_story_pk(self):
        """A mention whose story_pk is in already_reposted must not be reposted."""
        from phantom_fleet.agents.specialists.ig_story_mention_agent import (
            IGStoryMentionAgent, IGStoryMentionTask,
        )

        task = IGStoryMentionTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            already_reposted={"story_001"},  # already done
            reposts_today=0,
        )

        mention = self._make_mention(story_pk="story_001", follower_count=1000)

        with patch(
            "phantom_fleet.agents.specialists.ig_story_mention_agent.InstagramClient"
        ) as MockClient:
            mock_ig = AsyncMock()
            mock_ig.__aenter__ = AsyncMock(return_value=mock_ig)
            mock_ig.__aexit__ = AsyncMock(return_value=False)
            mock_ig.get_story_mentions = AsyncMock(return_value=[mention])
            mock_ig.repost_story_mention = AsyncMock(return_value=True)
            MockClient.return_value = mock_ig

            agent = IGStoryMentionAgent()
            result = await agent.monitor_and_repost(task)

        assert result.data["reposted_count"] == 0
        assert any(s["reason"] == "already_reposted" for s in result.data["skipped"])
        mock_ig.repost_story_mention.assert_not_called()

    # -----------------------------------------------------------------------
    # Test 13: daily cap at 10 enforced
    # -----------------------------------------------------------------------
    async def test_daily_repost_cap_at_10(self):
        """monitor_and_repost() must not exceed 10 reposts per day."""
        from phantom_fleet.agents.specialists.ig_story_mention_agent import (
            IGStoryMentionAgent, IGStoryMentionTask,
        )

        task = IGStoryMentionTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            already_reposted=set(),
            reposts_today=8,   # 8 already done — only 2 more allowed
        )

        # 5 distinct qualified mentions
        mentions = [
            self._make_mention(
                story_pk=f"story_{i:03d}",
                mentioner_id=f"usr_{i:03d}",
                follower_count=500,
            )
            for i in range(5)
        ]

        with (
            patch(
                "phantom_fleet.agents.specialists.ig_story_mention_agent.InstagramClient"
            ) as MockClient,
            patch(
                "phantom_fleet.agents.specialists.ig_story_mention_agent.asyncio.sleep"
            ),
        ):
            mock_ig = AsyncMock()
            mock_ig.__aenter__ = AsyncMock(return_value=mock_ig)
            mock_ig.__aexit__ = AsyncMock(return_value=False)
            mock_ig.get_story_mentions = AsyncMock(return_value=mentions)
            mock_ig.repost_story_mention = AsyncMock(return_value=True)
            MockClient.return_value = mock_ig

            agent = IGStoryMentionAgent()
            result = await agent.monitor_and_repost(task)

        # 8 already + 2 this run = 10 (cap); cannot exceed
        assert result.data["reposted_count"] == 2, (
            f"Expected 2 reposts (cap enforcement), got {result.data['reposted_count']}"
        )

    # -----------------------------------------------------------------------
    # Test 14: thank-you overlay is stable per (account, mentioner) but varies
    # -----------------------------------------------------------------------
    async def test_thank_you_overlay_seeded_per_mentioner(self):
        """Same account+mentioner always gets the same overlay; different mentioners differ."""
        from phantom_fleet.agents.specialists.ig_story_mention_agent import (
            select_thank_you_overlay, THANK_YOU_OVERLAYS,
        )

        pool = list(THANK_YOU_OVERLAYS)
        account_id = "acc_001"

        # Same inputs → same overlay
        overlay_a = select_thank_you_overlay(pool, account_id, "mentioner_111")
        overlay_b = select_thank_you_overlay(pool, account_id, "mentioner_111")
        assert overlay_a == overlay_b, "Same account+mentioner must always get same overlay"

        # Different mentioners → collect results; must have variety
        overlays = {
            select_thank_you_overlay(pool, account_id, f"mentioner_{i:03d}")
            for i in range(12)
        }
        assert len(overlays) > 1, (
            "Different mentioners must receive different overlays at fleet scale"
        )

    # -----------------------------------------------------------------------
    # Test 15: repost_story_mention is called for a qualified mention
    # -----------------------------------------------------------------------
    async def test_repost_called_for_qualified_mention(self):
        """repost_story_mention() must be called with the correct story_pk."""
        from phantom_fleet.agents.specialists.ig_story_mention_agent import (
            IGStoryMentionAgent, IGStoryMentionTask,
        )

        task = IGStoryMentionTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            already_reposted=set(),
            reposts_today=0,
        )

        mention = self._make_mention(
            story_pk="story_XYZ",
            mentioner_id="usr_999",
            follower_count=1500,
        )

        with (
            patch(
                "phantom_fleet.agents.specialists.ig_story_mention_agent.InstagramClient"
            ) as MockClient,
            patch(
                "phantom_fleet.agents.specialists.ig_story_mention_agent.asyncio.sleep"
            ),
        ):
            mock_ig = AsyncMock()
            mock_ig.__aenter__ = AsyncMock(return_value=mock_ig)
            mock_ig.__aexit__ = AsyncMock(return_value=False)
            mock_ig.get_story_mentions = AsyncMock(return_value=[mention])
            mock_ig.repost_story_mention = AsyncMock(return_value=True)
            MockClient.return_value = mock_ig

            agent = IGStoryMentionAgent()
            result = await agent.monitor_and_repost(task)

        assert result.data["reposted_count"] == 1
        mock_ig.repost_story_mention.assert_called_once()
        call_args = mock_ig.repost_story_mention.call_args
        assert call_args[0][0] == "story_XYZ" or call_args.args[0] == "story_XYZ"


# ===========================================================================
# IGStoryRecyclerAgent tests
# ===========================================================================

class TestIGStoryRecyclerAgent:

    def _now_iso(self, days_ago: float = 0.0) -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return dt.isoformat()

    def _make_task(
        self,
        story_log: list,
        recycles_today: int = 0,
    ):
        from phantom_fleet.agents.specialists.ig_story_recycler_agent import (
            IGStoryRecyclerTask,
        )
        return IGStoryRecyclerTask(
            account_id="acc_001",
            ig_session=_make_session("acc_001"),
            story_log=story_log,
            phone_ip="192.168.1.100",
            phone_serial="emulator-5554",
            clone_package="com.instagram.android.clone1",
            apk_port=8090,
            recycles_today=recycles_today,
            view_threshold=500,
        )

    # -----------------------------------------------------------------------
    # Test 16: stories < 7 days old are not recycled
    # -----------------------------------------------------------------------
    async def test_not_recycled_if_less_than_7_days_old(self):
        """Stories posted less than 7 days ago must not be recycled."""
        from phantom_fleet.agents.specialists.ig_story_recycler_agent import (
            IGStoryRecyclerAgent, StoryLogEntry,
        )

        recent_entry = StoryLogEntry(
            story_id="story_001",
            media_url="https://cdn.ig.com/s1.jpg",
            view_count=10000,
            posted_at_iso=self._now_iso(days_ago=3),   # only 3 days ago
            reposted_count=0,
        )

        task = self._make_task([recent_entry])
        agent = IGStoryRecyclerAgent()
        result = await agent.run_recycler(task)

        assert result.success is True
        assert result.data["recycled_count"] == 0
        assert result.data.get("reason") == "no_eligible_stories"

    # -----------------------------------------------------------------------
    # Test 17: stories with reposted_count >= 3 are not recycled
    # -----------------------------------------------------------------------
    async def test_not_recycled_if_reposted_count_at_3(self):
        """Stories already reposted 3 times must not be recycled again."""
        from phantom_fleet.agents.specialists.ig_story_recycler_agent import (
            IGStoryRecyclerAgent, StoryLogEntry,
        )

        maxed_entry = StoryLogEntry(
            story_id="story_002",
            media_url="https://cdn.ig.com/s2.jpg",
            view_count=50000,
            posted_at_iso=self._now_iso(days_ago=14),  # old enough
            reposted_count=3,                           # already at max
        )

        task = self._make_task([maxed_entry])
        agent = IGStoryRecyclerAgent()
        result = await agent.run_recycler(task)

        assert result.success is True
        assert result.data["recycled_count"] == 0

    # -----------------------------------------------------------------------
    # Test 18: transform seed is unique per (account, story, repost_number)
    # -----------------------------------------------------------------------
    async def test_transform_seed_unique_per_recycle(self):
        """_make_transform_seed must produce different seeds for different inputs."""
        from phantom_fleet.agents.specialists.ig_story_recycler_agent import (
            _make_transform_seed,
        )

        seed_a = _make_transform_seed("acc_001", "story_001", 1)
        seed_b = _make_transform_seed("acc_001", "story_001", 2)  # different repost number
        seed_c = _make_transform_seed("acc_002", "story_001", 1)  # different account

        assert seed_a != seed_b, "Different repost_number must produce different seed"
        assert seed_a != seed_c, "Different account_id must produce different seed"

        # Same inputs → same seed (deterministic)
        seed_a2 = _make_transform_seed("acc_001", "story_001", 1)
        assert seed_a == seed_a2, "Same inputs must always produce same seed"

    # -----------------------------------------------------------------------
    # Test 19: daily cap at 2 enforced
    # -----------------------------------------------------------------------
    async def test_daily_cap_at_2_enforced(self):
        """run_recycler() must refuse when recycles_today >= 2."""
        from phantom_fleet.agents.specialists.ig_story_recycler_agent import (
            IGStoryRecyclerAgent, StoryLogEntry,
        )

        eligible_entry = StoryLogEntry(
            story_id="story_003",
            media_url="https://cdn.ig.com/s3.jpg",
            view_count=20000,
            posted_at_iso=self._now_iso(days_ago=10),
            reposted_count=0,
        )

        task = self._make_task([eligible_entry], recycles_today=2)
        agent = IGStoryRecyclerAgent()
        result = await agent.run_recycler(task)

        assert result.success is False
        assert "daily_recycle_cap_reached" in (result.error or "")

    # -----------------------------------------------------------------------
    # Test 20: eligible stories sorted by view_count descending
    # -----------------------------------------------------------------------
    async def test_sorted_by_view_count_descending(self):
        """
        When multiple stories are eligible, run_recycler must process the
        highest view_count first. With cap=2 and 3 eligible stories, the
        top 2 by view count must be recycled.
        """
        from phantom_fleet.agents.specialists.ig_story_recycler_agent import (
            IGStoryRecyclerAgent, StoryLogEntry,
        )

        old_enough = self._now_iso(days_ago=10)

        entries = [
            StoryLogEntry("story_low",  "https://cdn.ig.com/sl.jpg",  1000, old_enough, 0),
            StoryLogEntry("story_high", "https://cdn.ig.com/sh.jpg", 50000, old_enough, 0),
            StoryLogEntry("story_mid",  "https://cdn.ig.com/sm.jpg", 15000, old_enough, 0),
        ]

        task = self._make_task(entries, recycles_today=0)

        # Track order of transform calls
        transformed_seeds: list[int] = []
        story_ids_processed: list[str] = []

        async def fake_post(url: str, **kwargs) -> MagicMock:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "/media/transform" in url:
                seed = int(kwargs.get("params", {}).get("seed", 0))
                transformed_seeds.append(seed)
                resp.content = b"fake_transformed_bytes"
                resp.headers = {"content-type": "image/jpeg"}
            elif "/instagram/story" in url:
                json_body = kwargs.get("json", {})
                story_ids_processed.append(json_body.get("transformSeed", ""))
                resp.content = b""
                resp.headers = {}
                resp.json = MagicMock(return_value={"success": True})
            return resp

        async def fake_get(url: str, **kwargs) -> MagicMock:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.content = b"fake_media_bytes"
            resp.headers = {"content-type": "image/jpeg"}
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=fake_post)
        mock_client.get = AsyncMock(side_effect=fake_get)

        with (
            patch(
                "phantom_fleet.agents.specialists.ig_story_recycler_agent.asyncio.sleep"
            ),
        ):
            agent = IGStoryRecyclerAgent(http_client=mock_client)
            result = await agent.run_recycler(task)

        # With cap=2, should recycle the 2 highest view-count stories
        assert result.data["recycled_count"] == 2, (
            f"Expected 2 recycles (cap), got {result.data['recycled_count']}"
        )
        recycled_ids = {r["story_id"] for r in result.data["recycled"]}
        assert "story_high" in recycled_ids, "Highest view-count story must be recycled"
        assert "story_mid" in recycled_ids, "Second highest view-count story must be recycled"
        assert "story_low" not in recycled_ids, "Lowest view-count story must be skipped (cap)"
