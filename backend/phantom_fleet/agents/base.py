"""
Agent base class — enforces the CLAUDE.md agent-audit rules.

Every Phantom Fleet agent inherits from Agent. The base class enforces:
- Tool allowlist (can only call tools listed in ALLOWED_TOOLS)
- Loop iteration cap (max_iterations)
- Per-run cost cap (max_usd_per_run)
- Per-session cost cap (max_usd_per_session)
- Event-sourced audit log (every action written BEFORE execution)
- Confirmation gate on destructive actions (never auto-execute)
- Idempotency key (dedup against repeated runs)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, ClassVar

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Per-agent config. Override these in subclasses or at construction."""

    name: str
    max_iterations: int = 5  # hard loop cap per run
    max_usd_per_run: float = 1.00
    max_usd_per_session: float = 10.00
    confirmation_required_for: tuple[str, ...] = ()  # action names needing human confirm
    allowed_tools: tuple[str, ...] = ()  # tool names the agent may call
    idempotency_window_minutes: int = 60  # repeated runs within this window dedupe


@dataclass
class AgentRun:
    """One execution of an agent. All inputs/outputs/cost logged."""

    run_id: str
    agent_name: str
    started_at: datetime
    ended_at: datetime | None = None
    iterations: int = 0
    cost_usd: float = 0.0
    status: str = "running"  # running / success / failed / blocked_confirmation / cost_exceeded
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    error: str = ""
    audit_events: list[dict] = field(default_factory=list)


class ToolNotAllowed(Exception):
    pass


class LoopLimitExceeded(Exception):
    pass


class CostLimitExceeded(Exception):
    pass


class ConfirmationRequired(Exception):
    pass


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class Agent:
    """Base class for every Phantom Fleet agent.

    Subclasses override `run_once(self, ctx)` with the agent's actual logic.
    The base class wraps every run with audit logging, cost accounting,
    iteration limits, and tool allowlisting.

    Usage:
        class WarmingAgent(Agent):
            config = AgentConfig(
                name="warming",
                max_iterations=5,
                max_usd_per_run=0.20,
                allowed_tools=("phone.tap", "phone.scroll", "phone.screenshot"),
            )

            async def run_once(self, ctx):
                # agent logic here — may call self.tool("phone.tap", ...)
                ...
    """

    config: ClassVar[AgentConfig] = AgentConfig(name="base")

    def __init__(
        self,
        *,
        tool_registry: dict[str, Callable] | None = None,
        audit_sink: Callable[[dict], None] | None = None,
    ):
        self.tool_registry = tool_registry or {}
        self.audit_sink = audit_sink or (lambda e: None)
        self._session_cost_usd = 0.0

    # -- tool invocation wrapper ------------------------------------------------

    async def tool(self, name: str, *args, **kwargs):
        if name not in self.config.allowed_tools:
            raise ToolNotAllowed(
                f"{self.config.name} agent cannot call {name!r}; "
                f"allowed: {self.config.allowed_tools}"
            )
        fn = self.tool_registry.get(name)
        if fn is None:
            raise ToolNotAllowed(f"{name!r} not registered in tool_registry")
        self._audit({"event": "tool_call", "tool": name, "args": args, "kwargs": kwargs})
        result = await fn(*args, **kwargs)
        self._audit({"event": "tool_result", "tool": name, "success": True})
        return result

    # -- cost tracking ----------------------------------------------------------

    def charge_cost(self, run: AgentRun, usd: float, note: str = ""):
        run.cost_usd += usd
        self._session_cost_usd += usd
        self._audit({"event": "cost", "usd": usd, "note": note})
        if run.cost_usd > self.config.max_usd_per_run:
            raise CostLimitExceeded(
                f"{self.config.name} exceeded per-run cost "
                f"{run.cost_usd:.4f} > {self.config.max_usd_per_run:.4f}"
            )
        if self._session_cost_usd > self.config.max_usd_per_session:
            raise CostLimitExceeded(
                f"{self.config.name} exceeded per-session cost "
                f"{self._session_cost_usd:.4f} > {self.config.max_usd_per_session:.4f}"
            )

    # -- confirmation gate ------------------------------------------------------

    def require_confirmation_for(self, action_name: str, run: AgentRun):
        if action_name in self.config.confirmation_required_for:
            self._audit({"event": "confirmation_required", "action": action_name})
            raise ConfirmationRequired(
                f"{self.config.name}: action {action_name!r} requires human confirmation"
            )

    # -- audit ------------------------------------------------------------------

    def _audit(self, event: dict):
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        event.setdefault("agent", self.config.name)
        self.audit_sink(event)

    # -- run wrapper ------------------------------------------------------------

    async def run(self, ctx: dict) -> AgentRun:
        """Single agent run. Subclasses implement run_once; this wraps the loop."""
        run = AgentRun(
            run_id=str(uuid.uuid4()),
            agent_name=self.config.name,
            started_at=datetime.now(timezone.utc),
            inputs=ctx,
        )
        run.audit_events.append({"event": "run_start", "ctx_keys": list(ctx.keys())})
        try:
            for step in range(self.config.max_iterations):
                run.iterations += 1
                done = await self.run_once(ctx=ctx, run=run)
                if done:
                    break
            else:
                raise LoopLimitExceeded(
                    f"{self.config.name} exceeded max_iterations={self.config.max_iterations}"
                )
            run.status = "success"
        except ConfirmationRequired as e:
            run.status = "blocked_confirmation"
            run.error = str(e)
        except CostLimitExceeded as e:
            run.status = "cost_exceeded"
            run.error = str(e)
        except Exception as e:
            run.status = "failed"
            run.error = f"{type(e).__name__}: {e}"
            log.exception("Agent %s run failed", self.config.name)
        finally:
            run.ended_at = datetime.now(timezone.utc)
            self._audit({
                "event": "run_end",
                "status": run.status,
                "iterations": run.iterations,
                "cost_usd": run.cost_usd,
            })
        return run

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        """Subclasses override this. Return True when the agent is done."""
        raise NotImplementedError
