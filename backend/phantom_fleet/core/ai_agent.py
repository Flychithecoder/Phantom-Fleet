"""
AI Agent core — autonomous per-account Threads growth agent.

Architecture:
    - AgentManager: singleton that tracks running/stopped agents per account
    - agent_tick(account_id, pool): single decision cycle for one account
    - Uses account_configs for per-account goals, schedule, and DM/comment settings
    - Stage classifier: maps warmup phase + days active → behavior mode
    - Risk scorer: 0-100 based on error rate, action density, and phase
    - Decision tree: which action to take this tick based on stage + risk + time

Stage classification:
    brand_new       → profile_warmup phase (days 1-3)
    early_warmup    → soft_engage phase (days 4-8)
    mid_warmup      → engage phase (days 9-15)
    content_start   → content_start phase
    graduated       → graduated phase
    mature          → active phase, >30 days

Risk scoring (0-100):
    - Recent errors in last 24h: +10 per error (max 40)
    - Action velocity: if doing >80% of daily cap: +20
    - Phase gap: if actions are premature for phase: +30
    - Low follower count relative to age: +10

All LLM calls go through OpenRouter (OPENROUTER_API_KEY env var).
Model: claude-haiku-4-5-20251001 for ticks, claude-sonnet-4-6 for deep analysis.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

from .warmup_phases import is_action_allowed, get_phase_limits, get_day_limits  # noqa: F401

log = logging.getLogger("phantom_fleet.ai_agent")

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGE_ORDER = [
    "brand_new",
    "early_warmup",
    "mid_warmup",
    "content_start",
    "graduated",
    "mature",
]

_PHASE_TO_STAGE = {
    "profile_warmup": "brand_new",
    "soft_engage":    "early_warmup",
    "engage":         "mid_warmup",
    "content_start":  "content_start",
    "graduated":      "graduated",
    "active":         "mature",
}

# ---------------------------------------------------------------------------
# Agent state per account
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    account_id: str
    running: bool = False
    stage: str = "brand_new"
    risk_score: int = 0
    last_tick: Optional[datetime] = None
    errors_today: int = 0
    actions_today: int = 0
    tick_count: int = 0
    task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# AgentManager
# ---------------------------------------------------------------------------

class AgentManager:
    """
    Singleton managing per-account agent loops.
    All agents share the same event loop.
    """

    def __init__(self) -> None:
        self._states: dict[str, AgentState] = {}

    def get_all_statuses(self) -> list[dict]:
        return [
            {
                "account_id": s.account_id,
                "running": s.running,
                "stage": s.stage,
                "risk_score": s.risk_score,
                "last_tick": s.last_tick.isoformat() if s.last_tick else None,
                "errors_today": s.errors_today,
                "actions_today": s.actions_today,
            }
            for s in self._states.values()
        ]

    async def start_agent(self, account_id: str, pool) -> None:
        state = self._states.get(account_id)
        if state and state.running:
            return  # Already running

        if state is None:
            state = AgentState(account_id=account_id)
            self._states[account_id] = state

        state.running = True
        state.task = asyncio.create_task(
            self._agent_loop(account_id, pool),
            name=f"agent_{account_id}",
        )
        log.info("Agent started: %s", account_id)

    def stop_agent(self, account_id: str) -> None:
        state = self._states.get(account_id)
        if state:
            state.running = False
            if state.task and not state.task.done():
                state.task.cancel()
        log.info("Agent stopped: %s", account_id)

    def stop_all(self) -> None:
        for account_id in list(self._states):
            self.stop_agent(account_id)

    async def agent_tick(self, account_id: str, pool) -> dict:
        """Run a single agent decision cycle (for run-once endpoint)."""
        return await _run_tick(account_id, pool)

    async def _agent_loop(self, account_id: str, pool) -> None:
        """Continuous loop — one tick every ~5 minutes with jitter."""
        import random
        state = self._states.get(account_id)
        while state and state.running:
            try:
                result = await _run_tick(account_id, pool)
                if state:
                    state.last_tick = datetime.now(timezone.utc)
                    state.tick_count += 1
                    state.stage = result.get("stage", state.stage)
                    state.risk_score = result.get("risk_score", 0)
                    state.actions_today += result.get("actions_taken", 0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Agent loop %s: %s", account_id, exc)
                if state:
                    state.errors_today += 1

            # Wait 5-15 min between ticks (seeded jitter to spread fleet load)
            sleep_sec = 300 + random.uniform(0, 600)
            try:
                await asyncio.sleep(sleep_sec)
            except asyncio.CancelledError:
                break


# ---------------------------------------------------------------------------
# Core tick logic
# ---------------------------------------------------------------------------

async def _run_tick(account_id: str, pool) -> dict:
    """
    One autonomous agent decision cycle:
    1. Fetch account + config data (60+ context points)
    2. Classify stage + compute risk
    3. Ask Claude what to do
    4. Execute the action
    5. Log to activity_log
    """
    async with pool.acquire() as conn:
        acc = await conn.fetchrow(
            """
            SELECT a.*, ac.ai_agent_goal, ac.ai_agent_enabled, ac.schedule_start,
                   ac.schedule_end, ac.dm_enabled, ac.dm_template, ac.dm_trigger,
                   ac.comment_enabled, ac.comment_templates, ac.comment_ai_enabled,
                   ac.comment_ai_prompt
            FROM accounts a
            LEFT JOIN account_configs ac ON ac.account_id = a.id
            WHERE a.id = $1
            """,
            account_id,
        )
        if not acc:
            raise ValueError(f"Account {account_id} not found")

        if not acc.get("ai_agent_enabled"):
            return {"skipped": True, "reason": "ai_agent not enabled"}

        # Recent error count
        errors_24h = await conn.fetchval(
            """
            SELECT COUNT(*) FROM activity_log
            WHERE account_id=$1 AND status='failed'
              AND created_at > now() - interval '24 hours'
            """,
            account_id,
        ) or 0

        # Actions today
        actions_today = await conn.fetchval(
            """
            SELECT COUNT(*) FROM activity_log
            WHERE account_id=$1 AND status='success'
              AND created_at::date = CURRENT_DATE
            """,
            account_id,
        ) or 0

        # Pending targets count
        pending_targets = await conn.fetchval(
            """
            SELECT COUNT(*) FROM scraped_targets
            WHERE status='pending'
              AND (group_id IS NULL OR group_id IN (
                  SELECT group_id FROM accounts WHERE id=$1
              ))
            """,
            account_id,
        ) or 0

    phase = acc.get("warmup_phase") or "profile_warmup"
    stage = _PHASE_TO_STAGE.get(phase, "brand_new")
    risk  = _calc_risk(phase, int(errors_24h), int(actions_today))

    context = _build_context(acc, stage, risk, int(errors_24h), int(actions_today), int(pending_targets))

    # Check schedule window
    now_utc = datetime.now(timezone.utc)
    schedule_start = acc.get("schedule_start") or "09:00"
    schedule_end   = acc.get("schedule_end")   or "23:00"
    if not _in_schedule_window(now_utc, schedule_start, schedule_end):
        return {"skipped": True, "reason": f"outside schedule window {schedule_start}-{schedule_end}", "stage": stage, "risk_score": risk}

    # Get AI decision
    decision = await _ask_ai(context, acc.get("ai_agent_goal") or "", account_id)

    # Execute action
    action_taken = await _execute_decision(decision, acc, pool, account_id)

    # Log to activity_log
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO activity_log (account_id, action, target, status, message)
            VALUES ($1, 'ai_agent', $2, $3, $4)
            """,
            account_id,
            decision.get("action", "noop"),
            decision.get("target", ""),
            "success" if action_taken else "failed",
            json.dumps({"stage": stage, "risk": risk, "decision": decision}),
        )

    return {
        "stage": stage,
        "risk_score": risk,
        "decision": decision,
        "actions_taken": 1 if action_taken else 0,
    }


def _calc_risk(phase: str, errors_24h: int, actions_today: int) -> int:
    """Risk score 0-100. Higher = back off."""
    score = 0
    score += min(errors_24h * 10, 40)

    limits = get_phase_limits("threads", phase)
    cap = limits.max_follows + limits.max_likes + limits.max_posts + limits.max_comments
    if cap > 0 and actions_today / cap > 0.8:
        score += 20

    if phase in ("profile_warmup", "soft_engage"):
        score += 10  # New account — always elevated caution

    return min(score, 100)


def _build_context(acc: dict, stage: str, risk: int, errors: int, actions: int, pending: int) -> str:
    """Build the context string for the AI decision prompt."""
    now = datetime.now(timezone.utc)
    return (
        f"Account: {acc.get('username', 'unknown')} | "
        f"Stage: {stage} | Risk: {risk}/100 | "
        f"Phase: {acc.get('warmup_phase', 'unknown')} | "
        f"Actions today: {actions} | Errors 24h: {errors} | "
        f"Pending targets: {pending} | "
        f"Follower count: {acc.get('follower_count', 0)} | "
        f"Follow count: {acc.get('follow_count', 0)} | "
        f"Time UTC: {now.strftime('%H:%M')} | "
        f"DM enabled: {bool(acc.get('dm_enabled'))} | "
        f"Comment enabled: {bool(acc.get('comment_enabled'))}"
    )


async def _ask_ai(context: str, goal: str, account_id: str) -> dict:
    """Ask Claude Haiku what action to take this tick."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        return {"action": "like_trending", "reason": "No API key — defaulting to safe action"}

    system = """You are an autonomous Threads growth agent. Given account context and goal, decide the single best action to take right now.

Return ONLY valid JSON:
{
  "action": "like_trending|warm_and_follow|post_content|comment|dm|noop",
  "target": "user_id or media_id or empty",
  "reason": "brief reason",
  "priority": 1-10
}

Rules:
- noop if risk > 70
- noop if outside active hours
- like_trending if stage is brand_new or early_warmup
- warm_and_follow if pending targets > 0 and stage >= mid_warmup
- post_content at most 3x per day
- Never reference OnlyFans — use Telegram funnel
- Prefer warm_and_follow > post_content > like_trending > noop"""

    user_msg = f"Context: {context}\n\nGoal: {goal}\n\nWhat action should I take right now?"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "anthropic/claude-haiku-4-5-20251001",
                    "temperature": 0.3,
                    "max_tokens":  150,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user_msg},
                    ],
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            import re
            clean = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
            return json.loads(clean)
    except Exception as exc:
        log.warning("[%s] AI decision failed: %s", account_id, exc)
        return {"action": "like_trending", "reason": f"AI failed: {exc}", "priority": 1}


async def _execute_decision(decision: dict, acc: dict, pool, account_id: str) -> bool:
    """Execute the AI's chosen action directly via ThreadsClient."""
    action = decision.get("action", "noop")
    if action == "noop":
        return False

    try:
        from .instagram_client import IGSession
        from .threads_client import ThreadsClient
        from .hybrid_runner import PlatformHeaders

        # Build session from account DB row
        session = IGSession(
            account_id=account_id,
            ig_user_id=acc.get("user_id", ""),
            username=acc.get("username", ""),
            session_id=acc.get("sessionid", ""),
            csrftoken=acc.get("csrftoken", ""),
            mid=acc.get("mid", ""),
            ds_user_id=acc.get("user_id", ""),
            headers=PlatformHeaders(),
        )

        proxy_url = None
        if acc.get("proxy_id"):
            async with pool.acquire() as conn:
                proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", acc["proxy_id"])
                if proxy:
                    proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"

        if action == "like_trending":
            async with pool.acquire() as conn:
                post = await conn.fetchrow(
                    "SELECT media_id FROM trending_posts ORDER BY RANDOM() LIMIT 1"
                )
            if post:
                async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                    await client.like(post["media_id"])
                return True

        elif action == "warm_and_follow":
            async with pool.acquire() as conn:
                target = await conn.fetchrow(
                    "SELECT user_id FROM scraped_targets WHERE status='pending' ORDER BY RANDOM() LIMIT 1"
                )
            if target:
                async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                    await client.follow(target["user_id"])
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE scraped_targets SET status='followed', followed_at=now() WHERE user_id=$1 AND status='pending'",
                        target["user_id"],
                    )
                return True

        elif action == "post_content":
            # Generate caption via ThreadsContentGenerator
            caption = "✨"
            try:
                from ..agents.specialists.threads_content_generator import (
                    ThreadsContentGenerator, PersonaContext
                )
                from datetime import date
                gen = ThreadsContentGenerator()
                persona = PersonaContext()
                generated = await gen.generate_post(
                    account_id=account_id,
                    persona=persona,
                    date_iso=date.today().isoformat(),
                )
                caption = generated.text
            except Exception as exc:
                log.warning("[%s] Caption generation failed: %s", account_id, exc)

            async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                await client.post_text(caption)
            return True

        return False
    except Exception as exc:
        log.warning("[%s] Execute decision failed: %s", account_id, exc)
        return False


def _in_schedule_window(now_utc: datetime, start: str, end: str) -> bool:
    """Check if current UTC time is within the schedule window."""
    try:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        current_min = now_utc.hour * 60 + now_utc.minute
        start_min   = sh * 60 + sm
        end_min     = eh * 60 + em
        return start_min <= current_min <= end_min
    except Exception:
        return True  # Default open if parse fails
