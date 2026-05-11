"""
ChiefAgentManager — the fleet conductor.

Sits at the top of the hierarchy. The Chief does NOT touch specialist agents
directly — it only talks to the other managers (infrastructure, instagram,
threads, reddit, x, tiktok, dating, funnel). Its job is cross-platform
strategic coordination:

  - Unified daily budget distribution across platforms
  - Cross-platform persona coherence checks
  - Global risk posture (if IG is blocking heavy, slow everything down)
  - Multi-platform funnel prioritization (which platforms drive conversions?)
  - Escalation resolution (manager escalates → Chief decides)
  - Fleet-wide audit harness gating

The Chief is the ONLY agent authorized to issue cross-platform directives
like "pause Tatiana on every platform" or "promote Melodie on TikTok because
her IG conversion rate is top 5%." All such directives are audit-logged.

If Phantom Fleet had a CEO, this would be it.
"""
from __future__ import annotations

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class ChiefAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="chief",
        max_iterations=8,
        max_usd_per_run=1.00,
        max_usd_per_session=20.00,
        confirmation_required_for=(
            "pause_all_platforms",
            "emergency_fleet_shutdown",
            "mass_replacement",
        ),
        allowed_tools=(
            "db.load_fleet_state",
            "db.load_manager_reports",
            "db.save_fleet_directive",
            "db.load_cross_platform_funnel",
            "notifier.alert",
            "llm.strategic_decision",
        ),
        supervises=(
            "infrastructure", "instagram", "threads", "reddit",
            "x", "tiktok", "dating", "funnel",
        ),
        escalates_to=None,   # the Chief has no parent
        report_cadence_min=60,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        # 1. Pull all platform manager reports from the last cycle
        reports = await self.tool("db.load_manager_reports", minutes=60)

        # 2. Pull cross-platform funnel data (which platform drives conversions)
        funnel = await self.tool("db.load_cross_platform_funnel", days=7)

        # 3. Pull global risk posture from infrastructure + audit harness
        fleet_state = await self.tool("db.load_fleet_state")

        # 4. Strategic decision — high-level, low-frequency.
        # The LLM call here is where the Chief "thinks". It gets a full
        # fleet summary and returns a JSON directive that gets dispatched
        # to specific managers.
        directive = await self.tool(
            "llm.strategic_decision",
            reports=reports,
            funnel=funnel,
            fleet_state=fleet_state,
            current_risk_posture=self.state.get("risk_posture", "normal"),
        )
        self.charge_cost(run, 0.20, "chief_strategic_decision")

        # 5. Persist the new fleet directive
        await self.tool("db.save_fleet_directive", directive)

        # 6. Dispatch into each platform manager with directive slices
        for manager_name in self.config.supervises:
            if manager_name not in directive.get("per_manager", {}):
                continue
            manager_ctx = directive["per_manager"][manager_name]
            try:
                await self.dispatch(manager_name, manager_ctx)
            except Exception as e:
                self._audit({"event": "dispatch_failed",
                             "manager": manager_name, "error": str(e)[:200]})

        # 7. Update state + self-report (no parent to report to)
        self.state["risk_posture"] = directive.get("risk_posture", "normal")
        self.state["last_directive_ts"] = directive.get("ts")

        run.audit_events.append({
            "reports_consumed": len(reports),
            "managers_dispatched": len(directive.get("per_manager", {})),
            "risk_posture": self.state["risk_posture"],
        })
        return True
