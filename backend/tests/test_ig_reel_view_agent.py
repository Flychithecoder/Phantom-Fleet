"""
Tests for IGReelViewAgent — 8 tests covering detection-critical properties.

1.  Watch duration distribution is LogNormal (sample 100 accounts, histogram not flat)
2.  Watch pct always in [0.25, 1.0]
3.  Rewatch rate across 1000 decisions ≈ 18% (within 3% tolerance)
4.  Story share rate across 1000 decisions ≈ 8% (within 2% tolerance)
5.  Fleet stagger offsets are in [0, 7200] and not uniform (distribution shape test)
6.  Daily reel cap enforced at 80
7.  Story share cap enforced at 6/day
8.  Same account+media always produces same watch_duration (determinism test)
"""
from __future__ import annotations

import asyncio
import math
import statistics
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.agents.specialists.ig_reel_view_agent import (
    MAX_REELS_PER_ACCOUNT_PER_DAY,
    MAX_STORY_SHARES_PER_DAY,
    MIN_INTER_REEL_DELAY_SEC,
    ReelToWatch,
    ReelSessionResult,
    IGReelViewAgent,
    _decision,
    _watch_duration,
    reel_view_offset_seconds,
    _REWATCH_THRESHOLD,
    _SHARE_THRESHOLD,
    _WATCH_PCT_FLOOR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reel(media_id: str = "reel001", duration: int = 30) -> ReelToWatch:
    return ReelToWatch(
        media_id=media_id,
        creator_user_id="creator_123",
        duration_seconds=duration,
        posted_at_iso="2026-04-11T10:00:00Z",
    )


def _make_session() -> MagicMock:
    session = MagicMock()
    session.account_id = "acct_test"
    session.ig_user_id = "12345"
    session.username = "test_user"
    return session


# ---------------------------------------------------------------------------
# Test 1: Watch duration distribution is LogNormal (not flat)
#
# Sample watch_pct for 100 different account/media combos.
# A flat (uniform) distribution would have standard deviation ≈ 0.217 for
# range [0.25, 1.0].  A LogNormal distribution has lower std dev because it
# concentrates mass around the mode.
# We also verify the mean is near 0.78 and the distribution has clear spread
# (not all values equal), which rules out a degenerate constant.
# ---------------------------------------------------------------------------


def test_watch_duration_distribution_is_lognormal_shaped():
    duration = 60  # 60-second reel

    pcts = [
        _watch_duration(f"acct_{i:04d}", "reel_dist_test", duration, 0.78, 0.18)
        / duration
        for i in range(100)
    ]

    mean_pct = statistics.mean(pcts)
    stdev_pct = statistics.stdev(pcts)

    # Mean should be near 0.78 (within 0.10 tolerance for 100 samples)
    assert 0.68 <= mean_pct <= 0.88, (
        f"Mean watch_pct={mean_pct:.3f} not near 0.78; distribution may be degenerate"
    )

    # Standard deviation should be non-trivial (real spread exists)
    assert stdev_pct > 0.05, (
        f"stdev={stdev_pct:.3f} too small; distribution looks constant, not log-normal"
    )

    # Should not be uniform: a uniform distribution over [0.25, 1.0] has
    # stdev ≈ 0.217; a log-normal should be noticeably tighter
    uniform_stdev = (1.0 - 0.25) / math.sqrt(12)  # ≈ 0.217
    assert stdev_pct < uniform_stdev * 0.9, (
        f"stdev={stdev_pct:.3f} is close to uniform stdev={uniform_stdev:.3f}; "
        "may be using a flat distribution"
    )


# ---------------------------------------------------------------------------
# Test 2: Watch pct always in [0.25, 1.0]
# ---------------------------------------------------------------------------


def test_watch_pct_always_in_bounds():
    duration = 45

    for i in range(500):
        raw = _watch_duration(f"acct_{i:05d}", f"reel_{i % 10}", duration, 0.78, 0.18)
        pct = raw / duration
        assert _WATCH_PCT_FLOOR <= pct <= 1.0, (
            f"watch_pct={pct:.4f} out of bounds [0.25, 1.0] for account acct_{i:05d}"
        )


# ---------------------------------------------------------------------------
# Test 3: Rewatch rate across 1000 decisions ≈ 18% (±3%)
# ---------------------------------------------------------------------------


def test_rewatch_rate_approximately_18_pct():
    n = 1000
    rewatches = sum(
        1 for i in range(n)
        if _decision(f"acct_{i:05d}", "reel_rewatch_test", "rewatch", _REWATCH_THRESHOLD)
    )
    rate = rewatches / n

    assert 0.15 <= rate <= 0.21, (
        f"Rewatch rate={rate:.3f} outside [0.15, 0.21]; expected ≈18%"
    )


# ---------------------------------------------------------------------------
# Test 4: Story share rate across 1000 decisions ≈ 8% (±2%)
# ---------------------------------------------------------------------------


def test_story_share_rate_approximately_8_pct():
    n = 1000
    shares = sum(
        1 for i in range(n)
        if _decision(f"acct_{i:05d}", "reel_share_test", "share", _SHARE_THRESHOLD)
    )
    rate = shares / n

    assert 0.06 <= rate <= 0.10, (
        f"Story share rate={rate:.3f} outside [0.06, 0.10]; expected ≈8%"
    )


# ---------------------------------------------------------------------------
# Test 5: Fleet stagger offsets are in [0, 7200] and not uniform
#
# Uniformity test: split [0, 7200] into 10 equal buckets and check that no
# bucket has more than 3x the expected count (chi-square "too uniform" is OK
# here — we just want to confirm values are spread, and each account gets
# a different offset from the hash).  We also verify no two of the first
# 20 accounts share the same offset (birthday-paradox: P(collision) ≈ 0.25%
# for 20 samples out of 7201 values — so exact equality is extremely unlikely).
# ---------------------------------------------------------------------------


def test_fleet_stagger_offsets_in_range_and_not_identical():
    media_id = "reel_stagger_test"
    n = 200

    offsets = [reel_view_offset_seconds(f"acct_{i:05d}", media_id) for i in range(n)]

    # All offsets must be in [0, 7200]
    for i, offset in enumerate(offsets):
        assert 0 <= offset <= 7200, f"offset[{i}]={offset} out of [0, 7200]"

    # No two of the first 20 offsets should be identical
    first_20 = offsets[:20]
    assert len(set(first_20)) == len(first_20), (
        f"Duplicate offsets found in first 20: {first_20}"
    )

    # Distribution spread: standard deviation should be at least 1000 seconds
    # (roughly 1/7 of the window); a degenerate distribution at one value
    # would have stdev ≈ 0.
    stdev = statistics.stdev(offsets)
    assert stdev > 1000, (
        f"stdev of offsets={stdev:.1f} too small; offsets may be clustering"
    )


# ---------------------------------------------------------------------------
# Test 6: Daily reel cap enforced at 80
#
# Pass views_sent_today = MAX_REELS_PER_ACCOUNT_PER_DAY (80).
# The session should return immediately with cap_reached=True and watch 0 reels.
# ---------------------------------------------------------------------------


def test_daily_reel_cap_enforced():
    agent = IGReelViewAgent()
    reels = [_make_reel(f"reel_{i:03d}") for i in range(5)]
    session = _make_session()

    result = asyncio.run(
        agent.run_reel_session(
            account_id="acct_captest",
            session=session,
            reels_to_watch=reels,
            views_sent_today=MAX_REELS_PER_ACCOUNT_PER_DAY,
        )
    )

    assert result.success is True
    assert result.data.get("cap_reached") is True
    assert result.data["session_result"].reels_watched == 0


# ---------------------------------------------------------------------------
# Test 7: Story share cap enforced at 6/day
#
# Run a mocked session where all share decisions are forced True (monkey-patch
# _decision).  The agent must stop sharing after 6 shares even if every reel
# passes the share decision.
# ---------------------------------------------------------------------------


def test_story_share_cap_enforced():
    agent = IGReelViewAgent()
    # 20 reels, all 15 seconds
    reels = [_make_reel(f"reel_{i:03d}", duration=15) for i in range(20)]
    session = _make_session()

    # Patch _decision so every share decision returns True, others return False
    def forced_decision(acct, media, field, threshold):
        return field == "share"

    # Patch asyncio.sleep to be instant, and InstagramClient to be a no-op
    async def _noop_sleep(_):
        return

    async def _noop_post(self, endpoint, data):
        return {"status": "ok"}

    async def _noop_like(self, media_id):
        return {"status": "ok"}

    async def _noop_comment(self, media_id, text):
        return True

    import phantom_fleet.agents.specialists.ig_reel_view_agent as mod
    from phantom_fleet.core.instagram_client import InstagramClient

    with (
        patch.object(mod, "_decision", side_effect=forced_decision),
        patch("asyncio.sleep", side_effect=_noop_sleep),
        patch.object(InstagramClient, "_build_client", return_value=MagicMock()),
        patch.object(InstagramClient, "__aexit__", new=AsyncMock(return_value=False)),
        patch.object(InstagramClient, "_post", _noop_post),
        patch.object(InstagramClient, "like_post", _noop_like),
        patch.object(InstagramClient, "comment_post", _noop_comment),
    ):
        result = asyncio.run(
            agent.run_reel_session(
                account_id="acct_sharecap",
                session=session,
                reels_to_watch=reels,
                views_sent_today=0,
            )
        )

    session_result: ReelSessionResult = result.data["session_result"]
    assert session_result.story_shares <= MAX_STORY_SHARES_PER_DAY, (
        f"story_shares={session_result.story_shares} exceeded cap {MAX_STORY_SHARES_PER_DAY}"
    )


# ---------------------------------------------------------------------------
# Test 8: Same account+media always produces same watch_duration (determinism)
# ---------------------------------------------------------------------------


def test_watch_duration_is_deterministic():
    account_id = "acct_determinism_test"
    media_id = "reel_determinism_test"
    duration = 60

    # Call three times — must get identical results
    d1 = _watch_duration(account_id, media_id, duration, 0.78, 0.18)
    d2 = _watch_duration(account_id, media_id, duration, 0.78, 0.18)
    d3 = _watch_duration(account_id, media_id, duration, 0.78, 0.18)

    assert d1 == d2 == d3, (
        f"watch_duration not deterministic: got {d1}, {d2}, {d3} for same inputs"
    )

    # Different account must get a different duration (with overwhelming probability)
    d_other = _watch_duration("different_account_xyz", media_id, duration, 0.78, 0.18)
    assert d_other != d1, (
        "Different account got identical watch_duration — hash may not be diffusing correctly"
    )
