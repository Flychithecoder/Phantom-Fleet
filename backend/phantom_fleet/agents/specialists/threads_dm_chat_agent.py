"""
ThreadsDMChatAgent — AI-powered DM inbox responder for Threads.

Threads shares DM infrastructure with Instagram. The DM inbox, threads, and
message send endpoints are the same as Instagram's direct_v2 API, accessed
via the same IGSession and device headers. No separate Threads login needed.

Inherits all core logic from _BaseDMChatAgent:
    - LLM reply generation (claude-haiku-4-5-20251001)
    - LLM tell stripping
    - Conversation state tracking
    - Daily cap enforcement (40 msgs/day, code-enforced)
    - Min 90s gate between replies to same thread (code-enforced)
    - PPV pitch at configured message threshold
    - Human handoff flagging
    - XML-delimited prompt construction

Platform-specific overrides:
    - _fetch_inbox() → client.get_inbox() (same endpoint as IG)
    - _send_reply()  → client.send_dm() (same endpoint as IG)
    - _build_client() → InstagramClient context manager (shared session)
    - platform_name = "threads"
    - _default_profile = THREADS_CASUAL (ChatTier.CASUAL_SFW)

Note on tone: Threads DMs use THREADS_CASUAL (tier 2) rather than INSTAGRAM_FLIRTY
(tier 3). Threads is a public-by-default text platform with a more conversational,
less flirty culture. The profile system enforces this boundary automatically.

Agent audit table (CLAUDE.md):
    ┌─────────────────┬──────────────────────────────────────────────────────┐
    │ Agent           │ ThreadsDMChatAgent                                   │
    │ Purpose         │ AI-powered Threads DM inbox responder                │
    │ Tools           │ None — direct HTTP via InstagramClient (shared sess) │
    │ Untrusted input │ DM message bodies (XML-delimited in all prompts)     │
    │ User isolation  │ Keyed by (account_id, "threads", thread_id)          │
    │ Cost cap        │ 40 replies × $0.00025 ≈ $0.01/account/day           │
    │ Loop cap        │ MAX_CONVERSATIONS_PER_SESSION = 20 (code-enforced)   │
    │ Confirmation    │ None required (non-destructive sends)                │
    └─────────────────┴──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import logging
from typing import Optional

from ...core.chat_modes import (
    THREADS_CASUAL,
    ChatModeProfile,
    ChatTier,
)
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGSession,
    InstagramClient,
)
from .base_dm_chat_agent import _BaseDMChatAgent

log = logging.getLogger(__name__)


class ThreadsDMChatAgent(_BaseDMChatAgent):
    """
    AI-powered Threads DM inbox responder.

    Threads shares Instagram DM infrastructure, so this agent uses the
    same InstagramClient and IGSession as the IG DM agent. The only
    differences are the platform name and the default chat profile.

    Usage:
        agent = ThreadsDMChatAgent()
        result = await agent.run_session(
            account_id="acct_001",
            session=ig_session,   # shared IG/Threads session
            chat_tier=ChatTier.CASUAL_SFW,
            date_iso="2026-04-11",
            ppv_pitch_after_msgs=6,
        )

    Returns a WorkerResult with `data` keys:
        replies_sent, threads_touched, ppv_pitched,
        human_handoff_flagged, errors
    """

    platform_name: str = "threads"
    _default_profile: ChatModeProfile = THREADS_CASUAL

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        chat_tier: ChatTier = ChatTier.CASUAL_SFW,
        date_iso: Optional[str] = None,
        ppv_pitch_after_msgs: int = 6,
    ) -> WorkerResult:
        """
        Process the Threads DM inbox for one account.

        Args:
            account_id:           Internal account identifier.
            session:              Authenticated IGSession (shared with Threads).
            chat_tier:            ChatTier controlling which profile/voice is used.
                                  Threads defaults to CASUAL_SFW (tier 2).
            date_iso:             YYYY-MM-DD (defaults to today UTC).
            ppv_pitch_after_msgs: Messages exchanged before appending PPV pitch.
                                  Defaults to 6 (higher than IG's 4 — Threads
                                  audiences are less pre-warmed for CTAs).

        Returns:
            WorkerResult with detailed summary in data dict.
        """
        task_id = f"{account_id}_threads_dm_{date_iso or 'today'}"

        try:
            summary = await self._run_inbox(
                account_id=account_id,
                session=session,
                chat_tier=chat_tier,
                date_iso=date_iso,
                ppv_pitch_after_msgs=ppv_pitch_after_msgs,
            )
        except Exception as exc:
            log.error("[%s/threads] Session-level error: %s", account_id, exc)
            return WorkerResult(
                task_id=task_id,
                platform="threads",
                account_id=account_id,
                success=False,
                error=str(exc),
                data={},
            )

        return WorkerResult(
            task_id=task_id,
            platform="threads",
            account_id=account_id,
            success=True,
            data={
                "action":                "threads_dm_chat",
                "replies_sent":          summary["replies_sent"],
                "threads_touched":       summary["threads_touched"],
                "ppv_pitched":           summary["ppv_pitched"],
                "human_handoff_flagged": summary["human_handoff_flagged"],
                "errors":                summary["errors"],
            },
        )

    # ------------------------------------------------------------------
    # Platform-specific implementations
    # ------------------------------------------------------------------

    def _build_client(self, session: IGSession):
        """Return an InstagramClient async context manager (shared IG/Threads)."""
        return InstagramClient(session)

    async def _fetch_inbox(self, client: InstagramClient, cursor: str) -> dict:
        """Fetch the Threads DM inbox (same IG direct_v2 endpoint)."""
        return await client.get_inbox(cursor=cursor)

    async def _send_reply(
        self,
        client: InstagramClient,
        thread_id: str,
        recipient_id: str,
        text: str,
    ) -> None:
        """Send a DM reply on Threads (same IG send_dm endpoint)."""
        await client.send_dm(recipient_user_id=recipient_id, text=text)
