"""
XPostAgent — posts tweets with full human posting behaviour simulation.

X-specific constraints:
    - 280 character limit (hard; posts truncated with "…" if over)
    - New accounts (< 30 days): max 2 tweets/day
    - Warm accounts (30+ days): max 5 tweets/day
    - Content dedup: (account_id, content_hash) never reused from same account
    - Template pool MUST contain >= 15 items (raised as ValueError on construction)

Fleet-scale hardening (CLAUDE.md 20K account rule):
    - All timing uses LogNormal distributions — fleet histograms are bell-shaped
    - Pre-post scroll: LogNormal(mean=ln(20), σ=0.35) per tweet read
    - Compose dwell: LogNormal(mean=ln(10), σ=0.4)
    - Typing delay: len(text) × LogNormal(mean=ln(0.11), σ=0.25)
    - Rethink pause (18% chance): LogNormal(mean=ln(12), σ=0.3)
    - Post timing jitter: Normal(0, 720) seconds
    - Template selection seeded per (account_id, date_iso, post_index) so
      different accounts pick different templates from same pool
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from datetime import date

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.distributions import LogNormal, Normal, seed_for
from ...core.human_post_behavior import select_template
from ...core.x_client import XClient, XSession, XSessionExpired, XRateLimited

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# X character limit
# ---------------------------------------------------------------------------

X_CHAR_LIMIT = 280

# ---------------------------------------------------------------------------
# Human posting timing distributions
# ---------------------------------------------------------------------------

# Pre-post timeline scroll: median ~20s per tweet read (quick scan)
_PRE_POST_READ_DIST = LogNormal(low=5.0, high=90.0, sigma=0.35)

# Compose dwell: time before first keystroke, median ~10s
_COMPOSE_DWELL_DIST = LogNormal(low=3.0, high=50.0, sigma=0.40)

# Per-character typing speed (seconds): median ~0.11s/char
_TYPING_SPEED_DIST = LogNormal(low=0.04, high=0.60, sigma=0.25)

# Rethink pause (X posts are more carefully written): median ~12s
_RETHINK_PAUSE_DIST = LogNormal(low=3.0, high=45.0, sigma=0.30)

# Post timing jitter: Normal(0, 720) → ±12 min typical, clamped ±30 min
_JITTER_DIST = Normal(mean=0.0, std=720.0, low=-1800.0, high=1800.0)

# ---------------------------------------------------------------------------
# Warming-curve daily post caps (code-enforced)
# ---------------------------------------------------------------------------

# X aggressively rate-limits new accounts
_CAP_NEW_ACCOUNT  = 2   # Days 0-30
_CAP_WARM_ACCOUNT = 5   # Days 30+

# Rethink probability for X (more deliberate than casual platforms)
_RETHINK_PROBABILITY_BYTE = 46   # 46/256 ≈ 18%

# Minimum template pool size (fleet: must be large enough for diversity)
MIN_TEMPLATE_POOL_SIZE = 15

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _x_daily_post_cap(account_day_in_curve: int) -> int:
    """Return the maximum tweets per day given account age."""
    return _CAP_WARM_ACCOUNT if account_day_in_curve >= 30 else _CAP_NEW_ACCOUNT


def _truncate_to_limit(text: str, limit: int = X_CHAR_LIMIT) -> str:
    """Truncate text to limit chars, appending '…' if truncated."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _content_hash(account_id: str, text: str) -> str:
    """SHA-256 hash of (account_id, text) for dedup tracking."""
    payload = f"{account_id}|{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _should_rethink() -> bool:
    """Return True with ~18% probability (non-deterministic per call)."""
    return secrets.token_bytes(1)[0] < _RETHINK_PROBABILITY_BYTE


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class XPostAgent(Agent):
    """
    Specialist agent: post tweets for one X account.

    ctx keys:
        account_id            (str)        — Phantom Fleet account ID
        session               (XSession)   — pre-built X session
        template_pool         (list[str])  — tweet templates (>= 15 required)
        account_day_in_curve  (int)        — account age in days
        posts_to_attempt      (int)        — how many tweets to post this run
        date_iso              (str)        — YYYY-MM-DD (defaults to today)
        already_posted_today  (int)        — count of tweets already sent today
        posted_hashes         (set[str])   — (account_id, content_hash) dedup set
        proxy_url             (str)        — SOCKS5 proxy (optional)

    Outputs (run.outputs):
        result   (WorkerResult)   — tweets_posted, skipped_dedup, skipped_cap, errors
    """

    config = AgentConfig(
        name="x_post",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:           str        = ctx["account_id"]
        session:              XSession   = ctx["session"]
        template_pool:        list[str]  = ctx["template_pool"]
        account_day_in_curve: int        = ctx.get("account_day_in_curve", 0)
        posts_to_attempt:     int        = ctx.get("posts_to_attempt", 1)
        date_iso:             str        = ctx.get("date_iso", date.today().isoformat())
        already_posted_today: int        = ctx.get("already_posted_today", 0)
        posted_hashes:        set[str]   = ctx.get("posted_hashes") or set()
        proxy_url:            str        = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        # ---- Template pool validation (code-enforced minimum) ----
        if len(template_pool) < MIN_TEMPLATE_POOL_SIZE:
            raise ValueError(
                f"XPostAgent: template_pool must have >= {MIN_TEMPLATE_POOL_SIZE} items, "
                f"got {len(template_pool)}"
            )

        # ---- Daily cap (code-enforced) ----
        cap = _x_daily_post_cap(account_day_in_curve)

        result = WorkerResult()

        self._audit({
            "event": "x_post_session_start",
            "account_id": account_id,
            "cap": cap,
            "already_posted_today": already_posted_today,
            "posts_to_attempt": posts_to_attempt,
            "account_day_in_curve": account_day_in_curve,
        })

        async with XClient(session, proxy_url=proxy_url) as client:
            for post_idx in range(posts_to_attempt):
                # ---- Hard daily cap check ----
                if already_posted_today + result.tweets_posted >= cap:
                    log.info(
                        "[x_post/%s] Daily cap %d reached, stopping",
                        account_id, cap,
                    )
                    result.skipped_cap += posts_to_attempt - post_idx
                    break

                # ---- Template selection (seeded for per-account diversity) ----
                seed = seed_for(account_id, date_iso, f"x_post_template_{post_idx}")
                text = select_template(template_pool, seed)

                # ---- 280-char validation + truncation ----
                text = _truncate_to_limit(text, X_CHAR_LIMIT)

                # ---- Dedup check (account_id, content_hash) ----
                chash = _content_hash(account_id, text)
                if chash in posted_hashes:
                    log.debug(
                        "[x_post/%s] Dedup skip for hash %s", account_id, chash
                    )
                    result.skipped_dedup += 1
                    continue
                posted_hashes.add(chash)

                # ---- Timing jitter on scheduled time ----
                jitter = int(_JITTER_DIST.sample())
                # (actual scheduling is managed by the caller; jitter is logged
                #  here so audit trail captures the intended delivery offset)

                # ---- Human pre-post behaviour ----
                # 1. Fetch timeline + simulate reading 3-5 tweets
                try:
                    timeline = await client.get_timeline(count=10)
                except Exception:
                    timeline = {}

                tweets_in_feed = min(5, max(3, len(
                    timeline.get("data", {}).get("home", {}).get(
                        "home_timeline_upe", {}
                    ).get("instructions", [])
                )))
                for _ in range(tweets_in_feed):
                    read_dur = _PRE_POST_READ_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"pre_read_{post_idx}",
                    )
                    await asyncio.sleep(read_dur)

                # 2. Compose dwell
                compose_dur = _COMPOSE_DWELL_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"compose_dwell_{post_idx}",
                )
                await asyncio.sleep(compose_dur)

                # 3. Typing delay (proportional to text length)
                per_char = _TYPING_SPEED_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"typing_speed_{post_idx}",
                )
                typing_dur = len(text) * per_char
                await asyncio.sleep(typing_dur)

                # 4. Rethink pause (18% chance)
                if _should_rethink():
                    rethink_dur = _RETHINK_PAUSE_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"rethink_{post_idx}",
                    )
                    await asyncio.sleep(rethink_dur)

                # ---- Audit BEFORE posting ----
                self._audit({
                    "event": "x_post_attempt",
                    "account_id": account_id,
                    "text_length": len(text),
                    "content_hash": chash,
                    "jitter_sec": jitter,
                    "post_idx": post_idx,
                })

                # ---- Post ----
                try:
                    # X's create tweet endpoint (GraphQL CreateTweet)
                    await client._graphql_post(
                        "SiM_cAu83R0wnrpmKQgbIw/CreateTweet",
                        variables={
                            "tweet_text": text,
                            "dark_request": False,
                            "media": {"media_entities": [], "possibly_sensitive": False},
                            "semantic_annotation_ids": [],
                        },
                        features={
                            "interactive_text_enabled": True,
                            "longform_notetweets_inline_media_enabled": False,
                            "responsive_web_text_conversations_enabled": False,
                            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
                            "vibe_api_enabled": False,
                        },
                    )
                    result.tweets_posted += 1
                    log.debug(
                        "[x_post/%s] Posted tweet %d/%d (len=%d)",
                        account_id, post_idx + 1, posts_to_attempt, len(text),
                    )

                except XSessionExpired:
                    log.warning("[x_post/%s] Session expired — stopping", account_id)
                    result.errors.append("session_expired")
                    break

                except XRateLimited as exc:
                    log.warning(
                        "[x_post/%s] Rate limited — backing off %ds",
                        account_id, exc.retry_after_sec,
                    )
                    result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
                    await asyncio.sleep(min(exc.retry_after_sec, 120))
                    break

                except Exception as exc:
                    result.errors.append(f"post_error:{exc}")
                    log.error("[x_post/%s] Post failed: %s", account_id, exc)
                    continue

        self._audit({
            "event": "x_post_session_end",
            "account_id": account_id,
            "tweets_posted": result.tweets_posted,
            "skipped_dedup": result.skipped_dedup,
            "skipped_cap": result.skipped_cap,
            "errors": len(result.errors),
        })

        run.outputs["result"] = result
        return True
