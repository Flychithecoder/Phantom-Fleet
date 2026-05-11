"""
ReplacementAgent — dead account replacement lifecycle.

When an account dies, the persona keeps existing. ReplacementAgent:
    1. Marks the dead account in target_history with action='death'
    2. Queries the replacement_queue for pending slots under the persona
    3. Pulls the next aged account from the user's manual import queue
    4. Assigns it to the same persona cohort
    5. Routes it through AccountSetupAgent → WarmingAgent Day 0 flow
    6. Updates the dashboard so the user sees the replacement happened
"""
from __future__ import annotations

from .base import Agent, AgentConfig, AgentRun


class ReplacementAgent(Agent):
    config = AgentConfig(
        name="replacement",
        max_iterations=5,
        max_usd_per_run=0.00,
        confirmation_required_for=("purchase_new_accounts",),
        allowed_tools=(
            "db.load_replacement_queue",
            "db.pull_next_available_aged_account",
            "db.assign_account_to_persona",
            "db.mark_account_dead",
            "agent.kick_setup_agent",
            "notifier.alert",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        dead_account_id = ctx["dead_account_id"]
        persona_id = ctx["persona_id"]
        reason = ctx.get("reason", "unknown")

        await self.tool("db.mark_account_dead", dead_account_id, reason=reason)

        replacement = await self.tool("db.pull_next_available_aged_account", persona_id)
        if replacement is None:
            await self.tool("notifier.alert", {
                "type": "replacement_needed",
                "persona_id": persona_id,
                "dead_account_id": dead_account_id,
                "message": "no aged accounts available in replacement queue",
            })
            return True

        await self.tool("db.assign_account_to_persona", replacement.id, persona_id)
        await self.tool("agent.kick_setup_agent", replacement.id)

        run.audit_events.append({
            "dead": dead_account_id,
            "replacement": replacement.id,
            "persona": persona_id,
            "reason": reason,
        })
        return True
