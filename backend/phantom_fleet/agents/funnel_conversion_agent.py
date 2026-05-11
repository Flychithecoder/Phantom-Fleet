"""
FunnelConversionAgent — tracks fan → OF/Fanvue/ScaleHer subscription.

Attributes every OF/Fanvue/ScaleHer subscription to the persona + account
that drove it. Shows per-persona ROI on the dashboard so you see which
accounts are actually making money.

Integrations:
    - OnlyFansAPI.com (reference key in memory)
    - Fanvue API (Chat AI integration)
    - ScaleHer attribution hooks
    - Bouncy.ai cloaked link click-through tracking
"""
from __future__ import annotations

from .base import Agent, AgentConfig, AgentRun


class FunnelConversionAgent(Agent):
    config = AgentConfig(
        name="funnel_conversion",
        max_iterations=10,
        max_usd_per_run=0.00,
        allowed_tools=(
            "onlyfans.list_new_subs",
            "fanvue.list_new_subs",
            "scaleher.list_new_subs",
            "bouncy.list_click_events",
            "db.save_conversion",
            "db.attribute_conversion_to_account",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        since = ctx.get("since_iso")
        of_subs = await self.tool("onlyfans.list_new_subs", since=since)
        fv_subs = await self.tool("fanvue.list_new_subs", since=since)
        sh_subs = await self.tool("scaleher.list_new_subs", since=since)
        clicks = await self.tool("bouncy.list_click_events", since=since)

        total_attributed = 0
        for sub in of_subs + fv_subs + sh_subs:
            acct_id = self._attribute_sub_to_account(sub, clicks)
            if acct_id:
                await self.tool("db.save_conversion", sub, acct_id)
                await self.tool("db.attribute_conversion_to_account", acct_id, sub)
                total_attributed += 1

        run.outputs = {"attributed": total_attributed, "total_subs": len(of_subs) + len(fv_subs) + len(sh_subs)}
        return True

    def _attribute_sub_to_account(self, sub, clicks):
        """Match a subscription to the account that drove it via click tracking."""
        # Find a click event from this user within N hours of the sub timestamp
        for click in clicks:
            if click.get("user_hash") == sub.get("user_hash") and click.get("account_id"):
                return click["account_id"]
        return None
