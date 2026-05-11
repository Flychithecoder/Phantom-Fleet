"""
DiscordServerAgent — joins Discord servers and participates with human behavior.

Responsibilities:
    - Join servers via invite codes (max 1 new server/day per account)
    - Lurk after joining: LogNormal(mean=ln(86400), sigma=0.3) seconds before posting
    - React to 3-8 messages per server per day
    - Post messages only if account is 7+ days old IN THIS SERVER
    - Max 10 messages/day across all servers (code-enforced)
    - Message pool >= 20 entries; seeded per (account_id, channel_id, date_iso)
    - Never repeat same message in same channel (dedup)
    - Post during simulated "active hours" for account's timezone
    - Inter-message sleep: LogNormal(mean=ln(2400), sigma=0.6) within same server

Detection hardening (CLAUDE.md fleet-level rules):
    - Lurk gate applied to all new server joins (not instant post)
    - Max 1 server/day code-enforced (not prompt-enforced)
    - Max 10 messages/day across all servers code-enforced
    - Reaction emoji selection seeded by hash(account_id + message_id)
      so different accounts react differently to the same message
    - Message selection seeded per (account, channel, date) — fleet diversity
    - Timing respects account's timezone_offset for diurnal activity curve
    - Inter-server sleep is LogNormal with sigma=0.6 (wide variance)
    - ValueError raised at init if template pool < 20 (catches pool shrinkage)

Fleet-scale considerations:
    - Reactions: 10 emoji options seeded per (account, message) so no two accounts
      react the same way to the same message — cross-account reaction clustering avoided
    - Message dedup key is hash(account_id + channel_id + message) — stable across
      restarts, prevents repeating content in same channel
    - Server join timing has 30-minute average with sigma=0.5 for fleet-wide spread

Agent audit table (CLAUDE.md):
    ┌───────────────────┬──────────────────────────────────────────────┐
    │ Agent             │ DiscordServerAgent                           │
    │ Purpose           │ Server join + human-like participation       │
    │ Tools             │ None — direct HTTP via DiscordClient         │
    │ Untrusted input   │ None (action is outbound only)               │
    │ User isolation    │ Keyed by (account_id, server_id)             │
    │ Cost cap          │ 0.00 USD (no LLM calls in server agent)      │
    │ Loop cap          │ 1 join/day, 10 msgs/day (code-enforced)      │
    │ Confirmation      │ None (non-destructive)                       │
    └───────────────────┴──────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ...core.discord_client import (
    DiscordClient,
    DiscordRateLimited,
    DiscordSessionExpired,
)
from ...core.distributions import LogNormal
from ._base_chat import WorkerResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (ALL code-enforced)
# ---------------------------------------------------------------------------

MAX_SERVER_JOINS_PER_DAY: int = 1
MAX_MESSAGES_PER_DAY: int = 10          # across ALL servers
MIN_SERVER_AGE_DAYS_FOR_POSTING: int = 7  # days since account joined THIS server
REACTIONS_PER_SERVER_MIN: int = 3
REACTIONS_PER_SERVER_MAX: int = 8

# ---------------------------------------------------------------------------
# Timing distributions (LogNormal — never fixed)
# ---------------------------------------------------------------------------

# Inter-server-join sleep: mean=ln(1800)≈7.5, sigma=0.5 → median≈30min
JOIN_SLEEP_DIST = LogNormal(low=600.0, high=7200.0, sigma=0.50)

# Lurk duration after join: mean=ln(86400), sigma=0.3 → median≈1 day
LURK_DIST = LogNormal(low=14400.0, high=259200.0, sigma=0.30)

# Inter-message sleep within same server: mean=ln(2400), sigma=0.6 → median≈40min
INTER_MSG_DIST = LogNormal(low=600.0, high=14400.0, sigma=0.60)

# ---------------------------------------------------------------------------
# Reaction emoji pool — standard emojis only, >= 10 options
# Seeded per (account_id, message_id) for fleet diversity
# ---------------------------------------------------------------------------

REACTION_POOL: list[str] = [
    "%F0%9F%91%8D",   # 👍
    "%F0%9F%94%A5",   # 🔥
    "%F0%9F%98%82",   # 😂
    "%E2%9D%A4%EF%B8%8F",  # ❤️
    "%F0%9F%98%8D",   # 😍
    "%F0%9F%A4%A3",   # 🤣
    "%F0%9F%91%80",   # 👀
    "%F0%9F%92%AF",   # 💯
    "%F0%9F%98%85",   # 😅
    "%F0%9F%A4%94",   # 🤔
]

if len(REACTION_POOL) < 10:
    raise ValueError(
        f"REACTION_POOL must have >= 10 entries, got {len(REACTION_POOL)}"
    )


def _reaction_for(account_id: str, message_id: str) -> str:
    """Select a reaction emoji seeded by (account_id, message_id).

    Different accounts reacting to the same message pick different emoji,
    preventing a cross-account reaction monoculture fingerprint.
    """
    key = f"{account_id}|{message_id}|reaction"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(REACTION_POOL)
    return REACTION_POOL[idx]


def _reaction_count_for(account_id: str, server_id: str, date_iso: str) -> int:
    """
    Determine how many reactions this account sends in this server today.
    Seeded draw in [REACTIONS_PER_SERVER_MIN, REACTIONS_PER_SERVER_MAX].
    """
    key = f"{account_id}|{server_id}|{date_iso}|reaction_count"
    digest = hashlib.sha256(key.encode()).digest()
    n = int.from_bytes(digest[:4], "big") % (REACTIONS_PER_SERVER_MAX - REACTIONS_PER_SERVER_MIN + 1)
    return REACTIONS_PER_SERVER_MIN + n


# ---------------------------------------------------------------------------
# Server message pool — MUST be >= 20 entries
# ---------------------------------------------------------------------------

SERVER_MESSAGE_POOL: list[str] = [
    "lmao yeah that's fair",
    "okay this is actually kinda interesting",
    "wait when did this happen",
    "ngl i've been wondering about this too",
    "honestly makes sense when you think about it",
    "this is the kind of thing nobody talks about",
    "been lurking but this made me say something",
    "solid point, hard to argue with",
    "wait i need to catch up on this whole thread",
    "this is why i'm in this server lol",
    "okay i'm genuinely curious about this now",
    "yeah that tracks actually",
    "not gonna lie i had the same thought",
    "this is getting interesting",
    "anyone else just catching up to this",
    "fr this is a good discussion",
    "been a while since something this good came up",
    "okay you're not wrong",
    "same, had no idea about this",
    "this whole thread is a goldmine",
    "glad someone finally brought this up",
    "this is the thread i needed today",
    "adding this to my list of things to look into",
    "yeah i've seen a couple people mention this lately",
    "idk why this doesn't get talked about more",
]

if len(SERVER_MESSAGE_POOL) < 20:
    raise ValueError(
        f"SERVER_MESSAGE_POOL must have >= 20 entries, got {len(SERVER_MESSAGE_POOL)}"
    )


def _server_message_for(account_id: str, channel_id: str, date_iso: str) -> str:
    """Select a message seeded by (account, channel, date) for fleet diversity."""
    key = f"{account_id}|{channel_id}|{date_iso}|server_msg"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(SERVER_MESSAGE_POOL)
    return SERVER_MESSAGE_POOL[idx]


def _message_dedup_key(account_id: str, channel_id: str, message: str) -> str:
    """Stable dedup key for (account, channel, message)."""
    key = f"{account_id}|{channel_id}|{message}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Server membership state
# ---------------------------------------------------------------------------


@dataclass
class ServerMembershipState:
    """Per-(account, server) state tracking."""
    account_id:        str
    server_id:         str
    joined_at:         float = 0.0       # unix timestamp when joined
    lurk_until:        float = 0.0       # unix timestamp until lurk expires
    messages_today:    int = 0
    last_posted_at:    float = 0.0
    posted_keys:       set = field(default_factory=set)  # dedup keys
    reactions_sent_today: int = 0


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class DiscordServerAgent:
    """
    Joins Discord servers and participates with human-like behavior.

    ctx keys (passed to run_once):
        account_id:         str
        date_iso:           str (YYYY-MM-DD)
        session:            DiscordSession (pre-built)
        timezone_offset:    int — hours offset from UTC (e.g. -5 for EST)
        invite_codes:       list[str] — server invites to consider joining
        known_servers:      list[dict] — already-joined servers
            each: {server_id: str, channel_id: str, recent_message_ids: list[str]}
        joins_today:        int — server joins already done today
        messages_today:     int — server messages already sent today
    """

    def __init__(self) -> None:
        # Keyed by (account_id, server_id)
        self._server_states: dict[tuple[str, str], ServerMembershipState] = {}
        self._joins_today: dict[str, int] = {}
        self._msgs_today: dict[str, int] = {}

    def _is_active_hour(self, timezone_offset: int) -> bool:
        """
        Check if current UTC time falls in the account's simulated active hours
        (9:00–23:00 local time). This spreads posting across a diurnal curve
        rather than all accounts posting at the same UTC hour.
        """
        import datetime
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        local_hour = (utc_now.hour + timezone_offset) % 24
        return 9 <= local_hour <= 23

    async def run_once(
        self,
        client: DiscordClient,
        ctx: dict,
    ) -> WorkerResult:
        """Execute one server session: join queued servers + participate in existing ones."""
        account_id: str = ctx["account_id"]
        date_iso: str = ctx.get("date_iso", date.today().isoformat())
        timezone_offset: int = int(ctx.get("timezone_offset", 0))
        invite_codes: list[str] = ctx.get("invite_codes", [])
        known_servers: list[dict] = ctx.get("known_servers", [])

        # Restore daily counters from ctx
        self._joins_today[account_id] = int(ctx.get("joins_today", 0))
        self._msgs_today[account_id] = int(ctx.get("messages_today", 0))

        result = WorkerResult()
        result.servers_joined = 0
        result.messages_sent = 0
        result.reactions_sent = 0
        result.lurk_gates_applied = 0

        now = time.time()

        # ------------------------------------------------------------------
        # 1. Join new servers (max 1/day, code-enforced)
        # ------------------------------------------------------------------
        for invite_code in invite_codes:
            if self._joins_today.get(account_id, 0) >= MAX_SERVER_JOINS_PER_DAY:
                log.info(
                    "[discord_server/%s] Daily join cap %d reached",
                    account_id, MAX_SERVER_JOINS_PER_DAY,
                )
                break

            try:
                join_result = await client.join_server(invite_code=invite_code)
                server_id = str(join_result.get("guild", {}).get("id", invite_code))
                self._joins_today[account_id] = self._joins_today.get(account_id, 0) + 1
                result.servers_joined += 1

                # Initialize lurk state for new server
                state_key = (account_id, server_id)
                lurk_duration = LURK_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"lurk_{server_id}",
                )
                self._server_states[state_key] = ServerMembershipState(
                    account_id=account_id,
                    server_id=server_id,
                    joined_at=now,
                    lurk_until=now + lurk_duration,
                )
                log.info(
                    "[discord_server/%s] Joined server %s, lurk for %.0fh",
                    account_id, server_id, lurk_duration / 3600,
                )
            except DiscordRateLimited as e:
                result.errors.append(f"rate_limited_join:{e.retry_after_sec}s")
                break
            except DiscordSessionExpired:
                result.errors.append("session_expired")
                return result
            except Exception as exc:
                result.errors.append(f"join_failed:{invite_code}:{exc}")

            # Inter-join sleep (LogNormal — never fixed)
            sleep_s = JOIN_SLEEP_DIST.sample()
            await asyncio.sleep(sleep_s)

        # ------------------------------------------------------------------
        # 2. Participate in known servers
        # ------------------------------------------------------------------
        # Check active hours gate
        if not self._is_active_hour(timezone_offset):
            log.debug(
                "[discord_server/%s] Outside active hours (tz offset %d), skipping participation",
                account_id, timezone_offset,
            )
            return result

        for server_info in known_servers:
            server_id: str = server_info.get("server_id", "")
            channel_id: str = server_info.get("channel_id", "")
            recent_message_ids: list[str] = server_info.get("recent_message_ids", [])

            if not server_id or not channel_id:
                continue

            state_key = (account_id, server_id)
            if state_key not in self._server_states:
                # Server was joined before this agent run; no lurk state
                self._server_states[state_key] = ServerMembershipState(
                    account_id=account_id,
                    server_id=server_id,
                    joined_at=float(server_info.get("joined_at", 0.0)),
                    lurk_until=0.0,
                )
            state = self._server_states[state_key]

            # ------------------------------------------------------------------
            # Lurk gate — don't post in newly joined servers
            # ------------------------------------------------------------------
            if state.lurk_until > now:
                log.debug(
                    "[discord_server/%s/%s] Lurk gate active (%.0fh remaining)",
                    account_id, server_id, (state.lurk_until - now) / 3600,
                )
                result.lurk_gates_applied += 1
                # Still allow reactions while lurking (low-key engagement)
            else:
                # ------------------------------------------------------------------
                # Server age gate: account must be 7+ days old in THIS server
                # ------------------------------------------------------------------
                server_join_age_days = (now - state.joined_at) / 86400.0 if state.joined_at else 9999

                if (
                    server_join_age_days >= MIN_SERVER_AGE_DAYS_FOR_POSTING
                    and self._msgs_today.get(account_id, 0) < MAX_MESSAGES_PER_DAY
                ):
                    # Timing: inter-message sleep since last post in this server
                    time_since_last = now - state.last_posted_at
                    inter_msg_threshold = INTER_MSG_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_msg_{server_id}",
                    )
                    if state.last_posted_at > 0 and time_since_last < inter_msg_threshold:
                        log.debug(
                            "[discord_server/%s/%s] Too soon to post (%.0fs < %.0fs)",
                            account_id, server_id, time_since_last, inter_msg_threshold,
                        )
                    else:
                        message = _server_message_for(account_id, channel_id, date_iso)
                        dedup_key = _message_dedup_key(account_id, channel_id, message)

                        if dedup_key in state.posted_keys:
                            log.debug(
                                "[discord_server/%s/%s] Message already posted (dedup)",
                                account_id, server_id,
                            )
                        else:
                            try:
                                await client.send_message(
                                    channel_id=channel_id, content=message
                                )
                                state.posted_keys.add(dedup_key)
                                state.messages_today += 1
                                state.last_posted_at = time.time()
                                self._msgs_today[account_id] = self._msgs_today.get(account_id, 0) + 1
                                result.messages_sent += 1
                                log.info(
                                    "[discord_server/%s/%s] Posted server message",
                                    account_id, server_id,
                                )
                            except DiscordRateLimited as e:
                                result.errors.append(f"rate_limited_msg:{e.retry_after_sec}s")
                                break
                            except DiscordSessionExpired:
                                result.errors.append("session_expired")
                                return result
                            except Exception as exc:
                                result.errors.append(f"post_failed:{server_id}:{exc}")

            # ------------------------------------------------------------------
            # React to recent messages (3-8 reactions, seeded count)
            # ------------------------------------------------------------------
            reaction_target_count = _reaction_count_for(account_id, server_id, date_iso)
            # Cap at available message IDs
            reaction_targets = recent_message_ids[:reaction_target_count]

            for message_id in reaction_targets:
                emoji = _reaction_for(account_id, message_id)
                try:
                    await client.react_to_message(
                        channel_id=channel_id,
                        message_id=message_id,
                        emoji=emoji,
                    )
                    result.reactions_sent += 1
                except DiscordRateLimited as e:
                    result.errors.append(f"rate_limited_react:{e.retry_after_sec}s")
                    break
                except DiscordSessionExpired:
                    result.errors.append("session_expired")
                    return result
                except Exception as exc:
                    log.debug(
                        "[discord_server/%s/%s] React failed for msg %s: %s",
                        account_id, server_id, message_id, exc,
                    )

        return result
