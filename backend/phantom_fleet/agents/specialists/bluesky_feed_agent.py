"""
BlueSkyFeedAgent — custom feed generator record management.

AT Protocol custom feeds — architecture overview:
    A "feed generator" on BlueSky is a two-part system:
      1. A generator SERVICE (HTTP server at a stable URL) that implements
         the app.bsky.feed.getFeedSkeleton endpoint and returns a list
         of AT post URIs in response order.  This service runs externally
         and is owned by the persona / Phantom Fleet backend.
      2. A generator RECORD (app.bsky.feed.generator) published to the
         actor's repo that tells BlueSky where the service lives, what it
         is named, and what content labels it carries.

    This agent manages the RECORD side only.  The service side is assumed
    to be running at the URL provided in ctx["feed_service_url"].

Organic reach value of custom feeds on BlueSky:
    - Feeds appear in the BlueSky discovery sidebar.
    - Other users can pin your feed to their home view.
    - Popular feeds have their own follower counts — a feed with 2 000+
      pinners is permanent branded reach at zero marginal cost.
    - The feed record is the "landing page" — its description and avatar
      are the first thing a potential pinner sees.

Operations this agent performs:
    create:   PUT a new app.bsky.feed.generator record (idempotent via putRecord).
    refresh:  Update display_name / description / avatar on an existing record.
    disable:  Set acceptsInteractions=false to pause feed visibility.

Fleet-scale notes:
    - Each persona account that runs this agent publishes its OWN feed record
      under its own DID — there is no shared feed record across accounts.
    - rkey is stable (derived from feed_id) so re-running this agent on the
      same account+feed_id is a safe idempotent upsert.
    - No timing sleeps needed — this is a single write-record operation, not
      a mass-action loop.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_rkey(feed_id: str) -> str:
    """
    Generate a stable rkey from a feed_id.

    rkey must be a valid AT identifier (URL-safe, ≤ 512 chars).
    We use the first 32 hex chars of SHA-256(feed_id) — globally unique
    and collision-resistant at any realistic fleet scale.
    """
    return hashlib.sha256(feed_id.encode("utf-8")).hexdigest()[:32]


def _build_generator_record(
    feed_id:         str,
    display_name:    str,
    description:     str,
    feed_service_url: str,
    did:             str,
    accepts_interactions: bool = True,
) -> dict:
    """
    Build the app.bsky.feed.generator record.

    feed_service_url: The URL of the HTTP service that implements
                      app.bsky.feed.getFeedSkeleton for this feed.
                      e.g. "https://feed.phantomfleet.io"
    """
    return {
        "$type":       "app.bsky.feed.generator",
        "did":         f"did:web:{feed_service_url.lstrip('https://').lstrip('http://')}",
        "displayName": display_name,
        "description": description,
        "createdAt":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "acceptsInteractions": accepts_interactions,
        # Avatar / banner blobs are set separately via uploadBlob — not included here
        # so the feed is live without needing an image upload step.
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyFeedAgent(Agent):
    """
    Create or refresh a custom feed generator record for one account.

    ctx keys:
        account_id:        str
        session:           BlueSkySession
        feed_id:           str   — stable identifier (used to derive rkey)
        display_name:      str   — shown in BlueSky feed discovery
        description:       str   — shown in feed profile (≤ 300 chars)
        feed_service_url:  str   — URL of the getFeedSkeleton server
        operation:         str   — "create" | "refresh" | "disable"
        persona_id:        str   — for audit trail
        date_iso:          str
        proxy_url:         str

    Outputs (run.outputs):
        feed_uri:     str   — AT URI of the published feed record
        rkey:         str   — rkey used
        operation:    str   — what was performed
        result:       WorkerResult
    """

    config = AgentConfig(
        name="bluesky_feed",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:       str            = ctx["account_id"]
        session:          BlueSkySession = ctx["session"]
        feed_id:          str            = ctx["feed_id"]
        display_name:     str            = ctx.get("display_name", feed_id)
        description:      str            = ctx.get("description", "")[:300]
        feed_service_url: str            = ctx.get("feed_service_url", "")
        operation:        str            = ctx.get("operation", "create")
        persona_id:       str            = ctx.get("persona_id", account_id)
        date_iso:         str            = ctx.get("date_iso", date.today().isoformat())
        proxy_url:        str            = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        result = WorkerResult()
        rkey = _stable_rkey(feed_id)

        self._audit({
            "event":       "bluesky_feed_start",
            "account_id":  account_id,
            "feed_id":     feed_id,
            "operation":   operation,
            "rkey":        rkey,
            "persona_id":  persona_id,
        })

        if not feed_service_url:
            log.warning(
                "[bluesky_feed/%s] feed_service_url not provided — "
                "feed record cannot be published without a generator DID",
                account_id,
            )
            result.errors.append("missing_feed_service_url")
            run.outputs["result"]    = result
            run.outputs["operation"] = operation
            return True

        accepts_interactions = operation != "disable"

        record = _build_generator_record(
            feed_id=feed_id,
            display_name=display_name,
            description=description,
            feed_service_url=feed_service_url,
            did=session.did,
            accepts_interactions=accepts_interactions,
        )

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            try:
                self._audit({
                    "event":       "bluesky_feed_put_record",
                    "account_id":  account_id,
                    "rkey":        rkey,
                    "operation":   operation,
                    "display_name": display_name,
                })

                resp = await client.put_record(
                    collection="app.bsky.feed.generator",
                    rkey=rkey,
                    record=record,
                )

                feed_uri = resp.get("uri", f"at://{session.did}/app.bsky.feed.generator/{rkey}")

                log.info(
                    "[bluesky_feed/%s] Feed record %s: %s",
                    account_id, operation, feed_uri,
                )

            except BlueSkySessionExpired:
                log.warning("[bluesky_feed/%s] Session expired", account_id)
                result.errors.append("session_expired")
                run.outputs["result"]    = result
                run.outputs["operation"] = operation
                return True

            except BlueSkyRateLimited as exc:
                log.warning("[bluesky_feed/%s] Rate limited — %ds", account_id, exc.retry_after_sec)
                result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
                run.outputs["result"]    = result
                run.outputs["operation"] = operation
                return True

            except Exception as exc:
                log.error("[bluesky_feed/%s] Feed record PUT failed: %s", account_id, exc)
                result.errors.append(f"put_record_error:{exc}")
                run.outputs["result"]    = result
                run.outputs["operation"] = operation
                return True

        self._audit({
            "event":       "bluesky_feed_end",
            "account_id":  account_id,
            "feed_uri":    feed_uri,
            "operation":   operation,
            "errors":      len(result.errors),
        })

        run.outputs["feed_uri"]  = feed_uri
        run.outputs["rkey"]      = rkey
        run.outputs["operation"] = operation
        run.outputs["result"]    = result
        return True
