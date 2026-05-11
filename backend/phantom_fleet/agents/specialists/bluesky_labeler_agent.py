"""
BlueSkyLabelerAgent — publish and maintain labeler service records on BlueSky.

AT Protocol labeler overview:
    A "labeler" is a service that attaches semantic labels to AT Protocol content
    (posts, accounts, feeds). Labels are used by BlueSky clients to apply content
    warnings, hiding, or category tags. Any DID can publish a labeler service record
    under collection `app.bsky.labeler.service`.

    The labeler record declares:
        - Which label values this service can emit (e.g. "spam", "nsfw", "gore")
        - A policies object with optional custom label definitions
        - Timestamps

    Phantom Fleet labeler usage:
        Publishing a labeler record is a no-cost signal of operator identity on the
        AT Protocol. Accounts with labeler records are treated as "service" accounts
        rather than plain user accounts, which provides:
            - Immunity to certain automated report classifiers
            - Access to the `app.bsky.moderation.defs` label set
            - Visibility in the BlueSky moderation dashboard

Operations:
    publish:  PUT app.bsky.labeler.service record (idempotent upsert).
    refresh:  Update the record (same as publish — putRecord is always safe to retry).
    disable:  Remove the labeler record by deleting it via deleteRecord.

Fleet-scale notes:
    - Each account that runs this agent publishes its OWN labeler record.
    - rkey is always "self" — the AT Protocol convention for labeler service records.
    - No timing sleeps needed — single write operation, not a mass-action loop.
    - Run weekly (manager dispatches only on ctx["is_weekly"]).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import WorkerResult
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)

# rkey is always "self" for labeler service records (AT Protocol convention)
_LABELER_RKEY = "self"

# Default label values a Phantom Fleet labeler declares.
# These are the minimal set that lets a labeler be recognised as a valid service.
_DEFAULT_LABEL_VALUES: list[str] = [
    "spam",
    "impersonation",
    "misleading",
]


def _build_labeler_record(
    label_values: list[str],
    created_at:   str,
) -> dict:
    """
    Build an app.bsky.labeler.service record.

    AT Protocol schema:
        app.bsky.labeler.service:
            policies:
                labelValues:            list[str]
                labelValueDefinitions:  list[LabelValueDefinition]  (optional)
            createdAt:  datetime string
    """
    return {
        "$type":     "app.bsky.labeler.service",
        "policies":  {
            "labelValues": label_values or _DEFAULT_LABEL_VALUES,
        },
        "createdAt": created_at,
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BlueSkyLabelerAgent(Agent):
    """
    Publish or remove the labeler service record for one BlueSky account.

    ctx keys:
        account_id:    str
        session:       BlueSkySession
        operation:     str            — "publish" | "refresh" | "disable"
                                        (default: "publish")
        label_values:  list[str]      — label values to declare (default: _DEFAULT_LABEL_VALUES)
        date_iso:      str
        proxy_url:     str

    Outputs (run.outputs):
        record_uri:  str         — AT URI of the labeler record (publish/refresh only)
        operation:   str         — operation performed
        result:      WorkerResult
    """

    config = AgentConfig(
        name="bluesky_labeler",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:   str            = ctx["account_id"]
        session:      BlueSkySession = ctx["session"]
        operation:    str            = ctx.get("operation", "publish")
        label_values: list[str]      = ctx.get("label_values") or _DEFAULT_LABEL_VALUES
        date_iso:     str            = ctx.get("date_iso", date.today().isoformat())
        proxy_url:    str            = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        result = WorkerResult()

        self._audit({
            "event":        "bluesky_labeler_start",
            "account_id":   account_id,
            "operation":    operation,
            "label_values": label_values,
        })

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            if operation in ("publish", "refresh"):
                record_uri = await self._publish(
                    client, account_id, session.did, label_values, result
                )
                run.outputs["record_uri"] = record_uri
            elif operation == "disable":
                await self._disable(client, account_id, session.did, result)
                run.outputs["record_uri"] = ""
            else:
                log.warning(
                    "[bluesky_labeler/%s] Unknown operation %r — skipping",
                    account_id, operation,
                )
                result.errors.append(f"unknown_operation:{operation}")

        self._audit({
            "event":      "bluesky_labeler_end",
            "account_id": account_id,
            "operation":  operation,
            "errors":     len(result.errors),
        })

        run.outputs["operation"] = operation
        run.outputs["result"]    = result
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _publish(
        self,
        client:       BlueSkyClient,
        account_id:   str,
        did:          str,
        label_values: list[str],
        result:       WorkerResult,
    ) -> str:
        """Upsert the labeler service record; returns the AT URI on success."""
        created_at = datetime.now(timezone.utc).isoformat()
        record = _build_labeler_record(label_values, created_at)

        try:
            resp = await client.put_record(
                collection="app.bsky.labeler.service",
                rkey=_LABELER_RKEY,
                record=record,
            )
            uri = resp.get("uri", f"at://{did}/app.bsky.labeler.service/{_LABELER_RKEY}")
            log.info("[bluesky_labeler/%s] Labeler record published: %s", account_id, uri)
            return uri

        except BlueSkySessionExpired:
            log.warning("[bluesky_labeler/%s] Session expired — cannot publish", account_id)
            result.errors.append("session_expired")
            return ""

        except BlueSkyRateLimited as exc:
            log.warning(
                "[bluesky_labeler/%s] Rate limited (%ds) — cannot publish",
                account_id, exc.retry_after_sec,
            )
            result.errors.append(f"rate_limited:{exc.retry_after_sec}s")
            return ""

        except Exception as exc:
            log.warning("[bluesky_labeler/%s] Publish failed: %s", account_id, exc)
            result.errors.append(f"publish_error:{exc}")
            return ""

    async def _disable(
        self,
        client:     BlueSkyClient,
        account_id: str,
        did:        str,
        result:     WorkerResult,
    ) -> None:
        """Delete the labeler service record to disable the labeler."""
        try:
            await client._post(
                "com.atproto.repo.deleteRecord",
                payload={
                    "repo":       did,
                    "collection": "app.bsky.labeler.service",
                    "rkey":       _LABELER_RKEY,
                },
            )
            log.info("[bluesky_labeler/%s] Labeler record deleted", account_id)

        except BlueSkySessionExpired:
            log.warning("[bluesky_labeler/%s] Session expired — cannot disable", account_id)
            result.errors.append("session_expired")

        except BlueSkyRateLimited as exc:
            log.warning(
                "[bluesky_labeler/%s] Rate limited (%ds) — cannot disable",
                account_id, exc.retry_after_sec,
            )
            result.errors.append(f"rate_limited:{exc.retry_after_sec}s")

        except Exception as exc:
            err = str(exc).lower()
            if "recordnotfound" in err or "not found" in err or "404" in err:
                # Already absent — treat as success
                log.debug("[bluesky_labeler/%s] Labeler record already absent", account_id)
            else:
                log.warning("[bluesky_labeler/%s] Disable failed: %s", account_id, exc)
                result.errors.append(f"disable_error:{exc}")
