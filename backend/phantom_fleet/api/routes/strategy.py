"""
Strategy routes — AI-generated campaign plans.

Endpoints:
    POST   /api/strategy/generate     — generate strategy JSON from goal string
    POST   /api/strategy/apply        — apply strategy to a group
    GET    /api/strategy/{group_id}   — retrieve saved strategy for a group
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.strategy")
router = APIRouter()

# ---------------------------------------------------------------------------
# Strategy system prompt (ported from threads panel)
# ---------------------------------------------------------------------------

STRATEGY_PROMPT = """You are an elite social media marketing strategist specializing in funnel-based growth campaigns. The user will give you a campaign goal — it might be vague ("grow model accounts") or specific ("funnel men to Telegram through Threads model accounts").

CRITICAL CONTEXT: These campaigns run model/influencer accounts that funnel traffic to a link in bio (Telegram channel, landing page, etc.). The goal is NOT follower count — it's PROFILE VISITS and LINK CLICKS from the right demographic. Trending/active users are 10x more valuable than cold followers because they're online NOW and will see notifications immediately.

IMPORTANT: Never reference OnlyFans directly in any strategy output — use "Telegram", "link in bio", or "channel" instead. Meta flags direct OnlyFans references and will suspend accounts.

Your job is to create a COMPLETE, ACTIONABLE execution plan that the AI agent can follow autonomously.

Return ONLY valid JSON with this structure:

{
  "campaign_name": "Short name for this campaign",
  "summary": "1-2 sentence summary of the strategy",
  "target_niche": "The niche/industry",
  "target_accounts_to_scrape": ["@competitor1", "@competitor2", "@competitor3", "@competitor4", "@competitor5"],
  "target_hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"],
  "target_keywords": ["keyword1", "keyword2", "keyword3"],
  "warmup_plan": {
    "day_1_3": { "follows": 0, "likes": 5, "notes": "Browse only — no actions" },
    "day_4_7": { "follows": 5, "likes": 15, "comments": 0, "notes": "Soft engagement starts" },
    "day_8_14": { "follows": 15, "likes": 30, "comments": 3, "notes": "Normal engagement" },
    "day_15_30": { "follows": 25, "likes": 50, "comments": 8, "notes": "Ramping up" },
    "day_30_plus": { "follows": 40, "likes": 80, "comments": 12, "notes": "Full operation" }
  },
  "follow_strategy": {
    "source_priority": ["followers_of_competitors", "hashtag_users", "similar_accounts"],
    "filters": { "min_followers": 100, "max_followers": 50000, "exclude_private": true },
    "unfollow_after_hours": 72,
    "unfollow_non_followers_only": true
  },
  "dm_strategy": {
    "trigger": "after_follow",
    "template": "DM template with [[recipient]] and [[target_name]] variables",
    "ai_enabled": true,
    "ai_persona": "System prompt for AI-generated personalized DMs"
  },
  "comment_strategy": {
    "tone": "casual",
    "ai_enabled": true,
    "ai_prompt": "System prompt for AI comment generation",
    "templates": ["Template 1", "Template 2"]
  },
  "content_strategy": {
    "posting_frequency": "3 posts per day",
    "best_times": ["09:00", "12:00", "18:00"],
    "content_themes": ["theme1", "theme2", "theme3"]
  },
  "schedule": {
    "active_hours": { "start": "09:00", "end": "23:00" },
    "peak_activity": ["12:00-14:00", "19:00-22:00"],
    "rest_days": "none"
  },
  "risk_management": {
    "max_actions_per_day": 200,
    "ban_threshold_pct": 30,
    "reduce_on_high_risk": true
  },
  "agent_goal": "Complete 2-3 paragraph goal string for the AI agent with everything needed to operate autonomously — funnel destination is Telegram, never mention OnlyFans",
  "estimated_results": {
    "followers_per_account_30d": "X-Y",
    "followback_rate": "X-Y%",
    "total_reach_30d": "X"
  }
}"""


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    goal: str
    model: Optional[str] = None
    api_key: Optional[str] = None

class ApplyRequest(BaseModel):
    group_id: str
    strategy: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(503, "Database unavailable")
    return pool


async def _get_setting(pool, key: str) -> Optional[str]:
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM settings WHERE key=$1", key)
            return row["value"] if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate_strategy(body: GenerateRequest, request: Request):
    if not body.goal:
        raise HTTPException(400, "goal required")

    pool = _pool(request)
    api_key = body.api_key or await _get_setting(pool, "openrouter_api_key") or os.getenv("OPENROUTER_API_KEY", "")
    model = body.model or await _get_setting(pool, "ai_agent_model") or "anthropic/claude-sonnet-4-6"

    if not api_key:
        raise HTTPException(400, "No OpenRouter API key configured — set OPENROUTER_API_KEY env var or POST /api/ai-agent/configure")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       model,
                    "temperature": 0.4,
                    "max_tokens":  2000,
                    "messages": [
                        {"role": "system", "content": STRATEGY_PROMPT},
                        {"role": "user",   "content": body.goal},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"OpenRouter error: {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(502, f"Strategy generation failed: {exc}")

    # Strip markdown fences
    clean = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try:
        strategy = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"AI returned non-JSON response: {exc}")

    return {"strategy": strategy}


@router.post("/apply")
async def apply_strategy(body: ApplyRequest, request: Request):
    if not body.group_id or not body.strategy:
        raise HTTPException(400, "group_id and strategy required")

    s = body.strategy
    pool = _pool(request)

    async with pool.acquire() as conn:
        # Update group targets
        if s.get("target_accounts_to_scrape"):
            await conn.execute(
                "UPDATE groups SET target_accounts=$1::jsonb WHERE id=$2",
                json.dumps(s["target_accounts_to_scrape"]), body.group_id,
            )
        if s.get("target_hashtags"):
            await conn.execute(
                "UPDATE groups SET target_hashtags=$1::jsonb WHERE id=$2",
                json.dumps(s["target_hashtags"]), body.group_id,
            )
        if s.get("target_keywords"):
            await conn.execute(
                "UPDATE groups SET target_keywords=$1::jsonb WHERE id=$2",
                json.dumps(s["target_keywords"]), body.group_id,
            )

        # Upsert account_configs for all accounts in group
        if s.get("agent_goal"):
            await conn.execute(
                """
                INSERT INTO account_configs (account_id, ai_agent_goal, ai_agent_enabled)
                SELECT id, $1, true FROM accounts WHERE group_id=$2
                ON CONFLICT (account_id) DO UPDATE
                    SET ai_agent_goal=EXCLUDED.ai_agent_goal, ai_agent_enabled=true
                """,
                s["agent_goal"], body.group_id,
            )

        # Set schedule hours
        sched = s.get("schedule", {}).get("active_hours", {})
        if sched.get("start") and sched.get("end"):
            await conn.execute(
                """
                INSERT INTO account_configs (account_id, schedule_start, schedule_end)
                SELECT id, $1, $2 FROM accounts WHERE group_id=$3
                ON CONFLICT (account_id) DO UPDATE
                    SET schedule_start=EXCLUDED.schedule_start, schedule_end=EXCLUDED.schedule_end
                """,
                sched["start"], sched["end"], body.group_id,
            )

        # Set DM template
        dm = s.get("dm_strategy", {})
        if dm.get("template"):
            await conn.execute(
                """
                INSERT INTO account_configs (account_id, dm_template, dm_enabled, dm_trigger)
                SELECT id, $1, true, $2 FROM accounts WHERE group_id=$3
                ON CONFLICT (account_id) DO UPDATE
                    SET dm_template=EXCLUDED.dm_template, dm_enabled=true, dm_trigger=EXCLUDED.dm_trigger
                """,
                dm["template"], dm.get("trigger", "after_follow"), body.group_id,
            )

        # Set comment config
        cs = s.get("comment_strategy", {})
        if cs.get("templates"):
            await conn.execute(
                """
                INSERT INTO account_configs (account_id, comment_templates, comment_enabled, comment_ai_enabled, comment_ai_prompt)
                SELECT id, $1::jsonb, true, $2, $3 FROM accounts WHERE group_id=$4
                ON CONFLICT (account_id) DO UPDATE
                    SET comment_templates=EXCLUDED.comment_templates,
                        comment_enabled=true,
                        comment_ai_enabled=EXCLUDED.comment_ai_enabled,
                        comment_ai_prompt=EXCLUDED.comment_ai_prompt
                """,
                json.dumps(cs["templates"]),
                bool(cs.get("ai_enabled", False)),
                cs.get("ai_prompt", ""),
                body.group_id,
            )

        # Save full strategy in settings KV
        await conn.execute(
            """
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()
            """,
            f"strategy_{body.group_id}", json.dumps(s),
        )

    return {"success": True, "applied": True}


@router.get("/{group_id}")
async def get_strategy(group_id: str, request: Request):
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key=$1", f"strategy_{group_id}")
        if not row:
            return {"strategy": None}
        try:
            return {"strategy": json.loads(row["value"])}
        except Exception:
            return {"strategy": None}
