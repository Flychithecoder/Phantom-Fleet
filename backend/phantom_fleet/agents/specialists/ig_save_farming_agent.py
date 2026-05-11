"""
IGSaveFarmingAgent — coordinates child accounts to save creator posts,
boosting the Instagram algorithm signal that drives organic reach.

Post SAVES are Instagram's highest-value engagement signal. A save tells
the recommendation algorithm "this content is worth bookmarking" — it carries
far more algorithmic weight than likes or comments. By coordinating a fleet
of child accounts to save creator posts, we dramatically increase the creator's
(or mother account's) content reach without any synthetic engagement pattern.

Why saves matter algorithmically:
    Instagram's feed and Reels ranking treats saves as a strong "user found this
    valuable" signal. A post with many saves within the first few hours of
    publishing gets pushed to the Explore page and Reels recommendation feed,
    generating 10x–100x organic impressions from non-followers.

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):

    Volume distribution:
        - Daily saves per child account: LogNormal(ln(3), 0.3), clamped [1, 6]
        - Median of ~3 saves/day is indistinguishable from a user who bookmarks
          a few things each day; [1, 6] range means no account has a suspiciously
          uniform save count
        - Hard cap: 6 saves/account/day (code-enforced, not prompt-enforced)

    Timing:
        - Save delay after viewing post: LogNormal(ln(8), 0.5), clamped [2, 60]
          → median ~8s, simulates "reading/watching then deciding to save"
        - Inter-save delay: LogNormal(ln(300), 0.4), clamped [60, 900]
          → median ~5 minutes between saves, very natural scroll behavior
        - Fleet stagger: SHA-256 offset per account spreads saves across a
          4-hour window → not all 500 accounts save the same post simultaneously

    Dedup:
        - NEVER save the same media_id twice per account (dedup set provided by caller)
        - Dedup is code-enforced via set membership check, not prompt-enforced

    Fleet coordination:
        - save_offset_minutes = SHA-256(account_id + media_id) % 240
        - Caller should respect this offset to schedule when each account saves
        - Ensures a fleet of 500 accounts saving the same post appears to do so
          over a natural 4-hour window, not in a single 1-second burst

    Post freshness priority:
        - Posts < 48 hours old are prioritized (fresh saves have more weight)
        - Caller passes creator_posts_to_save sorted by priority (newest first)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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

DAILY_SAVE_HARD_CAP: int = 6           # absolute ceiling per child account per day
FRESH_POST_AGE_HOURS: int = 48         # posts younger than this get priority
FLEET_STAGGER_WINDOW_MINUTES: int = 240  # 4-hour spread window for fleet coordination

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# Daily save count: LogNormal(mean=ln(3), sigma=0.3), clamped [1, 6]
_DAILY_COUNT_DIST = LogNormal(low=1.0, high=6.0, sigma=0.30)

# View-to-save delay: LogNormal(mean=ln(8), sigma=0.5), clamped [2, 60]
# Simulates user reading/watching the post before deciding to bookmark it
_VIEW_TO_SAVE_DIST = LogNormal(low=2.0, high=60.0, sigma=0.50)

# Inter-save delay: LogNormal(mean=ln(300), sigma=0.4), clamped [60, 900]
# ~5 minutes average between saves; matches organic scroll-and-bookmark behavior
_INTER_SAVE_DIST = LogNormal(low=60.0, high=900.0, sigma=0.40)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CreatorPost:
    """
    One post from a followed creator, eligible for saving.

    Callers build this list from the account's feed API response.
    Sort by posted_at descending (newest first) to ensure fresh posts
    are prioritized when the daily cap limits how many we can save.
    """
    media_id: str
    posted_at_iso: str            # ISO-8601 when the post was published
    creator_user_id: str

    @property
    def age_hours(self) -> float:
        """Hours since the post was published (approximate, uses UTC)."""
        try:
            posted = datetime.fromisoformat(self.posted_at_iso.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return (now - posted).total_seconds() / 3600.0
        except Exception:
            return 9999.0  # unknown age → treat as old

    @property
    def is_fresh(self) -> bool:
        """True if the post is younger than FRESH_POST_AGE_HOURS."""
        return self.age_hours < FRESH_POST_AGE_HOURS


@dataclass
class SaveSessionResult:
    """Outcome of one save session for one child account."""
    saves_sent: int
    skipped_already_saved: int
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _stable_hash(text: str) -> int:
    """Deterministic 64-bit integer from a string (SHA-256 based)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def save_offset_minutes(account_id: str, media_id: str) -> int:
    """
    Per-account, per-post offset in minutes within the fleet stagger window.

    Returns an integer in [0, FLEET_STAGGER_WINDOW_MINUTES).
    The caller should delay the save action for this account by this many
    minutes relative to the session start time, so a fleet of 500 accounts
    saving the same post appears to do so across a natural 4-hour window
    rather than in a synchronised burst.

    This is a pure function — the same (account_id, media_id) pair always
    returns the same offset, making it replay-safe.
    """
    seed_input = f"{account_id}|{media_id}|fleet_stagger".encode("utf-8")
    seed = int(hashlib.sha256(seed_input).hexdigest(), 16)
    return seed % FLEET_STAGGER_WINDOW_MINUTES


def _failure_result(account_id: str, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id=f"ig_save_{account_id}",
        platform="instagram",
        account_id=account_id,
        success=False,
        error="; ".join(errors),
        data={"errors": errors},
    )


# ---------------------------------------------------------------------------
# IGSaveFarmingAgent
# ---------------------------------------------------------------------------

class IGSaveFarmingAgent:
    """
    Coordinates child accounts to save creator posts, boosting the creator's
    organic reach through Instagram's algorithm save signal.

    Each child account saves 2-4 posts per day from target creators, prioritising
    fresh posts (< 48 hours old). Saves are staggered across the fleet using
    SHA-256 per-account offsets to prevent synchronised save bursts.

    Safety invariants:
        - NEVER save the same media_id twice per account (dedup by caller-provided set)
        - Hard cap: 6 saves/account/day (code-enforced)
        - View-to-save delay simulates real reading/watching behavior
        - Inter-save delay matches natural scroll-and-bookmark patterns

    Usage:
        agent = IGSaveFarmingAgent()
        result = await agent.run_save_session(
            account_id="child_456",
            session=ig_session,
            creator_posts_to_save=[
                CreatorPost(media_id="123", posted_at_iso="2026-04-11T08:00:00Z",
                            creator_user_id="creator_789"),
            ],
            saves_sent_today=0,
        )

    Stub (not used in this agent but provided for completeness):
        await agent.unsave_post(session, media_id)
    """

    def __init__(self) -> None:
        pass

    async def run_save_session(
        self,
        account_id: str,
        session: IGSession,
        creator_posts_to_save: list[CreatorPost],
        saves_sent_today: int,
        already_saved_media_ids: Optional[set[str]] = None,
        date_iso: Optional[str] = None,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ) -> WorkerResult:
        """
        Execute one save session for one child account.

        Posts in creator_posts_to_save should be sorted by the caller:
            1. Fresh posts first (age < 48h) — fresh saves carry more algorithmic weight
            2. Within each freshness tier, newest first

        The agent will save up to the LogNormal-sampled daily target, limited
        by the DAILY_SAVE_HARD_CAP, then stop.

        Steps:
            1. Daily cap check (code-enforced)
            2. Sample today's save target via LogNormal
            3. Filter out already-saved posts (dedup)
            4. Execute saves with view-to-save and inter-save delays
            5. Return WorkerResult

        Args:
            account_id:               Child account internal identifier.
            session:                  Authenticated IGSession.
            creator_posts_to_save:    Posts to consider saving, sorted by priority.
            saves_sent_today:         Saves already sent today (cap check).
            already_saved_media_ids:  Set of media_ids already saved by this account.
                                      Agent will not save any post in this set.
            date_iso:                 YYYY-MM-DD for seeding. Defaults to today UTC.
            proxy_url:                SOCKS5 proxy for this account.

        Returns:
            WorkerResult with data = {saves_sent, errors, skipped_already_saved}
        """
        if date_iso is None:
            date_iso = date.today().isoformat()
        if already_saved_media_ids is None:
            already_saved_media_ids = set()

        # ------------------------------------------------------------------
        # 1. Daily cap check (code-enforced)
        # ------------------------------------------------------------------
        if saves_sent_today >= DAILY_SAVE_HARD_CAP:
            msg = (
                f"daily_cap_reached:save:"
                f"{saves_sent_today}/{DAILY_SAVE_HARD_CAP} "
                f"for account {account_id}"
            )
            log.warning("[%s] %s", account_id, msg)
            return _failure_result(account_id, [msg])

        remaining_cap = DAILY_SAVE_HARD_CAP - saves_sent_today

        # ------------------------------------------------------------------
        # 2. Sample today's target save count via LogNormal
        # ------------------------------------------------------------------
        raw_target = _DAILY_COUNT_DIST.sample(
            account_id=account_id,
            date_iso=date_iso,
            field="save_daily_count",
        )
        target = max(1, min(int(math.ceil(raw_target)), remaining_cap))

        log.info(
            "[%s] save session start: target=%d, remaining_cap=%d, candidates=%d",
            account_id, target, remaining_cap, len(creator_posts_to_save),
        )

        # ------------------------------------------------------------------
        # 3. Filter candidates (dedup)
        # ------------------------------------------------------------------
        eligible: list[CreatorPost] = []
        skipped_already_saved = 0

        for post in creator_posts_to_save:
            if post.media_id in already_saved_media_ids:
                skipped_already_saved += 1
                log.debug("[%s] Skip %s — already saved", account_id, post.media_id)
                continue
            eligible.append(post)

        if not eligible:
            log.info("[%s] No eligible posts to save (all already saved)", account_id)
            return WorkerResult(
                task_id=f"ig_save_{account_id}",
                platform="instagram",
                account_id=account_id,
                success=True,
                data={
                    "saves_sent":            0,
                    "skipped_already_saved": skipped_already_saved,
                    "errors":                [],
                },
            )

        # Limit to target
        to_save = eligible[:target]

        # ------------------------------------------------------------------
        # 4. Execute saves
        # ------------------------------------------------------------------
        saves_sent = 0
        errors: list[str] = []

        async with InstagramClient(session, proxy_url=proxy_url) as client:
            for idx, post in enumerate(to_save):
                # Re-check hard cap on every iteration (concurrent safety)
                if saves_sent_today + saves_sent >= DAILY_SAVE_HARD_CAP:
                    log.info(
                        "[%s] Hard cap hit mid-session (%d), stopping",
                        account_id, DAILY_SAVE_HARD_CAP,
                    )
                    break

                # View-to-save delay (simulates reading/watching before bookmarking)
                view_delay = _VIEW_TO_SAVE_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"view_to_save_{idx}",
                )
                await asyncio.sleep(view_delay)

                # Execute save via POST /api/v1/media/{media_id}/save/
                try:
                    await client.save_post(post.media_id)
                    saves_sent += 1
                    already_saved_media_ids.add(post.media_id)
                    log.info(
                        "[%s] Saved post %s from creator %s (age=%.1fh, fresh=%s)",
                        account_id,
                        post.media_id,
                        post.creator_user_id,
                        post.age_hours,
                        post.is_fresh,
                    )

                except IGSessionExpired:
                    log.warning("[%s] Session expired during save", account_id)
                    errors.append(f"session_expired:media={post.media_id}")
                    break

                except IGRateLimited:
                    log.warning("[%s] Rate limited during save", account_id)
                    errors.append(f"rate_limited:media={post.media_id}")
                    break

                except IGActionBlocked:
                    log.warning("[%s] Save action blocked", account_id)
                    errors.append(f"action_blocked:media={post.media_id}")
                    break

                except Exception as exc:
                    err = f"error:media={post.media_id}:{exc}"
                    log.error("[%s] %s", account_id, err)
                    errors.append(err)
                    continue

                # Inter-save delay (only if more saves remain)
                if idx < len(to_save) - 1:
                    inter_delay = _INTER_SAVE_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_save_{idx}",
                    )
                    await asyncio.sleep(inter_delay)

        session_result = SaveSessionResult(
            saves_sent=saves_sent,
            skipped_already_saved=skipped_already_saved,
            errors=errors,
        )

        log.info(
            "[%s] save session done: saves_sent=%d, skipped_already_saved=%d, errors=%d",
            account_id,
            session_result.saves_sent,
            session_result.skipped_already_saved,
            len(session_result.errors),
        )

        return WorkerResult(
            task_id=f"ig_save_{account_id}",
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "saves_sent":            session_result.saves_sent,
                "skipped_already_saved": session_result.skipped_already_saved,
                "errors":                session_result.errors,
            },
        )

    # ------------------------------------------------------------------
    # Stub for unsave (not used by this agent but wired for counterpart)
    # ------------------------------------------------------------------

    async def unsave_post(
        self,
        account_id: str,
        session: IGSession,
        media_id: str,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ) -> WorkerResult:
        """
        Remove a saved post.

        Uses POST /api/v1/media/{media_id}/unsave/ — not used in the
        save farming flow, but provided here as a counterpart for any
        future cleanup or A/B unsave-then-resave testing.

        Args:
            account_id: Internal account identifier.
            session:    Authenticated IGSession.
            media_id:   The media ID to unsave.
            proxy_url:  SOCKS5 proxy for this account.

        Returns:
            WorkerResult with data = {media_id, unsaved_at}
        """
        async with InstagramClient(session, proxy_url=proxy_url) as client:
            try:
                await client.unsave_post(media_id)
                from datetime import datetime, timezone
                return WorkerResult(
                    task_id=f"ig_unsave_{account_id}",
                    platform="instagram",
                    account_id=account_id,
                    success=True,
                    data={
                        "media_id":   media_id,
                        "unsaved_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:
                err = f"unsave_failed:{type(exc).__name__}:{exc}"
                log.error("[%s] %s", account_id, err)
                return _failure_result(account_id, [err])
