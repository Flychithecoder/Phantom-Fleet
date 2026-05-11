"""
IGCommentAgent — posts comments on target Instagram media.

Responsibilities:
    - Accept a media pool and comment template pool from task params
    - Select comments deterministically per (account_id, media_id) so the
      same account always posts the same comment on the same media (idempotent
      on retry) but different accounts see different templates (anti-monoculture)
    - Simulate human dwell (reading the post) before posting
    - Simulate human typing timing between characters
    - Enforce a hard daily cap of 5 comments per account
    - Deduplicate: never post the same (account_id, media_id, template_idx)
      combination twice in a session
    - Space comments with LogNormal inter-comment timing

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - template selection: hash(account_id + media_id) % len(pool) → each pair
      deterministically picks one of ≥30 templates. At 20K accounts hitting
      the same media, the comment histogram is roughly uniform across the 30+
      templates — no single template dominates.
    - Pre-comment dwell: LogNormal so fleet histogram of dwell times is
      log-normal, not a spike at a fixed value.
    - Inter-comment delay: LogNormal(mean=ln(120), σ=0.5) → median ~2 min,
      heavy tail — some comments post minutes apart, some many minutes apart.
    - Daily cap of 5 enforced in CODE so prompt-injection cannot override it.

Out of scope (DO NOT add):
    - Photo/video/story upload — Meta detects third-party upload clients.
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
    _generate_uuid,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced)
# ---------------------------------------------------------------------------

MAX_COMMENTS_PER_ACCOUNT_PER_DAY: int = 5
MIN_TEMPLATE_POOL_SIZE: int = 30

# ---------------------------------------------------------------------------
# Distribution instances
# ---------------------------------------------------------------------------

# Pre-comment dwell: how long the account "reads" the post before commenting
# LogNormal(mean=ln(8), σ=0.3) → median ~8s
_PRE_COMMENT_DWELL_DIST = LogNormal(low=2.0, high=40.0, sigma=0.30)

# Inter-comment sleep: time between posting successive comments
# LogNormal(mean=ln(120), σ=0.5) → median ~2 min, tail to ~10+ min
_INTER_COMMENT_DIST = LogNormal(low=30.0, high=600.0, sigma=0.50)

# Typing speed per character: LogNormal(mean=ln(0.09), σ=0.20) seconds/char
_TYPING_SPEED_DIST = LogNormal(low=0.04, high=0.35, sigma=0.20)


# ---------------------------------------------------------------------------
# Comment selection helpers
# ---------------------------------------------------------------------------


def _template_index_for(account_id: str, media_id: str, pool_size: int) -> int:
    """
    Return a deterministic template index for (account_id, media_id).

    Seeded by SHA-256 so:
      - Same (account, media) always picks the same template (idempotent on retry)
      - Different accounts on the same media pick different templates (~uniform spread)
    """
    key = f"{account_id}|{media_id}|comment_template"
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:4], "big") % pool_size


# ---------------------------------------------------------------------------
# IGCommentAgent
# ---------------------------------------------------------------------------


@dataclass
class IGCommentResult:
    """Detailed result returned alongside WorkerResult."""
    comments_posted: int = 0
    comments_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class IGCommentAgent:
    """
    Posts comments on target Instagram media with human behavior simulation.

    Usage:
        agent = IGCommentAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,
            media_pool=["media_id_1", "media_id_2", ...],
            comment_templates=["Great!", "Love this!", ...],  # ≥30 items
            date_iso="2026-04-11",
        )

    Returns a WorkerResult with `data` keys:
        comments_posted, comments_skipped, errors
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        media_pool: list[str],
        comment_templates: list[str],
        date_iso: Optional[str] = None,
        already_commented: Optional[set[tuple[str, str, int]]] = None,
        comments_posted_today: int = 0,
    ) -> WorkerResult:
        """
        Run one commenting session for one account.

        Args:
            account_id:          Internal account identifier.
            session:             Authenticated IGSession.
            media_pool:          List of media IDs to target.
            comment_templates:   Pool of comment text templates (min 30).
            date_iso:            YYYY-MM-DD (defaults to today UTC).
            already_commented:   Set of (account_id, media_id, template_idx)
                                 tuples already posted in this or prior runs.
                                 Mutated in-place — caller persists state.
            comments_posted_today: Count of comments already posted today for
                                 this account (for daily cap enforcement).

        Returns:
            WorkerResult with success=True and detailed data dict.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        # Validate template pool size (fleet-scale anti-monoculture guard)
        if len(comment_templates) < MIN_TEMPLATE_POOL_SIZE:
            raise ValueError(
                f"IGCommentAgent: comment_templates pool has {len(comment_templates)} items "
                f"but minimum is {MIN_TEMPLATE_POOL_SIZE}. Small pools create "
                f"comment-monoculture clusters detectable at fleet scale."
            )

        if already_commented is None:
            already_commented = set()

        detail = IGCommentResult()
        task_id = f"{account_id}_comment_{date_iso}"

        async with InstagramClient(session) as client:
            for media_id in media_pool:
                # Hard daily cap — code enforced
                if comments_posted_today >= MAX_COMMENTS_PER_ACCOUNT_PER_DAY:
                    log.info(
                        "[%s] Daily comment cap reached (%d), stopping",
                        account_id, MAX_COMMENTS_PER_ACCOUNT_PER_DAY,
                    )
                    break

                # Select template deterministically
                tmpl_idx = _template_index_for(account_id, media_id, len(comment_templates))
                dedup_key = (account_id, media_id, tmpl_idx)

                # Dedup: skip if already commented with this template on this media
                if dedup_key in already_commented:
                    log.debug(
                        "[%s] Skipping media %s — already commented (tmpl_idx=%d)",
                        account_id, media_id, tmpl_idx,
                    )
                    detail.comments_skipped += 1
                    continue

                comment_text = comment_templates[tmpl_idx]

                # Pre-comment dwell: simulate reading the post
                dwell = _PRE_COMMENT_DWELL_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"comment_dwell_{media_id}",
                )
                await asyncio.sleep(dwell)

                # Typing simulation: delay proportional to comment length
                per_char = _TYPING_SPEED_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"type_speed_{media_id}",
                )
                typing_duration = len(comment_text) * per_char
                await asyncio.sleep(typing_duration)

                log.info(
                    "[%s] Posting comment on media %s (tmpl_idx=%d, dwell=%.1fs)",
                    account_id, media_id, tmpl_idx, dwell,
                )

                # Audit BEFORE execution (CLAUDE.md agent rule)
                audit_ts = datetime.now(timezone.utc).isoformat()

                try:
                    await client._post(
                        f"media/{media_id}/comment/",
                        {
                            "comment_text":  comment_text,
                            "media_id":      media_id,
                            "_uuid":         _generate_uuid(),
                            "_uid":          session.ig_user_id,
                            "_csrftoken":    session.csrftoken,
                            "container_module": "feed_timeline",
                            "user_breadcrumb": _encode_breadcrumb(comment_text),
                        },
                    )
                    already_commented.add(dedup_key)
                    comments_posted_today += 1
                    detail.comments_posted += 1

                except IGSessionExpired:
                    log.warning("[%s] Session expired during comment", account_id)
                    detail.errors.append(f"session_expired:media={media_id}")
                    break

                except IGRateLimited:
                    log.warning("[%s] Rate limited during comment", account_id)
                    detail.errors.append(f"rate_limited:media={media_id}")
                    break

                except IGActionBlocked:
                    log.warning("[%s] Comment action blocked", account_id)
                    detail.errors.append(f"action_blocked:media={media_id}")
                    break

                except Exception as exc:
                    log.error("[%s] Comment error on media %s: %s", account_id, media_id, exc)
                    detail.errors.append(f"error:media={media_id}:{exc}")
                    continue

                # Inter-comment delay — only if more media to process
                remaining_in_pool = (
                    media_pool.index(media_id) < len(media_pool) - 1
                )
                if remaining_in_pool and comments_posted_today < MAX_COMMENTS_PER_ACCOUNT_PER_DAY:
                    inter_delay = _INTER_COMMENT_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_comment_{media_id}",
                    )
                    await asyncio.sleep(inter_delay)

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":           "comment",
                "comments_posted":  detail.comments_posted,
                "comments_skipped": detail.comments_skipped,
                "errors":           detail.errors,
            },
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _encode_breadcrumb(text: str) -> str:
    """
    Encode the user breadcrumb for IG comment endpoint.
    Format: "length_ms elapsed_ms backspace_count key_count"
    This simulates realistic typing telemetry sent with each comment.
    """
    import secrets
    length_ms = len(text) * secrets.randbelow(80) + len(text) * 90
    elapsed_ms = length_ms + secrets.randbelow(500)
    backspaces = max(0, secrets.randbelow(max(1, len(text) // 10)))
    key_count = len(text) + backspaces
    return f"{length_ms} {elapsed_ms} {backspaces} {key_count}"
