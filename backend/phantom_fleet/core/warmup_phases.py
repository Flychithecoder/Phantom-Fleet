"""
Warmup phase system for Phantom Fleet accounts.

Six phases gate what actions an account is allowed to take, preventing
new accounts from immediately blasting full follow/comment/post volumes
(which is a day-1 ban signal on every platform).

Phases (platform-aware — IG/Threads and Reddit have different karma gates):
    1. profile_warmup  — browse only, no actions (3 days)
    2. soft_engage     — likes only, no follows/comments/posts (5 days)
    3. engage          — likes + follows (≤20/day), no posts (7 days)
    4. content_start   — all above + 1-2 posts/day (7 days)
    5. graduated       — all above, increasing limits (7 days)
    6. active          — full daily limits, unrestricted within caps

Reddit-specific phases also include karma thresholds:
    comment_farming: must reach 400 comment-karma before advancing
    post_farming:    must reach 3000 post-karma before advancing

All caps are enforced by CODE — the phase system is the authoritative
limiter. Prompts saying "don't do more than X" are NOT sufficient.

Fleet-scale detection notes:
    - Phase durations are minimum guarantees — accounts that don't hit
      engagement thresholds stay in their phase longer.
    - Daily action resets happen at midnight UTC (caller responsible for
      resetting daily_follows/likes/posts/comments at midnight).
    - Phase advancement is checked on every warming cycle; no cron needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("phantom_fleet.warmup_phases")

# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------

PHASE_ORDER = [
    "profile_warmup",
    "soft_engage",
    "engage",
    "content_start",
    "graduated",
    "active",
]

@dataclass
class PhaseLimits:
    """Daily action limits and graduation criteria for one phase."""
    max_follows:  int = 0
    max_likes:    int = 0
    max_posts:    int = 0
    max_comments: int = 0
    min_days:     int = 1
    # Optional karma thresholds (Reddit / engagement score)
    graduation_comment_karma: Optional[int] = None
    graduation_post_karma:    Optional[int] = None


# Instagram / Threads phases
IG_PHASE_LIMITS: dict[str, PhaseLimits] = {
    "profile_warmup": PhaseLimits(
        max_follows=0, max_likes=0, max_posts=0, max_comments=0,
        min_days=3,
    ),
    "soft_engage": PhaseLimits(
        max_follows=0, max_likes=30, max_posts=0, max_comments=0,
        min_days=5,
    ),
    "engage": PhaseLimits(
        max_follows=20, max_likes=60, max_posts=0, max_comments=5,
        min_days=7,
    ),
    "content_start": PhaseLimits(
        max_follows=30, max_likes=80, max_posts=2, max_comments=8,
        min_days=7,
    ),
    "graduated": PhaseLimits(
        max_follows=45, max_likes=100, max_posts=3, max_comments=10,
        min_days=7,
    ),
    "active": PhaseLimits(
        max_follows=60, max_likes=150, max_posts=5, max_comments=15,
        min_days=0,
    ),
}

# Reddit phases (karma-gated)
REDDIT_PHASE_LIMITS: dict[str, PhaseLimits] = {
    "profile_warmup": PhaseLimits(
        max_follows=0, max_likes=0, max_posts=0, max_comments=0,
        min_days=3,
    ),
    "soft_engage": PhaseLimits(
        max_follows=0, max_likes=20, max_posts=0, max_comments=0,
        min_days=3,
    ),
    "engage": PhaseLimits(
        max_follows=0, max_likes=20, max_posts=0, max_comments=10,
        min_days=5,
    ),
    "content_start": PhaseLimits(
        max_follows=0, max_likes=20, max_posts=2, max_comments=15,
        min_days=7,
        graduation_comment_karma=400,
    ),
    "graduated": PhaseLimits(
        max_follows=0, max_likes=30, max_posts=5, max_comments=15,
        min_days=7,
        graduation_post_karma=3000,
    ),
    "active": PhaseLimits(
        max_follows=0, max_likes=50, max_posts=10, max_comments=20,
        min_days=0,
    ),
}

# Default: use IG limits for all other platforms
_PLATFORM_PHASE_MAP: dict[str, dict[str, PhaseLimits]] = {
    "instagram":  IG_PHASE_LIMITS,
    "threads":    IG_PHASE_LIMITS,
    "reddit":     REDDIT_PHASE_LIMITS,
    "x":          IG_PHASE_LIMITS,
    "tiktok":     IG_PHASE_LIMITS,
    "bluesky":    IG_PHASE_LIMITS,
    "discord":    IG_PHASE_LIMITS,
    "telegram":   IG_PHASE_LIMITS,
}


def get_day_limits(day_num: int) -> dict:
    """
    Return action caps based on warmup day number (day_in_curve).

    Used by the AI agent and warmup routes for simple day-based dispatching
    when the full phase system context isn't available.

    Returns dict with keys: likes, follows, comments, posts.
    """
    if day_num <= 3:
        return {"likes": 10,  "follows": 0,  "comments": 0, "posts": 0}
    elif day_num <= 7:
        return {"likes": 25,  "follows": 10, "comments": 0, "posts": 0}
    elif day_num <= 14:
        return {"likes": 40,  "follows": 25, "comments": 5, "posts": 1}
    elif day_num <= 21:
        return {"likes": 60,  "follows": 50, "comments": 10, "posts": 2}
    else:
        return {"likes": 80,  "follows": 100, "comments": 15, "posts": 3}


def get_phase_limits(platform: str, phase: str) -> PhaseLimits:
    """Return the PhaseLimits for a given platform+phase combination."""
    limits_map = _PLATFORM_PHASE_MAP.get(platform, IG_PHASE_LIMITS)
    return limits_map.get(phase, IG_PHASE_LIMITS["active"])


def get_next_phase(current: str) -> Optional[str]:
    """Return the next phase name, or None if already at 'active'."""
    idx = PHASE_ORDER.index(current) if current in PHASE_ORDER else -1
    if idx == -1 or idx >= len(PHASE_ORDER) - 1:
        return None
    return PHASE_ORDER[idx + 1]


# ---------------------------------------------------------------------------
# Advancement check
# ---------------------------------------------------------------------------


@dataclass
class PhaseCheckResult:
    should_advance: bool
    next_phase:     Optional[str] = None
    reason:         Optional[str] = None  # why NOT advancing (if should_advance=False)


def check_phase_advancement(
    phase: str,
    phase_started_at: Optional[datetime],
    platform: str = "instagram",
    comment_karma: int = 0,
    post_karma:    int = 0,
) -> PhaseCheckResult:
    """
    Determine whether an account is eligible to advance to the next phase.

    Args:
        phase:            Current phase name.
        phase_started_at: When the account entered this phase.
        platform:         Platform name (affects which limits to use).
        comment_karma:    Accumulated comment karma/likes (Reddit).
        post_karma:       Accumulated post karma/score (Reddit).

    Returns:
        PhaseCheckResult with should_advance=True and next_phase set,
        or should_advance=False with a human-readable reason.
    """
    limits = get_phase_limits(platform, phase)
    next_phase = get_next_phase(phase)

    if next_phase is None:
        return PhaseCheckResult(should_advance=False, reason="Already at active phase")

    # Time gate
    if limits.min_days > 0:
        if phase_started_at is None:
            return PhaseCheckResult(should_advance=False, reason="phase_started_at not set")
        now = datetime.now(timezone.utc)
        started = phase_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        days_in_phase = (now - started).total_seconds() / 86400.0
        if days_in_phase < limits.min_days:
            remaining = limits.min_days - days_in_phase
            return PhaseCheckResult(
                should_advance=False,
                reason=f"Need {remaining:.1f} more days in {phase}",
            )

    # Karma gates
    if limits.graduation_comment_karma is not None:
        if comment_karma < limits.graduation_comment_karma:
            deficit = limits.graduation_comment_karma - comment_karma
            return PhaseCheckResult(
                should_advance=False,
                reason=f"Need {deficit} more comment karma (have {comment_karma}, need {limits.graduation_comment_karma})",
            )

    if limits.graduation_post_karma is not None:
        if post_karma < limits.graduation_post_karma:
            deficit = limits.graduation_post_karma - post_karma
            return PhaseCheckResult(
                should_advance=False,
                reason=f"Need {deficit} more post karma (have {post_karma}, need {limits.graduation_post_karma})",
            )

    return PhaseCheckResult(should_advance=True, next_phase=next_phase)


# ---------------------------------------------------------------------------
# Action cap enforcement
# ---------------------------------------------------------------------------


def is_action_allowed(
    action: str,
    phase: str,
    platform: str,
    daily_counts: dict[str, int],
) -> tuple[bool, str]:
    """
    Check whether an action is allowed given current phase and today's counts.

    Args:
        action:       "follow" | "like" | "post" | "comment"
        phase:        Current account phase.
        platform:     Platform name.
        daily_counts: Dict with keys "follows", "likes", "posts", "comments"
                      representing today's completed actions.

    Returns:
        (allowed: bool, reason: str)
    """
    limits = get_phase_limits(platform, phase)

    if action == "follow":
        cap = limits.max_follows
        done = daily_counts.get("follows", 0)
    elif action == "like":
        cap = limits.max_likes
        done = daily_counts.get("likes", 0)
    elif action == "post":
        cap = limits.max_posts
        done = daily_counts.get("posts", 0)
    elif action == "comment":
        cap = limits.max_comments
        done = daily_counts.get("comments", 0)
    else:
        return True, ""  # unknown action — let it through

    if cap == 0:
        return False, f"{action} not allowed in {phase} phase"
    if done >= cap:
        return False, f"Daily {action} cap reached ({done}/{cap})"
    return True, ""


# ---------------------------------------------------------------------------
# DB helpers (asyncpg)
# ---------------------------------------------------------------------------


async def advance_account_phase(
    conn,
    account_id: str,
    next_phase: str,
) -> None:
    """
    Write the new phase to the DB and log the transition.
    `conn` is an asyncpg connection.
    """
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        UPDATE accounts
           SET warmup_phase = $1, phase_started_at = $2
         WHERE id = $3
        """,
        next_phase, now, account_id,
    )
    await conn.execute(
        """
        INSERT INTO action_log
            (account_id, agent_name, action_type, status, metadata)
        VALUES ($1, 'phase_system', 'phase_advance', 'success',
                jsonb_build_object('new_phase', $2))
        """,
        account_id, next_phase,
    )
    log.info("Account %s advanced to phase %s", account_id, next_phase)


async def reset_daily_counts(conn, account_id: str) -> None:
    """
    Reset daily action counters to zero. Call once per day per account
    (typically at midnight UTC in the fleet scheduler).
    """
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        UPDATE accounts
           SET daily_follows  = 0,
               daily_likes    = 0,
               daily_posts    = 0,
               daily_comments = 0,
               daily_reset_at = $1
         WHERE id = $2
        """,
        now, account_id,
    )


async def get_daily_counts(conn, account_id: str) -> dict[str, int]:
    """Fetch today's action counts for an account."""
    row = await conn.fetchrow(
        """
        SELECT daily_follows, daily_likes, daily_posts, daily_comments,
               warmup_phase, phase_started_at
          FROM accounts WHERE id = $1
        """,
        account_id,
    )
    if row is None:
        return {"follows": 0, "likes": 0, "posts": 0, "comments": 0}
    return {
        "follows":  row["daily_follows"]  or 0,
        "likes":    row["daily_likes"]    or 0,
        "posts":    row["daily_posts"]    or 0,
        "comments": row["daily_comments"] or 0,
        "phase":    row["warmup_phase"]   or "profile_warmup",
        "phase_started_at": row["phase_started_at"],
    }
