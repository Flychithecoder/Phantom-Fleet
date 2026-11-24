"""
ThreadsAgent — wraps every Threads dispatch in the CLAUDE.md agent frame.

Up to this point the Threads orchestrator appended actions straight onto a
shared queue and the executor drained them. That works but it skips every
guardrail the global CLAUDE.md agent-audit section requires:

    > Each agent has: a named tool allowlist, a hard iteration cap
    > (≤5 typical, ≤20 absolute max), a per-run cost cap, a per-session
    > cost cap, a per-user cost cap.
    >
    > Destructive actions ... require confirmation gates in code, not
    > just in prompt.
    >
    > Every agent action writes to an event-sourced audit log before
    > execution, and writes the result after.

This module gives Threads actions that frame. ThreadsAgent has:
    * an allowlist of exactly the five tools dispatch needs
      (`threads.compose_reply`, `threads.compose_post`, `threads.budget_remaining`,
       `threads.enqueue`, `threads.ig_bridge_enqueue`)
    * max_iterations = 3 (plan+budget+enqueue — anything more is a bug)
    * max_usd_per_run = 0.05, max_usd_per_session = 2.00
    * `confirmation_required_for = ("retire_account", "factory_reset_phone")`
      — these aren't actions the planner takes today, but the slots are
      wired so any later code that does need them is gated in CODE, not in
      prompt
    * an audit_sink wired to the AgentRunsRing below so each run is
      inspectable by the UI without touching the agent class itself

Orchestrator calls `ThreadsAgent.run()` once per planned action instead of
appending to the queue directly. That means the four guardrails run on
every dispatch and the audit ring records every tool call made on this
account's behalf. If an enqueue needs to be routed differently later (via
NATS, through a mesh proxy, under test-mode mocks), the agent is the
single cutpoint.
"""
from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .base import Agent, AgentConfig, AgentRun

log = logging.getLogger("phantom_fleet.agents.threads")


# ---------------------------------------------------------------------------
# AgentRunsRing — observability of every Threads agent run
# ---------------------------------------------------------------------------


@dataclass
class AgentRunRecord:
    run_id:      str
    agent_name:  str
    account_id:  str
    kind:        str
    status:      str
    iterations:  int
    cost_usd:    float
    started_at:  str
    ended_at:    Optional[str]
    error:       str
    audit:       list[dict] = field(default_factory=list)

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


class AgentRunsRing:
    """
    Bounded ring of agent runs. Writes are O(1), reads are O(N<=200).
    The UI polls this; the Audit harness samples it for distribution checks
    on cost + iteration counts.
    """

    def __init__(self, maxlen: int = 500):
        self._runs: deque[AgentRunRecord] = deque(maxlen=maxlen)

    def append(self, rec: AgentRunRecord) -> None:
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
# ThreadsAgent — single specialist that runs one Threads dispatch
# ---------------------------------------------------------------------------


class ThreadsAgent(Agent):
    """
    One agent that handles every Threads dispatch kind (post / reply /
    repost / follow). Each call to run() is a SINGLE dispatch — this is
    deliberately small so iterations stay ≤ 3 even under retries.
    """

    config = AgentConfig(
        name="threads",
        max_iterations=3,
        max_usd_per_run=0.05,
        max_usd_per_session=2.00,
        confirmation_required_for=(
            "retire_account",            # future: hard-stop a Threads account
            "factory_reset_phone",       # future: destructive, per CLAUDE.md
        ),
        allowed_tools=(
            "threads.budget_remaining",
            "threads.compose_reply",
            "threads.compose_post",
            "threads.enqueue",
            "threads.ig_bridge_enqueue",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id = ctx["account_id"]
        kind = ctx["kind"]

        # Iteration 1: check budget. Don't eat run cost on a no-budget action.
        remaining = await self.tool("threads.budget_remaining",
                                      account_id=account_id, kind=kind)
        if remaining <= 0:
            run.outputs = {"skipped": "no_budget", "kind": kind,
                           "budget_remaining": remaining}
            return True

        # Iteration 2: compose body / target.
        if kind in ("reply", "post"):
            tool_name = ("threads.compose_reply" if kind == "reply"
                         else "threads.compose_post")
            composed = await self.tool(tool_name,
                                        account_id=account_id,
                                        ctx=ctx)
            self.charge_cost(run, 0.001, f"compose_{kind}")
        else:
            composed = {"target": ctx.get("target", ""), "body": ""}

        # Iteration 3: enqueue. Separate path for IG-bridge replies so the
        # orchestrator can route them without duplicating code here.
        tool = ("threads.ig_bridge_enqueue"
                if ctx.get("source") == "ig_bridge"
                else "threads.enqueue")
        enq = await self.tool(tool,
                               account_id=account_id, kind=kind,
                               target=composed.get("target", ctx.get("target", "")),
                               body=composed.get("body", ctx.get("body", "")),
                               reason=ctx.get("reason", ""),
                               planner=ctx.get("planner", "orchestrator"))
        run.outputs = {"action_id": enq.get("action_id"),
                       "queued": enq.get("queued", False),
                       "kind": kind}
        return True


# ---------------------------------------------------------------------------
# Tool bridge — maps the agent's allowlist to concrete callables
# ---------------------------------------------------------------------------


def build_tool_registry(
    threads_mod,
    accounts_store_getter: Callable[[], dict],
    queue_getter: Callable[[], list[dict]],
) -> dict[str, Callable]:
    """
    Return a dict of {tool_name: async_callable} for the ThreadsAgent.
    All tools are read/write on the in-memory accounts store + queue, so
    they inherit the write-through to Postgres via the funnel/health
    repos already wired on the state.
    """
    async def budget_remaining(*, account_id: str, kind: str) -> int:
        row = accounts_store_getter().get(account_id)
        if row is None:
            return 0
        b = threads_mod.budget_for(account_id, int(row.get("warmup_day", 1)))
        day = datetime.now(timezone.utc).date().isoformat()
        used = sum(1 for e in queue_getter()
                   if e.get("account_id") == account_id
                   and e.get("kind") == kind and e.get("date") == day)
        return max(0, getattr(b, kind) - used)

    async def compose_reply(*, account_id: str, ctx: dict) -> dict:
        # Compose is deterministic and seeded — this is where ModelForge
        # will be swapped in later. For now, pass through the seeded body.
        return {"target": ctx.get("target", ""), "body": ctx.get("body", "")}

    async def compose_post(*, account_id: str, ctx: dict) -> dict:
        return {"target": "", "body": ctx.get("body", "")}

    def _enqueue(entry_tag: str) -> Callable:
        async def _inner(*, account_id: str, kind: str, target: str,
                         body: str, reason: str, planner: str) -> dict:
            now = datetime.now(timezone.utc)
            action_id = f"th-{uuid.uuid4().hex[:12]}"
            queue_getter().append({
                "action_id":  action_id,
                "account_id": account_id,
                "kind":       kind,
                "target":     target,
                "body":       body,
                "route":      threads_mod.ACTION_ROUTES[kind],
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
        "threads.budget_remaining":   budget_remaining,
        "threads.compose_reply":      compose_reply,
        "threads.compose_post":       compose_post,
        "threads.enqueue":            _enqueue("orchestrator_agent"),
        "threads.ig_bridge_enqueue":  _enqueue("ig_bridge_agent"),
    }


# ---------------------------------------------------------------------------
# Convenience: run one dispatch end-to-end + append to the ring
# ---------------------------------------------------------------------------


async def dispatch_one(
    agent: ThreadsAgent,
    ring:  AgentRunsRing,
    ctx:   dict,
) -> AgentRunRecord:
    collected: list[dict] = []
    original_sink = agent.audit_sink
    agent.audit_sink = lambda e: (collected.append(e) or original_sink(e))
    try:
        run = await agent.run(ctx)
    finally:
        agent.audit_sink = original_sink
    rec = AgentRunRecord(
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
