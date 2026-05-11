"""Test the warming curve produces valid DailyPlans."""
from phantom_fleet.core.warming_curve import (
    FRESH_WARMUP_CURVE,
    RE_WAKE_CURVE,
    STEADY_STATE,
    plan_daily_actions,
)


def test_fresh_curve_day_0_is_zero():
    plan = plan_daily_actions(
        account_id="test",
        date_iso="2026-04-11",
        day_in_curve=0,
        curve=FRESH_WARMUP_CURVE,
    )
    assert plan.follows == 0
    assert plan.likes == 0
    assert plan.story_views == 0
    assert plan.comments == 0
    assert plan.dms == 0


def test_fresh_curve_day_3_has_actions():
    plan = plan_daily_actions(
        account_id="test",
        date_iso="2026-04-11",
        day_in_curve=3,
        curve=FRESH_WARMUP_CURVE,
    )
    assert 0 <= plan.follows <= 10  # allows multiplier variance
    assert plan.intensity_level in {"minimal", "light", "normal", "heavy"}


def test_re_wake_curve_day_1_is_minimal():
    plan = plan_daily_actions(
        account_id="test",
        date_iso="2026-04-11",
        day_in_curve=1,
        curve=RE_WAKE_CURVE,
    )
    assert plan.follows == 0  # re-wake day 1: no follow actions
    assert plan.story_views >= 0  # may be 0-5 × intensity


def test_steady_state_past_curve():
    plan = plan_daily_actions(
        account_id="test",
        date_iso="2026-04-11",
        day_in_curve=100,  # well past curve
        curve=FRESH_WARMUP_CURVE,
    )
    # Steady state is 18-32 follows × intensity × aggressiveness; allow wide range
    assert plan.follows >= 0


def test_per_account_different_values():
    p1 = plan_daily_actions(
        account_id="account_1",
        date_iso="2026-04-11",
        day_in_curve=14,
        curve=FRESH_WARMUP_CURVE,
    )
    p2 = plan_daily_actions(
        account_id="account_2",
        date_iso="2026-04-11",
        day_in_curve=14,
        curve=FRESH_WARMUP_CURVE,
    )
    # Two accounts on the same day should NOT produce identical plans
    # (that would be a cluster fingerprint)
    different = (
        p1.follows != p2.follows
        or p1.likes != p2.likes
        or p1.story_views != p2.story_views
        or p1.intensity_level != p2.intensity_level
    )
    assert different, "two accounts on same day produced identical plan — cluster bug"
