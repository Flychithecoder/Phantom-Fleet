"""
Instagram platform module — warming curve + per-account LogNormal budgets.

IG is the root account of the fleet: the one Threads replies into, the
one Reddit/TikTok personas crib fingerprints from. Its warming curve
runs LONGER than Threads (28 days vs 14) because IG's new-account
detection is tighter and because the content cadence on IG is slower
(stories + 2-3 posts per week beats Threads' reply-heavy stream).

Primitives:
    follow         — follow a target account
    like           — like a post
    story_view     — open a story card
    post           — publish a feed post or reel

Distribution rule (CLAUDE.md): no `random.uniform` anywhere. Every
budget sample is a LogNormal draw whose seed is SHA256(account_id + day
+ kind), so the fleet's per-account fingerprints are both unique and
reproducible for audit.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Literal

IG_PACKAGE = "com.instagram.android"

# Longer than Threads — IG new-account detection runs hot the first 3 weeks.
WARMING_DAYS = 28

IGActionKind = Literal["follow", "like", "story_view", "post"]


# ---------------------------------------------------------------------------
# Warming curve — 28 days, LogNormal-scaled
# ---------------------------------------------------------------------------
#
# Shape:
#   Days  1-4   : passive — just story_views
#   Days  5-10  : discovery — follow + likes ramp
#   Days 11-18  : engagement — first comments (via "like" collapse) + first post
#   Days 19-28  : full operating — posts 1-2/day, stories, follow budget capped
#
# Numbers are the MEAN of a LogNormal draw. Per-account jitter comes from
# a deterministic seed on account_id + day + kind.

_BASE_BUDGETS: dict[int, dict[IGActionKind, float]] = {
    1:  {"follow": 0,  "like": 0,  "story_view": 5,  "post": 0},
    2:  {"follow": 1,  "like": 2,  "story_view": 8,  "post": 0},
    3:  {"follow": 2,  "like": 4,  "story_view": 10, "post": 0},
    4:  {"follow": 3,  "like": 6,  "story_view": 12, "post": 0},
    5:  {"follow": 4,  "like": 8,  "story_view": 14, "post": 0},
    6:  {"follow": 5,  "like": 10, "story_view": 16, "post": 0},
    7:  {"follow": 6,  "like": 12, "story_view": 18, "post": 0},
    8:  {"follow": 7,  "like": 14, "story_view": 20, "post": 1},
    9:  {"follow": 8,  "like": 16, "story_view": 22, "post": 1},
    10: {"follow": 9,  "like": 18, "story_view": 24, "post": 1},
    11: {"follow": 10, "like": 20, "story_view": 26, "post": 1},
    12: {"follow": 11, "like": 22, "story_view": 28, "post": 1},
    13: {"follow": 12, "like": 24, "story_view": 30, "post": 1},
    14: {"follow": 13, "like": 26, "story_view": 32, "post": 2},
    15: {"follow": 14, "like": 28, "story_view": 34, "post": 2},
    16: {"follow": 15, "like": 30, "story_view": 36, "post": 2},
    17: {"follow": 16, "like": 32, "story_view": 38, "post": 2},
    18: {"follow": 17, "like": 34, "story_view": 40, "post": 2},
    19: {"follow": 18, "like": 36, "story_view": 42, "post": 2},
    20: {"follow": 19, "like": 38, "story_view": 44, "post": 2},
    21: {"follow": 20, "like": 40, "story_view": 46, "post": 2},
    22: {"follow": 20, "like": 42, "story_view": 48, "post": 2},
    23: {"follow": 20, "like": 44, "story_view": 50, "post": 3},
    24: {"follow": 20, "like": 46, "story_view": 52, "post": 3},
    25: {"follow": 20, "like": 48, "story_view": 54, "post": 3},
    26: {"follow": 20, "like": 50, "story_view": 56, "post": 3},
    27: {"follow": 20, "like": 52, "story_view": 58, "post": 3},
    28: {"follow": 20, "like": 54, "story_view": 60, "post": 3},
}

# LogNormal sigma per action. Tighter for high-cadence actions (IG caps
# follow hard, so variance is low), wider for creative (posts, stories).
_SIGMA: dict[IGActionKind, float] = {
    "follow":     0.20,
    "like":       0.25,
    "story_view": 0.30,
    "post":       0.45,
}


@dataclass(frozen=True)
class IGDailyBudget:
    day:        int
    follow:     int
    like:       int
    story_view: int
    post:       int

    @property
    def total(self) -> int:
        return self.follow + self.like + self.story_view + self.post

    def as_dict(self) -> dict:
        return {
            "day":        self.day,
            "follow":     self.follow,
            "like":       self.like,
            "story_view": self.story_view,
            "post":       self.post,
            "total":      self.total,
        }


def _seed(account_id: str, day: int, kind: str) -> float:
    digest = hashlib.sha256(f"ig:{account_id}:{day}:{kind}".encode()).hexdigest()
    return int(digest[:16], 16) / 0xFFFF_FFFF_FFFF_FFFF


def _lognormal_sample(mean: float, sigma: float, u: float) -> float:
    """
    LogNormal(μ, σ²) via Abramowitz-Stegun 26.2.23 inverse normal — same
    math as threads.py so the audit shape checks compare apples to apples.
    """
    if u <= 0 or u >= 1:
        u = 0.5
    t = math.sqrt(-2.0 * math.log(min(u, 1 - u)))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
    if u > 0.5:
        z = -z
    mu = math.log(mean) - 0.5 * sigma * sigma
    return math.exp(mu + sigma * z)


def budget_for(account_id: str, warmup_day: int) -> IGDailyBudget:
    """
    Per-account daily IG budget at warming day N. Clamps day to
    [1, WARMING_DAYS]; each action samples LogNormal around the base
    curve seeded on (account_id, day, kind).
    """
    day = max(1, min(warmup_day, WARMING_DAYS))
    base = _BASE_BUDGETS[day]

    def _sample(kind: IGActionKind) -> int:
        mean = base[kind]
        if mean == 0:
            return 0
        u = _seed(account_id, day, kind)
        raw = _lognormal_sample(mean, _SIGMA[kind], u)
        return max(1, min(int(round(raw)), int(round(mean * 1.5))))

    return IGDailyBudget(
        day=day,
        follow=_sample("follow"),
        like=_sample("like"),
        story_view=_sample("story_view"),
        post=_sample("post"),
    )


def budgets_across_curve(account_id: str) -> list[IGDailyBudget]:
    return [budget_for(account_id, d) for d in range(1, WARMING_DAYS + 1)]


# ---------------------------------------------------------------------------
# Inter-action delays — LogNormal, same entropy source
# ---------------------------------------------------------------------------
# Means (seconds) between consecutive actions of the given kind. These
# shape the executor's pacing: a 180s like cadence is three likes/minute
# fleet-wide at peak budget, which matches real human bursts without
# saturating IG's rate limits.

_DELAY_MEAN_SEC: dict[IGActionKind, float] = {
    "follow":     180.0,
    "like":        40.0,
    "story_view":  15.0,
    "post":       900.0,
}
_DELAY_SIGMA: dict[IGActionKind, float] = {
    "follow":     0.30,
    "like":       0.35,
    "story_view": 0.40,
    "post":       0.25,
}


def next_delay_sec(account_id: str, kind: IGActionKind, seq: int) -> float:
    u = _seed(account_id, seq, f"delay:{kind}")
    raw = _lognormal_sample(_DELAY_MEAN_SEC[kind], _DELAY_SIGMA[kind], u)
    # Bound so a long tail can't stall the executor: 0.25× … 4× the mean.
    mean = _DELAY_MEAN_SEC[kind]
    return max(mean * 0.25, min(raw, mean * 4.0))


ACTION_ROUTES: dict[IGActionKind, str] = {
    "follow":     "ig.follow",
    "like":       "ig.like",
    "story_view": "ig.story_view",
    "post":       "ig.post",
}
