"""
ThreadsAgentManager — runs the Threads platform autonomously.

Threads is **tightly coupled** to Instagram:
    - Threads accounts ARE Instagram accounts (same auth, cookies, device fingerprint)
    - Every IG persona automatically has a Threads identity
    - Posting on IG CAN cross-post to Threads with one additional toggle

This manager's job:
    1. **Cross-post IG→Threads automatically** for every IG post the Content Agent schedules
    2. Run Threads-specific follow/like/reply engagement (separate daily budget from IG)
    3. Consume Threads-trending feeds (Google Trends, Reddit rising, Threads hashtag rotation)
    4. Build Threads reply chains to boost reach
    5. NO booster network (user has limited accounts; quality > spray)
    6. Route all Threads actions through the SAME phone + proxy + session as the IG parent
    7. Coordinate with InstagramAgentManager via the Chief — when IG is in cool-down,
       Threads throttles too (they share accounts)
"""
from __future__ import annotations

from datetime import date

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class ThreadsAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="threads",
        max_iterations=10,
        max_usd_per_run=0.20,
        max_usd_per_session=3.00,
        allowed_tools=(
            "db.load_ig_personas",
            "db.load_threads_health",
            "db.load_trending_topics",
            "db.save_threads_state",
            "llm.decide_daily_budget",
        ),
        supervises=(
            "threads_cross_post",
            "threads_engagement",
            "trending_feed",
        ),
        escalates_to="chief",
        report_cadence_min=15,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        personas = await self.tool("db.load_ig_personas")
        health = await self.tool("db.load_threads_health")
        trending = await self.tool("db.load_trending_topics", sources=["google", "reddit_rising", "threads"])

        decision = await self.tool(
            "llm.decide_daily_budget",
            platform="threads",
            personas=personas,
            health=health,
            trending=trending,
            current_state=self.state,
        )
        self.charge_cost(run, 0.04, "threads_daily_decision")

        today = date.today().isoformat()

        # 1. Refresh trending topics pool (Threads-specific)
        await self.dispatch("trending_feed", {
            "platform": "threads",
            "sources": ["google_trends", "reddit_rising", "threads_rotation"],
        })

        # 2. Cross-post IG → Threads for each persona (uses same IG session)
        for persona in personas:
            if persona["id"] in decision.get("cross_post_personas", []):
                await self.dispatch("threads_cross_post", {
                    "persona_id": persona["id"],
                    "date_iso": today,
                    "daily_post_quota": decision.get("cross_post_quota_per_persona", 2),
                })

        # 3. Engagement pass — follow/like/reply on trending Threads
        for persona in personas:
            budget = decision.get("engagement_budget_per_persona", {}).get(persona["id"], {})
            if not budget:
                continue
            await self.dispatch("threads_engagement", {
                "persona_id": persona["id"],
                "date_iso": today,
                "follows": budget.get("follows", 0),
                "likes": budget.get("likes", 0),
                "replies": budget.get("replies", 0),
                "trending_topic_slots": budget.get("trending_topic_slots", 3),
            })

        # Persist + report
        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_threads_state", self.state)

        self.report_upward(run, {
            "personas": len(personas),
            "threads_accounts_alive": health.get("alive_accounts", 0),
            "cross_posts_queued_today": decision.get("cross_posts_queued", 0),
            "trending_topics_active": len(trending or []),
        })
        return True
