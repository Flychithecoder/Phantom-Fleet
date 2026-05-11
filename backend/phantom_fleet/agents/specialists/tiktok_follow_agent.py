"""
TikTokFollowAgent — executes follow/unfollow campaigns on TikTok.

Specialist agent dispatched by TikTokAgentManager. Runs in the foreground
slot of the assigned phone after the Companion APK has verified proxy
connectivity.

Campaign flow per invocation:
    1. Receive a list of target_usernames from ctx
    2. For each target:
        a. view_profile (dwell sampled from LogNormal)
        b. follow_user
        c. inter-action sleep (LogNormal)
    3. Stop when daily follow budget from DailyPlan is exhausted
    4. Write one audit entry per follow (before + result)

Detection hardening:
    - Profile view precedes every follow — matches real user behaviour
    - Dwell on profile is LogNormal(low=3, high=15) — not a fixed value
    - Inter-follow sleep is LogNormal(mean=12s, sigma=4s, lo=5, hi=45)
    - Daily budget is sampled from warming curve, not a hardcoded constant
    - Target list is shuffled per (account_id, date) before processing
      so two accounts never follow the same sequence
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import random
from datetime import date, timezone, datetime
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import LogNormal, seed_for
from ...core.tiktok_controller import TikTokController, TikTokSession
from ...core.warming_curve import DailyPlan

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing distributions (module-level constants — sampled per call, not per fleet)
# ---------------------------------------------------------------------------

_PROFILE_DWELL_SEC  = LogNormal(low=3.0,  high=15.0, sigma=0.30)
_INTER_FOLLOW_SEC   = LogNormal(low=5.0,  high=45.0, sigma=0.40)


class TikTokFollowAgent(Agent):
    """
    Specialist agent that runs a TikTok follow campaign for one account.

    Context keys (ctx):
        account_id        (str)          — Phantom Fleet account ID
        username          (str)          — TikTok @username (without @)
        phone_serial      (str)          — ADB serial of the phone
        clone_package     (str)          — installed clone package name
        target_usernames  (list[str])    — ordered list of targets to follow
        daily_plan        (DailyPlan)    — plan produced by plan_daily_actions()
        date_iso          (str)          — YYYY-MM-DD (account's local date)
        unfollow_mode     (bool)         — if True, unfollow instead of follow

    Output keys (run.outputs):
        followed          (list[str])    — usernames successfully followed
        skipped           (list[str])    — targets skipped (budget exhausted / error)
        follow_count      (int)
        error_count       (int)
    """

    config = AgentConfig(
        name="tiktok_follow",
        max_iterations=1,   # one run = one campaign pass; manager re-invokes as needed
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),   # no LLM tools — pure accessibility actions
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:      str       = ctx["account_id"]
        username:        str       = ctx["username"]
        phone_serial:    str       = ctx["phone_serial"]
        clone_package:   str       = ctx["clone_package"]
        targets:         list[str] = ctx["target_usernames"]
        daily_plan:      DailyPlan = ctx["daily_plan"]
        date_iso:        str       = ctx.get("date_iso", date.today().isoformat())
        unfollow_mode:   bool      = ctx.get("unfollow_mode", False)

        action_label = "unfollow" if unfollow_mode else "follow"

        # Budget from DailyPlan
        budget: int = daily_plan.follows if not unfollow_mode else ctx.get("unfollow_budget", 0)

        # Shuffle targets deterministically per (account_id, date_iso) so
        # two accounts never process the same sequence — prevents network
        # graph regularities at fleet scale.
        seed = seed_for(account_id, date_iso, "follow_target_order")
        rng  = random.Random(seed)
        shuffled = list(targets)
        rng.shuffle(shuffled)

        session = TikTokSession(
            account_id=account_id,
            username=username,
            phone_serial=phone_serial,
            clone_package=clone_package,
        )

        followed: list[str] = []
        skipped:  list[str] = []
        error_count = 0

        async with TikTokController(session) as ctrl:
            for target in shuffled:
                if len(followed) >= budget:
                    skipped.extend(shuffled[len(followed) + len(skipped):])
                    break

                # Pre-sample dwell so the distribution shape is correct
                dwell = _PROFILE_DWELL_SEC.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"profile_dwell_{target}",
                )

                # Audit BEFORE executing (CLAUDE.md agent rule #23)
                self._audit({
                    "event": f"tiktok_{action_label}_attempt",
                    "account_id": account_id,
                    "target": target,
                    "dwell_sec": round(dwell, 2),
                    "budget_remaining": budget - len(followed),
                })

                # Step 1: view profile with human dwell
                view_result = await ctrl.view_profile(target, dwell_sec=dwell)
                if not view_result.success:
                    log.warning(
                        "view_profile failed for %s → %s: %s",
                        account_id, target, view_result.error,
                    )
                    skipped.append(target)
                    error_count += 1
                    # Brief pause even on failure — don't hammer on errors
                    await _lognormal_sleep(mean=6.0, sigma=0.5, lo=3.0, hi=15.0)
                    continue

                # Step 2: follow or unfollow
                if unfollow_mode:
                    action_result = await ctrl.unfollow_user(target)
                else:
                    action_result = await ctrl.follow_user(target)

                if action_result.success:
                    followed.append(target)
                    self._audit({
                        "event": f"tiktok_{action_label}_success",
                        "account_id": account_id,
                        "target": target,
                    })
                else:
                    log.warning(
                        "%s failed for %s → %s: %s",
                        action_label, account_id, target, action_result.error,
                    )
                    skipped.append(target)
                    error_count += 1

                # Inter-action sleep — LogNormal, not uniform
                inter_sleep = _INTER_FOLLOW_SEC.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"inter_follow_{len(followed)}",
                )
                await asyncio.sleep(inter_sleep)

        run.outputs.update({
            "followed":     followed,
            "skipped":      skipped,
            "follow_count": len(followed),
            "error_count":  error_count,
        })

        self._audit({
            "event": f"tiktok_{action_label}_session_complete",
            "account_id": account_id,
            "followed": len(followed),
            "skipped":  len(skipped),
            "errors":   error_count,
        })

        return True  # always done after one pass; manager re-invokes for next session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _lognormal_sleep(mean: float, sigma: float, lo: float, hi: float) -> None:
    """LogNormal sleep — shared by agents in this module."""
    mu_ln = math.log(mean) - 0.5 * sigma ** 2
    raw = random.lognormvariate(mu_ln, sigma)
    await asyncio.sleep(max(lo, min(hi, raw)))
