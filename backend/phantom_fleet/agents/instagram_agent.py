"""
InstagramAgent — wraps every IG dispatch in the CLAUDE.md agent frame.

Mirrors ThreadsAgent: the IG orchestrator used to append actions straight
to `ig_queue`. That skipped every guardrail in CLAUDE.md's agent-audit
section (tool allowlist, iteration cap, cost caps, event-sourced audit,
confirmation gates on destructive actions). This module gives IG that
frame.

Caps (per CLAUDE.md agent-audit rule):
    max_iterations      = 3  (plan+budget+enqueue)
    max_usd_per_run     = 0.05
    max_usd_per_session = 2.00

Allowlist (exactly 5 tools):
    instagram.budget_remaining
    instagram.compose_post
    instagram.compose_action
    instagram.enqueue
    instagram.probe_enqueue

Confirmation-required slots (not called today, wired for future use):
    retire_ig_account, factory_reset_phone
"""
from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .base import Agent, AgentConfig, AgentRun

log = logging.getLogger("phantom_fleet.agents.instagram")


# ---------------------------------------------------------------------------
# IGAgentRunsRing — observability of every IG agent run
# ---------------------------------------------------------------------------


@dataclass
class IGAgentRunRecord:
    run_id:     str
    agent_name: str
    account_id: str
    kind:       str
    status:     str
    iterations: int
    cost_usd:   float
    started_at: str
    ended_at:   Optional[str]
    error:      str
    audit:      list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "run_id":     self.run_id,
            "agent_name": self.agent_name,
            "account_id": self.account_id,
            "kind":       self.kind,
            "status":     self.status,
            "iterations": self.iterations,
            "cost_usd":   round(self.cost_usd, 5),
            "started_at": self.started_at,
            "ended_at":   self.ended_at,
            "error":      self.error,
            "audit":      list(self.audit),
        }


class IGAgentRunsRing:
    """Bounded ring of IG agent runs. 500 entries."""

    def __init__(self, maxlen: int = 500):
        self._runs: deque[IGAgentRunRecord] = deque(maxlen=maxlen)

    def append(self, rec: IGAgentRunRecord) -> None:
        self._runs.append(rec)

    def recent(self, limit: int = 50,
               account_id: Optional[str] = None) -> list[dict]:
        rows: list[dict] = []
        for rec in reversed(self._runs):
            if account_id and rec.account_id != account_id:
                continue
            rows.append(rec.as_dict())
            if len(rows) >= limit:
                break
        return rows

    def summary(self) -> dict:
        total = len(self._runs)
        by_status: dict[str, int] = {}
        total_cost = 0.0
        total_iter = 0
        for r in self._runs:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            total_cost += r.cost_usd
            total_iter += r.iterations
        return {
            "total":      total,
            "by_status":  by_status,
            "total_cost": round(total_cost, 5),
            "avg_iters":  (total_iter / total) if total else 0.0,
        }


# ---------------------------------------------------------------------------
# InstagramAgent — one specialist per IG dispatch
# ---------------------------------------------------------------------------


class InstagramAgent(Agent):
    """One agent per IG dispatch (follow / like / story_view / post)."""

    config = AgentConfig(
        name="instagram",
        max_iterations=3,
        max_usd_per_run=0.05,
        max_usd_per_session=2.00,
        confirmation_required_for=(
            "retire_ig_account",
            "factory_reset_phone",
        ),
        allowed_tools=(
            "instagram.budget_remaining",
            "instagram.compose_post",
            "instagram.compose_action",
            "instagram.enqueue",
            "instagram.probe_enqueue",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id = ctx["account_id"]
        kind = ctx["kind"]

        # Iteration 1: budget check — skip when the account has no remaining
        # budget for this kind today.
        remaining = await self.tool("instagram.budget_remaining",
                                      account_id=account_id, kind=kind)
        if remaining <= 0:
            run.outputs = {"skipped": "no_budget", "kind": kind,
                           "budget_remaining": remaining}
            return True

        # Iteration 2: compose target / body. Post uses its own composer
        # (no target); follow/like/story_view share a simple composer.
        if kind == "post":
            composed = await self.tool("instagram.compose_post",
                                        account_id=account_id, ctx=ctx)
            self.charge_cost(run, 0.001, "compose_post")
        else:
            composed = await self.tool("instagram.compose_action",
                                        account_id=account_id,
                                        kind=kind, ctx=ctx)

        # Iteration 3: enqueue. Probes (if introduced later) take a
        # different path; today everything goes through .enqueue.
        tool = ("instagram.probe_enqueue"
                if ctx.get("source") == "probe"
                else "instagram.enqueue")
        enq = await self.tool(tool,
                               account_id=account_id, kind=kind,
                               target=composed.get("target", ctx.get("target", "")),
                               body=composed.get("body", ctx.get("body", "")),
                               reason=ctx.get("reason", ""),
                               planner=ctx.get("planner", "ig_orchestrator"))
        run.outputs = {"action_id": enq.get("action_id"),
                       "queued": enq.get("queued", False),
                       "kind": kind}
        return True


# ---------------------------------------------------------------------------
# Tool bridge
# ---------------------------------------------------------------------------


def build_tool_registry(
    ig_mod,
    accounts_store_getter: Callable[[], dict],
    queue_getter: Callable[[], list[dict]],
) -> dict[str, Callable]:
    import hashlib

    async def budget_remaining(*, account_id: str, kind: str) -> int:
        row = accounts_store_getter().get(account_id)
        if row is None:
            return 0
        b = ig_mod.budget_for(account_id, int(row.get("warmup_day", 1)))
        day = datetime.now(timezone.utc).date().isoformat()
        used = sum(1 for e in queue_getter()
                   if e.get("account_id") == account_id
                   and e.get("kind") == kind and e.get("date") == day)
        return max(0, getattr(b, kind) - used)

    async def compose_post(*, account_id: str, ctx: dict) -> dict:
        # Composer is deterministic and seeded; ModelForge plugs in later.
        return {"target": "", "body": ctx.get("body", "")}

    async def compose_action(*, account_id: str, kind: str, ctx: dict) -> dict:
        target = ctx.get("target", "")
        if not target:
            seed = f"ig:{account_id}:{kind}:compose"
            idx = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
            if kind == "story_view":
                target = f"story://account_{(idx % 11) + 1}"
            elif kind == "like":
                target = f"ig://post_{(idx % 17) + 1}"
            else:  # follow
                target = f"@fresh_target_{(idx % 13) + 1}"
        return {"target": target, "body": ""}

    def _enqueue(entry_tag: str) -> Callable:
        async def _inner(*, account_id: str, kind: str, target: str,
                         body: str, reason: str, planner: str) -> dict:
            now = datetime.now(timezone.utc)
            action_id = f"ig-{uuid.uuid4().hex[:12]}"
            queue_getter().append({
                "action_id":  action_id,
                "account_id": account_id,
                "kind":       kind,
                "target":     target,
                "body":       body,
                "route":      ig_mod.ACTION_ROUTES[kind],
                "date":       now.date().isoformat(),
                "queued_at":  now.isoformat(),
                "status":     "queued",
                "planner":    planner,
                "reason":     reason,
                "via":        entry_tag,
            })
            return {"action_id": action_id, "queued": True}
        return _inner

    return {
        "instagram.budget_remaining": budget_remaining,
        "instagram.compose_post":     compose_post,
        "instagram.compose_action":   compose_action,
        "instagram.enqueue":          _enqueue("ig_orchestrator_agent"),
        "instagram.probe_enqueue":    _enqueue("ig_probe_agent"),
    }


# ---------------------------------------------------------------------------
# Convenience: run one dispatch end-to-end + append to the ring
# ---------------------------------------------------------------------------


async def dispatch_one(
    agent: InstagramAgent,
    ring:  IGAgentRunsRing,
    ctx:   dict,
) -> IGAgentRunRecord:
    collected: list[dict] = []
    original_sink = agent.audit_sink
    agent.audit_sink = lambda e: (collected.append(e) or original_sink(e))
    try:
        run = await agent.run(ctx)
    finally:
        agent.audit_sink = original_sink
    rec = IGAgentRunRecord(
        run_id=run.run_id,
        agent_name=run.agent_name,
        account_id=ctx.get("account_id", "?"),
        kind=ctx.get("kind", "?"),
        status=run.status,
        iterations=run.iterations,
        cost_usd=run.cost_usd,
        started_at=run.started_at.isoformat(),
        ended_at=run.ended_at.isoformat() if run.ended_at else None,
        error=run.error,
        audit=collected,
    )
    ring.append(rec)
    return rec
