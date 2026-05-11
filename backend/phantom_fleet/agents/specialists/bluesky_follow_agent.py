"""
BlueSkyFollowAgent — follow users on BlueSky via AT Protocol.

AT Protocol notes:
    - BlueSky requires DIDs (Decentralised Identifiers) for follow operations.
    - Handles can be resolved to DIDs via client.get_profile(handle).
    - Follow record: com.atproto.repo.createRecord → app.bsky.graph.follow
    - No per-account numeric ID needed — DID is the universal identifier.

Fleet-scale hardening (CLAUDE.md 20K account rule):
    - Target list shuffled per (account_id, date_iso) — fleet has no
      homogeneous target sequence.
    - Inter-follow sleep: LogNormal(mean=ln(25), σ=0.4) — log-normal
      histogram, not uniform.
    - Daily cap: 100 follows/day (BlueSky is more lenient than X) —
      enforced by code.
    - already_following detected from 403 / AlreadyExists error response.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import date

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
# Timing distributions
# ---------------------------------------------------------------------------

# Inter-follow sleep: LogNormal(mean=ln(25), σ=0.4)
# median ~25s — more relaxed than X because BlueSky is more tolerant
_INTER_FOLLOW_DIST = LogNormal(low=8.0, high=120.0, sigma=0.40)

# ---------------------------------------------------------------------------
# Daily cap (code-enforced)
# ---------------------------------------------------------------------------

MAX_FOLLOWS_PER_DAY = 100


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyFollowAgent(Agent):
    """
    Specialist agent: follow users on BlueSky for one account.

    ctx keys:
        account_id     (str)          — Phantom Fleet account ID
        session        (BlueSkySession) — pre-built session
        target_dids    (list[str])    — target DIDs to follow (preferred)
        target_handles (list[str])    — target handles to follow (resolved to DIDs)
        date_iso       (str)          — YYYY-MM-DD (defaults to today)
        proxy_url      (str)          — SOCKS5 proxy (optional)

    Either target_dids or target_handles (or both) must be provided.
    If target_handles are given, they are resolved to DIDs via get_profile().

    Outputs (run.outputs):
        result   (WorkerResult)   — followed, already_following, errors
    """

    config = AgentConfig(
        name="bluesky_follow",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:     str              = ctx["account_id"]
        session:        BlueSkySession   = ctx["session"]
        target_dids:    list[str]        = ctx.get("target_dids") or []
        target_handles: list[str]        = ctx.get("target_handles") or []
        date_iso:       str              = ctx.get("date_iso", date.today().isoformat())
        proxy_url:      str              = ctx.get("proxy_url", "socks5://127.0.0.1:8089")
        ab_test_id:     str              = ctx.get("ab_test_id", "")
        ab_variant_id:  str              = ctx.get("ab_variant_id", "")

        result = WorkerResult()
        followed_dids: list[str] = []   # accumulated for follow-back reconciliation

        if not target_dids and not target_handles:
            log.warning(
                "[bluesky_follow/%s] Neither target_dids nor target_handles provided — nothing to do",
                account_id,
            )
            run.outputs["result"]        = result
            run.outputs["followed_dids"] = followed_dids
            return True

        # A/B recording — lazy import, only active when test metadata is passed
        _ab_mgr = None
        if ab_test_id and ab_variant_id:
            from ...core.bluesky_ab_test import BlueSkyABManager
            _ab_mgr = BlueSkyABManager()

        self._audit({
            "event": "bluesky_follow_session_start",
            "account_id": account_id,
            "dids_provided": len(target_dids),
            "handles_provided": len(target_handles),
            "ab_test_id": ab_test_id or None,
        })

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            # ---- Resolve handles to DIDs ----
            resolved_dids: list[str] = list(target_dids)
            for handle in target_handles:
                try:
                    profile = await client.get_profile(handle)
                    did = profile.get("did", "")
                    if did:
                        resolved_dids.append(did)
                    else:
                        log.warning(
                            "[bluesky_follow/%s] Could not resolve handle %s",
                            account_id, handle,
                        )
                        result.errors.append(f"resolve_handle_failed:{handle}")
                except BlueSkySessionExpired:
                    log.warning(
                        "[bluesky_follow/%s] Session expired during handle resolution",
                        account_id,
                    )
                    result.errors.append("session_expired")
                    run.outputs["result"] = result
                    return True
                except Exception as exc:
                    log.warning(
                        "[bluesky_follow/%s] Failed to resolve %s: %s",
                        account_id, handle, exc,
                    )
                    result.errors.append(f"resolve_failed:{handle}:{exc}")

            # ---- Seeded shuffle (fleet: no two accounts share same sequence) ----
            seed = seed_for(account_id, date_iso, "bluesky_follow_target_order")
            rng  = random.Random(seed)
            shuffled = list(resolved_dids)
            rng.shuffle(shuffled)

            action_count = 0

            for did in shuffled:
                # ---- Hard daily cap ----
                if action_count >= MAX_FOLLOWS_PER_DAY:
                    log.info(
                        "[bluesky_follow/%s] Daily cap %d reached, stopping",
                        account_id, MAX_FOLLOWS_PER_DAY,
                    )
                    break

                self._audit({
                    "event": "bluesky_follow_attempt",
                    "account_id": account_id,
                    "target_did": did,
                    "cap_remaining": MAX_FOLLOWS_PER_DAY - action_count,
                })

                try:
                    await client.follow_user(did)
                    result.followed += 1
                    action_count += 1
                    followed_dids.append(did)
                    if _ab_mgr:
                        _ab_mgr.record_follow(ab_test_id, account_id, ab_variant_id, did)
                    log.debug("[bluesky_follow/%s] Followed %s", account_id, did)

                except BlueSkySessionExpired:
                    log.warning(
                        "[bluesky_follow/%s] Session expired — stopping", account_id
                    )
                    result.errors.append("session_expired")
                    break

                except BlueSkyRateLimited as exc:
                    log.warning(
                        "[bluesky_follow/%s] Rate limited — backing off %ds",
                        account_id, exc.retry_after_sec,
                    )
                    result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    await asyncio.sleep(min(exc.retry_after_sec, 120))
                    break

                except Exception as exc:
                    err_str = str(exc).lower()
                    # AT Protocol returns AlreadyExists when following someone again
                    if "alreadyexists" in err_str or "already" in err_str or "409" in err_str:
                        result.already_following += 1
                        log.debug(
                            "[bluesky_follow/%s] Already following %s", account_id, did
                        )
                    else:
                        result.errors.append(f"follow_error:{did}:{exc}")
                        log.warning(
                            "[bluesky_follow/%s] Follow failed for %s: %s",
                            account_id, did, exc,
                        )

                # ---- Inter-follow sleep (LogNormal, never fixed) ----
                sleep_sec = _INTER_FOLLOW_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"inter_follow_{did}",
                )
                await asyncio.sleep(sleep_sec)

        self._audit({
            "event": "bluesky_follow_session_end",
            "account_id": account_id,
            "followed": result.followed,
            "already_following": result.already_following,
            "errors": len(result.errors),
            "ab_test_id": ab_test_id or None,
        })

        run.outputs["result"]       = result
        run.outputs["followed_dids"] = followed_dids   # for follow-back reconciliation
        return True
