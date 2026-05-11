"""
RedditAgentManager — runs the Reddit platform autonomously.

Reddit is fundamentally different from IG/Threads/X:
    - Karma-gated (subreddits require minimum karma to post)
    - 4-stage farming funnel from birth to full activity
    - Per-subreddit posting rules (flair, title length, blacklists)
    - CQS (Community Quality Score) affects post removal rates
    - Accounts need shadowban checks separate from dead-account detection

This manager owns:
    - KarmaFarmingAgent (the 4-stage lurk→comment→post→full pipeline)
    - SubredditDiscoveryAgent (scrapes + classifies subreddits)
    - PostSchedulerAgent (schedules posts with per-subreddit compliance)
    - InboxAgent (processes incoming DMs, marks read, AI auto-reply)
    - ShadowbanCheckAgent (per-account shadowban probe)

Strategic decisions:
    1. Stage advancement: when does an account graduate from Lurk→Comment→Post→Full?
    2. Subreddit assignment per account (eligibility + karma requirements)
    3. Per-proxy serialization (accounts sharing a proxy never post concurrently)
    4. Karma target before live posting (default: 500+ CQS before hitting the vault)
    5. Repost/recycle strategy (RedGIFs re-upload, caption spin for uniqueness)
    6. Shadowban triage (paused accounts quarantine for 48h then re-check)
"""
from __future__ import annotations

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class RedditAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="reddit",
        max_iterations=12,
        max_usd_per_run=0.20,
        max_usd_per_session=3.00,
        confirmation_required_for=("mass_post_restart", "subreddit_blast"),
        allowed_tools=(
            "db.load_reddit_accounts",
            "db.load_reddit_farming_state",
            "db.load_subreddit_library",
            "db.load_shadowban_queue",
            "db.save_reddit_strategy_state",
            "llm.decide_reddit_strategy",
        ),
        supervises=(
            "karma_farming",
            "subreddit_discovery",
            "post_scheduler",
            "reddit_inbox",
            "shadowban_check",
        ),
        escalates_to="chief",
        report_cadence_min=15,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts = await self.tool("db.load_reddit_accounts")
        farming_state = await self.tool("db.load_reddit_farming_state")
        library = await self.tool("db.load_subreddit_library")
        shadowban_queue = await self.tool("db.load_shadowban_queue")

        decision = await self.tool(
            "llm.decide_reddit_strategy",
            accounts=accounts,
            farming_state=farming_state,
            library_size=len(library or []),
            current_state=self.state,
        )
        self.charge_cost(run, 0.04, "reddit_daily_decision")

        # 1. Refresh subreddit library (hourly cap)
        if decision.get("refresh_library"):
            await self.dispatch("subreddit_discovery", {
                "nsfw_mix": decision.get("nsfw_mix", 0.5),
                "min_subs": 5_000,
                "max_new": 200,
            })

        # 2. Per-account farming stage advancement
        for acct in accounts:
            stage = acct.get("farming_stage", 1)
            graduation_ready = acct.get("graduation_ready", False)
            await self.dispatch("karma_farming", {
                "account_id": acct["id"],
                "stage": stage,
                "advance_if_ready": graduation_ready,
                "session_cap_min": decision.get("farming_session_cap_min", 15),
            })

        # 3. Shadowban checks for flagged accounts
        for shadow in shadowban_queue or []:
            await self.dispatch("shadowban_check", {
                "account_id": shadow["account_id"],
            })

        # 4. Post scheduler — only for accounts past karma gate
        for acct in accounts:
            if acct.get("farming_stage") >= 4 and acct.get("cqs", 0) >= 500:
                await self.dispatch("post_scheduler", {
                    "account_id": acct["id"],
                    "subreddit_pool": decision.get("pool_for_account", {}).get(acct["id"], []),
                    "per_day_min": decision.get("posts_per_day_min", 1),
                    "per_day_max": decision.get("posts_per_day_max", 3),
                })

        # 5. Inbox agent — handle DMs across active accounts
        for acct in accounts:
            if acct.get("status") == "active":
                await self.dispatch("reddit_inbox", {
                    "account_id": acct["id"],
                })

        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_reddit_strategy_state", self.state)

        self.report_upward(run, {
            "accounts_total": len(accounts),
            "stage_1_lurk": sum(1 for a in accounts if a.get("farming_stage") == 1),
            "stage_2_comment": sum(1 for a in accounts if a.get("farming_stage") == 2),
            "stage_3_post": sum(1 for a in accounts if a.get("farming_stage") == 3),
            "stage_4_full": sum(1 for a in accounts if a.get("farming_stage") == 4),
            "shadowban_queue_size": len(shadowban_queue or []),
            "library_size": len(library or []),
        })
        return True
