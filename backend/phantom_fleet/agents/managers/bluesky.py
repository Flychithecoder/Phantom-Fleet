"""
BlueSkyAgentManager — first-mover advantage in the AT Protocol ecosystem.

Why BlueSky is strategically valuable despite small audience:
    - ZERO fingerprint ML detection currently (year 2 of the platform lifecycle)
    - Open AT Protocol = no reverse engineering needed, custom clients legal
    - 20+ accounts per phone trivially (no phone verification, email-only signup)
    - "Twitter refugees" are a meaningful niche (tech, journalist, creator)
    - Option value: if BlueSky hits mainstream in 2027-2028, you already own it
    - Marketing: "Phantom Fleet runs on 11 platforms including BlueSky" is a
      differentiator — no competitor currently automates BlueSky at scale on
      real devices

Real-world intel (2026-04-11):
    OFM agencies on Telegram are currently using "Ghost BlueSky", a
    Chrome Extension + Ads Power (antidetect browser) combo that offers:
        - Mass Follow (with pause-after-follow + pause-after-skip min/max)
        - Mass Unfollow
        - Mass Likes
        - Autopilot mode
        - Unlimited number of accounts
        - Ads Power antidetect-browser integration
        - Skip already-followed filter
        - Daily limit per run
        - Blacklist
        - Chrome Extension delivery

    Phantom Fleet's BlueSky Agent Manager MUST match every one of those
    features AND leap them:
        - Real unroot Samsung device (hardware attestation = free trust) vs
          Ads Power browser fingerprints
        - Kotlin Companion APK driver vs Chrome Extension
        - Per-session unique residential IPs pinned to persona home region
        - LogNormal-sampled pause timing (shape matches real humans, not
          a flat uniform range)
        - 90-day fleet-wide target_history dedup (beats per-account "skip
          already followed" by several orders of magnitude)
        - Shared persona blacklist across every account in the persona cohort
        - Manager-level "autopilot" makes STRATEGIC decisions (which sources
          to prioritize, when to promote persona, when to pause cohort on
          cluster signals) — not just a loop on a fixed config

Unique BlueSky technical traits the manager exploits:
    - Native multi-account switching (no AppCloner/Nomixcloner needed)
    - AT Protocol exposes the firehose (scraping is trivial, server-side free)
    - Custom feeds are a first-class concept (algorithm transparency = control)
    - Labels + moderation lists are decentralized (can be bypassed by client)
    - No shadowban infrastructure yet — bans are server-enforced only

Owns:
    - BlueSkyPostAgent           — post / reply / repost / thread
    - BlueSkyFollowAgent         — mass follow with persona-pinned regions
    - BlueSkyUnfollowAgent       — mass unfollow with age + ratio optimization
    - BlueSkyLikeAgent           — mass like with target-scored feed sampling
    - BlueSkyScrapeAgent         — firehose scraping via AT Protocol
    - BlueSkyFeedAgent           — custom feed creation + curation
    - BlueSkyLabelerAgent        — publish labeler records for moderation lists
    - BlueSkyCrossPostAgent      — bring content from IG / X / Threads into BlueSky
    - BlueSkyABTestAgent         — AI-driven A/B test lifecycle manager
    - BlueSkyFollowBackAgent     — daily follow-back reconciliation for A/B accuracy

A/B testing integration:
    The manager builds a `variant_map` at the start of every run by loading
    active tests from BlueSkyABManager. The map is keyed by account_id and
    contains {test_id, variant_id, strategy}. This map drives:

    1. Variant enforcement — follow/like dispatches inject ab_test_id +
       ab_variant_id into the specialist ctx so events are recorded.

    2. DM gating — DM dispatch is ONLY sent to accounts whose variant
       strategy includes DM (follow_like_dm, follow_post_dm). Variant A
       accounts (follow_like_only, follow_only) never receive DM dispatch,
       ensuring the test measures a real behavioural difference.

    3. Follow-back reconciliation — after the follow pass, a
       bluesky_followback_check dispatch runs for every test-enrolled
       account to detect and record follow_backs that day.

    4. Test evaluation — once the decision layer flags ab_test_operation,
       the AI agent evaluates and concludes the test with LLM analysis.
"""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import date

from .base import ManagerAgent, ManagerConfig
from ..base import AgentRun
from ...core.bluesky_ab_test import BlueSkyABManager, BlueSkyEngagementVariant

log = logging.getLogger(__name__)

# Variants where DM dispatch is enabled
_DM_VARIANTS = {
    BlueSkyEngagementVariant.FOLLOW_LIKE_DM.value,
    BlueSkyEngagementVariant.FOLLOW_POST_DM.value,
}


class BlueSkyAgentManager(ManagerAgent):
    config = ManagerConfig(
        name="bluesky",
        max_iterations=12,
        max_usd_per_run=0.10,
        max_usd_per_session=2.00,
        confirmation_required_for=(
            "mass_post_burst",
            "bulk_username_grab",
        ),
        allowed_tools=(
            "db.load_bluesky_accounts",
            "db.load_custom_feeds",
            "db.load_target_topics",
            "db.load_persona_blacklist",
            "db.load_bluesky_source_pool",
            "db.save_bluesky_strategy_state",
            "llm.decide_bluesky_strategy",
            "atprotocol.firehose_tail",
        ),
        supervises=(
            "bluesky_post",
            "bluesky_follow",
            "bluesky_unfollow",
            "bluesky_like",
            "bluesky_scrape",
            "bluesky_feed",
            "bluesky_labeler",
            "bluesky_crosspost",
            "bluesky_dm_chat",
            "bluesky_ab_test",
            "bluesky_followback_check",
        ),
        escalates_to="chief",
        report_cadence_min=30,
    )

    MAX_FOLLOWS_PER_DAY_PER_ACCOUNT    = 100  # must match BlueSkyFollowAgent.MAX_FOLLOWS_PER_DAY
    MAX_UNFOLLOWS_PER_DAY_PER_ACCOUNT  = 150
    MAX_LIKES_PER_DAY_PER_ACCOUNT      = 300

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ab_mgr = BlueSkyABManager()

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts     = await self.tool("db.load_bluesky_accounts")
        custom_feeds = await self.tool("db.load_custom_feeds")
        topics       = await self.tool("db.load_target_topics", platform="bluesky")
        blacklist    = await self.tool("db.load_persona_blacklist", platform="bluesky")
        source_pool  = await self.tool("db.load_bluesky_source_pool")

        # ----------------------------------------------------------------
        # A/B: Build variant_map {account_id: {test_id, variant_id, strategy}}
        # This drives event recording + DM gating for the entire run.
        # ----------------------------------------------------------------
        variant_map: dict[str, dict] = {}
        active_tests = self._ab_mgr.list_active_tests()
        for spec in active_tests:
            for account_id in spec.cohort_account_ids:
                variant = self._ab_mgr.get_variant_for_account(account_id, spec)
                if variant:
                    if account_id in variant_map:
                        log.warning(
                            "[bluesky_manager] Account %s is enrolled in multiple active tests "
                            "(%s and %s) — using %s for this run. Avoid overlapping cohorts.",
                            account_id, variant_map[account_id]["test_id"],
                            spec.test_id, spec.test_id,
                        )
                    variant_map[account_id] = {
                        "test_id":    spec.test_id,
                        "variant_id": variant.variant_id,
                        "strategy":   variant.engagement_strategy.value,
                    }

        # ----------------------------------------------------------------
        # LLM strategic decision — now includes A/B context
        # ----------------------------------------------------------------
        decision = await self.tool(
            "llm.decide_bluesky_strategy",
            accounts=accounts,
            custom_feeds=custom_feeds,
            topics=topics,
            source_pool_size=len(source_pool or []),
            current_state=self.state,
            ab_active_tests=[
                {
                    "test_id":    spec.test_id,
                    "name":       spec.name,
                    "status":     spec.status,
                    "cohort":     len(spec.cohort_account_ids),
                    "end_date":   spec.end_date_iso,
                    "min_sample": spec.min_sample_size,
                }
                for spec in active_tests
            ],
        )
        self.charge_cost(run, 0.03, "bluesky_daily_decision")

        today = date.today().isoformat()

        # ----------------------------------------------------------------
        # 1. Cross-post from IG / X / Threads into BlueSky
        # ----------------------------------------------------------------
        for persona_id in decision.get("crosspost_personas", []):
            account_data = next(
                (a for a in (accounts or []) if a.get("persona_id") == persona_id),
                None,
            )
            if account_data is None:
                log.warning(
                    "[bluesky_manager] Crosspost: persona %s not in accounts list — skipping",
                    persona_id,
                )
                continue
            session = account_data.get("session")
            if session is None:
                log.warning(
                    "[bluesky_manager] Crosspost: persona %s has no session — skipping",
                    persona_id,
                )
                continue
            await self.dispatch("bluesky_crosspost", {
                "account_id":       account_data["account_id"],
                "session":          session,
                "persona_id":       persona_id,
                "source_posts":     account_data.get("pending_crossposts", []),
                "source_platforms": decision.get("crosspost_sources", ["instagram", "x"]),
                "max_per_day":      decision.get("crosspost_per_day", 3),
                "date_iso":         today,
            })

        # ----------------------------------------------------------------
        # 2. Native BlueSky post scheduling per persona
        # ----------------------------------------------------------------
        for persona_id in decision.get("native_post_personas", []):
            account_data = next(
                (a for a in (accounts or []) if a.get("persona_id") == persona_id),
                None,
            )
            if account_data is None:
                log.warning(
                    "[bluesky_manager] Post: persona %s not in accounts list — skipping",
                    persona_id,
                )
                continue
            session = account_data.get("session")
            if session is None:
                log.warning(
                    "[bluesky_manager] Post: persona %s has no session — skipping",
                    persona_id,
                )
                continue
            template_pool = account_data.get("template_pool") or []
            if not template_pool:
                log.warning(
                    "[bluesky_manager] Post: persona %s has no template_pool — skipping",
                    persona_id,
                )
                continue
            await self.dispatch("bluesky_post", {
                "account_id":       account_data["account_id"],
                "session":          session,
                "persona_id":       persona_id,
                "template_pool":    template_pool,
                "posts_to_attempt": decision.get("native_posts_per_day", 2),
                "date_iso":         today,
            })

        # ----------------------------------------------------------------
        # 3. MASS FOLLOW — inject A/B test metadata when account is enrolled
        #    so BlueSkyFollowAgent records follow events to the test.
        # ----------------------------------------------------------------

        # Pre-compute blacklist set once for O(1) DID lookup.
        _blacklist_set: set[str] = set(blacklist or [])

        for account_id, follow_plan in decision.get("follow_plan", {}).items():
            capped = min(follow_plan.get("count", 0), self.MAX_FOLLOWS_PER_DAY_PER_ACCOUNT)
            if capped <= 0:
                continue

            account_data = next(
                (a for a in (accounts or []) if a.get("account_id") == account_id),
                None,
            )
            if account_data is None:
                log.warning(
                    "[bluesky_manager] Follow: account %s not in accounts list — skipping",
                    account_id,
                )
                continue

            # Resolve target DIDs from source pool.
            # Entries may be plain DID strings or dicts {did, handle, ...}.
            # Filter by source_pool_id (pool_id field on dict entries) when set,
            # and strip blacklisted DIDs before handing to the follow agent.
            #
            # CRITICAL 20K-rule: shuffle the pool per-account so each account
            # follows a different subset of targets. Without this, all accounts
            # draw the same first N DIDs → identical network graph edges → cluster.
            pool_id = follow_plan.get("source_pool_id")
            pool_seed = int(
                hashlib.sha256(f"{account_id}|{today}|pool_order".encode()).hexdigest()[:8], 16
            )
            shuffled_pool = list(source_pool or [])
            random.Random(pool_seed).shuffle(shuffled_pool)

            target_dids: list[str] = []
            for entry in shuffled_pool:
                did = entry if isinstance(entry, str) else entry.get("did", "")
                if not did or did in _blacklist_set:
                    continue
                if pool_id and isinstance(entry, dict) and entry.get("pool_id") != pool_id:
                    continue
                target_dids.append(did)
                if len(target_dids) >= capped:
                    break

            if not target_dids:
                log.warning(
                    "[bluesky_manager] Follow: no target DIDs for account %s "
                    "(pool_id=%s, pool_size=%d) — skipping",
                    account_id, pool_id, len(source_pool or []),
                )
                continue

            session = account_data.get("session")
            if session is None:
                log.warning(
                    "[bluesky_manager] Follow: account %s has no session — skipping",
                    account_id,
                )
                continue

            follow_ctx: dict = {
                "account_id":  account_id,
                "session":     session,
                "target_dids": target_dids,
                "date_iso":    today,
            }
            # Inject A/B metadata if enrolled
            ab = variant_map.get(account_id)
            if ab:
                follow_ctx["ab_test_id"]    = ab["test_id"]
                follow_ctx["ab_variant_id"] = ab["variant_id"]

            await self.dispatch("bluesky_follow", follow_ctx)

        # ----------------------------------------------------------------
        # 4. MASS UNFOLLOW
        # ----------------------------------------------------------------
        for account_id, unfollow_plan in decision.get("unfollow_plan", {}).items():
            capped = min(
                unfollow_plan.get("count", 0), self.MAX_UNFOLLOWS_PER_DAY_PER_ACCOUNT
            )
            if capped <= 0:
                continue
            account_data = next(
                (a for a in (accounts or []) if a.get("account_id") == account_id),
                None,
            )
            if account_data is None:
                log.warning(
                    "[bluesky_manager] Unfollow: account %s not in accounts list — skipping",
                    account_id,
                )
                continue
            session = account_data.get("session")
            if session is None:
                log.warning(
                    "[bluesky_manager] Unfollow: account %s has no session — skipping",
                    account_id,
                )
                continue
            await self.dispatch("bluesky_unfollow", {
                "account_id":       account_id,
                "session":          session,
                "target_count":     capped,
                "strategy":         unfollow_plan.get("strategy", "non_followers_first"),
                "keep_ratio_target": unfollow_plan.get("keep_ratio", 1.2),
                # Follower/follow counts from account metadata for ratio gate
                "current_followers": int(account_data.get("follower_count", 0)),
                "current_follows":   int(account_data.get("follows_count", 0)),
                # follow_records: pre-fetched by caller or loaded from account metadata
                "follow_records":   account_data.get("follow_records") or [],
                "date_iso":         today,
            })

        # ----------------------------------------------------------------
        # 5. MASS LIKE — inject A/B metadata; apply variant-specific feed source
        # ----------------------------------------------------------------
        for account_id, like_plan in decision.get("like_plan", {}).items():
            capped = min(like_plan.get("count", 0), self.MAX_LIKES_PER_DAY_PER_ACCOUNT)
            if capped <= 0:
                continue

            account_data = next(
                (a for a in (accounts or []) if a.get("account_id") == account_id),
                None,
            )
            if account_data is None:
                log.warning(
                    "[bluesky_manager] Like: account %s not in accounts list — skipping",
                    account_id,
                )
                continue

            ab = variant_map.get(account_id)
            # Variant params can override feed source for the like pass
            feed_source = like_plan.get("feed_source", "timeline")
            if ab and ab.get("strategy") == BlueSkyEngagementVariant.FOLLOW_LIKE_DM.value:
                # DM variant uses search feed to find higher-intent targets
                feed_source = like_plan.get("feed_source", "search")

            session = account_data.get("session")
            if session is None:
                log.warning(
                    "[bluesky_manager] Like: account %s has no session — skipping",
                    account_id,
                )
                continue

            like_ctx: dict = {
                "account_id":     account_id,
                "session":        session,
                "target_count":   capped,
                "feed_source":    feed_source,
                "topic_affinity": like_plan.get("topic_affinity", topics),
                "date_iso":       today,
            }
            if ab:
                like_ctx["ab_test_id"]    = ab["test_id"]
                like_ctx["ab_variant_id"] = ab["variant_id"]

            await self.dispatch("bluesky_like", like_ctx)

        # ----------------------------------------------------------------
        # 6. DM CHAT — VARIANT-GATED
        #    Only dispatched to accounts where the A/B variant strategy
        #    includes DM (follow_like_dm, follow_post_dm).
        #    Accounts NOT in a test receive DM if decision enables it.
        #    Accounts IN a test only receive DM if their variant requires it.
        # ----------------------------------------------------------------
        for account_id, dm_plan in decision.get("dm_plan", {}).items():
            ab = variant_map.get(account_id)

            # Test-enrolled: enforce variant gating before loading account data
            if ab and ab["strategy"] not in _DM_VARIANTS:
                log.debug(
                    "[bluesky_manager] Skipping DM for %s — variant %s is non-DM",
                    account_id, ab["strategy"],
                )
                continue

            account_data = next(
                (a for a in (accounts or []) if a.get("account_id") == account_id),
                None,
            )
            if account_data is None:
                log.warning(
                    "[bluesky_manager] DM: account %s not in accounts list — skipping",
                    account_id,
                )
                continue

            session = account_data.get("session")
            if session is None:
                log.warning(
                    "[bluesky_manager] DM: account %s has no session — skipping",
                    account_id,
                )
                continue

            dm_ctx: dict = {
                "account_id": account_id,
                "session":    session,
                "date_iso":   today,
            }
            if ab:
                dm_ctx["ab_test_id"]    = ab["test_id"]
                dm_ctx["ab_variant_id"] = ab["variant_id"]

            await self.dispatch("bluesky_dm_chat", dm_ctx)

        # ----------------------------------------------------------------
        # 7. Firehose scraping for target audience discovery
        # ----------------------------------------------------------------
        if decision.get("firehose_sample"):
            # Use a dedicated scraper account if the LLM specifies one,
            # otherwise fall back to the first available account.
            scraper_id   = decision.get("scraper_account_id", "")
            scraper_data = next(
                (a for a in (accounts or []) if a.get("account_id") == scraper_id),
                (accounts or [None])[0],
            )
            if scraper_data:
                scraper_session = scraper_data.get("session")
                if scraper_session is None:
                    log.warning("[bluesky_manager] Scrape: scraper account has no session — skipping")
                else:
                    existing_pool = [
                        entry if isinstance(entry, str) else entry.get("did", "")
                        for entry in (source_pool or [])
                    ]
                    await self.dispatch("bluesky_scrape", {
                        "account_id":        scraper_data["account_id"],
                        "session":           scraper_session,
                        "topics":            topics,
                        "max_dids":          decision.get("firehose_sample_dids", 200),
                        "existing_did_pool": [d for d in existing_pool if d],
                    })
            else:
                log.warning("[bluesky_manager] Scrape: no accounts available — skipping")

        # ----------------------------------------------------------------
        # 8. Custom feed maintenance
        # ----------------------------------------------------------------
        for feed in custom_feeds or []:
            if feed.get("refresh_due"):
                feed_persona = feed.get("persona_id", "")
                account_data = next(
                    (a for a in (accounts or []) if a.get("persona_id") == feed_persona),
                    None,
                )
                if account_data is None:
                    log.warning(
                        "[bluesky_manager] Feed: persona %s not in accounts list — skipping feed %s",
                        feed_persona, feed.get("id"),
                    )
                    continue
                session = account_data.get("session")
                if session is None:
                    log.warning(
                        "[bluesky_manager] Feed: persona %s has no session — skipping feed %s",
                        feed_persona, feed.get("id"),
                    )
                    continue
                await self.dispatch("bluesky_feed", {
                    "account_id":       account_data["account_id"],
                    "session":          session,
                    "feed_id":          feed["id"],
                    "persona_id":       feed_persona,
                    "display_name":     feed.get("display_name", feed["id"]),
                    "description":      feed.get("description", ""),
                    "feed_service_url": feed.get("feed_service_url", ""),
                    "operation":        feed.get("operation", "refresh"),
                    "algorithm":        feed.get("algorithm", "topic_affinity"),
                    "date_iso":         today,
                })

        # ----------------------------------------------------------------
        # 9. Labeler publishing (weekly cadence only)
        # ----------------------------------------------------------------
        if ctx.get("is_weekly"):
            for account_data in (accounts or []):
                if not account_data.get("run_labeler"):
                    continue
                session = account_data.get("session")
                if session is None:
                    continue
                await self.dispatch("bluesky_labeler", {
                    "account_id":   account_data["account_id"],
                    "session":      session,
                    "date_iso":     today,
                    "label_values": account_data.get("labeler_label_values", []),
                })

        # ----------------------------------------------------------------
        # 10. Follow-back reconciliation — runs for every test-enrolled account.
        #     Detects which followed DIDs have followed back and records
        #     follow_back events, closing the measurement loop for follow_back_rate.
        # ----------------------------------------------------------------
        for account_id, ab in variant_map.items():
            # Only run for accounts that were in the follow plan this cycle
            # OR always run if the manager is in reconcile-only mode
            account_data = next(
                (a for a in (accounts or []) if a.get("account_id") == account_id),
                None,
            )
            if account_data is None:
                continue
            await self.dispatch("bluesky_followback_check", {
                "account_id":    account_id,
                "session":       account_data.get("session"),
                "ab_test_id":    ab["test_id"],
                "ab_variant_id": ab["variant_id"],
                "date_iso":      today,
            })

        # ----------------------------------------------------------------
        # 11. A/B test management — evaluate / create / rollout / status
        # ----------------------------------------------------------------
        ab_op = decision.get("ab_test_operation")
        if ab_op == "evaluate":
            await self.dispatch("bluesky_ab_test", {
                "operation": "evaluate",
                "test_id":   decision.get("ab_test_id", ""),
                "use_llm":   True,
            })
        elif ab_op == "create":
            await self.dispatch("bluesky_ab_test", {
                "operation":      "create",
                "account_ids":    decision.get("ab_test_cohort", []),
                "test_name":      decision.get("ab_test_name", f"BlueSky AB {today}"),
                "niche":          decision.get("persona_niche", "lifestyle"),
                "start_date_iso": today,
                "end_date_iso":   decision.get("ab_test_end_date", ""),
                "use_llm":        True,
            })
        elif ab_op == "rollout":
            # Conclude the test and pull winning params
            await self.dispatch("bluesky_ab_test", {
                "operation": "rollout",
                "test_id":   decision.get("ab_test_id", ""),
            })
        else:
            # Daily free status snapshot — always runs, no LLM cost
            await self.dispatch("bluesky_ab_test", {
                "operation": "status",
            })

        # ----------------------------------------------------------------
        # Persist state + report upward
        # ----------------------------------------------------------------
        self.state.update(decision.get("state_update", {}))
        await self.tool("db.save_bluesky_strategy_state", self.state)

        self.report_upward(run, {
            "accounts_total":   len(accounts or []),
            "custom_feeds":     len(custom_feeds or []),
            "blacklist_size":   len(blacklist or []),
            "source_pool_size": len(source_pool or []),
            "first_mover_phase": self.state.get("phase", "land_grab"),
            "ab_active_tests":  len(active_tests),
            "ab_enrolled_accounts": len(variant_map),
            "autopilot_active": True,
        })
        return True
