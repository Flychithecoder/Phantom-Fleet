"""
WarmingAgent — runs the conservative re-wake / warmup curve for every account.

Responsibilities:
    - Every morning (per account's claimed timezone), produce the DailyPlan
      for every assigned account using core.warming_curve.plan_daily_actions
    - Distribute actions across the day with the persona's biometrics
    - Respect intra-day pacing rules (min gaps, min session length)
    - Honor the conservative 28-day curve + the 7-day re-wake curve
    - Pause accounts on block signals
    - Never exceed the daily range for a given curve day
    - No rest days ever — every account active every day via daily intensity sample
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

from .base import Agent, AgentConfig, AgentRun
from ..core.warming_curve import (
    RE_WAKE_CURVE,
    FRESH_WARMUP_CURVE,
    STEADY_STATE,
    plan_daily_actions,
)

log = logging.getLogger(__name__)


class WarmingAgent(Agent):
    config = AgentConfig(
        name="warming",
        max_iterations=50,  # one per account per run
        max_usd_per_run=0.00,  # no LLM calls; pure scheduling
        max_usd_per_session=0.00,
        allowed_tools=(
            "db.load_accounts",
            "db.load_persona",
            "db.save_daily_plan",
            "db.mark_account_paused",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        """
        ctx expects:
            - persona_id: str
            - date_iso: str (today in the persona's timezone)
            - curve_type: "re_wake" | "fresh_warmup"
        """
        persona_id = ctx["persona_id"]
        date_iso = ctx["date_iso"]
        curve_type = ctx.get("curve_type", "fresh_warmup")

        persona = await self.tool("db.load_persona", persona_id)
        accounts = await self.tool("db.load_accounts", persona_id)

        curve = RE_WAKE_CURVE if curve_type == "re_wake" else FRESH_WARMUP_CURVE

        for acct in accounts:
            if acct.status == "paused":
                continue

            day_in_curve = acct.day_in_curve
            weekly_mult = acct.weekly_multiplier  # sampled each Monday per account
            plan = plan_daily_actions(
                account_id=acct.id,
                date_iso=date_iso,
                day_in_curve=day_in_curve,
                curve=curve,
                steady_state=STEADY_STATE,
                persona_aggressiveness=persona.aggressiveness,
                weekly_multiplier=weekly_mult,
            )

            await self.tool("db.save_daily_plan", acct.id, plan)

            run.audit_events.append({
                "account": acct.id,
                "day_in_curve": day_in_curve,
                "intensity": plan.intensity_level,
                "follows": plan.follows,
                "likes": plan.likes,
                "story_views": plan.story_views,
                "comments": plan.comments,
                "dms": plan.dms,
            })

        return True  # done after one pass
