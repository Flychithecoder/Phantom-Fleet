"""
FunnelAgentManager — owns cross-platform growth strategy + conversion attribution.

This is the meta-manager that runs everything downstream of the
per-platform managers: content creation, conversion tracking, persona
generation, and growth strategy reweighting.

Owns:
    - ContentAgent (cross-platform content generation)
    - FunnelConversionAgent (attribution pipeline)
    - GrowthStrategyAgent (weekly KPI review + reweight sources)
    - PersonaFactoryAgent (on-demand persona generation)

Strategic decisions:
    1. Which personas should scale UP this week?
    2. Which sources are producing converting followers?
    3. Which content formats drive conversions fastest?
    4. When to generate a new persona to fill a gap?
    5. When to retire a persona that's not earning its phone slots?
"""
from __future__ import annotations

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class FunnelAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="funnel",
        max_iterations=10,
        max_usd_per_run=0.25,
        max_usd_per_session=4.00,
        confirmation_required_for=("retire_persona", "create_persona"),
        allowed_tools=(
            "db.load_persona_kpis",
            "db.load_cross_platform_funnel",
            "db.load_content_performance",
            "db.save_funnel_strategy_state",
            "llm.decide_funnel_strategy",
        ),
        supervises=(
            "content",
            "funnel_conversion",
            "growth_strategy",
            "persona_factory",
            "content_scout",
        ),
        escalates_to="chief",
        report_cadence_min=60,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        kpis = await self.tool("db.load_persona_kpis")
        funnel = await self.tool("db.load_cross_platform_funnel", days=7)
        content_perf = await self.tool("db.load_content_performance")

        decision = await self.tool(
            "llm.decide_funnel_strategy",
            kpis=kpis,
            funnel=funnel,
            content_perf=content_perf,
            current_state=self.state,
        )
        self.charge_cost(run, 0.05, "funnel_daily_decision")

        # 1. Attribution — resolve recent conversions back to source account/persona
        await self.dispatch("funnel_conversion", {"days": 1})

        # 2. Growth strategy weekly review (only runs Mondays)
        if ctx.get("is_weekly"):
            for persona_id in (p["id"] for p in kpis):
                await self.dispatch("growth_strategy", {"persona_id": persona_id})

        # 3. Content scouting per persona
        for persona_id in decision.get("content_scout_personas", []):
            await self.dispatch("content_scout", {
                "niche": decision.get("niche_by_persona", {}).get(persona_id, "general"),
                "persona_id": persona_id,
            })

        # 4. Persona factory — create new persona if the fleet has a gap
        if decision.get("create_persona"):
            await self.dispatch("persona_factory", decision["create_persona"])

        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_funnel_strategy_state", self.state)

        self.report_upward(run, {
            "personas_tracked": len(kpis),
            "funnel_revenue_7d": funnel.get("revenue_7d", 0),
            "top_performing_persona": decision.get("top_performer"),
            "recommended_promote": decision.get("promote_persona"),
            "recommended_retire": decision.get("retire_persona"),
        })
        return True
