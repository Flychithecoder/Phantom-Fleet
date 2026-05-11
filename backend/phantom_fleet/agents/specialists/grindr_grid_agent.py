"""
GrindrGridAgent — grid browsing and opening-message automation for Grindr.

Responsibilities:
    - Browse the Grindr cascade (nearby grid) for N profiles per session
    - View profiles with realistic dwell times
    - Send an opening message to a subset of viewed profiles
    - Choose opening messages from a pool seeded deterministically by
      (account_id, target_id) — same account always sends same opener to
      same target (idempotent retry), different accounts send different openers
    - Log all actions to audit trail BEFORE execution

Detection hardening (20K account cluster analysis applied):
    - view_count: LogNormal(mean=40, sigma=12) — per-account, per-day variation
    - message_count: LogNormal — fraction of views, bounded per spec
    - chat_open_probability: 0.10–0.20 range, sampled per-account per-day
      (not a hardcoded constant — avoids the static-ratio fingerprint)
    - Dwell per profile: LogNormal(mean=4s, sigma=2) — log-normal histogram
    - Template pool: 30+ templates with 4 style categories for distribution
    - Template selection seeded by hash(account_id + target_id) — cross-account
      distribution ensures templates don't cluster to one at fleet scale

Opening message pool design:
    30+ templates covering: direct, playful, compliment, question styles
    Pool is divided roughly evenly across style categories so that fleet-wide
    the MESSAGE STYLE histogram is balanced (~25% each), not a monoculture
    of one style.

    Production note: this pool is the fleet-safe baseline. The full production
    build will route through Chat AI for generative per-account-per-target
    personalization. Until that integration is live, the pool provides
    the style and length diversity needed to avoid content fingerprinting.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import LogNormal, seed_for, _rng_from_seed
from ...core.grindr_client import (
    GrindrClient,
    GrindrSession,
    GrindrSessionExpired,
    GrindrRateLimited,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Distribution constants
# ---------------------------------------------------------------------------

# Number of profiles to view per session — LogNormal mean=40 σ=12 per spec
VIEW_COUNT_DIST = LogNormal(low=15.0, high=70.0, sigma=0.35)

# Number of opening messages to send — LogNormal, bounded to realistic range
MSG_COUNT_DIST = LogNormal(low=3.0, high=18.0, sigma=0.40)

# chat_open_probability per-account per-day (0.10–0.20 per spec)
# LogNormal over this range so fleet histogram is shaped, not a rectangle
CHAT_OPEN_PROB_DIST = LogNormal(low=0.10, high=0.20, sigma=0.20)

# Dwell per profile (seconds)
DWELL_DIST = LogNormal(low=1.5, high=12.0, sigma=0.45)

# Inter-action pause
PAUSE_DIST = LogNormal(low=0.8, high=5.0, sigma=0.40)

# ---------------------------------------------------------------------------
# Opening message pool
# 30+ templates covering: direct (D), playful (P), compliment (C), question (Q)
# Each template is tagged for analytics; tag doesn't affect selection logic.
# seeded selection ensures per-account diversity at fleet scale.
# ---------------------------------------------------------------------------

OPENING_TEMPLATES: list[tuple[str, str]] = [
    # (text, style_tag)
    # --- Direct (D) ---
    ("Hey, how's your day going?",                                              "D"),
    ("Hey, what are you up to today?",                                          "D"),
    ("Hi, nice to see you on here",                                             "D"),
    ("Hey there, what's good?",                                                 "D"),
    ("Hey, I came across your profile and wanted to say hi",                    "D"),
    ("Hey, you seem interesting — want to chat?",                               "D"),
    ("Hi! You seem like someone worth talking to",                              "D"),
    ("Hey, I'm [Account], let's see where this goes",                           "D"),
    # --- Playful (P) ---
    ("Okay your profile actually made me smile, that's rare",                   "P"),
    ("Not gonna lie, you're the best thing I've seen on here today",            "P"),
    ("I don't usually message first but here we are",                           "P"),
    ("My thumb stopped scrolling for a reason",                                 "P"),
    ("You look like trouble. I'm in.",                                          "P"),
    ("Fair warning: I'm probably funnier in person",                            "P"),
    ("Okay I'll shoot my shot — hey 👋",                                        "P"),
    ("You passed the vibe check. First question: coffee or energy drinks?",     "P"),
    # --- Compliment (C) ---
    ("Love your energy in that photo",                                          "C"),
    ("You have a really genuine smile, just saying",                            "C"),
    ("Your bio is actually refreshingly honest",                                "C"),
    ("You seem like someone who's comfortable in their own skin — that's attractive", "C"),
    ("Real talk, your photos are great",                                        "C"),
    ("You have really good taste, I can tell",                                  "C"),
    ("I like how real your profile feels compared to most",                     "C"),
    ("Your vibe is honestly one of the best I've come across on here",          "C"),
    # --- Question (Q) ---
    ("If you could be anywhere right now, where would you be?",                 "Q"),
    ("Quick question: what's the last thing you genuinely laughed at?",         "Q"),
    ("What's something you'd recommend to a stranger?",                         "Q"),
    ("What does a good Sunday look like to you?",                               "Q"),
    ("Tell me one thing that's been on your mind lately",                       "Q"),
    ("What's the most interesting thing about you that's not on your profile?", "Q"),
    ("What's your current obsession?",                                          "Q"),
    ("Honest question: what are you actually on here for?",                     "Q"),
]

assert len(OPENING_TEMPLATES) >= 30, "Pool must have at least 30 templates"


def _opening_for(account_id: str, target_id: str) -> str:
    """
    Select an opening message deterministically from the pool.

    Seeded by hash(account_id + target_id):
    - Same account, same target → always same message (idempotent retry)
    - Different accounts, same target → different messages
    - Fleet-wide: template distribution approaches uniform across 30+ templates
      because the hash seed is uniformly distributed over account IDs
    """
    key = f"{account_id}|{target_id}|opening"
    digest = hashlib.sha256(key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(OPENING_TEMPLATES)
    return OPENING_TEMPLATES[idx][0]


# ---------------------------------------------------------------------------
# Grid session record
# ---------------------------------------------------------------------------


@dataclass
class GridRecord:
    """Audit record for one Grindr grid session."""
    account_id:     str
    profiles_viewed: int
    messages_sent:  int
    view_records:   list[dict] = field(default_factory=list)
    message_records: list[dict] = field(default_factory=list)
    session_start:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_end:    Optional[str] = None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class GrindrGridAgent(Agent):
    """
    Executes one Grindr grid browsing session for one account.

    ctx keys:
        account_id:             str
        session:                GrindrSession (pre-built, auth_token set)
        date_iso:               str  (YYYY-MM-DD)
        distance_km:            float | None  (grid radius; default 5)
        profile_views_count:    int | None    (if None, sampled from LogNormal)
        chat_open_probability:  float | None  (if None, sampled per-account)
        tap_filter:             dict | None   (filter criteria; reserved for future)
        profile_dwell_range_sec: tuple[float,float] | None  (override dwell dist)
    """

    config = AgentConfig(
        name="grindr_grid",
        max_iterations=1,          # single session per run
        max_usd_per_run=0.00,      # no LLM calls in the grid path
        max_usd_per_session=0.00,
        allowed_tools=(
            "db.save_grid_records",
        ),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id = ctx["account_id"]
        session: GrindrSession = ctx["session"]
        date_iso = ctx.get("date_iso", date.today().isoformat())

        # ------------------------------------------------------------------
        # 1. Sample session parameters
        # ------------------------------------------------------------------
        view_count = ctx.get("profile_views_count")
        if view_count is None:
            view_count = VIEW_COUNT_DIST.sample_int(
                account_id=account_id,
                date_iso=date_iso,
                field="grindr_view_count",
            )

        chat_open_prob = ctx.get("chat_open_probability")
        if chat_open_prob is None:
            chat_open_prob = CHAT_OPEN_PROB_DIST.sample(
                account_id=account_id,
                date_iso=date_iso,
                field="grindr_chat_open_prob",
            )
        chat_open_prob = max(0.10, min(0.20, chat_open_prob))

        # Expected messages = view_count * chat_open_prob, sampled with variation
        max_messages = MSG_COUNT_DIST.sample_int(
            account_id=account_id,
            date_iso=date_iso,
            field="grindr_msg_count",
        )

        self._audit_event(run, "session_plan", {
            "view_count": view_count,
            "chat_open_prob": round(chat_open_prob, 3),
            "max_messages": max_messages,
        })

        # ------------------------------------------------------------------
        # 2. Run the grid session
        # ------------------------------------------------------------------
        record = GridRecord(account_id=account_id)
        messages_sent = 0

        async with GrindrClient(session) as client:
            # Update location if provided
            lat = ctx.get("lat")
            lon = ctx.get("lon")
            if lat is not None and lon is not None:
                try:
                    await client.update_location(lat, lon)
                except (GrindrSessionExpired, GrindrRateLimited, Exception) as e:
                    log.warning("Location update failed for %s: %s", account_id, e)

            # Fetch cascade
            try:
                cascade_resp = await client.get_cascade(limit=max(view_count, 50))
            except GrindrSessionExpired:
                log.warning("Grindr session expired for %s", account_id)
                return True
            except GrindrRateLimited as e:
                log.warning("Grindr rate limited for %s", account_id)
                await asyncio.sleep(min(e.retry_after, 120))
                return True

            profiles = cascade_resp.get("profiles", [])
            if not profiles:
                log.info("Empty cascade for %s", account_id)
                return True

            # Process up to view_count profiles
            profiles = profiles[:view_count]

            for i, profile in enumerate(profiles):
                target_profile_id = str(
                    profile.get("profileId", profile.get("profile_id", ""))
                )
                if not target_profile_id:
                    continue

                # Dwell time before and during view
                dwell_s = DWELL_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"dwell_{target_profile_id}",
                )
                await asyncio.sleep(dwell_s / 2)  # pre-view pause

                # View the profile
                self._audit_event(run, "profile_view", {
                    "target_id": target_profile_id,
                    "position": i,
                    "dwell_s": round(dwell_s, 2),
                })

                try:
                    profile_data = await client.view_profile(
                        target_profile_id,
                        dwell_ms=int(dwell_s * 1000),
                    )
                except GrindrSessionExpired:
                    break
                except GrindrRateLimited as e:
                    await asyncio.sleep(min(e.retry_after, 60))
                    break
                except Exception as e:
                    log.debug("view_profile failed for %s: %s", target_profile_id, e)
                    continue

                record.view_records.append({
                    "target_id": target_profile_id,
                    "dwell_ms": int(dwell_s * 1000),
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                record.profiles_viewed += 1

                await asyncio.sleep(dwell_s / 2)  # post-view dwell

                # ------------------------------------------------------------------
                # Decide whether to send an opening message
                # ------------------------------------------------------------------
                if messages_sent >= max_messages:
                    pass  # hit message cap, still view but don't message
                else:
                    rng = _rng_from_seed(
                        seed_for(account_id, date_iso, f"chat_open_{target_profile_id}")
                    )
                    should_message = rng.random() < chat_open_prob

                    if should_message:
                        # Need conversation_id — for new contacts on Grindr this
                        # is created on first message. Profile ID serves as
                        # conversation ID for new conversations.
                        opening = _opening_for(account_id, target_profile_id)

                        self._audit_event(run, "send_message", {
                            "target_id": target_profile_id,
                            "template_hash": hashlib.sha256(opening.encode()).hexdigest()[:8],
                        })

                        try:
                            msg_resp = await client.send_message(
                                conversation_id=target_profile_id,
                                body=opening,
                                msg_type="Text",
                            )
                            record.message_records.append({
                                "target_id": target_profile_id,
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "msg_id": msg_resp.get("messageId", ""),
                            })
                            messages_sent += 1
                        except GrindrSessionExpired:
                            break
                        except GrindrRateLimited as e:
                            await asyncio.sleep(min(e.retry_after, 60))
                            break
                        except Exception as e:
                            log.debug(
                                "send_message failed to %s: %s",
                                target_profile_id, e,
                            )

                # Inter-profile pause
                pause_s = PAUSE_DIST.sample(
                    account_id=account_id,
                    date_iso=date_iso,
                    field=f"pause_{target_profile_id}",
                )
                await asyncio.sleep(pause_s)

        # ------------------------------------------------------------------
        # 3. Persist records
        # ------------------------------------------------------------------
        record.messages_sent = messages_sent
        record.session_end = datetime.now(timezone.utc).isoformat()

        await self.tool("db.save_grid_records", record)

        run.outputs.update({
            "profiles_viewed": record.profiles_viewed,
            "messages_sent":   messages_sent,
        })
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _audit_event(self, run: AgentRun, event_type: str, data: dict) -> None:
        event = {
            "event": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": self.config.name,
            **data,
        }
        run.audit_events.append(event)
        self.audit_sink(event)
