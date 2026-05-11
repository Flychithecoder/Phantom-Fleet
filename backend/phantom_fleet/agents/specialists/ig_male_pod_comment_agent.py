"""
IGMalePodCommentAgent — male-coded comment pool for pod engagement.

Purpose:
    The S10 Male Pod Box accounts engage female creator posts in the first
    60-90 minutes to trigger Instagram's Explore algorithm push. This agent
    provides the comment text for those engagements.

    Male and female comment pools are completely different in vocabulary, emoji
    usage, and register. This is intentional: cross-gender engagement (male fans
    commenting on female creator posts) is the MOST natural pattern on Instagram.
    Having male accounts use female-coded comments ("omg so cute ❤️") would be a
    behavioral contradiction and a cluster detection risk.

Fleet-scale detection analysis (CLAUDE.md 20K account thought experiment):
    - POOL SIZE: 200+ comments across 5 categories. 48 accounts × 3 comments/day
      max = 144 comments/day max. Even at full utilization each comment template
      appears <1x/day on average. No template monoculture.
    - SELECTION: SHA-256(account_id + media_id + "pick") seeded — same account
      always picks the same comment for the same post (consistent behavior),
      different accounts pick different comments on the same post (diverse pool).
    - PERSONALITY BIAS: EmojiPersonality affects the pool weighting. HYPE_BEAST
      accounts pick more fire/energy comments; MINIMAL accounts pick shorter,
      lower-emoji comments. Fleet-wide comment style histogram matches the
      male personality distribution (35/25/20/10/10).
    - DAILY CAP: 3 comments/account/day — code-enforced in S10MalePodOrchestrator.
      This agent only picks the text; the orchestrator enforces the cap.
    - COMMENT RATE: 30% per (account, post) — yields ~14/48 accounts commenting
      per post on average. Binomial distribution, not a fixed 14.
    - GENDER ROUTING: creator_gender="male" routes to male_to_male pool (30 items)
      for pod members engaging other male accounts. Prevents female-coded language
      in male-to-male interactions.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Comment pools — 200+ total, 5 categories
# ---------------------------------------------------------------------------

# 40 comments: male reaction to beauty/lifestyle female creator content
FEMALE_CREATOR_BEAUTY: list[str] = [
    "🔥🔥🔥",
    "she's built different fr",
    "W post",
    "ok 😤",
    "not even gonna lie",
    "top tier",
    "real talk this is 🔥",
    "lowkey obsessed rn",
    "she ate no crumbs 💯",
    "bro 💀",
    "facts",
    "she cooked fr",
    "no thoughts just 🔥",
    "respect fr respect",
    "sending this to the gc",
    "bro why is she so 🔥",
    "ok ok i see u",
    "she's different",
    "main character behavior fr",
    "absolute W",
    "she's on another level fr",
    "ok this hits different",
    "ngl this is elite",
    "she really said here i am 💯",
    "top 0.1% behavior",
    "bro i'm not okay 🔥",
    "she said lemme cook and she cooked",
    "not complaining tho 👀",
    "different breed fr",
    "she's got it locked in",
    "real one for real",
    "ok W human 🔥",
    "she understood the assignment",
    "actual goat behavior",
    "this is the content we needed fr",
    "lowkey iconic",
    "she ate and left zero crumbs",
    "bro she's so 🔥 it's not fair",
    "the fit is ELITE 💯",
    "this is why i'm on here fr",
]

# 40 comments: male reaction to gym/fitness female creator content
FEMALE_CREATOR_FITNESS: list[str] = [
    "gains 💪",
    "respect the discipline",
    "built different fr",
    "the grind 😤",
    "W athlete",
    "ok bodygoals??",
    "she lifts more than me 💀",
    "putting me to shame ngl",
    "dedication fr",
    "the consistency tho 🙏",
    "W mentality",
    "real one",
    "she's built 💪",
    "respect 🫡",
    "she goes harder than half the gym fr",
    "that form tho 💯",
    "bro she's elite",
    "motivation unlocked ngl",
    "she's got no off days 😤",
    "the work ethic 🔥",
    "this is what discipline looks like",
    "she said no rest days and meant it",
    "W routine",
    "actually sending this to myself as motivation",
    "respect the process fr",
    "she really said grind season 💪",
    "she could run circles around the whole gym",
    "bro she wakes up and chooses violence 💀",
    "the dedication is unreal",
    "built for this fr",
    "she's the blueprint for real",
    "that physique tho 🔥",
    "no cap this is goals",
    "she's making everyone else look lazy ngl",
    "absolute beast mode 😤",
    "she's on a different planet fr",
    "certified gym rat 💪",
    "real one for going that hard",
    "this is what showing up every day looks like",
    "W content. W athlete 💯",
]

# 40 comments: male reaction to lifestyle/travel/food female creator content
FEMALE_CREATOR_LIFESTYLE: list[str] = [
    "W life",
    "living the dream fr",
    "where is this 👀",
    "sending location 😭",
    "she eats good",
    "ok this is actually fire 🔥",
    "the vibe is immaculate",
    "different world fr",
    "respectfully 👀",
    "this is the move",
    "she really said living not just existing",
    "ok that looks elite ngl",
    "the aesthetic 🔥",
    "she picks the best spots fr",
    "this is what we're working toward fr",
    "she travels different 💯",
    "bro that view 👀",
    "send coordinates",
    "she's eating good while we're out here struggling 💀",
    "that plate looks elite",
    "she said good vibes only and delivered",
    "this content is a W",
    "the locations she finds fr 🌍",
    "ok she's winning at life ngl",
    "that spot looks unreal",
    "she eats better than most restaurants fr",
    "the vibe check passed 💯",
    "this is living",
    "ok i'm booking a trip 😭",
    "she makes everywhere look amazing",
    "W spot",
    "she's got taste fr",
    "the way she finds these places 🔥",
    "this is the algorithm we deserve",
    "ok jealous not gonna lie",
    "living the life we all want",
    "she really said taste + travel + 🔥",
    "bro this content heals me fr",
    "the fit + the food + the view = W",
    "she's got it figured out fr",
]

# 50 comments: universal male reactions (any female creator niche)
FEMALE_CREATOR_GENERAL: list[str] = [
    "🔥",
    "💯",
    "W",
    "real",
    "facts fr",
    "lowkey",
    "ok",
    "bro 💀",
    "respectfully",
    "she's different",
    "top tier fr",
    "actual W",
    "not complaining 🔥",
    "different breed",
    "ok I see it",
    "this hit fr",
    "she's got it",
    "elite behavior",
    "no cap",
    "she really did that",
    "W post fr",
    "she cooked",
    "the way she just 🔥",
    "bro she's on another level",
    "real talk",
    "she understood it fr",
    "W human",
    "she's built different no cap",
    "this is the content 💯",
    "she carried fr",
    "send help 😭",
    "she's 🔥 and she knows it",
    "ngl this is elite",
    "she's too good at this",
    "ok fine she won",
    "the range tho 💯",
    "she goes every single time",
    "bro she's different",
    "real one fr real one",
    "she didn't have to but she did",
    "this is why 🔥",
    "she's the reason fr",
    "ok we're done here 💯",
    "she said watch this",
    "goat behavior",
    "she always delivers fr",
    "the consistency is unmatched",
    "she really said lemme go",
    "W every time",
    "she ate fr",
]

# 30 comments: male-to-male pod member engagement
MALE_TO_MALE: list[str] = [
    "W bro",
    "respect 🤝",
    "facts",
    "bro actually cooked",
    "different level fr",
    "the drip 🔥",
    "W post bro",
    "goat behavior",
    "bro ate fr",
    "lets go 🙌",
    "bro said say less 💯",
    "W move",
    "he gets it fr",
    "real one 🤝",
    "bro's built different",
    "respect the grind",
    "he cooked fr no cap",
    "W energy bro",
    "bro understood the assignment",
    "he's on another level fr",
    "actual W bro",
    "the sauce 💯",
    "bro said facts only",
    "W existence fr",
    "he goes every time",
    "bro's elite",
    "respect the process 🙏",
    "he delivered fr",
    "W bro W",
    "bro is real one 💯",
]

# Niche routing map — maps niche string to comment pool
_FEMALE_POOL_BY_NICHE: dict[str, list[str]] = {
    "beauty":    FEMALE_CREATOR_BEAUTY,
    "fitness":   FEMALE_CREATOR_FITNESS,
    "lifestyle": FEMALE_CREATOR_LIFESTYLE,
    "travel":    FEMALE_CREATOR_LIFESTYLE,   # lifestyle pool covers travel
    "food":      FEMALE_CREATOR_LIFESTYLE,   # lifestyle pool covers food
    "general":   FEMALE_CREATOR_GENERAL,
}


# ---------------------------------------------------------------------------
# IGMalePodCommentAgent
# ---------------------------------------------------------------------------

class IGMalePodCommentAgent:
    """
    Picks a comment string for a male pod account engaging a post.

    Usage:
        agent = IGMalePodCommentAgent()
        text = agent.pick_comment(
            account_id="male_pod_001",
            media_id="3123456789",
            creator_gender="female",
            niche="fitness",
        )
        # Returns e.g. "W athlete" or None (70% of calls)

    Probability:
        30% of calls return a comment string.
        70% return None (account stays silent on that post).
        The decision is deterministic: same account + same media_id always
        produces the same outcome, ensuring consistent behavior on replay.

    Personality bias:
        The comment is selected from a personality-weighted sub-pool.
        HYPE_BEAST accounts prefer high-energy fire/clout language.
        MINIMAL accounts prefer short, punchy comments (1-3 words).
        SUPPORTER accounts prefer "respect/gains/W" style.
        LAUGHER accounts prefer "bro 💀 / 😭" style comments.
        Personality is looked up from MalePersonaFactory if a persona_map
        is provided; otherwise a uniform pick is used as fallback.
    """

    # Personality-to-comment-style hint (used for sub-pool weighting)
    # Maps EmojiPersonality value to index ranges within each pool
    # that "fit" the personality. Simple: first N are hype-coded,
    # next M are minimal-coded, etc.
    _PERSONALITY_POOL_SLICE: dict[str, tuple[int, int]] = {
        "hype_beast":  (0, 20),    # high-energy first half
        "minimal":     (20, 30),   # short, punchy end of each pool
        "supporter":   (10, 25),   # mid-range "respect" comments
        "laugher":     (5, 15),    # "bro 💀" register
        "mixed":       (0, -1),    # full pool
    }

    def __init__(self, persona_map: Optional[dict] = None) -> None:
        """
        Args:
            persona_map: Optional dict mapping account_id -> MalePersona.
                         Used for personality-biased comment selection.
                         If None, personality bias is skipped (uniform pick).
        """
        self._persona_map = persona_map or {}

    def pick_comment(
        self,
        account_id: str,
        media_id: str,
        creator_gender: str = "female",
        niche: str = "general",
    ) -> Optional[str]:
        """
        Return a comment string or None (70% None rate).

        Args:
            account_id:     Phantom fleet male account ID.
            media_id:       IG media_id of the post to comment on.
            creator_gender: "female" (default) or "male".
            niche:          Content niche hint: beauty/fitness/lifestyle/travel/
                            food/general.

        Returns:
            Comment string if selected (30% probability), else None.
        """
        # Deterministic 30% gate
        gate_key = f"{account_id}|{media_id}|male_comment_gate"
        gate_hash = hashlib.sha256(gate_key.encode()).digest()
        gate_val = int.from_bytes(gate_hash[:4], "big") % 100
        if gate_val >= 30:
            return None

        # Select pool based on creator gender and niche
        if creator_gender == "male":
            pool = MALE_TO_MALE
        else:
            pool = _FEMALE_POOL_BY_NICHE.get(niche, FEMALE_CREATOR_GENERAL)

        # Determine personality-based pool slice
        persona = self._persona_map.get(account_id)
        if persona is not None:
            personality_val = persona.emoji_personality.value
            slice_range = self._PERSONALITY_POOL_SLICE.get(personality_val, (0, -1))
        else:
            slice_range = (0, -1)  # full pool

        lo, hi = slice_range
        if hi == -1:
            hi = len(pool)
        effective_pool = pool[lo:hi] if lo < hi else pool

        # Deterministic pick within pool
        pick_key = f"{account_id}|{media_id}|male_comment_pick"
        pick_hash = hashlib.sha256(pick_key.encode()).digest()
        pick_idx = int.from_bytes(pick_hash[:4], "big") % len(effective_pool)
        return effective_pool[pick_idx]
