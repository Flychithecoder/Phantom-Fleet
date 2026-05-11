"""
SourceDiscoveryAgent — auto-discovers female US high-engagement source accounts.

This is the "game-changing" feature: instead of manually curating source
lists, the agent continuously discovers new candidate sources, scores them
through core.source_scorer, and maintains a ranked pool that the
FreshTargetAgent pulls from for daily target scraping.

Discovery loop:
    1. SEED — start with known-good sources
    2. EXPAND — IG 'Suggested Similar Accounts' from each seed
    3. CHAIN — followers of followers (2nd-degree graph walks)
    4. CROSS-REFERENCE — accounts appearing in multiple seeds' similars rank higher
    5. SEARCH — scraper accounts run keyword text searches (no hashtags)
    6. SCORE — every candidate run through SourceScoringEngine
    7. PROMOTE — top-scoring candidates join the approved pool
    8. RETIRE — sources producing low-converting targets auto-retired
    9. REFRESH — re-score approved sources weekly
"""
from __future__ import annotations

import logging

from .base import Agent, AgentConfig, AgentRun
from ..core.source_scorer import CandidateSource, score_source

log = logging.getLogger(__name__)


class SourceDiscoveryAgent(Agent):
    config = AgentConfig(
        name="source_discovery",
        max_iterations=10,
        max_usd_per_run=0.10,  # may use LLM for bio parsing
        max_usd_per_session=2.00,
        allowed_tools=(
            "db.load_persona_sources",
            "db.load_seed_sources",
            "db.save_candidate_source",
            "db.update_source_score",
            "db.retire_source",
            "scraper.profile_info",
            "scraper.similar_accounts",
            "scraper.chain_walk",
            "scraper.keyword_search",
            "scraper.sample_followers",
            "scraper.recent_posts_stats",
        ),
    )

    # Minimum count of approved sources per persona (auto-discover until hit)
    TARGET_APPROVED_POOL_SIZE = 500

    # Minimum score to enter the pool
    MIN_APPROVED_SCORE = 65.0

    # Minimum score to be flagged premium
    PREMIUM_SCORE = 85.0

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        """
        ctx expects:
            - persona_id: str
            - max_new_candidates: int (default 100)
        """
        persona_id = ctx["persona_id"]
        max_new = ctx.get("max_new_candidates", 100)

        existing = await self.tool("db.load_persona_sources", persona_id)
        seeds = await self.tool("db.load_seed_sources", persona_id)

        # Phase 1: EXPAND — pull similar accounts from seeds
        candidates: set[str] = set()
        for seed in seeds[:20]:
            similar = await self.tool("scraper.similar_accounts", seed.username, limit=50)
            candidates.update(similar)

        # Phase 2: CHAIN — follower-of-follower walks
        for seed in seeds[:5]:
            chain_results = await self.tool("scraper.chain_walk", seed.username, depth=2, limit_per_hop=30)
            candidates.update(chain_results)

        # Remove already-known
        known = {s.username for s in existing}
        new_candidates = [u for u in candidates if u not in known][:max_new]

        scored_count = 0
        approved_count = 0
        premium_count = 0

        for uname in new_candidates:
            # Build a CandidateSource from scraped profile data
            profile = await self.tool("scraper.profile_info", uname)
            if not profile:
                continue
            recent = await self.tool("scraper.recent_posts_stats", uname, limit=12)
            sample_followers = await self.tool("scraper.sample_followers", uname, limit=50)

            candidate = CandidateSource(
                username=uname,
                full_name=profile.get("full_name", ""),
                bio=profile.get("bio", ""),
                follower_count=profile.get("followers", 0),
                following_count=profile.get("following", 0),
                post_count=profile.get("posts", 0),
                avg_likes_last_12=recent.get("avg_likes", 0.0),
                avg_comments_last_12=recent.get("avg_comments", 0.0),
                days_since_last_post=recent.get("days_since_last_post", 999),
                post_cadence_days=recent.get("cadence", 999.0),
                follower_growth_30d=profile.get("growth_30d", 0),
                profile_pic_url=profile.get("profile_pic_url", ""),
                sample_follower_usernames=sample_followers,
            )

            result = score_source(candidate)
            scored_count += 1

            if result.approved:
                await self.tool(
                    "db.save_candidate_source",
                    persona_id=persona_id,
                    username=uname,
                    score=result.score,
                    tier=result.tier,
                    metrics=result.metrics,
                    reasons=result.reasons,
                )
                approved_count += 1
                if result.tier == "premium":
                    premium_count += 1

        run.audit_events.append({
            "persona": persona_id,
            "candidates_found": len(new_candidates),
            "scored": scored_count,
            "approved": approved_count,
            "premium": premium_count,
        })

        return True
