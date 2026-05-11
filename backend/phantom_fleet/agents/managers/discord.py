"""
DiscordAgentManager — Discord automation for community funnel + growth.

Discord's role in the Phantom Fleet ecosystem:
    - #2 VIP destination for fans after Telegram (for OFM)
    - Massive community platform for crypto, gaming, NFT, tech, trading (for non-OFM)
    - Relatively soft bot detection (ToS bans user-token self-botting but rarely enforced)
    - Native multi-account switching + cloning = 10-15 accounts per phone

Owns:
    - DiscordJoinAgent       — mass server join (by invite / keyword)
    - DiscordScrapeAgent     — member list scraping on public servers
    - DiscordDMAgent         — targeted DM outreach + AI reply
    - DiscordPresenceAgent   — voice channel presence + stage attendance
    - DiscordOwnerAgent      — own server creation + moderation + role mgmt
    - DiscordReactAgent      — reaction engagement on trending messages

Strategic decisions:
    1. Which target servers to join this week (community match + activity)
    2. DM rate limiting (Discord bans for spam aggressively)
    3. Voice presence rotation (pure social proof — no audio transmitted)
    4. Own-server management (branded community growth for customers)
    5. Role escalation (auto-promote active members to VIP tier)
"""
from __future__ import annotations

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class DiscordAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="discord",
        max_iterations=10,
        max_usd_per_run=0.15,
        max_usd_per_session=2.50,
        confirmation_required_for=("mass_dm_blast",),
        allowed_tools=(
            "db.load_discord_accounts",
            "db.load_target_servers",
            "db.load_owned_servers",
            "db.load_discord_dm_queue",
            "db.save_discord_strategy_state",
            "llm.decide_discord_strategy",
        ),
        supervises=(
            "discord_join",
            "discord_scrape",
            "discord_dm",
            "discord_presence",
            "discord_owner",
            "discord_react",
        ),
        escalates_to="chief",
        report_cadence_min=20,
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts = await self.tool("db.load_discord_accounts")
        target_servers = await self.tool("db.load_target_servers")
        owned_servers = await self.tool("db.load_owned_servers")
        dm_queue = await self.tool("db.load_discord_dm_queue")

        decision = await self.tool(
            "llm.decide_discord_strategy",
            accounts=accounts,
            target_servers=target_servers,
            owned_servers=owned_servers,
            current_state=self.state,
        )
        self.charge_cost(run, 0.04, "discord_daily_decision")

        # 1. Join new target servers (rate-limited per account)
        for account_id, server_invites in decision.get("join_assignments", {}).items():
            await self.dispatch("discord_join", {
                "account_id": account_id,
                "server_invites": server_invites,
                "max_joins_per_hour": decision.get("max_joins_per_hour", 2),
            })

        # 2. Scrape members from active servers
        for server in target_servers or []:
            if server.get("ready_to_scrape"):
                await self.dispatch("discord_scrape", {
                    "server_id": server["id"],
                    "limit": decision.get("scrape_limit", 500),
                })

        # 3. DM outreach from scraped members (Discord is strict — small batches)
        for dm_batch in decision.get("dm_batches", []):
            await self.dispatch("discord_dm", {
                "account_id": dm_batch["account_id"],
                "targets": dm_batch["targets"][:15],  # hard cap — DM flood limit
                "opener_style": dm_batch.get("opener_style", "casual"),
                "cta_link": dm_batch.get("cta_link"),
            })

        # 4. Voice channel presence (pure social proof, no audio)
        for presence_plan in decision.get("voice_presence_plan", []):
            await self.dispatch("discord_presence", {
                "account_id": presence_plan["account_id"],
                "server_id": presence_plan["server_id"],
                "channel_id": presence_plan["channel_id"],
                "duration_min": presence_plan.get("duration_min", 45),
            })

        # 5. Own-server management: post content, manage roles, promote VIPs
        for server in owned_servers or []:
            await self.dispatch("discord_owner", {
                "server_id": server["id"],
                "pending_posts": server.get("pending_posts", []),
                "vip_promotion_queue": server.get("vip_promotion_queue", []),
            })

        # 6. Reaction engagement (light social signal boost)
        if decision.get("react_campaigns"):
            for react in decision["react_campaigns"]:
                await self.dispatch("discord_react", react)

        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_discord_strategy_state", self.state)

        self.report_upward(run, {
            "accounts_total": len(accounts),
            "target_servers": len(target_servers or []),
            "owned_servers": len(owned_servers or []),
            "dm_queue_size": len(dm_queue or []),
        })
        return True
