"""
TikTokScrollAgent — organic TikTok feed simulation.

Keeps accounts algorithmically active by simulating real browsing sessions:
    - Scrolls the For You Page for a sampled number of minutes
    - Likes videos at a rate sampled from LogNormal (not a fixed ratio)
    - Dwells on each video for a duration sampled from LogNormal(mean=12s, sigma=5s)
    - Occasionally visits the creator's profile (probability 0.15)
    - Never scrolls past a video in < 3 seconds (hard floor)

All sampling happens per (account_id, date_iso, video_index) so:
    - The same account on the same date always gets the same session plan
      (deterministic replay for debugging)
    - Two different accounts on the same date get different plans
      (prevents fleet-wide uniform behaviour)

This is the warmth-maintenance agent. It runs for EVERY account every day
regardless of phase (dormant, warming, steady), though the like_rate and
session_minutes budget differ per phase.

Context keys (ctx):
    account_id        (str)   — Phantom Fleet account ID
    username          (str)   — TikTok @username
    phone_serial      (str)   — ADB serial
    clone_package     (str)   — installed clone package name
    date_iso          (str)   — YYYY-MM-DD (account's local date)
    session_minutes   (float) — total session length budget (pre-sampled by manager)
    like_rate         (float) — probability of liking each video (0.0–1.0, pre-sampled)
    min_dwell_sec     (float) — minimum dwell per video (default 3.0)
    creator_visit_prob (float)— probability of visiting creator profile (default 0.15)

Output keys (run.outputs):
    videos_scrolled   (int)
    videos_liked      (int)
    profiles_visited  (int)
    session_sec       (float)
    error_count       (int)
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import date

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import LogNormal, seed_for
from ...core.tiktok_controller import TikTokController, TikTokSession

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# Session length: LogNormal mean=8min sigma=3min, clipped 3-25min
# (converted to seconds for swipe count calculation)
_SESSION_MIN   = LogNormal(low=3.0,  high=25.0, sigma=0.35)

# Video watch duration per swipe
_VIDEO_DWELL_SEC = LogNormal(low=3.0, high=45.0, sigma=0.50)

# Like pause before double-tap (after deciding to like)
_LIKE_PAUSE_MS = LogNormal(low=800.0, high=2500.0, sigma=0.25)

# Profile dwell when visiting creator
_PROFILE_DWELL_SEC = LogNormal(low=3.0, high=15.0, sigma=0.30)

# Inter-swipe micro-pause (time to lift finger and re-position)
_SWIPE_GAP_MS = LogNormal(low=120.0, high=600.0, sigma=0.20)

# Like rate: LogNormal across 0.08–0.25 range
_LIKE_RATE = LogNormal(low=0.08, high=0.25, sigma=0.20)


class TikTokScrollAgent(Agent):
    """
    Simulates organic TikTok feed scrolling for one account.

    Designed to run in the foreground slot after TikTokController is active.
    The agent plans the full session upfront (how many videos, which to like,
    which creator to visit) using deterministic seeds, then executes the plan
    sequentially via TikTokController.
    """

    config = AgentConfig(
        name="tiktok_scroll",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:        str   = ctx["account_id"]
        username:          str   = ctx["username"]
        phone_serial:      str   = ctx["phone_serial"]
        clone_package:     str   = ctx["clone_package"]
        date_iso:          str   = ctx.get("date_iso", date.today().isoformat())
        session_minutes:   float = ctx.get("session_minutes", 0.0)
        like_rate:         float = ctx.get("like_rate", 0.0)
        min_dwell_sec:     float = ctx.get("min_dwell_sec", 3.0)
        creator_visit_prob: float = ctx.get("creator_visit_prob", 0.15)

        # If manager did not pre-sample session_minutes, sample it here.
        # This path is used only in standalone / test invocations.
        if session_minutes <= 0:
            session_minutes = _SESSION_MIN.sample(
                account_id=account_id,
                date_iso=date_iso,
                field="session_minutes",
            )

        # If manager did not pre-sample like_rate, sample it here.
        if like_rate <= 0:
            like_rate = _LIKE_RATE.sample(
                account_id=account_id,
                date_iso=date_iso,
                field="like_rate",
            )

        session_sec = session_minutes * 60.0

        # ---------------------------------------------------------------
        # Plan the session upfront for determinism and auditability
        # ---------------------------------------------------------------
        plan = _plan_session(
            account_id=account_id,
            date_iso=date_iso,
            session_sec=session_sec,
            like_rate=like_rate,
            min_dwell_sec=min_dwell_sec,
            creator_visit_prob=creator_visit_prob,
        )

        self._audit({
            "event": "tiktok_scroll_session_planned",
            "account_id": account_id,
            "session_sec": round(session_sec, 1),
            "video_count": len(plan),
            "planned_likes": sum(1 for p in plan if p["like"]),
            "planned_profile_visits": sum(1 for p in plan if p["visit_creator"]),
        })

        session = TikTokSession(
            account_id=account_id,
            username=username,
            phone_serial=phone_serial,
            clone_package=clone_package,
        )

        videos_scrolled  = 0
        videos_liked     = 0
        profiles_visited = 0
        elapsed_sec      = 0.0
        error_count      = 0

        async with TikTokController(session) as ctrl:
            for i, step in enumerate(plan):
                dwell_sec   = step["dwell_sec"]
                should_like = step["like"]
                visit_creator = step["visit_creator"]
                swipe_gap_ms  = step["swipe_gap_ms"]

                # Scroll one video (single swipe)
                scroll_result = await ctrl.scroll_feed(
                    duration_sec=dwell_sec,
                    swipe_count=1,
                )

                if not scroll_result.success:
                    log.warning(
                        "scroll_feed failed for %s at video %d: %s",
                        account_id, i, scroll_result.error,
                    )
                    error_count += 1
                    # Don't abort the session on a scroll error — TikTok feed
                    # occasionally misfires an accessibility event
                    await asyncio.sleep(2.0)
                    continue

                videos_scrolled += 1
                elapsed_sec += dwell_sec

                # Probabilistic like
                if should_like:
                    like_pause_ms = step["like_pause_ms"]
                    like_result = await ctrl.like_video(
                        pause_ms_range=(800, 2500),
                        pause_ms=int(like_pause_ms),
                    )
                    if like_result.success:
                        videos_liked += 1
                        self._audit({
                            "event": "tiktok_scroll_liked",
                            "account_id": account_id,
                            "video_index": i,
                        })
                    else:
                        log.debug(
                            "like_video failed at index %d for %s: %s",
                            i, account_id, like_result.error,
                        )

                # Occasional creator profile visit
                if visit_creator:
                    # The scroll agent doesn't know the creator's username —
                    # the APK resolves it from the visible UI element.
                    # We pass a sentinel so the APK knows to tap the creator link.
                    profile_dwell = step.get("profile_dwell_sec", 5.0)
                    visit_result = await ctrl.view_profile(
                        username="__current_creator__",   # APK resolves from UI
                        dwell_sec=profile_dwell,
                    )
                    if visit_result.success:
                        profiles_visited += 1
                        self._audit({
                            "event": "tiktok_scroll_creator_visit",
                            "account_id": account_id,
                            "video_index": i,
                            "dwell_sec": round(profile_dwell, 1),
                        })

                # Inter-swipe gap
                await asyncio.sleep(swipe_gap_ms / 1000.0)

                # Check budget
                if elapsed_sec >= session_sec:
                    break

        run.outputs.update({
            "videos_scrolled":   videos_scrolled,
            "videos_liked":      videos_liked,
            "profiles_visited":  profiles_visited,
            "session_sec":       round(elapsed_sec, 1),
            "error_count":       error_count,
        })

        self._audit({
            "event": "tiktok_scroll_session_complete",
            "account_id": account_id,
            "videos_scrolled":  videos_scrolled,
            "videos_liked":     videos_liked,
            "profiles_visited": profiles_visited,
            "session_sec":      round(elapsed_sec, 1),
        })

        return True


# ---------------------------------------------------------------------------
# Session planner
# ---------------------------------------------------------------------------

def _plan_session(
    account_id: str,
    date_iso: str,
    session_sec: float,
    like_rate: float,
    min_dwell_sec: float,
    creator_visit_prob: float,
) -> list[dict]:
    """
    Plan all video interactions for a scroll session upfront.

    Returns a list of dicts, one per video, with pre-sampled values for:
        dwell_sec, like, like_pause_ms, visit_creator, profile_dwell_sec,
        swipe_gap_ms

    All values are seeded per (account_id, date_iso, video_index) so
    the plan is deterministic for replay and unique per account/day.
    """
    plan = []
    elapsed = 0.0
    video_index = 0

    while elapsed < session_sec:
        seed_base = f"{account_id}|{date_iso}|video_{video_index}"
        rng = random.Random(_hash_seed(seed_base))

        dwell_sec = _lognormal_sample(rng, mean=12.0, sigma=5.0, lo=min_dwell_sec, hi=45.0)
        elapsed += dwell_sec

        like_roll = rng.random()
        should_like = like_roll < like_rate

        like_pause_ms = 0.0
        if should_like:
            like_pause_ms = _lognormal_sample(rng, mean=1300.0, sigma=400.0, lo=800.0, hi=2500.0)

        visit_roll = rng.random()
        visit_creator = visit_roll < creator_visit_prob

        profile_dwell_sec = 0.0
        if visit_creator:
            profile_dwell_sec = _lognormal_sample(rng, mean=7.0, sigma=2.5, lo=3.0, hi=15.0)
            elapsed += profile_dwell_sec

        swipe_gap_ms = _lognormal_sample(rng, mean=280.0, sigma=100.0, lo=120.0, hi=600.0)
        elapsed += swipe_gap_ms / 1000.0

        plan.append({
            "dwell_sec":        round(dwell_sec, 2),
            "like":             should_like,
            "like_pause_ms":    round(like_pause_ms, 0),
            "visit_creator":    visit_creator,
            "profile_dwell_sec": round(profile_dwell_sec, 2),
            "swipe_gap_ms":     round(swipe_gap_ms, 1),
        })

        video_index += 1

        # Safety cap — never plan more than 500 videos per session
        if video_index >= 500:
            break

    return plan


def _lognormal_sample(rng: random.Random, mean: float, sigma: float, lo: float, hi: float) -> float:
    """Sample from LogNormal using an existing Random instance."""
    mu_ln = math.log(mean) - 0.5 * (sigma / mean) ** 2
    sigma_ln = sigma / mean
    raw = rng.lognormvariate(mu_ln, max(0.01, sigma_ln))
    return max(lo, min(hi, raw))


def _hash_seed(s: str) -> int:
    import hashlib
    digest = hashlib.sha256(s.encode()).digest()
    return int.from_bytes(digest[:8], "big")
