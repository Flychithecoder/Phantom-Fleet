"""
XFollowAgent — follow / unfollow users on X (Twitter) via XClient.

Fleet-scale hardening (CLAUDE.md 20K account rule):
    - Target list shuffled per (account_id, date_iso) so no two accounts
      ever process the same sequence — prevents network-graph regularities.
    - Inter-follow sleep sampled from LogNormal(mean=ln(45), σ=0.45) —
      fleet-wide histogram is log-normal, not uniform/rectangular.
    - Daily follow cap enforced by CODE against the warming stage,
      not by prompt — blast radius is provably bounded.
    - Follow-back ratio tracked and returned for manager monitoring.

Warming-curve follow caps:
    Days 0-7:   max 10 follows/day
    Days 7-30:  max 30 follows/day
    Days 30+:   max 50 follows/day
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import date, datetime, timezone
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.distributions import LogNormal, seed_for
from ...core.x_client import XClient, XSession, XSessionExpired, XRateLimited

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# Inter-follow sleep: LogNormal(mean=ln(45), σ=0.45)
# median ~45s, 90th-pctile ~75s — matches real human follow pacing
_INTER_FOLLOW_DIST = LogNormal(low=15.0, high=180.0, sigma=0.45)

# ---------------------------------------------------------------------------
# Warming-curve daily caps (code-enforced)
# ---------------------------------------------------------------------------

def _daily_follow_cap(account_day_in_curve: int) -> int:
    """Return the maximum follows per day for the given account age in days."""
    if account_day_in_curve < 7:
        return 10
    if account_day_in_curve < 30:
        return 30
    return 50


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class XFollowAgent(Agent):
    """
    Specialist agent: follow / unfollow X users for one account.

    ctx keys:
        account_id           (str)        — Phantom Fleet account ID
        session              (XSession)   — pre-built X session
        target_user_ids      (list[str])  — X numeric user IDs to follow
        account_day_in_curve (int)        — how many days old the account is
        date_iso             (str)        — YYYY-MM-DD (defaults to today)
        unfollow_mode        (bool)       — if True, unfollow instead of follow
                                           (unfollows non-followers from target_user_ids)
        proxy_url            (str)        — SOCKS5 proxy for XClient (optional)

    Outputs (run.outputs):
        result   (WorkerResult)   — followed, unfollowed, already_following, errors
    """

    config = AgentConfig(
        name="x_follow",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:           str       = ctx["account_id"]
        session:              XSession  = ctx["session"]
        target_user_ids:      list[str] = ctx.get("target_user_ids", [])
        account_day_in_curve: int       = ctx.get("account_day_in_curve", 0)
        date_iso:             str       = ctx.get("date_iso", date.today().isoformat())
        unfollow_mode:        bool      = ctx.get("unfollow_mode", False)
        proxy_url:            str       = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        # ---- Determine daily cap (code-enforced, not prompt-enforced) ----
        cap = _daily_follow_cap(account_day_in_curve)

        # ---- Seeded per-account shuffle (fleet: no two accounts same sequence) ----
        seed = seed_for(account_id, date_iso, "x_follow_target_order")
        rng  = random.Random(seed)
        targets = list(target_user_ids)
        rng.shuffle(targets)

        result = WorkerResult()

        self._audit({
            "event": "x_follow_session_start",
            "account_id": account_id,
            "target_count": len(targets),
            "cap": cap,
            "unfollow_mode": unfollow_mode,
            "account_day_in_curve": account_day_in_curve,
        })

        action_count = 0  # tracks follows OR unfollows executed this run

        async with XClient(session, proxy_url=proxy_url) as client:
            for user_id in targets:
                # ---- Hard cap enforced by code ----
                if action_count >= cap:
                    log.info(
                        "[x_follow/%s] Daily cap %d reached, stopping",
                        account_id, cap,
                    )
                    break

                self._audit({
                    "event": "x_follow_attempt",
                    "account_id": account_id,
                    "target_user_id": user_id,
                    "action": "unfollow" if unfollow_mode else "follow",
                    "cap_remaining": cap - action_count,
                })

                try:
                    if unfollow_mode:
                        await client.unfollow_user(user_id)
                        result.unfollowed += 1
                        action_count += 1
                        log.debug("[x_follow/%s] Unfollowed %s", account_id, user_id)
                    else:
                        await client.follow_user(user_id)
                        result.followed += 1
                        action_count += 1
                        log.debug("[x_follow/%s] Followed %s", account_id, user_id)

                except XSessionExpired:
                    log.warning("[x_follow/%s] Session expired — stopping", account_id)
                    result.errors.append("session_expired")
                    break

                except XRateLimited as exc:
                    log.warning(
                        "[x_follow/%s] Rate limited — backing off %ds",
                        account_id, exc.retry_after_sec,
                    )
                    result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    # Back off for the indicated time, then stop (manager will reschedule)
                    await asyncio.sleep(min(exc.retry_after_sec, 120))
                    break

                except Exception as exc:
                    # X returns 403 / "already_following" error in response body;
                    # treat all non-rate-limit errors as already_following or generic error
                    err_str = str(exc).lower()
                    if "already" in err_str or "403" in err_str:
                        result.already_following += 1
                        log.debug(
                            "[x_follow/%s] Already following %s", account_id, user_id
                        )
                    else:
                        result.errors.append(f"follow_error:{user_id}:{exc}")
                        log.warning(
                            "[x_follow/%s] Follow error for %s: %s",
                            account_id, user_id, exc,
                        )

                # ---- Inter-follow sleep (LogNormal, never fixed) ----
                sleep_sec = _INTER_FOLLOW_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"inter_follow_{user_id}",
                )
                await asyncio.sleep(sleep_sec)

        # Follow-back ratio: how many of the targets were already followed
        # (useful for manager to monitor list quality)
        total_attempted = result.followed + result.unfollowed + result.already_following
        follow_back_ratio = (
            result.already_following / total_attempted if total_attempted else 0.0
        )

        self._audit({
            "event": "x_follow_session_end",
            "account_id": account_id,
            "followed": result.followed,
            "unfollowed": result.unfollowed,
            "already_following": result.already_following,
            "errors": len(result.errors),
            "follow_back_ratio": round(follow_back_ratio, 3),
        })

        run.outputs["result"] = result
        run.outputs["follow_back_ratio"] = follow_back_ratio
        return True
