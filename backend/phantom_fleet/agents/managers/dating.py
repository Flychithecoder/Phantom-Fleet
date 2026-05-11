"""
DatingAgentManager — runs Tinder / Bumble / Hinge / Grindr on physical phones.

Where Onimator failed (user confirmed "Tinder/Bumble broken on Onimator"):
    - Play Integrity API blocks (Hinge/Bumble check hardware-backed attestation)
    - SafetyNet ctsProfileMatch (Tinder reads this on every launch)
    - Photo verification fails on fake camera → low trust score forever
    - Phone verification requires real SIM (SMS-PVA burns in hours)
    - Swipe pattern detection (bots swipe too predictably)
    - Location spoofing detection (fake GPS without motion = flag)

Phantom Fleet Dating Manager fills every gap:

    1. **Stock + Magisk-hidden phones**: keep hardware attestation clean
    2. **Real photo verification pipeline**: model handshake — the actual
       persona-owner records a short verification clip once per account at
       signup, clips stored in Content Vault for every re-verification
    3. **Real SIM pool rotation**: dedicated pool of real SIM cards for dating
       tier only, rotated with 60-day cooldowns per account
    4. **Bezier swipe biometrics**: swipe velocity, curve, and dwell sampled
       from real human recordings, locked per persona
    5. **Motion-synced location**: GPS spoof steps through a realistic walking
       path during sessions (not just a teleport)
    6. **Chat handoff to real model OR Chat AI**: first few turns auto-sent
       by the persona biometric profile, then handoff to either the real
       human owner or Phantom Fleet Chat AI agents for conversation
    7. **Auto-unmatch on CTA send**: after CTA is delivered, account unmatches
       with natural delay (not robot rage-quit)
    8. **Per-platform differentiation**: each app needs its own flow

Supported platforms (each has its own sub-agent under the manager):

    - Tinder  — swipe flow, photo carousel, strict verification
    - Bumble  — women-first flow, Bizz + BFF modes off, photo verify
    - Hinge   — Likes/Roses with prompt responses, strict verify
    - Grindr  — grid-based chat flow, tribes/interests filtering, LOW
                security posture (no SafetyNet), highest per-phone density
                (5-10 accounts), targets the trans/male creator niche that
                mainstream automation tools completely ignore — zero
                competition, 3-5x higher revenue per fan than female-mainstream

Grindr-specific decision notes (added 2026-04-11):
    - Lowest technical barrier of any dating app (no hardware attestation)
    - Highest density per phone in the dating tier (5-10 vs 2-4 on Tinder/Bumble/Hinge)
    - Chat-first UX converts 2-4x better than swipe-first apps
    - NO competitor automation tool serves this niche today → first-mover capture
    - Grindr phone verification is OPTIONAL (email signup accepted)
    - Location spoofing works reliably (no motion-check enforcement)
    - Trans/male OFM creators have 3-5x average-revenue-per-user on OF
"""
from __future__ import annotations

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun


class DatingAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="dating",
        max_iterations=12,
        max_usd_per_run=0.20,
        max_usd_per_session=3.50,
        confirmation_required_for=(
            "approve_new_verification_clip",
            "mass_unmatch",
            "photo_set_rotation",
        ),
        allowed_tools=(
            "db.load_dating_accounts",
            "db.load_photo_sets",
            "db.load_verification_vault",
            "db.load_sim_pool",
            "db.save_dating_strategy_state",
            "llm.decide_dating_strategy",
        ),
        supervises=(
            "swipe",               # Tinder / Bumble / Hinge swipe logic
            "grindr_grid",         # Grindr grid-based browsing + filters
            "grindr_chat",         # Grindr chat-first conversation + CTA
            "photo_rotation",
            "chat_handoff",
            "dating_verification",
        ),
        escalates_to="chief",
        report_cadence_min=15,
    )

    # Per-platform account density ceilings (hard limits)
    MAX_ACCOUNTS_PER_PHONE = {
        "tinder": 4,
        "bumble": 4,
        "hinge": 3,
        "grindr": 10,  # lowest security = highest density
    }

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts = await self.tool("db.load_dating_accounts")
        photo_sets = await self.tool("db.load_photo_sets")
        verification_vault = await self.tool("db.load_verification_vault")
        sim_pool = await self.tool("db.load_sim_pool")

        decision = await self.tool(
            "llm.decide_dating_strategy",
            accounts=accounts,
            photo_sets=photo_sets,
            verification_vault=verification_vault,
            sim_pool=sim_pool,
            current_state=self.state,
        )
        self.charge_cost(run, 0.05, "dating_daily_decision")

        # 1. Verification clip check — any account in the queue gets handled first
        for a in accounts:
            if a.get("needs_verification"):
                await self.dispatch("dating_verification", {
                    "account_id": a["id"],
                    "platform": a["platform"],
                    "vault_clip_id": a.get("vault_clip_id"),
                })

        # 2. Swipe vs Grid dispatch — platform-specific sub-agents
        for a in accounts:
            platform = a["platform"]
            budget = decision.get("action_budget_per_account", {}).get(a["id"], {})
            if not budget:
                continue

            if platform in ("tinder", "bumble", "hinge"):
                await self.dispatch("swipe", {
                    "account_id": a["id"],
                    "platform": platform,
                    "swipe_count": budget.get("swipes", 30),
                    "right_ratio": budget.get("right_ratio", 0.15),
                    "session_minutes": budget.get("session_minutes", 8),
                    "bezier_profile": a.get("biometric_swipe_profile", "default"),
                })
            elif platform == "grindr":
                await self.dispatch("grindr_grid", {
                    "account_id": a["id"],
                    "tap_filter": a.get("tap_filter"),
                    "distance_km": budget.get("grid_distance_km", 5),
                    "profile_views_count": budget.get("profile_views", 40),
                    "profile_dwell_range_sec": (2, 15),
                    "chat_open_probability": budget.get("chat_open_probability", 0.10),
                })

        # 3. Chat handoff — process inbound messages
        for a in accounts:
            if a.get("unread_matches", 0) == 0:
                continue
            if a.get("platform") == "grindr":
                await self.dispatch("grindr_chat", {
                    "account_id": a["id"],
                    "handoff_mode": a.get("handoff_mode", "chat_ai"),
                    "cta_link": a.get("cta_link"),
                    "max_turns_before_cta": decision.get("grindr_turns_before_cta", 3),
                })
            else:
                await self.dispatch("chat_handoff", {
                    "account_id": a["id"],
                    "platform": a["platform"],
                    "handoff_mode": a.get("handoff_mode", "chat_ai"),
                    "cta_link": a.get("cta_link"),
                    "max_turns_before_cta": decision.get("turns_before_cta", 4),
                })

        # 4. Photo rotation — weekly refresh of approved sets
        if decision.get("photo_rotation_run"):
            for a in accounts:
                await self.dispatch("photo_rotation", {
                    "account_id": a["id"],
                    "new_photo_set_id": decision.get("photo_assignments", {}).get(a["id"]),
                })

        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_dating_strategy_state", self.state)

        self.report_upward(run, {
            "total_dating_accounts": len(accounts),
            "tinder":  sum(1 for a in accounts if a.get("platform") == "tinder"),
            "bumble":  sum(1 for a in accounts if a.get("platform") == "bumble"),
            "hinge":   sum(1 for a in accounts if a.get("platform") == "hinge"),
            "grindr":  sum(1 for a in accounts if a.get("platform") == "grindr"),
            "sim_pool_size": sim_pool.get("size", 0),
            "sim_pool_available": sim_pool.get("available", 0),
            "verification_queue": sum(1 for a in accounts if a.get("needs_verification")),
        })
        return True
