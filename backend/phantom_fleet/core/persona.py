"""
Persona primitive — the core Phantom Fleet differentiator.

A Persona is a human character with a consistent identity across every
platform. ONE persona → N accounts across N platforms → N phones → all
consistent. When an account dies, the Persona keeps existing and a
replacement account is provisioned under the same Persona.

Onimator has "accounts". Phantom Fleet has Personas. This is why cross-
platform unification and long-term growth strategies are possible.

Every Persona is locked at creation with:
- Claimed demographic (age, gender, city, state, country)
- Device model + OS version from real installed-base distributions
- Behavioral biometric profile (touch dwell, typing cadence, scroll velocity)
- Aggressiveness factor (0.85-1.15, applied to every daily target forever)
- Active hours window (which part of the day the persona is "awake")
- Content style (bio template, caption voice, hashtag-free keyword vocab)
- Targeting source config (per-persona, no overlap with other personas)
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any

from .distributions import LogNormal, Normal, WeightedCategorical


# ---------------------------------------------------------------------------
# Device distribution — match real-world IG installed base, NOT 78% flagships.
# Source: cross-referenced from IG user survey data + Play Store install counts.
# Note: skewed toward mid-range Samsung because that's what Phase 0 fleet IS.
# ---------------------------------------------------------------------------


DEVICE_DISTRIBUTION = WeightedCategorical(
    choices=[
        # model, weight
        ("SM-G770F", 12.0),   # Galaxy S10 Lite EU (user's fleet)
        ("SM-G770U1", 8.0),   # Galaxy S10 Lite US
        ("SM-G973F", 6.0),    # Galaxy S10
        ("SM-G975F", 5.0),    # Galaxy S10+
        ("SM-G980F", 7.0),    # Galaxy S20
        ("SM-G981U", 5.0),    # Galaxy S20 5G US
        ("SM-G991U", 4.0),    # Galaxy S21 US
        ("SM-G998U", 3.0),    # Galaxy S21 Ultra US
        ("SM-A515F", 9.0),    # Galaxy A51 (very common)
        ("SM-A526B", 7.0),    # Galaxy A52
        ("SM-A536U", 5.0),    # Galaxy A53
        ("Pixel 6", 3.0),     # Google Pixel 6
        ("Pixel 7", 2.0),     # Google Pixel 7
        ("SM-N986B", 3.0),    # Galaxy Note 20 Ultra
    ]
)


# ---------------------------------------------------------------------------
# Android version distribution — spread along natural update-lag curve.
# Most users are 1-2 major versions behind, not all on the latest patch.
# ---------------------------------------------------------------------------


ANDROID_VERSION_DISTRIBUTION = WeightedCategorical(
    choices=[
        ("10", 8.0),
        ("11", 22.0),  # Phase 0 fleet is Android 11
        ("12", 24.0),
        ("13", 22.0),
        ("14", 15.0),
        ("15", 6.0),
        ("16", 3.0),
    ]
)


# ---------------------------------------------------------------------------
# Geography pools (US East Coast for Tatiana/Melodie to match residential proxy)
# ---------------------------------------------------------------------------


US_EAST_COAST_CITIES = WeightedCategorical(
    choices=[
        (("New York", "NY"), 20.0),
        (("Brooklyn", "NY"), 12.0),
        (("Jersey City", "NJ"), 8.0),
        (("Newark", "NJ"), 6.0),
        (("Philadelphia", "PA"), 10.0),
        (("Pittsburgh", "PA"), 4.0),
        (("Boston", "MA"), 10.0),
        (("Cambridge", "MA"), 5.0),
        (("Hartford", "CT"), 5.0),
        (("Stamford", "CT"), 4.0),
        (("Baltimore", "MD"), 6.0),
        (("Washington", "DC"), 5.0),
        (("Atlanta", "GA"), 5.0),
    ]
)


# ---------------------------------------------------------------------------
# Biometric profile — sampled ONCE at persona creation, locked for life.
# ---------------------------------------------------------------------------


@dataclass
class BehavioralBiometrics:
    """Per-persona touch/typing/scroll signature, locked at creation.

    These are the behavioral fingerprints that make each persona 'feel'
    different. They're used by the Warming Agent to pace every action.
    Two personas with the same target counts still produce different
    action timings because their biometrics differ.
    """

    # Touch dynamics
    tap_dwell_ms_mean: float  # mean touch-down duration
    tap_dwell_ms_std: float
    tap_offset_px_std: float  # how far from button center taps land

    # Typing dynamics
    keystroke_ms_mean: float
    keystroke_ms_std: float
    typo_rate: float  # 0.015 .. 0.045
    burst_probability: float  # chance of "typing fast for a moment"

    # Scroll dynamics
    scroll_velocity_px_s_mean: float
    scroll_velocity_px_s_std: float
    scroll_distance_px_mean: float
    back_scroll_probability: float  # 0.05 .. 0.12

    # Session dynamics
    session_min_minutes: float
    session_max_minutes: float
    min_action_gap_sec: float  # 60..180
    min_session_gap_min: float  # 30..150

    # Content attention
    content_pause_sec_mean: float  # on posts the persona "likes"
    content_pause_sec_std: float


# ---------------------------------------------------------------------------
# Persona dataclass
# ---------------------------------------------------------------------------


@dataclass
class Persona:
    """A cross-platform human character.

    Personas are immutable once created. When an account under a persona
    dies, a replacement account is provisioned under the same persona ID
    and the persona continues.
    """

    persona_id: str
    display_name: str  # "Tatiana", "Melodie", ...
    gender: str  # "f" / "m" / "nb"
    age: int  # 18-45 typically
    city: str
    state: str
    country: str  # "US"
    locale: str  # "en-US"
    timezone: str  # "America/New_York"
    device_model: str
    android_version: str
    biometrics: BehavioralBiometrics

    # Locked once, forever
    aggressiveness: float  # 0.85-1.15
    peak_hour_local: int  # 0-23, the persona's busiest hour
    active_window_hours: tuple[int, int]  # (start_hour, end_hour) local

    # Content style
    bio_template: str = ""
    caption_voice: str = "casual_young_adult_texting"
    interest_topics: tuple[str, ...] = field(default_factory=tuple)

    # Assignment
    assigned_phone_serials: tuple[str, ...] = field(default_factory=tuple)
    account_ids: tuple[str, ...] = field(default_factory=tuple)

    # Funnel
    target_funnel: str = "onlyfans"  # or "fanvue", "scaleher", "brand"


# ---------------------------------------------------------------------------
# Factory — produce a persona with all fields sampled from real distributions.
# ---------------------------------------------------------------------------


def _sampled_biometrics(rng) -> BehavioralBiometrics:
    """Draw a full biometric profile from realistic ranges."""
    return BehavioralBiometrics(
        tap_dwell_ms_mean=rng.uniform(80, 160),
        tap_dwell_ms_std=rng.uniform(15, 40),
        tap_offset_px_std=rng.uniform(5, 12),
        keystroke_ms_mean=rng.uniform(140, 240),
        keystroke_ms_std=rng.uniform(30, 80),
        typo_rate=rng.uniform(0.015, 0.045),
        burst_probability=rng.uniform(0.1, 0.35),
        scroll_velocity_px_s_mean=rng.uniform(1200, 3200),
        scroll_velocity_px_s_std=rng.uniform(300, 900),
        scroll_distance_px_mean=rng.uniform(400, 1100),
        back_scroll_probability=rng.uniform(0.05, 0.12),
        session_min_minutes=rng.uniform(5, 9),
        session_max_minutes=rng.uniform(12, 20),
        min_action_gap_sec=rng.uniform(60, 180),
        min_session_gap_min=rng.uniform(30, 150),
        content_pause_sec_mean=rng.uniform(1.5, 5.0),
        content_pause_sec_std=rng.uniform(0.8, 2.5),
    )


def create_persona(
    display_name: str,
    gender: str = "f",
    *,
    persona_id: str | None = None,
    target_funnel: str = "onlyfans",
    interest_topics: tuple[str, ...] = (),
    bio_template: str = "",
) -> Persona:
    """Create a new persona with all fields sampled from realistic distributions.

    Uses the OS cryptographic RNG (via secrets) so the persona's biometric
    profile is non-replayable and non-predictable. Once created, store the
    persona in Postgres — never regenerate it.
    """
    import random as _random

    rng = _random.Random(secrets.randbits(64))
    if persona_id is None:
        persona_id = secrets.token_hex(8)

    city, state = US_EAST_COAST_CITIES.sample()
    device_model = DEVICE_DISTRIBUTION.sample()
    android_version = ANDROID_VERSION_DISTRIBUTION.sample()

    return Persona(
        persona_id=persona_id,
        display_name=display_name,
        gender=gender,
        age=rng.randint(19, 32),
        city=city,
        state=state,
        country="US",
        locale="en-US",
        timezone="America/New_York",
        device_model=device_model,
        android_version=android_version,
        biometrics=_sampled_biometrics(rng),
        aggressiveness=rng.uniform(0.85, 1.15),
        peak_hour_local=rng.choice([10, 11, 12, 13, 18, 19, 20, 21]),
        active_window_hours=(rng.randint(7, 10), rng.randint(21, 24)),
        bio_template=bio_template,
        interest_topics=interest_topics,
        target_funnel=target_funnel,
    )
