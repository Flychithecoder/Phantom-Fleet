"""
XDMChatAgent — AI-powered DM inbox responder for X (Twitter).

Inherits _BaseDMChatAgent for shared LLM call, tell-stripping, daily-cap,
min-gap, PPV pitch, human-handoff, and XML-delimited prompt logic.

X-specific parameters:
    platform_name       = "x"
    max_daily_replies   = 35
    min_gap_sec         = 90.0   (X DMs feel spammy if replied faster)
    max_tokens          = 140    (X culture: punchy and concise)
    inter_conv_sleep    = LogNormal(mean=ln(75), σ=0.45)

Behaviour:
    1. Calls client.get_timeline() to establish session activity (real user
       opens timeline before checking DMs).
    2. Polls DM inbox via XClient GQL_GET_DM_INBOX endpoint.
    3. For each unread thread:
        - Check daily cap (35/day, code-enforced)
        - Check 90s min gap per conversation
        - Build XML-delimited prompt from X_MIXED ChatModeProfile
        - Call OpenRouter (claude-haiku-4-5-20251001, temp=0.85, max_tokens=140)
        - Strip LLM tells
        - Send via client.send_dm()
        - Sleep LogNormal(mean=ln(75), σ=0.45) between conversations
    4. Pitch PPV at max_turns_before_cta threshold
    5. Flag human handoff for real_human mode

Detection hardening (CLAUDE.md fleet-level):
    - Timeline fetch before DM check matches real X app session flow
    - Reply timing: LogNormal, never uniform
    - XML-delimited conversation content prevents prompt injection
    - LLM tells stripped before every send
    - Credentials never in prompts — OPENROUTER_API_KEY from env only
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from ..base import Agent, AgentConfig, AgentRun
from ._base_chat import (
    _BaseDMChatAgent,
    WorkerResult,
    ConversationState,
)
from ...core.chat_modes import X_MIXED, ChatModeProfile
from ...core.distributions import LogNormal
from ...core.x_client import (
    XClient,
    XSession,
    XSessionExpired,
    XRateLimited,
    GQL_GET_DM_INBOX,
)

log = logging.getLogger(__name__)


class XDMChatAgent(_BaseDMChatAgent, Agent):
    """
    AI-powered DM inbox responder for X.

    ctx keys:
        account_id    (str)       — Phantom Fleet account ID
        session       (XSession)  — pre-built X session
        date_iso      (str)       — YYYY-MM-DD (defaults to today)
        proxy_url     (str)       — SOCKS5 proxy (optional)

    Outputs (run.outputs):
        result  (WorkerResult)  — replies_sent, threads_touched, ppv_pitched, errors
    """

    # _BaseDMChatAgent parameters
    platform_name         = "x"
    max_daily_replies     = 35
    min_gap_sec           = 90.0
    max_tokens            = 140
    inter_conv_sleep_dist = LogNormal(low=30.0, high=200.0, sigma=0.45)

    config = AgentConfig(
        name="x_dm_chat",
        max_iterations=1,
        max_usd_per_run=0.10,
        max_usd_per_session=1.50,
        allowed_tools=(),
    )

    def __init__(self, **kwargs) -> None:
        _BaseDMChatAgent.__init__(self)
        Agent.__init__(self, **kwargs)

    # ------------------------------------------------------------------
    # _BaseDMChatAgent interface
    # ------------------------------------------------------------------

    def _get_chat_mode_profile(self) -> ChatModeProfile:
        return X_MIXED

    async def _fetch_conversations(self, client: Any) -> list[dict]:
        """
        Fetch unread DM threads from X's DM inbox.

        Returns a normalised list of dicts:
            conv_id     str   — conversation identifier
            messages    list  — messages in the thread
            unread      bool  — whether thread has unread messages
            recipient_id str  — who to reply to
        """
        try:
            resp = await client._graphql_get(
                f"{GQL_GET_DM_INBOX}/DMInbox",
                variables={
                    "filter": "DEFAULT",
                    "count": 20,
                },
            )
        except Exception as exc:
            log.warning("[x_dm/%s] DM inbox fetch failed: %s", self.platform_name, exc)
            return []

        conversations: list[dict] = []
        # Navigate X GraphQL response structure
        inbox = (
            resp.get("data", {})
                .get("inbox_initial_state", {})
                .get("conversations", {})
        )
        for conv_id, conv_data in (inbox or {}).items():
            messages_raw = conv_data.get("messages", [])
            # Determine if there are unread messages (messages we haven't sent)
            our_user_id = getattr(client.session, "user_id", "")
            unread = any(
                m.get("message_data", {}).get("sender_id") != our_user_id
                for m in messages_raw[-3:]   # check last 3
            )
            if not unread:
                continue

            # Normalise messages for _BaseDMChatAgent._build_prompt
            messages = []
            for m in messages_raw[-10:]:
                mdata = m.get("message_data", {})
                sender_id = mdata.get("sender_id", "")
                role = "us" if sender_id == our_user_id else "them"
                messages.append({
                    "role":    role,
                    "text":    mdata.get("text", ""),
                    "msg_id":  m.get("id", ""),
                })

            # Identify the other participant to reply to
            participants = conv_data.get("participants", [])
            recipient_id = next(
                (p.get("user_id") for p in participants if p.get("user_id") != our_user_id),
                "",
            )

            conversations.append({
                "conv_id":      conv_id,
                "messages":     messages,
                "unread":       True,
                "recipient_id": recipient_id,
            })

        return conversations

    async def _send_reply(self, client: Any, conv: dict, text: str) -> None:
        """Send a DM reply via XClient.send_dm()."""
        recipient_id = conv.get("recipient_id", "")
        if not recipient_id:
            raise ValueError(f"No recipient_id in conv {conv.get('conv_id')}")
        await client.send_dm(recipient_id=recipient_id, text=text)

    # ------------------------------------------------------------------
    # Agent.run_once
    # ------------------------------------------------------------------

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id: str      = ctx["account_id"]
        session:    XSession = ctx["session"]
        date_iso:   str      = ctx.get("date_iso", date.today().isoformat())
        proxy_url:  str      = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        self._audit({
            "event": "x_dm_chat_session_start",
            "account_id": account_id,
        })

        async with XClient(session, proxy_url=proxy_url) as client:
            # Timeline fetch first — mirrors real X app flow
            try:
                await client.get_timeline(count=10)
            except Exception:
                pass   # non-fatal; continue to DM check

            result = await self._run_dm_session(
                client=client,
                account_id=account_id,
                date_iso=date_iso,
                ppv_turn_threshold=X_MIXED.max_turns_before_cta,
            )

        self._audit({
            "event": "x_dm_chat_session_end",
            "account_id": account_id,
            "replies_sent": result.replies_sent,
            "threads_touched": result.threads_touched,
            "ppv_pitched": result.ppv_pitched,
            "errors": len(result.errors),
        })

        run.outputs["result"] = result
        return True
