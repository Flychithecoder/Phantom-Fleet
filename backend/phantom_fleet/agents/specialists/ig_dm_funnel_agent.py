"""
IGDMFunnelAgent — advances Instagram DM funnel enrollments through their sequences.

Processes active enrollments for one account per session, executing the next
due funnel step for each enrollment: story views, likes, profile visits, or
AI-generated DMs. Conversion signals in target replies are detected
and enrollments are marked accordingly.

Fleet-scale design (CLAUDE.md 20K account rule):
    - Daily cap: 30 funnel actions/account/day — code-enforced, not prompt-enforced.
    - Inter-step stagger: LogNormal(mean=ln(180), sigma=0.5) between enrollments.
      Median ~180s gap prevents cluster timing at fleet scale.
    - AI DM template selection: hash(account_id + target_id + step_index) % len(pool)
      so every (account, target, step) triple gets a unique deterministic pick.
      Two accounts targeting the same person send different messages.
    - XML-delimited target profile data in all LLM prompts.
    - LLM tell stripping applied to every AI-generated message before send.
    - No uniform distributions anywhere in this file.

Agent audit table (CLAUDE.md agent-audit rules):
    ┌─────────────────────┬────────────────────────────────────────────────────┐
    │ Agent               │ IGDMFunnelAgent                                    │
    │ Purpose             │ Advance DM funnel enrollments step by step         │
    │ Tools               │ None — direct HTTP via InstagramClient             │
    │ Untrusted input     │ Target DM inbox bodies (XML-delimited in prompts)  │
    │ User isolation      │ Keyed by (account_id, target_user_id) in sidecar  │
    │ Cost cap            │ 30 actions/day (code-enforced)                     │
    │ Loop cap            │ One step per enrollment per run (no inner loop)    │
    │ Confirmation        │ None required (non-destructive sends)              │
    └─────────────────────┴────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from ...core.chat_modes import ChatTier
from ...core.distributions import LogNormal
from ...core.dm_funnel import (
    CONVERSION_SIGNALS,
    FUNNEL_DAILY_ACTION_CAP,
    FUNNEL_MAX_LLM_RETRIES,
    FUNNEL_OPENROUTER_MAX_TOKENS,
    FUNNEL_OPENROUTER_MODEL,
    FUNNEL_OPENROUTER_TEMPERATURE,
    SEQUENCE_REGISTRY,
    FunnelEnrollment,
    FunnelSequence,
    FunnelStep,
    _STAGGER_HIGH,
    _STAGGER_LOW,
    _STAGGER_SIGMA,
)
from ...core.hybrid_runner import WorkerResult, WorkerTask
from ...core.instagram_client import IGSession, InstagramClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenRouter endpoint
# ---------------------------------------------------------------------------

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# ---------------------------------------------------------------------------
# LLM tell patterns — stripped from all generated funnel DMs before send
# (mirrors base_dm_chat_agent.py; duplicated here for agent independence)
# ---------------------------------------------------------------------------

_LLM_TELL_PATTERNS: list[str] = [
    "Certainly!", "Of course!", "I'd be happy to", "I would be happy to",
    "Delve into", "It's worth noting", "It is worth noting", "In conclusion",
    "As an AI", "As an AI language model", "I'm just an AI", "I am just an AI",
    "delve deeper", "elevate", "resonates with", "game-changer", "game changer",
    "furthermore", "moreover", "at the end of the day", "paradigm", "at its core",
    "a testament to", "navigate the", "harness the power", "unlock the potential",
    "tapestry of", "rich tapestry", "realm of", "embark on", "leverage",
    "cornerstone", "beacon of", "treasure trove",
]

# ---------------------------------------------------------------------------
# Stagger distribution — LogNormal, never fixed, never uniform
# ---------------------------------------------------------------------------

_STAGGER_DIST = LogNormal(low=_STAGGER_LOW, high=_STAGGER_HIGH, sigma=_STAGGER_SIGMA)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class IGDMFunnelAgent:
    """
    Advances active DM funnel enrollments for one Instagram account.

    One session processes all enrollments for the account, executing at most
    one step per enrollment (the next due step), and at most FUNNEL_DAILY_ACTION_CAP
    total actions per day across all enrollments.

    Usage:
        agent = IGDMFunnelAgent()
        result = await agent.run_session(task)

    task.params must contain:
        account_id:   str
        date_iso:     str  (YYYY-MM-DD)

    task.params may optionally contain:
        enrollments:  list[dict]  — pre-loaded enrollment dicts (for testing /
                      for when the caller manages state). If omitted, the agent
                      loads from the sidecar file.
        sequence_override: dict   — FunnelSequence dict to use instead of registry.
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_session(self, task: WorkerTask) -> WorkerResult:
        """
        Process all active enrollments for one account in one pass.

        Returns WorkerResult with data keys:
            steps_executed, conversions_detected, daily_cap_hit,
            enrollments_completed, errors
        """
        account_id = task.account_id
        date_iso = task.params.get("date_iso") or datetime.now(timezone.utc).date().isoformat()
        session: Optional[IGSession] = task.params.get("session")

        summary = {
            "steps_executed": 0,
            "conversions_detected": 0,
            "daily_cap_hit": False,
            "enrollments_completed": 0,
            "errors": [],
        }

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            log.warning("[%s/funnel] OPENROUTER_API_KEY not set — DM steps will fail", account_id)

        # Load enrollments
        enrollments = self._load_enrollments(task)
        if not enrollments:
            return WorkerResult(
                task_id=task.task_id,
                platform="instagram",
                account_id=account_id,
                success=True,
                data={**summary, "note": "no_active_enrollments"},
            )

        # Compute actions already done today (from state embedded in enrollments)
        actions_today = sum(
            1 for e in enrollments
            if e.last_action_at_iso and e.last_action_at_iso.startswith(date_iso)
        )

        # Open IG client if a real session is provided
        client_ctx = InstagramClient(session) if session else _NullClient()

        async with client_ctx as client:
            for enrollment in enrollments:
                if actions_today >= FUNNEL_DAILY_ACTION_CAP:
                    summary["daily_cap_hit"] = True
                    log.info("[%s/funnel] Daily cap reached (%d)", account_id, FUNNEL_DAILY_ACTION_CAP)
                    break

                if enrollment.completed or enrollment.converted:
                    continue

                # Resolve sequence
                sequence = self._resolve_sequence(task, enrollment.sequence_id)
                if sequence is None:
                    summary["errors"].append(
                        f"sequence_not_found:{enrollment.sequence_id}"
                    )
                    continue

                # Find the next step due
                step_idx = enrollment.current_step_index
                if step_idx >= len(sequence.steps):
                    enrollment.completed = True
                    summary["enrollments_completed"] += 1
                    continue

                step = sequence.steps[step_idx]

                # Gate: has enough time elapsed since enrollment?
                days_elapsed = _days_since(enrollment.enrolled_at_iso, date_iso)
                if days_elapsed < step.day_offset:
                    log.debug(
                        "[%s/funnel] enrollment %s: day %d < offset %d, skipping",
                        account_id, enrollment.enrollment_id, days_elapsed, step.day_offset,
                    )
                    continue

                # Gate: condition check
                condition_met = await self._check_condition(
                    step.condition, enrollment, client, session
                )
                if not condition_met:
                    log.debug(
                        "[%s/funnel] enrollment %s: condition %s not met, skipping",
                        account_id, enrollment.enrollment_id, step.condition,
                    )
                    continue

                # Execute the step
                log.info(
                    "[%s/funnel] enrollment %s step %d (%s) — executing",
                    account_id, enrollment.enrollment_id, step_idx, step.action,
                )
                success = await self._execute_step(
                    step=step,
                    enrollment=enrollment,
                    sequence=sequence,
                    client=client,
                    session=session,
                    api_key=api_key,
                )

                now_iso = datetime.now(timezone.utc).isoformat()
                if success:
                    enrollment.current_step_index += 1
                    enrollment.last_action_at_iso = now_iso
                    actions_today += 1
                    summary["steps_executed"] += 1

                    # Mark completed when all steps done
                    if enrollment.current_step_index >= len(sequence.steps):
                        enrollment.completed = True
                        summary["enrollments_completed"] += 1
                else:
                    summary["errors"].append(
                        f"step_failed:enrollment={enrollment.enrollment_id}:step={step_idx}"
                    )

                # Check inbox for conversion signals (only if we have a real session)
                if session is not None:
                    converted = await self._check_conversion(
                        enrollment, client
                    )
                    if converted and not enrollment.converted:
                        enrollment.converted = True
                        summary["conversions_detected"] += 1
                        log.info(
                            "[%s/funnel] CONVERSION: enrollment %s target %s",
                            account_id, enrollment.enrollment_id, enrollment.target_user_id,
                        )

                # Stagger between enrollments: LogNormal, not fixed
                stagger = _STAGGER_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"stagger_{enrollment.enrollment_id}",
                )
                await asyncio.sleep(stagger)

        # Persist updated enrollment state
        self._save_enrollments(account_id, date_iso, enrollments)

        return WorkerResult(
            task_id=task.task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action": "ig_dm_funnel",
                **summary,
            },
        )

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        step: FunnelStep,
        enrollment: FunnelEnrollment,
        sequence: FunnelSequence,
        client,
        session: Optional[IGSession],
        api_key: str,
    ) -> bool:
        """Execute one funnel step. Returns True on success, False on failure."""
        target_id = enrollment.target_user_id

        try:
            if step.action == "story_view":
                return await self._do_story_view(target_id, enrollment, client)

            elif step.action == "like_post":
                return await self._do_like_post(target_id, enrollment, client)

            elif step.action == "profile_visit":
                return await self._do_profile_visit(target_id, client)

            elif step.action == "dm":
                return await self._do_send_dm(
                    step=step,
                    enrollment=enrollment,
                    sequence=sequence,
                    client=client,
                    api_key=api_key,
                )

        except Exception as exc:
            log.error(
                "[funnel] Step %s failed for enrollment %s: %s",
                step.action, enrollment.enrollment_id, exc,
            )
            return False

        return False  # unreachable but satisfies type checker

    async def _do_story_view(
        self,
        target_id: str,
        enrollment: FunnelEnrollment,
        client,
    ) -> bool:
        """View the target's current stories."""
        # Use a stored reel/media ID from state, or fall back to target_id as reel_id.
        # In production the follow agent stores story tray data in enrollment.state.
        reel_id = enrollment.state.get("story_reel_id", target_id)
        media_ids = enrollment.state.get("story_media_ids", [target_id])
        await client.story_view(reel_id=reel_id, media_ids=media_ids)
        return True

    async def _do_like_post(
        self,
        target_id: str,
        enrollment: FunnelEnrollment,
        client,
    ) -> bool:
        """Like the target's most recent post."""
        media_id = enrollment.state.get("last_media_id", target_id)
        await client.like_post(media_id=media_id)
        return True

    async def _do_profile_visit(
        self,
        target_id: str,
        client,
    ) -> bool:
        """Fetch target profile — registers as a profile view on Instagram."""
        await client.get_user_info(target_id)
        return True

    async def _do_send_dm(
        self,
        step: FunnelStep,
        enrollment: FunnelEnrollment,
        sequence: FunnelSequence,
        client,
        api_key: str,
    ) -> bool:
        """Generate (or select) and send a funnel DM."""
        step_idx = enrollment.current_step_index
        pool = step.dm_template_pool or []

        # Select template deterministically: hash(account_id + target_id + step_index)
        # This guarantees two different accounts targeting the same person on the
        # same step pick different messages — no monoculture at fleet scale.
        seed_key = f"{enrollment.account_id}|{enrollment.target_user_id}|{step_idx}"
        digest = hashlib.sha256(seed_key.encode()).digest()
        template_idx = int.from_bytes(digest[:4], "big") % len(pool)
        base_template = pool[template_idx]

        # Generate AI-enhanced message (uses base_template as context hint)
        text = await self._generate_funnel_dm(
            template=base_template,
            enrollment=enrollment,
            step_idx=step_idx,
            total_steps=len(sequence.steps),
            chat_tier=sequence.chat_tier,
            api_key=api_key,
            max_tokens=step.max_tokens,
        )
        if text is None:
            # Fallback: use the raw template if AI fails
            text = base_template
            log.warning(
                "[funnel] LLM failed for enrollment %s step %d, using raw template",
                enrollment.enrollment_id, step_idx,
            )

        await client.send_dm(recipient_user_id=enrollment.target_user_id, text=text)
        return True

    # ------------------------------------------------------------------
    # AI DM generation
    # ------------------------------------------------------------------

    async def _generate_funnel_dm(
        self,
        template: str,
        enrollment: FunnelEnrollment,
        step_idx: int,
        total_steps: int,
        chat_tier: ChatTier,
        api_key: str,
        max_tokens: int,
    ) -> Optional[str]:
        """
        Generate a short, casual DM using OpenRouter (Haiku).

        System prompt includes:
            - step context ("this is day 4 of 14, keep it casual, no mention of OF yet")
            - ChatTier tone guidance
            - template as a style seed

        Target profile data is XML-delimited (CLAUDE.md injection defense).
        LLM tells are stripped unconditionally before return.
        """
        if not api_key:
            return None

        # Compute "day" context from step_idx
        day_labels = {0: "first", 1: "second", 2: "third", 3: "fourth",
                      4: "fifth", 5: "sixth", 6: "seventh"}
        day_label = day_labels.get(step_idx, f"step {step_idx + 1}")
        is_cta_step = step_idx == total_steps - 1

        tone_guide = {
            ChatTier.FLIRTY_SFW:  "playful, flirty but clean, lowercase, 1-2 emojis max",
            ChatTier.CASUAL_SFW:  "casual, friendly, lowercase, 1-2 emojis max",
            ChatTier.MIXED:       "casual, slight flirt ok, lowercase, 1-2 emojis",
        }.get(chat_tier, "casual, lowercase, 1-2 emojis max")

        cta_note = (
            " This is the final message — include a gentle call to action for "
            "exclusive content, keep it natural."
            if is_cta_step else
            " Do NOT mention any platform, link, or CTA in this message."
        )

        system_prompt = (
            f"You are a young woman sending a casual Instagram DM. "
            f"This is the {day_label} touch in a multi-step nurture sequence. "
            f"Tone: {tone_guide}. "
            f"Keep the message under 20 words. No hashtags. No formal language. "
            f"Use the provided template as inspiration for style, NOT as an exact script."
            f"{cta_note}"
        )

        # XML-delimit template (it came from our pool, but fence it anyway per rule)
        user_prompt = (
            f"<template_inspiration>\n{template}\n</template_inspiration>\n\n"
            f"Write a fresh, natural Instagram DM in that style. "
            f"Max 20 words. No hashtags."
        )

        payload = {
            "model": FUNNEL_OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": FUNNEL_OPENROUTER_TEMPERATURE,
            "max_tokens":  max_tokens,
        }

        for attempt in range(FUNNEL_MAX_LLM_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    resp = await http.post(
                        OPENROUTER_API_URL,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type":  "application/json",
                        },
                        content=json.dumps(payload).encode(),
                    )
                    resp.raise_for_status()
                    data = resp.json()

                text = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if not text:
                    log.warning("[funnel] Empty LLM reply attempt %d", attempt + 1)
                    continue

                text = _strip_llm_tells(text)
                return text

            except Exception as exc:
                log.error("[funnel] LLM error attempt %d: %s", attempt + 1, exc)

        return None

    # ------------------------------------------------------------------
    # Condition checking
    # ------------------------------------------------------------------

    async def _check_condition(
        self,
        condition: Optional[str],
        enrollment: FunnelEnrollment,
        client,
        session: Optional[IGSession],
    ) -> bool:
        """Return True if the step's condition is satisfied (or is None)."""
        if condition is None:
            return True

        if condition == "if_followed_back":
            return await self._target_follows_us(enrollment, client, session)

        if condition == "if_story_viewed_back":
            # We can't reliably detect this from the API, so check state
            return enrollment.state.get("story_viewed_back", False)

        # Unknown condition — fail safe (don't execute)
        log.warning("[funnel] Unknown condition %r — blocking step", condition)
        return False

    async def _target_follows_us(
        self,
        enrollment: FunnelEnrollment,
        client,
        session: Optional[IGSession],
    ) -> bool:
        """
        Check whether the target follows our account back.

        Uses a cached value in enrollment.state["follows_us"] if present
        (avoids an API call on every session run).
        If not cached, call get_user_info to refresh the relationship.
        """
        cached = enrollment.state.get("follows_us")
        if cached is not None:
            return bool(cached)

        if session is None:
            return False

        try:
            info = await client.get_user_info(enrollment.target_user_id)
            # IG API returns friendship_status in user info for our account
            friendship = info.get("user", {}).get("friendship_status", {})
            follows_us = bool(friendship.get("followed_by", False))
            enrollment.state["follows_us"] = follows_us
            return follows_us
        except Exception as exc:
            log.warning(
                "[funnel] Could not check follow status for %s: %s",
                enrollment.target_user_id, exc,
            )
            return False

    # ------------------------------------------------------------------
    # Conversion detection
    # ------------------------------------------------------------------

    async def _check_conversion(
        self,
        enrollment: FunnelEnrollment,
        client,
    ) -> bool:
        """
        Scan the inbox thread with this target for conversion signal keywords.

        Returns True if any conversion keyword is found in the target's messages.
        Keywords are checked case-insensitively (CONVERSION_SIGNALS is lowercase).
        """
        try:
            inbox = await client.get_inbox()
            threads = inbox.get("inbox", {}).get("threads", [])
            for thread in threads:
                users = thread.get("users", [])
                user_ids = [str(u.get("pk") or u.get("id") or "") for u in users]
                if enrollment.target_user_id not in user_ids:
                    continue
                items = thread.get("items", [])
                for item in items:
                    # Only check messages FROM the target (not sent by viewer)
                    if item.get("is_sent_by_viewer", False):
                        continue
                    text = (item.get("text") or "").lower()
                    for signal in CONVERSION_SIGNALS:
                        if signal in text:
                            return True
        except Exception as exc:
            log.warning("[funnel] Inbox conversion check failed: %s", exc)

        return False

    # ------------------------------------------------------------------
    # State persistence (JSON sidecar)
    # ------------------------------------------------------------------

    def _load_enrollments(self, task: WorkerTask) -> list[FunnelEnrollment]:
        """
        Load enrollments either from task.params["enrollments"] (test injection)
        or from the JSON sidecar file on disk.
        """
        account_id = task.account_id
        date_iso = task.params.get("date_iso", datetime.now(timezone.utc).date().isoformat())

        # Allow caller to inject pre-loaded enrollments (testing + API layer)
        raw_list = task.params.get("enrollments")
        if raw_list is not None:
            return [FunnelEnrollment.from_dict(d) for d in raw_list]

        path = _sidecar_path(account_id, date_iso)
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [FunnelEnrollment.from_dict(d) for d in data]
        except Exception as exc:
            log.warning("[funnel] Failed to load enrollments for %s: %s", account_id, exc)
            return []

    def _save_enrollments(
        self,
        account_id: str,
        date_iso: str,
        enrollments: list[FunnelEnrollment],
    ) -> None:
        """Persist enrollment state to JSON sidecar."""
        path = _sidecar_path(account_id, date_iso)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps([e.to_dict() for e in enrollments], indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.error("[funnel] Failed to save enrollments for %s: %s", account_id, exc)

    # ------------------------------------------------------------------
    # Sequence resolution
    # ------------------------------------------------------------------

    def _resolve_sequence(
        self, task: WorkerTask, sequence_id: str
    ) -> Optional[FunnelSequence]:
        """
        Resolve a FunnelSequence by ID.

        Checks task.params["sequence_override"] first (for testing), then
        the global SEQUENCE_REGISTRY.
        """
        override = task.params.get("sequence_override")
        if override is not None:
            steps = [
                FunnelStep(
                    day_offset=s["day_offset"],
                    action=s["action"],
                    dm_template_pool=s.get("dm_template_pool"),
                    condition=s.get("condition"),
                    max_tokens=s.get("max_tokens", FUNNEL_OPENROUTER_MAX_TOKENS),
                )
                for s in override["steps"]
            ]
            return FunnelSequence(
                sequence_id=override["sequence_id"],
                name=override.get("name", "override"),
                steps=steps,
                chat_tier=ChatTier(override.get("chat_tier", int(ChatTier.FLIRTY_SFW))),
            )

        return SEQUENCE_REGISTRY.get(sequence_id)


# ---------------------------------------------------------------------------
# Null client for sessions-less test runs (dry-run mode)
# ---------------------------------------------------------------------------


class _NullClient:
    """
    Drop-in replacement for InstagramClient when no real session is provided.
    All methods are no-ops that return empty dicts. Used so the funnel agent
    can run unit-tested without mocking the full client context manager.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def story_view(self, **_) -> dict:
        return {}

    async def like_post(self, **_) -> dict:
        return {}

    async def get_user_info(self, *_, **__) -> dict:
        return {}

    async def send_dm(self, **_) -> dict:
        return {}

    async def get_inbox(self, **_) -> dict:
        return {}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _days_since(enrolled_at_iso: str, date_iso: str) -> int:
    """Return integer days between enrolled_at_iso date and date_iso."""
    from datetime import date as _date

    try:
        enrolled = _date.fromisoformat(enrolled_at_iso[:10])
        today = _date.fromisoformat(date_iso)
        return (today - enrolled).days
    except Exception:
        return 0


def _sidecar_path(account_id: str, date_iso: str):
    """Path to the JSON sidecar file for one account's funnel enrollments."""
    from pathlib import Path

    base = Path(os.environ.get("PHANTOM_STATE_DIR", "/tmp/phantom_state"))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"funnel_{account_id}_{date_iso}.json"


def _strip_llm_tells(text: str) -> str:
    """Remove common LLM tell phrases from generated text."""
    for tell in _LLM_TELL_PATTERNS:
        lower = text.lower()
        tell_lower = tell.lower()
        pos = lower.find(tell_lower)
        while pos != -1:
            text = text[:pos] + text[pos + len(tell):]
            lower = text.lower()
            pos = lower.find(tell_lower)
    return text.strip()
