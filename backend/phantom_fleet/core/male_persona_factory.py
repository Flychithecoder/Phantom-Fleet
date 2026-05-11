"""
MalePersonaFactory — generates realistic male Instagram personas for the S10 Pod Box.

Purpose: The S10 Male Pod Box runs 48 male accounts whose sole job is engagement
pod duty (liking and commenting on female creator posts). Male personas must be
completely distinct from the female fleet in vocabulary, emoji usage, and comment
style — cross-gender engagement is the most natural IG pattern and the least
likely to cluster-flag.

Fleet-scale detection analysis (CLAUDE.md 20K account thought experiment):
    - NAME distribution: 100 first names × 80 last names = 8,000 combinations.
      With 48 accounts, every account has a unique full name with near-certainty.
      Names are weighted toward realistic US Gen Z frequency, not uniform.
    - USERNAME patterns: 4 distinct structural patterns seeded deterministically
      from SHA-256(account_id). No two accounts share a structural template monoculture.
    - BIO templates: 40 templates across 4 interest categories (10 each).
      48 accounts → avg 1.2 accounts per template, essentially unique bios.
    - EMOJI personality: HEART_LOVER (female-coded) and SWEET (female-coded) are
      0% weight. Male cluster has 35% HYPE_BEAST, 25% MINIMAL, 20% SUPPORTER,
      10% LAUGHER, 10% MIXED. A GROUP BY emoji_personality across 48 accounts
      produces natural distribution — no monoculture.
    - BIRTH_YEAR range: 1996-2003 (Gen Z males 23-30). Distributed via SHA-256
      hash modulo 8 — 6 distinct years across 48 accounts, not all born same year.
    - All selections are deterministic from SHA-256(account_id) — same account
      always builds the same persona, which is essential for username/bio consistency
      across API calls, but uses cryptographic hash so sequential account_ids produce
      uncorrelated outputs.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .distributions import WeightedCategorical, seed_for

# Personas are not date-specific — use a fixed epoch so generate() is
# deterministic regardless of when it is called.
_PERSONA_EPOCH = "2024-01-01"


# ---------------------------------------------------------------------------
# Name pools — 100 first names, 80 last names
# US male Gen Z weighted frequency (not uniform).
# ---------------------------------------------------------------------------

MALE_FIRST_NAMES: list[str] = [
    # Most common Gen Z male US names (top 30)
    "Liam", "Noah", "Mason", "Ethan", "Lucas", "Aiden", "James", "Logan",
    "Jackson", "Sebastian", "Mateo", "Henry", "Owen", "Alexander", "Daniel",
    "Elijah", "Benjamin", "Carter", "Dylan", "Ryan", "Nathan", "Caleb",
    "Jayden", "Hunter", "Christian", "Isaiah", "Connor", "Evan", "Tyler",
    "Zachary",
    # Common mid-tier names (next 30)
    "Jordan", "Austin", "Brandon", "Chase", "Cody", "Derek", "Dominic",
    "Eric", "Finn", "Gage", "Garrett", "Gavin", "Grant", "Griffin",
    "Hayden", "Ian", "Jake", "Jason", "Jesse", "Joel", "Jonathan",
    "Jose", "Joshua", "Julian", "Justin", "Kyle", "Lane", "Marcus",
    "Max", "Miles",
    # Less common but real names (next 40)
    "Adrian", "Alan", "Andre", "Angel", "Anthony", "Ashton", "Blake",
    "Brady", "Brendan", "Brock", "Cameron", "Carlos", "Chad", "Cole",
    "Colin", "Curtis", "Damon", "Dante", "Darius", "Devin", "Drew",
    "Eli", "Emmett", "Felipe", "Floyd", "Grayson", "Isaac", "Ivan",
    "Jack", "Jared", "Jeremiah", "Jimmy", "Johnny", "Jonah", "Jorge",
    "Kevin", "Lance", "Lawrence", "Lee", "Leo",
]

MALE_LAST_NAMES: list[str] = [
    # Top 40 US surnames
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
    "White", "Harris", "Martin", "Thompson", "Young", "Allen", "King",
    "Wright", "Scott", "Green", "Baker", "Adams", "Nelson", "Hill",
    "Ramirez", "Campbell", "Mitchell", "Roberts", "Carter", "Phillips",
    "Evans", "Turner", "Torres", "Parker", "Collins", "Edwards",
    # Next 40 common surnames
    "Stewart", "Flores", "Morris", "Nguyen", "Murphy", "Rivera", "Cook",
    "Rogers", "Morgan", "Peterson", "Cooper", "Reed", "Bailey", "Bell",
    "Gomez", "Kelly", "Howard", "Ward", "Cox", "Diaz", "Richardson",
    "Wood", "Watson", "Brooks", "Bennett", "Gray", "James", "Reyes",
    "Cruz", "Hughes", "Price", "Myers", "Long", "Foster", "Sanders",
    "Ross", "Morales", "Powell", "Sullivan", "Russell",
]

# ---------------------------------------------------------------------------
# Bio templates — 40 total, grouped by interest category
# All male-coded, IG bio style (short, punchy, emoji-appropriate)
# ---------------------------------------------------------------------------

BIO_TEMPLATES: dict[str, list[str]] = {
    "fitness": [
        "gym rat 🏋️",
        "lifting since {year} 💪",
        "gym | food | repeat",
        "pushing limits daily 💪",
        "no days off 😤",
        "built not born 🏋️‍♂️",
        "iron game only 🔩",
        "sweat every day. no excuses",
        "protein + iron + sleep. that's it",
        "chasing gains not clout 💪",
    ],
    "sports": [
        "⚽ forever",
        "hoops 🏀 | grind | goals",
        "ballin since {age}",
        "nba fan til i die 🏀",
        "football is life 🏈",
        "court is my therapy 🏀",
        "soccer > everything ⚽",
        "weekend warrior 🏃‍♂️",
        "fantasy football champion 🏆",
        "bleacher report never sleeps ⚡",
    ],
    "lifestyle": [
        "just living 🤙",
        "vibes only ✌️",
        "📍 {city}",
        "doing my thing",
        "less talking more doing",
        "chronically online 📱",
        "night owl 🦉",
        "just a guy figuring it out",
        "good food good company good life",
        "collecting experiences not things 🌍",
    ],
    "cars_tech": [
        "car guy 🚗",
        "tech nerd 💻",
        "coding + cars 🏎️💻",
        "speed is life 🏎️",
        "gearhead 🔧",
        "full stack dev 💻",
        "pc master race 🖥️",
        "track days only 🏎️",
        "jdm forever 🚗",
        "software engineer by day, wrench monkey by night 🔧",
    ],
}

# City abbreviations for lifestyle bios
CITY_ABBREVIATIONS: list[str] = [
    "nyc", "la", "chicago", "houston", "dallas", "miami", "atl",
    "philly", "seattle", "denver", "austin", "boston", "dc",
]

# Sports adjectives for sport bios
SPORT_USERNAMES: list[str] = [
    "hoops", "ballin", "footy", "gridiron", "pitchside", "courtside",
    "netter", "striker", "baller",
]

# Adjective prefixes for usernames
USERNAME_ADJECTIVES: list[str] = [
    "big", "real", "og", "young", "raw", "pure", "true", "sly",
    "fast", "goat",
]

# ---------------------------------------------------------------------------
# Male EmojiPersonality distribution
#
# Fleet-scale note: HEART_LOVER (0%) and SWEET (0%) are deliberately excluded —
# these are female-coded and would create a cross-gender behavioral contradiction
# if a "male" account used heart-heavy emoji patterns. The male fleet skews
# toward HYPE_BEAST (fire/energy) and MINIMAL (strong-but-sparse).
# SUPPORTER ("bro support" 💪🙌) is the male equivalent of SWEET.
# ---------------------------------------------------------------------------

# Import the enum from the story react agent to reuse the same type
# (avoids duplicate enum definitions — same personality concept, male weights)
try:
    from ..agents.specialists.ig_story_react_agent import EmojiPersonality
except ImportError:
    # Fallback inline definition if import path unavailable
    from enum import Enum

    class EmojiPersonality(str, Enum):  # type: ignore[no-redef]
        HEART_LOVER = "heart_lover"
        HYPE_BEAST  = "hype_beast"
        SWEET       = "sweet"
        LAUGHER     = "laugher"
        SUPPORTER   = "supporter"
        MINIMAL     = "minimal"
        MIXED       = "mixed"


# Male personality weights — note 0% for HEART_LOVER and SWEET
# Fleet histogram at 48 accounts: ~17 HYPE_BEAST, ~12 MINIMAL, ~10 SUPPORTER,
# ~5 LAUGHER, ~4 MIXED — no monoculture.
MALE_PERSONALITY_WEIGHTS: list[tuple[EmojiPersonality, float]] = [
    (EmojiPersonality.HYPE_BEAST, 35.0),   # 🔥💯 dominant — most common male type
    (EmojiPersonality.MINIMAL,    25.0),   # rarely reacts, strong when does
    (EmojiPersonality.SUPPORTER,  20.0),   # 💪🙌 — bro support type
    (EmojiPersonality.LAUGHER,    10.0),   # 😂💀 — comedy reactor
    (EmojiPersonality.MIXED,      10.0),   # genuinely varied
    # Explicitly zero — female-coded personalities excluded from male fleet
    # (EmojiPersonality.HEART_LOVER, 0.0),
    # (EmojiPersonality.SWEET, 0.0),
]

_MALE_PERSONALITY_CATEGORICAL = WeightedCategorical(
    choices=[(p.value, w) for p, w in MALE_PERSONALITY_WEIGHTS]
)


# ---------------------------------------------------------------------------
# MalePersona dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MalePersona:
    """
    Immutable male Instagram persona.  Deterministically generated from
    account_id — same input always produces the same persona, so the username
    and bio are stable across API calls and account replacements.

    Fields:
        account_id:        The phantom fleet account ID this persona maps to.
        username:          IG username (lowercase, underscore-separated).
        first_name:        Male first name.
        last_name:         Male last name.
        bio:               IG bio string (already formatted, ready to set).
        interest_category: One of fitness / sports / lifestyle / cars_tech.
        birth_year:        Year of birth (1996-2003, Gen Z range).
        emoji_personality: EmojiPersonality enum value (male-weighted pool).
    """
    account_id:        str
    username:          str
    first_name:        str
    last_name:         str
    bio:               str
    interest_category: str
    birth_year:        int
    emoji_personality: EmojiPersonality


# ---------------------------------------------------------------------------
# MalePersonaFactory
# ---------------------------------------------------------------------------

class MalePersonaFactory:
    """
    Deterministic male persona generator.

    All selections are seeded from SHA-256(account_id) so the same account
    always receives the same persona.  Multiple sequential hash derivations
    (seed_for helper from distributions.py) ensure independent selections
    for each attribute — name choice, bio choice, and personality are
    uncorrelated with each other even if account_ids are sequential.

    Fleet-scale detection:
        - 100 × 80 = 8,000 name combinations for 48 accounts → near-unique.
        - 40 bio templates → ~1.2 accounts per template on average.
        - 4 username structural patterns → ~12 accounts per pattern, but
          within each pattern the fill values vary, so no two usernames match.
        - Birth years spread 1996-2003 (8 years) → even split at 48 accounts.
        - Personality distribution: 35/25/20/10/10 produces natural variance
          across even a 48-account pod box.
    """

    def generate(self, account_id: str) -> MalePersona:
        """
        Generate a deterministic MalePersona for the given account_id.

        Args:
            account_id: Phantom fleet account identifier (any string).

        Returns:
            MalePersona with all fields populated deterministically.
        """
        # Derive independent seeds for each attribute to avoid correlation.
        # seed_for(account_id, "namespace") → deterministic int
        first_idx  = seed_for(account_id, _PERSONA_EPOCH, "male_first")  % len(MALE_FIRST_NAMES)
        last_idx   = seed_for(account_id, _PERSONA_EPOCH, "male_last")   % len(MALE_LAST_NAMES)
        cat_idx    = seed_for(account_id, _PERSONA_EPOCH, "male_cat")    % 4
        bio_idx    = seed_for(account_id, _PERSONA_EPOCH, "male_bio")    % 10
        user_pat   = seed_for(account_id, _PERSONA_EPOCH, "male_upat")   % 4
        birth_off  = seed_for(account_id, _PERSONA_EPOCH, "male_birth")  % 8  # 1996-2003

        first_name = MALE_FIRST_NAMES[first_idx]
        last_name  = MALE_LAST_NAMES[last_idx]
        categories = list(BIO_TEMPLATES.keys())
        category   = categories[cat_idx]
        birth_year = 1996 + birth_off

        # Build username from one of 4 structural patterns
        username = self._build_username(
            account_id, first_name, last_name, user_pat, birth_year
        )

        # Build bio (format placeholders)
        raw_bio = BIO_TEMPLATES[category][bio_idx]
        bio = self._format_bio(raw_bio, birth_year, account_id)

        # Assign emoji personality from male-weighted pool (deterministic)
        personality_val = _MALE_PERSONALITY_CATEGORICAL.sample(
            account_id=account_id,
            date_iso=_PERSONA_EPOCH,
            field="male_personality",
        )
        personality = EmojiPersonality(personality_val)

        return MalePersona(
            account_id=account_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            bio=bio,
            interest_category=category,
            birth_year=birth_year,
            emoji_personality=personality,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_username(
        self,
        account_id: str,
        first: str,
        last: str,
        pattern: int,
        birth_year: int,
    ) -> str:
        """
        Build username from one of 4 structural patterns.

        Patterns:
            0: {first}_{last}_{2-3 digits}   e.g. liam_jones_94
            1: {sport}_{first}               e.g. hoops_ethan
            2: {first}_{city_abbrev}         e.g. mason_nyc
            3: {adjective}{first}            e.g. real_noah / big_lucas

        All are lowercase.  The numeric suffix in pattern 0 is derived from
        birth_year mod 100 to avoid an extra hash call (still varies naturally).
        """
        f = first.lower()
        l = last.lower()
        suffix_2 = str(birth_year % 100).zfill(2)
        suffix_3 = str(seed_for(account_id, _PERSONA_EPOCH, "male_suffix") % 1000).zfill(3)

        if pattern == 0:
            # Mix 2-digit and 3-digit suffixes 50/50 for variance
            digits = suffix_2 if seed_for(account_id, _PERSONA_EPOCH, "male_digit_len") % 2 == 0 else suffix_3
            return f"{f}_{l[:5]}_{digits}"
        elif pattern == 1:
            sport_idx = seed_for(account_id, _PERSONA_EPOCH, "male_sport") % len(SPORT_USERNAMES)
            sport = SPORT_USERNAMES[sport_idx]
            return f"{sport}_{f}"
        elif pattern == 2:
            city_idx = seed_for(account_id, _PERSONA_EPOCH, "male_city") % len(CITY_ABBREVIATIONS)
            city = CITY_ABBREVIATIONS[city_idx]
            return f"{f}_{city}"
        else:
            adj_idx = seed_for(account_id, _PERSONA_EPOCH, "male_adj") % len(USERNAME_ADJECTIVES)
            adj = USERNAME_ADJECTIVES[adj_idx]
            return f"{adj}_{f}"

    def _format_bio(self, template: str, birth_year: int, account_id: str) -> str:
        """Replace template placeholders with realistic values."""
        if "{year}" in template:
            # Lifting/started year: 2-5 years ago from birth year + 18
            start_age = 17 + (seed_for(account_id, _PERSONA_EPOCH, "male_start_age") % 4)
            start_year = birth_year + start_age
            template = template.replace("{year}", str(start_year))
        if "{age}" in template:
            # Age when they started the sport: 8-14
            sport_start_age = 8 + (seed_for(account_id, _PERSONA_EPOCH, "male_sport_age") % 7)
            template = template.replace("{age}", str(sport_start_age))
        if "{city}" in template:
            city_idx = seed_for(account_id, _PERSONA_EPOCH, "male_bio_city") % len(CITY_ABBREVIATIONS)
            template = template.replace("{city}", CITY_ABBREVIATIONS[city_idx].upper())
        return template
