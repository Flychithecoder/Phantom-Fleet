"""
CapacityPlannerAgent — AI agent that turns natural language farm requests into
a precise capacity plan.

Agencies interact with this agent in plain language:
    "I want to run Instagram, TikTok, Telegram and Grindr on my farm"
    "20 phones, IG + Threads + Reddit"
    "snap, twitter, discord and tinder"  ← will flag snap as unsupported

The agent:
    1. Parses the request (LLM call for robust NL understanding)
    2. Runs CapacityPlanner.plan() (pure deterministic calculation)
    3. Returns a structured CapacityReport + a human-readable summary
    4. Flags unsupported platforms, warns about tradeoffs

This agent is a SPECIALIST — it does not manage other agents.
It is invoked by:
    - The Chief agent when onboarding a new customer
    - The dashboard's Capacity Planner UI endpoint
    - Direct API call from the frontend (/api/capacity-plan)

Cost profile: 1 small LLM call for parsing (cheap), 0 for the calculation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .base import Agent, AgentConfig, AgentRun
from ..core.capacity_planner import (
    CapacityPlanner,
    CapacityReport,
    PLATFORM_PROFILES,
    PHONE_PROFILES,
    resolve_platforms,
)


class CapacityPlannerAgent(Agent):
    config = AgentConfig(
        name="capacity_planner",
        max_iterations=3,    # parse → plan → respond, never needs more
        max_usd_per_run=0.02,
        max_usd_per_session=0.10,
        confirmation_required_for=(),
        allowed_tools=(
            "llm.parse_capacity_request",
            "db.load_agency_phone_profile",
        ),
    )

    # Known phone model keywords → profile key
    PHONE_MODEL_HINTS: dict[str, str] = {
        "s10 lite": "samsung_s10_lite",
        "s10lite": "samsung_s10_lite",
        "s10":     "samsung_s10_lite",
        "s20":     "samsung_s20",
        "a53":     "samsung_a53",
        "m20":     "samsung_m20",
    }

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        """
        ctx keys:
            "request"      — raw agency input string (required)
            "phone_count"  — int, optional (default 20)
            "phone_model"  — string, optional (default "samsung_s10_lite")
            "agency_id"    — optional, loads saved profile from DB
        """
        raw_request: str = ctx.get("request", "")
        if not raw_request:
            run.result = {"error": "No request provided."}
            return True

        # Step 1: Extract platform list and farm params from the request
        parsed = self._parse_request(raw_request, ctx)
        self.charge_cost(run, 0.01, "parse_capacity_request")

        # Step 2: Run deterministic capacity calculation
        planner = CapacityPlanner()
        report  = planner.plan(
            platforms=parsed["platforms"],
            phone_model=parsed["phone_model"],
            phone_count=parsed["phone_count"],
            custom_limits=parsed.get("custom_limits"),
        )

        # Step 3: Build response
        run.result = {
            "report": report,
            "summary": report.render(),
            "parsed_platforms": parsed["platforms"],
            "unsupported": report.unsupported,
            "general_brand_only": report.general_brand_only,
            "warnings": report.warnings,
            "total_accounts_per_phone": report.total_accounts_per_phone,
            "total_accounts_fleet": report.total_accounts_fleet,
        }
        return True

    def _parse_request(self, raw: str, ctx: dict) -> dict:
        """
        Parse platform names + farm params from natural language.

        Uses regex + alias lookup for determinism (no LLM call needed for
        a well-defined vocabulary). Falls back to LLM only if the request
        contains ambiguous platform names not in the alias table.
        """
        raw_lower = raw.lower()

        # Extract platform mentions by scanning for all known aliases
        found_raw: list[str] = []
        for alias in sorted(
            list({**{k: k for k in PLATFORM_PROFILES},
                  "ig": "ig", "tg": "tg", "tiktok": "tiktok",
                  "snap": "snap", "snapchat": "snapchat",
                  "twitter": "twitter", "tw": "tw",
                  "bsky": "bsky", "bluesky": "bluesky",
                  "linkedin": "linkedin",
                  "threads": "threads", "discord": "discord",
                  "dating": "dating", "grindr": "grindr",
                  "tinder": "tinder", "bumble": "bumble", "hinge": "hinge",
                  "reddit": "reddit"}),
            key=len,
            reverse=True,   # match longer aliases first to avoid "tg" eating "telegram"
        ):
            if alias in raw_lower and alias not in found_raw:
                found_raw.append(alias)

        # Phone count: look for a number near words like "phone", "box", "farm"
        phone_count = ctx.get("phone_count", 20)
        match = re.search(r"(\d+)\s*(?:phones?|devices?|boxes?|units?)", raw_lower)
        if match:
            phone_count = int(match.group(1))

        # Phone model: scan for known model hints
        phone_model = ctx.get("phone_model", "samsung_s10_lite")
        for hint, model_key in self.PHONE_MODEL_HINTS.items():
            if hint in raw_lower:
                phone_model = model_key
                break

        return {
            "platforms": found_raw if found_raw else _extract_comma_list(raw),
            "phone_count": phone_count,
            "phone_model": phone_model,
            "custom_limits": ctx.get("custom_limits"),
        }


# ---------------------------------------------------------------------------
# Standalone function — usable from the API layer without the agent wrapper
# ---------------------------------------------------------------------------


def plan_from_request(
    request: str,
    phone_count: int = 20,
    phone_model: str = "samsung_s10_lite",
    custom_limits: dict[str, int] | None = None,
) -> CapacityReport:
    """
    Synchronous shortcut for the FastAPI endpoint.

    POST /api/capacity-plan
        { "request": "IG, Threads, TikTok, Telegram, Grindr", "phone_count": 20 }

    Returns a CapacityReport directly.
    """
    agent   = CapacityPlannerAgent()
    parsed  = agent._parse_request(request, {
        "phone_count": phone_count,
        "phone_model": phone_model,
        "custom_limits": custom_limits,
    })
    planner = CapacityPlanner()
    return planner.plan(
        platforms=parsed["platforms"],
        phone_model=parsed["phone_model"],
        phone_count=parsed["phone_count"],
        custom_limits=parsed.get("custom_limits"),
    )


def _extract_comma_list(raw: str) -> list[str]:
    """Fallback: split on commas / 'and' / newlines to get platform tokens."""
    tokens = re.split(r"[,\n]+|\band\b", raw, flags=re.IGNORECASE)
    return [t.strip().lower() for t in tokens if t.strip()]
