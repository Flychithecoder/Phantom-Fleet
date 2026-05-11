"""
Tests for per-account EmojiPersonality variation in IGStoryReactAgent.

Coverage:
    assign_personality:
        - Stable: same account_id always returns the same personality
        - All 7 personalities represented across 100 distinct accounts
          (no monoculture — every personality type appears at least once)

    Fleet distribution:
        - 500 accounts reacting to the same story produce no single emoji
          dominant at > 25% (old system had ❤️ at 35%)
        - MINIMAL personality accounts react at < 12% of stories
        - HEART_LOVER personality accounts react at > 25% of stories

    Daily rate jitter:
        - Same account produces different rates on different dates

    Emoji pool correctness:
        - LAUGHER never sends 👏 as its top emoji
        - HEART_LOVER's most-common emoji is ❤️

    WorkerResult:
        - data["personality"] is populated with a valid EmojiPersonality value

    Existing invariants still hold:
        - React dedup: same media_id never reacted to twice in one session
        - Daily cap enforced at MAX_REACTIONS_PER_ACCOUNT_PER_DAY

All HTTP calls are mocked — no real API calls.
asyncio_mode = "auto" is configured in pyproject.toml (no decorator needed).
"""
from __future__ import annotations

from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.core.hybrid_runner import PlatformHeaders, WorkerResult
from phantom_fleet.core.instagram_client import (
    IGSession,
    InstagramClient,
)


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


# ---------------------------------------------------------------------------
# assign_personality tests
# ---------------------------------------------------------------------------


class TestAssignPersonality:
    def test_stable_same_account_same_result(self):
        """Same account_id always returns the same personality."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import assign_personality

        p1 = assign_personality("acc_stable_001")
        p2 = assign_personality("acc_stable_001")
        assert p1 == p2

    def test_stable_across_many_calls(self):
        """50 repeated calls for the same account_id all return the same value."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import assign_personality

        account_id = "acc_repeat_check"
        results = {assign_personality(account_id) for _ in range(50)}
        assert len(results) == 1, "Personality must be deterministic"

    def test_all_7_personalities_represented_across_100_accounts(self):
        """No monoculture: all 7 EmojiPersonality values appear across 100 accounts."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            assign_personality,
            EmojiPersonality,
        )

        personalities_seen = {assign_personality(f"acc_dist_{i:04d}") for i in range(100)}
        all_personalities = set(EmojiPersonality)
        missing = all_personalities - personalities_seen
        assert not missing, f"Missing personalities across 100 accounts: {missing}"

    def test_returns_valid_emoji_personality_enum(self):
        """Return value is always a valid EmojiPersonality member."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            assign_personality,
            EmojiPersonality,
        )

        for i in range(30):
            result = assign_personality(f"acc_enum_check_{i}")
            assert isinstance(result, EmojiPersonality)


# ---------------------------------------------------------------------------
# Fleet distribution tests
# ---------------------------------------------------------------------------


class TestFleetEmojiDistribution:
    def test_no_single_emoji_exceeds_25_percent_across_500_accounts(self):
        """
        500 different accounts reacting to the same story should not produce
        any single emoji at > 25% share.  The old fleet-wide weights produced
        ❤️ at 35%, which was a detectable cluster fingerprint.
        """
        from phantom_fleet.agents.specialists.ig_story_react_agent import _pick_emoji

        media_id = "media_fleet_distribution_test"
        emoji_counts: Counter = Counter()

        for i in range(500):
            account_id = f"acc_fleet_{i:04d}"
            emoji = _pick_emoji(account_id, media_id)
            emoji_counts[emoji] += 1

        total = sum(emoji_counts.values())
        for emoji, count in emoji_counts.items():
            share = count / total
            assert share <= 0.25, (
                f"Emoji {emoji} has {share:.1%} share across 500 accounts — "
                f"exceeds 25% threshold (old system had ❤️ at 35%)"
            )

    def test_minimal_personality_reacts_less_than_12_percent(self):
        """MINIMAL accounts react to fewer than 12% of stories."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            assign_personality,
            _daily_reaction_rate,
            _should_react,
            EmojiPersonality,
        )

        # Find an account assigned MINIMAL personality
        minimal_account = None
        for i in range(500):
            account_id = f"acc_minimal_search_{i:04d}"
            if assign_personality(account_id) == EmojiPersonality.MINIMAL:
                minimal_account = account_id
                break

        assert minimal_account is not None, "Could not find a MINIMAL account in 500 tries"

        date_iso = "2026-04-11"
        rate = _daily_reaction_rate(minimal_account, date_iso)

        # Test across 200 stories
        reacted = sum(
            1 for j in range(200)
            if _should_react(minimal_account, f"media_{j:04d}", rate)
        )
        actual_rate = reacted / 200
        assert actual_rate < 0.12, (
            f"MINIMAL account {minimal_account} reacted at {actual_rate:.1%} — "
            f"expected < 12%"
        )

    def test_heart_lover_personality_reacts_more_than_25_percent(self):
        """HEART_LOVER accounts react to more than 25% of stories on average."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            assign_personality,
            _daily_reaction_rate,
            _should_react,
            EmojiPersonality,
        )

        # Find an account assigned HEART_LOVER personality
        heart_account = None
        for i in range(500):
            account_id = f"acc_heart_search_{i:04d}"
            if assign_personality(account_id) == EmojiPersonality.HEART_LOVER:
                heart_account = account_id
                break

        assert heart_account is not None, "Could not find a HEART_LOVER account in 500 tries"

        # Average rate across several dates to smooth daily jitter
        rates = [
            _daily_reaction_rate(heart_account, f"2026-04-{d:02d}")
            for d in range(1, 15)
        ]
        avg_rate = sum(rates) / len(rates)
        assert avg_rate > 0.25, (
            f"HEART_LOVER account {heart_account} has avg rate {avg_rate:.1%} — "
            f"expected > 25%"
        )


# ---------------------------------------------------------------------------
# Daily rate jitter tests
# ---------------------------------------------------------------------------


class TestDailyRateJitter:
    def test_same_account_different_rates_on_different_dates(self):
        """Same account produces different reaction rates on different dates."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import _daily_reaction_rate

        account_id = "acc_jitter_test"
        rates = [
            _daily_reaction_rate(account_id, f"2026-04-{d:02d}")
            for d in range(1, 15)
        ]
        unique_rates = set(rates)
        assert len(unique_rates) >= 5, (
            f"Only {len(unique_rates)} distinct rates across 14 days — "
            f"daily jitter is not working"
        )

    def test_rate_stays_within_clamped_bounds(self):
        """All rates are within [0.03, 0.60] regardless of personality."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import _daily_reaction_rate

        for i in range(200):
            account_id = f"acc_bounds_{i:04d}"
            for day in range(1, 8):
                rate = _daily_reaction_rate(account_id, f"2026-04-{day:02d}")
                assert 0.03 <= rate <= 0.60, (
                    f"Rate {rate:.4f} out of [0.03, 0.60] for {account_id}"
                )


# ---------------------------------------------------------------------------
# Emoji pool correctness tests
# ---------------------------------------------------------------------------


class TestEmojiPoolCorrectness:
    def test_laugher_top_emoji_is_not_clap(self):
        """LAUGHER personality's most frequent emoji across many stories should not be 👏."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            assign_personality,
            _pick_emoji,
            EmojiPersonality,
        )

        # Find a LAUGHER account
        laugher_account = None
        for i in range(500):
            account_id = f"acc_laugher_search_{i:04d}"
            if assign_personality(account_id) == EmojiPersonality.LAUGHER:
                laugher_account = account_id
                break

        assert laugher_account is not None

        # Sample across 300 stories
        counts: Counter = Counter()
        for j in range(300):
            emoji = _pick_emoji(laugher_account, f"media_laugher_{j:04d}")
            counts[emoji] += 1

        top_emoji = counts.most_common(1)[0][0]
        assert top_emoji != "👏", (
            f"LAUGHER top emoji is 👏 — should be 😂 or 💀"
        )

    def test_heart_lover_top_emoji_is_heart(self):
        """HEART_LOVER personality's most frequent emoji should be ❤️."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            assign_personality,
            _pick_emoji,
            EmojiPersonality,
        )

        heart_account = None
        for i in range(500):
            account_id = f"acc_heart_emoji_{i:04d}"
            if assign_personality(account_id) == EmojiPersonality.HEART_LOVER:
                heart_account = account_id
                break

        assert heart_account is not None

        counts: Counter = Counter()
        for j in range(300):
            emoji = _pick_emoji(heart_account, f"media_heart_{j:04d}")
            counts[emoji] += 1

        top_emoji = counts.most_common(1)[0][0]
        assert top_emoji == "❤️", (
            f"HEART_LOVER top emoji is {top_emoji}, expected ❤️"
        )

    def test_hype_beast_top_emoji_is_fire(self):
        """HYPE_BEAST personality's most frequent emoji should be 🔥."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            assign_personality,
            _pick_emoji,
            EmojiPersonality,
        )

        hype_account = None
        for i in range(500):
            account_id = f"acc_hype_emoji_{i:04d}"
            if assign_personality(account_id) == EmojiPersonality.HYPE_BEAST:
                hype_account = account_id
                break

        assert hype_account is not None

        counts: Counter = Counter()
        for j in range(300):
            emoji = _pick_emoji(hype_account, f"media_hype_{j:04d}")
            counts[emoji] += 1

        top_emoji = counts.most_common(1)[0][0]
        assert top_emoji == "🔥", (
            f"HYPE_BEAST top emoji is {top_emoji}, expected 🔥"
        )


# ---------------------------------------------------------------------------
# WorkerResult data tests
# ---------------------------------------------------------------------------


class TestWorkerResultData:
    async def test_personality_stored_in_worker_result_data(self):
        """WorkerResult.data['personality'] is populated with a valid personality value."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            IGStoryReactAgent,
            StoryViewRecord,
            EmojiPersonality,
        )

        agent = IGStoryReactAgent()
        session = make_session("acc_result_test")

        records = [
            StoryViewRecord(
                reel_id="reel_r1",
                media_id=f"media_r{i}",
                account_id="acc_result_test",
                target_user_id="reel_r1",
            )
            for i in range(10)
        ]

        mock_react = AsyncMock(return_value=True)
        with (
            patch("phantom_fleet.agents.specialists.ig_story_react_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=MagicMock(react_to_story=mock_react)),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        ):
            result = await agent.run_session(
                account_id="acc_result_test",
                session=session,
                story_views_today=records,
                date_iso="2026-04-11",
            )

        assert "personality" in result.data
        valid_values = {p.value for p in EmojiPersonality}
        assert result.data["personality"] in valid_values, (
            f"personality value '{result.data['personality']}' not a valid EmojiPersonality"
        )

    async def test_personality_consistent_across_calls(self):
        """Same account always gets same personality in WorkerResult."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            IGStoryReactAgent,
            StoryViewRecord,
        )

        agent = IGStoryReactAgent()
        account_id = "acc_consistent_personality"
        session = make_session(account_id)

        records = [
            StoryViewRecord(
                reel_id="reel_c1",
                media_id=f"media_c{i}",
                account_id=account_id,
                target_user_id="reel_c1",
            )
            for i in range(5)
        ]

        async def run_once(date_iso: str) -> str:
            mock_react = AsyncMock(return_value=True)
            with (
                patch("phantom_fleet.agents.specialists.ig_story_react_agent.asyncio.sleep", new=AsyncMock()),
                patch.object(InstagramClient, "__aenter__", return_value=MagicMock(react_to_story=mock_react)),
                patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            ):
                result = await agent.run_session(
                    account_id=account_id,
                    session=session,
                    story_views_today=records,
                    date_iso=date_iso,
                )
            return result.data["personality"]

        p1 = await run_once("2026-04-11")
        p2 = await run_once("2026-04-12")
        assert p1 == p2, "Personality must not change between dates for same account"


# ---------------------------------------------------------------------------
# Existing invariant regression tests
# ---------------------------------------------------------------------------


class TestExistingInvariantsStillHold:
    async def test_react_dedup_never_reacts_to_same_story_twice(self):
        """Dedup: same media_id is never reacted to twice in one session."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            IGStoryReactAgent,
            StoryViewRecord,
        )

        agent = IGStoryReactAgent()
        session = make_session("acc_dedup_test")

        # Duplicate records: same media_id appears three times
        records = [
            StoryViewRecord(reel_id="reel_d1", media_id="media_dup", account_id="acc_dedup_test", target_user_id="reel_d1"),
            StoryViewRecord(reel_id="reel_d1", media_id="media_dup", account_id="acc_dedup_test", target_user_id="reel_d1"),
            StoryViewRecord(reel_id="reel_d1", media_id="media_dup", account_id="acc_dedup_test", target_user_id="reel_d1"),
        ]

        mock_react = AsyncMock(return_value=True)
        with (
            patch("phantom_fleet.agents.specialists.ig_story_react_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=MagicMock(react_to_story=mock_react)),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch(
                "phantom_fleet.agents.specialists.ig_story_react_agent._should_react",
                return_value=True,
            ),
        ):
            result = await agent.run_session(
                account_id="acc_dedup_test",
                session=session,
                story_views_today=records,
                date_iso="2026-04-11",
            )

        # media_dup can only be reacted to once
        assert result.data["reactions_sent"] <= 1
        assert result.data["already_reacted_skips"] >= 2

    async def test_daily_cap_enforced_at_max(self):
        """reactions_sent never exceeds MAX_REACTIONS_PER_ACCOUNT_PER_DAY."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            IGStoryReactAgent,
            StoryViewRecord,
            MAX_REACTIONS_PER_ACCOUNT_PER_DAY,
        )

        agent = IGStoryReactAgent()
        session = make_session("acc_cap_personality_test")

        # 300 unique stories — should stop at cap
        records = [
            StoryViewRecord(
                reel_id=f"reel_{i}",
                media_id=f"media_cap_{i:04d}",
                account_id="acc_cap_personality_test",
                target_user_id=f"reel_{i}",
            )
            for i in range(300)
        ]

        mock_react = AsyncMock(return_value=True)
        with (
            patch("phantom_fleet.agents.specialists.ig_story_react_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=MagicMock(react_to_story=mock_react)),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch(
                "phantom_fleet.agents.specialists.ig_story_react_agent._should_react",
                return_value=True,
            ),
        ):
            result = await agent.run_session(
                account_id="acc_cap_personality_test",
                session=session,
                story_views_today=records,
                date_iso="2026-04-11",
            )

        assert result.data["reactions_sent"] <= MAX_REACTIONS_PER_ACCOUNT_PER_DAY

    async def test_daily_cap_counts_previously_sent_reactions(self):
        """reactions_sent_today already at cap → no new reactions sent."""
        from phantom_fleet.agents.specialists.ig_story_react_agent import (
            IGStoryReactAgent,
            StoryViewRecord,
            MAX_REACTIONS_PER_ACCOUNT_PER_DAY,
        )

        agent = IGStoryReactAgent()
        session = make_session("acc_pre_cap_test")

        records = [
            StoryViewRecord(
                reel_id="reel_p1",
                media_id=f"media_p{i}",
                account_id="acc_pre_cap_test",
                target_user_id="reel_p1",
            )
            for i in range(20)
        ]

        mock_react = AsyncMock(return_value=True)
        with (
            patch("phantom_fleet.agents.specialists.ig_story_react_agent.asyncio.sleep", new=AsyncMock()),
            patch.object(InstagramClient, "__aenter__", return_value=MagicMock(react_to_story=mock_react)),
            patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
            patch(
                "phantom_fleet.agents.specialists.ig_story_react_agent._should_react",
                return_value=True,
            ),
        ):
            result = await agent.run_session(
                account_id="acc_pre_cap_test",
                session=session,
                story_views_today=records,
                date_iso="2026-04-11",
                # Already at or over the cap
                reactions_sent_today=MAX_REACTIONS_PER_ACCOUNT_PER_DAY,
            )

        assert result.data["reactions_sent"] == 0
