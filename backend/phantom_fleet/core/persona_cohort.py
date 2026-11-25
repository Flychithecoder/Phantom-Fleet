"""Persona cohort engine — moonshot #10.

OrionFarm's own CLAUDE.md requires:
  - Every random value from a typed distribution (LogNormal, Normal,
    Bimodal, WeightedCategorical) — NEVER `random.uniform/randint/
    Math.random` on identity/fingerprint/scheduling paths.
  - `secrets.randbits()` as the underlying entropy source (not time()).
  - Cross-field consistency: locale/timezone, device/OS, carrier/HNI/
    country, proxy/timezone — pair-check every identity field against
    every other identity field.
  - Fixes for the four known Onimator bugs:
      1. en-GB personas with America/New_York timezone
      2. AppCloner fleet-wide shared signing certs
      3. Static 15-22 accounts per device across the fleet
      4. Flat fleet-wide action timing ignoring timezone

This module ships typed distributions, reference tables derived from
measurable public facts (ISO locale codes, IANA tz, ITU MCC/MNC), and
a `generate_cohort(n)` entrypoint. The accompanying validators module
pair-checks every field.
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass, asdict, field
from typing import Any


# ============================================================
#  TYPED DISTRIBUTIONS — all entropy from secrets.randbits(53)
# ============================================================

def _uniform01() -> float:
    """53-bit uniform in [0, 1). Matches float64 mantissa. Uses
    secrets.randbits so it's crypto-quality entropy, never time()."""
    return secrets.randbits(53) / (1 << 53)


def _gauss() -> float:
    """Box-Muller standard normal from two _uniform01() draws."""
    u1 = max(_uniform01(), 1e-12)
    u2 = _uniform01()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


@dataclass(frozen=True)
class LogNormal:
    mu: float
    sigma: float
    def sample(self) -> float:
        return math.exp(self.mu + self.sigma * _gauss())


@dataclass(frozen=True)
class Normal:
    mean: float
    sd: float
    def sample(self) -> float:
        return self.mean + self.sd * _gauss()


@dataclass(frozen=True)
class Bimodal:
    """Mixture of two Normals with weight `w1` on the first."""
    mean1: float; sd1: float; mean2: float; sd2: float; w1: float
    def sample(self) -> float:
        if _uniform01() < self.w1:
            return self.mean1 + self.sd1 * _gauss()
        return self.mean2 + self.sd2 * _gauss()


@dataclass(frozen=True)
class WeightedCategorical:
    """Items + weights (need not sum to 1 — normalized at sample time)."""
    items: tuple[Any, ...]
    weights: tuple[float, ...]
    def sample(self) -> Any:
        total = sum(self.weights)
        if total <= 0:
            raise ValueError("weights must sum to >0")
        r = _uniform01() * total
        acc = 0.0
        for item, w in zip(self.items, self.weights):
            acc += w
            if r <= acc:
                return item
        return self.items[-1]  # numeric tail


# ============================================================
#  REFERENCE TABLES — measurable public facts
# ============================================================

# Locale -> plausible timezones (IANA). Fix for Onimator bug #1:
# en-GB personas must never land on America/New_York. Weights are
# rough real-world population share within the locale.
LOCALE_TIMEZONES: dict[str, WeightedCategorical] = {
    "en-US": WeightedCategorical(
        items=("America/New_York", "America/Chicago", "America/Denver",
               "America/Los_Angeles", "America/Phoenix"),
        weights=(0.46, 0.22, 0.09, 0.19, 0.04),
    ),
    "en-GB": WeightedCategorical(
        items=("Europe/London",),
        weights=(1.0,),
    ),
    "en-CA": WeightedCategorical(
        items=("America/Toronto", "America/Vancouver", "America/Edmonton",
               "America/Winnipeg", "America/Halifax"),
        weights=(0.49, 0.16, 0.12, 0.08, 0.10),
    ),
    "en-AU": WeightedCategorical(
        items=("Australia/Sydney", "Australia/Melbourne", "Australia/Brisbane",
               "Australia/Perth", "Australia/Adelaide"),
        weights=(0.32, 0.27, 0.18, 0.11, 0.07),
    ),
    "es-MX": WeightedCategorical(
        items=("America/Mexico_City", "America/Tijuana", "America/Monterrey"),
        weights=(0.72, 0.14, 0.14),
    ),
    "pt-BR": WeightedCategorical(
        items=("America/Sao_Paulo", "America/Fortaleza", "America/Recife",
               "America/Manaus"),
        weights=(0.55, 0.14, 0.15, 0.16),
    ),
    "de-DE": WeightedCategorical(items=("Europe/Berlin",), weights=(1.0,)),
    "fr-FR": WeightedCategorical(items=("Europe/Paris",), weights=(1.0,)),
    "ja-JP": WeightedCategorical(items=("Asia/Tokyo",), weights=(1.0,)),
}

LOCALE_WEIGHTS = WeightedCategorical(
    items=tuple(LOCALE_TIMEZONES.keys()),
    weights=(0.38, 0.09, 0.07, 0.05, 0.11, 0.09, 0.07, 0.07, 0.07),
)


# Device model -> OS version range that model actually shipped with.
# Narrow ranges only; a bogus combo (Pixel 8 on Android 10) would be
# flagged by the validator.
DEVICE_OS_RANGES: dict[str, tuple[int, int]] = {
    "Pixel 6": (12, 15),
    "Pixel 7": (13, 15),
    "Pixel 8": (14, 15),
    "Samsung Galaxy S22": (12, 14),
    "Samsung Galaxy S23": (13, 15),
    "Samsung Galaxy A54": (13, 14),
    "OnePlus 10 Pro": (12, 14),
    "Xiaomi 13": (13, 14),
}
DEVICE_WEIGHTS = WeightedCategorical(
    items=tuple(DEVICE_OS_RANGES.keys()),
    weights=(0.14, 0.16, 0.12, 0.14, 0.16, 0.11, 0.09, 0.08),
)


# Carrier -> (country, MCC, MNC list). MCC/MNC are ITU-assigned.
CARRIERS: dict[str, dict[str, Any]] = {
    "AT&T":        {"country": "US", "mcc": "310", "mncs": ("410", "150", "170")},
    "Verizon":     {"country": "US", "mcc": "311", "mncs": ("480", "280")},
    "T-Mobile US": {"country": "US", "mcc": "310", "mncs": ("260", "210")},
    "Rogers":      {"country": "CA", "mcc": "302", "mncs": ("720",)},
    "Bell":        {"country": "CA", "mcc": "302", "mncs": ("610",)},
    "EE":          {"country": "GB", "mcc": "234", "mncs": ("30",)},
    "O2 UK":       {"country": "GB", "mcc": "234", "mncs": ("10",)},
    "Vodafone DE": {"country": "DE", "mcc": "262", "mncs": ("02",)},
    "Orange FR":   {"country": "FR", "mcc": "208", "mncs": ("01",)},
    "Telcel":      {"country": "MX", "mcc": "334", "mncs": ("020",)},
    "Telstra":     {"country": "AU", "mcc": "505", "mncs": ("01",)},
    "NTT Docomo":  {"country": "JP", "mcc": "440", "mncs": ("10",)},
    "Vivo BR":     {"country": "BR", "mcc": "724", "mncs": ("06",)},
}
# Which country each locale implies (used to constrain carrier choice).
LOCALE_COUNTRY: dict[str, str] = {
    "en-US": "US", "en-GB": "GB", "en-CA": "CA", "en-AU": "AU",
    "es-MX": "MX", "pt-BR": "BR", "de-DE": "DE", "fr-FR": "FR",
    "ja-JP": "JP",
}


# Account-count distribution: Bimodal fixes Onimator bug #3 (flat
# 15-22). Clean devices cluster around 3, farm devices around 18.
# w1=0.65 says ~65% of personas are "clean" (not purely farm phones).
ACCOUNT_COUNT_DIST = Bimodal(mean1=3.0, sd1=1.1, mean2=18.0, sd2=3.4, w1=0.65)


# Diurnal action-rate curve (24 values, one per hour of the persona's
# own timezone). Fix for Onimator bug #4. Night trough, morning rise,
# evening peak. Values are relative action-weights; sum normalized at
# sample time.
DIURNAL_CURVE = (
    0.08, 0.05, 0.03, 0.03, 0.04, 0.07,   # 00-05  (night trough)
    0.15, 0.32, 0.55, 0.70, 0.78, 0.82,   # 06-11  (morning rise)
    0.88, 0.92, 0.95, 0.98, 1.00, 0.95,   # 12-17  (midday + evening peak build)
    0.90, 0.82, 0.70, 0.55, 0.35, 0.18,   # 18-23  (evening decline)
)


# ============================================================
#  PERSONA SCHEMA + GENERATOR
# ============================================================

@dataclass
class Persona:
    persona_id: str
    locale: str
    timezone: str
    country: str
    device_model: str
    android_version: int
    carrier: str
    mcc: str
    mnc: str
    hni: str                       # MCC + MNC concatenated (ITU standard)
    account_count: int
    device_age_days: int
    app_signature_salt: str        # per-persona; fix for bug #2
    diurnal_peak_hour_local: int   # hour at which this persona is most active
    randomness_source: str = "secrets.randbits(53)"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pick_carrier_for_locale(locale: str) -> str:
    """Pick a carrier whose country matches the locale. Weights uniform
    among eligible carriers (country aside, we have no fleet data to
    weight further yet)."""
    country = LOCALE_COUNTRY[locale]
    eligible = tuple(name for name, meta in CARRIERS.items() if meta["country"] == country)
    if not eligible:
        raise LookupError(f"no carrier reference for country {country}")
    # Uniform categorical over eligible.
    return WeightedCategorical(items=eligible, weights=tuple(1.0 for _ in eligible)).sample()


def generate_persona() -> Persona:
    """Build one persona with every identity field cross-consistent.
    Entropy source: secrets.randbits(53)."""
    locale = LOCALE_WEIGHTS.sample()
    timezone = LOCALE_TIMEZONES[locale].sample()
    country = LOCALE_COUNTRY[locale]

    device = DEVICE_WEIGHTS.sample()
    os_lo, os_hi = DEVICE_OS_RANGES[device]
    # Uniform integer over the shipped OS range via _uniform01()
    android_version = os_lo + int(_uniform01() * (os_hi - os_lo + 1))
    android_version = min(android_version, os_hi)

    carrier = _pick_carrier_for_locale(locale)
    cmeta = CARRIERS[carrier]
    mnc = WeightedCategorical(
        items=cmeta["mncs"], weights=tuple(1.0 for _ in cmeta["mncs"])
    ).sample()
    mcc = cmeta["mcc"]
    hni = mcc + mnc

    # Age: LogNormal 180d median, wide tail (some devices very old).
    device_age_days = max(1, int(LogNormal(mu=math.log(180), sigma=0.8).sample()))

    # Account count: Bimodal, age-nudged (every 90 days of age adds +1.5
    # mean to the heavy side — older farm devices accumulate accounts).
    base = ACCOUNT_COUNT_DIST.sample()
    age_bonus = (device_age_days / 90) * 1.5
    account_count = max(1, int(round(base + age_bonus * (1 if base > 10 else 0))))

    # Signature salt: unique per persona. Fix for bug #2.
    app_signature_salt = secrets.token_hex(16)

    # Diurnal peak hour sampled from the curve (not uniform!).
    peak = WeightedCategorical(
        items=tuple(range(24)),
        weights=DIURNAL_CURVE,
    ).sample()

    pid = secrets.token_hex(8)
    return Persona(
        persona_id=pid,
        locale=locale,
        timezone=timezone,
        country=country,
        device_model=device,
        android_version=android_version,
        carrier=carrier,
        mcc=mcc,
        mnc=mnc,
        hni=hni,
        account_count=account_count,
        device_age_days=device_age_days,
        app_signature_salt=app_signature_salt,
        diurnal_peak_hour_local=peak,
    )


def generate_cohort(n: int) -> dict[str, Any]:
    """Generate n personas with validator pair-check on every one."""
    if not isinstance(n, int) or n < 1 or n > 10_000:
        raise ValueError("n must be int in [1, 10000]")
    from .persona_cohort_validators import validate_persona
    personas: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    for _ in range(n):
        p = generate_persona()
        d = p.as_dict()
        v = validate_persona(d)
        if v["violations"]:
            violations.append({"persona_id": p.persona_id, "violations": v["violations"]})
        personas.append(d)
    unique_salts = len({p["app_signature_salt"] for p in personas})
    return {
        "personas": personas,
        "count": len(personas),
        "violation_count": len(violations),
        "violations_sample": violations[:5],
        "unique_app_signature_salts": unique_salts,
        "entropy_source": "secrets.randbits(53)",
    }
