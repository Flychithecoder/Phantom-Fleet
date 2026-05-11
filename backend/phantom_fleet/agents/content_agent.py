"""
ContentAgent — pulls content from the Content Vault, generates captions,
schedules posts across the fleet.

Caption rules (user-locked 2026-04-11):
    - NO hashtags. Ever. Caption generator rejects any output containing '#'.
    - NO LLM tells (banned phrase list).
    - NO em-dashes, ellipses, or semicolons in short captions.
    - 15-40 words max per caption.
    - 2-3 emojis max, naturally placed.
    - Reference the actual content in the image/reel (not generic).
    - Voice: 22-year-old woman texting style, not brand voice.
"""
from __future__ import annotations

from .base import Agent, AgentConfig, AgentRun
from .dm_agent import BANNED_LLM_PHRASES


class ContentAgent(Agent):
    config = AgentConfig(
        name="content",
        max_iterations=20,
        max_usd_per_run=0.30,
        max_usd_per_session=5.00,
        allowed_tools=(
            "vault.pull_content",
            "vault.mark_used",
            "db.load_persona_voice",
            "llm.generate_caption",
            "phone.queue_post",
            "phone.queue_reel",
            "phone.queue_story",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id = ctx["account_id"]
        persona_id = ctx["persona_id"]

        voice = await self.tool("db.load_persona_voice", account_id)
        content = await self.tool("vault.pull_content", persona_id, limit=1)
        if not content:
            return True

        media = content[0]
        prompt = self._build_prompt(voice, media)
        caption = await self.tool("llm.generate_caption", prompt=prompt)
        self.charge_cost(run, 0.003, "caption_gen")

        if not self._is_caption_valid(caption):
            run.audit_events.append({"rejected_caption": caption[:120]})
            return True

        if media["type"] == "reel":
            await self.tool("phone.queue_reel", account_id, media, caption)
        elif media["type"] == "story":
            await self.tool("phone.queue_story", account_id, media, caption)
        else:
            await self.tool("phone.queue_post", account_id, media, caption)

        await self.tool("vault.mark_used", media["id"], persona_id)

        run.audit_events.append({
            "account": account_id,
            "media_type": media["type"],
            "caption_len": len(caption),
        })
        return True

    def _build_prompt(self, voice: dict, media: dict) -> str:
        return (
            f"Write an Instagram caption for this {media['type']}. "
            f"Persona: {voice['display_name']}, {voice['age']}, {voice['city']}. "
            f"Voice: 22-year-old woman texting, casual, slightly playful. "
            f"Reference the actual content. "
            f"NO hashtags. NO em-dashes. NO ellipses. NO semicolons. "
            f"NO LLM tells like 'delve into', 'it's worth noting', 'elevate'. "
            f"15-40 words max. 2-3 emojis max, placed naturally. "
            f"Keywords to weave in as natural sentences (NOT tags): "
            f"{', '.join(voice.get('keywords', []))}"
        )

    def _is_caption_valid(self, caption: str) -> bool:
        if not caption:
            return False
        if "#" in caption:
            return False
        if "—" in caption or "…" in caption or ";" in caption:
            return False
        word_count = len(caption.split())
        if word_count < 5 or word_count > 45:
            return False
        lower = caption.lower()
        for phrase in BANNED_LLM_PHRASES:
            if phrase in lower:
                return False
        return True
