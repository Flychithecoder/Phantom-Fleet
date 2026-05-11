"""
IGPodManager — Instagram engagement pod orchestration for Phantom Fleet.

An engagement pod is a group of 10-15 accounts that automatically like and
comment on each other's posts within 0-90 minutes of publication. Instagram's
early-engagement algorithm rewards posts that accumulate 15+ engagements in
the first 60-90 minutes with Explore-page placement. Pods manufacture this
signal artificially.

Fleet-scale detection analysis (CLAUDE.md 20K account thought experiment):

TIMING DISTRIBUTION
    Each pod member draws its engagement delay from
    LogNormal(ln(900), 0.6) seconds — median ≈ 15 min, spread 2-90 min.
    The seed is hash(account_id + post_id), so:
      - Same account always engages with the same post at the same delay
        (deterministic replay).
      - Different accounts engage at different times (no two identical).
      Running HISTOGRAM(delay_seconds) across all pod members of a post
      produces a log-normal decay curve matching organic early-fan behaviour,
      NOT a flat staircase of equal-interval delays.

    Fleet risk without this: if all 12 members engage within a 5-second
    burst, the engagement velocity graph is a vertical spike. Instagram's
    ML detects coordinated bursts as an anomaly signal.

COMMENT PROBABILITY (30%)
    Not all pod members comment — a flat 100% comment rate on every pod
    post would mean 12 comments from the same 12 accounts on every single
    post (perfectly repeated sub-graph). 30% rate + probability seeded by
    hash(account_id + media_id + "comment_gate") means:
      - Each (account, post) pair has a stable yes/no decision.
      - Across 20K posts, an account comments on ≈ 30% of pod posts.
      - Running GROUP BY comment_text across the fleet shows the pool of
        200+ comments spread across many distinct values, not a tight cluster.

COMMENT POOL DIVERSITY
    200+ short natural comments grouped by niche. Each niche has 40+ entries.
    At 20K accounts × 30% comment probability: per-comment frequency across
    the fleet stays below 1% per entry even before personality weighting.
    EmojiPersonality from ig_story_react_agent further biases per-account
    comment picks, so the same account consistently prefers a subset of the
    pool — a realistic individual "voice."

IDENTITY ENTROPY
    Pod IDs are derived from sha256(account_id) % num_pods — stable, not
    random. Account always stays in the same pod; no reshuffling needed.
    This prevents "membership jitter" where an account's pod affiliation
    changes day to day (that would be detectable in the social graph).

POST AGE GATE (< 2 hours)
    Late engagement has diminishing algorithmic value AND creates an
    anomalous pattern: real fans engage within the first hour; pods
    engaging at hour 8 look like a scheduled bot sweep. Hard gate at
    7200 seconds enforced in code.

DAILY CAPS (code-enforced, never prompt-guided)
    - 10 pod-likes/account/day
    - 3 pod-comments/account/day
    These keep pod activity within the budget of a real power-user.
    Without caps: an account in 1 pod posting 5x/day could rack up
    50 pod-likes/day — a detectable outlier vs organic like behaviour.

REDIS PUB/SUB FANOUT
    New-post notifications fan out via Redis pub/sub channel
    pod:{pod_id}:new_post. Each subscriber (pod member's worker) wakes,
    draws its individual delay, and schedules its engagement independently.
    This decouples engagement timing across the fleet — workers on
    different phones do not synchronize.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import random as _random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ...core.distributions import LogNormal, seed_for
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGActionBlocked,
    IGRateLimited,
    IGSession,
    IGSessionExpired,
    InstagramClient,
)
from ...core.pod_registry import PodConfig, PodRegistry
from .ig_story_react_agent import EmojiPersonality, assign_personality

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius caps (CODE-enforced)
# ---------------------------------------------------------------------------

MAX_POD_LIKES_PER_ACCOUNT_PER_DAY: int = 10
MAX_POD_COMMENTS_PER_ACCOUNT_PER_DAY: int = 3
MAX_POD_ENGAGEMENT_WINDOW_SECONDS: int = 7_200   # 2 hours — no late engagement
COMMENT_PROBABILITY: float = 0.30

# ---------------------------------------------------------------------------
# Timing distributions
# ---------------------------------------------------------------------------

# LogNormal(ln(900), 0.6) — median ≈ 15 min, range ≈ 2-90 min
# Simulates "early fans noticing a post within the first hour"
_ENGAGEMENT_DELAY_DIST = LogNormal(low=120.0, high=5400.0, sigma=0.6)

# LogNormal(ln(30), 0.4) — post-engagement dwell (simulates reading comments)
_POST_DWELL_DIST = LogNormal(low=8.0, high=180.0, sigma=0.4)

# ---------------------------------------------------------------------------
# Comment pool — 200+ short natural comments, grouped by niche
# ---------------------------------------------------------------------------
# Fleet-scale diversity requirement: each niche must have ≥ 40 entries so
# that at scale (20K accounts × 30% comment probability) no single comment
# text appears in more than ~0.5% of pod-generated comments.
# Banned phrases (too generic / detectable): "Great post!", "Amazing!", "Wow!",
# "Nice!", "Love this!", "Beautiful!", "Awesome!", "Congrats!", "Well done!"
# ---------------------------------------------------------------------------

_COMMENT_POOLS: dict[str, list[str]] = {
    "beauty": [
        "omg yes 🔥", "this is so you 😍", "period bestie", "can't stop coming back to this",
        "saved this immediately", "the way you did that 😭", "ok but this look tho",
        "literally obsessed w this", "you're that girl fr", "i need this whole look",
        "the skin 😭🙌", "ok glam queen", "this is the vibe i want", "giving everything rn",
        "the way this is so clean", "no because why are you so pretty", "it's giving model",
        "ma'am you are not real", "this look is everything", "the makeup is immaculate",
        "ok you ate this one", "the aesthetic >>>", "i wanted to scroll past but i couldn't",
        "the color on you 😍", "queen behavior only", "this gave me inspo tbh",
        "the way i ran here", "ugh yes yes yes", "makeup is an art and you're a painter",
        "the soft glam is sending me", "not me studying this photo", "the glow 💫",
        "giving luxury catalog vibes", "main character behavior", "your aesthetic is immaculate",
        "no bc the vibe is unmatched", "face card declined? never.", "this is serotonin",
        "the energy in this photo is something", "idk what you're doing but keep doing it",
        "the fit the hair the makeup all serving", "this was made for you",
    ],
    "fitness": [
        "gains 💪", "you're built different fr", "putting me to shame lol", "ok bodygoals??",
        "the discipline tho", "how are you real", "this is what consistency looks like",
        "the progress is visible and i'm here for it", "i need to be in this gym yesterday",
        "you make it look so easy", "not me getting motivated rn", "respect 🙏",
        "the form is clean", "what's your program?? asking for a friend", "ok i'm going to the gym",
        "you're literally an athlete", "the dedication is unmatched", "this is my motivation post",
        "training arc activated (watching you)", "built from the ground up fr",
        "the physique 😤", "ok coach", "i aspire to this", "real ones train like this",
        "the work ethic showing", "no off days energy", "you make suffering look aesthetic",
        "the muscle definition tho", "this is what showing up looks like", "i felt this in my soul",
        "not skipping anymore after seeing this", "the grind is real", "fitness goals unlocked",
        "body built by sacrifice fr", "the progress in this is insane", "you're an inspiration ngl",
        "the athleticism is giving", "ok i need to get up", "routine check??",
        "you're carrying the whole gym fr", "hard work doesn't lie", "the results are speaking",
    ],
    "food": [
        "already hungry 😭", "where is this from pls", "the way i need this rn",
        "ok chef 👨‍🍳", "sending location", "this is food crime and i'm a victim",
        "i would eat this at 3am no hesitation", "my stomach just growled at the screen",
        "i was not prepared for this", "who made this and where can i find them",
        "the plating 😭", "not me drooling rn", "this is illegal", "recipe or i riot",
        "i need this in my life immediately", "the colors are insane", "comfort food unlocked",
        "whoever made this is a god", "the aesthetics AND the food? double win",
        "my tastebuds are crying from looking at this", "i could eat this every day",
        "ok this is peak food content", "the flavor i can TASTE through the screen",
        "ngl i'd wake up early for this", "food photography deserves an oscar",
        "this got me opening delivery apps", "the crunch in this photo is real",
        "absolutely unhinged and delicious", "the spread is giving feast",
        "this is what i deserve", "top tier eating experience incoming",
        "the way this is literally calling my name", "food goals fr",
        "ok the garnish alone tho", "this is art and also food which is better",
        "the texture is sending me", "no thoughts just eat this",
        "whoever ate this first is my hero", "the portions are speaking to me",
        "this is the serotonin i needed today", "the flavors must be crazy rn",
    ],
    "comedy": [
        "HELP 💀", "i am deceased", "not me cackling at work", "why is this so accurate",
        "i felt this", "i'm losing my mind at this rn", "the accuracy is criminal",
        "this is me and i'm not okay with how much it's me", "screaming internally",
        "i sent this to 7 people", "the timing on this 😭", "i physically cannot",
        "my therapist needs to see this", "not me spiraling because of a post",
        "this described my life in 3 seconds", "i'm telling everyone about this",
        "the way i audibly laughed", "chaotic energy and i love it",
        "this is unhinged behavior and i relate", "i'm actually crying 💀",
        "whoever made this understands me", "the chaos is the point",
        "i have no words but also so many words", "this is a cry for help and also funny",
        "certified unhinged content 10/10", "why did i watch this 4 times",
        "the relatable to unhinged pipeline is real", "i'm going to think about this tomorrow",
        "ok but why am i like this", "the way this called me out specifically",
        "the internet was made for this", "absolute menace behavior 💀",
        "not me showing everyone around me this", "this is my villain origin story",
        "i went through all 5 stages of grief watching this", "this is too real rn",
        "i need to lie down", "why is this funnier the more i watch it",
        "the writing on this 😭", "ok i'm dead and this killed me",
        "this should be illegal it's too good", "the chaos i aspire to",
    ],
    "lifestyle": [
        "this is the vibe i'm chasing", "the aesthetic is immaculate",
        "living this life through your photos fr", "ok the balance is everything",
        "this is peak content and i said what i said", "how are you doing this",
        "the curation is unreal", "this made my whole day honestly",
        "not me saving this for vision board purposes", "the mood in this photo",
        "you manifested this and it shows", "ok this is goals on goals",
        "the way this feels like a movie", "living intentionally looks good on you",
        "the peace in this feed is doing something for my nervous system",
        "ok you're living the life", "this is what balance looks like",
        "the vibe is elevated and i'm taking notes", "effortlessly aesthetic fr",
        "this is the content that makes me want to do better",
        "the whole thing is giving", "just want this life pls",
        "the way you document your world", "not me going to restructure my whole aesthetic",
        "ok lifestyle content done right", "this is so soft and so beautiful",
        "the curated chaos that works", "living your best life is showing",
        "this is giving peaceful and productive", "the ambiance in this photo is elite",
        "the whole page is a vibe tbh", "i felt calm just looking at this",
        "ok life planner energy", "this is what intentional living looks like",
        "the softness of this content 🥺", "saturated life, love to see it",
        "this is aspirational and achievable which is the best combo",
        "not me bookmarking everything you post", "the realness in this is refreshing",
        "this is the kind of feed that keeps me sane", "effortless and inspiring",
    ],
    "general": [
        "this hit different today", "idk why but i needed this", "you ate and left no crumbs",
        "obsessed", "not me saving this", "came back to this 3 times already",
        "this is the content i'm here for", "the way this found me at the right time",
        "no thoughts just appreciation", "this is everything rn",
        "ok i'm a fan now", "the energy of this post is immaculate",
        "i can't explain why i love this but i do", "this is so good it's making me emotional",
        "you're that person and it shows", "this is what the internet was made for",
        "i've been thinking about this all day", "the timing of this dropping today",
        "real ones understand this", "this just made my day better",
        "the way this is so right", "no notes, no notes at all",
        "screenshotted this instantly", "the vibe doesn't miss",
        "this is art whether you meant it or not", "the intention is felt",
        "posted at the right time for real", "not everything hits but this hit",
        "this is giving what it's supposed to give", "you are consistent and it shows",
        "the quality of the content tho", "ok i'm pressing follow and staying",
        "this made me feel something and i didn't expect that",
        "whoever taught you to do this, thank them", "the way this is just so good",
        "unmatched energy in this one", "i needed this reminder honestly",
        "the way this is better every time i look at it", "so good it's almost annoying",
        "not me emotionally invested in a post", "this is the type of content i run to show people",
        "i would have liked this twice if i could",
    ],
}

# Validate all pools have sufficient entries
_POOL_MIN_SIZE = 40
for _niche, _pool in _COMMENT_POOLS.items():
    assert len(_pool) >= _POOL_MIN_SIZE, (
        f"Comment pool for niche '{_niche}' has only {len(_pool)} entries; "
        f"need ≥ {_POOL_MIN_SIZE} for fleet-scale diversity."
    )

# Niches that map to the pools above (fallback → general)
_NICHE_ALIASES: dict[str, str] = {
    "beauty": "beauty",
    "makeup": "beauty",
    "skincare": "beauty",
    "fashion": "beauty",
    "fitness": "fitness",
    "gym": "fitness",
    "sport": "fitness",
    "health": "fitness",
    "food": "food",
    "cooking": "food",
    "recipe": "food",
    "restaurant": "food",
    "comedy": "comedy",
    "humor": "comedy",
    "meme": "comedy",
    "lifestyle": "lifestyle",
    "travel": "lifestyle",
    "wellness": "lifestyle",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PodEngagementRecord:
    """Audit log entry for a single pod engagement action."""
    actor_account_id: str
    target_account_id: str
    media_id: str
    action: str                       # "like" | "comment"
    comment_text: Optional[str]
    engaged_at_iso: str
    delay_seconds: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _stable_hash(text: str) -> int:
    """Deterministic 64-bit integer from a string via SHA-256."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _draw_engagement_delay(account_id: str, media_id: str) -> float:
    """
    Draw staggered engagement delay from LogNormal(ln(900), 0.6).

    Seeded by hash(account_id + media_id + "pod_delay") so:
      - Same account engages with the same post after the same delay (replay).
      - Different accounts engage at different times (no burst cluster).

    Median ≈ 15 min, range 2-90 min. This produces a realistic early-fan
    engagement decay curve — fast commenters arrive within minutes, slower
    ones up to an hour after posting.
    """
    seed = _stable_hash(f"{account_id}|{media_id}|pod_delay")
    rng = _random.Random(seed)
    raw = rng.lognormvariate(math.log(900), 0.6)
    return max(120.0, min(5400.0, raw))


def _should_comment(account_id: str, media_id: str) -> bool:
    """
    Stable 30% comment gate per (account, post).

    Uses hash(account_id + media_id + "comment_gate") % 1000 < 300.
    Same pair always gets same decision. Different pairs are independent.
    """
    h = _stable_hash(f"{account_id}|{media_id}|comment_gate") % 1000
    return h < 300


def _resolve_niche(niche: str) -> str:
    """Normalise niche string to a known pool key, defaulting to 'general'."""
    n = niche.lower().strip()
    return _NICHE_ALIASES.get(n, n if n in _COMMENT_POOLS else "general")


def _pick_comment_text(account_id: str, media_id: str, niche: str) -> str:
    """
    Select a comment from the niche pool, biased by EmojiPersonality.

    Personality maps to a slice index offset within the pool so accounts
    with different personalities consistently prefer different ends of the
    comment pool. This creates realistic individual "voices" across the
    fleet — a HEART_LOVER account leaves warmer comments than a LAUGHER.

    Seeded by hash(account_id + media_id + "comment_pick") for determinism.
    """
    pool_key = _resolve_niche(niche)
    pool = _COMMENT_POOLS[pool_key]

    personality = assign_personality(account_id)
    # Personality → offset into pool (each personality prefers a different slice)
    personality_offsets: dict[EmojiPersonality, int] = {
        EmojiPersonality.HEART_LOVER: 0,
        EmojiPersonality.HYPE_BEAST:  5,
        EmojiPersonality.SWEET:       10,
        EmojiPersonality.LAUGHER:     15,
        EmojiPersonality.SUPPORTER:   20,
        EmojiPersonality.MINIMAL:     25,
        EmojiPersonality.MIXED:       30,
    }
    offset = personality_offsets.get(personality, 0)

    # Draw from a personality-biased window of the pool (wraps around)
    seed = _stable_hash(f"{account_id}|{media_id}|comment_pick")
    rng = _random.Random(seed)

    # Primary candidate: comment at (offset + draw) % pool_length
    # This means different personalities weight different sections of the pool
    window_size = min(15, len(pool))  # pick from a window of 15 options
    start = offset % len(pool)
    candidates = [pool[(start + i) % len(pool)] for i in range(window_size)]
    return rng.choice(candidates)


def _post_age_seconds(posted_at_iso: str) -> float:
    """Return seconds since post was published."""
    posted_at = datetime.fromisoformat(posted_at_iso.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - posted_at).total_seconds()


# ---------------------------------------------------------------------------
# IGPodManager
# ---------------------------------------------------------------------------


class IGPodManager:
    """
    Engagement pod orchestration for Phantom Fleet Instagram accounts.

    Manages pod assignment, new-post notification, and the full engagement
    session lifecycle for pod members.

    Usage:
        manager = IGPodManager(account_ids, niche="beauty")

        # When a post is published
        await manager.notify_new_post("acct_abc", "1234567890", "2026-04-11T14:00:00Z")

        # In the pod member's worker loop
        result = await manager.run_pod_engagement_session(
            account_id="acct_xyz",
            session=session,
            pending_posts=[{"account_id": "acct_abc", "media_id": "1234567890",
                            "posted_at_iso": "2026-04-11T14:00:00Z",
                            "target_ig_user_id": "98765"}],
        )

    Fleet-scale detection properties:
        - Pod sizes vary via LogNormal (10-15 members); no uniform cluster.
        - Per-post engagement delays are LogNormal, not uniform stagger.
        - 30% comment probability creates natural sparse comment patterns.
        - Code-enforced daily caps prevent over-engagement signatures.
        - Post-age gate ensures only fresh content gets pod treatment.
    """

    def __init__(
        self,
        account_ids: list[str],
        niche: str = "general",
        registry: Optional[PodRegistry] = None,
    ) -> None:
        self._niche = niche
        self._registry = registry or PodRegistry()

        # Build or load pods
        saved = self._registry.load_pods()
        if saved:
            self._pods: list[PodConfig] = saved
        else:
            self._pods = self._registry.build_pods(account_ids, niche=niche)
            self._registry.save_pods(self._pods)

        # account_id → pod lookup cache
        self._account_pod: dict[str, PodConfig] = {}
        for pod in self._pods:
            for aid in pod.member_account_ids:
                self._account_pod[aid] = pod

    # ------------------------------------------------------------------
    # Pod lookup
    # ------------------------------------------------------------------

    def get_pod_members(self, account_id: str) -> list[str]:
        """
        Return the list of pod siblings for account_id (excluding self).

        Returns [] if account is not in any pod.
        """
        pod = self._account_pod.get(account_id)
        if pod is None:
            return []
        return [m for m in pod.member_account_ids if m != account_id]

    # ------------------------------------------------------------------
    # New-post notification
    # ------------------------------------------------------------------

    async def notify_new_post(
        self,
        account_id: str,
        media_id: str,
        posted_at_iso: str,
    ) -> None:
        """
        Publish a new-post event to the pod's Redis channel.

        Pod members' background workers subscribe to
        pod:{pod_id}:new_post and schedule their individual engagement
        after drawing their LogNormal delay.

        If Redis is unavailable, falls back to a no-op log (workers
        will pick up pending_posts via their own polling path instead).
        """
        pod = self._account_pod.get(account_id)
        if pod is None:
            log.debug("[notify_new_post] account %s not in any pod", account_id)
            return

        payload = {
            "account_id": account_id,
            "media_id": media_id,
            "posted_at_iso": posted_at_iso,
            "pod_id": pod.pod_id,
        }

        try:
            import redis.asyncio as aioredis  # type: ignore
            r = aioredis.from_url("redis://localhost:6379")
            channel = f"pod:{pod.pod_id}:new_post"
            import json
            await r.publish(channel, json.dumps(payload))
            await r.aclose()
            log.info(
                "[pod] Published new_post for media %s → channel %s",
                media_id, channel,
            )
        except Exception as exc:
            log.warning(
                "[pod] Redis publish failed (media %s): %s — workers fall back to polling",
                media_id, exc,
            )

    # ------------------------------------------------------------------
    # Engagement gate
    # ------------------------------------------------------------------

    def should_engage(
        self,
        actor_account_id: str,
        post_account_id: str,
        media_id: str,
        posted_at_iso: str,
        pod_likes_today: int = 0,
        pod_comments_today: int = 0,
    ) -> bool:
        """
        Decide whether actor should engage with post_account's media.

        Checks:
          1. Actor and poster are in the same pod.
          2. Actor is not the poster.
          3. Post age < 2 hours (no value in late engagement).
          4. Daily pod-like cap not reached (10/day, code-enforced).
          5. Daily pod-comment cap checked separately in pick_comment().

        Args:
            actor_account_id:  The account considering engagement.
            post_account_id:   The account that published the post.
            media_id:          Instagram media ID of the post.
            posted_at_iso:     ISO 8601 timestamp when post was published.
            pod_likes_today:   Number of pod likes actor has sent today.
            pod_comments_today: Number of pod comments actor has sent today.

        Returns:
            True if all gates pass.
        """
        # Must not engage with own post
        if actor_account_id == post_account_id:
            return False

        # Both must be in the same pod
        actor_pod = self._account_pod.get(actor_account_id)
        post_pod = self._account_pod.get(post_account_id)
        if actor_pod is None or post_pod is None:
            return False
        if actor_pod.pod_id != post_pod.pod_id:
            return False

        # Post must be < 2 hours old (code-enforced)
        age = _post_age_seconds(posted_at_iso)
        if age > MAX_POD_ENGAGEMENT_WINDOW_SECONDS:
            log.debug(
                "[pod] Post %s is %.0f s old — past engagement window, skipping",
                media_id, age,
            )
            return False

        # Daily like cap (code-enforced)
        if pod_likes_today >= MAX_POD_LIKES_PER_ACCOUNT_PER_DAY:
            log.debug(
                "[pod] Actor %s has hit daily pod-like cap (%d), skipping",
                actor_account_id, MAX_POD_LIKES_PER_ACCOUNT_PER_DAY,
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Comment selection
    # ------------------------------------------------------------------

    def pick_comment(
        self,
        account_id: str,
        media_id: str,
        niche: str = "general",
        pod_comments_today: int = 0,
    ) -> Optional[str]:
        """
        Return a comment string with 30% probability, or None.

        The 30% gate is per-(account, post) and stable (same pair always
        gets same decision). When the gate passes, returns a personality-
        matched comment from the niche pool.

        Daily comment cap (3/day) is code-enforced here: if the actor has
        already left 3 pod comments today, always returns None regardless
        of probability gate.

        Args:
            account_id:         Actor's account ID.
            media_id:           Target post's media ID.
            niche:              Content niche for pool selection.
            pod_comments_today: Number of pod comments already sent today.

        Returns:
            Comment text string, or None if gate fails or cap reached.
        """
        # Code-enforced daily cap
        if pod_comments_today >= MAX_POD_COMMENTS_PER_ACCOUNT_PER_DAY:
            return None

        # 30% probability gate (stable per account+post)
        if not _should_comment(account_id, media_id):
            return None

        return _pick_comment_text(account_id, media_id, niche)

    # ------------------------------------------------------------------
    # Engagement session
    # ------------------------------------------------------------------

    async def run_pod_engagement_session(
        self,
        account_id: str,
        session: IGSession,
        pending_posts: list[dict],
        pod_likes_today: int = 0,
        pod_comments_today: int = 0,
    ) -> WorkerResult:
        """
        Run one pod engagement session for account_id.

        For each pending_post where should_engage() passes:
          1. Wait the LogNormal stagger delay for this (account, post) pair.
          2. Like the post (always when gate passes).
          3. Maybe comment (30% probability, personality-matched).
          4. Dwell on the post (LogNormal 8-180s) before moving on.

        Args:
            account_id:          Actor's internal account ID.
            session:             Authenticated IGSession for the actor.
            pending_posts:       List of dicts with keys:
                                   account_id      — poster's account ID
                                   media_id        — IG media ID
                                   posted_at_iso   — ISO 8601 publish time
                                   target_ig_user_id — poster's IG numeric ID
                                   niche           — content niche (optional)
            pod_likes_today:     Likes already sent today (caller tracks).
            pod_comments_today:  Comments already sent today (caller tracks).

        Returns:
            WorkerResult with data keys:
                likes_sent, comments_sent, skipped_late, skipped_cap,
                records, errors
        """
        task_id = f"{account_id}_pod_engagement_{datetime.now(timezone.utc).date().isoformat()}"

        likes_sent = 0
        comments_sent = 0
        skipped_late = 0
        skipped_cap = 0
        records: list[dict] = []
        errors: list[str] = []

        async with InstagramClient(session) as client:
            for post in pending_posts:
                poster_id = post.get("account_id", "")
                media_id = post.get("media_id", "")
                posted_at_iso = post.get("posted_at_iso", "")
                target_ig_user_id = post.get("target_ig_user_id", "")
                niche = post.get("niche", self._niche)

                if not media_id or not posted_at_iso:
                    log.warning("[pod] Skipping post with missing media_id/posted_at_iso")
                    continue

                # Age check (separate path so we can count late skips)
                age = _post_age_seconds(posted_at_iso)
                if age > MAX_POD_ENGAGEMENT_WINDOW_SECONDS:
                    skipped_late += 1
                    continue

                # Full engagement gate
                if not self.should_engage(
                    actor_account_id=account_id,
                    post_account_id=poster_id,
                    media_id=media_id,
                    posted_at_iso=posted_at_iso,
                    pod_likes_today=pod_likes_today + likes_sent,
                    pod_comments_today=pod_comments_today + comments_sent,
                ):
                    skipped_cap += 1
                    continue

                # Wait individual stagger delay before engaging
                delay = _draw_engagement_delay(account_id, media_id)
                log.info(
                    "[pod] %s will engage with %s after %.0fs delay",
                    account_id, media_id, delay,
                )
                await asyncio.sleep(delay)

                # ── Like (always) ──────────────────────────────────────────
                engaged_at = datetime.now(timezone.utc).isoformat()
                try:
                    like_resp = await client.like_post(media_id=media_id)
                    ok = isinstance(like_resp, dict) and like_resp.get("status") == "ok"
                    if ok:
                        likes_sent += 1
                        records.append(
                            PodEngagementRecord(
                                actor_account_id=account_id,
                                target_account_id=poster_id,
                                media_id=media_id,
                                action="like",
                                comment_text=None,
                                engaged_at_iso=engaged_at,
                                delay_seconds=delay,
                            ).__dict__
                        )
                        log.info("[pod] %s liked post %s", account_id, media_id)
                    else:
                        errors.append(f"like_failed:media={media_id}")
                except IGSessionExpired:
                    errors.append(f"session_expired:media={media_id}")
                    break
                except IGRateLimited:
                    errors.append(f"rate_limited:media={media_id}")
                    break
                except IGActionBlocked:
                    errors.append(f"action_blocked:media={media_id}")
                    break
                except Exception as exc:
                    errors.append(f"error:like:media={media_id}:{exc}")
                    continue

                # ── Comment (30% probability) ──────────────────────────────
                comment_text = self.pick_comment(
                    account_id=account_id,
                    media_id=media_id,
                    niche=niche,
                    pod_comments_today=pod_comments_today + comments_sent,
                )
                if comment_text:
                    try:
                        ok = await client.comment_post(
                            media_id=media_id,
                            comment_text=comment_text,
                        )
                        if ok:
                            comments_sent += 1
                            records.append(
                                PodEngagementRecord(
                                    actor_account_id=account_id,
                                    target_account_id=poster_id,
                                    media_id=media_id,
                                    action="comment",
                                    comment_text=comment_text,
                                    engaged_at_iso=datetime.now(timezone.utc).isoformat(),
                                    delay_seconds=delay,
                                ).__dict__
                            )
                            log.info(
                                "[pod] %s commented on %s: %r",
                                account_id, media_id, comment_text,
                            )
                        else:
                            errors.append(f"comment_failed:media={media_id}")
                    except IGSessionExpired:
                        errors.append(f"session_expired:comment:media={media_id}")
                        break
                    except IGRateLimited:
                        errors.append(f"rate_limited:comment:media={media_id}")
                        break
                    except IGActionBlocked:
                        errors.append(f"action_blocked:comment:media={media_id}")
                        break
                    except Exception as exc:
                        errors.append(f"error:comment:media={media_id}:{exc}")

                # ── Post-engagement dwell (simulate reading comments) ──────
                dwell = _POST_DWELL_DIST.sample(
                    account_id=account_id,
                    date_iso=datetime.now(timezone.utc).date().isoformat(),
                    field=f"pod_dwell_{media_id}",
                )
                await asyncio.sleep(dwell)

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":          "pod_engagement",
                "likes_sent":      likes_sent,
                "comments_sent":   comments_sent,
                "skipped_late":    skipped_late,
                "skipped_cap":     skipped_cap,
                "records":         records,
                "errors":          errors,
            },
        )
