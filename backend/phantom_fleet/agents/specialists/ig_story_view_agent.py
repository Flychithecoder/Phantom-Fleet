"""
IGStoryViewAgent — marks stories as seen to warm the algorithm signal.

Responsibilities:
    - Accept a list of target user IDs whose stories to view
    - Fetch story trays for each target (embedded in feed or via story endpoint)
    - Call client.story_view(reel_id, media_ids) per target
    - Simulate per-story "watch" dwell before marking seen
    - Skip targets gracefully when no active stories are present
    - Enforce hard daily cap of 50 story views per account

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Story view order: targets are processed in the order supplied (caller
      should shuffle the list per account to avoid fleet-wide ordering fingerprints)
    - Per-story dwell: LogNormal(mean=ln(6), σ=0.4) → median ~6s per story,
      matching typical human story watch time (4-15s). Fleet histogram is
      log-normal, not rectangular.
    - Daily cap of 50 enforced by code, not prompt.

Out of scope:
    - Story CREATION/upload — out of scope, see module docstring.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from ...core.distributions import LogNormal
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
# Blast-radius constants (code-enforced)
# ---------------------------------------------------------------------------

MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY: int = 50

# ---------------------------------------------------------------------------
# Distribution instances
# ---------------------------------------------------------------------------

# Per-story "watch" dwell: how long the account "watches" before swiping next
# LogNormal(mean=ln(6), σ=0.4) → median ~6s, 90th-pctile ~10s
_STORY_DWELL_DIST = LogNormal(low=2.0, high=30.0, sigma=0.40)

# Inter-target pause: brief delay moving between story trays
# LogNormal(mean=ln(3), σ=0.3) → median ~3s
_INTER_TARGET_DIST = LogNormal(low=1.0, high=15.0, sigma=0.30)


# ---------------------------------------------------------------------------
# IGStoryViewAgent
# ---------------------------------------------------------------------------


@dataclass
class IGStoryViewResult:
    """Detailed result returned alongside WorkerResult."""
    stories_viewed: int = 0
    accounts_viewed: int = 0
    skipped_no_stories: int = 0
    errors: list[str] = field(default_factory=list)


class IGStoryViewAgent:
    """
    Marks stories as seen for target accounts.

    Helps warm the Instagram algorithm by signaling that the account
    is an active consumer of content from followed users.

    Usage:
        agent = IGStoryViewAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            target_user_ids=["111", "222", ...],
            date_iso="2026-04-11",
        )

    Returns a WorkerResult with `data` keys:
        stories_viewed, accounts_viewed, skipped_no_stories, errors
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        target_user_ids: list[str],
        date_iso: Optional[str] = None,
        views_posted_today: int = 0,
    ) -> WorkerResult:
        """
        Run one story-view session for one account.

        Args:
            account_id:         Internal account identifier.
            session:            Authenticated IGSession.
            target_user_ids:    List of IG user IDs whose stories to view.
                                Caller should shuffle per-account to avoid
                                fleet-wide target ordering fingerprints.
            date_iso:           YYYY-MM-DD (defaults to today UTC).
            views_posted_today: Count of story views already done today.

        Returns:
            WorkerResult with success=True and detailed data dict.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        detail = IGStoryViewResult()
        task_id = f"{account_id}_story_view_{date_iso}"

        async with InstagramClient(session) as client:
            for idx, user_id in enumerate(target_user_ids):
                # Hard daily cap — code enforced
                if views_posted_today >= MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY:
                    log.info(
                        "[%s] Daily story view cap reached (%d), stopping",
                        account_id, MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY,
                    )
                    break

                # Fetch story tray for this user via their reel feed
                try:
                    story_resp = await client._get(
                        f"feed/user/{user_id}/story/",
                        params={"supported_capabilities_new": "[]"},
                    )
                except IGSessionExpired:
                    log.warning("[%s] Session expired fetching stories", account_id)
                    detail.errors.append(f"session_expired:user={user_id}")
                    break
                except IGRateLimited:
                    log.warning("[%s] Rate limited fetching stories", account_id)
                    detail.errors.append(f"rate_limited:user={user_id}")
                    break
                except Exception as exc:
                    log.error("[%s] Error fetching stories for %s: %s", account_id, user_id, exc)
                    detail.errors.append(f"fetch_error:user={user_id}:{exc}")
                    continue

                # Extract reel/media items
                reel = story_resp.get("reel") or story_resp.get("user", {})
                media_items = (
                    reel.get("items", [])
                    if isinstance(reel, dict)
                    else story_resp.get("items", [])
                )

                if not media_items:
                    log.debug("[%s] No active stories for user %s — skipping", account_id, user_id)
                    detail.skipped_no_stories += 1
                    continue

                media_ids = [str(item.get("id", item.get("pk", ""))) for item in media_items if item.get("id") or item.get("pk")]
                if not media_ids:
                    detail.skipped_no_stories += 1
                    continue

                # Per-story watch dwell (before marking seen)
                for media_id in media_ids:
                    if views_posted_today >= MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY:
                        break

                    dwell = _STORY_DWELL_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"story_dwell_{user_id}_{media_id}",
                    )
                    await asyncio.sleep(dwell)

                # Mark stories as seen
                try:
                    await client.story_view(
                        reel_id=user_id,
                        media_ids=media_ids[:MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY - views_posted_today],
                    )

                    stories_in_batch = min(len(media_ids), MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY - views_posted_today)
                    views_posted_today += stories_in_batch
                    detail.stories_viewed += stories_in_batch
                    detail.accounts_viewed += 1

                    log.info(
                        "[%s] Viewed %d stories for user %s",
                        account_id, stories_in_batch, user_id,
                    )

                except IGSessionExpired:
                    log.warning("[%s] Session expired while marking stories seen", account_id)
                    detail.errors.append(f"session_expired_view:user={user_id}")
                    break
                except IGRateLimited:
                    log.warning("[%s] Rate limited while marking stories seen", account_id)
                    detail.errors.append(f"rate_limited_view:user={user_id}")
                    break
                except IGActionBlocked:
                    log.warning("[%s] Story view action blocked", account_id)
                    detail.errors.append(f"action_blocked:user={user_id}")
                    break
                except Exception as exc:
                    log.error("[%s] Story view error for user %s: %s", account_id, user_id, exc)
                    detail.errors.append(f"error:user={user_id}:{exc}")
                    continue

                # Inter-target pause (only if more targets remain)
                if idx < len(target_user_ids) - 1 and views_posted_today < MAX_STORY_VIEWS_PER_ACCOUNT_PER_DAY:
                    inter_delay = _INTER_TARGET_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_target_{user_id}",
                    )
                    await asyncio.sleep(inter_delay)

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":               "story_view",
                "stories_viewed":       detail.stories_viewed,
                "accounts_viewed":      detail.accounts_viewed,
                "skipped_no_stories":   detail.skipped_no_stories,
                "errors":               detail.errors,
            },
        )
