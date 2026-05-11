"""
DatingChatSessionManager — coordinates DatingChatAgent across all accounts
on a phone, enforcing concurrency limits and producing a summary report.

Responsibilities:
    - Accept a list of account dicts with their active platform sessions
    - Run DatingChatAgent for each account concurrently (max 3 via semaphore)
    - Aggregate per-account results into a ChatSessionReport
    - Never crash the whole run if one account fails — log and continue

Concurrency model:
    asyncio.Semaphore(3) caps simultaneous account runs. This matches
    the hybrid-runner model: we do not want all 10+ accounts on a phone
    hammering inboxes simultaneously — that's a timing cluster fingerprint.
    3 concurrent is enough for throughput without creating a batch-start spike.

Account dict format:
    account_id:  str                                — stable internal ID
    chat_tier:   ChatTier | int                     — content tier for this account
    sessions:    dict[str, TinderSession | ...]     — platform → session objects
    date_iso:    str | None                         — YYYY-MM-DD (defaults to today)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from .dating_chat_agent import DatingChatAgent, ChatReplyRecord
from ...core.chat_modes import ChatTier

log = logging.getLogger(__name__)

# Max simultaneous account runs — semaphore-enforced (not prompt-enforced)
MAX_CONCURRENT_ACCOUNTS: int = 3


@dataclass
class ChatSessionReport:
    """Aggregate result of one chat session run across all accounts."""
    date_iso:                   str
    accounts_processed:         int = 0
    total_replies_sent:         int = 0
    total_conversations_touched: int = 0
    ppv_pitches_made:           int = 0
    human_handoff_flagged:      int = 0
    errors:                     list[str] = field(default_factory=list)
    per_account:                dict[str, dict] = field(default_factory=dict)


class DatingChatSessionManager:
    """
    Coordinates DatingChatAgent runs across multiple accounts on one phone.

    Usage:
        manager = DatingChatSessionManager()
        report = await manager.run_all_accounts(accounts, date_iso="2026-04-11")
    """

    def __init__(self) -> None:
        pass

    async def run_all_accounts(
        self,
        accounts: list[dict],
        date_iso: str | None = None,
    ) -> ChatSessionReport:
        """
        Run chat sessions for all accounts concurrently (max 3 at a time).

        Args:
            accounts:   List of account dicts. Each must have:
                        - account_id: str
                        - chat_tier: ChatTier | int
                        - sessions: dict[str, session_object]
                        - date_iso (optional): YYYY-MM-DD
            date_iso:   Global date override. Per-account date_iso takes priority.

        Returns:
            ChatSessionReport aggregating all results.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        report = ChatSessionReport(date_iso=date_iso)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_ACCOUNTS)

        tasks = [
            self._run_one_account(account, date_iso, semaphore, report)
            for account in accounts
        ]

        await asyncio.gather(*tasks, return_exceptions=False)
        return report

    async def _run_one_account(
        self,
        account: dict,
        default_date_iso: str,
        semaphore: asyncio.Semaphore,
        report: ChatSessionReport,
    ) -> None:
        """Run DatingChatAgent for a single account under the semaphore gate."""
        account_id: str = account["account_id"]
        date_iso: str = account.get("date_iso") or default_date_iso
        sessions: dict = account.get("sessions", {})
        raw_tier = account.get("chat_tier", ChatTier.FLIRTY_SFW)
        try:
            chat_tier = ChatTier(int(raw_tier))
        except (ValueError, KeyError):
            chat_tier = ChatTier.FLIRTY_SFW

        if not sessions:
            report.errors.append(f"{account_id}: no sessions provided")
            return

        action_log: list[dict] = []

        async with semaphore:
            log.info("[manager] Starting chat session for %s", account_id)
            agent = DatingChatAgent()
            try:
                records: list[ChatReplyRecord] = await agent.run_session(
                    account_id=account_id,
                    platforms=sessions,
                    chat_tier=chat_tier,
                    date_iso=date_iso,
                    action_log=action_log,
                )
            except Exception as exc:
                err = f"{account_id}: unexpected error — {exc}"
                log.error("[manager] %s", err)
                report.errors.append(err)
                return

        # Tally results
        replies_sent = len(records)
        conversations_touched = len({r.conversation_id for r in records})
        ppv_count = sum(1 for r in records if r.ppv_pitched)
        handoff_count = sum(
            1 for evt in action_log
            if evt.get("event") == "human_handoff_flagged"
        )

        report.accounts_processed += 1
        report.total_replies_sent += replies_sent
        report.total_conversations_touched += conversations_touched
        report.ppv_pitches_made += ppv_count
        report.human_handoff_flagged += handoff_count

        report.per_account[account_id] = {
            "replies_sent": replies_sent,
            "conversations_touched": conversations_touched,
            "ppv_pitches_made": ppv_count,
            "human_handoff_flagged": handoff_count,
            "errors": [
                evt for evt in action_log
                if evt.get("event") in (
                    "llm_error",
                    "reply_send_failed",
                    "conversation_skipped_llm_failure",
                    "platform_error",
                )
            ],
        }

        log.info(
            "[manager] %s done: %d replies, %d convs, %d ppv, %d handoffs",
            account_id, replies_sent, conversations_touched, ppv_count, handoff_count,
        )
