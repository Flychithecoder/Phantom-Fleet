"""
GrowthStrategyAgent — weekly KPI review.

Every Monday, reviews last week's KPIs per account:
    - Follower growth rate
    - Post reach
    - Story views
    - DM response rate
    - Fan-to-OF conversion rate
Then adjusts:
    - Target source weights (promote high-FBR sources)
    - Action pacing (slow down under-performers)
    - Persona aggressiveness micro-tuning
    - Whale promotion (top converters get premium proxy/content priority)
"""
from __future__ import annotations

from .base import Agent, AgentConfig, AgentRun


class GrowthStrategyAgent(Agent):
    config = AgentConfig(
        name="growth_strategy",
        max_iterations=10,
        max_usd_per_run=0.25,
        max_usd_per_session=2.00,
        allowed_tools=(
            "db.load_weekly_kpis",
            "db.load_source_performance",
            "db.update_source_weight",
            "db.promote_account_to_whale",
            "llm.analyze_growth_trends",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        persona_id = ctx["persona_id"]
        kpis = await self.tool("db.load_weekly_kpis", persona_id)
        source_perf = await self.tool("db.load_source_performance", persona_id)

        # Promote top 5% FBR sources, demote bottom 10%
        top_sources = sorted(source_perf, key=lambda s: s["fbr"], reverse=True)[: max(1, len(source_perf) // 20)]
        bottom_sources = sorted(source_perf, key=lambda s: s["fbr"])[: max(1, len(source_perf) // 10)]
        for s in top_sources:
            await self.tool("db.update_source_weight", s["id"], delta=+0.2)
        for s in bottom_sources:
            await self.tool("db.update_source_weight", s["id"], delta=-0.3)

        # Whale promotion: any account above fleet-avg conversion rate
        if kpis:
            fleet_avg_conv = sum(k["conversion_rate"] for k in kpis) / max(1, len(kpis))
            for k in kpis:
                if k["conversion_rate"] > fleet_avg_conv * 1.5:
                    await self.tool("db.promote_account_to_whale", k["account_id"])

        run.audit_events.append({
            "persona": persona_id,
            "top_sources_boosted": len(top_sources),
            "bottom_sources_cut": len(bottom_sources),
        })
        return True
