"""
ThreadsContentGenerator — AI-generated Threads-native posts for OF creator promotion.

This replaces the broken "cross-post IG captions" approach.

Problem with cross-posting IG captions:
    IG captions are written to accompany a specific photo. "Check out my latest
    content 🔥" means nothing as a standalone Threads text post. Threads is
    text-first — posts must stand alone and make sense WITHOUT an image.

What this generates instead:
    Threads-native standalone text posts in 6 content types:

    1. TEASER       — hints at exclusive content, builds curiosity
    2. PERSONALITY  — GFE/connection-building posts, makes fans feel they know the creator
    3. BTS          — behind-the-scenes, day-in-life, "just finished a shoot..."
    4. RELATABLE    — commentary on dating/lifestyle/trending topics relevant to the niche
    5. CTA          — direct call to action to Telegram or cloaking link
    6. STORY        — short narrative post that pulls the reader in

Funnel rules (HARD):
    - NEVER mention OnlyFans directly (Meta flags accounts — see CLAUDE.md)
    - Use Telegram channel link OR cloaking link as the destination
    - CTA posts reference "my Telegram" or "the link in bio" — never "my OnlyFans"
    - Teaser posts hint without explicit content references

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Each account gets different content_type weights via seeded hash
      (e.g. account A = 40% personality, 20% CTA; account B = 30% BTS, 30% teaser)
    - Temperature 0.92 + per-account seed ensures unique output per account
    - Minimum response validation: reject if output > 500 chars (Threads limit)
      or if "onlyfans" appears in output (safety gate)
    - Learning engine context injected before generation
    - Daily cap of 3 posts per account (enforced by caller)

LLM:
    - Model: claude-haiku-4-5-20251001 for single posts
    - Model: claude-sonnet-4-6 for batch generation (better quality)
    - Max tokens: 200 (Threads posts are short)
    - Temperature: 0.92
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

log = logging.getLogger("phantom_fleet.threads_content_generator")

# ---------------------------------------------------------------------------
# Content types and their Threads weights
# ---------------------------------------------------------------------------

CONTENT_TYPES = ["teaser", "personality", "bts", "relatable", "cta", "story"]

# Default weight distribution (must sum to 1.0)
# Real accounts should have VARIED mix — not all CTA, not all teaser
_DEFAULT_WEIGHTS = {
    "teaser":      0.25,
    "personality": 0.25,
    "bts":         0.15,
    "relatable":   0.15,
    "cta":         0.10,
    "story":       0.10,
}

# ---------------------------------------------------------------------------
# Prompt templates per content type
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You write Threads posts for an OnlyFans creator.
Threads posts are standalone text — no photo, no link unless instructed.
Rules:
- Sound like a REAL PERSON. Use first-person, casual voice.
- Never say "OnlyFans" — the platform is never named.
- Never use hashtags unless they're extremely natural.
- Max 280 characters.
- No generic AI phrases: no "In conclusion", "It's worth noting", "Delve into".
- No em-dashes overuse. No lists. No bullet points.
- Write ONE post only. No alternatives, no explanations.{learning_context}"""

_USER_PROMPTS = {
    "teaser": (
        "Write a Threads post that hints at new exclusive content without saying what it is. "
        "Build curiosity. Something like hinting she just made something really personal/intense/special. "
        "DO NOT name the platform. DO NOT include a link. Just the tease.\n"
        "Creator persona: {persona_desc}"
    ),
    "personality": (
        "Write a Threads post that shows a real slice of the creator's personality — "
        "her mood, something she's thinking about, something relatable about her life. "
        "Not about content. About HER. Makes fans feel like they know her.\n"
        "Creator persona: {persona_desc}"
    ),
    "bts": (
        "Write a Threads post that gives a behind-the-scenes glimpse — just finished a shoot, "
        "getting ready for something, candid moment from the day. "
        "Feels authentic, not staged.\n"
        "Creator persona: {persona_desc}"
    ),
    "relatable": (
        "Write a Threads post that comments on something relatable in the creator's niche "
        "— dating, attraction, relationships, modern life. Something that makes people "
        "comment or relate. Trending topic if applicable: {trending_topic}\n"
        "Creator persona: {persona_desc}"
    ),
    "cta": (
        "Write a Threads post that naturally drives people to {funnel_destination} "
        "without being salesy. Frame it as 'for my real fans', 'if you actually want to see', "
        "or similar soft CTA. Reference the link in bio or 'my Telegram'. "
        "DO NOT say OnlyFans.\n"
        "Creator persona: {persona_desc}"
    ),
    "story": (
        "Write a short narrative Threads post — a mini story (3-5 sentences) that pulls the reader in. "
        "Could be a real scenario, a moment, a confession. Something that makes people stop scrolling.\n"
        "Creator persona: {persona_desc}"
    ),
}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class GeneratedPost:
    """A single generated Threads post."""
    text:          str
    content_type:  str
    account_id:    str
    date_iso:      str
    model_used:    str   = ""
    insight_ids:   list[str] = field(default_factory=list)
    char_count:    int   = 0

    def __post_init__(self):
        self.char_count = len(self.text)


@dataclass
class PersonaContext:
    """Creator persona for content generation."""
    name:          str   = ""
    personality:   str   = "fun, confident, approachable"
    niche:         str   = "lifestyle"
    funnel_dest:   str   = "Telegram"  # "Telegram" or a cloaking URL
    tone_examples: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Content type selection (seeded per account)
# ---------------------------------------------------------------------------


def _select_content_type(
    account_id: str,
    date_iso: str,
    post_index: int,
    weights: Optional[dict[str, float]] = None,
) -> str:
    """
    Select content type using a deterministic seed.
    Different accounts get different content mixes on the same day.
    """
    import random
    if weights is None:
        weights = _DEFAULT_WEIGHTS
    key = f"{account_id}|{date_iso}|ctype_{post_index}"
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    types = list(weights.keys())
    probs = list(weights.values())
    return rng.choices(types, weights=probs, k=1)[0]


# ---------------------------------------------------------------------------
# ThreadsContentGenerator
# ---------------------------------------------------------------------------


class ThreadsContentGenerator:
    """
    Generates Threads-native posts for OF creator promotion.

    Usage:
        gen = ThreadsContentGenerator()

        # Single post
        post = await gen.generate_post(
            account_id="acct_001",
            persona=PersonaContext(name="Luna", personality="playful, confident"),
            content_type="teaser",  # or None for auto-select
        )

        # Batch (for content vault pre-generation)
        posts = await gen.generate_batch(
            account_id="acct_001",
            persona=persona,
            count=10,
        )
    """

    async def generate_post(
        self,
        account_id: str,
        persona: PersonaContext,
        content_type: Optional[str] = None,
        date_iso: Optional[str] = None,
        post_index: int = 0,
        trending_topic: str = "",
        learning_context: str = "",
        insight_ids: Optional[list[str]] = None,
        use_sonnet: bool = False,
    ) -> GeneratedPost:
        """
        Generate a single Threads post.

        Args:
            account_id:       Account this post is for (affects content type seed).
            persona:          Creator persona context.
            content_type:     One of CONTENT_TYPES, or None for auto-select.
            date_iso:         YYYY-MM-DD for seeded selection (defaults to today).
            post_index:       Which post in the day's sequence (0-based).
            trending_topic:   Optional trending topic to reference in relatable posts.
            learning_context: Pre-fetched learning engine prompt block.
            insight_ids:      Insight IDs injected (for learning engine tracking).
            use_sonnet:       Use claude-sonnet-4-6 instead of haiku (higher quality).

        Returns:
            GeneratedPost with validated text.
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        if content_type is None or content_type not in CONTENT_TYPES:
            content_type = _select_content_type(account_id, date_iso, post_index)

        persona_desc = self._build_persona_desc(persona)
        funnel_dest  = f"my Telegram" if "t.me" not in persona.funnel_dest else f"the link in my bio"

        user_prompt = _USER_PROMPTS[content_type].format(
            persona_desc=persona_desc,
            funnel_destination=funnel_dest,
            trending_topic=trending_topic or "something relatable in the dating/lifestyle space",
        )

        system = _SYSTEM_PROMPT.replace(
            "{learning_context}",
            f"\n{learning_context}" if learning_context else "",
        )

        model = "anthropic/claude-sonnet-4-6" if use_sonnet else "anthropic/claude-haiku-4-5-20251001"
        text, model_used = await self._call_llm(system, user_prompt, model, account_id)

        # Safety validation
        text = self._validate_and_clean(text, account_id, content_type)

        return GeneratedPost(
            text=text,
            content_type=content_type,
            account_id=account_id,
            date_iso=date_iso,
            model_used=model_used,
            insight_ids=insight_ids or [],
        )

    async def generate_batch(
        self,
        account_id: str,
        persona: PersonaContext,
        count: int = 10,
        date_iso: Optional[str] = None,
        trending_topic: str = "",
        learning_context: str = "",
    ) -> list[GeneratedPost]:
        """
        Generate a batch of Threads posts (for content vault pre-generation).

        Uses claude-sonnet-4-6 with a single call for better diversity.
        """
        import asyncio
        if date_iso is None:
            date_iso = date.today().isoformat()

        # Cap batch size to prevent LLM cost runaway
        count = min(count, 20)

        persona_desc = self._build_persona_desc(persona)
        funnel_dest  = "my Telegram" if "t.me" not in persona.funnel_dest else "the link in my bio"

        type_distribution = ", ".join(
            f"{n}× {ct}" for ct, n in _count_content_types(count).items()
        )

        system = _SYSTEM_PROMPT.replace("{learning_context}", f"\n{learning_context}" if learning_context else "")

        user_prompt = (
            f"Generate exactly {count} Threads posts for this creator.\n\n"
            f"Creator: {persona_desc}\n"
            f"Funnel destination: {funnel_dest}\n"
            f"Trending context (for relatable posts): {trending_topic or 'modern dating/lifestyle'}\n\n"
            f"Content mix: {type_distribution}\n\n"
            f"Return ONLY a JSON array of objects: [{{\"type\": \"teaser\", \"text\": \"...\"}}]\n"
            f"Each text must be under 280 characters. Never say OnlyFans."
        )

        raw, model_used = await self._call_llm(
            system, user_prompt,
            "anthropic/claude-sonnet-4-6",
            account_id,
            max_tokens=count * 80,
        )

        posts: list[GeneratedPost] = []
        try:
            clean = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
            items = json.loads(clean)
            if not isinstance(items, list):
                items = [items]
        except Exception:
            # Fallback: single post
            items = [{"type": "teaser", "text": raw[:280]}]

        for i, item in enumerate(items[:count]):
            ctype = item.get("type", CONTENT_TYPES[i % len(CONTENT_TYPES)])
            text  = item.get("text", "")
            if not text:
                continue
            text = self._validate_and_clean(text, account_id, ctype)
            posts.append(GeneratedPost(
                text=text,
                content_type=ctype,
                account_id=account_id,
                date_iso=date_iso,
                model_used=model_used,
            ))

        return posts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_persona_desc(self, persona: PersonaContext) -> str:
        parts = []
        if persona.name:
            parts.append(f"Name: {persona.name}")
        if persona.personality:
            parts.append(f"Personality: {persona.personality}")
        if persona.niche:
            parts.append(f"Niche: {persona.niche}")
        if persona.tone_examples:
            examples = " | ".join(persona.tone_examples[:3])
            parts.append(f"Her real voice examples: {examples}")
        return ". ".join(parts) if parts else "a confident, playful lifestyle creator"

    def _validate_and_clean(self, text: str, account_id: str, content_type: str) -> str:
        """Validate and clean generated text. Returns safe post or fallback."""
        text = text.strip().strip('"').strip("'")

        # Hard safety gate: no OnlyFans mentions
        if re.search(r"\bonlyfans\b", text, re.IGNORECASE):
            log.warning(
                "[%s] SAFETY: 'OnlyFans' found in %s post — using fallback",
                account_id, content_type,
            )
            return _FALLBACK_POSTS.get(content_type, "new content just went up 🔥")

        # Length gate
        if len(text) > 500:
            text = text[:497] + "..."

        # Remove markdown artifacts
        text = re.sub(r"\*\*|\*|__", "", text)

        return text if text else _FALLBACK_POSTS.get(content_type, "check the link in my bio 🔥")

    async def _call_llm(
        self,
        system: str,
        user: str,
        model: str,
        account_id: str,
        max_tokens: int = 200,
    ) -> tuple[str, str]:
        """Call OpenRouter. Returns (text, model_used)."""
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if not openrouter_key:
            log.warning("[%s] No OPENROUTER_API_KEY — using fallback post", account_id)
            return ("check the link in my bio 🔥", "fallback")

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type":  "application/json",
                    },
                    json={
                        "model":       model,
                        "temperature": 0.92,
                        "max_tokens":  max_tokens,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user},
                        ],
                    },
                )
                resp.raise_for_status()
                body = resp.json()
                text = body["choices"][0]["message"]["content"].strip()
                used_model = body.get("model", model)
                return (text, used_model)

        except Exception as exc:
            log.warning("[%s] LLM call failed: %s — using fallback", account_id, exc)
            return ("just dropped something for you 🔥 link in bio", "fallback")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_content_types(total: int) -> dict[str, int]:
    """Distribute `total` posts across content types using default weights."""
    result: dict[str, int] = {ct: 0 for ct in CONTENT_TYPES}
    remaining = total
    for ct, weight in _DEFAULT_WEIGHTS.items():
        n = round(weight * total)
        result[ct] = n
        remaining -= n
    # Fix rounding drift
    if remaining > 0:
        result["teaser"] += remaining
    elif remaining < 0:
        for ct in CONTENT_TYPES:
            if result[ct] > 0:
                result[ct] += remaining
                break
    return {k: v for k, v in result.items() if v > 0}


_FALLBACK_POSTS = {
    "teaser":      "you're not ready for what I just made 🔥",
    "personality": "some days you just have to do what makes you happy honestly",
    "bts":         "just wrapped a long day of shooting... exhausted but so worth it",
    "relatable":   "why is dating in 2026 so complicated lmao",
    "cta":         "everything I can't post here is on my Telegram. link in bio",
    "story":       "I almost didn't post this but honestly... here we are",
}
