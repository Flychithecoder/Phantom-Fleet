"""
DMAgent — fan DM conversations + funnel to OF/Fanvue/ScaleHer.

Runs per-account, per-session. Reads inbox, generates replies in the
persona's voice (via Phantom Fleet's built-in Chat AI agents), qualifies
fans, and funnels high-intent leads to OnlyFans/Fanvue/ScaleHer.

Strict rules:
    - Never paste; always type character-by-character with realistic timings
    - Match reply cadence to persona biometrics
    - LLM detection tells banned from generated text (see ContentAgent rules)
    - Per-account daily DM limit enforced by code
    - CTA frequency capped (max 1 CTA per conversation per 24h)
    - Destructive actions (mass DM blasts) require confirmation
"""
from __future__ import annotations

from .base import Agent, AgentConfig, AgentRun


BANNED_LLM_PHRASES = frozenset([
    "delve into", "it's worth noting", "elevate", "resonates with",
    "game-changer", "in conclusion", "furthermore", "moreover",
    "it's important to note", "at the end of the day", "paradigm",
    "at its core", "a testament to", "navigate the",
])


class DMAgent(Agent):
    config = AgentConfig(
        name="dm",
        max_iterations=15,
        max_usd_per_run=0.15,  # LLM calls for reply generation
        max_usd_per_session=3.00,
        confirmation_required_for=("mass_dm_blast",),
        allowed_tools=(
            "phone.read_dm_inbox",
            "phone.type_message",
            "phone.send_message",
            "phone.send_media",
            "db.load_persona_voice",
            "db.load_conversation_history",
            "db.save_dm_turn",
            "llm.generate_reply",
            "funnel.log_cta",
            "funnel.attribute_sub",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id = ctx["account_id"]
        phone_serial = ctx["phone_serial"]
        persona_voice = await self.tool("db.load_persona_voice", account_id)

        inbox = await self.tool("phone.read_dm_inbox", phone_serial, account_id)
        for thread in inbox:
            history = await self.tool("db.load_conversation_history", thread["thread_id"])
            reply = await self.tool(
                "llm.generate_reply",
                persona_voice=persona_voice,
                history=history,
                latest_message=thread["latest_message"],
                banned_phrases=list(BANNED_LLM_PHRASES),
                max_words=40,
                no_hashtags=True,
                no_em_dashes=True,
            )
            self.charge_cost(run, 0.002, "llm_reply")

            if self._contains_banned(reply):
                run.audit_events.append({"rejected": reply, "reason": "llm_tells"})
                continue

            await self.tool(
                "phone.type_message",
                phone_serial=phone_serial,
                account_id=account_id,
                thread_id=thread["thread_id"],
                message=reply,
                type_cadence="persona_biometrics",
            )
            await self.tool("phone.send_message", phone_serial, account_id, thread["thread_id"])
            await self.tool("db.save_dm_turn", thread["thread_id"], "outbound", reply)

        return True

    def _contains_banned(self, text: str) -> bool:
        lower = text.lower()
        if "#" in text:
            return True  # no hashtags in captions or DMs
        for phrase in BANNED_LLM_PHRASES:
            if phrase in lower:
                return True
        if "—" in text or "…" in text:
            return True  # em-dash / ellipsis ban
        return False
