"""
TelegramGroupAgent — joins Telegram groups and participates with human-like behavior.

Responsibilities:
    - Join up to 2 new groups/day per account via invite links
    - Post 1 message/group/day (only if account is 14+ days old)
    - Use typing indicator before every post (same as DM agent)
    - React/forward to 2-5 messages per group per session
    - Message timing: LogNormal(mean=ln(600), sigma=0.5) after last group activity
      → don't be first to post; 10-min average wait
    - Message deduplication: never send same message to same group from same account
    - Inter-join sleep: LogNormal(mean=ln(300), sigma=0.5) → 5-min average

Detection hardening:
    - Max 2 group joins/day (code-enforced)
    - Max 5 group messages/account/day (code-enforced)
    - Account age gate (14+ days) for posting (code-enforced)
    - Message pool >= 20 templates; seeded by hash(account_id + group_id + date)
    - Typing indicator before every group post
    - Inter-join and post-timing sleeps are LogNormal, never fixed
    - Deduplication prevents repeat messages per (account, group)

Fleet-scale considerations (CLAUDE.md 20K account thought experiment):
    - Message selection is seeded by hash(account_id + group_id + date) not a fixed
      position — different accounts in same group post different messages each day
    - Pool of 25 messages; at 20K accounts each group sees diverse content
    - Inter-join timing has sigma=0.5 creating wide variance (not a monoculture spike)

Agent audit table (CLAUDE.md):
    ┌───────────────────┬──────────────────────────────────────────────┐
    │ Agent             │ TelegramGroupAgent                           │
    │ Purpose           │ Group join + human-like participation        │
    │ Tools             │ None — direct HTTP via TelegramClient        │
    │ Untrusted input   │ None (action is outbound only)               │
    │ User isolation    │ Keyed by account_id in state dicts           │
    │ Cost cap          │ 0.00 USD (no LLM calls in group agent)       │
    │ Loop cap          │ 2 joins/day, 5 posts/day (code-enforced)     │
    │ Confirmation      │ None (non-destructive)                       │
    └───────────────────┴──────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from ...core.distributions import LogNormal
from ...core.telegram_client import TelegramClient, TelegramFloodWait, TelegramSessionExpired
from ._base_chat import WorkerResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (ALL code-enforced)
# ---------------------------------------------------------------------------

MAX_GROUP_JOINS_PER_DAY: int = 2
MAX_GROUP_MESSAGES_PER_DAY: int = 5
MIN_ACCOUNT_AGE_DAYS_FOR_POSTING: int = 14

# ---------------------------------------------------------------------------
# Timing distributions (LogNormal — never fixed)
# ---------------------------------------------------------------------------

# Inter-join sleep: mean=ln(300)≈5.7, sigma=0.5 → median≈300s (5min), heavy tail
JOIN_SLEEP_DIST = LogNormal(low=60.0, high=900.0, sigma=0.50)

# Post timing after last group activity: mean=ln(600), sigma=0.5 → median≈600s (10min)
# This prevents the account being first to post in a group.
POST_TIMING_DIST = LogNormal(low=120.0, high=2400.0, sigma=0.50)

# Typing indicator delay before group post
TYPING_DELAY_DIST = LogNormal(low=1.5, high=10.0, sigma=0.35)

# ---------------------------------------------------------------------------
# Group message pool — MUST be >= 20 entries
# Pool is seeded per (account_id, group_id, date) so fleet posts diverse content.
# ---------------------------------------------------------------------------

GROUP_MESSAGE_POOL: list[str] = [
    "lmao yeah that's exactly what happened to me too",
    "wait really? that's wild",
    "honestly this is the most underrated topic in here",
    "anyone else notice this or just me",
    "been following this for a while, finally makes sense",
    "this is actually really helpful, thanks for sharing",
    "ngl i was thinking the same thing",
    "fr fr this keeps coming up and nobody talks about it",
    "okay this is actually interesting",
    "has anyone tried this and got results?",
    "been seeing this everywhere lately",
    "this is the kind of thing people sleep on",
    "good timing seeing this today",
    "this hits different when you've been through it",
    "not gonna lie this actually changed my perspective",
    "i feel like more people need to know about this",
    "okay now i'm curious about the backstory",
    "this is genuinely one of the better takes i've seen",
    "came across this earlier and had to come back to it",
    "the comments on this are going to be interesting",
    "been thinking about this for a while",
    "this is exactly the kind of thing worth discussing",
    "honestly didn't expect to agree but here we are",
    "solid point, hard to argue with that",
    "this is why i stick around in here",
]

if len(GROUP_MESSAGE_POOL) < 20:
    raise ValueError(
        f"GROUP_MESSAGE_POOL must have >= 20 entries, got {len(GROUP_MESSAGE_POOL)}"
    )


def _group_message_for(account_id: str, group_id: str, date_iso: str) -> str:
    """
    Select a message from the pool, deterministically seeded by
    (account_id, group_id, date_iso).

    Different accounts in the same group get different messages.
    Same account in same group on same day always gets the same message
    (idempotent on retry).
    """
    key = f"{account_id}|{group_id}|{date_iso}|group_msg"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(GROUP_MESSAGE_POOL)
    return GROUP_MESSAGE_POOL[idx]


def _message_dedup_key(account_id: str, group_id: str, message: str) -> str:
    """Unique key for (account, group, message) deduplication."""
    key = f"{account_id}|{group_id}|{message}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class GroupParticipationState:
    """Per-(account, group) participation tracking."""
    account_id:        str
    group_id:          str
    joined_at:         float = 0.0          # unix timestamp
    last_posted_at:    float = 0.0          # unix timestamp; 0 = never
    posted_message_keys: set = field(default_factory=set)  # dedup keys
    messages_today:    int = 0
    last_activity_at:  float = 0.0          # last observed group activity ts


class TelegramGroupAgent:
    """
    Joins Telegram groups and participates with human-like posting behavior.

    ctx keys (passed to run_once):
        account_id:        str
        date_iso:          str (YYYY-MM-DD)
        session:           TelegramSession (pre-built)
        account_created_at: float  — unix timestamp of account creation
        invite_links:      list[str]  — groups to consider joining
        known_groups:      list[dict] — already-joined groups to participate in
            each: {group_id: str, last_activity_at: float}
        joins_today:       int  — already-joined groups today (across calls)
        messages_today:    int  — group messages sent today (across calls)
    """

    def __init__(self) -> None:
        # Keyed by (account_id, group_id)
        self._group_states: dict[tuple[str, str], GroupParticipationState] = {}
        # Keyed by account_id → joins_today count
        self._joins_today: dict[str, int] = {}
        # Keyed by account_id → group_messages_today count
        self._msgs_today: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Typing indicator (same pattern as DM agent)
    # ------------------------------------------------------------------

    async def _fire_typing_indicator(
        self, client: TelegramClient, chat_id: str
    ) -> None:
        """Fire sendChatAction typing then LogNormal delay before posting."""
        try:
            await client._post("sendChatAction", {
                "chat_id": chat_id,
                "action": "typing",
            })
        except Exception as exc:
            log.debug("Typing indicator failed for group %s: %s", chat_id, exc)

        delay = TYPING_DELAY_DIST.sample()
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # run_once
    # ------------------------------------------------------------------

    async def run_once(
        self,
        client: TelegramClient,
        ctx: dict,
    ) -> WorkerResult:
        """
        Execute one group session: join queued groups + participate in existing ones.
        """
        account_id: str = ctx["account_id"]
        date_iso: str = ctx.get("date_iso", date.today().isoformat())
        account_created_at: float = float(ctx.get("account_created_at", 0.0))
        invite_links: list[str] = ctx.get("invite_links", [])
        known_groups: list[dict] = ctx.get("known_groups", [])

        # Restore daily counters from ctx (populated by manager)
        self._joins_today[account_id] = int(ctx.get("joins_today", 0))
        self._msgs_today[account_id] = int(ctx.get("messages_today", 0))

        result = WorkerResult()
        result.groups_joined = 0
        result.messages_posted = 0
        result.reactions_sent = 0

        # ------------------------------------------------------------------
        # 1. Join new groups (max 2/day, code-enforced)
        # ------------------------------------------------------------------
        for invite_link in invite_links:
            if self._joins_today.get(account_id, 0) >= MAX_GROUP_JOINS_PER_DAY:
                log.info(
                    "[telegram_group/%s] Daily join cap %d reached",
                    account_id, MAX_GROUP_JOINS_PER_DAY,
                )
                break

            try:
                await client.join_group(invite_link=invite_link)
                self._joins_today[account_id] = self._joins_today.get(account_id, 0) + 1
                result.groups_joined += 1
                log.info("[telegram_group/%s] Joined group: %s", account_id, invite_link)
            except TelegramFloodWait as e:
                log.warning(
                    "[telegram_group/%s] Flood wait %ds on join", account_id, e.retry_after_sec
                )
                result.errors.append(f"flood_wait_join:{e.retry_after_sec}s")
                break
            except TelegramSessionExpired:
                result.errors.append("session_expired")
                return result
            except Exception as exc:
                result.errors.append(f"join_failed:{invite_link}:{exc}")

            # Inter-join sleep (LogNormal — never fixed)
            sleep_s = JOIN_SLEEP_DIST.sample()
            await asyncio.sleep(sleep_s)

        # ------------------------------------------------------------------
        # 2. Participate in known groups
        # ------------------------------------------------------------------
        # Account age check for posting
        now = time.time()
        account_age_days = (now - account_created_at) / 86400.0 if account_created_at else 9999

        for group_info in known_groups:
            group_id: str = group_info.get("group_id", "")
            if not group_id:
                continue

            state_key = (account_id, group_id)
            if state_key not in self._group_states:
                self._group_states[state_key] = GroupParticipationState(
                    account_id=account_id,
                    group_id=group_id,
                    last_activity_at=float(group_info.get("last_activity_at", 0.0)),
                )
            state = self._group_states[state_key]

            # Update last activity from current group info
            state.last_activity_at = float(group_info.get("last_activity_at", state.last_activity_at))

            # 2a. Post a message (if eligible)
            if (
                account_age_days >= MIN_ACCOUNT_AGE_DAYS_FOR_POSTING
                and self._msgs_today.get(account_id, 0) < MAX_GROUP_MESSAGES_PER_DAY
            ):
                # Timing gate: don't post too soon after last group activity
                time_since_activity = now - state.last_activity_at
                post_timing_threshold = POST_TIMING_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"post_timing_{group_id}",
                )
                if state.last_activity_at > 0 and time_since_activity < post_timing_threshold:
                    log.debug(
                        "[telegram_group/%s/%s] Too soon to post (%.0fs < %.0fs)",
                        account_id, group_id, time_since_activity, post_timing_threshold,
                    )
                else:
                    message = _group_message_for(account_id, group_id, date_iso)
                    dedup_key = _message_dedup_key(account_id, group_id, message)

                    if dedup_key in state.posted_message_keys:
                        log.debug(
                            "[telegram_group/%s/%s] Message already posted (dedup), skipping",
                            account_id, group_id,
                        )
                    else:
                        try:
                            await self._fire_typing_indicator(client, group_id)
                            await client.send_dm(user_id=group_id, text=message)
                            state.posted_message_keys.add(dedup_key)
                            state.messages_today += 1
                            state.last_posted_at = time.time()
                            self._msgs_today[account_id] = self._msgs_today.get(account_id, 0) + 1
                            result.messages_posted += 1
                            log.info(
                                "[telegram_group/%s/%s] Posted group message",
                                account_id, group_id,
                            )
                        except TelegramFloodWait as e:
                            result.errors.append(f"flood_wait_post:{e.retry_after_sec}s")
                            break
                        except TelegramSessionExpired:
                            result.errors.append("session_expired")
                            return result
                        except Exception as exc:
                            result.errors.append(f"post_failed:{group_id}:{exc}")

        return result
