"""
IGBroadcastAgent — Manages Instagram Broadcast Channels for mass reach.

Instagram Broadcast Channels are one-way channels: the creator sends messages
and all opted-in subscribers receive them in their DM inbox. Subscribers opt in
voluntarily — so this is zero-spam mass messaging to a warm, engaged audience.

Key capabilities:
    - Auto-invite new followers to join the channel
    - Send personal updates / behind-the-scenes messages to all subscribers
    - Send AI-generated weekly recap on Sunday evenings

Design decisions (CLAUDE.md fleet-scale audit):

    invite_new_followers:
        - Max 50 invites per day is code-enforced (not prompt-based)
        - Per-invite stagger is LogNormal(mean=ln(30), sigma=0.4) — median ~30s
          tail to ~120s — no two accounts share identical invite timing patterns

    send_content_drop:
        - Max 2 broadcasts per day is code-enforced
        - Length cap 500 chars is validated by code
        - AI generation via OpenRouter when message not provided — uses
          claude-haiku-4-5-20251001 (cheapest capable model)

    send_weekly_recap:
        - Runs Sunday evenings (scheduling by caller)
        - Generates 2-sentence recap via OpenRouter from caller-provided
          content item list
        - Counts against the 2-broadcast/day cap

Agent audit table (CLAUDE.md):
    ┌─────────────────┬──────────────────────────────────────────────────┐
    │ Agent           │ IGBroadcastAgent                                 │
    │ Purpose         │ Broadcast Channel invite + mass announcement     │
    │ Tools           │ None — direct HTTP via InstagramClient           │
    │ Untrusted input │ message param (caller-provided, not user DMs)    │
    │ User isolation  │ Keyed by account_id — no shared state           │
    │ Cost cap        │ 2 broadcasts/day × ~$0.001 ≈ $0.002/acct/day   │
    │ Loop cap        │ 50 invites/day (code), 2 broadcasts/day (code)  │
    │ Confirmation    │ None required                                    │
    └─────────────────┴──────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import IGSession, InstagramClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Daily hard caps — code-enforced
# ---------------------------------------------------------------------------

_DAILY_INVITE_CAP: int     = 50    # max invites per account per day
_DAILY_BROADCAST_CAP: int  = 2     # max broadcast messages per account per day

# ---------------------------------------------------------------------------
# Message limits
# ---------------------------------------------------------------------------

_BROADCAST_MAX_CHARS: int = 500

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# Stagger between individual invites: LogNormal median ~30s, tail to ~2 min
_INVITE_STAGGER_DIST = LogNormal(low=5.0, high=120.0, sigma=0.40)

# ---------------------------------------------------------------------------
# OpenRouter constants
# ---------------------------------------------------------------------------

_OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
_RECAP_MODEL        = "anthropic/claude-haiku-4-5-20251001"
_MAX_RECAP_TOKENS   = 120   # 2 sentences is plenty


# ---------------------------------------------------------------------------
# Task types
# ---------------------------------------------------------------------------

@dataclass
class IGBroadcastInviteTask:
    """Input for invite_new_followers()."""
    account_id:       str
    ig_session:       IGSession
    channel_id:       str
    new_follower_ids: list[str]         # IG numeric user ID strings
    invites_today:    int = 0           # already sent today
    proxy_url:        str = "socks5://127.0.0.1:8089"


@dataclass
class IGBroadcastDropTask:
    """Input for send_content_drop()."""
    account_id:       str
    ig_session:       IGSession
    channel_id:       str
    message:          Optional[str] = None      # if None, AI generates
    content_type:     str = "personal update"   # context hint for AI generation
    broadcasts_today: int = 0
    proxy_url:        str = "socks5://127.0.0.1:8089"


@dataclass
class IGWeeklyRecapTask:
    """Input for send_weekly_recap()."""
    account_id:       str
    ig_session:       IGSession
    channel_id:       str
    content_items:    list[str]         # description strings for this week's posts
    broadcasts_today: int = 0
    proxy_url:        str = "socks5://127.0.0.1:8089"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IGBroadcastAgent:
    """
    Manages Instagram Broadcast Channels for mass reach.

    - Auto-invites new followers to join the channel
    - Sends personal updates and genuine moments to subscribers
    - Sends AI-generated weekly recaps on Sunday evenings
    - Never mentions content, links, PPV, or sales in broadcasts
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # invite_new_followers
    # ------------------------------------------------------------------

    async def invite_new_followers(
        self,
        task: IGBroadcastInviteTask,
    ) -> WorkerResult:
        """
        Invite a batch of new followers to the broadcast channel.

        Caps at 50 invites/day (code-enforced). Staggers each invite with
        a LogNormal delay so the invite rate does not form a detectable cluster.

        task.new_follower_ids is the full list of new followers — this method
        slices to respect remaining cap and staggers sends.
        """
        remaining_cap = _DAILY_INVITE_CAP - task.invites_today
        if remaining_cap <= 0:
            msg = (
                f"daily_invite_cap_reached:"
                f"{task.invites_today}/{_DAILY_INVITE_CAP} "
                f"for account {task.account_id}"
            )
            log.warning("[%s] %s", task.account_id, msg)
            return _failure_result_invite(task, [msg])

        # Enforce cap by slicing — code fence, not prompt
        batch = task.new_follower_ids[:remaining_cap]
        if len(batch) < len(task.new_follower_ids):
            log.info(
                "[%s] invite batch truncated %d → %d (daily cap)",
                task.account_id, len(task.new_follower_ids), len(batch),
            )

        invited: list[str]  = []
        failed:  list[str]  = []
        errors:  list[str]  = []

        async with InstagramClient(task.ig_session, proxy_url=task.proxy_url) as client:
            for i, user_id in enumerate(batch):
                try:
                    ok = await client.invite_to_broadcast(task.channel_id, [user_id])
                    if ok:
                        invited.append(user_id)
                        log.debug(
                            "[%s] invited user %s to channel %s",
                            task.account_id, user_id, task.channel_id,
                        )
                    else:
                        failed.append(user_id)
                        errors.append(f"invite_rejected:user_id={user_id}")
                except Exception as exc:
                    err = f"invite_error:user_id={user_id}:{type(exc).__name__}:{exc}"
                    log.error("[%s] %s", task.account_id, err)
                    failed.append(user_id)
                    errors.append(err)

                # Stagger between invites (except after the last one)
                if i < len(batch) - 1:
                    gap = _INVITE_STAGGER_DIST.sample()
                    await asyncio.sleep(gap)

        success = len(invited) > 0
        return WorkerResult(
            task_id    = f"ig_broadcast_invite_{task.account_id}",
            platform   = "instagram",
            account_id = task.account_id,
            success    = success,
            error      = "; ".join(errors) if errors else None,
            data       = {
                "invited_count":  len(invited),
                "failed_count":   len(failed),
                "invited_ids":    invited,
                "failed_ids":     failed,
                "errors":         errors,
            },
        )

    # ------------------------------------------------------------------
    # send_content_drop
    # ------------------------------------------------------------------

    async def send_content_drop(
        self,
        task: IGBroadcastDropTask,
    ) -> WorkerResult:
        """
        Send an announcement to all broadcast subscribers.

        If task.message is not provided, an AI-generated message is created
        using OpenRouter. The broadcast cap of 2/day is code-enforced.

        Text must be <= 500 chars (code-enforced, not prompt-based).
        """
        # Daily cap check
        if task.broadcasts_today >= _DAILY_BROADCAST_CAP:
            msg = (
                f"daily_broadcast_cap_reached:"
                f"{task.broadcasts_today}/{_DAILY_BROADCAST_CAP} "
                f"for account {task.account_id}"
            )
            log.warning("[%s] %s", task.account_id, msg)
            return _failure_result_drop(task, [msg])

        # Resolve message text
        if task.message:
            message = task.message
        else:
            try:
                message = await _generate_drop_message(task.content_type)
            except Exception as exc:
                err = f"ai_generate_failed:{type(exc).__name__}:{exc}"
                log.error("[%s] %s", task.account_id, err)
                return _failure_result_drop(task, [err])

        # Length enforcement
        if len(message) > _BROADCAST_MAX_CHARS:
            err = (
                f"message_too_long:{len(message)}_chars "
                f"(max={_BROADCAST_MAX_CHARS})"
            )
            log.error("[%s] %s", task.account_id, err)
            return _failure_result_drop(task, [err])

        # Send broadcast
        try:
            async with InstagramClient(task.ig_session, proxy_url=task.proxy_url) as client:
                ok = await client.send_broadcast_message(task.channel_id, message)
        except Exception as exc:
            err = f"send_broadcast_failed:{type(exc).__name__}:{exc}"
            log.error("[%s] %s", task.account_id, err)
            return _failure_result_drop(task, [err])

        if not ok:
            err = "send_broadcast_returned_not_ok"
            log.error("[%s] %s", task.account_id, err)
            return _failure_result_drop(task, [err])

        log.info(
            "[%s] broadcast sent to channel %s: %r",
            task.account_id, task.channel_id, message[:60],
        )
        return WorkerResult(
            task_id    = f"ig_broadcast_drop_{task.account_id}",
            platform   = "instagram",
            account_id = task.account_id,
            success    = True,
            error      = None,
            data       = {
                "message":      message,
                "channel_id":   task.channel_id,
                "char_count":   len(message),
            },
        )

    # ------------------------------------------------------------------
    # send_weekly_recap
    # ------------------------------------------------------------------

    async def send_weekly_recap(
        self,
        task: IGWeeklyRecapTask,
    ) -> WorkerResult:
        """
        Auto-generate and send a weekly content recap on Sunday evenings.

        Uses OpenRouter to produce a punchy 2-sentence recap from the list of
        content items provided by the caller. The broadcast counts against the
        2/day cap (code-enforced).

        Scheduled by the caller for Sunday ~6–9 PM account local time with
        per-account jitter derived from hash(account_id).
        """
        # Daily cap check (shared with send_content_drop)
        if task.broadcasts_today >= _DAILY_BROADCAST_CAP:
            msg = (
                f"daily_broadcast_cap_reached:"
                f"{task.broadcasts_today}/{_DAILY_BROADCAST_CAP} "
                f"for account {task.account_id}"
            )
            log.warning("[%s] %s", task.account_id, msg)
            return _failure_result_recap(task, [msg])

        if not task.content_items:
            err = "content_items is empty — cannot generate recap"
            log.error("[%s] %s", task.account_id, err)
            return _failure_result_recap(task, [err])

        # Generate recap via OpenRouter
        try:
            recap = await _generate_weekly_recap(task.content_items)
        except Exception as exc:
            err = f"ai_recap_generate_failed:{type(exc).__name__}:{exc}"
            log.error("[%s] %s", task.account_id, err)
            return _failure_result_recap(task, [err])

        # Length guard
        if len(recap) > _BROADCAST_MAX_CHARS:
            recap = recap[: _BROADCAST_MAX_CHARS - 3] + "..."

        # Send
        try:
            async with InstagramClient(task.ig_session, proxy_url=task.proxy_url) as client:
                ok = await client.send_broadcast_message(task.channel_id, recap)
        except Exception as exc:
            err = f"send_recap_failed:{type(exc).__name__}:{exc}"
            log.error("[%s] %s", task.account_id, err)
            return _failure_result_recap(task, [err])

        if not ok:
            err = "send_recap_returned_not_ok"
            log.error("[%s] %s", task.account_id, err)
            return _failure_result_recap(task, [err])

        log.info(
            "[%s] weekly recap sent to channel %s",
            task.account_id, task.channel_id,
        )
        return WorkerResult(
            task_id    = f"ig_broadcast_recap_{task.account_id}",
            platform   = "instagram",
            account_id = task.account_id,
            success    = True,
            error      = None,
            data       = {
                "recap":        recap,
                "channel_id":   task.channel_id,
                "item_count":   len(task.content_items),
            },
        )


# ---------------------------------------------------------------------------
# OpenRouter helpers
# ---------------------------------------------------------------------------

async def _generate_drop_message(content_type: str) -> str:
    """
    Generate a short broadcast message via OpenRouter.

    Broadcast messages should feel like personal updates from the creator —
    genuine moments, exclusive behind-the-scenes feelings, or real check-ins.
    Never mention OF, content drops, PPV, or links. No CTAs.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not set")

    prompt = (
        f"Write a single short Instagram broadcast channel message (max 100 characters) "
        f"from a creator to their closest followers. "
        f"It should feel like a genuine personal update — a mood, a moment, a feeling. "
        f"Do NOT mention content, links, sales, PPV, or calls to action. "
        f"Sound like a real person sharing a genuine thought. Use 1 emoji max. "
        f"No hashtags. Reply with ONLY the message text."
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _RECAP_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": _MAX_RECAP_TOKENS,
                "temperature": 0.9,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


async def _generate_weekly_recap(content_items: list[str]) -> str:
    """
    Generate a 2-sentence weekly content recap via OpenRouter.

    content_items: list of brief descriptions of posts from the week.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not set")

    items_text = "\n".join(f"- {item}" for item in content_items[:20])
    prompt = (
        f"You are writing a weekly recap broadcast message for an Instagram creator's "
        f"broadcast channel. The creator posted the following content this week:\n"
        f"{items_text}\n\n"
        f"Write exactly 2 sentences summarising the week's content, making subscribers "
        f"feel like they missed out if they didn't see it. Use 1-2 emojis. "
        f"Keep it under 200 characters total. Reply with ONLY the message text."
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _RECAP_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": _MAX_RECAP_TOKENS,
                "temperature": 0.85,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Failure result helpers
# ---------------------------------------------------------------------------

def _failure_result_invite(task: IGBroadcastInviteTask, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id    = f"ig_broadcast_invite_{task.account_id}",
        platform   = "instagram",
        account_id = task.account_id,
        success    = False,
        error      = "; ".join(errors),
        data       = {
            "invited_count": 0,
            "failed_count":  0,
            "errors":        errors,
        },
    )


def _failure_result_drop(task: IGBroadcastDropTask, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id    = f"ig_broadcast_drop_{task.account_id}",
        platform   = "instagram",
        account_id = task.account_id,
        success    = False,
        error      = "; ".join(errors),
        data       = {"errors": errors},
    )


def _failure_result_recap(task: IGWeeklyRecapTask, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id    = f"ig_broadcast_recap_{task.account_id}",
        platform   = "instagram",
        account_id = task.account_id,
        success    = False,
        error      = "; ".join(errors),
        data       = {"errors": errors},
    )
