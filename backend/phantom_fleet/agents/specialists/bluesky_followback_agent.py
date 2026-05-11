"""
BlueSkyFollowBackAgent — detect and record follow-backs for A/B test accuracy.

Why this is necessary:
    follow_back_rate = follows_received / follows_sent is the primary A/B
    test metric.  It closes the loop on whether the engagement strategy
    (Follow+Like vs Follow+Like+DM) actually converts into reciprocal follows.

    The follow_agent records the "send" side.  This agent provides the
    "receive" side by cross-referencing:
        - DIDs we followed in the test  (from the A/B event log)
        - DIDs that now follow us back  (from app.bsky.graph.getFollowers)

    It then records a `follow_back` event for each new match, idempotently
    (already-recorded follow_backs are skipped using the event log).

How it runs:
    Dispatched once per day by the BlueSky manager for each account that is
    enrolled in an active A/B test.  The manager passes `ab_test_id` and
    `ab_variant_id` so the agent knows which test to record against.

Pagination:
    Fetches up to MAX_FOLLOWER_PAGES pages of followers (50/page = 500 max).
    Stops early once all followed DIDs have been accounted for.  This keeps
    the daily API call cost bounded even for accounts with many followers.

Fleet-scale note:
    Only runs for accounts IN an active test — not the entire fleet.
    The cohort is typically 20–500 accounts, not 20K, so the API cost per
    run is controlled.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.bluesky_ab_test import BlueSkyABManager
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------

MAX_FOLLOWER_PAGES = 10    # 10 × 50 = 500 followers max per reconciliation run
FOLLOWERS_PER_PAGE = 50


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyFollowBackAgent(Agent):
    """
    Detect follow-backs from A/B test targets and record them.

    ctx keys:
        account_id:    str            — Phantom Fleet account ID
        session:       BlueSkySession — pre-built session
        ab_test_id:    str            — active test to record against
        ab_variant_id: str            — this account's variant in the test
        date_iso:      str
        proxy_url:     str

    Outputs (run.outputs):
        new_followbacks:  int    — number of new follow_back events recorded
        errors:           list[str]
    """

    config = AgentConfig(
        name="bluesky_followback_check",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ab_mgr = BlueSkyABManager()

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:    str            = ctx["account_id"]
        session:       BlueSkySession = ctx["session"]
        ab_test_id:    str            = ctx.get("ab_test_id", "")
        ab_variant_id: str            = ctx.get("ab_variant_id", "")
        date_iso:      str            = ctx.get("date_iso", date.today().isoformat())
        proxy_url:     str            = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        errors: list[str] = []
        new_followbacks = 0

        if not ab_test_id or not ab_variant_id:
            run.outputs["new_followbacks"] = 0
            run.outputs["errors"] = ["ab_test_id and ab_variant_id required"]
            return True

        # ---- Single event-log read for both sets (avoids double file I/O) ----
        followed_dids, already_recorded = self._ab_mgr.get_follow_reconciliation_sets(
            ab_test_id, account_id
        )
        if not followed_dids:
            log.debug(
                "[bluesky_followback/%s] No followed DIDs in test %s — skipping",
                account_id, ab_test_id,
            )
            run.outputs["new_followbacks"] = 0
            run.outputs["errors"] = errors
            return True

        # ---- Candidates: followed but not yet recorded ----
        pending = followed_dids - already_recorded
        if not pending:
            log.debug(
                "[bluesky_followback/%s] All %d followed DIDs already recorded",
                account_id, len(followed_dids),
            )
            run.outputs["new_followbacks"] = 0
            run.outputs["errors"] = errors
            return True

        self._audit({
            "event":          "bluesky_followback_start",
            "account_id":     account_id,
            "ab_test_id":     ab_test_id,
            "followed_dids":  len(followed_dids),
            "pending_check":  len(pending),
        })

        # ---- Fetch followers (paginated, capped) ----
        follower_dids: set[str] = set()
        cursor = ""
        pages_fetched = 0

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            while pages_fetched < MAX_FOLLOWER_PAGES:
                try:
                    resp = await client.get_followers(
                        actor=session.did,
                        limit=FOLLOWERS_PER_PAGE,
                        cursor=cursor,
                    )
                except BlueSkySessionExpired:
                    log.warning("[bluesky_followback/%s] Session expired", account_id)
                    errors.append("session_expired")
                    break
                except BlueSkyRateLimited as exc:
                    log.warning(
                        "[bluesky_followback/%s] Rate limited — %ds",
                        account_id, exc.retry_after_sec,
                    )
                    errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    await asyncio.sleep(min(exc.retry_after_sec, 60))
                    break
                except Exception as exc:
                    log.warning(
                        "[bluesky_followback/%s] getFollowers page %d failed: %s",
                        account_id, pages_fetched, exc,
                    )
                    errors.append(f"get_followers_error:{exc}")
                    break

                followers_page = resp.get("followers", [])
                for f in followers_page:
                    did = f.get("did", "")
                    if did:
                        follower_dids.add(did)

                pages_fetched += 1
                cursor = resp.get("cursor", "")

                # Stop early if we've seen all pending DIDs
                if pending.issubset(follower_dids):
                    break

                # Stop if no more pages
                if not cursor or len(followers_page) < FOLLOWERS_PER_PAGE:
                    break

        # Warn if we exhausted the page cap without finding all pending DIDs.
        # This means some follow-backs may be undetected — account has >500 followers.
        if pages_fetched >= MAX_FOLLOWER_PAGES and not pending.issubset(follower_dids):
            unresolved = pending - follower_dids
            log.warning(
                "[bluesky_followback/%s] Page cap (%d pages / %d followers) hit without "
                "finding all pending DIDs — %d DIDs unresolved. Account may have >%d followers.",
                account_id, MAX_FOLLOWER_PAGES, len(follower_dids),
                len(unresolved), MAX_FOLLOWER_PAGES * FOLLOWERS_PER_PAGE,
            )
            errors.append(f"page_cap_hit:{len(unresolved)}_unresolved")

        # ---- Cross-reference and record new follow_backs ----
        new_followback_dids = pending & follower_dids
        for did in new_followback_dids:
            self._ab_mgr.record_follow_back(ab_test_id, account_id, ab_variant_id, did)
            new_followbacks += 1
            log.debug(
                "[bluesky_followback/%s] New follow_back: %s (test=%s, variant=%s)",
                account_id, did, ab_test_id, ab_variant_id,
            )

        self._audit({
            "event":            "bluesky_followback_end",
            "account_id":       account_id,
            "ab_test_id":       ab_test_id,
            "followers_scanned": len(follower_dids),
            "new_followbacks":  new_followbacks,
            "errors":           len(errors),
        })

        log.info(
            "[bluesky_followback/%s] %d new follow_backs recorded (scanned %d followers)",
            account_id, new_followbacks, len(follower_dids),
        )

        run.outputs["new_followbacks"] = new_followbacks
        run.outputs["errors"]          = errors
        return True


# Public alias for manager dispatch
BlueSkyFollowBackAgent.__name__ = "BlueSkyFollowBackAgent"
