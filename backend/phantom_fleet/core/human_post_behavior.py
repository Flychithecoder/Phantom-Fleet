"""
Shared human posting behavior primitives.
Used by every posting agent (Threads, Reddit, X, BlueSky, Discord, Telegram).
All timing is LogNormal — never uniform, never fixed.

Distribution rationale (fleet-scale, CLAUDE.md 20K account rule):
    - Every timing value is LogNormal so fleet-wide histograms are log-normal
      bell curves, not rectangular (uniform) distributions that ML classifiers
      detect as synthetic.
    - post_time_jitter_seconds uses Normal — symmetric around 0 is correct here
      because scheduled posting jitter is genuinely symmetric (early and late
      equally likely).
    - should_rethink uses a deterministic hash of (process-level entropy) so
      the 15% "rethink" probability is stochastic per call, not predictable.
    - select_template is seeded by caller-provided seed so different accounts
      posting the same content pool get different picks — prevents content
      monoculture even with a small pool.
"""
from __future__ import annotations

import asyncio
import math
import os
import secrets

from .distributions import LogNormal, Normal

# ---------------------------------------------------------------------------
# Distribution instances (instantiated once, reused everywhere)
# ---------------------------------------------------------------------------

# Pre-post browsing: median ~45s, realistic app-open-then-scroll dwell
_PRE_POST_BROWSE_DIST = LogNormal(low=10.0, high=180.0, sigma=0.30)

# Compose dwell: time before typing starts, median ~12s
_COMPOSE_DWELL_DIST = LogNormal(low=3.0, high=60.0, sigma=0.40)

# Per-character typing speed multiplier (seconds per char): median ~0.10s/char
# At 200-char post → median ~20s typing delay
_TYPING_SPEED_DIST = LogNormal(low=0.03, high=0.50, sigma=0.25)

# Rethink pause: median ~8s pause mid-compose
_RETHINK_PAUSE_DIST = LogNormal(low=2.0, high=35.0, sigma=0.30)

# Inter-post delay: median ~1hr (3600s), heavy right tail → some posts hours apart
_INTER_POST_DIST = LogNormal(low=300.0, high=14400.0, sigma=0.50)

# Jitter added to scheduled post time: N(0, 900) → ±15 min typical
_JITTER_DIST = Normal(mean=0.0, std=900.0, low=-1800.0, high=1800.0)


# ---------------------------------------------------------------------------
# Async timing primitives
# ---------------------------------------------------------------------------


async def pre_post_browse_delay() -> float:
    """
    Simulate opening the app and scrolling through the feed before posting.

    Returns the actual sleep duration in seconds (useful for tests).
    LogNormal(mean=ln(45), sigma=0.3) — median ~45s, tail to ~3 min.
    """
    duration = _PRE_POST_BROWSE_DIST.sample()
    await asyncio.sleep(duration)
    return duration


async def compose_dwell() -> float:
    """
    Simulate the pause between opening the compose box and starting to type.

    Returns the actual sleep duration in seconds.
    LogNormal(mean=ln(12), sigma=0.4) — median ~12s, tail to ~1 min.
    """
    duration = _COMPOSE_DWELL_DIST.sample()
    await asyncio.sleep(duration)
    return duration


async def typing_delay(text: str) -> float:
    """
    Simulate the time taken to type `text` character by character.

    Timing: len(text) × LogNormal(mean=ln(0.10), sigma=0.25) seconds.
    A 200-character post takes median ~20s to "type", which is realistic
    (roughly 10 WPM casual typing speed).

    Returns the actual sleep duration in seconds.
    """
    if not text:
        return 0.0
    per_char = _TYPING_SPEED_DIST.sample()
    duration = len(text) * per_char
    await asyncio.sleep(duration)
    return duration


async def rethink_pause() -> float:
    """
    Simulate a mid-compose "rethink" pause (re-reading, editing, second-guessing).

    Returns the actual sleep duration in seconds.
    LogNormal(mean=ln(8), sigma=0.3) — median ~8s.
    """
    duration = _RETHINK_PAUSE_DIST.sample()
    await asyncio.sleep(duration)
    return duration


async def inter_post_delay() -> float:
    """
    Simulate the time between consecutive posts in a multi-post session.

    Returns the actual sleep duration in seconds.
    LogNormal(mean=ln(3600), sigma=0.5) — median ~1hr, heavy tail toward
    several hours. Prevents uniform 1-post-per-hour clusters.
    """
    duration = _INTER_POST_DIST.sample()
    await asyncio.sleep(duration)
    return duration


# ---------------------------------------------------------------------------
# Non-async helpers
# ---------------------------------------------------------------------------


def post_time_jitter_seconds(
    account_id: str | None = None,
    date_iso: str | None = None,
    field: str = "post_time_jitter",
) -> int:
    """
    Return an integer jitter in seconds to add to a scheduled post time.

    Drawn from Normal(0, 900) and clamped to [-1800, 1800] (±30 min max).
    This prevents a fleet of accounts all posting at exactly :00/:30 each hour,
    which would be a timing cluster fingerprint.

    When account_id + date_iso are supplied the draw is deterministic per
    (account, date, field) — required for replay, debugging, and zero-collision
    guarantees in the scheduler. Without seeds it falls back to a secure random draw.
    """
    raw = _JITTER_DIST.sample(account_id=account_id, date_iso=date_iso, field=field)
    return int(raw)


def should_rethink() -> bool:
    """
    Return True with ~15% probability to trigger a mid-compose rethink pause.

    Uses os.urandom for entropy so it is non-deterministic (the rethink event
    should not be predictable per account+date — it is a random UI gesture).
    The probability is 15/256 ≈ 5.86% per low byte, but we use the full
    first byte range: True if byte < 38 (38/256 ≈ 14.8% ≈ 15%).
    """
    return secrets.token_bytes(1)[0] < 38


def select_template(pool: list[str], seed: int) -> str:
    """
    Select a template from `pool` using a deterministic seed.

    The seed should be derived from hash(account_id + date_iso + post_index)
    by the caller so different accounts pick different templates.

    Does NOT enforce no-repeat (pool must be large enough that repeat risk is
    acceptable at fleet scale — minimum pool sizes are enforced by callers).

    Raises ValueError if pool is empty.
    """
    if not pool:
        raise ValueError("select_template: pool must not be empty")
    idx = seed % len(pool)
    return pool[idx]
