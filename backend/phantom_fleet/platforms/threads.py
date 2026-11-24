"""
Threads platform module — Phase 2 first unlock.

Threads is Meta's text-first social app linked to Instagram at account level:
one Threads account per IG account, same session cookie, same companion APK
primitives (tap/type/swipe) just pointed at the Threads package instead of
Instagram.

That linkage is the whole reason Threads ships before Reddit/TikTok/Snap:
  - $0 account cost (every IG account can enable Threads in two taps)
  - No new persona factory work (Threads reuses the IG persona verbatim)
  - No new proxy routing (same device → same IP → same WiFi fingerprint)
  - No new fingerprint audit (IG passed → Threads passes)

What's new vs IG:
  - A SHORTER warming curve. Threads has looser detection than IG and the
    account already has IG age baked in. We run 14 days instead of 28.
  - Four action primitives: post, reply, repost, follow. Likes count under
    reply budget (Threads collapses them in the UI anyway).
  - A DIFFERENT funnel path: IG posts the long-form content → the linked
    Threads account replies in the thread → bio link points at Linktree.
    Threads traffic warms up Threads replies on the IG post itself.

This module is deliberately DISTRIBUTION-DRIVEN per CLAUDE.md:
every randomized value comes from a named distribution with measured
parameters. No `random.uniform` on action timing or budgets.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Literal

# The Threads companion package name. Shared between USA and EU builds.
THREADS_PACKAGE = "com.instagram.barcelona"

# Warming curve length, days. Shorter than IG because Threads tolerates
# faster ramp-ups and the linked IG account is already aged.
WARMING_DAYS = 14

ActionKind = Literal["post", "reply", "repost", "follow"]


# ---------------------------------------------------------------------------
# Warming curve — 14-day LogNormal-scaled ramp per CLAUDE.md distribution rule
# ---------------------------------------------------------------------------

# Base action budgets per day of warming. Numbers are the *mean* of a
# LogNormal(μ, σ²) draw. Per-account jitter comes from a deterministic
# seed on account_id so the curve is reproducible for audit.
#
# Curve shape: slow ramp days 1-4 (just log in, scroll), discovery days 5-8
# (follow IG-linked circles), engagement days 9-12 (reply + repost), full
# posting days 13-14 (introduce own posts).

_BASE_BUDGETS: dict[int, dict[ActionKind, float]] = {
    1:  {"follow": 2,  "reply": 0,  "repost": 0,  "post": 0},
    2:  {"follow": 3,  "reply": 0,  "repost": 0,  "post": 0},
    3:  {"follow": 4,  "reply": 1,  "repost": 0,  "post": 0},
    4:  {"follow": 5,  "reply": 2,  "repost": 0,  "post": 0},
    5:  {"follow": 6,  "reply": 3,  "repost": 1,  "post": 0},
    6:  {"follow": 7,  "reply": 4,  "repost": 1,  "post": 0},
    7:  {"follow": 8,  "reply": 5,  "repost": 2,  "post": 0},
    8:  {"follow": 9,  "reply": 6,  "repost": 2,  "post": 1},
    9:  {"follow": 10, "reply": 8,  "repost": 3,  "post": 1},
    10: {"follow": 11, "reply": 9,  "repost": 3,  "post": 1},
    11: {"follow": 12, "reply": 10, "repost": 4,  "post": 2},
    12: {"follow": 12, "reply": 12, "repost": 4,  "post": 2},
    13: {"follow": 13, "reply": 13, "repost": 5,  "post": 2},
    14: {"follow": 14, "reply": 14, "repost": 5,  "post": 3},
}

# LogNormal sigma per action. Follow has tighter variance (budgets are
# more enforced by Threads), post has wider (creative cadence varies).
_SIGMA = {"follow": 0.22, "reply": 0.28, "repost": 0.35, "post": 0.45}


@dataclass(frozen=True)
class DailyBudget:
    """Per-account per-day action ceiling. Agents MUST NOT exceed."""
    day:    int
    follow: int
    reply:  int
    repost: int
    post:   int

    @property
    def total(self) -> int:
        return self.follow + self.reply + self.repost + self.post

    def as_dict(self) -> dict:
        return {
            "day":    self.day,
            "follow": self.follow,
            "reply":  self.reply,
            "repost": self.repost,
            "post":   self.post,
            "total":  self.total,
        }


def _seed(account_id: str, day: int, kind: str) -> float:
    """Deterministic 0..1 draw from account_id + day + action kind."""
    digest = hashlib.sha256(f"{account_id}:{day}:{kind}".encode()).hexdigest()
    return int(digest[:16], 16) / 0xFFFF_FFFF_FFFF_FFFF


def _lognormal_sample(mean: float, sigma: float, u: float) -> float:
    """
    LogNormal(μ, σ²) via inverse-CDF given a uniform u ∈ (0,1).
    Keeps the math in-module (no SciPy dep). Approximate inverse-normal
    with Beasley-Springer-Moro is overkill here — a rational Newton step
    on the standard normal is accurate enough for budget sampling.
    """
    if u <= 0 or u >= 1:
        u = 0.5
    # Abramowitz-Stegun 26.2.23 inverse normal
    t = math.sqrt(-2.0 * math.log(min(u, 1 - u)))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
    if u > 0.5:
        z = -z
    mu = math.log(mean) - 0.5 * sigma * sigma
    return math.exp(mu + sigma * z)


def budget_for(account_id: str, warmup_day: int) -> DailyBudget:
    """
    The per-account daily budget at warming day N.

    Clamps day to [1, WARMING_DAYS]. Each action kind is sampled from a
    LogNormal distribution around the base-curve value, seeded on
    (account_id, day, kind) so the number is both deterministic and
    varied across accounts and days.
    """
    day = max(1, min(warmup_day, WARMING_DAYS))
    base = _BASE_BUDGETS[day]

    def _sample(kind: ActionKind) -> int:
        mean = base[kind]
        if mean == 0:
            return 0
        u = _seed(account_id, day, kind)
        raw = _lognormal_sample(mean, _SIGMA[kind], u)
        # Clamp to a sane ceiling: 1.5× the daily mean so one lucky draw
        # doesn't blow the audit numbers.
        return max(1, min(int(round(raw)), int(round(mean * 1.5))))

    return DailyBudget(
        day=day,
        follow=_sample("follow"),
        reply=_sample("reply"),
        repost=_sample("repost"),
        post=_sample("post"),
    )


def budgets_across_curve(account_id: str) -> list[DailyBudget]:
    """Every day's budget for one account — audit + preview helper."""
    return [budget_for(account_id, d) for d in range(1, WARMING_DAYS + 1)]


# ---------------------------------------------------------------------------
# Action primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThreadsAction:
    account_id:  str
    kind:        ActionKind
    target:      str              # @handle for follow/reply/repost, text for post
    payload:     str = ""         # post/reply body


# The surface the executor dispatches through. Keeping the strings as
# constants so a missed primitive is obvious at import time.
ACTION_ROUTES: dict[ActionKind, str] = {
    "post":   "threads.post",
    "reply":  "threads.reply",
    "repost": "threads.repost",
    "follow": "threads.follow",
}


# ---------------------------------------------------------------------------
# Account linking
# ---------------------------------------------------------------------------


@dataclass
class ThreadsLink:
    """A Threads account linked to an IG parent. Both share the IG session."""
    threads_account_id: str
    ig_account_id:      str
    handle:             str
    linked_at:          str
    warmup_day:         int = 1


def can_cross_post(ig_account_row: dict) -> bool:
    """
    Cross-posting from IG into the linked Threads account is only safe once
    IG itself is past day 7 of its warming curve. Before that, Threads
    activity on a fresh IG account fast-tracks the detection stack that
    flags IG new-account warming.
    """
    return int(ig_account_row.get("warmup_day", 0)) >= 7
