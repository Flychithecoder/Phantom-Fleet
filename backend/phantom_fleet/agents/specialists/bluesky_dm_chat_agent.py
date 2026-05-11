"""
BlueSkyDMChatAgent — AI inbox responder for BlueSky DMs.

Uses AT Protocol chat.bsky.app lexicon (com.atproto.repo / chat.bsky.convo.*).

Inherits _BaseDMChatAgent for shared LLM call, tell-stripping, daily-cap,
min-gap, PPV pitch, human-handoff, and XML-delimited prompt logic.

BlueSky-specific parameters:
    platform_name       = "bluesky"
    max_daily_replies   = 40       (BlueSky more tolerant than X)
    min_gap_sec         = 60.0
    max_tokens          = 160      (BlueSky culture: thoughtful, more words OK)
    inter_conv_sleep    = LogNormal(mean=ln(55), σ=0.4)

Conversation fetch uses:
    client._get("chat.bsky.convo.listConvos")
    client._get("chat.bsky.convo.getMessages", {"convoId": id})

Reply sent via:
    client._post("chat.bsky.convo.sendMessage", {...})

AT Protocol DM lexicon note:
    The chat.bsky.app service runs as a separate subdomain at
    https://api.bsky.chat/xrpc/ but we route through the same proxy-backed
    BlueSkyClient which already handles auth. The _get / _post helpers are
    used with full lexicon IDs.
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
from ...core.chat_modes import BLUESKY_MIXED, ChatModeProfile
from ...core.distributions import LogNormal
from ...core.bluesky_ab_test import BlueSkyABManager
from ...core.bluesky_client import (
    BlueSkyClient,
    BlueSkySession,
    BlueSkySessionExpired,
    BlueSkyRateLimited,
)

log = logging.getLogger(__name__)

# AT Protocol DM lexicon base (chat service endpoint)
_CHAT_BASE = "https://api.bsky.chat/xrpc"


class BlueSkyDMChatAgent(_BaseDMChatAgent, Agent):
    """
    AI-powered DM inbox responder for BlueSky.

    ctx keys:
        account_id    (str)             — Phantom Fleet account ID
        session       (BlueSkySession)  — pre-built session
        date_iso      (str)             — YYYY-MM-DD (defaults to today)
        proxy_url     (str)             — SOCKS5 proxy (optional)

    Outputs (run.outputs):
        result  (WorkerResult)  — replies_sent, threads_touched, ppv_pitched, errors
    """

    # _BaseDMChatAgent parameters
    platform_name         = "bluesky"
    max_daily_replies     = 40
    min_gap_sec           = 60.0
    max_tokens            = 160
    inter_conv_sleep_dist = LogNormal(low=20.0, high=160.0, sigma=0.40)

    config = AgentConfig(
        name="bluesky_dm_chat",
        max_iterations=1,
        max_usd_per_run=0.10,
        max_usd_per_session=1.50,
        allowed_tools=(),
    )

    def __init__(self, **kwargs) -> None:
        _BaseDMChatAgent.__init__(self)
        Agent.__init__(self, **kwargs)
        # A/B metadata — populated in run_once, used in _send_reply
        self._ab_test_id:    str = ""
        self._ab_variant_id: str = ""
        self._ab_account_id: str = ""
        # Single shared instance — avoids re-instantiation on every DM send
        self._ab_mgr = BlueSkyABManager()

    # ------------------------------------------------------------------
    # _BaseDMChatAgent interface
    # ------------------------------------------------------------------

    def _get_chat_mode_profile(self) -> ChatModeProfile:
        return BLUESKY_MIXED

    async def _fetch_conversations(self, client: Any) -> list[dict]:
        """
        List BlueSky DM conversations and return normalised conv dicts.

        Uses the chat.bsky.convo.listConvos lexicon. For each conversation
        with unread messages, fetches recent messages via getMessages.
        """
        our_did = client.session.did

        try:
            # Route through the chat subdomain (api.bsky.chat, not bsky.social)
            resp = await client._get(
                "chat.bsky.convo.listConvos",
                params={"limit": 20},
                base_url=_CHAT_BASE,
            )
        except Exception as exc:
            log.warning(
                "[bluesky_dm/%s] listConvos failed: %s",
                self.platform_name, exc,
            )
            return []

        conversations: list[dict] = []
        for convo in resp.get("convos", []):
            conv_id  = convo.get("id", "")
            unread   = convo.get("unreadCount", 0)
            if not conv_id or not unread:
                continue

            # Fetch recent messages
            try:
                msgs_resp = await client._get(
                    "chat.bsky.convo.getMessages",
                    params={"convoId": conv_id, "limit": 10},
                    base_url=_CHAT_BASE,
                )
            except Exception as exc:
                log.warning(
                    "[bluesky_dm/%s] getMessages failed for %s: %s",
                    self.platform_name, conv_id, exc,
                )
                continue

            raw_msgs = msgs_resp.get("messages", [])
            messages = []
            for m in raw_msgs:
                sender_did = m.get("sender", {}).get("did", "")
                role = "us" if sender_did == our_did else "them"
                text = m.get("text", "")
                messages.append({"role": role, "text": text, "msg_id": m.get("id", "")})

            # Find the other participant's DID to reply to
            members = convo.get("members", [])
            recipient_did = next(
                (m.get("did") for m in members if m.get("did") != our_did),
                "",
            )

            conversations.append({
                "conv_id":       conv_id,
                "messages":      messages,
                "unread":        True,
                "recipient_did": recipient_did,
            })

        return conversations

    async def _send_reply(self, client: Any, conv: dict, text: str) -> None:
        """Send a DM reply via chat.bsky.convo.sendMessage + optional A/B recording."""
        conv_id       = conv.get("conv_id", "")
        recipient_did = conv.get("recipient_did", "")
        await client._post(
            "chat.bsky.convo.sendMessage",
            payload={
                "convoId": conv_id,
                "message": {"text": text},
            },
            base_url=_CHAT_BASE,
        )
        if self._ab_test_id and self._ab_variant_id and self._ab_account_id:
            try:
                self._ab_mgr.record_dm_sent(
                    self._ab_test_id,
                    self._ab_account_id,
                    self._ab_variant_id,
                    recipient_did,
                )
            except Exception:
                pass  # never let A/B recording break the DM send

    # ------------------------------------------------------------------
    # Agent.run_once
    # ------------------------------------------------------------------

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id: str              = ctx["account_id"]
        session:    BlueSkySession   = ctx["session"]
        date_iso:   str              = ctx.get("date_iso", date.today().isoformat())
        proxy_url:  str              = ctx.get("proxy_url", "socks5://127.0.0.1:8089")

        # Store A/B metadata on instance so _send_reply can access it
        self._ab_test_id    = ctx.get("ab_test_id", "")
        self._ab_variant_id = ctx.get("ab_variant_id", "")
        self._ab_account_id = account_id

        self._audit({
            "event": "bluesky_dm_chat_session_start",
            "account_id": account_id,
            "ab_test_id": self._ab_test_id or None,
        })

        async with BlueSkyClient(session, proxy_url=proxy_url) as client:
            result = await self._run_dm_session(
                client=client,
                account_id=account_id,
                date_iso=date_iso,
                ppv_turn_threshold=BLUESKY_MIXED.max_turns_before_cta,
            )

        self._audit({
            "event": "bluesky_dm_chat_session_end",
            "account_id": account_id,
            "replies_sent": result.replies_sent,
            "threads_touched": result.threads_touched,
            "ppv_pitched": result.ppv_pitched,
            "errors": len(result.errors),
        })

        run.outputs["result"] = result
        return True
