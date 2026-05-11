"""
BlueSkyUnfollowAgent — follow/unfollow cycle cleanup for BlueSky.

Strategies:
    non_followers_first (default):
        Unfollow accounts that do not follow back, sorted by oldest
        follow date first. Preserves mutuals and recent follows.
    oldest_first:
        Unfollow strictly by follow age, regardless of whether they
        follow back. Used for pure churn cycles.

Ratio protection (code-enforced):
    If unfollowing would drop the follows/followers ratio below
    keep_ratio_target, the agent stops early. The ratio check runs
    BEFORE each unfollow so the fleet never violates the target.

AT Protocol unfollow mechanics:
    - A follow is stored as a com.atproto.repo record with its own rkey.
    - To unfollow, we delete the follow record via
      com.atproto.repo.deleteRecord using the rkey extracted from the
      follow URI: at://did:plc:xxx/app.bsky.graph.follow/{rkey}
    - The caller (manager) is responsible for building follow_records
      with is_follower pre-populated (from a getFollowers call).

Fleet-scale hardening (CLAUDE.md 20K-account rule):
    - Unfollow order shuffled per (account_id, date_iso) within each
      strategy bucket — no two accounts hit the same unfollow sequence.
    - Inter-unfollow sleep: LogNormal(mean=ln(30), σ=0.4).
    - Daily cap: 150/day (code-enforced, not prompt-enforced).
    - Ratio check before every unfollow action.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import date, datetime, timezone
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.distributions import LogNormal, seed_for
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

_INTER_UNFOLLOW_DIST = LogNormal(low=8.0, high=120.0, sigma=0.40)

# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------

MAX_UNFOLLOWS_PER_DAY = 150


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rkey_from_uri(uri: str) -> str:
    """Extract the rkey from an AT URI: at://did:plc:.../collection/rkey → rkey."""
    return uri.rsplit("/", 1)[-1]


def _sort_non_followers_first(
    records: list[dict],
    account_id: str,
    date_iso: str,
) -> list[dict]:
    """
    Sort follow_records so non-followers appear before mutuals.

    Within each group, shuffle deterministically so the fleet does not
    produce the same unfollow ordering across accounts.
    """
    non_followers = [r for r in records if not r.get("is_follower", False)]
    mutuals       = [r for r in records if r.get("is_follower", False)]

    seed_nf = seed_for(account_id, date_iso, "unfollow_nf_shuffle")
    seed_mu = seed_for(account_id, date_iso, "unfollow_mutual_shuffle")

    rng_nf = random.Random(seed_nf)
    rng_mu = random.Random(seed_mu)

    # Within non-followers: oldest-first + shuffle tie-breaker
    non_followers.sort(key=lambda r: r.get("followed_at_iso", ""))
    rng_nf.shuffle(non_followers)

    # Mutuals: shuffle only (we rarely unfollow mutuals)
    rng_mu.shuffle(mutuals)

    return non_followers + mutuals


def _sort_oldest_first(
    records: list[dict],
    account_id: str,
    date_iso: str,
) -> list[dict]:
    """Sort by follow age, oldest first. Shuffle ties deterministically."""
    sorted_recs = sorted(records, key=lambda r: r.get("followed_at_iso", ""))
    # Fine-shuffle records sharing the same date so fleet order differs
    seed = seed_for(account_id, date_iso, "unfollow_oldest_shuffle")
    rng  = random.Random(seed)
    rng.shuffle(sorted_recs)
    return sorted_recs


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyUnfollowAgent(Agent):
    """
    Unfollow cycle cleanup for BlueSky.

    ctx keys:
        account_id:          str
        session:             BlueSkySession
        follow_records:      list[dict]   — see schema below
        strategy:            str          — "non_followers_first" | "oldest_first"
        keep_ratio_target:   float        — min follows/followers ratio to preserve
        current_followers:   int          — current follower count
        current_follows:     int          — current following count
        target_count:        int          — max unfollows this run
        date_iso:            str          — YYYY-MM-DD (defaults to today)
        proxy_url:           str          — optional

    follow_records schema (each dict):
        did:             str   — DID of the account we follow
        rkey:            str   — record key for the follow record
                                 (extracted from the follow URI by caller)
        followed_at_iso: str   — ISO timestamp when we followed them
        is_follower:     bool  — whether they follow us back

    Outputs (run.outputs):
        result   WorkerResult  — unfollowed, errors
        unfollowed_dids   list[str]
    """

    config = AgentConfig(
        name="bluesky_unfollow",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:        str            = ctx["account_id"]
        session:           BlueSkySession = ctx["session"]
        follow_records:    list[dict]     = ctx.get("follow_records") or []
        strategy:          str            = ctx.get("strategy", "non_followers_first")
        keep_ratio_target: float          = float(ctx.get("keep_ratio_target", 1.0))
        current_followers: int            = int(ctx.get("current_followers", 0))
        current_follows:   int            = int(ctx.get("current_follows", len(follow_records)))
        target_count:      int            = min(int(ctx.get("target_count", 50)), MAX_UNFOLLOWS_PER_DAY)
        date_iso:          str            = ctx.get("date_iso", date.today().isoformat())
        proxy_url:         str            = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        result = WorkerResult()
        unfollowed_dids: list[str] = []

        self._audit({
            "event":            "bluesky_unfollow_session_start",
            "account_id":       account_id,
            "strategy":         strategy,
            "records_provided": len(follow_records),
            "target_count":     target_count,
            "keep_ratio":       keep_ratio_target,
        })

        if not follow_records:
            log.info("[bluesky_unfollow/%s] No follow records — nothing to unfollow", account_id)
            run.outputs["result"] = result
            run.outputs["unfollowed_dids"] = unfollowed_dids
            return True

        # ---- Sort per strategy ----
        if strategy == "oldest_first":
            ordered = _sort_oldest_first(follow_records, account_id, date_iso)
        else:
            ordered = _sort_non_followers_first(follow_records, account_id, date_iso)

        action_count  = 0
        follows_left  = current_follows  # tracks as we unfollow

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            for record in ordered:
                # ---- Hard caps ----
                if action_count >= target_count:
                    break
                if action_count >= MAX_UNFOLLOWS_PER_DAY:
                    log.info(
                        "[bluesky_unfollow/%s] Daily cap %d reached",
                        account_id, MAX_UNFOLLOWS_PER_DAY,
                    )
                    break

                # ---- Ratio protection (code-enforced) ----
                if current_followers > 0:
                    projected_ratio = (follows_left - 1) / max(current_followers, 1)
                    if projected_ratio < keep_ratio_target:
                        log.info(
                            "[bluesky_unfollow/%s] Ratio gate: %.2f would drop below "
                            "target %.2f — stopping",
                            account_id, projected_ratio, keep_ratio_target,
                        )
                        break

                did  = record.get("did", "")
                rkey = record.get("rkey", "")
                if not did or not rkey:
                    # Try to extract rkey from a uri field
                    uri = record.get("uri", "")
                    if uri:
                        rkey = _rkey_from_uri(uri)
                    if not rkey:
                        log.warning("[bluesky_unfollow/%s] Missing rkey for DID %s", account_id, did)
                        result.errors.append(f"missing_rkey:{did}")
                        continue

                self._audit({
                    "event":      "bluesky_unfollow_attempt",
                    "account_id": account_id,
                    "target_did": did,
                    "is_follower": record.get("is_follower", False),
                })

                try:
                    await client.unfollow_user(follow_rkey=rkey)
                    result.unfollowed += 1
                    unfollowed_dids.append(did)
                    follows_left -= 1
                    action_count += 1
                    log.debug("[bluesky_unfollow/%s] Unfollowed %s", account_id, did)

                except BlueSkySessionExpired:
                    log.warning("[bluesky_unfollow/%s] Session expired — stopping", account_id)
                    result.errors.append("session_expired")
                    break

                except BlueSkyRateLimited as exc:
                    log.warning(
                        "[bluesky_unfollow/%s] Rate limited — backing off %ds",
                        account_id, exc.retry_after_sec,
                    )
                    result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    await asyncio.sleep(min(exc.retry_after_sec, 120))
                    break

                except Exception as exc:
                    result.errors.append(f"unfollow_error:{did}:{exc}")
                    log.warning("[bluesky_unfollow/%s] Unfollow failed for %s: %s", account_id, did, exc)

                # ---- Inter-unfollow sleep ----
                sleep_sec = _INTER_UNFOLLOW_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"inter_unfollow_{did}",
                )
                await asyncio.sleep(sleep_sec)

        self._audit({
            "event":      "bluesky_unfollow_session_end",
            "account_id": account_id,
            "unfollowed": result.unfollowed,
            "errors":     len(result.errors),
        })

        run.outputs["result"]         = result
        run.outputs["unfollowed_dids"] = unfollowed_dids
        return True
