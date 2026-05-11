"""
Gen Z 2026 Voice Style — Global baseline for ALL Phantom Fleet chat agents.

This is injected into EVERY system prompt before any persona customization.
It defines how the AI sounds at a fundamental level — not what it says,
but HOW it says it.

A real 18-25 year old girl in 2026. Never sounds like:
- A 2020 millennial ("lol that's so lit haha chill vibes")
- A corporate chatbot ("I'd be happy to help you with that!")
- A 2023 AI ("Certainly! That's a great question.")
- A try-hard chaser of slang ("no cap fr fr bussin")

Sounds like:
- Someone texting their friend between classes
- Natural, unbothered, occasionally unhinged
- Reacts genuinely, doesn't over-explain
- Short messages. Never walls of text.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Global voice baseline — prepended to EVERY chat system prompt
# ---------------------------------------------------------------------------

GENZ_VOICE_BASELINE = """## how you text

you sound like a real girl, 20 years old, texting in 2026. not performing. not trying. just real.

**short messages always.** 1-3 sentences max. if you want to say more, send two messages mentally but only one here.

**never say:**
- lol → use 💀 😭 or nothing
- haha → "no literally" or just react
- epic, lit, dope, slaps, gotcha → these are retired
- "that's so cool!" → too generic, say what's actually cool about it
- "omg wow!" → pick one reaction, don't stack fake enthusiasm
- "I'd love to" / "I'd be happy to" / "Certainly" → never. ever.
- complete sentences with proper grammar when a fragment works better
- ending every message with a question (desperate energy)

**you do say (naturally, not forced):**
- "no bc" when something is genuinely surprising
- "💀" instead of lol when something is funny
- "thats giving [thing]" for comparisons
- "not me [doing thing]" for self-aware moments
- "lowkey" / "highkey" when appropriate
- "real" or "so real" when agreeing
- "the audacity??" when shocked
- "unhinged" (sparingly, when actually unhinged)
- "brainrot" for things you're obsessed with
- "ate" / "you ate" as a compliment
- "no rizz" as light teasing

**texting style:**
- lowercase most of the time
- no period at end of casual messages
- period = serious/cold energy (use intentionally)
- ALL CAPS for emphasis occasionally: "HELP why is that so funny"
- ellipsis (...) for trailing off, not for pause
- 1-2 emojis max per message, not as decoration but as reaction
- never 🙂 — that emoji is passive aggressive to gen z

**vibe:**
- unbothered but engaged
- a little chaotic but self-aware
- warm but not desperate
- playful but not try-hard
- if you don't have something real to say, say less not more"""


# ---------------------------------------------------------------------------
# Platform-specific voice context — appended after GENZ_VOICE_BASELINE
# ---------------------------------------------------------------------------

PLATFORM_VOICE_CONTEXT: dict[str, str] = {
    "instagram":  "you're in instagram dms. keep it warm and casual. short messages.",
    "threads":    "you're messaging on threads. chill, like instagram but more random.",
    "reddit":     "you're in reddit dms. people here are more text-heavy, match their energy but stay gen z.",
    "x":          "you're in twitter/x dms. punchy. very short. attitude.",
    "bluesky":    "you're on bluesky dms. artsy crowd, thoughtful but still casual.",
    "telegram":   "you're on telegram. feels more private. can be a bit more open.",
    "discord":    "you're in discord dms. community energy. gaming-adjacent.",
    "tinder":     "you're on tinder. flirty, playful. not desperate. you get matches.",
    "bumble":     "you're on bumble. she messaged first (or you did). keep that energy.",
    "hinge":      "you're on hinge. bit more intentional than tinder. still casual.",
    "grindr":     "you're on grindr. direct but warm. this community has its own vibe.",
    # dating is the generic fallback key used by the dating manager
    "dating":     "you're on a dating app. flirty but natural, not desperate.",
    "tiktok":     "you're in tiktok dms. very short, very casual, creator energy.",
    "linkedin":   "you're on linkedin. professional — override voice style: drop the gen z baseline here.",
}


def get_voice_context(platform: str) -> str:
    """Return the platform-specific voice context line for the given platform key.

    Falls back to an empty string for unknown platforms so the baseline still applies.
    LinkedIn is a special case — the baseline should be suppressed for professional tone.
    """
    return PLATFORM_VOICE_CONTEXT.get(platform.lower(), "")


def build_voice_prefix(platform: str) -> str:
    """
    Build the full voice prefix block to prepend to a system prompt.

    For LinkedIn, the Gen Z baseline is deliberately excluded — the professional
    ChatModeProfile already defines the correct voice for that platform.

    For all other platforms, returns:
        GENZ_VOICE_BASELINE + newline + platform context line
    """
    if platform.lower() == "linkedin":
        return ""

    ctx = get_voice_context(platform)
    if ctx:
        return f"{GENZ_VOICE_BASELINE}\n\n{ctx}"
    return GENZ_VOICE_BASELINE


# ---------------------------------------------------------------------------
# Replacement map — applied in order by apply_voice_style()
# Tuples of (regex_pattern, replacement)
# ---------------------------------------------------------------------------

VOICE_REPLACEMENTS: list[tuple[str, str]] = [
    # Retired words → modern replacements
    (r"\blol\b",                                "💀"),
    (r"\bhaha\b",                               "no literally"),
    (r"\bepic\b",                               "so good"),
    (r"\blit\b",                                "fire"),
    (r"\bdope\b",                               "actually so good"),
    (r"\bslaps\b",                              "goes hard"),
    (r"\bgotcha\b",                             "got it"),
    (r"\bchill out\b",                          "relax"),
    (r"that'?s so cool\b",                      "ok that's actually good"),

    # AI tells → removed or softened
    (r"I'?d be happy to\b[^.!?]*[.!?]?",       ""),
    (r"Certainly[,!]?\s*",                      ""),
    (r"Of course[,!]?\s*",                      ""),
    (r"Great question[,!]?\s*",                 ""),
    (r"That'?s a great\b",                      "ok that's a"),
    (r"\bI understand\b",                       "yeah"),
    (r"\bI apologize\b",                        "my bad"),
    (r"As an AI\b[^.]*\.",                      ""),
    (r"I hope this helps[.!]?\s*",              ""),
    (r"Feel free to\b",                         ""),
    (r"Don'?t hesitate to\b[^.]*\.",            ""),

    # Over-enthusiastic AI openers
    (r"Absolutely[,!]\s*",                      ""),
    (r"Definitely[,!]\s*",                      "yeah "),
    (r"Amazing[,!]\s*",                         "ok that's actually "),
    (r"Wonderful[,!]\s*",                       ""),
    (r"Fantastic[,!]\s*",                       "ok "),
]

# Compiled once at module load for performance
_COMPILED_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), repl)
    for pat, repl in VOICE_REPLACEMENTS
]


# ---------------------------------------------------------------------------
# Hard-banned phrases — if ANY appear, the message must be retried
# ---------------------------------------------------------------------------

HARD_BANNED_PHRASES: frozenset[str] = frozenset([
    "i'd be happy to",
    "i would be happy to",
    "certainly!",
    "of course!",
    "great question",
    "as an ai",
    "i hope this helps",
    "don't hesitate",
    "feel free to reach out",
    "it's worth noting",
    "it is worth noting",
    "in conclusion",
    "to summarize",
    "furthermore",
    "additionally",
    "i apologize for",
    "delve into",
    "delve deeper",
])


# ---------------------------------------------------------------------------
# Test cases — verified before/after pairs for tests/test_voice_style.py
# ---------------------------------------------------------------------------

VOICE_STYLE_TEST_CASES: list[tuple[str, bool]] = [
    # (message_text, should_pass_score_gate)
    ("no bc why is that so funny 💀",                                          True),
    ("thats actually giving main character energy",                             True),
    ("the audacity?? 😭",                                                      True),
    ("I'd be happy to help you with that! Certainly, that's a great question.", False),
    ("haha lol that's so lit and dope!",                                       False),
    ("omg wow! Amazing! That's so cool!",                                      False),
    ("ok but why does that go so hard",                                        True),
    ("lowkey obsessed with this rn",                                           True),
    ("HELP why is that so funny 😭",                                           True),
    ("Furthermore, I would like to add that this is quite interesting.",       False),
]


# ---------------------------------------------------------------------------
# Core post-processing functions
# ---------------------------------------------------------------------------


def apply_voice_style(text: str) -> str:
    """
    Post-process LLM output to enforce Gen Z 2026 voice style.

    Step 1: Apply regex replacements in order (VOICE_REPLACEMENTS).
    Step 2: Collapse whitespace artifacts left by empty-string replacements.
    Step 3: Strip leading/trailing whitespace.

    Does NOT retry — callers should check has_banned_phrases() and
    voice_style_score() after this call to decide whether to retry.
    """
    result = text
    for pattern, replacement in _COMPILED_REPLACEMENTS:
        result = pattern.sub(replacement, result)

    # Collapse multiple consecutive spaces / blank lines left by deletions
    result = re.sub(r"  +", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def has_banned_phrases(text: str) -> bool:
    """
    Return True if the text contains any hard-banned phrase.

    Case-insensitive. Triggers an unconditional retry regardless of score.
    """
    lower = text.lower()
    return any(phrase in lower for phrase in HARD_BANNED_PHRASES)


def voice_style_score(text: str) -> float:
    """
    Score 0.0–1.0 of how 'on-voice' a message is.

    Used to decide whether to retry LLM generation.
        0.0 = sounds like a corporate chatbot
        1.0 = sounds like a real gen z girl

    Scoring breakdown:
        Penalties:
            -0.4  contains any hard-banned phrase
            -0.2  contains "lol" (one occurrence enough)
            -0.2  contains "haha" (one occurrence enough)
            -0.1  message length > 150 characters (too long for casual DM)
            -0.1  contains 3 or more emojis (overdone)
            -0.15 starts with a capital letter and ends with a period (formal structure)
            -0.1  contains "!" more than once (over-enthusiastic)

        Bonuses:
            +0.1  contains 💀 or 😭 (authentic gen z reaction emoji)
            +0.1  majority of alphabetic chars are lowercase (≥ 80%)
            +0.05 does NOT end with a period (casual sign-off)
            +0.05 contains "lowkey", "highkey", "no bc", "unhinged", or "brainrot"

    Score is clamped to [0.0, 1.0].
    """
    score = 0.5  # neutral baseline

    lower = text.lower()

    # --- Penalties ---
    if has_banned_phrases(text):
        score -= 0.4

    if "lol" in lower:
        score -= 0.2

    if "haha" in lower:
        score -= 0.2

    if len(text) > 150:
        score -= 0.1

    # Count emojis using a broad Unicode range
    emoji_pattern = re.compile(
        r"[\U0001F300-\U0001F9FF"
        r"\U0001FA00-\U0001FA6F"
        r"\U0001FA70-\U0001FAFF"
        r"\u2600-\u27BF]+",
        re.UNICODE,
    )
    emoji_matches = emoji_pattern.findall(text)
    emoji_count = sum(len(m) for m in emoji_matches)
    if emoji_count >= 3:
        score -= 0.1

    # Formal structure: starts capital, ends period
    stripped = text.strip()
    if stripped and stripped[0].isupper() and stripped.endswith("."):
        score -= 0.15

    # Over-enthusiastic exclamation marks
    if text.count("!") > 1:
        score -= 0.2

    # --- Bonuses ---
    if "💀" in text or "😭" in text:
        score += 0.1

    # Lowercase dominance check
    alpha_chars = [c for c in text if c.isalpha()]
    if alpha_chars:
        lowercase_ratio = sum(1 for c in alpha_chars if c.islower()) / len(alpha_chars)
        if lowercase_ratio >= 0.80:
            score += 0.1

    # No trailing period = casual
    if stripped and not stripped.endswith("."):
        score += 0.05

    # Authentic Gen Z vocabulary
    genz_vocab = ("lowkey", "highkey", "no bc", "unhinged", "brainrot")
    if any(term in lower for term in genz_vocab):
        score += 0.05

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Retry nudge instruction — appended to user prompt on low-score retry
# ---------------------------------------------------------------------------

STYLE_RETRY_NUDGE = (
    "rewrite this to sound more natural, shorter, less formal. "
    "lowercase. 1-2 sentences max. no corporate words."
)
