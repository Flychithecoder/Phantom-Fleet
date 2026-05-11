"""
IGCompetitorHarvesterAgent — scrapes followers of competitor/top-creator accounts.

Followers of proven top-of-funnel lifestyle creators are the highest-quality
cold targets in the niche.

Detection hardening (CLAUDE.md 20K account fleet-level):
    - Pagination delay: LogNormal(mean=ln(5), σ=0.4) → median ~5s, log-normal histogram.
    - Scraping is rotated across scraping_accounts so no single account accumulates
      a large per-session follower-scrape footprint. Each account does at most 100
      profiles before rotating to the next one.
    - Hard cap of 200 NEW targets per session, enforced by code.
    - Competitor cooldown enforced by CompetitorRegistry (≥7 days between harvests
      for the same handle).

Scoring rubric (0–8 scale, filter ≥ 4):
    +2  is_public
    +2  follower_count 200–15000 (engaged niche accounts)
    +1  following_count < 5000
    +1  has_profile_pic
    +1  has_bio (shows real person)
    +1  account age > 180 days (estimated from user_id range — large IDs = newer)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
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
# Blast-radius constant (code-enforced, not prompt)
# ---------------------------------------------------------------------------

MAX_NEW_TARGETS_PER_SESSION: int = 200
MAX_PROFILES_PER_SCRAPING_ACCOUNT: int = 100

# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

# LogNormal(mean=ln(5), σ=0.4) → median ~5s between pagination requests
_PAGE_DELAY_DIST = LogNormal(low=1.5, high=30.0, sigma=0.40)

# ---------------------------------------------------------------------------
# User-ID age estimation
# ---------------------------------------------------------------------------

# Instagram numeric user IDs are roughly sequential. Accounts created before
# mid-2017 have IDs below ~4 billion; rough threshold for "old enough".
# This is an approximation — precision is not needed for a +1 bonus.
_OLD_ACCOUNT_UID_THRESHOLD: int = 4_000_000_000


def _estimate_old_account(user_id: str) -> bool:
    """True if user_id suggests the account is older than ~180 days."""
    try:
        return int(user_id) < _OLD_ACCOUNT_UID_THRESHOLD
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Candidate dataclass + scorer
# ---------------------------------------------------------------------------


@dataclass
class HarvestedCandidate:
    """A follower harvested from a competitor account, scored for quality."""
    user_id: str
    username: str
    follower_count: int
    following_count: int
    is_public: bool
    has_profile_pic: bool
    has_bio: bool
    estimated_old_account: bool
    score: int
    competitor_handle: str
    raw: dict = field(default_factory=dict)


def _score_candidate(user: dict, competitor_handle: str) -> HarvestedCandidate:
    """
    Score a follower dict returned by IG followers API.

    Scoring is additive so each component is independently auditable.
    """
    follower_count  = int(user.get("follower_count", 0) or 0)
    following_count = int(user.get("following_count", user.get("follow_count", 9999)) or 9999)
    is_public       = not bool(user.get("is_private", True))
    has_profile_pic = bool(user.get("profile_pic_url") or user.get("profile_pic_id"))
    biography       = user.get("biography", user.get("bio", "")) or ""
    has_bio         = bool(biography.strip())
    user_id_str     = str(user.get("pk") or user.get("id") or "0")
    est_old         = _estimate_old_account(user_id_str)

    score = (
        (2 if is_public else 0)
        + (2 if 200 <= follower_count <= 15_000 else 0)  # engaged niche accounts
        + (1 if following_count < 5_000 else 0)
        + (1 if has_profile_pic else 0)
        + (1 if has_bio else 0)                           # shows real person
        + (1 if est_old else 0)
    )

    return HarvestedCandidate(
        user_id               = user_id_str,
        username              = user.get("username", ""),
        follower_count        = follower_count,
        following_count       = following_count,
        is_public             = is_public,
        has_profile_pic       = has_profile_pic,
        has_bio               = has_bio,
        estimated_old_account = est_old,
        score                 = score,
        competitor_handle     = competitor_handle,
        raw                   = user,
    )


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class HarvestResult:
    candidates_found:    int = 0
    candidates_approved: int = 0
    pages_scraped:       int = 0
    competitors_scraped: list[str] = field(default_factory=list)
    errors:              list[str] = field(default_factory=list)


# Type alias
HarvestSink = Callable[[list[HarvestedCandidate]], Awaitable[None]]


# ---------------------------------------------------------------------------
# IGCompetitorHarvesterAgent
# ---------------------------------------------------------------------------


class IGCompetitorHarvesterAgent:
    """
    Scrapes followers of competitor/top-creator accounts on Instagram.
    These followers are proven buyers in the niche — highest-quality targets.

    Operates carefully: pagination with natural delays, max pages per session,
    multiple accounts rotating the scraping work (no single account does all of it).

    Usage:
        agent = IGCompetitorHarvesterAgent()
        result = await agent.harvest_followers(task)

    task.params keys:
        competitor_handles   list[str]        — IG usernames to harvest from
        max_per_competitor   int (default 500) — max followers per competitor
        scraping_accounts    list[dict]        — each: {"account_id", "session"}
        output_sink          HarvestSink       — async callback for batches
        already_seen         set[str]          — mutated in-place; optional
        date_iso             str               — YYYY-MM-DD; optional
    """

    async def harvest_followers(self, task) -> WorkerResult:
        """
        Main entry point. Rotates scraping across provided accounts,
        paginating each competitor's followers with natural delays.

        Returns WorkerResult with data dict containing harvest statistics.
        """
        params             = task.params
        competitor_handles: list[str]    = params["competitor_handles"]
        max_per_competitor: int          = int(params.get("max_per_competitor", 500))
        scraping_accounts:  list[dict]   = params["scraping_accounts"]
        output_sink:        HarvestSink  = params["output_sink"]
        already_seen:       set[str]     = params.get("already_seen") or set()
        date_iso:           str          = params.get("date_iso") or date.today().isoformat()

        if not scraping_accounts:
            return WorkerResult(
                task_id    = getattr(task, "task_id", "harvest"),
                platform   = "instagram",
                account_id = "multi",
                success    = False,
                error      = "No scraping_accounts provided",
            )

        detail         = HarvestResult()
        total_approved = 0

        # Round-robin index across scraping accounts
        account_index       = 0
        profiles_this_acct  = 0

        def _next_scraping_acct() -> dict:
            nonlocal account_index, profiles_this_acct
            acct = scraping_accounts[account_index % len(scraping_accounts)]
            profiles_this_acct = 0
            return acct

        current_acct = _next_scraping_acct()

        for handle in competitor_handles:
            if total_approved >= MAX_NEW_TARGETS_PER_SESSION:
                log.info("[harvester] Session cap reached (%d), stopping", MAX_NEW_TARGETS_PER_SESSION)
                break

            # Resolve handle → user_id
            competitor_id: Optional[str] = None
            try:
                session: IGSession = current_acct["session"]
                async with InstagramClient(session) as client:
                    info = await client.get_user_info(handle)
                    user_node = info.get("user") or info
                    competitor_id = str(user_node.get("pk") or user_node.get("id") or "")
            except (IGSessionExpired, IGRateLimited, Exception) as exc:
                log.warning("[harvester] Could not resolve handle %s: %s", handle, exc)
                detail.errors.append(f"resolve_failed:{handle}:{exc}")
                continue

            if not competitor_id:
                log.warning("[harvester] Empty competitor_id for handle %s", handle)
                detail.errors.append(f"empty_id:{handle}")
                continue

            # Paginate this competitor's followers
            cursor              = ""
            harvested_this_comp = 0

            while harvested_this_comp < max_per_competitor:
                if total_approved >= MAX_NEW_TARGETS_PER_SESSION:
                    break

                # Rotate scraping account if this one has hit its per-account max
                if profiles_this_acct >= MAX_PROFILES_PER_SCRAPING_ACCOUNT:
                    account_index += 1
                    current_acct       = _next_scraping_acct()
                    log.debug(
                        "[harvester] Rotating to account %s",
                        current_acct.get("account_id"),
                    )

                session = current_acct["session"]
                acct_id = current_acct.get("account_id", "unknown")

                try:
                    async with InstagramClient(session) as client:
                        resp = await client.get_user_followers(
                            user_id = competitor_id,
                            max_id  = cursor,
                            count   = 50,
                        )
                except IGSessionExpired:
                    log.warning("[harvester][%s] Session expired", acct_id)
                    detail.errors.append(f"session_expired:{acct_id}")
                    account_index += 1
                    current_acct       = _next_scraping_acct()
                    break
                except IGRateLimited:
                    log.warning("[harvester][%s] Rate limited on %s", acct_id, handle)
                    detail.errors.append(f"rate_limited:{acct_id}:{handle}")
                    break
                except Exception as exc:
                    log.error("[harvester][%s] Error paginating %s: %s", acct_id, handle, exc)
                    detail.errors.append(f"page_error:{handle}:{exc}")
                    break

                users       = resp.get("users", [])
                next_cursor = resp.get("next_max_id", "")
                detail.pages_scraped += 1

                page_candidates: list[HarvestedCandidate] = []
                for user in users:
                    uid = str(user.get("pk") or user.get("id") or "")
                    if not uid:
                        continue

                    detail.candidates_found += 1
                    profiles_this_acct      += 1
                    harvested_this_comp     += 1

                    if uid in already_seen:
                        continue

                    candidate = _score_candidate(user, handle)
                    if candidate.score < 4:
                        continue

                    already_seen.add(uid)
                    page_candidates.append(candidate)
                    total_approved         += 1
                    detail.candidates_approved += 1

                    if total_approved >= MAX_NEW_TARGETS_PER_SESSION:
                        break

                if page_candidates:
                    try:
                        await output_sink(page_candidates)
                    except Exception as exc:
                        log.error("[harvester] output_sink error: %s", exc)
                        detail.errors.append(f"sink_error:{exc}")

                if not next_cursor:
                    break

                cursor = next_cursor

                # Natural pagination delay — LogNormal, never uniform
                delay = _PAGE_DELAY_DIST.sample(
                    account_id = acct_id,
                    date_iso   = date_iso,
                    field      = f"harvest_page_{handle}",
                )
                await asyncio.sleep(delay)

            if competitor_id:
                detail.competitors_scraped.append(handle)

        return WorkerResult(
            task_id    = getattr(task, "task_id", "harvest"),
            platform   = "instagram",
            account_id = "multi",
            success    = True,
            data       = {
                "action":               "competitor_harvest",
                "candidates_found":     detail.candidates_found,
                "candidates_approved":  detail.candidates_approved,
                "pages_scraped":        detail.pages_scraped,
                "competitors_scraped":  detail.competitors_scraped,
                "errors":               detail.errors,
            },
        )
