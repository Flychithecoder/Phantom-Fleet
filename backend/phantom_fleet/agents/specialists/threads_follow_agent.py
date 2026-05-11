"""
ThreadsFollowAgent — follows users on Threads.

Threads shares the Instagram session and device fingerprint — no separate login
or token refresh is needed. All requests carry the same IG session cookie and
device headers, routed through the phone's SOCKS5 proxy.

Responsibilities:
    - Accept a list of target user IDs to follow
    - Shuffle the target order per-account per-day (seeded hash) to prevent
      fleet-wide follow-order fingerprints
    - Follow each target via the Threads API
    - Space follows with LogNormal inter-follow dwell
    - Enforce a hard daily cap of 60 follows per account (Threads is less
      aggressive than IG on follow limits, but we stay well under to be safe)

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Target order: seeded shuffle per (account_id + date_iso) so no two
      accounts follow targets in the same order on the same day. Follow-graph
      edge correlation across the fleet would otherwise be a cluster signal.
    - Inter-follow dwell: LogNormal(mean=ln(30), σ=0.4) → median ~30s.
      Fleet histogram is log-normal, not a uniform spike.
    - Daily cap of 60 enforced by code, not prompt.

Threads API endpoint:
    POST https://i.instagram.com/api/v1/friendships/create/{user_id}/
    Same endpoint as Instagram — Threads is IG under the hood. The session
    cookie and headers carry the Threads identity context when the request
    originates from a Threads-registered session.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGActionBlocked,
    IGRateLimited,
    IGSession,
    IGSessionExpired,
    InstagramClient,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced)
# ---------------------------------------------------------------------------

MAX_FOLLOWS_PER_ACCOUNT_PER_DAY: int = 60

# ---------------------------------------------------------------------------
# Distribution instances
# ---------------------------------------------------------------------------

# Inter-follow dwell: LogNormal(mean=ln(30), σ=0.4) → median ~30s
_INTER_FOLLOW_DIST = LogNormal(low=8.0, high=180.0, sigma=0.40)


# ---------------------------------------------------------------------------
# Seeded shuffle helper
# ---------------------------------------------------------------------------


def _seeded_shuffle(items: list, account_id: str, date_iso: str) -> list:
    """
    Return a shuffled copy of items using a deterministic seed.

    Seed = hash(account_id + date_iso) so:
      - Same account on same day always gets same shuffle (idempotent on retry)
      - Different accounts on same day get different orderings
    """
    import random
    seed_input = f"{account_id}|{date_iso}|follow_order"
    digest = hashlib.sha256(seed_input.encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = random.Random(seed)
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled


# ---------------------------------------------------------------------------
# ThreadsFollowAgent
# ---------------------------------------------------------------------------


@dataclass
class ThreadsFollowResult:
    """Detailed result returned alongside WorkerResult."""
    followed: int = 0
    already_following: int = 0
    errors: list[str] = field(default_factory=list)


class ThreadsFollowAgent:
    """
    Follows users on Threads using the shared IG/Threads session.

    Usage:
        agent = ThreadsFollowAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            target_user_ids=["111", "222", ...],
            date_iso="2026-04-11",
        )

    Returns a WorkerResult with `data` keys:
        followed, already_following, errors
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        target_user_ids: list[str],
        date_iso: Optional[str] = None,
        follows_done_today: int = 0,
    ) -> WorkerResult:
        """
        Run one follow session for one account on Threads.

        Args:
            account_id:         Internal account identifier.
            session:            Authenticated IGSession (shared with Threads).
            target_user_ids:    List of Threads/IG user IDs to follow.
            date_iso:           YYYY-MM-DD (defaults to today UTC).
            follows_done_today: Count of follows already done today.

        Returns:
            WorkerResult with success=True and detailed data dict.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        # Seeded shuffle: prevent fleet-wide follow-order fingerprint
        shuffled_targets = _seeded_shuffle(target_user_ids, account_id, date_iso)

        detail = ThreadsFollowResult()
        task_id = f"{account_id}_threads_follow_{date_iso}"

        async with InstagramClient(session) as client:
            for idx, user_id in enumerate(shuffled_targets):
                # Hard daily cap — code enforced
                if follows_done_today >= MAX_FOLLOWS_PER_ACCOUNT_PER_DAY:
                    log.info(
                        "[%s/threads] Daily follow cap reached (%d), stopping",
                        account_id, MAX_FOLLOWS_PER_ACCOUNT_PER_DAY,
                    )
                    break

                log.info(
                    "[%s/threads] Following user %s (%d/%d)",
                    account_id, user_id, idx + 1, len(shuffled_targets),
                )

                try:
                    resp = await client.follow(user_id)
                    friendship_status = resp.get("friendship_status", {})

                    if friendship_status.get("following"):
                        follows_done_today += 1
                        detail.followed += 1
                    elif friendship_status.get("outgoing_request"):
                        # Private account — follow request sent, counts against cap
                        follows_done_today += 1
                        detail.followed += 1
                    else:
                        # Might already be following
                        detail.already_following += 1

                except IGSessionExpired:
                    log.warning("[%s/threads] Session expired during follow", account_id)
                    detail.errors.append(f"session_expired:user={user_id}")
                    break

                except IGRateLimited:
                    log.warning("[%s/threads] Rate limited during follow", account_id)
                    detail.errors.append(f"rate_limited:user={user_id}")
                    break

                except IGActionBlocked:
                    log.warning("[%s/threads] Follow action blocked", account_id)
                    detail.errors.append(f"action_blocked:user={user_id}")
                    break

                except Exception as exc:
                    log.error("[%s/threads] Follow error for user %s: %s", account_id, user_id, exc)
                    detail.errors.append(f"error:user={user_id}:{exc}")
                    continue

                # Inter-follow dwell
                if idx < len(shuffled_targets) - 1 and follows_done_today < MAX_FOLLOWS_PER_ACCOUNT_PER_DAY:
                    inter_delay = _INTER_FOLLOW_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_follow_{user_id}",
                    )
                    await asyncio.sleep(inter_delay)

        return WorkerResult(
            task_id=task_id,
            platform="threads",
            account_id=account_id,
            success=True,
            data={
                "action":           "follow",
                "followed":         detail.followed,
                "already_following": detail.already_following,
                "errors":           detail.errors,
            },
        )
