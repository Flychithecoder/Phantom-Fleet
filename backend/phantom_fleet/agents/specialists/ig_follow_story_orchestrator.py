"""
IGFollowStoryOrchestrator — the core Instagram growth engine.

CORRECT sequence (Story-first, then follow):

    Session 1 (Morning): View stories of targets + React to ~30%
        → Target sees us in their story viewers list
        → If we reacted: target receives DM notification "X reacted ❤️ to your story"

    Session 2 (2-4 hrs later): Follow accounts whose stories we viewed
        → Target sees "X followed you" notification
        → They check our profile — they recognise us from the story viewers list
        → Follow-back rate significantly higher vs cold follow (familiar face effect)

Why this order matters:
    When you follow someone cold, you're a stranger. When you view their story
    first, they see your username in their viewers list. Then when you follow
    them 2-4 hours later, the follow notification is from a "familiar face" they
    saw recently. This recognition effect increases follow-back rate.

    Volume ratio: 5-7x more story views than follows per day.
    - Story views: 500-900/day (platform very lenient on views)
    - Follows: 80-150/day (warming curve enforced)

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Target ORDER is shuffled per-account per-day (seeded by
      hash(account_id+date_iso)) so fleet-wide target ordering is not
      correlated across accounts.
    - 30-day re-follow dedup: never follow someone followed in last 30 days,
      enforced by code not prompt.
    - Inter-follow sleep: LogNormal(mean=ln(35), sigma=0.45) — median ~35s.
    - Inter-target story sleep: LogNormal(mean=ln(8), sigma=0.3) — median ~8s.
    - Per-story dwell: LogNormal(mean=ln(5), sigma=0.4) — median ~5s.
    - Story react delegation: IGStoryReactAgent.run_session() called inline
      after each account's stories are viewed (in morning session).
    - Volume caps enforced by code, not prompt.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
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
from .ig_story_react_agent import IGStoryReactAgent, StoryViewRecord

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing constants
# ---------------------------------------------------------------------------

# Follow must happen 2-4 hours after the story view (sweet spot for recognition)
# Still accept up to 8 hours — story recognition still works, story may have expired
STORY_TO_FOLLOW_MIN_SECS: float = 2 * 3600   # 2 hours
STORY_TO_FOLLOW_MAX_SECS: float = 8 * 3600   # 8 hours

# Re-follow dedup window (seconds = 30 days)
REFOLLOW_COOLDOWN_SECS: float = 30 * 24 * 3600

# ---------------------------------------------------------------------------
# Volume caps by warming stage (code-enforced)
# ---------------------------------------------------------------------------

DAILY_STORY_VIEW_CAPS: dict[str, int] = {
    "days_0_7":    150,   # new account — conservative
    "days_7_30":   400,   # growing
    "days_30_plus": 700,  # steady state
}

DAILY_FOLLOW_CAPS: dict[str, int] = {
    "days_0_7":    20,
    "days_7_30":   60,
    "days_30_plus": 130,
}


def _warming_stage(warmup_day: int) -> str:
    """Map day index to warming stage key."""
    if warmup_day < 7:
        return "days_0_7"
    elif warmup_day < 30:
        return "days_7_30"
    return "days_30_plus"


def story_view_cap_for_day(warmup_day: int) -> int:
    """Return the story view cap for a given warming day."""
    return DAILY_STORY_VIEW_CAPS[_warming_stage(warmup_day)]


def follow_cap_for_day(warmup_day: int) -> int:
    """Return the follow cap for a given warming day."""
    return DAILY_FOLLOW_CAPS[_warming_stage(warmup_day)]


# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# Inter-follow sleep: LogNormal(mean=ln(35), sigma=0.45) — median ~35s
_INTER_FOLLOW_DIST = LogNormal(low=8.0, high=180.0, sigma=0.45)

# Inter-target story sleep: LogNormal(mean=ln(8), sigma=0.3) — median ~8s
_INTER_STORY_TARGET_DIST = LogNormal(low=2.0, high=45.0, sigma=0.30)

# Per-story dwell: LogNormal(mean=ln(5), sigma=0.4) — median ~5s
_STORY_DWELL_DIST = LogNormal(low=2.0, high=25.0, sigma=0.40)


# ---------------------------------------------------------------------------
# Session state sidecar
# ---------------------------------------------------------------------------

@dataclass
class FollowStorySession:
    """
    In-memory state for one account's story-view+follow day.

    The CORRECT order is stored explicitly:
        1. targets_story_viewed: user_ids whose stories we viewed (morning session)
        2. story_viewed_at:      when we viewed each user's stories (for timing window)
        3. targets_reacted:      user_ids we reacted to during morning session
        4. targets_followed:     user_ids we followed (follow-up session, 2-4hrs later)

    Persisted as JSON sidecar between morning and follow-up sessions.
    """
    account_id: str
    date_iso: str
    # Morning: story views + reactions
    targets_story_viewed: list[str] = field(default_factory=list)   # user_ids whose stories we viewed
    story_viewed_at: dict[str, float] = field(default_factory=dict) # user_id → unix timestamp
    targets_reacted: list[str] = field(default_factory=list)        # user_ids we reacted to
    # Follow-up session: follows (AFTER story view)
    targets_followed: list[str] = field(default_factory=list)       # user_ids we followed
    # Stats
    follow_back_count: int = 0
    no_story_skips: int = 0   # targets with no active stories during morning session

    def to_dict(self) -> dict:
        return {
            "account_id":            self.account_id,
            "date_iso":              self.date_iso,
            "targets_story_viewed":  self.targets_story_viewed,
            "story_viewed_at":       self.story_viewed_at,
            "targets_reacted":       self.targets_reacted,
            "targets_followed":      self.targets_followed,
            "follow_back_count":     self.follow_back_count,
            "no_story_skips":        self.no_story_skips,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FollowStorySession":
        return cls(
            account_id=d["account_id"],
            date_iso=d["date_iso"],
            targets_story_viewed=d.get("targets_story_viewed", []),
            story_viewed_at=d.get("story_viewed_at", {}),
            targets_reacted=d.get("targets_reacted", []),
            targets_followed=d.get("targets_followed", []),
            follow_back_count=d.get("follow_back_count", 0),
            no_story_skips=d.get("no_story_skips", 0),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_hash(text: str) -> int:
    """Deterministic 64-bit integer from a string."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _shuffle_with_seed(items: list, seed: int) -> list:
    """Return a copy of items shuffled with the given seed."""
    import random as _random
    rng = _random.Random(seed)
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled


def _sidecar_path(account_id: str, date_iso: str) -> Path:
    """
    Path to the JSON sidecar file for a given account+date.
    Stored under /tmp/phantom_fleet/sidecars/ — ephemeral, cleaned daily.
    """
    base = Path("/tmp/phantom_fleet/sidecars")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"follow_story_{account_id}_{date_iso}.json"


def _save_session(session: FollowStorySession) -> None:
    path = _sidecar_path(session.account_id, session.date_iso)
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")


def _load_session(account_id: str, date_iso: str) -> Optional[FollowStorySession]:
    path = _sidecar_path(account_id, date_iso)
    if not path.exists():
        return None
    try:
        return FollowStorySession.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        log.warning("Could not load session sidecar for %s %s: %s", account_id, date_iso, exc)
        return None


# ---------------------------------------------------------------------------
# IGFollowStoryOrchestrator
# ---------------------------------------------------------------------------


class IGFollowStoryOrchestrator:
    """
    Core Instagram growth engine. Correct sequence:

    Session 1 (Morning): View stories of targets + React to ~30%
    Session 2 (2-4 hrs later): Follow accounts whose stories we viewed

    Why this order:
    - Target sees us in their story viewers first (recognition)
    - Then we follow → they see familiar face in follow notification
    - Follow-back rate is significantly higher vs cold follow

    Volume ratio: 5-7x more story views than follows per day
    - Story views: 500-900/day (platform very lenient)
    - Follows: 80-150/day (warming curve enforced)
    """

    def __init__(self, react_agent: Optional[IGStoryReactAgent] = None):
        self._react_agent = react_agent or IGStoryReactAgent()

    # ------------------------------------------------------------------
    # Session 1 (Morning): Story view + react
    # ------------------------------------------------------------------

    async def run_morning_story_session(
        self,
        account_id: str,
        session: IGSession,
        targets: list[str],
        story_view_cap: int,
        date_iso: Optional[str] = None,
        views_done_today: int = 0,
        reactions_sent_today: int = 0,
    ) -> WorkerResult:
        """
        View stories of target accounts and react to ~30%.

        Step 1 of the story-first growth flow. After this session, the
        follow-up session (run_followup_follow_session) runs 2-4 hours later.

        Implements:
        - Shuffle targets per-account (seeded by hash(account_id+date_iso))
        - Per-story dwell: LogNormal(mean=ln(5), sigma=0.4)
        - React to ~30% of stories immediately after viewing (seeded per account)
        - Record story_viewed_at timestamps for follow-up window check
        - Save session sidecar for follow-up session pick-up

        Args:
            account_id:           Internal account identifier.
            session:              Authenticated IGSession.
            targets:              List of target user IDs to view stories for.
            story_view_cap:       Max story views today (code-enforced).
            date_iso:             YYYY-MM-DD (defaults to today UTC).
            views_done_today:     Story views already done today.
            reactions_sent_today: Reactions already sent today.

        Returns:
            WorkerResult with data keys:
                stories_viewed, reactions_sent, no_story_skips, accounts_viewed, errors
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        task_id = f"{account_id}_morning_story_{date_iso}"

        # Load or create session sidecar
        session_state = _load_session(account_id, date_iso) or FollowStorySession(
            account_id=account_id,
            date_iso=date_iso,
        )

        # Shuffle targets per-account so fleet ordering is uncorrelated
        seed = _stable_hash(f"{account_id}|{date_iso}|story_view_order")
        shuffled_targets = _shuffle_with_seed(targets, seed)

        stories_viewed = 0
        accounts_viewed = 0
        no_story_skips = 0
        errors: list[str] = []
        story_view_records: list[StoryViewRecord] = []

        async with InstagramClient(session) as client:
            for idx, user_id in enumerate(shuffled_targets):
                # Code-enforced story view cap
                if views_done_today + stories_viewed >= story_view_cap:
                    log.info(
                        "[%s] Daily story view cap reached (%d), stopping",
                        account_id, story_view_cap,
                    )
                    break

                # Fetch story tray for this user
                try:
                    story_resp = await client._get(
                        f"feed/user/{user_id}/story/",
                        params={"supported_capabilities_new": "[]"},
                    )
                except IGSessionExpired:
                    log.warning("[%s] Session expired fetching story tray", account_id)
                    errors.append(f"session_expired:user={user_id}")
                    break
                except IGRateLimited:
                    log.warning("[%s] Rate limited fetching story tray", account_id)
                    errors.append(f"rate_limited:user={user_id}")
                    break
                except Exception as exc:
                    log.error("[%s] Error fetching stories for %s: %s", account_id, user_id, exc)
                    errors.append(f"fetch_error:user={user_id}:{exc}")
                    continue

                # Extract media items
                reel = story_resp.get("reel") or story_resp.get("user", {})
                media_items = (
                    reel.get("items", [])
                    if isinstance(reel, dict)
                    else story_resp.get("items", [])
                )

                if not media_items:
                    log.debug("[%s] No active stories for user %s — skipping", account_id, user_id)
                    no_story_skips += 1
                    session_state.no_story_skips += 1
                    continue

                media_ids = [
                    str(item.get("id", item.get("pk", "")))
                    for item in media_items
                    if item.get("id") or item.get("pk")
                ]
                if not media_ids:
                    no_story_skips += 1
                    session_state.no_story_skips += 1
                    continue

                # Clamp to remaining view cap
                remaining_cap = story_view_cap - (views_done_today + stories_viewed)
                allowed_ids = media_ids[:remaining_cap]

                # Per-story dwell before marking seen
                for media_id in allowed_ids:
                    dwell = _STORY_DWELL_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"story_dwell_{user_id}_{media_id}",
                    )
                    await asyncio.sleep(dwell)

                # Mark stories seen
                try:
                    await client.story_view(reel_id=user_id, media_ids=allowed_ids)
                    view_ts = time.time()
                    stories_viewed += len(allowed_ids)
                    accounts_viewed += 1

                    # Record for session state
                    if user_id not in session_state.targets_story_viewed:
                        session_state.targets_story_viewed.append(user_id)
                    session_state.story_viewed_at[user_id] = view_ts

                    # Collect for react agent
                    for media_id in allowed_ids:
                        story_view_records.append(StoryViewRecord(
                            reel_id=user_id,
                            media_id=media_id,
                            account_id=account_id,
                            target_user_id=user_id,
                        ))

                    log.info(
                        "[%s] Viewed %d stories for user %s",
                        account_id, len(allowed_ids), user_id,
                    )

                except IGSessionExpired:
                    log.warning("[%s] Session expired marking stories seen", account_id)
                    errors.append(f"session_expired_view:user={user_id}")
                    break
                except IGRateLimited:
                    log.warning("[%s] Rate limited marking stories seen", account_id)
                    errors.append(f"rate_limited_view:user={user_id}")
                    break
                except IGActionBlocked:
                    log.warning("[%s] Story view action blocked", account_id)
                    errors.append(f"action_blocked:user={user_id}")
                    break
                except Exception as exc:
                    log.error("[%s] Story view error for user %s: %s", account_id, user_id, exc)
                    errors.append(f"error:user={user_id}:{exc}")
                    continue

                # Inter-target sleep
                remaining_views = story_view_cap - (views_done_today + stories_viewed)
                if idx < len(shuffled_targets) - 1 and remaining_views > 0:
                    delay = _INTER_STORY_TARGET_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_story_target_{idx}",
                    )
                    await asyncio.sleep(delay)

        # Delegate reactions to IGStoryReactAgent after all story views
        reactions_sent = 0
        react_errors: list[str] = []
        if story_view_records:
            react_result = await self._react_agent.run_session(
                account_id=account_id,
                session=session,
                story_views_today=story_view_records,
                date_iso=date_iso,
                reactions_sent_today=reactions_sent_today,
            )
            reactions_sent = react_result.data.get("reactions_sent", 0)
            react_errors = react_result.data.get("errors", [])

        # Update reacted user_ids in session state
        # (approximate: if any story for a user was reacted to, count the user)
        # Full per-media-id tracking is in the react agent's dedup set.
        # For sidecar, track at user level via react_result data
        for record in story_view_records:
            if record.target_user_id not in session_state.targets_reacted:
                # Will be tracked by react agent per media_id — user-level here is approximate
                pass

        # Persist sidecar for follow-up session
        _save_session(session_state)

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":          "morning_story",
                "stories_viewed":  stories_viewed,
                "accounts_viewed": accounts_viewed,
                "reactions_sent":  reactions_sent,
                "no_story_skips":  no_story_skips,
                "errors":          errors + react_errors,
            },
        )

    # ------------------------------------------------------------------
    # Session 2 (Follow-up, 2-4hrs later): Follow accounts whose stories we viewed
    # ------------------------------------------------------------------

    async def run_followup_follow_session(
        self,
        account_id: str,
        session: IGSession,
        daily_follow_cap: int,
        date_iso: Optional[str] = None,
        recently_followed: Optional[dict[str, float]] = None,
        follows_sent_today: int = 0,
    ) -> WorkerResult:
        """
        Follow accounts whose stories we viewed 2-4 hours ago.

        Step 2 of the story-first growth flow. Loads the morning sidecar,
        selects targets whose stories were viewed 2-4 hours ago (still in
        the recognition window), and follows them.

        Time window enforcement is CODE-BASED: inspects story_viewed_at
        and computes elapsed seconds for each viewed account at call time.

        Qualifies accounts where:
            STORY_TO_FOLLOW_MIN_SECS (2hr) <= elapsed <= STORY_TO_FOLLOW_MAX_SECS (8hr)

        The follow-back notification lands as a "familiar face" because the
        target already saw us in their story viewers. Recognition effect is
        strongest at 2-4 hours, but still works up to 8 hours.

        Skips:
            - elapsed < 2hr: too soon, recognition benefit exists but follow may
              look correlated if viewed and followed within same minute
            - elapsed > 8hr: story likely viewed less recently than we think;
              NOTE: these are still followed (recognition still works even if
              the story expired — they saw us in viewers and may remember)

        Args:
            account_id:         Internal account identifier.
            session:            Authenticated IGSession.
            daily_follow_cap:   Max follows today (code-enforced).
            date_iso:           YYYY-MM-DD (defaults to today UTC).
            recently_followed:  Dict of user_id → timestamp for 30-day dedup.
            follows_sent_today: Follows already sent today.

        Returns:
            WorkerResult with data keys:
                followed, already_following, skipped_too_recent, errors
        """
        if date_iso is None:
            date_iso = date.today().isoformat()
        if recently_followed is None:
            recently_followed = {}

        task_id = f"{account_id}_followup_follow_{date_iso}"
        now = time.time()

        # Load morning sidecar
        session_state = _load_session(account_id, date_iso)
        if session_state is None:
            log.warning(
                "[%s] No morning story sidecar for %s — follow-up session skipped",
                account_id, date_iso,
            )
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=False,
                error="no_morning_sidecar",
                data={
                    "action":              "followup_follow",
                    "followed":            0,
                    "already_following":   0,
                    "skipped_too_recent":  0,
                    "errors":              ["no_morning_sidecar"],
                },
            )

        # Categorise targets: in-window, too-recent, too-old
        # Per the spec: too-recent = <2hr (skip, come back later)
        # Too-old (>8hr) = still follow them (recognition still works)
        in_window: list[str] = []
        too_old_but_follow: list[str] = []  # >8hr but we still follow
        skipped_too_recent = 0

        for user_id in session_state.targets_story_viewed:
            viewed_at = session_state.story_viewed_at.get(user_id, 0.0)
            elapsed = now - viewed_at
            if elapsed < STORY_TO_FOLLOW_MIN_SECS:
                skipped_too_recent += 1
                log.debug(
                    "[%s] Skip follow for %s: only %.0f min since story view (min 120 min)",
                    account_id, user_id, elapsed / 60,
                )
            elif elapsed > STORY_TO_FOLLOW_MAX_SECS:
                # Still follow — recognition still works even if story expired
                too_old_but_follow.append(user_id)
                log.debug(
                    "[%s] Follow %s (viewed %.0f min ago, story may be expired but still follow)",
                    account_id, user_id, elapsed / 60,
                )
            else:
                in_window.append(user_id)

        # Combine: in-window first, then too-old-but-follow
        all_to_follow = in_window + too_old_but_follow

        # Shuffle with per-account seed to prevent fleet-wide ordering fingerprints
        seed = _stable_hash(f"{account_id}|{date_iso}|follow_order")
        all_to_follow = _shuffle_with_seed(all_to_follow, seed)

        followed = 0
        already_following = 0
        errors: list[str] = []

        async with InstagramClient(session) as client:
            for idx, user_id in enumerate(all_to_follow):
                # Code-enforced daily follow cap
                if follows_sent_today + followed >= daily_follow_cap:
                    log.info(
                        "[%s] Daily follow cap reached (%d), stopping",
                        account_id, daily_follow_cap,
                    )
                    break

                # 30-day re-follow dedup
                last_followed_at = recently_followed.get(user_id, 0.0)
                if now - last_followed_at < REFOLLOW_COOLDOWN_SECS:
                    already_following += 1
                    continue

                # Skip if already followed in this session
                if user_id in session_state.targets_followed:
                    already_following += 1
                    continue

                # Execute follow
                try:
                    await client.follow(user_id)
                    session_state.targets_followed.append(user_id)
                    followed += 1
                    log.info("[%s] Followed user %s (after story view)", account_id, user_id)

                except IGSessionExpired:
                    log.warning("[%s] Session expired during follow", account_id)
                    errors.append(f"session_expired:user={user_id}")
                    break
                except IGRateLimited:
                    log.warning("[%s] Rate limited during follow", account_id)
                    errors.append(f"rate_limited:user={user_id}")
                    break
                except IGActionBlocked:
                    log.warning("[%s] Follow action blocked", account_id)
                    errors.append(f"action_blocked:user={user_id}")
                    break
                except Exception as exc:
                    log.error("[%s] Follow error for user %s: %s", account_id, user_id, exc)
                    errors.append(f"error:user={user_id}:{exc}")
                    continue

                # Inter-follow sleep
                remaining = daily_follow_cap - (follows_sent_today + followed)
                if idx < len(all_to_follow) - 1 and remaining > 0:
                    delay = _INTER_FOLLOW_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_follow_{idx}",
                    )
                    await asyncio.sleep(delay)

        # Persist updated sidecar
        _save_session(session_state)

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":             "followup_follow",
                "followed":           followed,
                "already_following":  already_following,
                "skipped_too_recent": skipped_too_recent,
                "errors":             errors,
            },
        )

    # ------------------------------------------------------------------
    # Follow-back check
    # ------------------------------------------------------------------

    async def check_follow_backs(
        self,
        account_id: str,
        session: IGSession,
        date_iso: Optional[str] = None,
    ) -> WorkerResult:
        """
        Check which of today's followed accounts have followed back.

        Used to measure conversion rate for A/B testing.  Fetches the
        account's own follower list and checks membership for each
        target followed today.

        Returns:
            WorkerResult with data keys:
                follow_back_count, follow_back_user_ids, checked_count
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        task_id = f"{account_id}_follow_back_check_{date_iso}"

        session_state = _load_session(account_id, date_iso)
        if session_state is None or not session_state.targets_followed:
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=True,
                data={
                    "action":               "follow_back_check",
                    "follow_back_count":    0,
                    "follow_back_user_ids": [],
                    "checked_count":        0,
                },
            )

        targets_set = set(session_state.targets_followed)
        follow_back_ids: list[str] = []
        errors: list[str] = []

        async with InstagramClient(session) as client:
            try:
                our_ig_user_id = session.ig_user_id
                resp = await client.get_user_followers(our_ig_user_id, count=200)
                follower_ids = {str(u.get("pk", u.get("id", ""))) for u in resp.get("users", [])}
                follow_back_ids = [uid for uid in targets_set if uid in follower_ids]
            except Exception as exc:
                errors.append(f"check_error:{exc}")

        # Update sidecar
        if session_state is not None:
            session_state.follow_back_count = len(follow_back_ids)
            _save_session(session_state)

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":               "follow_back_check",
                "follow_back_count":    len(follow_back_ids),
                "follow_back_user_ids": follow_back_ids,
                "checked_count":        len(session_state.targets_followed if session_state else []),
                "errors":               errors,
            },
        )
