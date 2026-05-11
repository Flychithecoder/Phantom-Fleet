"""
LinkedInAgentManager — runs LinkedIn for the B2B vertical.

**MARKETED AS A SEPARATE PRODUCT LINE**: "Phantom Fleet Sales" (or similar),
with completely separate landing page + pricing to avoid any adult-adjacent
marketing confusion. Phantom Fleet's core value proposition (fleet-scale
cluster detection, persona primitive, AI agent mesh) transfers cleanly to
LinkedIn — but the customer is an entirely different buyer (B2B sales teams,
recruiters, growth marketers, agency owners) who has zero overlap with OFM.

Why LinkedIn is a gold mine:
    - $100M+ existing market (LinkedHelper, Dux-Soup, Expandi, PhantomBuster,
      LaGrowthMachine, Waalaxy) — ALL browser-based, ALL get flagged
    - Real-device LinkedIn automation would be step-change better trust
    - B2B SaaS buyers pay 3-5x more than OFM buyers and churn less
    - Completely decoupled from adult content → easier to market + advertise
    - Sales Navigator is the high-value tier ($80-200/mo per seat)

This manager owns:
    - LinkedInConnectAgent   — personalized connection requests at scale
    - LinkedInDMAgent        — AI cold DM + accepted-connection follow-up
    - LinkedInScrapeAgent    — employee search, recruiter lookups, sales nav
    - LinkedInContentAgent   — post scheduling + engagement
    - LinkedInProfileAgent   — bulk profile optimization for agency clients
    - LinkedInCRMSyncAgent   — HubSpot / Salesforce / Pipedrive sync

Strategic decisions:
    1. Connection budget per account (LinkedIn caps at 100/week weekly limit)
    2. Targeting query optimization (which filters produce accepted connections)
    3. Follow-up cadence (3/7/14/30 day touches)
    4. Sales Navigator routing for high-tier accounts
    5. Content engagement budget (likes + thoughtful comments per day)
    6. Profile optimization rotations for agency-managed accounts

Detection posture:
    - STRICT. LinkedIn has the strongest bot detection of any B2B platform.
    - Hardware attestation passes automatically on unrooted Samsung (your fleet)
    - Aged accounts REQUIRED — never cold-start, always 90d+ buy-in
    - Bezier-curve realistic clicking through profile + feed
    - Connection requests throttled to natural pace (5-20 per day per account max)
"""
from __future__ import annotations

from datetime import date

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class LinkedInAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="linkedin",
        max_iterations=12,
        max_usd_per_run=0.35,
        max_usd_per_session=5.00,
        confirmation_required_for=(
            "mass_connection_blast",
            "profile_bulk_rewrite",
            "sales_nav_upgrade",
        ),
        allowed_tools=(
            "db.load_linkedin_accounts",
            "db.load_linkedin_targeting_queries",
            "db.load_linkedin_connection_queue",
            "db.load_linkedin_crm_sync_state",
            "db.save_linkedin_strategy_state",
            "llm.decide_linkedin_strategy",
        ),
        supervises=(
            "linkedin_connect",
            "linkedin_dm",
            "linkedin_scrape",
            "linkedin_content",
            "linkedin_profile",
            "linkedin_crm_sync",
        ),
        escalates_to="chief",
        report_cadence_min=30,
    )

    # LinkedIn's weekly connection request cap is ~100. We use a STRICT 20/day
    # per account as our ceiling to stay under radar.
    MAX_CONNECTIONS_PER_ACCOUNT_PER_DAY = 20

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts = await self.tool("db.load_linkedin_accounts")
        queries = await self.tool("db.load_linkedin_targeting_queries")
        conn_queue = await self.tool("db.load_linkedin_connection_queue")
        crm_state = await self.tool("db.load_linkedin_crm_sync_state")

        decision = await self.tool(
            "llm.decide_linkedin_strategy",
            accounts=accounts,
            queries=queries,
            connection_queue_size=len(conn_queue or []),
            crm_state=crm_state,
            current_state=self.state,
        )
        self.charge_cost(run, 0.08, "linkedin_daily_decision")

        today = date.today().isoformat()

        # 1. Scrape new prospects from saved targeting queries
        for query in queries or []:
            if query.get("refresh_due"):
                await self.dispatch("linkedin_scrape", {
                    "query_id": query["id"],
                    "filters": query.get("filters", {}),
                    "max_results": decision.get("scrape_cap", 500),
                })

        # 2. Connection request dispatches (strictly capped)
        for account_id, target_list in decision.get("connection_dispatches", {}).items():
            capped = target_list[: self.MAX_CONNECTIONS_PER_ACCOUNT_PER_DAY]
            await self.dispatch("linkedin_connect", {
                "account_id": account_id,
                "targets": capped,
                "personalized": True,  # ALWAYS use AI-personalized notes
                "delay_min_sec": 180,
                "delay_max_sec": 600,
            })

        # 3. DM follow-up on recently accepted connections
        for dm_batch in decision.get("dm_followups", []):
            await self.dispatch("linkedin_dm", {
                "account_id": dm_batch["account_id"],
                "thread_ids": dm_batch["thread_ids"],
                "followup_stage": dm_batch.get("stage", "day_3"),
                "cta_link": dm_batch.get("cta_link"),
            })

        # 4. Content engagement — like + comment on targeted feeds
        for account_id, engage_plan in decision.get("engagement_plan", {}).items():
            await self.dispatch("linkedin_content", {
                "account_id": account_id,
                "like_quota": engage_plan.get("likes", 10),
                "comment_quota": engage_plan.get("comments", 3),
                "target_feeds": engage_plan.get("feeds", ["industry", "my_network"]),
            })

        # 5. Profile optimization — only on explicit customer request (gated)
        for account_id in decision.get("profile_optimization_queue", []):
            await self.dispatch("linkedin_profile", {
                "account_id": account_id,
                "optimization_type": "bulk_skill_refresh",
            })

        # 6. CRM sync if customer has HubSpot / Salesforce / Pipedrive wired up
        if crm_state.get("enabled"):
            await self.dispatch("linkedin_crm_sync", {
                "crm_type": crm_state["crm_type"],
                "since": crm_state.get("last_sync_ts"),
            })

        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_linkedin_strategy_state", self.state)

        self.report_upward(run, {
            "accounts_total": len(accounts),
            "targeting_queries": len(queries or []),
            "connection_queue_size": len(conn_queue or []),
            "crm_sync_enabled": crm_state.get("enabled", False),
            "daily_connection_cap": self.MAX_CONNECTIONS_PER_ACCOUNT_PER_DAY,
        })
        return True
