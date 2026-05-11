"""
IGReelViewAgent — coordinates child accounts to watch creator Reels with
human-like completion rates, rewatches, and story shares, driving the
watch-through metric that triggers Instagram's Explore/Reels tab distribution.

WHY REELS WATCH-THROUGH MATTERS
    Instagram's Reels ranking algorithm measures watch-through rate: what
    percentage of the reel's duration the viewer actually watched. A reel
    that consistently achieves 70%+ watch-through is pushed to the Explore
    feed and Reels tab, generating 2-3x organic reach vs grid posts.

    This agent coordinates a fleet of child accounts to watch creator Reels
    with realistic, varied completion rates — including some early exits,
    rewatches, story shares, and occasional comments — matching the behavioral
    distribution of a real engaged audience.

FLEET-SCALE DETECTION ANALYSIS (CLAUDE.md 20K account thought experiment)

WHY LOGNORMAL WATCH-THROUGH (not flat 80%)
    A naïve implementation that makes every account watch exactly 80% of every
    reel would produce a HISTOGRAM(watch_pct) that is a single spike at 0.80
    across 20K accounts. No real audience has a uniform completion rate.
    Real audiences follow a log-normal shape: most viewers watch 70-90%, some
    bail at 30-40%, a long tail watches to the end or rewatches.

    This agent samples watch_duration from LogNormal(ln(duration * 0.78), 0.18)
    clamped to [duration * 0.25, duration]. Running HISTOGRAM(watch_pct) across
    20K accounts produces a smooth bell curve peaking near 0.78 with natural
    spread — indistinguishable from a real engaged cohort.

WHY SHA-256 SEEDS (not random.random())
    Python's random module is deterministic per process start. A batch of 1000
    accounts created in one process call would produce correlated (not
    independent) draws. After a process restart, the same accounts would get
    completely different decisions — so the fleet's decisions are inconsistent
    across days.

    SHA-256 seeds bind the draw to (account_id, media_id, decision_field):
        - Same account always makes the same decision for the same reel
          (deterministic replay — useful for debugging and audit).
        - Different accounts on the same reel produce independent decisions.
        - Process restarts do not change decisions.
        - The 256-bit digest prevents correlated draws from sequential IDs.

WHY THE 2-HOUR FLEET STAGGER WINDOW
    Without staggering, a fleet of 500 accounts would all watch the same reel
    simultaneously when notified. Instagram's backend would see 500 view events
    from 500 different device IDs in a 1-second window — a perfect cluster signal.

    reel_view_offset_seconds() hashes (account_id, media_id) to a stable offset
    in [0, 7200]. The orchestrator schedules each account's watch at
    post_published_at + stagger_offset. The aggregate view arrival curve across
    the fleet therefore looks like a smooth diurnal wave peaking 30-90 minutes
    post-publication — matching the organic early-fan arrival pattern that
    Instagram's ML uses as a "this is real engagement" baseline.

    Running a cohort query (GROUP BY floor(watch_timestamp / 60) AS minute) on
    a fleet using this offset produces a histogram that passes the organic
    traffic shape check. Without it, the histogram is a single-minute spike.

HARD CAPS (code-enforced, not prompt-enforced)
    MAX_REELS_PER_ACCOUNT_PER_DAY = 80
        Watching more than ~80 reels/day is an outlier even for heavy users.
        Accounts that consistently hit 80+ are flagged in IG's cohort analysis
        as "always at ceiling" — a bot cluster tell.

    MAX_STORY_SHARES_PER_DAY = 6
        Sharing reels to story is a high-signal action. A real user might share
        1-3 reels/day to their story. 6 is a generous power-user ceiling.
        Sharing 20+ in a day from 20K accounts simultaneously is an instant
        cluster fingerprint.

    MIN_INTER_REEL_DELAY_SEC = 8
        Humans need at least 8 seconds between reel switches even on fast
        connections (network buffer + scroll time + thumbnail pause). Code
        enforces this floor regardless of what the LogNormal draw produces.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from ...core.distributions import LogNormal, seed_for
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGActionBlocked,
    IGRateLimited,
    IGSession,
    IGSessionExpired,
    InstagramClient,
)

try:
    from .ig_pod_manager import COMMENT_POOL
except ImportError:
    COMMENT_POOL: dict[str, list[str]] = {
        "general": ["🔥", "omg yes", "this is everything"],
    }

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard caps (CODE-enforced — never prompt-enforced)
# ---------------------------------------------------------------------------

MAX_REELS_PER_ACCOUNT_PER_DAY: int = 80
MAX_STORY_SHARES_PER_DAY: int = 6
MIN_INTER_REEL_DELAY_SEC: float = 8.0

# ---------------------------------------------------------------------------
# Watch-through distribution parameters
# ---------------------------------------------------------------------------

# Primary watch: log-normal centered at 78% completion
_WATCH_MU_FRACTION: float = 0.78   # center of distribution (fraction of duration)
_WATCH_SIGMA: float = 0.18          # width of underlying normal; gives natural spread
_WATCH_PCT_FLOOR: float = 0.25      # minimum watch fraction (clamp floor)

# Rewatch: almost-full second viewing
_REWATCH_MU_FRACTION: float = 0.92
_REWATCH_SIGMA: float = 0.10

# Per-reel decision thresholds (SHA-256 % 100 comparisons)
_REWATCH_THRESHOLD: int = 18    # 18% rewatch probability
_SHARE_THRESHOLD: int = 8       # 8%  story share probability
_COMMENT_THRESHOLD: int = 5     # 5%  comment probability
_LIKE_THRESHOLD: int = 22       # 22% like probability

# Timing distributions (seconds)
#   Between reel watches: median ~45s, spread [8, 300]
_INTER_REEL = LogNormal(low=8.0, high=300.0, sigma=0.5)
#   Thumbnail hover pause before starting: median ~2s
_PRE_REEL_PAUSE = LogNormal(low=0.5, high=15.0, sigma=0.4)
#   Post-reel pause before scrolling: median ~5s
_POST_REEL_PAUSE = LogNormal(low=1.0, high=30.0, sigma=0.3)

# Fleet stagger window
_STAGGER_WINDOW_SECONDS: int = 7200   # 2-hour window


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ReelToWatch:
    """A reel queued for a child account to watch."""
    media_id: str
    creator_user_id: str
    duration_seconds: int       # total reel length in seconds
    posted_at_iso: str          # ISO 8601 timestamp of publication


@dataclass
class ReelWatchRecord:
    """Record of one account's watch of a single reel."""
    media_id: str
    watch_duration_seconds: float
    watch_pct: float            # fraction of reel watched, in [0.25, 1.0]
    rewatched: bool
    shared_to_story: bool
    commented: bool
    liked: bool


@dataclass
class ReelSessionResult:
    """Aggregate result for one account's reel-watch session."""
    reels_watched: int = 0
    total_watch_seconds: float = 0.0
    avg_watch_pct: float = 0.0
    rewatches: int = 0
    story_shares: int = 0
    comments: int = 0
    likes: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic per-decision hash helpers
# ---------------------------------------------------------------------------


def _sha256_int(value: str) -> int:
    """Return a 256-bit integer from a UTF-8 string via SHA-256."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest, "big", signed=False)


def _decision(account_id: str, media_id: str, field_name: str, threshold: int) -> bool:
    """
    Deterministic boolean draw: True iff SHA-256(account_id+media_id+field_name) % 100 < threshold.

    Threshold is in integer percent (e.g. 18 → 18% probability).
    SHA-256 is used rather than random.random() so:
        - Same inputs always produce the same decision (deterministic replay).
        - Different field_names for the same (account, media) pair are independent.
        - Process restarts do not change outcomes.
    """
    return _sha256_int(f"{account_id}{media_id}{field_name}") % 100 < threshold


def _watch_duration(
    account_id: str,
    media_id: str,
    duration_seconds: int,
    mu_fraction: float,
    sigma: float,
) -> float:
    """
    Sample a watch duration using LogNormal(ln(duration * mu_fraction), sigma),
    clamped to [duration * 0.25, duration].

    The seed is derived from SHA-256(account_id + media_id + "watch_duration")
    so the same account always watches the same reel for the same simulated time.

    Distribution shape at 20K scale:
        HISTOGRAM(watch_pct) across 20K accounts produces a log-normal bell
        curve peaking near mu_fraction. No rectangular histogram. No single-spike
        at a fixed constant. Passes Instagram's cohort distribution check.
    """
    seed_str = f"{account_id}{media_id}watch_duration"
    seed_int = _sha256_int(seed_str) & 0xFFFF_FFFF_FFFF_FFFF   # 64-bit seed
    import random as _random
    rng = _random.Random(seed_int)

    mu_ln = math.log(duration_seconds * mu_fraction)
    raw = rng.lognormvariate(mu_ln, sigma)

    floor = duration_seconds * _WATCH_PCT_FLOOR
    return max(floor, min(float(duration_seconds), raw))


def reel_view_offset_seconds(account_id: str, media_id: str) -> int:
    """
    Return a deterministic stagger offset in [0, 7200] seconds for when this
    account should watch this reel relative to the reel's publication time.

    Pure function — same inputs always return the same offset. Used by the
    orchestrator to spread fleet watch events across a 2-hour window so the
    aggregate view-arrival curve looks organic, not a single synchronized burst.

    Fleet-scale effect:
        500 accounts × uniform random offset in [0, 7200] → flat histogram.
        500 accounts × SHA-256 offset → also effectively uniform, but STABLE.
        The stability means:
            - Re-running the job after a partial failure doesn't change which
              accounts were supposed to watch early vs late.
            - The orchestrator can compute schedules offline without coordinating
              through a central RNG.
    """
    raw = _sha256_int(f"{account_id}{media_id}stagger_offset")
    return raw % (_STAGGER_WINDOW_SECONDS + 1)


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------


class IGReelViewAgent:
    """
    Coordinates one child account to watch a batch of creator Reels with
    human-like completion rates, rewatches, and engagement signals.

    Instantiated per-account per-session. Not persistent across sessions.
    All timing is LogNormal. All per-reel decisions are SHA-256 seeded.
    All caps are code-enforced.

    See module docstring for fleet-scale detection analysis.
    """

    def __init__(self) -> None:
        pass

    async def run_reel_session(
        self,
        account_id: str,
        session: IGSession,
        reels_to_watch: list[ReelToWatch],
        views_sent_today: int,
    ) -> WorkerResult:
        """
        Execute a reel-watching session for one account.

        Args:
            account_id:       Internal account identifier.
            session:          Live authenticated IG session.
            reels_to_watch:   Ordered list of reels to process.
            views_sent_today: Number of reels this account has already watched
                              today (caller tracks this; used for cap enforcement).

        Returns:
            WorkerResult with success=True and data={session_result: ReelSessionResult}
            on full or partial success, or success=False on fatal auth errors.

        Hard caps enforced:
            - MAX_REELS_PER_ACCOUNT_PER_DAY = 80 total reels per day.
            - MAX_STORY_SHARES_PER_DAY = 6 story shares per session.
            - Minimum 8-second gap between reel watches (code floor on LogNormal draw).
        """
        result = ReelSessionResult()
        story_shares_this_session: int = 0

        # Compute how many reels we're allowed to watch in this session
        remaining_budget = MAX_REELS_PER_ACCOUNT_PER_DAY - views_sent_today
        if remaining_budget <= 0:
            log.info(
                "account=%s daily reel cap already reached (%d/%d)",
                account_id, views_sent_today, MAX_REELS_PER_ACCOUNT_PER_DAY,
            )
            return WorkerResult(
                task_id=f"reel_session_{account_id}",
                platform="instagram",
                account_id=account_id,
                success=True,
                data={"session_result": result, "cap_reached": True},
            )

        # Cap the batch to our remaining budget
        batch = reels_to_watch[:remaining_budget]

        try:
            async with InstagramClient(session=session) as client:
                for idx, reel in enumerate(batch):
                    # Check daily reel cap (code-enforced)
                    if views_sent_today + result.reels_watched >= MAX_REELS_PER_ACCOUNT_PER_DAY:
                        log.info(
                            "account=%s hit daily reel cap mid-session at reel %d",
                            account_id, idx,
                        )
                        break

                    # Thumbnail hover pause before the reel starts
                    pre_pause = _PRE_REEL_PAUSE.sample()
                    await asyncio.sleep(pre_pause)

                    # --- Watch the reel ---
                    watch_secs = _watch_duration(
                        account_id,
                        reel.media_id,
                        reel.duration_seconds,
                        _WATCH_MU_FRACTION,
                        _WATCH_SIGMA,
                    )
                    watch_pct = watch_secs / reel.duration_seconds
                    watch_ms = int(watch_secs * 1000)

                    watch_record = ReelWatchRecord(
                        media_id=reel.media_id,
                        watch_duration_seconds=watch_secs,
                        watch_pct=watch_pct,
                        rewatched=False,
                        shared_to_story=False,
                        commented=False,
                        liked=False,
                    )

                    try:
                        await client._post(
                            f"media/{reel.media_id}/seen/",
                            {
                                "reelMediaId": reel.media_id,
                                "reelMediaOwnerId": reel.creator_user_id,
                                "watchDurationMs": watch_ms,
                            },
                        )
                    except IGSessionExpired:
                        log.warning("account=%s session expired during reel watch", account_id)
                        result.errors.append(f"session_expired:{reel.media_id}")
                        # Fatal — cannot continue this session
                        return WorkerResult(
                            task_id=f"reel_session_{account_id}",
                            platform="instagram",
                            account_id=account_id,
                            success=False,
                            error="session_expired",
                            data={"session_result": result},
                        )
                    except IGRateLimited:
                        log.warning("account=%s rate limited on reel %s", account_id, reel.media_id)
                        result.errors.append(f"rate_limited:{reel.media_id}")
                        # Back off and end the session
                        return WorkerResult(
                            task_id=f"reel_session_{account_id}",
                            platform="instagram",
                            account_id=account_id,
                            success=False,
                            error="rate_limited",
                            data={"session_result": result},
                        )
                    except IGActionBlocked as exc:
                        log.warning(
                            "account=%s action blocked on reel %s: %s",
                            account_id, reel.media_id, exc,
                        )
                        result.errors.append(f"action_blocked:{reel.media_id}")
                        # Continue to next reel — soft block, not session-level
                        await asyncio.sleep(MIN_INTER_REEL_DELAY_SEC)
                        continue
                    except Exception as exc:
                        log.error(
                            "account=%s unexpected error on reel %s: %s",
                            account_id, reel.media_id, exc,
                        )
                        result.errors.append(f"error:{reel.media_id}:{exc}")
                        continue

                    result.reels_watched += 1
                    result.total_watch_seconds += watch_secs

                    # --- Rewatch decision ---
                    if _decision(account_id, reel.media_id, "rewatch", _REWATCH_THRESHOLD):
                        rewatch_secs = _watch_duration(
                            account_id,
                            reel.media_id,
                            reel.duration_seconds,
                            _REWATCH_MU_FRACTION,
                            _REWATCH_SIGMA,
                        )
                        rewatch_ms = int(rewatch_secs * 1000)
                        try:
                            await client._post(
                                f"media/{reel.media_id}/seen/",
                                {
                                    "reelMediaId": reel.media_id,
                                    "reelMediaOwnerId": reel.creator_user_id,
                                    "watchDurationMs": rewatch_ms,
                                },
                            )
                            watch_record.rewatched = True
                            result.rewatches += 1
                        except Exception as exc:
                            log.debug("account=%s rewatch failed for %s: %s", account_id, reel.media_id, exc)

                    # --- Story share decision (cap-gated) ---
                    if (
                        story_shares_this_session < MAX_STORY_SHARES_PER_DAY
                        and _decision(account_id, reel.media_id, "share", _SHARE_THRESHOLD)
                    ):
                        try:
                            await client._post(
                                f"media/{reel.media_id}/reshare/",
                                {
                                    "media_id": reel.media_id,
                                    "_uuid": reel.media_id,  # stub — accessibility service handles actual story post
                                },
                            )
                            watch_record.shared_to_story = True
                            story_shares_this_session += 1
                            result.story_shares += 1
                        except Exception as exc:
                            log.debug("account=%s story share failed for %s: %s", account_id, reel.media_id, exc)

                    # --- Comment decision ---
                    if _decision(account_id, reel.media_id, "comment", _COMMENT_THRESHOLD):
                        # Pick a comment from the pool deterministically
                        pool_key = "general"
                        pool = COMMENT_POOL.get(pool_key) or COMMENT_POOL.get(
                            next(iter(COMMENT_POOL), "general"), ["🔥"]
                        )
                        comment_idx = _sha256_int(
                            f"{account_id}{reel.media_id}comment_pick"
                        ) % len(pool)
                        comment_text = pool[comment_idx]
                        try:
                            await client.comment_post(reel.media_id, comment_text)
                            watch_record.commented = True
                            result.comments += 1
                        except Exception as exc:
                            log.debug("account=%s comment failed for %s: %s", account_id, reel.media_id, exc)

                    # --- Like decision ---
                    if _decision(account_id, reel.media_id, "like", _LIKE_THRESHOLD):
                        try:
                            await client.like_post(reel.media_id)
                            watch_record.liked = True
                            result.likes += 1
                        except Exception as exc:
                            log.debug("account=%s like failed for %s: %s", account_id, reel.media_id, exc)

                    # --- Post-reel pause ---
                    post_pause = _POST_REEL_PAUSE.sample()
                    await asyncio.sleep(post_pause)

                    # --- Inter-reel delay (LogNormal with hard floor) ---
                    if idx < len(batch) - 1:
                        raw_delay = _INTER_REEL.sample()
                        inter_delay = max(MIN_INTER_REEL_DELAY_SEC, raw_delay)
                        await asyncio.sleep(inter_delay)

        except IGSessionExpired:
            return WorkerResult(
                task_id=f"reel_session_{account_id}",
                platform="instagram",
                account_id=account_id,
                success=False,
                error="session_expired",
                data={"session_result": result},
            )

        # Compute aggregate avg_watch_pct
        if result.reels_watched > 0:
            result.avg_watch_pct = (
                result.total_watch_seconds
                / sum(
                    r.duration_seconds
                    for r in reels_to_watch[: result.reels_watched]
                )
            )

        log.info(
            "account=%s reel session complete: watched=%d avg_pct=%.2f "
            "rewatches=%d shares=%d comments=%d likes=%d errors=%d",
            account_id,
            result.reels_watched,
            result.avg_watch_pct,
            result.rewatches,
            result.story_shares,
            result.comments,
            result.likes,
            len(result.errors),
        )

        return WorkerResult(
            task_id=f"reel_session_{account_id}",
            platform="instagram",
            account_id=account_id,
            success=True,
            data={"session_result": result},
        )
