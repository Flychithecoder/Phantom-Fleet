"""
Phantom Fleet warming curves.

Two curves live here:

1) RE_WAKE_CURVE — for accounts coming out of dormancy (e.g. the 219 Tatiana
   + Melodie accounts that went inactive in Oct 2025). Gentler 7-day ramp
   from zero actions to near-steady state, because returning dormant accounts
   are flagged more aggressively than never-used-before accounts.

2) FRESH_WARMUP_CURVE — for brand-new accounts. 28-day conservative ramp
   starting at 3-7 follows/day and ending at 25-30 follows/day steady state.
   User-proven to be below Onimator's historical "22 actions/day survived
   72 days zero bans" but with additional safety buffer for 2026 detection.

Both curves are RANGES. Every number below is (low, high). The actual value
for a specific account on a specific day is sampled per
(account_id, date) via the LogNormal sampler in core.distributions.

No exact values anywhere. No rest days ever. Daily intensity is sampled
separately from the curve (see core.distributions.sample_daily_intensity).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .distributions import sample_int_range, sample_daily_intensity


@dataclass
class DayTargets:
    """Ranges for one day of the curve."""

    follows: tuple[int, int]
    likes: tuple[int, int]
    story_views: tuple[int, int]
    comments: tuple[int, int]
    dms: tuple[int, int] = (0, 0)
    # Informational only; sessions are sampled independently by the agent
    label: str = ""
    # Evening unfollow cleanup (remove non-reciprocators after ~3 days)
    unfollows: tuple[int, int] = (0, 0)


# ---------------------------------------------------------------------------
# Re-wake curve (dormant → steady, 7 days, for the 219 existing accounts)
# ---------------------------------------------------------------------------


RE_WAKE_CURVE: list[DayTargets] = [
    DayTargets((0, 0), (0, 0), (0, 0), (0, 0), (0, 0), "login + scroll only"),
    DayTargets((0, 0), (0, 2), (3, 5), (0, 0), (0, 0), "very light browse"),
    DayTargets((1, 2), (2, 4), (5, 8), (0, 0), (0, 0), "first actions"),
    DayTargets((2, 4), (4, 8), (8, 12), (0, 1), (0, 0), "ramp"),
    DayTargets((3, 6), (6, 12), (10, 15), (0, 1), (0, 0), "ramp"),
    DayTargets((5, 9), (10, 18), (15, 22), (1, 2), (0, 1), "ramp"),
    DayTargets((8, 14), (18, 28), (22, 32), (2, 3), (1, 2), "near steady"),
]


# ---------------------------------------------------------------------------
# Fresh warmup curve (new accounts, 28 days to steady state)
# ---------------------------------------------------------------------------


FRESH_WARMUP_CURVE: list[DayTargets] = [
    # Phase 1 — Dormant (Day 0-2): zero actions, reel scrolling only
    DayTargets((0, 0), (0, 0), (0, 0), (0, 0), (0, 0), "day 0 dormant"),
    DayTargets((0, 0), (0, 0), (0, 0), (0, 0), (0, 0), "day 1 dormant"),
    DayTargets((0, 0), (0, 0), (0, 0), (0, 0), (0, 0), "day 2 dormant"),
    # Phase 2 — First actions (Day 3-7)
    DayTargets((2, 4), (3, 7), (6, 12), (0, 0), (0, 0), "day 3 first actions"),
    DayTargets((2, 5), (4, 9), (8, 14), (0, 0), (0, 0), "day 4"),
    DayTargets((3, 6), (5, 11), (10, 17), (0, 0), (0, 0), "day 5"),
    DayTargets((3, 7), (6, 13), (11, 19), (0, 1), (0, 0), "day 6"),
    DayTargets((4, 8), (7, 15), (13, 22), (0, 1), (0, 0), "day 7"),
    # Phase 3 — Controlled ramp (Day 8-14)
    DayTargets((5, 9), (9, 18), (14, 24), (0, 2), (0, 0), "day 8"),
    DayTargets((5, 10), (11, 20), (16, 27), (0, 2), (0, 0), "day 9"),
    DayTargets((6, 11), (13, 22), (17, 30), (1, 3), (0, 0), "day 10"),
    DayTargets((7, 12), (14, 24), (18, 32), (1, 3), (0, 0), "day 11"),
    DayTargets((7, 13), (16, 26), (20, 34), (1, 3), (0, 0), "day 12"),
    DayTargets((8, 14), (18, 30), (21, 36), (1, 4), (0, 0), "day 13"),
    DayTargets((9, 15), (20, 34), (22, 38), (1, 4), (0, 0), "day 14"),
    # Phase 4 — Sustained ramp (Day 15-21)
    DayTargets((9, 16), (22, 36), (25, 42), (2, 4), (0, 0), "day 15"),
    DayTargets((10, 17), (24, 38), (26, 44), (2, 5), (0, 1), "day 16"),
    DayTargets((11, 18), (26, 42), (28, 47), (2, 5), (0, 2), "day 17 first dm"),
    DayTargets((11, 19), (28, 45), (29, 49), (2, 6), (0, 2), "day 18"),
    DayTargets((12, 20), (30, 48), (31, 52), (3, 6), (1, 2), "day 19"),
    DayTargets((13, 21), (32, 50), (32, 54), (3, 7), (1, 3), "day 20"),
    DayTargets((14, 22), (34, 54), (34, 57), (3, 7), (1, 3), "day 21"),
    # Phase 5 — Established (Day 22-28)
    DayTargets((14, 23), (36, 58), (36, 60), (3, 7), (1, 4), "day 22"),
    DayTargets((15, 24), (38, 60), (38, 62), (4, 8), (1, 4), "day 23"),
    DayTargets((16, 25), (40, 62), (40, 65), (4, 8), (2, 4), "day 24"),
    DayTargets((17, 26), (42, 65), (42, 67), (4, 9), (2, 5), "day 25"),
    DayTargets((17, 27), (44, 68), (43, 70), (5, 9), (2, 5), "day 26"),
    DayTargets((18, 28), (46, 72), (45, 73), (5, 10), (2, 6), "day 27"),
    DayTargets((19, 30), (48, 75), (47, 75), (5, 10), (3, 6), "day 28"),
]


# Day 29+ steady state (sampled per day, never a fixed number)
STEADY_STATE = DayTargets(
    follows=(18, 32),
    likes=(45, 85),
    story_views=(48, 85),
    comments=(5, 12),
    dms=(3, 9),
    label="steady state",
)


# ---------------------------------------------------------------------------
# The main entry point the Warming Agent calls every morning per account.
# ---------------------------------------------------------------------------


@dataclass
class DailyPlan:
    """The plan for one account for one day.

    All numbers are concrete samples ready to drive a schedule. The
    samples are per-(account, date) seeded, so this DailyPlan is
    deterministic for replay/debugging but unique across the fleet.

    Growth action priority:
        HIGH  — follows, story_views, story_reacts  (notification stack)
        LOWER — feed_likes, comments
        CONDITIONAL — dms (only for A/B test variant B accounts)
    """

    account_id: str
    date_iso: str
    day_in_curve: int
    curve_label: str
    intensity_level: str
    intensity_multiplier: float
    weekly_multiplier: float
    persona_aggressiveness: float
    # Core growth actions (HIGH PRIORITY — notification stack engine)
    follows: int              # morning session — follow targets
    story_views: int          # afternoon session — view stories of followed accounts
    story_reacts: int         # afternoon session — ~10% of story_views, auto-computed
    unfollows: int            # evening cleanup — unfollow non-reciprocators
    # Secondary actions (LOWER PRIORITY)
    feed_likes: int           # renamed from likes for clarity
    comments: int
    # DM (only for A/B test variant B accounts — 0 for variant A)
    dms: int = 0

    @property
    def likes(self) -> int:
        """Alias for feed_likes — backwards-compatible with warming orchestrator."""
        return self.feed_likes


def plan_daily_actions(
    account_id: str,
    date_iso: str,
    day_in_curve: int,
    *,
    curve: Sequence[DayTargets] | None = None,
    steady_state: DayTargets = STEADY_STATE,
    persona_aggressiveness: float = 1.0,
    weekly_multiplier: float = 1.0,
) -> DailyPlan:
    """Produce the concrete DailyPlan for one account on one day.

    Arguments:
        account_id: stable unique id of the account
        date_iso: YYYY-MM-DD local to the account's claimed timezone
        day_in_curve: how many days into the curve this account is. 0 = day 0.
            If >= len(curve), the account is past warming and uses steady_state.
        curve: RE_WAKE_CURVE (for dormant accounts) or FRESH_WARMUP_CURVE.
            Defaults to FRESH_WARMUP_CURVE.
        steady_state: the range set to use once past the curve.
        persona_aggressiveness: locked per-account multiplier (0.85-1.15).
            Sampled once at account import, never changes.
        weekly_multiplier: 0.75-1.25 sampled per (persona_id, iso_week).
    """
    if curve is None:
        curve = FRESH_WARMUP_CURVE

    targets = curve[day_in_curve] if day_in_curve < len(curve) else steady_state

    # Pick daily intensity level (never "rest day"; zero is not a level)
    intensity_level, intensity_multiplier = sample_daily_intensity(account_id, date_iso)
    combined_multiplier = intensity_multiplier * weekly_multiplier * persona_aggressiveness

    def _sample(name: str, rng_tuple: tuple[int, int]) -> int:
        low, high = rng_tuple
        if high == 0:
            return 0
        base = sample_int_range(low, high, account_id, date_iso, name)
        return max(0, int(round(base * combined_multiplier)))

    story_views_count = _sample("story_views", targets.story_views)
    # story_reacts is auto-computed as ~10% of story_views.
    # Uses LogNormal(mean=ln(0.10), sigma=0.20) clamped to [0.05, 0.20]
    # so fleet-wide react rates are log-normal, not a flat 10% monoculture.
    import math as _math
    import random as _random
    _react_seed = sample_int_range(0, 2**31 - 1, account_id, date_iso, "react_rate_seed")
    _react_rng = _random.Random(_react_seed)
    _raw_rate = _react_rng.lognormvariate(_math.log(0.10), 0.20)
    _react_rate = max(0.05, min(0.20, _raw_rate))
    story_reacts_count = max(0, int(round(story_views_count * _react_rate)))

    return DailyPlan(
        account_id=account_id,
        date_iso=date_iso,
        day_in_curve=day_in_curve,
        curve_label=targets.label,
        intensity_level=intensity_level,
        intensity_multiplier=intensity_multiplier,
        weekly_multiplier=weekly_multiplier,
        persona_aggressiveness=persona_aggressiveness,
        follows=_sample("follows", targets.follows),
        feed_likes=_sample("likes", targets.likes),
        story_views=story_views_count,
        story_reacts=story_reacts_count,
        unfollows=_sample("unfollows", getattr(targets, "unfollows", (0, 0))),
        comments=_sample("comments", targets.comments),
        dms=_sample("dms", targets.dms),
    )
