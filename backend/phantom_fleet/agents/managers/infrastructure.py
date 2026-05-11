"""
InfrastructureAgentManager — runs the always-on fleet safety layer.

Owns:
    - ProxyOrchestratorAgent
    - FingerprintMonitorAgent
    - RecoveryAgent
    - ReplacementAgent
    - AuditHarnessAgent

Responsibilities:
    - Keep the fleet alive (proxy rotation, phone recovery, account replacement)
    - Catch clustering BEFORE platform managers burn accounts
    - Escalate emergency conditions to the Chief (ban waves, proxy outages)
    - Enforce the global safety gate: if audit harness fails, pause all platform managers
"""
from __future__ import annotations

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class InfrastructureAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="infrastructure",
        max_iterations=20,
        max_usd_per_run=0.05,
        max_usd_per_session=1.00,
        confirmation_required_for=("pause_all_cohorts",),
        allowed_tools=(
            "db.load_fleet_health",
            "db.load_active_alerts",
            "db.save_infrastructure_state",
            "notifier.alert",
        ),
        supervises=(
            "proxy_orchestrator",
            "fingerprint_monitor",
            "recovery",
            "replacement",
            "audit_harness",
        ),
        escalates_to="chief",
        report_cadence_min=5,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        health = await self.tool("db.load_fleet_health")
        alerts = await self.tool("db.load_active_alerts")

        # Kick the fingerprint monitor every cycle (5 min default)
        await self.dispatch("fingerprint_monitor", {})

        # Audit harness runs less often — only on demand or schedule
        if ctx.get("run_audit_harness"):
            await self.dispatch("audit_harness", {})

        # Recovery dispatches: one per phone showing crash/lost signal
        for phone in health.get("phones_needing_recovery", []):
            await self.dispatch("recovery", {
                "phone_serial": phone["serial"],
                "symptom": phone["symptom"],
                "account_id": phone.get("account_id"),
            })

        # Replacement dispatches: one per dead account
        for dead in health.get("dead_accounts", []):
            await self.dispatch("replacement", {
                "dead_account_id": dead["id"],
                "persona_id": dead["persona_id"],
                "reason": dead["reason"],
            })

        # Escalate ban waves to the Chief — they warrant cross-platform pauses
        critical = [a for a in alerts if a.get("severity") == "critical"]
        if len(critical) >= 3:
            self.escalate("critical_alert_surge", {
                "critical_count": len(critical),
                "alerts": critical[:10],
            })

        self.report_upward(run, {
            "phones_online": health.get("phones_online", 0),
            "phones_recovering": len(health.get("phones_needing_recovery", [])),
            "dead_accounts_24h": len(health.get("dead_accounts", [])),
            "critical_alerts": len(critical),
            "cluster_status": health.get("cluster_status", "clean"),
        })
        return True
