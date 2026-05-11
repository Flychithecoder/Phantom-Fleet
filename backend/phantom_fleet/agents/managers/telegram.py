"""
TelegramAgentManager — runs Telegram platform autonomously.

Why Telegram is a top-3 manager for OFM funnel:
    - #1 "VIP destination" for fans priced out of OnlyFans walls
    - Typical OFM funnel: IG DM → Telegram VIP → OF upgrade
    - Mass group join + member scraping is effectively legal (public groups)
    - Telegram's ML detection is far softer than Meta platforms
    - Native multi-account support in the app (3) + cloning (15-20 per phone)
    - MTProto API is well-documented, bot API is official

This manager owns:
    - TelegramJoinAgent      — mass group + channel joining
    - TelegramScrapeAgent    — public group member scraping
    - TelegramDMAgent        — AI-driven DM outreach + inbox reply
    - TelegramChannelAgent   — own-channel posting + branding
    - TelegramForwardAgent   — content forwarding between channels
    - TelegramInboxAgent     — inbound DM handling + Chat AI handoff

Strategic decisions:
    1. Which target groups to join this week (niche match + activity level)
    2. DM budget per account per day (Telegram's stranger-DM limit is ~50/day)
    3. When to upgrade a phantom account to "phone-verified" (boost trust)
    4. Forward-chain strategy for content distribution
    5. Channel creation: maintain N branded "VIP decoy" channels per persona
    6. Chat AI handoff rules (when to transfer a DM thread to the persona owner
       or to Phantom Fleet Chat AI agents for ongoing conversation)
"""
from __future__ import annotations

from datetime import date

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class TelegramAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="telegram",
        max_iterations=12,
        max_usd_per_run=0.20,
        max_usd_per_session=3.00,
        confirmation_required_for=("mass_dm_blast", "bulk_group_join"),
        allowed_tools=(
            "db.load_telegram_accounts",
            "db.load_target_groups",
            "db.load_dm_queue",
            "db.load_channel_roster",
            "db.save_telegram_strategy_state",
            "llm.decide_telegram_strategy",
        ),
        supervises=(
            "telegram_join",
            "telegram_scrape",
            "telegram_dm",
            "telegram_channel",
            "telegram_forward",
            "telegram_inbox",
        ),
        escalates_to="chief",
        report_cadence_min=15,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts = await self.tool("db.load_telegram_accounts")
        groups = await self.tool("db.load_target_groups")
        dm_queue = await self.tool("db.load_dm_queue")
        channels = await self.tool("db.load_channel_roster")

        decision = await self.tool(
            "llm.decide_telegram_strategy",
            accounts=accounts,
            groups=groups,
            channels=channels,
            current_state=self.state,
        )
        self.charge_cost(run, 0.04, "telegram_daily_decision")

        today = date.today().isoformat()

        # 1. Inbox agent runs FIRST — respond to every inbound before outbound
        for a in accounts:
            if a.get("status") == "active":
                await self.dispatch("telegram_inbox", {
                    "account_id": a["id"],
                    "handoff_mode": a.get("handoff_mode", "chat_ai"),
                    "cta_link": a.get("cta_link"),
                })

        # 2. Join new target groups (spread across accounts, respect flood limit)
        new_group_assignments = decision.get("join_assignments", {})
        for account_id, group_ids in new_group_assignments.items():
            await self.dispatch("telegram_join", {
                "account_id": account_id,
                "groups_to_join": group_ids,
                "max_joins_per_hour": decision.get("max_joins_per_hour", 3),
            })

        # 3. Scrape members from newly joined groups
        for group in groups:
            if group.get("ready_to_scrape"):
                await self.dispatch("telegram_scrape", {
                    "group_id": group["id"],
                    "sample_size": decision.get("scrape_sample_size", 200),
                })

        # 4. DM outreach from scraped members → cold DM with AI-generated opener
        for dm_batch in decision.get("dm_batches", []):
            await self.dispatch("telegram_dm", {
                "account_id": dm_batch["account_id"],
                "targets": dm_batch["targets"],
                "opener_style": dm_batch.get("opener_style", "curious"),
                "cta_link": dm_batch.get("cta_link"),
                "max_per_day": decision.get("max_dms_per_account_per_day", 30),
            })

        # 5. Own-channel posting for branded fan destinations
        for persona_channel in channels or []:
            if persona_channel.get("needs_post"):
                await self.dispatch("telegram_channel", {
                    "channel_id": persona_channel["id"],
                    "persona_id": persona_channel["persona_id"],
                    "content_id": persona_channel.get("next_content_id"),
                })

        # 6. Forward content between channels (for cross-channel amplification)
        if decision.get("forward_campaigns"):
            for camp in decision["forward_campaigns"]:
                await self.dispatch("telegram_forward", camp)

        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_telegram_strategy_state", self.state)

        self.report_upward(run, {
            "accounts_total": len(accounts),
            "target_groups": len(groups or []),
            "owned_channels": len(channels or []),
            "dm_queue_size": len(dm_queue or []),
            "joins_queued_today": sum(len(v) for v in new_group_assignments.values()),
        })
        return True
