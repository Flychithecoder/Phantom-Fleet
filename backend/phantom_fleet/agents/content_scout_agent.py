"""
ContentScoutAgent — scrapes trending content from real sources, routes to
Content Vault for later use by ContentAgent.

Sources (no hashtags):
    - Trending reels in persona's niche
    - Top posts from whitelisted creator accounts
    - Audio-based discovery (trending songs in niche)
    - Competitor top-performing posts (last 30 days)

All content is tagged with niche + persona fit score + trending window.
"""
from __future__ import annotations

from .base import Agent, AgentConfig, AgentRun


class ContentScoutAgent(Agent):
    config = AgentConfig(
        name="content_scout",
        max_iterations=15,
        max_usd_per_run=0.05,
        max_usd_per_session=1.00,
        allowed_tools=(
            "scraper.trending_reels",
            "scraper.top_posts",
            "scraper.audio_popular",
            "vault.save_content",
            "vault.score_content",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        niche = ctx["niche"]
        persona_id = ctx["persona_id"]

        trending = await self.tool("scraper.trending_reels", niche, limit=50)
        top = await self.tool("scraper.top_posts", niche, limit=30)
        audio = await self.tool("scraper.audio_popular", niche, limit=20)

        all_content = trending + top
        saved = 0
        for media in all_content:
            score = await self.tool("vault.score_content", media, persona_id)
            if score >= 0.6:
                await self.tool("vault.save_content", media, persona_id, score)
                saved += 1

        run.outputs = {"scraped": len(all_content), "saved": saved, "audio_tracks": len(audio)}
        return True
