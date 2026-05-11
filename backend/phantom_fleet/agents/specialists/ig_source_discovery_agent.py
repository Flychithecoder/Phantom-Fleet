"""
IGSourceDiscoveryAgent — finds new follow targets by scraping followers of
approved source accounts.

Responsibilities:
    - Accept a list of source account IDs to scrape followers from
    - Paginate get_user_followers(source_id, max_id=cursor) with cursor tracking
    - Score each candidate: (follower_count > 1000) + (following_count < 2000)
      + (is_public) + (has_profile_pic)
    - Filter out already-followed accounts and already-seen candidates
    - Write approved candidates to an output_sink callback
    - Enforce a hard cap of 200 new candidates per session (blast radius)

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Pagination delay: LogNormal(mean=ln(3), σ=0.3) → median ~3s between pages.
      Fleet histogram is log-normal, not a spike at any fixed value.
    - Candidate filtering is pure computation — no additional API calls needed
      beyond the followers list.
    - Hard cap of 200 candidates per session enforced by code, not prompt.

Scoring rubric (score 0-4):
    +1 if follower_count > 1000 (has a real audience, worth targeting)
    +1 if following_count < 2000 (selective, likely sees our account in feed)
    +1 if account is public (we can follow and they see us)
    +1 if has_profile_pic (not a blank/bot account)

All candidates with score >= 1 are written to the output_sink. Callers can
apply a higher score threshold for premium pool selection.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Awaitable, Callable, Optional

from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGRateLimited,
    IGSession,
    IGSessionExpired,
    InstagramClient,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced)
# ---------------------------------------------------------------------------

MAX_CANDIDATES_PER_SESSION: int = 200

# ---------------------------------------------------------------------------
# Distribution instances
# ---------------------------------------------------------------------------

# Delay between pagination requests: LogNormal(mean=ln(3), σ=0.3) → median ~3s
_PAGE_DELAY_DIST = LogNormal(low=1.0, high=15.0, sigma=0.30)


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryCandidate:
    """A discovered follow candidate with its score and raw profile data."""
    user_id: str
    username: str
    follower_count: int
    following_count: int
    is_public: bool
    has_profile_pic: bool
    score: int
    source_account_id: str
    raw: dict = field(default_factory=dict)


def _score_candidate(user: dict, source_account_id: str) -> DiscoveryCandidate:
    """
    Score a follower dict returned by the IG followers API.

    The scoring formula is additive so the components are independently
    debuggable. All conditions are binary (+1 or +0).
    """
    follower_count  = user.get("follower_count", 0)
    following_count = user.get("following_count", user.get("follow_count", 9999))
    is_public       = not user.get("is_private", True)
    has_profile_pic = bool(
        user.get("profile_pic_url") or user.get("profile_pic_id")
    )

    score = (
        int(follower_count > 1000) +
        int(following_count < 2000) +
        int(is_public) +
        int(has_profile_pic)
    )

    return DiscoveryCandidate(
        user_id         = str(user.get("pk") or user.get("id") or ""),
        username        = user.get("username", ""),
        follower_count  = follower_count,
        following_count = following_count,
        is_public       = is_public,
        has_profile_pic = has_profile_pic,
        score           = score,
        source_account_id = source_account_id,
        raw             = user,
    )


# ---------------------------------------------------------------------------
# IGSourceDiscoveryAgent
# ---------------------------------------------------------------------------


@dataclass
class IGSourceDiscoveryResult:
    """Detailed result returned alongside WorkerResult."""
    candidates_found: int = 0
    candidates_approved: int = 0
    pages_scraped: int = 0
    errors: list[str] = field(default_factory=list)


# Type alias for output sink callback
OutputSink = Callable[[list[DiscoveryCandidate]], Awaitable[None]]


class IGSourceDiscoveryAgent:
    """
    Discovers new follow candidates by paginating followers of source accounts.

    Usage:
        async def my_sink(candidates):
            await db.insert_candidates(candidates)

        agent = IGSourceDiscoveryAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            source_account_ids=["111", "222"],
            output_sink=my_sink,
            already_seen=set(),          # mutated in-place
            already_followed=set(),      # set of user_ids to exclude
            max_pages_per_source=10,
            date_iso="2026-04-11",
        )

    Returns a WorkerResult with `data` keys:
        candidates_found, candidates_approved, pages_scraped, errors
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        source_account_ids: list[str],
        output_sink: OutputSink,
        already_seen: Optional[set[str]] = None,
        already_followed: Optional[set[str]] = None,
        max_pages_per_source: int = 10,
        date_iso: Optional[str] = None,
    ) -> WorkerResult:
        """
        Run one discovery session for one account.

        Args:
            account_id:            Internal account identifier.
            session:               Authenticated IGSession.
            source_account_ids:    IG user IDs to scrape followers from.
            output_sink:           Async callback receiving a list of
                                   DiscoveryCandidate; called per page.
            already_seen:          Set of user_ids already discovered in
                                   prior sessions. Mutated in-place.
            already_followed:      Set of user_ids already followed by this
                                   account. Not mutated.
            max_pages_per_source:  Max follower pages to scrape per source.
            date_iso:              YYYY-MM-DD (defaults to today UTC).

        Returns:
            WorkerResult with success=True and detailed data dict.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        if already_seen is None:
            already_seen = set()
        if already_followed is None:
            already_followed = set()

        detail = IGSourceDiscoveryResult()
        task_id = f"{account_id}_source_discovery_{date_iso}"
        total_approved = 0

        async with InstagramClient(session) as client:
            for source_id in source_account_ids:
                # Check blast-radius cap before each source
                if total_approved >= MAX_CANDIDATES_PER_SESSION:
                    log.info(
                        "[%s] Discovery cap reached (%d), stopping",
                        account_id, MAX_CANDIDATES_PER_SESSION,
                    )
                    break

                cursor = ""
                page_num = 0

                while page_num < max_pages_per_source:
                    if total_approved >= MAX_CANDIDATES_PER_SESSION:
                        break

                    try:
                        resp = await client.get_user_followers(
                            user_id=source_id,
                            max_id=cursor,
                            count=50,
                        )
                    except IGSessionExpired:
                        log.warning("[%s] Session expired during discovery", account_id)
                        detail.errors.append(f"session_expired:source={source_id}")
                        break
                    except IGRateLimited:
                        log.warning("[%s] Rate limited during discovery", account_id)
                        detail.errors.append(f"rate_limited:source={source_id}")
                        break
                    except Exception as exc:
                        log.error("[%s] Discovery error for source %s: %s", account_id, source_id, exc)
                        detail.errors.append(f"error:source={source_id}:{exc}")
                        break

                    users = resp.get("users", [])
                    next_cursor = resp.get("next_max_id", "")
                    detail.pages_scraped += 1
                    page_num += 1

                    # Score and filter this page's users
                    page_candidates: list[DiscoveryCandidate] = []
                    for user in users:
                        user_id = str(user.get("pk") or user.get("id") or "")
                        if not user_id:
                            continue

                        detail.candidates_found += 1

                        # Filter already-seen and already-followed
                        if user_id in already_seen or user_id in already_followed:
                            continue

                        candidate = _score_candidate(user, source_id)
                        if candidate.score < 1:
                            continue

                        already_seen.add(user_id)
                        page_candidates.append(candidate)
                        total_approved += 1
                        detail.candidates_approved += 1

                        if total_approved >= MAX_CANDIDATES_PER_SESSION:
                            break

                    # Write approved candidates to sink
                    if page_candidates:
                        try:
                            await output_sink(page_candidates)
                        except Exception as exc:
                            log.error("[%s] output_sink error: %s", account_id, exc)
                            detail.errors.append(f"sink_error:{exc}")

                    # Stop pagination if no next cursor
                    if not next_cursor:
                        break

                    cursor = next_cursor

                    # Natural pagination delay
                    page_delay = _PAGE_DELAY_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"page_delay_{source_id}_{page_num}",
                    )
                    await asyncio.sleep(page_delay)

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":               "source_discovery",
                "candidates_found":     detail.candidates_found,
                "candidates_approved":  detail.candidates_approved,
                "pages_scraped":        detail.pages_scraped,
                "errors":               detail.errors,
            },
        )
