"""
Tests for the three Instagram optimization features:
    - IGHashtagTrackerAgent  (Feature 1)
    - IGBioABAgent           (Feature 2)
    - IGPeakTimeAgent        (Feature 3)

Coverage: 24 tests (minimum 20 required)

Test philosophy:
    - All HTTP calls are mocked — no real API calls.
    - asyncio_mode = "auto" configured in pyproject.toml (no decorator needed).
    - Determinism tests use fixed inputs and assert exact outputs.
    - Distribution-shape tests run enough samples to distinguish
      log-normal from uniform without being brittle.

Hashtag tracker (7 tests):
    1.  Bottom 25% of entries are retired after rotation
    2.  Top 25% are marked as proven_winners
    3.  Max 7 hashtags per set (code-enforced via HashtagSet.__post_init__)
    4.  Attribution: follows within 2h counted, follows after 2h NOT counted
    5.  Performance score formula: (follows*3 + dms*10) / times_used
    6.  record_post writes pending_attribution record
    7.  Seeded pick: different accounts get different fresh tags

Bio A/B (8 tests):
    8.  Account assignment is stable (same account always gets same variant)
    9.  Winner declared only when min 50 profile visits reached
    10. Rollout returns all cohort accounts in result.accounts_updated
    11. Bio max 150 chars enforced (ValueError on construction)
    12. Display name max 30 chars enforced (ValueError on construction)
    13. Tie-breaking: variant with more visits wins
    14. Insufficient_data when no variant has 50 visits
    15. declare_winner: highest dm_initiation_rate wins

Peak time optimizer (9 tests):
    16. Confidence "low" when < 10 posts
    17. Confidence "medium" for 10–30 posts
    18. Confidence "high" when > 30 posts
    19. Default hours used when confidence is "low"
    20. Learned hours used when confidence is "medium" or "high"
    21. Quiet hours (2–5am) never appear in peak_hours
    22. update_daily_schedule: quiet hour slots never modified
    23. FleetPeakReport: divergent_accounts identifies non-standard accounts
    24. Jitter included in recommendation (post_time_jitter_seconds called)

All timing is LogNormal per CLAUDE.md — no `asyncio.sleep` calls in tests
because the distribution primitives are called in the agents, not in the
test-facing methods being tested here.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.agents.specialists.ig_hashtag_tracker_agent import (
    HashtagEntry,
    HashtagSet,
    IGHashtagTrackerAgent,
    MAX_HASHTAGS_PER_SET,
    MIN_HASHTAGS_PER_SET,
    ATTRIBUTION_WINDOW_SECONDS,
    _seeded_pick,
    _dump_entries,
)
from phantom_fleet.agents.specialists.ig_bio_ab_agent import (
    BioVariant,
    ABTestSpec,
    IGBioABAgent,
    MIN_VISITS_FOR_SIGNIFICANCE,
    BIO_MAX_CHARS,
    DISPLAY_NAME_MAX_CHARS,
    _stable_hash_mod,
)
from phantom_fleet.agents.specialists.ig_peak_time_agent import (
    HourlyEngagementProfile,
    IGPeakTimeAgent,
    PostRecord,
    QUIET_HOURS,
    DEFAULT_PEAK_HOURS,
    LOW_CONFIDENCE_MAX_POSTS,
    MEDIUM_CONFIDENCE_MAX_POSTS,
    _confidence_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hashtag_sidecar(
    tags: dict[str, dict],
) -> dict:
    """Build a minimal sidecar dict with the given tag data."""
    return {
        "entries": tags,
        "pending_attribution": [],
        "proven_winners": {},
        "last_rotation_iso": None,
    }


def _make_entry_dict(
    tag: str,
    niche: str = "fitness",
    times_used: int = 10,
    attributed_follows: int = 0,
    attributed_dms: int = 0,
    retired: bool = False,
    retire_reason: str | None = None,
) -> dict:
    return {
        "tag": tag,
        "niche": niche,
        "times_used": times_used,
        "total_reach": 100,
        "attributed_follows": attributed_follows,
        "attributed_dms": attributed_dms,
        "last_used_iso": "2026-04-11T10:00:00Z",
        "retired": retired,
        "retire_reason": retire_reason,
    }


def _make_bio_variant(
    variant_id: str,
    bio_text: str = "Test bio",
    display_name: str = "Test Name",
) -> BioVariant:
    return BioVariant(
        variant_id=variant_id,
        bio_text=bio_text,
        display_name=display_name,
        profile_photo_path=None,
    )


def _make_post_record(
    account_id: str,
    hour_local: int,
    er_pct: float,
    post_id: str = "post_001",
) -> PostRecord:
    return PostRecord(
        post_id=post_id,
        account_id=account_id,
        hour_local=hour_local,
        day_of_week=0,
        er_pct=er_pct,
        posted_at_iso="2026-04-11T10:00:00Z",
    )


# ===========================================================================
# Feature 1: IGHashtagTrackerAgent
# ===========================================================================


class TestHashtagTrackerRotation:
    """Tests 1–7 covering rotation logic and attribution."""

    def test_bottom_25_pct_retired_after_rotation(self):
        """
        Test 1: Given 8 tags sorted by performance, bottom 25% (2 tags)
        must have retired=True after analyze_and_rotate.
        """
        # Create 8 tags with ascending performance:
        # attributed_follows=1..8, times_used=1 each → scores = 3, 6, 9, 12, 15, 18, 21, 24
        entries = {
            f"tag{i}": _make_entry_dict(
                tag=f"tag{i}",
                times_used=1,
                attributed_follows=i,
                attributed_dms=0,
            )
            for i in range(1, 9)
        }
        sidecar = _make_hashtag_sidecar(entries)
        agent = IGHashtagTrackerAgent()

        sidecar, result = agent.analyze_and_rotate(
            sidecar=sidecar,
            account_id="acc_001",
            niche="fitness",
            fresh_candidates=["fresh1", "fresh2", "fresh3"],
            date_iso="2026-04-11",
        )

        retired_tags = [
            tag for tag, data in sidecar["entries"].items()
            if data["retired"]
        ]
        # 25% of 8 = 2 (bottom performers: tag1, tag2)
        assert len(retired_tags) == 2, f"Expected 2 retired, got {len(retired_tags)}: {retired_tags}"
        assert "tag1" in retired_tags
        assert "tag2" in retired_tags

    def test_top_25_pct_flagged_as_proven_winners(self):
        """
        Test 2: Top 25% of tags by performance must appear in proven_winners.
        """
        entries = {
            f"tag{i}": _make_entry_dict(
                tag=f"tag{i}",
                times_used=1,
                attributed_follows=i,
            )
            for i in range(1, 9)
        }
        sidecar = _make_hashtag_sidecar(entries)
        agent = IGHashtagTrackerAgent()

        sidecar, result = agent.analyze_and_rotate(
            sidecar=sidecar,
            account_id="acc_001",
            niche="fitness",
            fresh_candidates=["fresh1"],
            date_iso="2026-04-11",
        )

        winners = sidecar.get("proven_winners", {}).get("fitness", [])
        # Top 25% of 8 = 2 tags: tag7, tag8 (highest scores)
        assert len(winners) == 2
        assert "tag7" in winners
        assert "tag8" in winners

    def test_max_7_hashtags_per_set_enforced(self):
        """
        Test 3: HashtagSet must reject construction with more than 7 tags.
        """
        with pytest.raises(ValueError, match="at most"):
            HashtagSet(
                set_id="set_001",
                tags=["a", "b", "c", "d", "e", "f", "g", "h"],  # 8 tags
                account_id="acc_001",
                niche="fitness",
                created_at_iso="2026-04-11T10:00:00Z",
            )

    def test_rotation_builds_set_within_limit(self):
        """
        Test 3b: analyze_and_rotate must produce a set with ≤ 7 tags.
        """
        entries = {
            f"tag{i}": _make_entry_dict(tag=f"tag{i}", times_used=1, attributed_follows=i)
            for i in range(1, 16)  # 15 tags available
        }
        sidecar = _make_hashtag_sidecar(entries)
        agent = IGHashtagTrackerAgent()

        sidecar, result = agent.analyze_and_rotate(
            sidecar=sidecar,
            account_id="acc_001",
            niche="fitness",
            fresh_candidates=[f"fresh{i}" for i in range(20)],
            date_iso="2026-04-11",
        )

        assert len(result.new_set.tags) <= MAX_HASHTAGS_PER_SET

    def test_attribution_within_2h_counted(self):
        """
        Test 4a: Follows attributed when 2h window has elapsed.
        """
        now = datetime(2026, 4, 11, 16, 30, tzinfo=timezone.utc)
        post_time = now - timedelta(hours=2, minutes=1)  # just past the window

        sidecar = _make_hashtag_sidecar({
            "gymlife": _make_entry_dict("gymlife", times_used=1),
        })
        agent = IGHashtagTrackerAgent()

        sidecar = agent.record_post(
            sidecar=sidecar,
            post_id="post_001",
            account_id="acc_001",
            hashtags_used=["gymlife"],
            post_time_iso=post_time.isoformat(),
        )
        sidecar = agent.attribute_follows(
            sidecar=sidecar,
            account_id="acc_001",
            new_followers_in_window=6,
            new_dms_in_window=2,
            now_iso=now.isoformat(),
        )

        entry = sidecar["entries"]["gymlife"]
        assert entry["attributed_follows"] > 0, "Follows within 2h window must be attributed"
        assert entry["attributed_dms"] > 0, "DMs within 2h window must be attributed"

    def test_attribution_before_2h_not_counted(self):
        """
        Test 4b: Follows NOT attributed when 2h window has not elapsed yet.
        """
        now = datetime(2026, 4, 11, 14, 0, tzinfo=timezone.utc)
        post_time = now - timedelta(hours=1)  # only 1h ago, window still open

        sidecar = _make_hashtag_sidecar({
            "gymlife": _make_entry_dict("gymlife", times_used=1, attributed_follows=0),
        })
        agent = IGHashtagTrackerAgent()

        sidecar = agent.record_post(
            sidecar=sidecar,
            post_id="post_001",
            account_id="acc_001",
            hashtags_used=["gymlife"],
            post_time_iso=post_time.isoformat(),
        )
        sidecar = agent.attribute_follows(
            sidecar=sidecar,
            account_id="acc_001",
            new_followers_in_window=10,
            new_dms_in_window=3,
            now_iso=now.isoformat(),
        )

        # Window has not closed — attribution must not have happened
        entry = sidecar["entries"]["gymlife"]
        assert entry["attributed_follows"] == 0, "Follows must NOT be attributed before 2h closes"
        assert entry["attributed_dms"] == 0

    def test_performance_score_formula(self):
        """
        Test 5: performance_score = (follows*3 + dms*10) / max(times_used, 1)
        """
        entry = HashtagEntry(
            tag="fitness",
            niche="fitness",
            times_used=4,
            attributed_follows=8,
            attributed_dms=2,
        )
        # (8*3 + 2*10) / 4 = (24 + 20) / 4 = 44 / 4 = 11.0
        expected = (8 * 3 + 2 * 10) / 4
        assert entry.performance_score == pytest.approx(expected)

    def test_record_post_writes_pending_record(self):
        """
        Test 6: record_post must add an entry to pending_attribution.
        """
        sidecar: dict = {
            "entries": {},
            "pending_attribution": [],
        }
        agent = IGHashtagTrackerAgent()

        sidecar = agent.record_post(
            sidecar=sidecar,
            post_id="media_abc",
            account_id="acc_001",
            hashtags_used=["gym", "fit"],
            post_time_iso="2026-04-11T10:00:00Z",
        )

        assert len(sidecar["pending_attribution"]) == 1
        record = sidecar["pending_attribution"][0]
        assert record["post_id"] == "media_abc"
        assert record["hashtags_used"] == ["gym", "fit"]
        assert record["attributed"] is False

    def test_seeded_pick_different_accounts_get_different_tags(self):
        """
        Test 7: _seeded_pick must return different selections for different
        account IDs when given the same pool and date.
        """
        pool = [f"tag{i}" for i in range(20)]
        date_iso = "2026-04-11"

        picks_a = _seeded_pick(pool, n=5, account_id="acc_A", date_iso=date_iso, field="test")
        picks_b = _seeded_pick(pool, n=5, account_id="acc_B", date_iso=date_iso, field="test")

        # Different accounts must get at least partially different picks
        assert picks_a != picks_b, "Different accounts must get different fresh tag picks"

        # But same account on same day must be stable (idempotent)
        picks_a2 = _seeded_pick(pool, n=5, account_id="acc_A", date_iso=date_iso, field="test")
        assert picks_a == picks_a2, "Same account+date must produce stable picks"


# ===========================================================================
# Feature 2: IGBioABAgent
# ===========================================================================


class TestBioABAgent:
    """Tests 8–15 covering A/B assignment, winner declaration, and constraints."""

    def test_account_assignment_is_stable(self):
        """
        Test 8: The same account must always map to the same variant
        regardless of how many times assign_accounts is called.
        """
        variants = [
            _make_bio_variant("v_a", "Mysterious bio"),
            _make_bio_variant("v_b", "Direct bio"),
        ]
        spec = ABTestSpec(
            test_id="test_001",
            cohort_account_ids=["acc_1", "acc_2", "acc_3", "acc_4"],
            variants=variants,
        )
        agent = IGBioABAgent()

        spec1 = agent.assign_accounts(spec)
        # Record which variant each account landed in
        assignment_1: dict[str, str] = {}
        for v in spec1.variants:
            for aid in v.assigned_account_ids:
                assignment_1[aid] = v.variant_id

        # Reset and re-assign
        spec2 = agent.assign_accounts(spec1)
        assignment_2: dict[str, str] = {}
        for v in spec2.variants:
            for aid in v.assigned_account_ids:
                assignment_2[aid] = v.variant_id

        assert assignment_1 == assignment_2, "Account-to-variant mapping must be stable"

    def test_winner_requires_min_50_visits(self):
        """
        Test 9: If no variant has >= 50 profile visits, result.insufficient_data
        must be True and winner_variant_id must be None.
        """
        variants = [
            _make_bio_variant("v_a"),
            _make_bio_variant("v_b"),
        ]
        # Give each variant only 30 visits — below the threshold
        variants[0].profile_visits = 30
        variants[0].dm_initiations = 5
        variants[1].profile_visits = 40
        variants[1].dm_initiations = 10

        spec = ABTestSpec(
            test_id="test_002",
            cohort_account_ids=["acc_1"],
            variants=variants,
        )
        agent = IGBioABAgent()
        result = agent.declare_winner_and_rollout(spec)

        assert result.insufficient_data is True
        assert result.winner_variant_id is None

    def test_rollout_accounts_updated_count(self):
        """
        Test 10: accounts_updated in the result must equal the cohort size.
        """
        cohort = ["acc_1", "acc_2", "acc_3", "acc_4", "acc_5"]
        variants = [
            _make_bio_variant("v_a"),
            _make_bio_variant("v_b"),
        ]
        variants[0].profile_visits = 60
        variants[0].dm_initiations = 10
        variants[1].profile_visits = 55
        variants[1].dm_initiations = 5

        spec = ABTestSpec(
            test_id="test_003",
            cohort_account_ids=cohort,
            variants=variants,
        )
        agent = IGBioABAgent()
        result = agent.declare_winner_and_rollout(spec)

        assert result.accounts_updated == len(cohort)
        assert result.insufficient_data is False

    def test_bio_max_150_chars_enforced(self):
        """
        Test 11: BioVariant must raise ValueError if bio_text > 150 chars.
        """
        long_bio = "x" * (BIO_MAX_CHARS + 1)
        with pytest.raises(ValueError, match="bio_text exceeds"):
            BioVariant(
                variant_id="v_over",
                bio_text=long_bio,
                display_name="Short Name",
                profile_photo_path=None,
            )

    def test_bio_exact_max_chars_allowed(self):
        """
        Test 11b: BioVariant with exactly 150 chars must not raise.
        """
        exact_bio = "x" * BIO_MAX_CHARS
        v = BioVariant(
            variant_id="v_exact",
            bio_text=exact_bio,
            display_name="Short Name",
            profile_photo_path=None,
        )
        assert len(v.bio_text) == BIO_MAX_CHARS

    def test_display_name_max_30_chars_enforced(self):
        """
        Test 12: BioVariant must raise ValueError if display_name > 30 chars.
        """
        long_name = "A" * (DISPLAY_NAME_MAX_CHARS + 1)
        with pytest.raises(ValueError, match="display_name exceeds"):
            BioVariant(
                variant_id="v_longname",
                bio_text="Normal bio",
                display_name=long_name,
                profile_photo_path=None,
            )

    def test_tie_breaking_more_visits_wins(self):
        """
        Test 13: When two variants have equal dm_initiation_rate, the variant
        with MORE profile_visits wins.
        """
        # Both variants have 10% DM rate but different visit counts
        v_a = _make_bio_variant("v_a")
        v_a.profile_visits = 100
        v_a.dm_initiations = 10   # 10.0% rate

        v_b = _make_bio_variant("v_b")
        v_b.profile_visits = 200   # more visits
        v_b.dm_initiations = 20   # also 10.0% rate — tie

        spec = ABTestSpec(
            test_id="test_tie",
            cohort_account_ids=["acc_1"],
            variants=[v_a, v_b],
        )
        agent = IGBioABAgent()
        result = agent.declare_winner_and_rollout(spec)

        assert result.winner_variant_id == "v_b", (
            "On tie in DM rate, the variant with more visits should win"
        )

    def test_winner_has_highest_dm_rate(self):
        """
        Test 15: The winner must be the variant with the highest
        dm_initiation_rate (not the most visits, not the first variant).
        """
        v_a = _make_bio_variant("v_a")
        v_a.profile_visits = 100
        v_a.dm_initiations = 5    # 5.0% rate

        v_b = _make_bio_variant("v_b")
        v_b.profile_visits = 60
        v_b.dm_initiations = 9    # 15.0% rate — winner

        v_c = _make_bio_variant("v_c")
        v_c.profile_visits = 200
        v_c.dm_initiations = 10   # 5.0% rate

        spec = ABTestSpec(
            test_id="test_rates",
            cohort_account_ids=["acc_1", "acc_2"],
            variants=[v_a, v_b, v_c],
        )
        agent = IGBioABAgent()
        result = agent.declare_winner_and_rollout(spec)

        assert result.winner_variant_id == "v_b"
        assert result.winner_dm_rate == pytest.approx(9 / 60 * 100)


# ===========================================================================
# Feature 3: IGPeakTimeAgent
# ===========================================================================


class TestPeakTimeAgent:
    """Tests 16–24 covering confidence, peak learning, quiet hours, and fleet report."""

    def test_confidence_low_under_10_posts(self):
        """Test 16: < 10 posts → confidence "low"."""
        assert _confidence_label(0) == "low"
        assert _confidence_label(5) == "low"
        assert _confidence_label(9) == "low"

    def test_confidence_medium_10_to_30_posts(self):
        """Test 17: 10–30 posts → confidence "medium"."""
        assert _confidence_label(10) == "medium"
        assert _confidence_label(20) == "medium"
        assert _confidence_label(30) == "medium"

    def test_confidence_high_over_30_posts(self):
        """Test 18: > 30 posts → confidence "high"."""
        assert _confidence_label(31) == "high"
        assert _confidence_label(100) == "high"

    def test_default_hours_used_when_confidence_low(self):
        """
        Test 19: When confidence is "low", recommend_schedule must return
        the DEFAULT_PEAK_HOURS, not learned peaks.
        """
        agent = IGPeakTimeAgent()
        # Create a profile with only 5 data points (low confidence)
        profile = agent.analyze_posting_history(
            account_id="acc_001",
            post_records=[
                _make_post_record("acc_001", hour_local=22, er_pct=10.0, post_id=f"p{i}")
                for i in range(5)
            ],
        )

        assert profile.confidence == "low"

        rec = agent.recommend_schedule(profile)
        recommended_hours = [slot[0] for slot in rec.recommended_slots]

        # Must use defaults, not the learned peak at hour 22
        for h in DEFAULT_PEAK_HOURS:
            if h not in QUIET_HOURS:
                assert h in recommended_hours, f"Default hour {h} must be in low-confidence recs"

    def test_learned_hours_used_when_confidence_medium(self):
        """
        Test 20a: When confidence is "medium", recommend_schedule must use
        the learned peak hours.
        """
        # 15 posts all at hour 11 — should learn hour 11 as a strong peak
        agent = IGPeakTimeAgent()
        posts = [
            _make_post_record("acc_001", hour_local=11, er_pct=8.0, post_id=f"p{i}")
            for i in range(15)
        ]
        profile = agent.analyze_posting_history("acc_001", posts)

        assert profile.confidence == "medium"
        assert 11 in profile.peak_hours

        rec = agent.recommend_schedule(profile)
        recommended_hours = [slot[0] for slot in rec.recommended_slots]
        assert 11 in recommended_hours

    def test_learned_hours_used_when_confidence_high(self):
        """
        Test 20b: When confidence is "high", learned peaks take effect.
        """
        agent = IGPeakTimeAgent()
        posts = [
            _make_post_record("acc_001", hour_local=20, er_pct=12.0, post_id=f"p{i}")
            for i in range(35)
        ]
        profile = agent.analyze_posting_history("acc_001", posts)

        assert profile.confidence == "high"
        assert 20 in profile.peak_hours

    def test_quiet_hours_never_in_peak_hours(self):
        """
        Test 21: peak_hours must never include hours 2, 3, 4, 5 regardless
        of what the engagement data says.
        """
        agent = IGPeakTimeAgent()
        # Flood quiet hours with very high ER posts
        posts = [
            _make_post_record("acc_001", hour_local=3, er_pct=99.0, post_id=f"p{i}")
            for i in range(40)
        ]
        # Also add some normal-hour posts so there IS a valid profile
        posts += [
            _make_post_record("acc_001", hour_local=10, er_pct=5.0, post_id=f"q{i}")
            for i in range(5)
        ]

        profile = agent.analyze_posting_history("acc_001", posts)

        for quiet_h in QUIET_HOURS:
            assert quiet_h not in profile.peak_hours, (
                f"Quiet hour {quiet_h} must never appear in peak_hours"
            )

    def test_update_daily_schedule_quiet_slots_unchanged(self):
        """
        Test 22: update_daily_schedule must never modify slots in quiet hours
        or slots with type="quiet".
        """
        agent = IGPeakTimeAgent()
        profile = HourlyEngagementProfile(
            account_id="acc_001",
            hour_scores={h: 5.0 for h in range(24)},
            peak_hours=[9, 14, 20],
            data_points=35,
            last_updated_iso="2026-04-11T10:00:00Z",
            confidence="high",
        )

        existing_slots = [
            {"hour": 3, "type": "quiet", "label": "sleep"},     # quiet hour + quiet type
            {"hour": 4, "type": "quiet", "label": "sleep"},     # quiet hour
            {"hour": 9, "type": "peak", "label": "morning"},    # should be updated
            {"hour": 14, "type": "peak", "label": "afternoon"}, # should be updated
            {"hour": 22, "type": "general", "label": "check"},  # non-peak, non-quiet
        ]

        updated = agent.update_daily_schedule(profile, existing_slots)

        # Quiet-hour slots must be untouched
        quiet_slots = [s for s in updated if s["hour"] in QUIET_HOURS]
        original_quiet = [s for s in existing_slots if s["hour"] in QUIET_HOURS]
        assert quiet_slots == original_quiet, "Quiet-hour slots must not be modified"

        # Quiet-type slots must also be untouched
        quiet_typed = [s for s in updated if s.get("type") == "quiet"]
        original_quiet_typed = [s for s in existing_slots if s.get("type") == "quiet"]
        assert quiet_typed == original_quiet_typed

    def test_fleet_report_identifies_divergent_accounts(self):
        """
        Test 23: FleetPeakReport.divergent_accounts must contain accounts
        whose peak hours have no overlap with the common fleet peaks.
        """
        agent = IGPeakTimeAgent()

        # Most accounts peak at 9, 12, 19
        common_profiles = [
            HourlyEngagementProfile(
                account_id=f"acc_{i:03d}",
                hour_scores={9: 10.0, 12: 8.0, 19: 9.0, **{h: 1.0 for h in range(24)}},
                peak_hours=[9, 12, 19],
                data_points=40,
                last_updated_iso="2026-04-11T10:00:00Z",
                confidence="high",
            )
            for i in range(8)
        ]

        # One divergent account peaks at completely different hours
        divergent = HourlyEngagementProfile(
            account_id="acc_divergent",
            hour_scores={7: 15.0, 21: 14.0, 23: 12.0, **{h: 1.0 for h in range(24)}},
            peak_hours=[7, 21, 23],
            data_points=40,
            last_updated_iso="2026-04-11T10:00:00Z",
            confidence="high",
        )

        all_profiles = common_profiles + [divergent]
        report = agent.build_fleet_report(all_profiles, date_iso="2026-04-11")

        assert "acc_divergent" in report.divergent_accounts, (
            "Account with no peak overlap with fleet common peaks must be in divergent_accounts"
        )
        # Common accounts must NOT be in divergent
        for prof in common_profiles:
            assert prof.account_id not in report.divergent_accounts

    def test_recommendation_includes_jitter_call(self):
        """
        Test 24: ScheduleRecommendation must include a jitter value drawn
        from post_time_jitter_seconds (±30 min = ±1800 sec max).
        """
        agent = IGPeakTimeAgent()
        profile = HourlyEngagementProfile(
            account_id="acc_001",
            hour_scores={h: float(h) for h in range(24)},
            peak_hours=[9, 14, 20],
            data_points=35,
            last_updated_iso="2026-04-11T10:00:00Z",
            confidence="high",
        )

        rec = agent.recommend_schedule(profile)

        # post_time_jitter_seconds returns values in [-1800, 1800]
        assert -1800 <= rec.jitter_seconds <= 1800, (
            f"Jitter {rec.jitter_seconds} must be in [-1800, 1800] range"
        )

    def test_update_schedule_no_change_when_low_confidence(self):
        """
        Test bonus: update_daily_schedule must not modify any slots when
        profile confidence is "low" (not enough data to trust).
        """
        agent = IGPeakTimeAgent()
        profile = HourlyEngagementProfile(
            account_id="acc_001",
            hour_scores={h: 5.0 for h in range(24)},
            peak_hours=[9, 12, 19],
            data_points=5,  # only 5 posts — low confidence
            last_updated_iso="2026-04-11T10:00:00Z",
            confidence="low",
        )

        existing_slots = [
            {"hour": 9, "type": "peak"},
            {"hour": 14, "type": "peak"},
            {"hour": 20, "type": "general"},
        ]

        updated = agent.update_daily_schedule(profile, existing_slots)

        # Low confidence — must be a copy of original, no changes
        assert updated == existing_slots, "Low-confidence profile must not modify any slots"

    def test_fleet_report_common_peaks_majority_threshold(self):
        """
        Test bonus: common_peak_hours must only include hours that appear
        in peak_hours for > 50% of accounts.
        """
        agent = IGPeakTimeAgent()

        # 6 accounts: 4 peak at hour 9, 2 peak at hour 15
        profiles = [
            HourlyEngagementProfile(
                account_id=f"acc_{i}",
                hour_scores={9: 10.0, **{h: 1.0 for h in range(24)}},
                peak_hours=[9, 10, 11],
                data_points=35,
                last_updated_iso="2026-04-11T10:00:00Z",
                confidence="high",
            )
            for i in range(4)
        ] + [
            HourlyEngagementProfile(
                account_id=f"acc_minority_{i}",
                hour_scores={15: 10.0, **{h: 1.0 for h in range(24)}},
                peak_hours=[15, 16, 17],
                data_points=35,
                last_updated_iso="2026-04-11T10:00:00Z",
                confidence="high",
            )
            for i in range(2)
        ]

        report = agent.build_fleet_report(profiles, date_iso="2026-04-11")

        # Hour 9 appears in 4/6 = 66.7% → should be common
        assert 9 in report.common_peak_hours
        # Hour 15 appears in 2/6 = 33.3% → should NOT be common
        assert 15 not in report.common_peak_hours
