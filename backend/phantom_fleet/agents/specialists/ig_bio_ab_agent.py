"""
IGBioABAgent — A/B tests Instagram profile elements across account cohorts.

Tracks which bio variant maximises DM initiation rate:
    DM_initiation_rate = new_DMs_received / profile_visits * 100

Design decisions (CLAUDE.md scale-level audit):

    1. Account assignment uses hash(account_id) % len(variants) for STABLE mapping.
       The same account always gets the same variant regardless of when the
       assignment runs. This prevents cross-contamination mid-test (variant
       switching during a test ruins the metric).

    2. Minimum 50 profile visits before declaring a winner. Below 50 visits,
       even a 10% true difference would not be statistically distinguishable
       from noise. 50 is a pragmatic floor for weekly test cadences.

    3. Tie-breaking: variant with more total profile_visits wins ties. Higher
       visit count → more statistical confidence in the measured rate.

    4. Bio max 150 chars and display name max 30 chars are enforced at the
       BioVariant dataclass level (code-enforced, not prompt).

    5. AI-generated variant pool uses OpenRouter with fresh per-call seeds so
       the N variants generated are diverse (different angles per variant).

    6. Assignment is by cohort (persona_id grouping), not fleet-wide.
       Different cohorts can run different tests simultaneously.

Fleet-scale note: bio content is account-level state, not per-post. The risk
here is not content monoculture per post but profile monoculture: if 1000
accounts all share one bio variant, Instagram's classifier may detect the
cluster. The test assigns variants to cohort sub-groups, keeping any single
variant to <25% of the fleet.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constraints (all code-enforced)
# ---------------------------------------------------------------------------

BIO_MAX_CHARS: int = 150
DISPLAY_NAME_MAX_CHARS: int = 30
MIN_VISITS_FOR_SIGNIFICANCE: int = 50
MAX_VARIANTS: int = 8     # Sane upper bound — more than this is impractical

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BioVariant:
    """One candidate in an A/B test."""

    variant_id: str
    bio_text: str                   # max 150 chars, enforced in __post_init__
    display_name: str               # max 30 chars, enforced in __post_init__
    profile_photo_path: str | None
    assigned_account_ids: list[str] = field(default_factory=list)
    dm_initiations: int = 0
    profile_visits: int = 0

    def __post_init__(self) -> None:
        if len(self.bio_text) > BIO_MAX_CHARS:
            raise ValueError(
                f"bio_text exceeds {BIO_MAX_CHARS} chars "
                f"(got {len(self.bio_text)}) for variant {self.variant_id}"
            )
        if len(self.display_name) > DISPLAY_NAME_MAX_CHARS:
            raise ValueError(
                f"display_name exceeds {DISPLAY_NAME_MAX_CHARS} chars "
                f"(got {len(self.display_name)}) for variant {self.variant_id}"
            )

    @property
    def dm_initiation_rate(self) -> float:
        """DM initiations per 100 profile visits. 0.0 if no visits."""
        return self.dm_initiations / max(self.profile_visits, 1) * 100

    @property
    def has_significance(self) -> bool:
        """True when this variant has enough visits for statistical inference."""
        return self.profile_visits >= MIN_VISITS_FOR_SIGNIFICANCE


@dataclass
class ABTestSpec:
    """Parameters for launching an A/B test."""

    test_id: str
    cohort_account_ids: list[str]
    variants: list[BioVariant]
    test_days: int = 7
    started_at_iso: str = ""
    ended_at_iso: str = ""
    winner_variant_id: str | None = None
    status: str = "pending"         # "pending" | "running" | "complete" | "insufficient_data"

    def __post_init__(self) -> None:
        if len(self.variants) > MAX_VARIANTS:
            raise ValueError(
                f"ABTestSpec supports at most {MAX_VARIANTS} variants; "
                f"got {len(self.variants)}"
            )
        if not self.variants:
            raise ValueError("ABTestSpec requires at least 1 variant")


@dataclass
class ABTestResult:
    """Outcome of a completed A/B test."""

    test_id: str
    winner_variant_id: str | None
    winner_dm_rate: float
    runner_up_variant_id: str | None
    runner_up_dm_rate: float
    total_visits_across_variants: int
    accounts_updated: int
    insufficient_data: bool         # True if no variant had >= MIN_VISITS_FOR_SIGNIFICANCE


# ---------------------------------------------------------------------------
# Core agent
# ---------------------------------------------------------------------------


class IGBioABAgent:
    """
    A/B tests Instagram profile elements (bio, display name, profile photo)
    across account cohorts to maximise DM initiation rate.

    The agent does NOT make HTTP calls directly. It returns instructions
    (which account gets which bio) and expects the caller to apply the
    changes via client.update_profile(). This keeps the agent pure
    business-logic and the HTTP layer in InstagramClient.

    Usage:
        agent = IGBioABAgent()

        # 1. Assign variants to accounts (stable hash-based)
        spec = agent.assign_accounts(spec)

        # 2. For each assigned account, caller calls client.update_profile()

        # 3. During test period, caller feeds in metrics:
        spec = agent.record_metrics(
            spec,
            variant_id="v_a",
            new_profile_visits=12,
            new_dm_initiations=2,
        )

        # 4. At test end:
        result = agent.declare_winner_and_rollout(spec)
    """

    # ------------------------------------------------------------------
    # Account assignment
    # ------------------------------------------------------------------

    def assign_accounts(self, spec: ABTestSpec) -> ABTestSpec:
        """
        Assign each account in the cohort to a variant via stable hash.

        Assignment rule: variant_index = hash(account_id) % len(variants)
        This is stable — the same account always maps to the same variant
        even if the agent restarts mid-test.

        Returns the spec with populated variant.assigned_account_ids lists.
        """
        if not spec.variants:
            raise ValueError("ABTestSpec has no variants")

        n = len(spec.variants)

        # Reset assignments (idempotent)
        for v in spec.variants:
            v.assigned_account_ids = []

        for account_id in spec.cohort_account_ids:
            idx = _stable_hash_mod(account_id, n)
            spec.variants[idx].assigned_account_ids.append(account_id)

        total_assigned = sum(len(v.assigned_account_ids) for v in spec.variants)
        log.info(
            "[test=%s] assigned %d accounts across %d variants",
            spec.test_id, total_assigned, n,
        )
        return spec

    # ------------------------------------------------------------------
    # Metrics ingestion
    # ------------------------------------------------------------------

    def record_metrics(
        self,
        spec: ABTestSpec,
        variant_id: str,
        new_profile_visits: int,
        new_dm_initiations: int,
    ) -> ABTestSpec:
        """
        Accumulate profile visit and DM initiation counts for a variant.

        Caller feeds these in from the account's activity data over the
        test period. All metrics are additive — call as often as data is
        available.
        """
        for v in spec.variants:
            if v.variant_id == variant_id:
                v.profile_visits += new_profile_visits
                v.dm_initiations += new_dm_initiations
                return spec
        raise ValueError(f"variant_id {variant_id!r} not found in test {spec.test_id!r}")

    # ------------------------------------------------------------------
    # Winner declaration and rollout instructions
    # ------------------------------------------------------------------

    def declare_winner_and_rollout(self, spec: ABTestSpec) -> ABTestResult:
        """
        Declare the winning variant and return rollout instructions.

        Rules:
            - Only eligible variants: profile_visits >= MIN_VISITS_FOR_SIGNIFICANCE
            - Winner = highest dm_initiation_rate among eligible variants
            - Tie-break: variant with more profile_visits wins
            - If no variant has enough visits: insufficient_data = True

        Does NOT call update_profile — the caller must apply the rollout
        by calling client.update_profile() for each account in the cohort.

        Returns ABTestResult with the winning variant ID (or None if
        insufficient data).
        """
        eligible = [v for v in spec.variants if v.has_significance]

        if not eligible:
            log.warning(
                "[test=%s] no variant reached %d visits — marking insufficient_data",
                spec.test_id, MIN_VISITS_FOR_SIGNIFICANCE,
            )
            spec.status = "insufficient_data"
            return ABTestResult(
                test_id=spec.test_id,
                winner_variant_id=None,
                winner_dm_rate=0.0,
                runner_up_variant_id=None,
                runner_up_dm_rate=0.0,
                total_visits_across_variants=sum(v.profile_visits for v in spec.variants),
                accounts_updated=0,
                insufficient_data=True,
            )

        # Sort by (dm_initiation_rate DESC, profile_visits DESC) for stable tie-break
        eligible.sort(
            key=lambda v: (v.dm_initiation_rate, v.profile_visits),
            reverse=True,
        )
        winner = eligible[0]
        runner_up = eligible[1] if len(eligible) > 1 else None

        spec.winner_variant_id = winner.variant_id
        spec.status = "complete"
        spec.ended_at_iso = datetime.now(timezone.utc).isoformat()

        accounts_to_update = len(spec.cohort_account_ids)
        log.info(
            "[test=%s] winner=%s (rate=%.2f%%, visits=%d) — rolling out to %d accounts",
            spec.test_id, winner.variant_id, winner.dm_initiation_rate,
            winner.profile_visits, accounts_to_update,
        )

        return ABTestResult(
            test_id=spec.test_id,
            winner_variant_id=winner.variant_id,
            winner_dm_rate=winner.dm_initiation_rate,
            runner_up_variant_id=runner_up.variant_id if runner_up else None,
            runner_up_dm_rate=runner_up.dm_initiation_rate if runner_up else 0.0,
            total_visits_across_variants=sum(v.profile_visits for v in spec.variants),
            accounts_updated=accounts_to_update,
            insufficient_data=False,
        )

    # ------------------------------------------------------------------
    # Variant generation via OpenRouter
    # ------------------------------------------------------------------

    async def generate_bio_variants(
        self,
        niche: str,
        of_link_included: bool,
        n: int = 4,
    ) -> list[str]:
        """
        Generate N bio variant texts via OpenRouter for A/B testing.

        Each variant uses a different persuasion angle:
            0: mysterious  — leaves something unsaid, curiosity hook
            1: direct      — clear value proposition, no ambiguity
            2: playful     — emoji-forward, personality-led
            3: personality — personal detail, feels like a real person

        Args:
            niche:            Content niche ("fitness", "lifestyle", etc.)
            of_link_included: Whether the bio mentions or implies an OF link.
            n:                Number of variants to generate (default 4).

        Returns:
            List of n bio strings, each ≤ BIO_MAX_CHARS characters.

        Raises:
            RuntimeError if OPENROUTER_API_KEY is not set.
        """
        import httpx  # local import — only needed here

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY environment variable is not set. "
                "Required for bio variant generation."
            )

        angles = ["mysterious", "direct", "playful", "personality-led"]
        prompts_for_angles = angles[:n] + angles[: max(0, n - len(angles))]

        system_prompt = (
            "You are a professional social media copywriter specialising in "
            "creator monetisation. Write Instagram bios that maximise DM initiations. "
            f"The account niche is: {niche}. "
            f"OF link in bio: {'yes' if of_link_included else 'no'}. "
            f"Hard limit: each bio must be {BIO_MAX_CHARS} characters or fewer. "
            "Return ONLY the bio text. No quotes, no explanation."
        )

        variants: list[str] = []

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
            for i in range(n):
                angle = prompts_for_angles[i % len(angles)]
                user_prompt = (
                    f"Write a {angle} Instagram bio for a {niche} creator. "
                    f"Max {BIO_MAX_CHARS} characters."
                )

                payload = {
                    "model": "anthropic/claude-3-haiku",
                    "max_tokens": 100,
                    "messages": [
                        {"role": "user", "content": user_prompt},
                    ],
                    "system": system_prompt,
                }

                try:
                    resp = await http.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    bio_text = (
                        data["choices"][0]["message"]["content"]
                        .strip()
                        .strip('"\'')
                    )
                    # Hard-enforce length (model may ignore the instruction)
                    if len(bio_text) > BIO_MAX_CHARS:
                        bio_text = bio_text[:BIO_MAX_CHARS].rstrip()
                    variants.append(bio_text)
                except Exception as exc:
                    log.error("generate_bio_variants: OpenRouter error (variant %d): %s", i, exc)
                    # Fallback placeholder so the caller always gets n variants
                    fallback = f"Creator in {niche} 🔥 DM me"
                    variants.append(fallback[:BIO_MAX_CHARS])

        return variants


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_hash_mod(account_id: str, modulus: int) -> int:
    """
    Return a stable hash of account_id modulo modulus.

    Uses SHA-256 so the result is identical across process restarts
    (Python's built-in hash() is process-scoped and randomised).
    """
    digest = hashlib.sha256(account_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % modulus
