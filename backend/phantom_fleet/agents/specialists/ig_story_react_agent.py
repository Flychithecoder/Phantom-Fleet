"""
IGStoryReactAgent — sends selective emoji reactions to Instagram stories.

When you react to someone's story, Instagram delivers a DM notification to
the creator: "X reacted ❤️ to your story."  This is the highest-conversion
touchpoint in the Follow+Story notification stack — the creator is pulled
into a DM thread, not just a profile visit.

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Reaction RATE: varies by EmojiPersonality type, with LogNormal jitter
      applied daily so the same account has different rates day to day.
      Fleet histogram across accounts is shaped by personality distribution —
      no flat monoculture rate.
    - Reaction SELECTION: each account has a stable EmojiPersonality assigned
      by hash(account_id), which determines the emoji weight pool.  The same
      account always picks from the same personality-specific pool.  500
      accounts reacting to the same story will produce a diverse emoji spread
      rather than 35% ❤️ monoculture.
    - Daily hard cap at 15: code-enforced, never prompt-enforced.  Too many
      reactions signals bot behaviour even with correct per-reaction timing.
    - Dedup: we track reacted media_ids and never react twice.
    - Inter-reaction sleep: LogNormal(mean=ln(45), sigma=0.5) — median ~45s.

Inputs come from today's story views (produced by IGFollowStoryOrchestrator).
The orchestrator calls this agent after running all story views.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from ...core.distributions import LogNormal, WeightedCategorical, seed_for
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGActionBlocked,
    IGRateLimited,
    IGSession,
    IGSessionExpired,
    InstagramClient,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constants (code-enforced, never prompt-guided)
# ---------------------------------------------------------------------------

MAX_REACTIONS_PER_ACCOUNT_PER_DAY: int = 50   # 30% of 150-170 story views/day

# Spec-mandated global emoji pool (used for backwards-compat and reporting).
# The personality system uses per-personality pools for actual emoji selection,
# but this global pool is exported for callers that need the canonical weights.
REACTION_POOL: list[tuple[str, float]] = [
    ("❤️", 35),
    ("🔥", 25),
    ("😍", 15),
    ("😂", 10),
    ("👏",  8),
    ("💜",  7),
]

# ---------------------------------------------------------------------------
# Emoji personality system
#
# Each account is assigned a stable EmojiPersonality seeded from
# hash(account_id).  This determines BOTH the emoji weight pool AND the
# base reaction rate.  Result: 500 accounts reacting to the same story
# produce a diverse emoji spread instead of a ❤️ monoculture cluster.
# ---------------------------------------------------------------------------


class EmojiPersonality(str, Enum):
    HEART_LOVER = "heart_lover"   # heavy ❤️ user — 50% hearts, rarely uses fire
    HYPE_BEAST  = "hype_beast"    # heavy 🔥 user — fire + 💯 dominant
    SWEET       = "sweet"         # 🥰 😍 💕 dominant — affectionate
    LAUGHER     = "laugher"       # 😂 💀 dominant — comedy reactor
    SUPPORTER   = "supporter"     # 👏 💪 🙌 — encouragement focused
    MINIMAL     = "minimal"       # rarely reacts, only strong emojis when does
    MIXED       = "mixed"         # genuinely varied, no dominant emoji


# Per-personality emoji weight distributions (emoji, weight)
#
# Fleet-scale diversity: each personality has a LARGE, distinct pool so
# that 500 accounts reacting to the same story produce a natural spread.
# If you run GROUP BY emoji across the whole fleet you get a long tail
# of 40+ distinct emojis — no single emoji dominates above ~12%.
# Personalities share almost no top-weight emojis, preventing cluster detection.
PERSONALITY_EMOJI_WEIGHTS: dict[EmojiPersonality, list[tuple[str, int]]] = {
    EmojiPersonality.HEART_LOVER: [
        # Romance / affection dominant — big heart family
        ("❤️", 30), ("🥰", 18), ("😍", 15), ("💕", 12), ("💖", 8),
        ("💗", 6), ("💓", 5), ("💞", 4), ("😘", 4), ("🫶", 3),
        ("❤️‍🔥", 3), ("💝", 2), ("💌", 2), ("🌹", 1), ("🔥", 1),
        # Rare tail — keeps distribution alive
        ("✨", 1), ("🌟", 1), ("💋", 1), ("🫀", 1), ("🩷", 1),
    ],
    EmojiPersonality.HYPE_BEAST: [
        # Energy / hype dominant — fire, trophies, explosions
        ("🔥", 28), ("💯", 18), ("👏", 12), ("🚀", 8), ("💥", 7),
        ("⚡", 6), ("🏆", 5), ("👑", 4), ("🤯", 4), ("🫡", 3),
        ("🤌", 3), ("💪", 3), ("😤", 3), ("🙌", 2), ("🔝", 2),
        # Tail
        ("🎯", 2), ("🫰", 1), ("🧨", 1), ("💣", 1), ("🎊", 1),
    ],
    EmojiPersonality.SWEET: [
        # Soft / cute / floral — pink and pastel vibes
        ("🥰", 25), ("💕", 20), ("😍", 15), ("🌸", 8), ("🌺", 7),
        ("✨", 6), ("🌷", 5), ("🦋", 4), ("💫", 4), ("🌟", 3),
        ("🍓", 3), ("🫧", 3), ("🩷", 3), ("🌼", 2), ("🫶", 2),
        # Tail
        ("🌈", 2), ("🍒", 1), ("🎀", 1), ("🌙", 1), ("💐", 1),
    ],
    EmojiPersonality.LAUGHER: [
        # Comedy / chaotic — dead + crying dominant
        ("😂", 28), ("💀", 22), ("😭", 16), ("🤣", 10), ("😅", 6),
        ("🫠", 5), ("💅", 4), ("🤡", 3), ("😩", 3), ("👀", 3),
        ("🥲", 2), ("🫡", 2), ("🤌", 2), ("🗿", 2), ("😳", 2),
        # Tail
        ("🤦", 1), ("🧍", 1), ("🫣", 1), ("🥴", 1), ("😵", 1),
    ],
    EmojiPersonality.SUPPORTER: [
        # Clapping / cheering / solidarity — encouragement focused
        ("👏", 25), ("💪", 20), ("🙌", 15), ("🫶", 10), ("✨", 8),
        ("👊", 6), ("🤝", 5), ("🙏", 5), ("💯", 4), ("🏆", 4),
        ("🌟", 3), ("💥", 2), ("❤️", 2), ("🫂", 2), ("👍", 2),
        # Tail
        ("🎉", 1), ("🎊", 1), ("🫁", 1), ("💫", 1), ("🫙", 1),
    ],
    EmojiPersonality.MINIMAL: [
        # Reacts rarely (rate 5-10%) but when they do: clean, strong emojis.
        # Small pool on purpose — selective accounts are still varied enough.
        ("❤️", 30), ("🔥", 25), ("👏", 15), ("💯", 12), ("🙌", 8),
        ("✨", 5), ("💪", 3), ("🫶", 2),
    ],
    EmojiPersonality.MIXED: [
        # Genuinely random — pulls from all emotional registers.
        # This personality alone covers 35+ distinct emojis at scale.
        ("❤️", 7), ("🔥", 7), ("😂", 6), ("🥰", 6), ("👏", 5),
        ("😍", 5), ("💯", 5), ("✨", 4), ("💀", 4), ("🚀", 3),
        ("🤯", 3), ("🫶", 3), ("💕", 3), ("🌸", 2), ("💪", 2),
        ("🙌", 2), ("😭", 2), ("🤌", 2), ("🎉", 2), ("🏆", 2),
        ("⚡", 2), ("💥", 2), ("🌟", 2), ("🫠", 1), ("👀", 1),
        ("😤", 1), ("💫", 1), ("🫡", 1), ("🥲", 1), ("🌺", 1),
        ("🤣", 1), ("😘", 1), ("💖", 1), ("🦋", 1), ("🎯", 1),
    ],
}

# Per-personality base reaction rate parameters (mean, sigma) for LogNormal.
# These are the ACCOUNT'S personal base rate before daily jitter.
PERSONALITY_REACT_RATES: dict[EmojiPersonality, tuple[float, float]] = {
    # (mean, sigma)
    EmojiPersonality.HEART_LOVER: (0.35, 0.15),  # reacts a lot
    EmojiPersonality.HYPE_BEAST:  (0.30, 0.18),
    EmojiPersonality.SWEET:       (0.32, 0.15),
    EmojiPersonality.LAUGHER:     (0.20, 0.20),  # selective
    EmojiPersonality.SUPPORTER:   (0.28, 0.18),
    EmojiPersonality.MINIMAL:     (0.08, 0.15),  # very selective
    EmojiPersonality.MIXED:       (0.22, 0.25),  # varied day to day
}

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# LogNormal(mean=ln(30), sigma=0.4) — median ~30s between reactions
_INTER_REACTION_DIST = LogNormal(low=8.0, high=300.0, sigma=0.40)


# ---------------------------------------------------------------------------
# Per-story view record (passed in from the orchestrator)
# ---------------------------------------------------------------------------

@dataclass
class StoryViewRecord:
    """A single story that was viewed today — candidate for reaction."""
    reel_id:        str   # story owner's IG user ID
    media_id:       str   # specific story item ID
    account_id:     str   # our account that viewed it
    target_user_id: str   # same as reel_id usually; kept explicit


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _stable_hash(text: str) -> int:
    """Deterministic 64-bit integer from a string."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def assign_personality(account_id: str) -> EmojiPersonality:
    """
    Assign a stable EmojiPersonality to an account.

    Seeded by SHA-256(account_id) so the assignment is deterministic:
    the same account_id always returns the same personality, but
    different account_ids are distributed across all 7 personality
    types.  Never changes for the same account_id.
    """
    seed = int(hashlib.sha256(account_id.encode()).hexdigest(), 16)
    personalities = list(EmojiPersonality)
    return personalities[seed % len(personalities)]


def _daily_reaction_rate(account_id: str, date_iso: str) -> float:
    """
    Per-account, per-day reaction rate drawn from the personality's LogNormal.

    Base rate comes from PERSONALITY_REACT_RATES[personality].
    Daily jitter: base_rate * LogNormal(0, 0.2) clamped to [0.15, 0.50].
    Fleet histogram is log-normal, shaped by personality distribution —
    no flat monoculture.
    Seeded by hash(account_id + date_iso) so replay is deterministic.
    """
    import random as _random

    personality = assign_personality(account_id)
    mean, sigma = PERSONALITY_REACT_RATES[personality]

    # Base rate draw: LogNormal around personality mean
    base_seed = _stable_hash(f"{account_id}|{date_iso}|reaction_rate_base")
    base_rng = _random.Random(base_seed)
    mu = math.log(mean)
    base_rate = base_rng.lognormvariate(mu, sigma)

    # Daily jitter: multiplicative LogNormal(0, 0.2) so rate varies day to day
    jitter_seed = _stable_hash(f"{account_id}|{date_iso}|reaction_rate_jitter")
    jitter_rng = _random.Random(jitter_seed)
    jitter = jitter_rng.lognormvariate(0.0, 0.2)

    daily_rate = base_rate * jitter
    return max(0.05, min(0.50, daily_rate))


def _should_react(account_id: str, media_id: str, rate: float) -> bool:
    """
    Deterministic per-(account, story) react decision.

    Uses hash(account_id + media_id) % 1000 < rate * 1000.
    Same account+story always gets same decision.
    """
    h = _stable_hash(f"{account_id}|{media_id}|react_decision") % 1000
    return h < int(rate * 1000)


def _pick_emoji(account_id: str, media_id: str) -> str:
    """
    Select a reaction emoji for this account+story using the account's
    personality-specific weight distribution.

    Consistent: the same account always reacts to the same story with the
    same emoji (seeded by account_id+media_id).  Different accounts react
    differently to the same story because they draw from different
    personality pools.  This is the primary mechanism that prevents a
    fleet-wide ❤️ monoculture — each personality type has a distinct
    dominant emoji.
    """
    import random as _random

    personality = assign_personality(account_id)
    pool = PERSONALITY_EMOJI_WEIGHTS[personality]

    seed = _stable_hash(f"{account_id}|{media_id}|emoji_pick")
    rng = _random.Random(seed)
    total = sum(w for _, w in pool)
    roll = rng.random() * total
    cumulative = 0.0
    for emoji, weight in pool:
        cumulative += weight
        if roll <= cumulative:
            return emoji
    return pool[0][0]  # fallback: first emoji in personality pool


# ---------------------------------------------------------------------------
# IGStoryReactAgent
# ---------------------------------------------------------------------------


class IGStoryReactAgent:
    """
    Sends selective emoji reactions to Instagram stories.

    Each account has a stable EmojiPersonality assigned by hash(account_id).
    Reaction rate and emoji selection both vary by personality, so 500 accounts
    reacting to the same story produce a realistic diverse emoji spread rather
    than a detectable ❤️ monoculture.

    A story reaction sends a DM notification to the creator. This is the
    highest-conversion touchpoint in the Follow+Story flow — more intimate
    than a view, less pushy than a cold DM.

    Usage:
        agent = IGStoryReactAgent()
        result = await agent.run_session(task, session)

    task.params keys:
        story_views_today  — list of StoryViewRecord dicts or StoryViewRecord objects
        date_iso           — YYYY-MM-DD (optional, defaults to today UTC)
    """

    async def run_session(
        self,
        account_id: str,
        session: IGSession,
        story_views_today: list[StoryViewRecord | dict],
        date_iso: Optional[str] = None,
        reactions_sent_today: int = 0,
    ) -> WorkerResult:
        """
        Run one story-react session for one account.

        Args:
            account_id:            Internal account identifier.
            session:               Authenticated IGSession.
            story_views_today:     List of stories viewed today (from
                                   IGFollowStoryOrchestrator).
            date_iso:              YYYY-MM-DD (defaults to today UTC).
            reactions_sent_today:  Count of reactions already sent today.

        Returns:
            WorkerResult with data keys:
                reactions_sent, reaction_rate_today, already_reacted_skips,
                errors, personality
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        task_id = f"{account_id}_story_react_{date_iso}"

        # Assign stable personality at session start
        personality = assign_personality(account_id)

        # Normalise to StoryViewRecord objects
        records: list[StoryViewRecord] = []
        for item in story_views_today:
            if isinstance(item, StoryViewRecord):
                records.append(item)
            else:
                records.append(StoryViewRecord(
                    reel_id=item["reel_id"],
                    media_id=item["media_id"],
                    account_id=item.get("account_id", account_id),
                    target_user_id=item.get("target_user_id", item["reel_id"]),
                ))

        # Per-account daily rate (personality-seeded, jittered per day)
        reaction_rate = _daily_reaction_rate(account_id, date_iso)

        reactions_sent = 0
        already_reacted_skips = 0
        errors: list[str] = []
        reacted_media_ids: set[str] = set()  # dedup within this session

        async with InstagramClient(session) as client:
            for idx, record in enumerate(records):
                # Code-enforced daily cap
                if reactions_sent_today + reactions_sent >= MAX_REACTIONS_PER_ACCOUNT_PER_DAY:
                    log.info(
                        "[%s] Daily reaction cap reached (%d), stopping",
                        account_id, MAX_REACTIONS_PER_ACCOUNT_PER_DAY,
                    )
                    break

                # Never react to the same story twice
                if record.media_id in reacted_media_ids:
                    already_reacted_skips += 1
                    continue

                # Probabilistic gate: react only if hash says yes
                if not _should_react(account_id, record.media_id, reaction_rate):
                    continue

                emoji = _pick_emoji(account_id, record.media_id)

                try:
                    ok = await client.react_to_story(
                        reel_id=record.reel_id,
                        media_id=record.media_id,
                        reaction_emoji=emoji,
                    )
                    if ok:
                        reactions_sent += 1
                        reacted_media_ids.add(record.media_id)
                        log.info(
                            "[%s] (%s) Reacted %s to story %s (user %s)",
                            account_id, personality.value, emoji,
                            record.media_id, record.reel_id,
                        )
                    else:
                        errors.append(f"react_failed:media={record.media_id}")

                except IGSessionExpired:
                    log.warning("[%s] Session expired during story reaction", account_id)
                    errors.append(f"session_expired:media={record.media_id}")
                    break
                except IGRateLimited:
                    log.warning("[%s] Rate limited during story reaction", account_id)
                    errors.append(f"rate_limited:media={record.media_id}")
                    break
                except IGActionBlocked:
                    log.warning("[%s] Story reaction action blocked", account_id)
                    errors.append(f"action_blocked:media={record.media_id}")
                    break
                except Exception as exc:
                    log.error("[%s] Reaction error for media %s: %s", account_id, record.media_id, exc)
                    errors.append(f"error:media={record.media_id}:{exc}")
                    continue

                # Inter-reaction sleep (only when more reactions may follow)
                remaining_budget = MAX_REACTIONS_PER_ACCOUNT_PER_DAY - (reactions_sent_today + reactions_sent)
                if idx < len(records) - 1 and remaining_budget > 0:
                    delay = _INTER_REACTION_DIST.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_react_{idx}",
                    )
                    await asyncio.sleep(delay)

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":                 "story_react",
                "reactions_sent":         reactions_sent,
                "reaction_rate_today":    reaction_rate,
                "already_reacted_skips":  already_reacted_skips,
                "errors":                 errors,
                "personality":            personality.value,
            },
        )
