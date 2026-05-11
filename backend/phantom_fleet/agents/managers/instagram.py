"""
InstagramAgentManager — runs the Instagram platform autonomously.

Owns:
    - WarmingAgent (IG cohort)
    - FreshTargetAgent (IG)
    - SourceDiscoveryAgent (IG)
    - DMAgent (IG)
    - ContentAgent (IG)
    - AccountSetupAgent (IG)
    - IGHashtagTrackerAgent (optimization — weekly hashtag rotation)
    - IGBioABAgent          (optimization — bio A/B testing)
    - IGPeakTimeAgent       (optimization — per-account peak time learning)

Strategic decisions this manager makes:
    1. Daily budget split: how many actions per cohort (whale / established / volume / warming)
    2. Source pool tier promotion: when to promote approved→premium, retire low-performers
    3. Content mix: ratio of grid posts, reels, stories, close-friend stories
    4. DM budget: how many accounts in each persona get DM duty today
    5. Warming cohort throttle: when to promote re-wake → steady state
    6. Cross-field anomaly pause: if two fingerprint dims look suspicious, pause that cohort
    7. Funnel tuning: which personas get amplified based on conversion ROI
    8. Hashtag rotation: weekly, retire bottom 25%, promote top 25%, introduce 25% fresh
    9. Bio A/B tests: launch tests on cohorts, declare winner after test_days, roll out
    10. Peak time updates: weekly re-analysis of per-account engagement history

Escalates to Chief when:
    - Cross-platform coherence needed (e.g. same persona's Threads needs adjustment)
    - Fleet-wide risk posture changed
    - Mass replacement required
"""
from __future__ import annotations

from datetime import date

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class InstagramAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="instagram",
        max_iterations=12,
        max_usd_per_run=0.25,
        max_usd_per_session=4.00,
        confirmation_required_for=("pause_persona", "mass_account_import"),
        allowed_tools=(
            "db.load_ig_accounts",
            "db.load_ig_personas",
            "db.load_ig_health_signals",
            "db.load_source_pool_stats",
            "db.load_funnel_by_persona",
            "db.save_ig_strategy_state",
            "db.load_ig_hashtag_sidecars",
            "db.save_ig_hashtag_sidecars",
            "db.load_ig_ab_test_specs",
            "db.save_ig_ab_test_specs",
            "db.load_ig_peak_profiles",
            "db.save_ig_peak_profiles",
            "llm.decide_daily_budget",
        ),
        supervises=(
            "warming",
            "fresh_target",
            "source_discovery",
            "dm",
            "content",
            "account_setup",
            "ig_hashtag_tracker",
            "ig_bio_ab",
            "ig_peak_time",
        ),
        escalates_to="chief",
        report_cadence_min=10,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        personas = await self.tool("db.load_ig_personas")
        health = await self.tool("db.load_ig_health_signals")
        source_stats = await self.tool("db.load_source_pool_stats", platform="instagram")
        funnel = await self.tool("db.load_funnel_by_persona", days=7, platform="instagram")

        # LLM-driven daily decision: what should each specialist do today?
        decision = await self.tool(
            "llm.decide_daily_budget",
            platform="instagram",
            personas=personas,
            health=health,
            source_stats=source_stats,
            funnel=funnel,
            current_state=self.state,
        )
        self.charge_cost(run, 0.05, "ig_daily_decision")

        today = date.today().isoformat()

        # 1. Source discovery: maintain the approved pool above 500
        if source_stats.get("approved_count", 0) < 500:
            for persona in personas:
                await self.dispatch("source_discovery", {
                    "persona_id": persona["id"],
                    "max_new_candidates": 100,
                })

        # 2. Fresh targets for today (one run per persona)
        for persona in personas:
            await self.dispatch("fresh_target", {
                "persona_id": persona["id"],
                "date_iso": today,
            })

        # 3. Warming Agent runs per persona to build daily plans
        for persona in personas:
            curve_type = decision.get("curve_type_by_persona", {}).get(persona["id"], "steady")
            await self.dispatch("warming", {
                "persona_id": persona["id"],
                "date_iso": today,
                "curve_type": curve_type,
            })

        # 4. DM agent — only on personas the manager flagged as DM-ready
        for persona_id in decision.get("dm_active_personas", []):
            # DM agent processes inbound queue per-account; manager doesn't loop accounts
            await self.dispatch("dm", {
                "persona_id": persona_id,
                "max_accounts": decision.get("dm_max_accounts_per_persona", 10),
            })

        # 5. Content agent — feeds new posts into the vault for each persona
        for persona_id in decision.get("content_pull_personas", []):
            await self.dispatch("content", {"persona_id": persona_id})

        # 6. Hashtag tracker — runs weekly (manager checks last_rotation_iso)
        if decision.get("run_hashtag_rotation", False):
            hashtag_sidecars = await self.tool("db.load_ig_hashtag_sidecars")
            for persona in personas:
                await self.dispatch("ig_hashtag_tracker", {
                    "persona_id": persona["id"],
                    "date_iso": today,
                    "sidecars": hashtag_sidecars.get(persona["id"], {}),
                })

        # 7. Bio A/B tests — launch new tests or close completed ones
        if decision.get("run_bio_ab", False):
            ab_specs = await self.tool("db.load_ig_ab_test_specs")
            for persona_id, spec in ab_specs.items():
                await self.dispatch("ig_bio_ab", {
                    "persona_id": persona_id,
                    "spec": spec,
                    "date_iso": today,
                })

        # 8. Peak time optimizer — runs weekly to re-learn per-account peaks
        if decision.get("run_peak_time_analysis", False):
            peak_profiles = await self.tool("db.load_ig_peak_profiles")
            await self.dispatch("ig_peak_time", {
                "date_iso": today,
                "existing_profiles": peak_profiles,
            })

        # Persist strategic state for the next cycle
        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_ig_strategy_state", self.state)

        # Report up to Chief
        self.report_upward(run, {
            "personas": len(personas),
            "alive_accounts": health.get("alive_accounts", 0),
            "dead_24h": health.get("dead_24h", 0),
            "shadowban_signals": health.get("shadowban_signals", 0),
            "approved_sources": source_stats.get("approved_count", 0),
            "premium_sources": source_stats.get("premium_count", 0),
            "conversion_30d_usd": funnel.get("total_30d_usd", 0),
        })
        return True
