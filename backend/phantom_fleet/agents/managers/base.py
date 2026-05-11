"""
ManagerAgent base class.

A ManagerAgent supervises a set of specialist agents. Unlike a specialist
agent that takes a specific action, a manager reasons over state, schedules
specialists, and reports upward to its parent manager.

Every manager enforces the same guardrails a specialist does (tool allowlist,
loop cap, cost cap, confirmation gate, audit log) PLUS a few extra:

  - **Subordinate allowlist**: can only dispatch to agents named in
    `config.supervises`. Prevents one manager from commanding another
    platform's agents.
  - **Strategic state**: persisted per-manager so decisions accumulate
    coherently across runs.
  - **Upward reporting**: every run ends with a report that flows to the
    parent manager (or Chief) via `outputs["report_to_parent"]`.
  - **Escalation gate**: if the manager needs to do something destructive
    or cross-platform, it escalates up the tree instead of acting.

A manager's `run_once` method should:
    1. Load strategic state
    2. Query signals from each supervised agent's recent runs
    3. Decide what to do next cycle (priorities, budgets, pauses)
    4. Dispatch specialist agents with context dicts via self.dispatch()
    5. Persist updated strategic state
    6. Emit a report_to_parent summary
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..base import Agent, AgentConfig, AgentRun

log = logging.getLogger(__name__)


@dataclass
class ManagerConfig(AgentConfig):
    """Manager-specific config — extends AgentConfig with a supervision
    allowlist and a reporting cadence."""

    supervises: tuple[str, ...] = ()  # agent names this manager may dispatch
    escalates_to: str | None = None   # parent manager name (Chief by default)
    report_cadence_min: int = 15      # how often to emit a status report


class ManagerAgent(Agent):
    """Base class for every Phantom Fleet platform agent manager.

    A manager holds *strategic state*: long-lived context about its platform
    (daily budgets, risk posture, cohort priorities, active experiments)
    that specialist agents can't see on their own. The manager is the brain;
    specialists are the hands.
    """

    config: ManagerConfig = ManagerConfig(name="base_manager")

    def __init__(
        self,
        *,
        tool_registry: dict | None = None,
        audit_sink: callable | None = None,
        specialist_registry: dict | None = None,
    ):
        super().__init__(tool_registry=tool_registry, audit_sink=audit_sink)
        # Map of agent_name -> agent instance that this manager can dispatch to.
        # Populated at construction time from a registry; enforced in dispatch().
        self.specialists: dict = specialist_registry or {}
        # Persisted strategic state — loaded from DB on run start, saved on run end.
        self.state: dict[str, Any] = {}

    # -- subordinate allowlist enforcement -------------------------------------

    async def dispatch(self, agent_name: str, ctx: dict) -> AgentRun | None:
        """Dispatch a specialist run. Enforces the supervises allowlist."""
        if agent_name not in self.config.supervises:
            raise RuntimeError(
                f"Manager {self.config.name} cannot dispatch to {agent_name!r}; "
                f"supervises only {self.config.supervises}"
            )
        specialist = self.specialists.get(agent_name)
        if specialist is None:
            log.warning(
                "Manager %s wants to dispatch %s but specialist not registered",
                self.config.name, agent_name,
            )
            return None
        self._audit({
            "event": "manager_dispatch",
            "manager": self.config.name,
            "specialist": agent_name,
            "ctx_keys": list(ctx.keys()),
        })
        return await specialist.run(ctx)

    # -- escalation gate --------------------------------------------------------

    def escalate(self, reason: str, payload: dict) -> None:
        """Write an escalation event. The Chief's next run picks these up."""
        self._audit({
            "event": "escalation",
            "from": self.config.name,
            "to": self.config.escalates_to or "chief",
            "reason": reason,
            "payload": payload,
        })

    # -- upward reporting -------------------------------------------------------

    def report_upward(self, run: AgentRun, summary: dict) -> None:
        """Attach a manager report to run.outputs.

        The Chief's next cycle reads these reports from child managers' audit
        logs and incorporates them into fleet-level strategic decisions.
        """
        run.outputs["report_to_parent"] = {
            "manager": self.config.name,
            "cadence_min": self.config.report_cadence_min,
            "summary": summary,
        }
        self._audit({
            "event": "report_to_parent",
            "to": self.config.escalates_to or "chief",
            "summary_keys": list(summary.keys()),
        })

    # -- subclass contract ------------------------------------------------------

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        raise NotImplementedError
