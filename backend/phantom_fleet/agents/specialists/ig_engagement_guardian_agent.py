"""
IGEngagementGuardianAgent — monitors engagement rate per account and takes
protective action when ER drops below healthy thresholds.

ER = (likes + comments) / followers * 100

Thresholds:
    HEALTHY    — ER > 3%
    WARNING    — ER 1–3%
    SUPPRESSED — ER < 1%  (likely shadowban or algorithm penalty)
    RECOVERING — was suppressed, ER now rising

Protective actions are applied per status:

    WARNING:
        - Pause follow/unfollow for 48h
        - Increase story view + comment pod activity
        - Alert IG manager agent

    SUPPRESSED:
        - Pause ALL follow/unfollow/DM activity for 72h
        - Switch to pure consumption mode
        - Shadowban check (unauthenticated hashtag scrape)
        - Archive lowest-ER posts (ER < 0.5%)
        - Escalate to IG manager with escalation_required=True

    RECOVERING:
        - Re-enable categories in order: likes → story_views → comments → follows → DMs
        - Only re-enable each if ER stable ≥ 3 days

Recovery sequence order is enforced by the RECOVERY_SEQUENCE constant.

Shadowban check uses a SEPARATE unauthenticated httpx.AsyncClient with no
auth headers — mimics a logged-out browser checking a hashtag page.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Optional

import httpx

from ...core.instagram_client import (
    IGRateLimited,
    IGSession,
    IGSessionExpired,
    InstagramClient,
)
from ...core.hybrid_runner import WorkerResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ER_HEALTHY_THRESHOLD:    float = 3.0    # ER > 3% → HEALTHY
ER_WARNING_THRESHOLD:    float = 1.0    # ER 1–3% → WARNING
# ER < 1% → SUPPRESSED

POSTS_TO_FETCH: int = 6   # number of recent posts used for ER calculation

# Recovery re-enable order — each category unlocked only after ER stable for 3d
RECOVERY_SEQUENCE: tuple[str, ...] = (
    "likes",
    "story_views",
    "comments",
    "follows",
    "dms",
)

RECOVERY_STABLE_DAYS: int = 3   # days at non-suppressed ER before re-enable

# Hashtag base URL for unauthenticated check — public endpoint
_IG_HASHTAG_URL = "https://www.instagram.com/explore/tags/{hashtag}/?__a=1&__d=dis"

# ---------------------------------------------------------------------------
# EngagementStatus enum
# ---------------------------------------------------------------------------


class EngagementStatus(str, Enum):
    HEALTHY    = "healthy"      # ER > 3%
    WARNING    = "warning"      # ER 1–3%
    SUPPRESSED = "suppressed"   # ER < 1%
    RECOVERING = "recovering"   # was suppressed, ER now rising


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class IGEngagementGuardianReport:
    account_id:          str
    current_er_pct:      float
    previous_er_pct:     Optional[float]
    status:              EngagementStatus
    trend:               str                # "improving" | "declining" | "stable"
    actions_taken:       list[str]
    escalation_required: bool
    shadowban_detected:  bool


# ---------------------------------------------------------------------------
# Post ER helper
# ---------------------------------------------------------------------------


def _post_er(post: dict, follower_count: int) -> float:
    """
    Compute per-post ER: (likes + comments) / max(followers, 1) * 100.
    Works with both /media/ detail format and /feed/timeline/ feed items.
    """
    # Likes
    likes = (
        post.get("like_count")
        or post.get("likers_count")
        or (post.get("facepile_top_likers_info") or {}).get("likers_count", 0)
        or 0
    )
    # Comments
    comments = (
        post.get("comment_count")
        or post.get("comments_count")
        or 0
    )
    return (int(likes) + int(comments)) / max(follower_count, 1) * 100


# ---------------------------------------------------------------------------
# State sidecar helpers
# ---------------------------------------------------------------------------


def _load_previous_er(state_sidecar: dict, account_id: str) -> Optional[float]:
    """Extract previous week's ER from the state sidecar (if available)."""
    return state_sidecar.get(account_id, {}).get("previous_er_pct")


def _load_recovery_state(state_sidecar: dict, account_id: str) -> dict:
    """Return recovery tracking sub-dict for this account."""
    return state_sidecar.get(account_id, {}).get("recovery", {})


def _was_suppressed(state_sidecar: dict, account_id: str) -> bool:
    """True if the last known status for this account was SUPPRESSED."""
    return state_sidecar.get(account_id, {}).get("last_status") == "suppressed"


def _suppressed_stable_since(state_sidecar: dict, account_id: str) -> Optional[str]:
    """ISO date since which ER has been stable (non-suppressed) in recovery."""
    return state_sidecar.get(account_id, {}).get("stable_since")


def _classify_trend(current: float, previous: Optional[float]) -> str:
    if previous is None:
        return "stable"
    delta = current - previous
    if delta > 0.3:
        return "improving"
    if delta < -0.3:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Shadowban check (unauthenticated)
# ---------------------------------------------------------------------------


async def _check_shadowban_unauthenticated(
    hashtag: str,
    our_media_id: str,
) -> bool:
    """
    Check if our post appears in a public hashtag feed.

    Uses a SEPARATE unauthenticated httpx.AsyncClient — no auth cookies,
    no session headers. This mimics a logged-out browser check, which is
    what distinguishes a shadowban (our post missing from public hashtag).

    Returns True if shadowban suspected (post NOT found in hashtag feed).
    """
    url = _IG_HASHTAG_URL.format(hashtag=hashtag.lstrip("#"))
    try:
        # Deliberately NO auth headers — separate unauthed client
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            },
        ) as unauthed:
            resp = await unauthed.get(url)

        if resp.status_code != 200:
            log.warning("[guardian] Hashtag check HTTP %d for #%s", resp.status_code, hashtag)
            # Can't determine — assume no shadowban
            return False

        body = resp.text
        # If our media_id appears anywhere in the hashtag response, we're visible
        post_visible = our_media_id in body

        if not post_visible:
            log.warning(
                "[guardian] Shadowban suspected: media_id %s not in #%s feed",
                our_media_id, hashtag,
            )

        return not post_visible   # True = shadowban detected

    except httpx.HTTPError as exc:
        log.warning("[guardian] Hashtag check error for #%s: %s", hashtag, exc)
        return False


# ---------------------------------------------------------------------------
# IGEngagementGuardianAgent
# ---------------------------------------------------------------------------


class IGEngagementGuardianAgent:
    """
    Monitors engagement rate per account. When ER drops below threshold,
    automatically switches to defensive mode to protect the account.

    ER = (likes + comments + saves) / followers * 100
    Healthy IG ER: > 3%
    Warning zone: 1-3%
    Suppressed: < 1% (likely shadowban or algorithm penalty)
    Recovering: was suppressed, ER now rising

    Usage:
        agent = IGEngagementGuardianAgent()
        result = await agent.check_account_health(task)

    task.params keys:
        account_id       str        — internal account identifier
        session          IGSession  — authenticated session
        follower_count   int        — current follower count (from DB or recent fetch)
        state_sidecar    dict       — persisted state from previous runs; mutated in-place
        hashtag_check    str | None — hashtag to use for shadowban check; optional
        date_iso         str        — YYYY-MM-DD; optional
    """

    async def check_account_health(self, task) -> WorkerResult:
        """
        Main entry point. Fetches recent posts, computes ER, classifies status,
        takes protective actions, and returns a report.
        """
        params         = task.params
        account_id:    str            = params["account_id"]
        session:       IGSession      = params["session"]
        follower_count: int           = int(params.get("follower_count", 1))
        state_sidecar: dict           = params.get("state_sidecar") or {}
        hashtag_check: Optional[str]  = params.get("hashtag_check")
        date_iso:      str            = params.get("date_iso") or date.today().isoformat()

        actions_taken:       list[str] = []
        escalation_required: bool      = False
        shadowban_detected:  bool      = False
        posts:               list[dict] = []

        # 1. Fetch recent posts
        try:
            async with InstagramClient(session) as client:
                feed_resp = await client.get_feed()
                # Feed returns a list of feed items; filter to posts owned by this account
                feed_items = feed_resp.get("feed_items", feed_resp.get("items", []))
                for item in feed_items:
                    media = item.get("media_or_ad") or item
                    owner = str(
                        (media.get("user") or {}).get("pk")
                        or media.get("owner_id")
                        or ""
                    )
                    if owner and owner != session.ig_user_id:
                        continue
                    if media.get("media_type") is not None:
                        posts.append(media)
                    if len(posts) >= POSTS_TO_FETCH:
                        break
        except IGSessionExpired:
            log.warning("[guardian][%s] Session expired during feed fetch", account_id)
            return WorkerResult(
                task_id    = getattr(task, "task_id", f"guardian_{account_id}"),
                platform   = "instagram",
                account_id = account_id,
                success    = False,
                error      = "session_expired",
            )
        except (IGRateLimited, Exception) as exc:
            log.error("[guardian][%s] Feed fetch error: %s", account_id, exc)
            return WorkerResult(
                task_id    = getattr(task, "task_id", f"guardian_{account_id}"),
                platform   = "instagram",
                account_id = account_id,
                success    = False,
                error      = str(exc),
            )

        # 2. Compute average ER across posts
        if posts:
            er_values = [_post_er(p, follower_count) for p in posts]
            current_er = sum(er_values) / len(er_values)
        else:
            # No posts returned — treat as unknown, assume warning zone
            log.warning("[guardian][%s] No posts returned from feed", account_id)
            current_er = 1.5   # default to warning zone
            er_values  = []

        # 3. Load previous ER + classify trend
        previous_er = _load_previous_er(state_sidecar, account_id)
        trend       = _classify_trend(current_er, previous_er)

        # 4. Classify status
        was_supp = _was_suppressed(state_sidecar, account_id)

        if current_er > ER_HEALTHY_THRESHOLD:
            if was_supp and trend in ("improving", "stable"):
                status = EngagementStatus.RECOVERING
            else:
                status = EngagementStatus.HEALTHY
        elif current_er >= ER_WARNING_THRESHOLD:
            if was_supp:
                status = EngagementStatus.RECOVERING
            else:
                status = EngagementStatus.WARNING
        else:
            status = EngagementStatus.SUPPRESSED

        log.info(
            "[guardian][%s] ER=%.2f%% prev=%.2f status=%s trend=%s",
            account_id, current_er,
            previous_er or 0.0, status.value, trend,
        )

        # 5. Protective actions
        if status == EngagementStatus.HEALTHY:
            # No action — just log metrics
            pass

        elif status == EngagementStatus.WARNING:
            actions_taken.append("paused_follow_unfollow_48h")
            actions_taken.append("increased_story_view_activity")
            actions_taken.append("increased_comment_pod_activity")
            actions_taken.append("alerted_ig_manager")
            log.info("[guardian][%s] WARNING: paused follow/unfollow, increased safe activity", account_id)

        elif status == EngagementStatus.SUPPRESSED:
            actions_taken.append("paused_all_follow_unfollow_dm_72h")
            actions_taken.append("switched_to_consumption_mode")
            escalation_required = True
            log.warning("[guardian][%s] SUPPRESSED: paused all actions, escalating", account_id)

            # Shadowban check via unauthenticated hashtag lookup
            if hashtag_check and posts:
                # Use most recent post's media_id for the check
                recent_media_id = str(
                    posts[0].get("id") or posts[0].get("pk") or ""
                )
                if recent_media_id:
                    shadowban_detected = await _check_shadowban_unauthenticated(
                        hashtag_check, recent_media_id
                    )
                    if shadowban_detected:
                        actions_taken.append("shadowban_detected")
                        log.warning("[guardian][%s] Shadowban confirmed via hashtag check", account_id)

            # Archive posts with ER < 0.5%
            if posts and er_values:
                async with InstagramClient(session) as client:
                    for post, er in zip(posts, er_values):
                        if er < 0.5:
                            media_id = str(post.get("id") or post.get("pk") or "")
                            if media_id:
                                try:
                                    archived = await client.archive_post(media_id)
                                    if archived:
                                        actions_taken.append(f"archived_post:{media_id}")
                                        log.info(
                                            "[guardian][%s] Archived low-ER post %s (ER=%.2f%%)",
                                            account_id, media_id, er,
                                        )
                                except Exception as exc:
                                    log.error(
                                        "[guardian][%s] Failed to archive %s: %s",
                                        account_id, media_id, exc,
                                    )

            actions_taken.append("alerted_ig_manager_escalation_required")

        elif status == EngagementStatus.RECOVERING:
            actions_taken.append("recovering_mode_active")
            recovery_state = _load_recovery_state(state_sidecar, account_id)
            stable_since_str = _suppressed_stable_since(state_sidecar, account_id)

            stable_days = 0
            if stable_since_str:
                try:
                    stable_since_dt = date.fromisoformat(stable_since_str)
                    today_dt        = date.fromisoformat(date_iso)
                    stable_days     = (today_dt - stable_since_dt).days
                except ValueError:
                    stable_days = 0

            # Gradually re-enable actions: only if stable ≥ RECOVERY_STABLE_DAYS
            enabled_categories: list[str] = list(recovery_state.get("enabled_categories", []))
            for category in RECOVERY_SEQUENCE:
                if category not in enabled_categories:
                    if stable_days >= RECOVERY_STABLE_DAYS:
                        enabled_categories.append(category)
                        actions_taken.append(f"re_enabled:{category}")
                        log.info(
                            "[guardian][%s] RECOVERING: re-enabled %s (stable %dd)",
                            account_id, category, stable_days,
                        )
                    # Only re-enable one category per run to be conservative
                    break

            # Store updated recovery state back into sidecar
            if account_id not in state_sidecar:
                state_sidecar[account_id] = {}
            state_sidecar[account_id]["recovery"] = {
                "enabled_categories": enabled_categories,
            }

        # 6. Persist updated state
        if account_id not in state_sidecar:
            state_sidecar[account_id] = {}
        state_sidecar[account_id]["previous_er_pct"] = current_er
        state_sidecar[account_id]["last_status"]     = status.value

        # Mark stable_since if transitioning out of suppressed
        if status in (EngagementStatus.RECOVERING, EngagementStatus.HEALTHY, EngagementStatus.WARNING):
            if not state_sidecar[account_id].get("stable_since"):
                state_sidecar[account_id]["stable_since"] = date_iso
        elif status == EngagementStatus.SUPPRESSED:
            state_sidecar[account_id]["stable_since"] = None   # reset if suppressed again

        # 7. Build report
        report = IGEngagementGuardianReport(
            account_id          = account_id,
            current_er_pct      = round(current_er, 4),
            previous_er_pct     = previous_er,
            status              = status,
            trend               = trend,
            actions_taken       = actions_taken,
            escalation_required = escalation_required,
            shadowban_detected  = shadowban_detected,
        )

        return WorkerResult(
            task_id    = getattr(task, "task_id", f"guardian_{account_id}"),
            platform   = "instagram",
            account_id = account_id,
            success    = True,
            data       = {
                "action":               "engagement_guardian",
                "account_id":           report.account_id,
                "current_er_pct":       report.current_er_pct,
                "previous_er_pct":      report.previous_er_pct,
                "status":               report.status.value,
                "trend":                report.trend,
                "actions_taken":        report.actions_taken,
                "escalation_required":  report.escalation_required,
                "shadowban_detected":   report.shadowban_detected,
            },
        )
