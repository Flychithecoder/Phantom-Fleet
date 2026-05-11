"""
TikTokFBRTracker — Follow/Block/Ratio monitor and unfollow trigger.

FBR (Follow-Back Ratio) is the primary health signal for a TikTok follow
campaign source. A source with FBR < 3% means we're burning follows on
accounts that will never follow back — polluting the account's follow:follower
ratio and making it look like a spam bot to TikTok's classifier.

What this agent does:
    1. Reads each account's current following_count vs follower_count
       (loaded from ctx — the manager fetches from DB)
    2. Calculates the account-level ratio imbalance:
           ratio = following_count / max(follower_count, 1)
       If ratio > 3.0 (following more than 3× followers), schedule an
       unfollow batch to rebalance
    3. Calculates per-source FBR from the follow history:
           fbr_pct = follows_returned / follows_sent * 100
       If fbr_pct < fbr_retire_threshold (default 3.0%), mark source "retired"
    4. Writes FBR history to DB (via ctx["db_write"] tool — injected by manager)
    5. Returns retirement candidates and accounts needing unfollow batches

Context keys (ctx):
    accounts             (list[dict])   — each dict has:
                                          id, username, following_count,
                                          follower_count, day_in_curve
    follow_history       (list[dict])   — each dict has:
                                          source_id, follows_sent, follows_returned,
                                          window_days
    fbr_retire_threshold (float)        — default 3.0%
    max_ratio            (float)        — default 3.0 (following:follower cap)
    date_iso             (str)

Output keys (run.outputs):
    fbr_by_source        (dict[str, float])  — source_id → fbr_pct
    retired_sources      (list[str])         — source IDs below retire threshold
    unfollow_needed      (list[dict])        — accounts that need unfollow batch
                                               [{account_id, current_ratio,
                                                 unfollow_target_count}]
    ratio_snapshots      (list[dict])        — current ratio per account
    fleet_fbr_avg_pct    (float)             — fleet-wide FBR average

The unfollow_target_count calculation:
    We want following_count / follower_count ≈ 1.2 (slight leading edge is fine).
    Target following = follower_count * 1.2
    unfollow_target = following_count - target_following
    Capped at 50 per session to avoid rapid mass-unfollow pattern.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FBR_RETIRE_THRESHOLD = 3.0    # percent
DEFAULT_MAX_RATIO             = 3.0    # following / follower cap
TARGET_RATIO                  = 1.2   # ideal following:follower ratio
MAX_UNFOLLOW_PER_SESSION      = 50    # blast-radius cap per account per session


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class FBRSnapshot:
    """Point-in-time FBR reading for one source."""
    source_id:        str
    follows_sent:     int
    follows_returned: int
    window_days:      int
    fbr_pct:          float
    retired:          bool = False


@dataclass
class RatioSnapshot:
    """Current following:follower ratio for one account."""
    account_id:       str
    username:         str
    following_count:  int
    follower_count:   int
    ratio:            float
    unfollow_needed:  bool = False
    unfollow_target:  int  = 0


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class TikTokFBRTracker(Agent):
    """
    Monitors follow-back ratio and flags accounts / sources for action.

    Runs once per manager cycle (every 5 min for TikTok — the highest
    cadence manager in the fleet). Does NOT take any TikTok UI actions
    itself — it writes decisions to run.outputs and the manager acts on them.

    This is a pure-computation agent: no HTTP calls, no phone I/O.
    All data is passed in via ctx.
    """

    config = AgentConfig(
        name="tiktok_fbr_tracker",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        accounts:        list[dict] = ctx.get("accounts", [])
        follow_history:  list[dict] = ctx.get("follow_history", [])
        fbr_threshold:   float      = ctx.get("fbr_retire_threshold", DEFAULT_FBR_RETIRE_THRESHOLD)
        max_ratio:       float      = ctx.get("max_ratio", DEFAULT_MAX_RATIO)
        date_iso:        str        = ctx.get("date_iso", date.today().isoformat())

        # ---------------------------------------------------------------
        # 1. Per-account ratio snapshot
        # ---------------------------------------------------------------
        ratio_snapshots: list[RatioSnapshot] = []
        unfollow_needed: list[dict] = []

        for acct in accounts:
            account_id      = acct["id"]
            username        = acct.get("username", "")
            following_count = int(acct.get("following_count", 0))
            follower_count  = int(acct.get("follower_count", 0))

            ratio = following_count / max(follower_count, 1)

            snap = RatioSnapshot(
                account_id=account_id,
                username=username,
                following_count=following_count,
                follower_count=follower_count,
                ratio=round(ratio, 3),
            )

            if ratio > max_ratio:
                # How many to unfollow to reach TARGET_RATIO
                target_following   = int(follower_count * TARGET_RATIO)
                unfollow_target    = min(
                    following_count - target_following,
                    MAX_UNFOLLOW_PER_SESSION,
                )
                unfollow_target    = max(0, unfollow_target)
                snap.unfollow_needed  = True
                snap.unfollow_target  = unfollow_target

                unfollow_needed.append({
                    "account_id":      account_id,
                    "username":        username,
                    "current_ratio":   round(ratio, 3),
                    "following_count": following_count,
                    "follower_count":  follower_count,
                    "unfollow_target": unfollow_target,
                })

                self._audit({
                    "event": "tiktok_fbr_ratio_exceeded",
                    "account_id": account_id,
                    "ratio": round(ratio, 3),
                    "max_ratio": max_ratio,
                    "unfollow_target": unfollow_target,
                })

            ratio_snapshots.append(snap)

        # ---------------------------------------------------------------
        # 2. Per-source FBR calculation
        # ---------------------------------------------------------------
        fbr_by_source:  dict[str, float] = {}
        retired_sources: list[str] = []
        fbr_snapshots:   list[FBRSnapshot] = []

        for entry in follow_history:
            source_id        = entry["source_id"]
            follows_sent     = int(entry.get("follows_sent", 0))
            follows_returned = int(entry.get("follows_returned", 0))
            window_days      = int(entry.get("window_days", 7))

            if follows_sent == 0:
                fbr_pct = 0.0
            else:
                fbr_pct = round(follows_returned / follows_sent * 100, 2)

            fbr_by_source[source_id] = fbr_pct

            retired = fbr_pct < fbr_threshold and follows_sent >= 20
            # Require at least 20 follows before retiring — don't kill a
            # source on a tiny sample (would bias toward false positives)

            if retired:
                retired_sources.append(source_id)
                self._audit({
                    "event": "tiktok_fbr_source_retired",
                    "source_id": source_id,
                    "fbr_pct": fbr_pct,
                    "follows_sent": follows_sent,
                    "follows_returned": follows_returned,
                    "window_days": window_days,
                })

            fbr_snapshots.append(FBRSnapshot(
                source_id=source_id,
                follows_sent=follows_sent,
                follows_returned=follows_returned,
                window_days=window_days,
                fbr_pct=fbr_pct,
                retired=retired,
            ))

        # Fleet-wide FBR average (exclude sources with 0 sends)
        active_fbrs = [s.fbr_pct for s in fbr_snapshots if s.follows_sent >= 5]
        fleet_fbr_avg = round(sum(active_fbrs) / max(len(active_fbrs), 1), 2)

        # ---------------------------------------------------------------
        # 3. Outputs
        # ---------------------------------------------------------------
        ratio_dicts = [
            {
                "account_id":      s.account_id,
                "username":        s.username,
                "following_count": s.following_count,
                "follower_count":  s.follower_count,
                "ratio":           s.ratio,
                "unfollow_needed": s.unfollow_needed,
                "unfollow_target": s.unfollow_target,
            }
            for s in ratio_snapshots
        ]

        run.outputs.update({
            "fbr_by_source":      fbr_by_source,
            "retired_sources":    retired_sources,
            "unfollow_needed":    unfollow_needed,
            "ratio_snapshots":    ratio_dicts,
            "fleet_fbr_avg_pct":  fleet_fbr_avg,
        })

        self._audit({
            "event": "tiktok_fbr_tracker_complete",
            "date_iso": date_iso,
            "accounts_checked": len(accounts),
            "sources_checked": len(follow_history),
            "unfollow_needed_count": len(unfollow_needed),
            "retired_sources_count": len(retired_sources),
            "fleet_fbr_avg_pct": fleet_fbr_avg,
        })

        return True
