"""
Typed distribution primitives.

RULE: Every random value that contributes to an account's identity, timing,
or behavior MUST come from one of these distribution classes. Raw
`random.uniform()`, `random.randint()`, `Math.random()`, `time.time() % N`
are LINT-BANNED throughout the Phantom Fleet codebase.

Flat/uniform distributions produce rectangular histograms. Real populations
don't. Every field sampled at scale (hundreds of accounts × hundreds of days)
produces a fleet-wide histogram that Meta's ML classifier analyzes. Typed
distributions ensure those histograms match real-world shapes.

All samplers accept a deterministic seed derived from
hash((account_id, date.isoformat(), field_name)) so Phantom Fleet is
replayable/debuggable: the same account on the same day gets the same value,
but two different accounts on the same day get different values.
"""
from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass
from typing import Iterable, Sequence


def seed_for(account_id: str, date_iso: str, field: str) -> int:
    """Return a deterministic seed for a specific account/date/field combo.

    The seed is stable for replay (same inputs → same output) but unique
    across accounts, dates, and fields. Uses SHA-256 for diffusion so that
    sequential account IDs or dates don't produce correlated seeds.
    """
    payload = f"{account_id}|{date_iso}|{field}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _rng_from_seed(seed: int) -> "random.Random":  # noqa: F821
    import random as _random

    return _random.Random(seed)


def _secure_rng() -> "random.Random":  # noqa: F821
    """A Random instance seeded from the OS cryptographic RNG.

    Use this when you need a fresh, non-deterministic draw (e.g. one-off
    session choices that should never be predictable). Any
    uniqueness-contributing value at account-provisioning time should go
    through here, never through `time.time()`.
    """
    import random as _random

    return _random.Random(secrets.randbits(64))


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


@dataclass
class Distribution:
    """Abstract base — every concrete subclass must implement sample_with_seed."""

    def sample(
        self,
        account_id: str | None = None,
        date_iso: str | None = None,
        field: str = "default",
    ):
        if account_id is not None and date_iso is not None:
            rng = _rng_from_seed(seed_for(account_id, date_iso, field))
        else:
            rng = _secure_rng()
        return self._draw(rng)

    def _draw(self, rng):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# LogNormal — biased to the low end, long right tail.
# Matches real human timing data (typing dwell, session length, scroll dist).
# ---------------------------------------------------------------------------


@dataclass
class LogNormal(Distribution):
    low: float
    high: float
    sigma: float = 0.25  # width of the underlying normal; 0.2-0.4 is natural

    def _draw(self, rng):
        mu = math.log((self.low + self.high) / 2)
        value = rng.lognormvariate(mu, self.sigma)
        return max(self.low, min(self.high, value))

    def sample_int(self, account_id=None, date_iso=None, field="default"):
        return int(round(self.sample(account_id, date_iso, field)))


# ---------------------------------------------------------------------------
# Normal (Gaussian) — symmetric around a mean, clipped to [low, high]
# Use for values where high and low tails should be equally unlikely:
# tap-position offsets, scroll-velocity, touch-pressure.
# ---------------------------------------------------------------------------


@dataclass
class Normal(Distribution):
    mean: float
    std: float
    low: float
    high: float

    def _draw(self, rng):
        value = rng.gauss(self.mean, self.std)
        return max(self.low, min(self.high, value))


# ---------------------------------------------------------------------------
# Bimodal — two modes blended.
# Real usage patterns often look bimodal: "morning checkers" + "evening
# scrollers", "weekday user" + "weekend user", etc. Never use flat distributions
# for anything humans do on a daily rhythm.
# ---------------------------------------------------------------------------


@dataclass
class Bimodal(Distribution):
    mode1_mean: float
    mode1_std: float
    mode2_mean: float
    mode2_std: float
    mode1_weight: float  # 0..1; mode2_weight = 1 - mode1_weight
    low: float
    high: float

    def _draw(self, rng):
        mean, std = (
            (self.mode1_mean, self.mode1_std)
            if rng.random() < self.mode1_weight
            else (self.mode2_mean, self.mode2_std)
        )
        value = rng.gauss(mean, std)
        return max(self.low, min(self.high, value))


# ---------------------------------------------------------------------------
# WeightedCategorical — discrete choices with real-world weights.
# Use this for device model, OS version, carrier, locale — any field where
# picks must match a known real-world distribution. NEVER use equal weights
# (that's a flat distribution in disguise).
# ---------------------------------------------------------------------------


@dataclass
class WeightedCategorical(Distribution):
    choices: Sequence[tuple[object, float]]  # (value, weight)

    def _draw(self, rng):
        total = sum(w for _, w in self.choices)
        if total <= 0:
            raise ValueError("WeightedCategorical weights must sum to > 0")
        roll = rng.random() * total
        cumulative = 0.0
        for value, weight in self.choices:
            cumulative += weight
            if roll <= cumulative:
                return value
        return self.choices[-1][0]  # fallback


# ---------------------------------------------------------------------------
# Ranges helper — returns an integer sampled from [low..high] via LogNormal.
# Convenience wrapper used by the warming curve throughout.
# ---------------------------------------------------------------------------


def sample_int_range(
    low: int,
    high: int,
    account_id: str,
    date_iso: str,
    field: str,
    sigma: float = 0.25,
) -> int:
    """Sample an integer in [low, high] with LogNormal bias toward the low end.

    This is the primary entry point the Warming Agent uses for daily action
    counts. LogNormal matches real-user behavior (more light days than heavy
    days, heavy days are a long right tail, never a uniform draw).
    """
    dist = LogNormal(low=low, high=high, sigma=sigma)
    return max(low, min(high, int(round(dist.sample(account_id, date_iso, field)))))


# ---------------------------------------------------------------------------
# Intensity sampler — the "no rest days, varied intensity" rule.
# Every account is active every day, but daily intensity varies.
# Rolled per (account, date) like everything else.
# ---------------------------------------------------------------------------


INTENSITY_LEVELS = (
    ("minimal", 0.15, (0.10, 0.25)),  # 15% of days: quick check
    ("light", 0.25, (0.30, 0.60)),  # 25%: browse, light engagement
    ("normal", 0.45, (0.80, 1.20)),  # 45%: baseline day
    ("heavy", 0.15, (1.30, 1.80)),  # 15%: binge scroll
)


def sample_daily_intensity(account_id: str, date_iso: str) -> tuple[str, float]:
    """Return (level_name, multiplier) for this account's day.

    The multiplier is applied to the baseline daily action target to produce
    the actual target. Same account on same date always gets same roll.
    """
    rng = _rng_from_seed(seed_for(account_id, date_iso, "intensity"))
    roll = rng.random()
    cumulative = 0.0
    for name, weight, (lo, hi) in INTENSITY_LEVELS:
        cumulative += weight
        if roll <= cumulative:
            # Uniformly pick a multiplier inside the level's range.
            # Flat is OK HERE because the containing level is already
            # weighted — the two-stage sample produces a shaped distribution.
            multiplier = lo + (hi - lo) * rng.random()
            return name, multiplier
    return INTENSITY_LEVELS[-1][0], INTENSITY_LEVELS[-1][2][1]


# ---------------------------------------------------------------------------
# Dirichlet sample — for action-type mix within a session.
# A session is 2-8 actions. Instead of a fixed "60% follows / 30% likes /
# 10% comments" every session, sample the mix from a Dirichlet distribution
# so some sessions are mostly follows, some mostly likes, some mostly browsing.
# ---------------------------------------------------------------------------


def sample_action_mix(
    categories: Sequence[str],
    alphas: Sequence[float],
    account_id: str,
    date_iso: str,
    field: str,
) -> dict[str, float]:
    """Return a dict of category → fraction, summing to 1.0."""
    if len(categories) != len(alphas):
        raise ValueError("categories and alphas must have same length")
    rng = _rng_from_seed(seed_for(account_id, date_iso, field))
    # Dirichlet sampling via independent Gammas (standard construction)
    draws = [rng.gammavariate(a, 1.0) for a in alphas]
    total = sum(draws) or 1.0
    return {cat: draw / total for cat, draw in zip(categories, draws)}
