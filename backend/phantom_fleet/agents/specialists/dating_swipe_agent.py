"""
DatingSwipeAgent — swipe automation for Tinder, Bumble, and Hinge.

Responsibilities:
    - Execute a daily swipe/like session for one account on one platform
    - Sample action counts and timing from LogNormal distributions
      (never fixed delays or flat random — see distributions.py rule)
    - Enforce per-platform client semantics (s_number for Tinder, etc.)
    - Integrate with PhotoVerificationOrchestrator when verification fires
    - Hinge: include comment with 30% probability on likes
    - Log every swipe to audit trail BEFORE execution

Detection hardening:
    - right_ratio: LogNormal mean=0.15 σ=0.05 (realistic human selectivity)
    - Dwell per profile: LogNormal mean=4s σ=2 (matches app usage telemetry)
    - Comments chosen from a pool, not generated fresh — production LLM variant
      will replace this with Chat AI, but pool is the fleet-safe fallback
    - Never fixed sleep intervals — always sampled from distributions

Fleet-scale notes (see CLAUDE.md 20K account thought experiment):
    - right_ratio is PER-ACCOUNT sampled, not a global constant. At 20K
      accounts the histogram of right_ratios forms a LogNormal bell, not
      a monoculture spike at 0.15
    - Dwell times produce a log-normal histogram, not a rectangular one
    - Comment selection is seeded by (account_id, target_id) so different
      accounts opening the same profile see different comments
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, timezone, datetime
from typing import Literal, Optional

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import LogNormal, seed_for, _rng_from_seed
from ...core.tinder_client import TinderClient, TinderSession, TinderSessionExpired, TinderRateLimited, TinderActionBlocked
from ...core.bumble_client import BumbleClient, BumbleSession, BumbleSessionExpired, BumbleRateLimited
from ...core.hinge_client import HingeClient, HingeSession, HingeSessionExpired, HingeRateLimited, HingeVerificationRequired
from ...core.photo_verification import (
    PhotoVerificationOrchestrator,
    VerificationRequest,
    VerificationResult,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Distribution constants
# ---------------------------------------------------------------------------

# How many profiles to process in one session (LogNormal)
DAILY_BUDGET_DIST = LogNormal(low=20.0, high=80.0, sigma=0.35)

# Right-swipe (like) probability: realistic human selectivity
# LogNormal with mean~0.15, sigma=0.05 — produces per-account variation
# so fleet histogram is bell-shaped, not monoculture at 0.15
RIGHT_RATIO_DIST = LogNormal(low=0.05, high=0.35, sigma=0.30)

# Dwell time per profile in seconds (how long human looks before swiping)
DWELL_DIST = LogNormal(low=1.5, high=15.0, sigma=0.50)

# Inter-swipe pause — brief gap between consecutive swipes
INTER_SWIPE_DIST = LogNormal(low=0.5, high=4.0, sigma=0.40)

# Hinge: probability a like includes a comment (30% per spec)
HINGE_COMMENT_PROBABILITY = 0.30

# ---------------------------------------------------------------------------
# Hinge comment pool
# The pool must be large enough that at fleet scale no two accounts share
# a comment on the same target. Pool size 60 → ~1 in 60 overlap risk.
# Production: replace with Chat AI LLM generation per-account per-target.
# ---------------------------------------------------------------------------

HINGE_COMMENT_POOL: list[str] = [
    "This actually made me laugh out loud",
    "Okay this is a great photo",
    "Love the energy here",
    "This needs a story behind it",
    "You look like someone I'd get along with",
    "That smile is contagious",
    "Strong opener right here",
    "I have so many questions about this",
    "This caught my eye immediately",
    "Honestly impressive",
    "Really love this",
    "That's a vibe",
    "Okay I need to know more",
    "This is my favorite kind of thing",
    "You seem genuinely fun",
    "I respect it",
    "This is exactly my kind of humor",
    "Underrated photo right here",
    "You have good taste",
    "That looks like a good time",
    "This tells me everything I need to know",
    "Okay this is actually perfect",
    "Bold choice, I'm into it",
    "Love the confidence",
    "This made me stop scrolling",
    "I feel like we'd have a great conversation",
    "You have really good energy",
    "This is adorable honestly",
    "Solid taste right here",
    "That's genuinely impressive",
    "Okay this is cute",
    "I like the way you think",
    "This feels real and I appreciate that",
    "You clearly have a fun side",
    "I'd love to hear more about this",
    "Honestly your vibe is great",
    "This is the type of thing I'd screenshot",
    "You seem like the most interesting person in the room",
    "Can we talk about this",
    "Love this so much",
    "This is giving main character energy",
    "I see you",
    "Underrated quality right here",
    "You have a great sense of self",
    "This is my kind of person",
    "I'm genuinely smiling at this",
    "That's a rare quality",
    "You have great taste in everything",
    "This photo tells a whole story",
    "I'd ask about this in person",
    "Okay you had me at this",
    "Love the authenticity here",
    "This is refreshing to see",
    "You seem like the real deal",
    "That's actually really cool",
    "I'd definitely want to hear this story",
    "You look like you know how to have fun",
    "This made me smile for real",
    "Genuinely great energy",
    "I appreciate someone who appreciates this",
]


def _hinge_comment_for(account_id: str, target_id: str, content_id: str) -> str:
    """
    Select a comment from the pool, deterministically seeded by
    (account_id, target_id, content_id).

    Different accounts viewing the same profile get different comments.
    Same account viewing the same profile always gets the same comment
    (idempotent on retry). Both properties come from the hash seed.
    """
    key = f"{account_id}|{target_id}|{content_id}"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(HINGE_COMMENT_POOL)
    return HINGE_COMMENT_POOL[idx]


def _should_comment(account_id: str, target_id: str, content_id: str) -> bool:
    """
    Deterministically decide whether THIS like should include a comment.
    Seeded so ~30% of likes across the fleet get comments, but the
    decision is stable per (account, target, content) triple.
    """
    key = f"{account_id}|{target_id}|{content_id}|comment_decision"
    digest = hashlib.sha256(key.encode()).digest()
    # Use first byte as a random roll in [0, 255]; threshold for 30% ≈ 77
    return digest[0] < 77


# ---------------------------------------------------------------------------
# Swipe result record
# ---------------------------------------------------------------------------


@dataclass
class SwipeRecord:
    """Audit record for one swipe/like action."""
    account_id:  str
    platform:    str
    target_id:   str
    action:      Literal["like", "pass", "super_like"]
    comment:     Optional[str]
    dwell_ms:    int
    ts:          str
    result:      dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class DatingSwipeAgent(Agent):
    """
    Executes one swipe session for one account on one platform.

    ctx keys:
        account_id:    str
        platform:      "tinder" | "bumble" | "hinge"
        session:       TinderSession | BumbleSession | HingeSession (pre-built)
        date_iso:      str  (YYYY-MM-DD in account's timezone)
        daily_swipe_budget: int | None  (if None, sampled from LogNormal)
        needs_verification: bool (if True, verification check runs first)
        vault_clip_id: str | None  (pre-assigned vault clip)
        verification_orchestrator: PhotoVerificationOrchestrator | None
    """

    config = AgentConfig(
        name="dating_swipe",
        max_iterations=1,          # single session per run — no inner loop
        max_usd_per_run=0.00,      # no LLM calls in the swipe path
        max_usd_per_session=0.00,
        allowed_tools=(
            "db.save_swipe_records",
            "db.mark_verification_done",
            "phone.inject_verification_frames",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id   = ctx["account_id"]
        platform     = ctx["platform"]
        session      = ctx["session"]
        date_iso     = ctx.get("date_iso", date.today().isoformat())

        # ------------------------------------------------------------------
        # 1. Handle pending photo verification first
        # ------------------------------------------------------------------
        if ctx.get("needs_verification"):
            orchestrator: Optional[PhotoVerificationOrchestrator] = ctx.get(
                "verification_orchestrator"
            )
            if orchestrator is not None:
                req = VerificationRequest(
                    account_id=account_id,
                    platform=platform,
                    attempt_number=ctx.get("verification_attempt", 1),
                    detected_poses=ctx.get("detected_poses", []),
                    vault_clip_id=ctx.get("vault_clip_id"),
                )
                result: VerificationResult = orchestrator.resolve(req)
                self._audit_event(run, "verification_resolved", {
                    "status": result.status,
                    "clip_id": result.clip_id,
                    "pose": result.pose.value if result.pose else None,
                })
                if result.status == "ready":
                    await self.tool(
                        "phone.inject_verification_frames",
                        delivery_url=result.delivery_url,
                        clip_id=result.clip_id,
                        replay_params=result.replay_params,
                    )
                    await self.tool("db.mark_verification_done", account_id)
                else:
                    log.warning(
                        "Verification not ready for %s: %s — %s",
                        account_id, result.status, result.notes,
                    )
                    run.outputs["verification_status"] = result.status
                    return True   # stop the run; can't swipe without verification

        # ------------------------------------------------------------------
        # 2. Sample daily swipe budget
        # ------------------------------------------------------------------
        budget = ctx.get("daily_swipe_budget")
        if budget is None:
            budget = DAILY_BUDGET_DIST.sample_int(
                account_id=account_id,
                date_iso=date_iso,
                field="swipe_budget",
            )

        # Sample this account's right_ratio for today
        right_ratio = RIGHT_RATIO_DIST.sample(
            account_id=account_id,
            date_iso=date_iso,
            field="right_ratio",
        )
        # Clamp to realistic range
        right_ratio = max(0.05, min(0.50, right_ratio))

        self._audit_event(run, "session_plan", {
            "budget": budget,
            "right_ratio": round(right_ratio, 3),
            "platform": platform,
        })

        # ------------------------------------------------------------------
        # 3. Run platform-specific swipe loop
        # ------------------------------------------------------------------
        swipe_records: list[SwipeRecord] = []

        if platform == "tinder":
            swipe_records = await self._run_tinder(
                session, account_id, date_iso, budget, right_ratio, run
            )
        elif platform == "bumble":
            swipe_records = await self._run_bumble(
                session, account_id, date_iso, budget, right_ratio, run
            )
        elif platform == "hinge":
            swipe_records = await self._run_hinge(
                session, account_id, date_iso, budget, right_ratio, run
            )
        else:
            log.error("DatingSwipeAgent: unsupported platform %r", platform)

        # ------------------------------------------------------------------
        # 4. Persist swipe records
        # ------------------------------------------------------------------
        if swipe_records:
            await self.tool("db.save_swipe_records", swipe_records)

        run.outputs.update({
            "swipes_executed": len(swipe_records),
            "likes":  sum(1 for r in swipe_records if r.action == "like"),
            "passes": sum(1 for r in swipe_records if r.action == "pass"),
        })
        return True

    # ------------------------------------------------------------------
    # Platform-specific loops
    # ------------------------------------------------------------------

    async def _run_tinder(
        self,
        session: TinderSession,
        account_id: str,
        date_iso: str,
        budget: int,
        right_ratio: float,
        run: AgentRun,
    ) -> list[SwipeRecord]:
        records: list[SwipeRecord] = []
        remaining = budget

        async with TinderClient(session) as client:
            while remaining > 0:
                batch_size = min(10, remaining)
                try:
                    resp = await client.get_recs(count=batch_size)
                except TinderSessionExpired:
                    log.warning("Tinder session expired for %s", account_id)
                    break
                except TinderRateLimited as e:
                    log.warning("Tinder rate limited for %s; backing off", account_id)
                    await asyncio.sleep(min(e.retry_after, 120))
                    break

                profiles = resp.get("data", {}).get("results", [])
                if not profiles:
                    break

                for profile in profiles:
                    if remaining <= 0:
                        break

                    user = profile.get("user", {})
                    target_id  = user.get("_id", "")
                    s_number   = profile.get("s_number", 0)
                    photos     = user.get("photos", [])
                    photo_id   = photos[0].get("id", "") if photos else ""

                    if not target_id:
                        continue

                    # Dwell before deciding
                    dwell_s = DWELL_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"dwell_{target_id}",
                    )
                    await asyncio.sleep(dwell_s)

                    # Decide like/pass
                    rng = _rng_from_seed(
                        seed_for(account_id, date_iso, f"right_{target_id}")
                    )
                    action: Literal["like", "pass"] = (
                        "like" if rng.random() < right_ratio else "pass"
                    )

                    self._audit_event(run, "swipe", {
                        "target_id": target_id,
                        "action": action,
                        "platform": "tinder",
                    })

                    try:
                        if action == "like":
                            result = await client.swipe_like(target_id, s_number, photo_id)
                        else:
                            result = await client.swipe_pass(target_id, s_number)
                    except TinderActionBlocked:
                        log.warning("Tinder action blocked for %s", account_id)
                        break
                    except TinderSessionExpired:
                        break
                    except TinderRateLimited as e:
                        await asyncio.sleep(min(e.retry_after, 120))
                        break

                    records.append(SwipeRecord(
                        account_id=account_id,
                        platform="tinder",
                        target_id=target_id,
                        action=action,
                        comment=None,
                        dwell_ms=int(dwell_s * 1000),
                        ts=datetime.now(timezone.utc).isoformat(),
                        result=result,
                    ))
                    remaining -= 1

                    # Inter-swipe pause
                    pause = INTER_SWIPE_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"pause_{target_id}",
                    )
                    await asyncio.sleep(pause)

        return records

    async def _run_bumble(
        self,
        session: BumbleSession,
        account_id: str,
        date_iso: str,
        budget: int,
        right_ratio: float,
        run: AgentRun,
    ) -> list[SwipeRecord]:
        records: list[SwipeRecord] = []
        remaining = budget

        async with BumbleClient(session) as client:
            while remaining > 0:
                try:
                    resp = await client.get_encounters()
                except BumbleSessionExpired:
                    log.warning("Bumble session expired for %s", account_id)
                    break
                except BumbleRateLimited as e:
                    log.warning("Bumble rate limited for %s", account_id)
                    await asyncio.sleep(min(e.retry_after, 120))
                    break

                # Bumble returns encounters in a nested structure
                results = resp.get("results", [])
                if not results:
                    break

                for enc in results:
                    if remaining <= 0:
                        break

                    user = enc.get("user", enc)
                    target_id = str(user.get("user_id", user.get("uid", "")))
                    if not target_id:
                        continue

                    dwell_s = DWELL_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"dwell_{target_id}",
                    )
                    await asyncio.sleep(dwell_s)

                    rng = _rng_from_seed(
                        seed_for(account_id, date_iso, f"right_{target_id}")
                    )
                    action: Literal["like", "pass"] = (
                        "like" if rng.random() < right_ratio else "pass"
                    )
                    direction = "yes" if action == "like" else "no"

                    self._audit_event(run, "swipe", {
                        "target_id": target_id,
                        "action": action,
                        "platform": "bumble",
                    })

                    try:
                        result = await client.vote(target_id, direction=direction)
                    except BumbleSessionExpired:
                        break
                    except BumbleRateLimited as e:
                        await asyncio.sleep(min(e.retry_after, 120))
                        break

                    records.append(SwipeRecord(
                        account_id=account_id,
                        platform="bumble",
                        target_id=target_id,
                        action=action,
                        comment=None,
                        dwell_ms=int(dwell_s * 1000),
                        ts=datetime.now(timezone.utc).isoformat(),
                        result=result,
                    ))
                    remaining -= 1

                    pause = INTER_SWIPE_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"pause_{target_id}",
                    )
                    await asyncio.sleep(pause)

        return records

    async def _run_hinge(
        self,
        session: HingeSession,
        account_id: str,
        date_iso: str,
        budget: int,
        right_ratio: float,
        run: AgentRun,
    ) -> list[SwipeRecord]:
        records: list[SwipeRecord] = []
        remaining = budget

        async with HingeClient(session) as client:
            while remaining > 0:
                try:
                    resp = await client.get_discover()
                except HingeSessionExpired:
                    log.warning("Hinge session expired for %s", account_id)
                    break
                except HingeVerificationRequired:
                    log.warning(
                        "Hinge verification required for %s — pausing swipe session",
                        account_id,
                    )
                    run.outputs["verification_required"] = True
                    break
                except HingeRateLimited as e:
                    log.warning("Hinge rate limited for %s", account_id)
                    await asyncio.sleep(min(e.retry_after, 120))
                    break

                profiles = resp.get("subjects", resp.get("profiles", []))
                if not profiles:
                    break

                for profile in profiles:
                    if remaining <= 0:
                        break

                    target_id = str(profile.get("subject_id", profile.get("id", "")))
                    if not target_id:
                        continue

                    # Hinge: pick the first content item to like
                    content_items = profile.get("content", [])
                    content_id = (
                        str(content_items[0].get("id", "")) if content_items else ""
                    )
                    if not content_id:
                        continue

                    dwell_s = DWELL_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"dwell_{target_id}",
                    )
                    await asyncio.sleep(dwell_s)

                    rng = _rng_from_seed(
                        seed_for(account_id, date_iso, f"right_{target_id}")
                    )
                    action: Literal["like", "pass"] = (
                        "like" if rng.random() < right_ratio else "pass"
                    )

                    comment: Optional[str] = None
                    if action == "like" and _should_comment(account_id, target_id, content_id):
                        comment = _hinge_comment_for(account_id, target_id, content_id)

                    self._audit_event(run, "swipe", {
                        "target_id": target_id,
                        "content_id": content_id,
                        "action": action,
                        "has_comment": comment is not None,
                        "platform": "hinge",
                    })

                    try:
                        if action == "like":
                            result = await client.like_content(
                                target_id, content_id, comment=comment
                            )
                        else:
                            result = await client.pass_profile(target_id)
                    except HingeVerificationRequired:
                        run.outputs["verification_required"] = True
                        break
                    except HingeSessionExpired:
                        break
                    except HingeRateLimited as e:
                        await asyncio.sleep(min(e.retry_after, 120))
                        break

                    records.append(SwipeRecord(
                        account_id=account_id,
                        platform="hinge",
                        target_id=target_id,
                        action=action,
                        comment=comment,
                        dwell_ms=int(dwell_s * 1000),
                        ts=datetime.now(timezone.utc).isoformat(),
                        result=result,
                    ))
                    remaining -= 1

                    pause = INTER_SWIPE_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"pause_{target_id}",
                    )
                    await asyncio.sleep(pause)

        return records

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _audit_event(self, run: AgentRun, event_type: str, data: dict) -> None:
        event = {
            "event": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": self.config.name,
            **data,
        }
        run.audit_events.append(event)
        self.audit_sink(event)
