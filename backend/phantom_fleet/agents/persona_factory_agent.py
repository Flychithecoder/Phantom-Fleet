"""
PersonaFactoryAgent — generates new personas on demand with consistent
cross-field identity, runs them through the audit harness before returning,
and rejects any persona whose fields would cluster at scale.
"""
from __future__ import annotations

from .base import Agent, AgentConfig, AgentRun
from ..core.persona import create_persona


class PersonaFactoryAgent(Agent):
    config = AgentConfig(
        name="persona_factory",
        max_iterations=5,
        max_usd_per_run=0.02,
        allowed_tools=(
            "db.save_persona",
            "audit.validate_persona",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        display_name = ctx["display_name"]
        gender = ctx.get("gender", "f")
        target_funnel = ctx.get("target_funnel", "onlyfans")
        interest_topics = tuple(ctx.get("interest_topics", ()))

        persona = create_persona(
            display_name=display_name,
            gender=gender,
            target_funnel=target_funnel,
            interest_topics=interest_topics,
        )

        is_valid = await self.tool("audit.validate_persona", persona)
        if not is_valid:
            run.error = "persona failed audit validation"
            return True

        await self.tool("db.save_persona", persona)
        run.outputs = {"persona_id": persona.persona_id}
        return True
