"""
XAgentManager — runs the X (Twitter) platform autonomously.

Unique X constraints:
    - ct0 + auth_token cookie pair required for every API call
    - GraphQL-heavy API with shifting query hashes (breaks on every X deploy)
    - Per-account session restoration from stored cookies (avoids re-login)
    - Premium user filtering (can't DM them — auto-exclude)
    - Rate limits are aggressive: per-endpoint, per-account, per-15m window
    - JA3/JA4 TLS fingerprint matching (Node tls-client with iOS 18 profile)
    - Reply-bait on trending topics is the highest-ROI growth channel

This manager owns:
    - TweetAgent (schedule + publish tweets + threads)
    - BaitReplyAgent (find trending posts, reply with on-brand comments)
    - XDMAgent (inbox scan + AI reply + CTA insertion)
    - ListBuilderAgent (curate Twitter lists for targeting)
    - XSessionRefreshAgent (ct0/auth_token health check + refresh)

Strategic decisions:
    1. Session health pass first — ANY account with bad session gets refreshed
       before other agents touch it
    2. Tweet budget per persona per day (LogNormal sampled)
    3. Reply-bait targeting: which trends to jump on, which to avoid
    4. DM opener rotation (A/B tested openers from the learning engine)
    5. List membership management — build follower lists for future bait targets
    6. Premium-user exclusion (enforced in targeting pipeline)
"""
from __future__ import annotations

from datetime import date

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class XAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="x",
        max_iterations=12,
        max_usd_per_run=0.30,
        max_usd_per_session=4.00,
        confirmation_required_for=("mass_dm_blast", "list_purge"),
        allowed_tools=(
            "db.load_x_accounts",
            "db.load_x_session_health",
            "db.load_x_trending",
            "db.load_x_dm_queue",
            "db.save_x_strategy_state",
            "llm.decide_x_strategy",
        ),
        supervises=(
            "tweet",
            "bait_reply",
            "x_dm",
            "list_builder",
            "x_session_refresh",
        ),
        escalates_to="chief",
        report_cadence_min=10,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts = await self.tool("db.load_x_accounts")
        sessions = await self.tool("db.load_x_session_health")
        trending = await self.tool("db.load_x_trending", region="US")
        dm_queue = await self.tool("db.load_x_dm_queue")

        decision = await self.tool(
            "llm.decide_x_strategy",
            accounts=accounts,
            sessions=sessions,
            trending=trending,
            current_state=self.state,
        )
        self.charge_cost(run, 0.05, "x_daily_decision")

        today = date.today().isoformat()

        # 1. Session refresh FIRST — expired ct0/auth_token must heal before anything
        for s in sessions.get("need_refresh", []):
            await self.dispatch("x_session_refresh", {"account_id": s["account_id"]})

        # 2. Tweet scheduler per persona
        for persona_id in decision.get("tweet_active_personas", []):
            await self.dispatch("tweet", {
                "persona_id": persona_id,
                "date_iso": today,
                "daily_tweet_quota": decision.get("tweet_quota", 3),
                "thread_probability": decision.get("thread_probability", 0.2),
            })

        # 3. Reply-bait on trending topics (highest growth channel)
        for topic in (trending or [])[:decision.get("bait_topic_count", 5)]:
            await self.dispatch("bait_reply", {
                "topic": topic,
                "accounts_per_topic": decision.get("bait_accounts_per_topic", 3),
                "max_replies_per_account": decision.get("bait_replies_per_account", 2),
                "reply_tone": decision.get("bait_tone", "casual"),
            })

        # 4. DM inbox processing
        for dm in dm_queue or []:
            await self.dispatch("x_dm", {
                "account_id": dm["account_id"],
                "thread_id": dm["thread_id"],
            })

        # 5. List builder — maintain target lists (async, low priority)
        if decision.get("list_builder_run"):
            await self.dispatch("list_builder", {
                "lists_to_refresh": decision.get("lists_to_refresh", []),
            })

        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_x_strategy_state", self.state)

        self.report_upward(run, {
            "accounts_total": len(accounts),
            "sessions_healthy": sessions.get("healthy_count", 0),
            "sessions_needing_refresh": len(sessions.get("need_refresh", [])),
            "trending_topics_tracked": len(trending or []),
            "dm_queue_size": len(dm_queue or []),
        })
        return True
