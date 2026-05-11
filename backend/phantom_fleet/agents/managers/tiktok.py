"""
TikTokAgentManager — runs TikTok automation with the most aggressive
anti-detection posture in the fleet.

TikTok is the hardest platform on Earth right now:
    - Fast, aggressive shadowban classifier (3-follow ban reports in Onimator community)
    - Geo-locked feed (the For You Page you see is your location + interest signature)
    - Aggressive clone detection: AppCloner variants get flagged almost immediately
    - Frequent app updates force everyone off spoofed builds
    - TE (TikTok Explore) actively checks device props + sensor streams
    - Rootless + signature-permission Magisk rollout improves survival 10x

This manager owns:
    - TikTokFollowAgent
    - TikTokScrollAgent  (feed scroll with realistic dwell per video)
    - TikTokCommentAgent
    - TikTokFBRTrackerAgent (follow-back ratio tracking; kills sources with bad FBR)
    - TikTokFeedGeoAgent   (matches feed location to persona claimed region)

Strategic decisions that MATTER on TikTok specifically:
    1. **Ultra-gentle warm-up** — 0 follows/day in first 72h, feed scroll only
    2. **Geo match** — feed algorithm reads location every launch; mismatch = shadowban
    3. **App version pinning** — use older TikTok APKs known to work with NomixCloner,
       auto-bump when old version stops loading
    4. **Per-account sensor stream replay** — Frida/Xposed hook feeds TikTok
       synthetic accelerometer + gyro data matching the claimed device
    5. **Scroll dwell realism** — never scroll a video in < 3 seconds, weight dwell
       toward longer view times for liked videos (matches real user curve)
    6. **FBR retirement** — any source with FBR < 3% over 7 days gets retired
    7. **Magisk tier** — phones with Magisk enabled handle 3x the account density
       (signature injection lets us hide ADB + developer settings)

This is the highest-risk platform manager. It reports up to Chief every 5 minutes
and Chief has standing authority to pause it wholesale on cluster signals.
"""
from __future__ import annotations

from datetime import date

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class TikTokAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="tiktok",
        max_iterations=12,
        max_usd_per_run=0.15,
        max_usd_per_session=2.00,
        confirmation_required_for=(
            "pause_all_tiktok",
            "accelerate_warmup",
            "magisk_rollout",
        ),
        allowed_tools=(
            "db.load_tiktok_accounts",
            "db.load_tiktok_app_version",
            "db.load_tiktok_fbr",
            "db.load_tiktok_geo_status",
            "db.save_tiktok_strategy_state",
            "llm.decide_tiktok_strategy",
        ),
        supervises=(
            "tiktok_follow",
            "tiktok_scroll",
            "tiktok_comment",
            "tiktok_fbr_tracker",
            "tiktok_feed_geo",
        ),
        escalates_to="chief",
        report_cadence_min=5,  # most aggressive reporting cadence — TikTok breaks fast
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts = await self.tool("db.load_tiktok_accounts")
        app_version = await self.tool("db.load_tiktok_app_version")
        fbr = await self.tool("db.load_tiktok_fbr", days=7)
        geo_status = await self.tool("db.load_tiktok_geo_status")

        decision = await self.tool(
            "llm.decide_tiktok_strategy",
            accounts=accounts,
            app_version=app_version,
            fbr=fbr,
            geo_status=geo_status,
            current_state=self.state,
        )
        self.charge_cost(run, 0.04, "tiktok_daily_decision")

        today = date.today().isoformat()

        # 0. Geo check FIRST — kill any mismatch before acting
        mismatched = [a for a in accounts if geo_status.get(a["id"], {}).get("mismatch")]
        if mismatched:
            # Fix via feed-geo agent — corrects the feed location signal
            for a in mismatched:
                await self.dispatch("tiktok_feed_geo", {
                    "account_id": a["id"],
                    "target_state": a.get("home_state"),
                    "target_city": a.get("home_city"),
                })
            # If many accounts mismatched, escalate
            if len(mismatched) > len(accounts) * 0.25:
                self.escalate("tiktok_geo_mass_mismatch", {
                    "count": len(mismatched), "sample": mismatched[:5],
                })

        # 1. Dormant-phase accounts: scroll feed only, ZERO follows
        dormant = [a for a in accounts if a.get("day_in_curve", 0) < 3]
        for a in dormant:
            await self.dispatch("tiktok_scroll", {
                "account_id": a["id"],
                "date_iso": today,
                "videos_to_scroll": decision.get("dormant_scroll_count", 40),
                "min_dwell_sec": 3,
                "like_ratio": 0,   # NO likes in dormant phase
            })

        # 2. Warming-phase accounts: minimal follows + scroll
        warming = [a for a in accounts if 3 <= a.get("day_in_curve", 0) < 14]
        for a in warming:
            budget = decision.get("warming_budget_per_account", {}).get(a["id"], {})
            await self.dispatch("tiktok_scroll", {
                "account_id": a["id"],
                "date_iso": today,
                "videos_to_scroll": budget.get("scroll", 60),
                "min_dwell_sec": 3,
                "like_ratio": budget.get("like_ratio", 0.08),
            })
            if budget.get("follows", 0) > 0:
                await self.dispatch("tiktok_follow", {
                    "account_id": a["id"],
                    "count": budget["follows"],
                    "source": "fbr_top_pool",
                })

        # 3. Steady-state accounts: normal ops
        steady = [a for a in accounts if a.get("day_in_curve", 0) >= 14]
        for a in steady:
            budget = decision.get("steady_budget_per_account", {}).get(a["id"], {})
            await self.dispatch("tiktok_scroll", {
                "account_id": a["id"],
                "date_iso": today,
                "videos_to_scroll": budget.get("scroll", 80),
                "min_dwell_sec": 3,
                "like_ratio": budget.get("like_ratio", 0.12),
            })
            if budget.get("follows"):
                await self.dispatch("tiktok_follow", {
                    "account_id": a["id"], "count": budget["follows"],
                })
            if budget.get("comments"):
                await self.dispatch("tiktok_comment", {
                    "account_id": a["id"], "count": budget["comments"],
                })

        # 4. FBR tracker — retire bad sources
        await self.dispatch("tiktok_fbr_tracker", {
            "retire_below_pct": decision.get("fbr_retire_threshold", 3.0),
        })

        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_tiktok_strategy_state", self.state)

        self.report_upward(run, {
            "accounts_total": len(accounts),
            "dormant": len(dormant),
            "warming": len(warming),
            "steady": len(steady),
            "geo_mismatched": len(mismatched),
            "app_version": app_version,
            "fbr_7d_avg": fbr.get("fleet_avg_pct", 0),
        })
        return True
