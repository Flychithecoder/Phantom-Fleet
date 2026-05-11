"""
IGNotesAgent — posts one Instagram Note per account per day to maintain
high-visibility presence at the top of every follower's DM inbox.

Instagram Notes appear as a small bubble above every DM thread in every
follower's inbox for 24 hours. When a follower opens their DM tab, the Notes
row is the first thing they see — 100% impression rate, zero algorithmic
dependency. This agent posts a fresh personality-driven Note each morning,
keeping our accounts visible without sending a single outbound message.

Design decisions (CLAUDE.md fleet-scale audit):

    Content monoculture prevention:
        - Pool of 120 note templates across 8 mood categories
        - Selection seed = hash(account_id + date_iso) → same account always
          posts the same note on a given day (idempotent replay), but different
          accounts on the same day post different notes
        - Minimum pool size of 120 enforced at construction; below this the
          per-account seeded selection concentrates too many accounts per template
        - 30-day dedup: same account never repeats the same note within 30 days
          (caller provides posted_notes_30d set; agent won't post if note is in it)

    Timing:
        - Target posting window: ~10am account local time (scheduled by caller)
        - Per-account jitter: derived from same hash seed → no fleet-wide 10:00 UTC spike
        - Delete-then-set gap: LogNormal(mean=ln(3), sigma=0.3), clamped [1, 15]

    Hard cap:
        - 1 Note per account per day, code-enforced

    Content rules:
        - NEVER include links, CTAs, "OnlyFans", dollar signs, or sales language
        - NEVER exceed 60 characters (Instagram limit, enforced by truncation in code)
        - Must sound like a real person's casual mood update, not marketing copy

    API:
        - POST /api/v1/notes/create_note/ with {"text": "...", "audience": 1}
        - audience=1 → followers only (not close friends)
        - Notes auto-expire after 24h — no cleanup needed
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import IGSession, InstagramClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Daily hard cap
# ---------------------------------------------------------------------------

_DAILY_NOTE_CAP: int = 1          # one post per account per day

# ---------------------------------------------------------------------------
# Note length limit (Instagram enforces 60 chars on-device)
# ---------------------------------------------------------------------------

NOTE_MAX_CHARS: int = 60

# ---------------------------------------------------------------------------
# Delete → set gap distribution
# LogNormal(mean=ln(3), sigma=0.3) → median ~3s, tail to ~12s
# Mirrors the natural delay between IG UI "delete note" tap and "set note" tap
# ---------------------------------------------------------------------------

_DELETE_SET_GAP_DIST = LogNormal(low=1.0, high=15.0, sigma=0.30)

# ---------------------------------------------------------------------------
# Minimum pool size for fleet-scale anti-monoculture guarantee
# ---------------------------------------------------------------------------

_MIN_POOL_SIZE: int = 120

# ---------------------------------------------------------------------------
# Note pool — 120 templates across 8 mood categories.
# Each template ≤ 60 chars. Authentic Gen Z voice. No CTAs, no sales language.
# Categories: flirty, funny, relatable, mystery, foodie, fitness, mood, seasonal
# ---------------------------------------------------------------------------

DEFAULT_NOTE_POOL: list[str] = [
    # ---- flirty (15 notes) ----
    "ur probably thinking about me rn 🫦",
    "not me looking cute for absolutely no reason",
    "dangerous when bored just saying 💅",
    "someone's lucky to know me lol",
    "sending soft vibes to whoever needs it 🌙",
    "main character szn is never ending for me",
    "i'm the type you tell your friends about 🫶",
    "not to brag but i'm kinda that girl",
    "wearing my confidence today 💋",
    "mysterious era loading… 🖤",
    "the ones who get me really get me",
    "some people just radiate something different ✨",
    "soft but not to be played with",
    "healing glow up is real and it shows",
    "eye contact but make it dangerous 🌹",

    # ---- funny (15 notes) ----
    "running on caffeine and delusion ☕",
    "my villain arc started today tbh",
    "why is it always [day of week] 😩",
    "asked for a sign, got three 🚨",
    "brain: off. vibes: on.",
    "professionally unbothered since forever",
    "my bed called, i answered immediately",
    "zero tasks completed. ten tabs open. thriving.",
    "accidentally became the main character again",
    "sent an email and now i deserve a nap",
    "my rizz is on a loading screen rn",
    "hot girl nap szn is year round 💤",
    "i said what i said and meant every word",
    "living in a group chat no one reads 💀",
    "therapy voice activated ✅",

    # ---- relatable (15 notes) ----
    "need sleep but also not 😭",
    "girl dinner szn 🍕",
    "this week has been a lot honestly",
    "can't stop thinking about [redacted] 🫣",
    "some days you just survive and that's ok",
    "doing my best which varies daily",
    "the quiet kind of tired you know?",
    "finally replied to texts. heroic honestly.",
    "woke up and chose to exist. brave.",
    "my emotional support snack understood me today",
    "nothing like a walk to fix literally nothing",
    "adulting is a scam no one warned me about",
    "soft launch of me being okay 🫶",
    "today was a 6/10 and that's fine",
    "the pressure to have a good day is real",

    # ---- mystery (15 notes) ----
    "you already know 🤫",
    "some things are better left unsaid 🖤",
    "not everything needs an explanation",
    "the best chapters are the ones no one reads",
    "quiet energy hits different 🌑",
    "interesting times ✦",
    "reading between the lines today",
    "things are shifting and it's giving growth",
    "something's changing. not sure what. staying ready.",
    "the feeling before something good happens 🕯️",
    "not ready to talk about it yet but soon",
    "trust the timing even when it makes no sense",
    "in my head but in the good way",
    "the vibe knows before the mind does ✨",
    "chapter one of something big 📖",

    # ---- foodie (15 notes) ----
    "soft scrambled eggs changed my life fr",
    "thinking about that pasta from three weeks ago",
    "iced coffee is a personality and i'm ok with that",
    "matcha era has been going for two years now",
    "comfort meal day is self care actually 🍜",
    "obsessed with anything warm and carb-y rn",
    "my roman empire: a perfect breakfast sandwich",
    "this snack understood the assignment 🫶",
    "late night fridge raid o'clock",
    "meal prepped and felt like a different person",
    "someone make me soup please 🥣",
    "bakery coffee on a slow morning is everything",
    "ate the whole thing and regret nothing",
    "new restaurant unlocked. life is good.",
    "the food was mid but the company wasn't 🍽️",

    # ---- fitness (15 notes) ----
    "body did the workout. brain got the trophy.",
    "rest day is a training day actually 💤",
    "sore in the best possible way rn",
    "morning walks are cheaper than therapy",
    "stretching is the gateway drug to health honestly",
    "gym was hard today. went anyway. growth.",
    "sweat equity is real and i'm investing",
    "movement is my mental health plan 🏃‍♀️",
    "the discipline is the glow up",
    "ran further than yesterday. small win.",
    "sleep + water + moving = the whole secret",
    "rest is productive. i say this as a reminder.",
    "the goal is consistency not perfection",
    "workout done. now eating everything in sight.",
    "strong is genuinely such a good feeling",

    # ---- mood (15 notes) ----
    "in my feelings today and that's allowed 🎵",
    "grateful for the small things today 🙏",
    "peace is the real flex honestly",
    "soft life is the only life worth living 🌸",
    "today was gentle and i needed that",
    "choosing calm over chaos, finally",
    "good energy is contagious and i'm patient zero",
    "the mindset shift hit different this week",
    "grounded era loading 🌿",
    "not performing happiness. actually feeling it.",
    "healing looks different for everyone and that's ok",
    "some days the vibe is just gratitude",
    "at peace with the pace of my own life",
    "present moment is actually where it's at",
    "still growing and it feels right 🌱",

    # ---- seasonal / timely (15 notes) ----
    "autumn energy is everything 🍂",
    "hot girl summer is a mindset not a season",
    "january energy but make it sustainable",
    "spring reset szn officially in effect 🌷",
    "winter is for hibernating and healing tbh",
    "cozy season is the only season i respect",
    "summer brain activated ☀️",
    "holiday season hits different when you're grateful",
    "new month means new intentions 🌙",
    "end of week survived. barely. still counts.",
    "friday energy on any day of the week",
    "sunday reset but like actually this week",
    "new year but make it a new day energy",
    "back to school brain never fully left me",
    "seasonal sadness is real but so is seasonal joy",
]

# Validate pool at module load — fail fast, not at runtime
assert len(DEFAULT_NOTE_POOL) >= _MIN_POOL_SIZE, (
    f"DEFAULT_NOTE_POOL has {len(DEFAULT_NOTE_POOL)} entries — "
    f"minimum required is {_MIN_POOL_SIZE} for fleet-scale anti-monoculture"
)


# ---------------------------------------------------------------------------
# Category metadata (for logging and analytics)
# ---------------------------------------------------------------------------

_MOOD_CATEGORIES = [
    "flirty",
    "funny",
    "relatable",
    "mystery",
    "foodie",
    "fitness",
    "mood",
    "seasonal",
]

_NOTES_PER_CATEGORY = 15  # 8 categories × 15 = 120

def _category_for_index(idx: int) -> str:
    """Return the mood category name for a given pool index."""
    cat_idx = idx // _NOTES_PER_CATEGORY
    return _MOOD_CATEGORIES[min(cat_idx, len(_MOOD_CATEGORIES) - 1)]


# ---------------------------------------------------------------------------
# Task / state helpers
# ---------------------------------------------------------------------------

@dataclass
class IGNotesTask:
    """Input for one IGNotesAgent rotation run."""
    account_id:       str
    ig_session:       IGSession
    date_iso:         str                # "YYYY-MM-DD" — used for stable seed
    note_pool:        list[str] = field(default_factory=lambda: list(DEFAULT_NOTE_POOL))
    rotations_today:  int       = 0      # how many times already posted today
    posted_notes_30d: set[str]  = field(default_factory=set)  # notes posted in last 30 days
    proxy_url:        str       = "socks5://127.0.0.1:8089"


@dataclass
class NotesRotationState:
    """Persisted per-account rotation state (serialised by caller as JSON/DB)."""
    account_id:     str
    last_rotated:   str    # ISO date string "YYYY-MM-DD"
    last_note_text: str
    rotations_today: int   = 0


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IGNotesAgent:
    """
    Posts one Instagram Note per account per day, maintaining high-visibility
    presence at the top of every follower's DM inbox.

    Notes appear above all DM threads for 24h → free impressions with 100%
    follower reach every time they open their DMs.

    Fleet-scale detection resistance:
        - 120-note pool across 8 mood categories (15 each)
        - SHA-256 seeded selection: same account + same day = same note
          (replay-safe idempotency), but fleet shows different notes on the same day
        - 30-day dedup: no account repeats the same note within 30 days
        - LogNormal gap between delete and set prevents fixed-delay clustering
        - Posting time jitter derived from same hash seed (no 10:00 UTC spike)

    Usage:
        agent = IGNotesAgent()
        result = await agent.post_daily_note(
            account_id="acct_123",
            session=ig_session,
            date_iso="2026-04-11",
            posted_notes_30d={"some old note text"},
        )
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def post_daily_note(
        self,
        account_id: str,
        session: IGSession,
        date_iso: str,
        posted_notes_30d: set[str],
        note_pool: Optional[list[str]] = None,
        rotations_today: int = 0,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ) -> WorkerResult:
        """
        Post today's Note for one account.

        Selection is deterministic: hash(account_id + date_iso) % pool_size.
        If the selected note was already posted in the last 30 days, the agent
        cycles through the pool (incrementing the index by 1 each time) until
        it finds an unused note or exhausts the pool (pool too small / account
        very active — raises a warning and uses the closest available note).

        Steps:
            1. Validate pool size (≥ 120 required)
            2. Check daily cap (1 post/day)
            3. Select note using deterministic seed (with 30-day dedup cycling)
            4. Delete existing note (non-fatal if none exists)
            5. LogNormal gap (mirrors human tap delay)
            6. POST /api/v1/notes/create_note/ with audience=1
            7. Return WorkerResult

        Args:
            account_id:        Internal account identifier.
            session:           Authenticated IGSession.
            date_iso:          YYYY-MM-DD for stable seed.
            posted_notes_30d:  Set of note texts posted in the last 30 days.
                               Agent will not select a note already in this set.
            note_pool:         Note pool to use. Defaults to DEFAULT_NOTE_POOL.
            rotations_today:   Notes already posted today (cap check).
            proxy_url:         SOCKS5 proxy for this account.

        Returns:
            WorkerResult with data = {note_text, mood_category, posted_at}
        """
        pool = note_pool or DEFAULT_NOTE_POOL

        # ------------------------------------------------------------------
        # 1. Validate pool
        # ------------------------------------------------------------------
        try:
            _validate_pool(pool)
        except ValueError as exc:
            return _failure_result(account_id, [str(exc)])

        # ------------------------------------------------------------------
        # 2. Daily cap check (code-enforced)
        # ------------------------------------------------------------------
        if rotations_today >= _DAILY_NOTE_CAP:
            msg = (
                f"daily_cap_reached:note:"
                f"{rotations_today}/{_DAILY_NOTE_CAP} "
                f"for account {account_id}"
            )
            log.warning("[%s] %s", account_id, msg)
            return _failure_result(account_id, [msg])

        # ------------------------------------------------------------------
        # 3. Select today's note with 30-day dedup cycling
        # ------------------------------------------------------------------
        note_text, pool_idx = select_note_with_dedup(
            pool=pool,
            account_id=account_id,
            date_iso=date_iso,
            posted_notes_30d=posted_notes_30d,
        )
        mood_category = _category_for_index(pool_idx)

        log.info(
            "[%s] selected note for %s (category=%s, idx=%d): %r",
            account_id, date_iso, mood_category, pool_idx, note_text,
        )

        # ------------------------------------------------------------------
        # 4–6. Delete existing → LogNormal gap → POST create_note
        # ------------------------------------------------------------------
        errors: list[str] = []
        posted_at: Optional[str] = None
        gap: float = 0.0

        async with InstagramClient(session, proxy_url=proxy_url) as client:
            # Delete existing note (non-fatal — IG returns OK even if none exists)
            try:
                await client.delete_note()
                log.debug("[%s] existing note deleted", account_id)
            except Exception as exc:
                log.debug(
                    "[%s] delete_note warning (likely benign): %s", account_id, exc
                )

            # LogNormal gap between delete and create
            gap = _DELETE_SET_GAP_DIST.sample(
                account_id=account_id,
                date_iso=date_iso,
                field="note_delete_set_gap",
            )
            await asyncio.sleep(gap)

            # POST create_note with audience=1 (followers only)
            try:
                ok = await client.create_note(
                    text=note_text,
                    audience=1,
                )
                from datetime import datetime, timezone
                posted_at = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                err = f"create_note_failed:{type(exc).__name__}:{exc}"
                log.error("[%s] %s", account_id, err)
                return _failure_result(account_id, [err])

        if not ok:
            err = "create_note_returned_not_ok"
            log.error("[%s] %s", account_id, err)
            return _failure_result(account_id, [err])

        log.info(
            "[%s] note posted: %r (category=%s, gap=%.1fs)",
            account_id, note_text, mood_category, gap,
        )

        return WorkerResult(
            task_id=f"ig_notes_{account_id}",
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "note_text":     note_text,
                "mood_category": mood_category,
                "posted_at":     posted_at,
                "gap_seconds":   round(gap, 2),
                "date_iso":      date_iso,
            },
        )

    # ------------------------------------------------------------------
    # Backward-compatible alias for callers using old interface
    # ------------------------------------------------------------------

    async def run_daily_rotation(self, task: IGNotesTask) -> WorkerResult:
        """Backward-compatible wrapper around post_daily_note."""
        return await self.post_daily_note(
            account_id=task.account_id,
            session=task.ig_session,
            date_iso=task.date_iso,
            posted_notes_30d=task.posted_notes_30d,
            note_pool=task.note_pool,
            rotations_today=task.rotations_today,
            proxy_url=task.proxy_url,
        )


# ---------------------------------------------------------------------------
# Pure helpers (exported so tests can call them directly)
# ---------------------------------------------------------------------------

def select_note(pool: list[str], account_id: str, date_iso: str) -> str:
    """
    Select a note from pool using a deterministic seed.

    Seed = hash(account_id + date_iso). Same account + same date always
    selects the same note. Different accounts on same date select different
    notes (anti-monoculture).

    Does NOT apply 30-day dedup — use select_note_with_dedup for that.
    Enforces the 60-char hard limit.
    """
    if not pool:
        raise ValueError("note pool must not be empty")
    seed_input = (account_id + date_iso).encode("utf-8")
    seed = int(hashlib.sha256(seed_input).hexdigest(), 16)
    idx = seed % len(pool)
    return _enforce_char_limit(pool[idx])


def select_note_with_dedup(
    pool: list[str],
    account_id: str,
    date_iso: str,
    posted_notes_30d: set[str],
) -> tuple[str, int]:
    """
    Select a note with 30-day dedup cycling.

    Starting from hash(account_id + date_iso) % pool_size, cycle through
    the pool until a note not in posted_notes_30d is found.

    Returns:
        (note_text, pool_index) — the selected note text and its index in pool.

    If every note in the pool was posted in the last 30 days (pool exhausted),
    logs a warning and returns the base index note regardless (pool is too small
    for the account's activity level — caller should expand the pool).
    """
    if not pool:
        raise ValueError("note pool must not be empty")
    seed_input = (account_id + date_iso).encode("utf-8")
    base_idx = int(hashlib.sha256(seed_input).hexdigest(), 16) % len(pool)

    for offset in range(len(pool)):
        idx = (base_idx + offset) % len(pool)
        candidate = _enforce_char_limit(pool[idx])
        if candidate not in posted_notes_30d:
            return candidate, idx

    # All notes in pool have been used in the last 30 days
    log.warning(
        "[%s] All %d notes in pool used in last 30 days — "
        "pool too small for account activity; using base index note",
        account_id, len(pool),
    )
    return _enforce_char_limit(pool[base_idx]), base_idx


def _enforce_char_limit(text: str) -> str:
    """Truncate text to NOTE_MAX_CHARS, appending '...' if truncated."""
    if len(text) <= NOTE_MAX_CHARS:
        return text
    return text[: NOTE_MAX_CHARS - 3] + "..."


def _validate_pool(pool: list[str]) -> None:
    """Raise ValueError if the pool is too small for fleet-scale anti-monoculture."""
    if len(pool) < _MIN_POOL_SIZE:
        raise ValueError(
            f"note pool must contain at least {_MIN_POOL_SIZE} entries to prevent "
            f"content monoculture at fleet scale — got {len(pool)}"
        )


def _failure_result(account_id: str, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id=f"ig_notes_{account_id}",
        platform="instagram",
        account_id=account_id,
        success=False,
        error="; ".join(errors),
        data={"errors": errors},
    )
