"""
RedditShadowbanCheckAgent — probes whether a Reddit account is shadowbanned.

How Reddit shadowbanning works:
    - A shadowbanned account can still post and comment normally from its own
      perspective (authenticated view).
    - But all of its content is invisible to logged-out users and other accounts.
    - The account owner sees their posts, but nobody else does.

Detection method:
    1. Authenticated call: fetch the account's recent comments via the account's
       own session → get authenticated_count.
    2. Unauthenticated call: fetch the same user's comments via a plain httpx
       client with NO auth headers to reddit.com (not oauth.reddit.com) →
       get public_count.
    3. Compare:
       - If public returns 404 or user not found → "shadowbanned"
       - If public_count == 0 and authenticated_count > 0 → "shadowbanned"
       - If public_count < authenticated_count * 0.5 → "uncertain" (partial shadow)
       - Otherwise → "clean"

Quarantine logic:
    If status == "shadowbanned", set quarantine_until_iso to now + 48h.
    The manager should not send this account to shadowban_check again until
    after quarantine_until_iso.

Fleet-scale note:
    This agent uses a SEPARATE unauthenticated httpx client so the check
    does not contaminate the account's session or cookies.
    The unauthenticated request uses no User-Agent or a generic browser UA
    to simulate a logged-out visitor.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ..base import Agent, AgentConfig, AgentRun
from ...core.reddit_client import (
    RedditClient,
    RedditSession,
    RedditSessionExpired,
    RedditRateLimited,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUARANTINE_HOURS     = 48
UNCERTAIN_THRESHOLD  = 0.5  # public_count < 50% of authenticated → uncertain
PUBLIC_API_BASE      = "https://www.reddit.com"

# ---------------------------------------------------------------------------
# Status values
# ---------------------------------------------------------------------------

STATUS_CLEAN       = "clean"
STATUS_SHADOWBANNED = "shadowbanned"
STATUS_UNCERTAIN    = "uncertain"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class RedditShadowbanCheckAgent(Agent):
    """
    Probes whether a Reddit account is shadowbanned.

    ctx keys:
        account_id:   str
        username:     str    (Reddit username, no /u/ prefix)
        session:      RedditSession  (for authenticated count)
        proxy_url:    str    (optional SOCKS5 proxy for authenticated calls)
    """

    config = AgentConfig(
        name="reddit_shadowban_check",
        max_iterations=1,
        max_usd_per_run=0.00,
        max_usd_per_session=0.00,
        allowed_tools=(
            "db.update_account_status",
            "db.set_shadowban_quarantine",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id = ctx["account_id"]
        username   = ctx.get("username") or ctx.get("session", {}) and ctx["session"].username
        session: RedditSession = ctx["session"]
        proxy_url  = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        if not username:
            username = session.username

        self._audit_event(run, "shadowban_check_start", {
            "account_id": account_id,
            "username": username,
        })

        # ------------------------------------------------------------------
        # 1. Authenticated count — how many comments does the account think it has?
        # ------------------------------------------------------------------
        authenticated_count = 0
        try:
            async with RedditClient(session, proxy_url=proxy_url) as client:
                auth_resp = await client._get(
                    f"user/{username}/comments",
                    params={"limit": 25},
                )
            auth_children = auth_resp.get("data", {}).get("children", [])
            authenticated_count = len(auth_children)
        except RedditSessionExpired:
            log.warning("Session expired for %s during shadowban check", account_id)
            run.outputs["session_expired"] = True
            return True
        except RedditRateLimited as e:
            log.warning("Rate limited for %s during shadowban check", account_id)
            run.outputs["rate_limited"]  = True
            run.outputs["retry_after"]   = e.retry_after_sec
            return True
        except Exception as e:
            log.warning("Auth check failed for %s: %s", account_id, e)
            authenticated_count = -1  # unknown

        # ------------------------------------------------------------------
        # 2. Unauthenticated count — what does a logged-out visitor see?
        # Uses plain HTTPS to reddit.com, no Authorization header.
        # ------------------------------------------------------------------
        public_count = 0
        is_404       = False

        try:
            async with httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Reddit/shadowban-check)",
                    "Accept":     "application/json",
                },
                timeout=httpx.Timeout(15.0),
                follow_redirects=True,
            ) as anon_client:
                resp = await anon_client.get(
                    f"{PUBLIC_API_BASE}/user/{username}/comments.json",
                    params={"limit": 25},
                )
                if resp.status_code == 404:
                    is_404 = True
                elif resp.status_code == 200:
                    data = resp.json()
                    children = data.get("data", {}).get("children", [])
                    public_count = len(children)
                else:
                    log.warning(
                        "Unexpected status %d for public check of %s",
                        resp.status_code, username,
                    )
                    is_404 = True  # treat unexpected as not-found
        except httpx.HTTPError as e:
            log.warning("Public check HTTP error for %s: %s", username, e)
            is_404 = True

        # ------------------------------------------------------------------
        # 3. Determine status
        # ------------------------------------------------------------------
        if is_404:
            status = STATUS_SHADOWBANNED
        elif authenticated_count > 0 and public_count == 0:
            status = STATUS_SHADOWBANNED
        elif (
            authenticated_count > 0
            and public_count < authenticated_count * UNCERTAIN_THRESHOLD
        ):
            status = STATUS_UNCERTAIN
        else:
            status = STATUS_CLEAN

        # ------------------------------------------------------------------
        # 4. Set quarantine if shadowbanned
        # ------------------------------------------------------------------
        quarantine_until_iso: Optional[str] = None
        if status == STATUS_SHADOWBANNED:
            quarantine_until = datetime.now(timezone.utc) + timedelta(hours=QUARANTINE_HOURS)
            quarantine_until_iso = quarantine_until.isoformat()
            log.warning(
                "Account %s (%s) is shadowbanned — quarantine until %s",
                account_id, username, quarantine_until_iso,
            )

        self._audit_event(run, "shadowban_check_result", {
            "account_id":           account_id,
            "username":             username,
            "status":               status,
            "authenticated_count":  authenticated_count,
            "public_count":         public_count,
            "is_404":               is_404,
            "quarantine_until_iso": quarantine_until_iso,
        })

        run.outputs.update({
            "status":                status,
            "authenticated_post_count": authenticated_count,
            "public_post_count":     public_count,
            "shadowbanned":          status == STATUS_SHADOWBANNED,
            "quarantine_until_iso":  quarantine_until_iso,
        })
        return True

    def _audit_event(self, run: AgentRun, event_type: str, data: dict) -> None:
        event = {
            "event": event_type,
            "ts":    datetime.now(timezone.utc).isoformat(),
            "agent": self.config.name,
            **data,
        }
        run.audit_events.append(event)
        self.audit_sink(event)
