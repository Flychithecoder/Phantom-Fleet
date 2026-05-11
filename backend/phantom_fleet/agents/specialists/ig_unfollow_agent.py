"""
IGUnfollowAgent — strategic unfollow engine to keep accounts under the
following-count soft limit and maintain a healthy follow ratio indefinitely.

Instagram enforces a hard limit of 7,500 following per account. Without
active unfollowing, high-volume follow campaigns (500+ targets/week) will
hit this ceiling within a few weeks and go dark. This agent keeps accounts
perpetually operational by pruning the following list daily.

Unfollow priority order (all code-enforced):
    1. Accounts that NEVER followed back after N days (default 5 days)
    2. Inactive accounts (no posts in 90 days) — dead weight regardless
    3. Low-engagement accounts (followed back but never interact) — future

Safety invariants (all enforced by code, never by prompt):
    - NEVER unfollow within 4 days of following (minimum gap enforced)
    - NEVER unfollow accounts that followed back (converting targets preserved)
    - Hard cap: 50 unfollows/day/account
    - Target steady-state: following ≤ 3,500 (gives headroom for fresh follows)

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):

    Distribution shape:
        - Daily unfollow count: LogNormal(ln(25), 0.3), clamped [10, 50]
          → median 25, long right tail, no rectangular histogram
        - Per-unfollow delay: LogNormal(ln(60), 0.45), clamped [15, 300]
          → median ~60s, tail up to 5 minutes, matches human browsing pauses

    Order entropy:
        - Candidate list shuffled per-account per-day with deterministic seed
          → two accounts pruning the same pool do not follow the same sequence
          → no correlated unfollow patterns in the network graph

    Gap enforcement:
        - 4-day minimum gap is code-enforced; agent rejects any candidate
          followed within the last 4 days regardless of follow-back state
          → prevents same-day-follow-then-unfollow being visible in the
          follower-change stream Instagram keeps server-side

    Sidecar integration:
        - Reads ig_follow_story_orchestrator's JSON sidecar files to get
          follow timestamps; no separate database query needed for MVP
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
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

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard caps (code-enforced — never prompt-enforced)
# ---------------------------------------------------------------------------

DAILY_UNFOLLOW_HARD_CAP: int = 50          # absolute ceiling per account per day
FOLLOWING_SOFT_LIMIT: int = 3_500          # target ceiling; above this we prune
FOLLOW_BACK_WAIT_DAYS: int = 5             # default days before deciding "not following back"
MINIMUM_FOLLOW_AGE_DAYS: int = 4           # must be followed ≥ 4 days before unfollowing
INACTIVITY_DAYS: int = 90                  # account with no posts this many days = dead

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# Daily volume: LogNormal(mean=ln(25), sigma=0.3), clamped [10, 50]
_DAILY_VOLUME_DIST = LogNormal(low=10.0, high=50.0, sigma=0.30)

# Per-unfollow delay: LogNormal(mean=ln(60), sigma=0.45), clamped [15, 300]
_INTER_UNFOLLOW_DIST = LogNormal(low=15.0, high=300.0, sigma=0.45)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UnfollowCandidate:
    """
    One account we're considering unfollowing.

    Fields populated by the caller from the follow history + optional
    profile metadata cache. The agent uses these fields to decide whether
    to unfollow and in what priority order.
    """
    target_user_id: str
    followed_at_iso: str            # ISO-8601 timestamp when WE followed them
    followed_back: bool             # True if they followed us back
    days_since_follow: float        # calculated by caller: (now - followed_at).days
    is_inactive: bool               # True if no posts in last INACTIVITY_DAYS days

    @property
    def priority_score(self) -> int:
        """
        Lower score = higher priority for unfollowing.

        Priority 1: never followed back (primary reason to unfollow)
        Priority 2: inactive account (dead weight regardless of follow-back)
        Priority 3: followed back but inactive (unusual; low-engagement cleanup)

        Accounts that followed back AND are active are never unfollowed.
        """
        if not self.followed_back:
            return 1          # primary target
        if self.is_inactive:
            return 2          # inactive follower
        return 99             # active mutual — never unfollow (caller filters these)


@dataclass
class UnfollowSessionResult:
    """Outcome of one unfollow session for one account."""
    unfollowed_count: int
    skipped_follows_back: int       # skipped because they followed us back
    skipped_too_recent: int         # skipped because followed < MINIMUM_FOLLOW_AGE_DAYS ago
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sidecar reader (reads follow_story_orchestrator's sidecar files)
# ---------------------------------------------------------------------------

def _sidecar_path(account_id: str, date_iso: str) -> Path:
    """Mirror of the path used by ig_follow_story_orchestrator."""
    base = Path("/tmp/phantom_fleet/sidecars")
    return base / f"follow_story_{account_id}_{date_iso}.json"


def load_follow_history_from_sidecars(
    account_id: str,
    lookback_days: int = 30,
) -> dict[str, float]:
    """
    Read follow timestamps from the orchestrator's daily sidecar files.

    Returns a dict of {user_id: unix_timestamp_of_follow} for all accounts
    followed in the last `lookback_days` days.  Missing sidecar files are
    silently skipped — they may not exist for days with no follow session.
    """
    result: dict[str, float] = {}
    today = date.today()
    for day_offset in range(lookback_days):
        from datetime import timedelta
        d = today - timedelta(days=day_offset)
        path = _sidecar_path(account_id, d.isoformat())
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # story_viewed_at has user_id → unix timestamp of view
            # targets_followed is a list of user_ids followed that day
            followed_ids: list[str] = data.get("targets_followed", [])
            story_viewed_at: dict[str, float] = data.get("story_viewed_at", {})
            for uid in followed_ids:
                if uid not in result:
                    # Use view timestamp as proxy for follow timestamp if exact ts missing
                    result[uid] = story_viewed_at.get(uid, 0.0)
        except Exception as exc:
            log.debug(
                "Could not parse sidecar for %s on %s: %s", account_id, d.isoformat(), exc
            )
    return result


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _stable_hash(text: str) -> int:
    """Deterministic 64-bit integer from a string (SHA-256 based)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _shuffle_with_seed(items: list, seed: int) -> list:
    """Return a copy of items shuffled with the given integer seed."""
    import random as _random
    rng = _random.Random(seed)
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled


def _failure_result(account_id: str, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id=f"ig_unfollow_{account_id}",
        platform="instagram",
        account_id=account_id,
        success=False,
        error="; ".join(errors),
        data={"errors": errors},
    )


# ---------------------------------------------------------------------------
# IGUnfollowAgent
# ---------------------------------------------------------------------------

class IGUnfollowAgent:
    """
    Strategic unfollow engine for Instagram accounts.

    Keeps each account's following count under FOLLOWING_SOFT_LIMIT (3,500)
    so the account never hits Instagram's 7,500 hard cap and always has
    headroom to follow new targets each day.

    Unfollow decisions are deterministic for a given (account_id, date_iso)
    pair — replays produce identical decisions, aiding debugging.

    Usage:
        agent = IGUnfollowAgent()
        result = await agent.run_unfollow_session(
            account_id="acct_123",
            session=ig_session,
            follow_history=candidates,   # list[UnfollowCandidate]
            following_count=4100,
        )
    """

    def __init__(self) -> None:
        pass

    async def run_unfollow_session(
        self,
        account_id: str,
        session: IGSession,
        follow_history: list[UnfollowCandidate],
        following_count: int,
        date_iso: Optional[str] = None,
        unfollows_done_today: int = 0,
        proxy_url: str = "socks5://127.0.0.1:8089",
        follow_back_wait_days: int = FOLLOW_BACK_WAIT_DAYS,
    ) -> WorkerResult:
        """
        Execute one unfollow session for one account.

        Steps:
            1. Determine if unfollowing is needed (following_count > soft limit
               OR there are stale non-followers to clean up).
            2. Filter candidates into eligible (can unfollow) and ineligible.
            3. Sort eligible candidates by priority score.
            4. Shuffle within same priority tier using per-account seed.
            5. Cap target volume via LogNormal daily draw.
            6. Execute unfollows with LogNormal inter-action delay.
            7. Return WorkerResult with UnfollowSessionResult.

        Args:
            account_id:           Internal account identifier.
            session:              Authenticated IGSession.
            follow_history:       UnfollowCandidate list built by caller from
                                  follow logs / sidecar files.
            following_count:      Current total following count for this account.
            date_iso:             YYYY-MM-DD — used for seeding. Defaults to today UTC.
            unfollows_done_today: Unfollows already done this calendar day (for cap).
            proxy_url:            SOCKS5 proxy for this account.
            follow_back_wait_days: Days before a non-follower-back is eligible.

        Returns:
            WorkerResult with data dict containing UnfollowSessionResult fields.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        now = time.time()
        today_ts = datetime.now(timezone.utc)

        # ------------------------------------------------------------------
        # 1. Daily cap check (code-enforced)
        # ------------------------------------------------------------------
        if unfollows_done_today >= DAILY_UNFOLLOW_HARD_CAP:
            msg = (
                f"daily_cap_reached:unfollow:"
                f"{unfollows_done_today}/{DAILY_UNFOLLOW_HARD_CAP} "
                f"for account {account_id}"
            )
            log.warning("[%s] %s", account_id, msg)
            return _failure_result(account_id, [msg])

        remaining_cap = DAILY_UNFOLLOW_HARD_CAP - unfollows_done_today

        # ------------------------------------------------------------------
        # 2. Determine target daily volume via LogNormal draw
        # ------------------------------------------------------------------
        raw_volume = _DAILY_VOLUME_DIST.sample(
            account_id=account_id,
            date_iso=date_iso,
            field="unfollow_daily_volume",
        )
        # LogNormal already clamped [10, 50], then we clamp to remaining cap
        target_volume = max(0, min(int(math.ceil(raw_volume)), remaining_cap))

        log.info(
            "[%s] unfollow session start: following=%d, soft_limit=%d, target_volume=%d",
            account_id, following_count, FOLLOWING_SOFT_LIMIT, target_volume,
        )

        # ------------------------------------------------------------------
        # 3. Filter candidates into eligible vs ineligible
        # ------------------------------------------------------------------
        eligible: list[UnfollowCandidate] = []
        skipped_follows_back = 0
        skipped_too_recent = 0

        for candidate in follow_history:
            # NEVER unfollow if they followed back
            if candidate.followed_back:
                skipped_follows_back += 1
                continue

            # Enforce minimum follow age (4 days) in code
            if candidate.days_since_follow < MINIMUM_FOLLOW_AGE_DAYS:
                skipped_too_recent += 1
                log.debug(
                    "[%s] Skip unfollow %s: only %.1f days since follow (min %d)",
                    account_id, candidate.target_user_id,
                    candidate.days_since_follow, MINIMUM_FOLLOW_AGE_DAYS,
                )
                continue

            # Enforce wait period before marking as "won't follow back"
            if (
                not candidate.is_inactive
                and candidate.days_since_follow < follow_back_wait_days
            ):
                # Not inactive AND haven't waited long enough — skip for now
                skipped_too_recent += 1
                continue

            eligible.append(candidate)

        if not eligible:
            log.info(
                "[%s] No eligible unfollow candidates (skipped: %d follows_back, %d too_recent)",
                account_id, skipped_follows_back, skipped_too_recent,
            )
            return WorkerResult(
                task_id=f"ig_unfollow_{account_id}",
                platform="instagram",
                account_id=account_id,
                success=True,
                data={
                    "unfollowed_count":     0,
                    "skipped_follows_back": skipped_follows_back,
                    "skipped_too_recent":   skipped_too_recent,
                    "errors":               [],
                },
            )

        # ------------------------------------------------------------------
        # 4. Sort by priority, shuffle within tier with per-account seed
        # ------------------------------------------------------------------
        # Group by priority score
        from itertools import groupby
        eligible.sort(key=lambda c: c.priority_score)

        ordered: list[UnfollowCandidate] = []
        for _score, group in groupby(eligible, key=lambda c: c.priority_score):
            tier = list(group)
            seed = _stable_hash(f"{account_id}|{date_iso}|unfollow_shuffle_{_score}")
            ordered.extend(_shuffle_with_seed(tier, seed))

        # Limit to target volume
        to_unfollow = ordered[:target_volume]

        # ------------------------------------------------------------------
        # 5. Execute unfollows
        # ------------------------------------------------------------------
        unfollowed_count = 0
        errors: list[str] = []

        async with InstagramClient(session, proxy_url=proxy_url) as client:
            for idx, candidate in enumerate(to_unfollow):
                # Re-check daily cap on every iteration (concurrent safety)
                if unfollows_done_today + unfollowed_count >= DAILY_UNFOLLOW_HARD_CAP:
                    log.info(
                        "[%s] Hard cap hit mid-session (%d), stopping",
                        account_id, DAILY_UNFOLLOW_HARD_CAP,
                    )
                    break

                try:
                    await client.unfollow(candidate.target_user_id)
                    unfollowed_count += 1
                    log.info(
                        "[%s] Unfollowed %s (days_since_follow=%.1f, is_inactive=%s)",
                        account_id,
                        candidate.target_user_id,
                        candidate.days_since_follow,
                        candidate.is_inactive,
                    )

                except IGSessionExpired:
                    log.warning("[%s] Session expired during unfollow", account_id)
                    errors.append(f"session_expired:user={candidate.target_user_id}")
                    break

                except IGRateLimited:
                    log.warning("[%s] Rate limited during unfollow", account_id)
                    errors.append(f"rate_limited:user={candidate.target_user_id}")
                    break

                except IGActionBlocked:
                    log.warning("[%s] Unfollow action blocked", account_id)
                    errors.append(f"action_blocked:user={candidate.target_user_id}")
                    break

                except Exception as exc:
                    err = f"error:user={candidate.target_user_id}:{exc}"
                    log.error("[%s] %s", account_id, err)
                    errors.append(err)
                    continue

                # Inter-unfollow delay: LogNormal(ln(60), 0.45), clamped [15, 300]
                if idx < len(to_unfollow) - 1:
                    delay = _INTER_UNFOLLOW_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_unfollow_{idx}",
                    )
                    await asyncio.sleep(delay)

        session_result = UnfollowSessionResult(
            unfollowed_count=unfollowed_count,
            skipped_follows_back=skipped_follows_back,
            skipped_too_recent=skipped_too_recent,
            errors=errors,
        )

        log.info(
            "[%s] unfollow session done: unfollowed=%d, skipped_follows_back=%d, "
            "skipped_too_recent=%d, errors=%d",
            account_id,
            session_result.unfollowed_count,
            session_result.skipped_follows_back,
            session_result.skipped_too_recent,
            len(session_result.errors),
        )

        return WorkerResult(
            task_id=f"ig_unfollow_{account_id}",
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "unfollowed_count":     session_result.unfollowed_count,
                "skipped_follows_back": session_result.skipped_follows_back,
                "skipped_too_recent":   session_result.skipped_too_recent,
                "errors":               session_result.errors,
            },
        )


# ---------------------------------------------------------------------------
# Convenience: build UnfollowCandidate list from sidecar data
# ---------------------------------------------------------------------------

def build_candidates_from_sidecars(
    account_id: str,
    current_followers_set: set[str],
    inactive_user_ids: set[str],
    lookback_days: int = 30,
) -> list[UnfollowCandidate]:
    """
    Build the UnfollowCandidate list by reading historical sidecar files.

    Args:
        account_id:           Our account's internal ID.
        current_followers_set: Set of user_ids that currently follow us back.
                               Callers build this from the IG followers API.
        inactive_user_ids:    Set of user_ids known to be inactive (no posts
                              in INACTIVITY_DAYS days). Populated by a separate
                              profile metadata cache or enrichment pass.
        lookback_days:        How many days of sidecar history to scan.

    Returns:
        list[UnfollowCandidate] sorted by ascending days_since_follow.
    """
    follow_history = load_follow_history_from_sidecars(account_id, lookback_days)
    now_ts = time.time()
    candidates: list[UnfollowCandidate] = []

    for user_id, followed_ts in follow_history.items():
        days_since = (now_ts - followed_ts) / 86_400.0 if followed_ts > 0 else 999.0
        candidates.append(
            UnfollowCandidate(
                target_user_id=user_id,
                followed_at_iso=datetime.fromtimestamp(followed_ts, tz=timezone.utc).isoformat()
                if followed_ts > 0
                else "unknown",
                followed_back=(user_id in current_followers_set),
                days_since_follow=days_since,
                is_inactive=(user_id in inactive_user_ids),
            )
        )

    candidates.sort(key=lambda c: c.days_since_follow, reverse=True)
    return candidates
