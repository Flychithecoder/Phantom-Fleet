"""
CapacityPlanner — tells an agency exactly how many accounts they can safely
run per platform on their specific phone hardware.

Usage:
    An agency inputs which platforms they want to use (in any form — "IG",
    "TG", "snap", "twitter", etc.). The planner resolves platform names,
    applies per-platform safe limits, cross-checks against phone RAM/storage,
    proxy budget, and TimeSlot concurrency, then returns a full capacity report.

Design principles:
    - Detection safety is the PRIMARY constraint, not hardware.
      Hardware constraints are validated AFTER detection limits are set.
    - Numbers are conservative — better to leave capacity on the table
      than to create cluster fingerprints.
    - Threads is always "free" if Instagram is selected (same session).
    - Snapchat and other unsupported platforms are flagged clearly rather
      than silently ignored.
    - The report is human-readable AND machine-readable (CapacityReport dataclass).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Platform alias resolver — handles every common shorthand
# ---------------------------------------------------------------------------

PLATFORM_ALIASES: dict[str, str] = {
    # Instagram
    "ig": "instagram", "insta": "instagram", "instagram": "instagram",
    # Threads
    "threads": "threads",
    # X / Twitter
    "x": "x", "twitter": "x", "tw": "x", "xtwitter": "x",
    # Reddit
    "reddit": "reddit", "rd": "reddit",
    # TikTok
    "tiktok": "tiktok", "tik tok": "tiktok", "tt": "tiktok", "tik-tok": "tiktok",
    # Telegram
    "telegram": "telegram", "tg": "telegram", "tele": "telegram",
    # Discord
    "discord": "discord", "dc": "discord",
    # BlueSky
    "bluesky": "bluesky", "blue sky": "bluesky", "bsky": "bluesky",
    # Dating
    "tinder": "tinder",
    "bumble": "bumble",
    "hinge": "hinge",
    "grindr": "grindr",
    "dating": "_dating_bundle",  # expands to all four dating platforms
    # Unsupported — surfaced as warnings
    "snapchat": "_unsupported_snapchat",
    "snap": "_unsupported_snapchat",
    "facebook": "_unsupported_facebook",
    "fb": "_unsupported_facebook",
    "whatsapp": "_unsupported_whatsapp",
    "wa": "_unsupported_whatsapp",
    "youtube": "_unsupported_youtube",
    "yt": "_unsupported_youtube",
    "pinterest": "_unsupported_pinterest",
    "linkedin": "_general_brand_only_linkedin",
}

DATING_BUNDLE_PLATFORMS = ("tinder", "bumble", "hinge", "grindr")


def resolve_platforms(raw_inputs: list[str]) -> tuple[list[str], list[str], list[str]]:
    """
    Resolve a list of raw platform strings to canonical platform keys.

    Returns:
        supported   — canonical platform keys that are in the OFM build
        unsupported — platform names that Phantom Fleet doesn't support
        general_only — platforms that exist but only in the general brand build
    """
    supported:     list[str] = []
    unsupported:   list[str] = []
    general_only:  list[str] = []
    seen:          set[str]  = set()

    for raw in raw_inputs:
        key = raw.strip().lower()
        resolved = PLATFORM_ALIASES.get(key)

        if resolved is None:
            # Try partial match
            for alias, canonical in PLATFORM_ALIASES.items():
                if key in alias or alias in key:
                    resolved = canonical
                    break

        if resolved is None:
            unsupported.append(raw)
            continue

        if resolved == "_dating_bundle":
            for p in DATING_BUNDLE_PLATFORMS:
                if p not in seen:
                    supported.append(p)
                    seen.add(p)
            continue

        if resolved.startswith("_unsupported_"):
            unsupported.append(raw)
            continue

        if resolved.startswith("_general_brand_only_"):
            general_only.append(raw)
            continue

        if resolved not in seen:
            supported.append(resolved)
            seen.add(resolved)

        # Auto-add Threads if Instagram is selected (free, same session)
        if resolved == "instagram" and "threads" not in seen:
            supported.append("threads")
            seen.add("threads")

    return supported, unsupported, general_only


# ---------------------------------------------------------------------------
# Per-platform safe limits and resource profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlatformProfile:
    platform:          str
    max_accounts:      int       # safe ceiling per phone (detection limit)
    start_accounts:    int       # recommended starting count (60% of ceiling)
    execution_mode:    str       # "background_api" | "foreground_ui"
    clone_storage_mb:  int       # disk space per cloned app instance
    clone_ram_mb:      int       # RAM while the clone is active
    threads_free:      bool      # True = no extra storage (e.g. Threads shares IG)
    notes:             str = ""


PLATFORM_PROFILES: dict[str, PlatformProfile] = {
    "instagram": PlatformProfile(
        platform="instagram",
        max_accounts=12,
        start_accounts=12,
        execution_mode="background_api",
        clone_storage_mb=280,
        clone_ram_mb=290,
        threads_free=False,
        notes="Community-confirmed safe ceiling (Onimator Discord: 8-12/phone, "
              "user confirmed 12 at zero bans). Proxy limit: 3-8 accounts per IP.",
    ),
    "threads": PlatformProfile(
        platform="threads",
        max_accounts=12,
        start_accounts=12,
        execution_mode="background_api",
        clone_storage_mb=0,    # shares IG app session — zero extra storage
        clone_ram_mb=60,       # lightweight API worker only, no separate app
        threads_free=True,
        notes="Free when Instagram is selected — shares the same session token. "
              "No separate app clone required in API mode.",
    ),
    "x": PlatformProfile(
        platform="x",
        max_accounts=6,
        start_accounts=4,
        execution_mode="background_api",
        clone_storage_mb=220,
        clone_ram_mb=260,
        threads_free=False,
        notes="X/Twitter post-2023 has aggressive device fingerprinting. "
              "Device-linked suspensions cascade — conservative ceiling.",
    ),
    "reddit": PlatformProfile(
        platform="reddit",
        max_accounts=8,
        start_accounts=5,
        execution_mode="background_api",
        clone_storage_mb=80,
        clone_ram_mb=120,
        threads_free=False,
        notes="Detection is behavior-focused (karma, spam), not device-level. "
              "8 is safe; official OAuth API used.",
    ),
    "telegram": PlatformProfile(
        platform="telegram",
        max_accounts=10,
        start_accounts=8,
        execution_mode="background_api",
        clone_storage_mb=110,
        clone_ram_mb=140,
        threads_free=False,
        notes="MTProto is multi-device by design. No device bans — only "
              "behavior bans (flood, spam). 10 is a conservative safe ceiling.",
    ),
    "discord": PlatformProfile(
        platform="discord",
        max_accounts=6,
        start_accounts=4,
        execution_mode="background_api",
        clone_storage_mb=130,
        clone_ram_mb=160,
        threads_free=False,
        notes="Discord bans primarily for behavior, not device. ToS risk "
              "regardless of mode. Gate with confirmation_required.",
    ),
    "bluesky": PlatformProfile(
        platform="bluesky",
        max_accounts=15,
        start_accounts=10,
        execution_mode="background_api",
        clone_storage_mb=55,
        clone_ram_mb=80,
        threads_free=False,
        notes="AT Protocol is open API, no strong anti-abuse ML yet. "
              "Highest safe density of any platform in the OFM build.",
    ),
    "tiktok": PlatformProfile(
        platform="tiktok",
        max_accounts=3,
        start_accounts=2,
        execution_mode="foreground_ui",
        clone_storage_mb=210,
        clone_ram_mb=320,
        threads_free=False,
        notes="Most aggressive device fingerprinting of any platform. "
              "Reads GPU fingerprint, sensor data, keyboard cadence. "
              "3 is a hard ceiling — do not exceed.",
    ),
    "grindr": PlatformProfile(
        platform="grindr",
        max_accounts=8,
        start_accounts=6,
        execution_mode="foreground_ui",
        clone_storage_mb=160,
        clone_ram_mb=200,
        threads_free=False,
        notes="Lowest security posture of any dating app. Email signup "
              "works (no SMS required). No SafetyNet check. Highest "
              "per-phone density in the dating tier.",
    ),
    "tinder": PlatformProfile(
        platform="tinder",
        max_accounts=3,
        start_accounts=2,
        execution_mode="foreground_ui",
        clone_storage_mb=180,
        clone_ram_mb=230,
        threads_free=False,
        notes="Play Integrity + Onfido liveness. Device-level bans cascade. "
              "3 is the safe ceiling confirmed by Onimator Discord community.",
    ),
    "bumble": PlatformProfile(
        platform="bumble",
        max_accounts=3,
        start_accounts=2,
        execution_mode="foreground_ui",
        clone_storage_mb=190,
        clone_ram_mb=240,
        threads_free=False,
        notes="iProov / FaceMatch liveness SDK. Same device ceiling as Tinder.",
    ),
    "hinge": PlatformProfile(
        platform="hinge",
        max_accounts=2,
        start_accounts=1,
        execution_mode="foreground_ui",
        clone_storage_mb=170,
        clone_ram_mb=220,
        threads_free=False,
        notes="Strictest dating app — only 2 verification attempts before "
              "24h lockout. Hardware attestation on launch. Hard ceiling: 2.",
    ),
}


# ---------------------------------------------------------------------------
# Phone hardware profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PhoneHardwareProfile:
    model:         str
    ram_mb:        int
    storage_mb:    int
    android_ver:   str


PHONE_PROFILES: dict[str, PhoneHardwareProfile] = {
    "samsung_s10_lite": PhoneHardwareProfile(
        model="Samsung Galaxy S10 Lite",
        ram_mb=6_144,
        storage_mb=128_000,
        android_ver="12",
    ),
    "samsung_s20": PhoneHardwareProfile(
        model="Samsung Galaxy S20",
        ram_mb=8_192,
        storage_mb=128_000,
        android_ver="13",
    ),
    "samsung_a53": PhoneHardwareProfile(
        model="Samsung Galaxy A53",
        ram_mb=6_144,
        storage_mb=128_000,
        android_ver="12",
    ),
    "samsung_m20": PhoneHardwareProfile(
        model="Samsung Galaxy M20",
        ram_mb=3_072,
        storage_mb=32_000,
        android_ver="10",
    ),
    "default": PhoneHardwareProfile(
        model="Generic Android (assumed 6GB RAM / 128GB)",
        ram_mb=6_144,
        storage_mb=128_000,
        android_ver="12",
    ),
}

# OS + system overhead reserved before app clones
RAM_OS_RESERVE_MB  = 2_200   # Android OS + launcher + background services
STORAGE_OS_RESERVE_MB = 12_000  # OS partition


# ---------------------------------------------------------------------------
# Capacity report
# ---------------------------------------------------------------------------

@dataclass
class PlatformAllocation:
    platform:          str
    max_accounts:      int
    start_accounts:    int
    execution_mode:    str
    storage_mb:        int     # total storage for all clones of this platform
    peak_ram_mb:       int     # RAM when this platform's worker is active
    is_free:           bool    # True = no extra resource cost (e.g. Threads)
    notes:             str


@dataclass
class CapacityReport:
    phone_model:         str
    phone_count:         int
    platforms_requested: list[str]
    allocations:         list[PlatformAllocation]
    unsupported:         list[str]   # platforms not in OFM build
    general_brand_only:  list[str]   # platforms available in general brand only
    warnings:            list[str]
    # Totals per phone
    total_accounts_per_phone:  int
    total_storage_mb_per_phone: int
    storage_available_mb:       int
    peak_concurrent_ram_mb:     int
    ram_available_mb:           int
    storage_ok:                 bool
    ram_ok:                     bool
    # Totals across the whole farm
    total_accounts_fleet:       int

    def render(self) -> str:
        """Human-readable report string."""
        lines = []
        lines.append("=" * 60)
        lines.append("  PHANTOM FLEET — CAPACITY PLAN")
        lines.append("=" * 60)
        lines.append(f"  Phone:       {self.phone_model}")
        lines.append(f"  Farm size:   {self.phone_count} phones")
        lines.append("")

        lines.append("  PLATFORM BREAKDOWN (per phone)")
        lines.append("  " + "-" * 56)
        for a in self.allocations:
            free_tag = "  ← free (shares IG session)" if a.is_free else ""
            lines.append(
                f"  {a.platform:<12}  {a.start_accounts:>2} start  /  {a.max_accounts:>2} ceiling"
                f"  [{a.execution_mode.replace('_', ' ')}]{free_tag}"
            )
        lines.append("  " + "-" * 56)
        lines.append(f"  {'TOTAL':<12}  {self._start_total():>2} start  /  {self.total_accounts_per_phone:>2} ceiling  per phone")
        lines.append("")

        lines.append("  RESOURCE CHECK (per phone)")
        storage_pct = int(self.total_storage_mb_per_phone / self.storage_available_mb * 100)
        ram_pct     = int(self.peak_concurrent_ram_mb / self.ram_available_mb * 100)
        storage_ok  = "✓" if self.storage_ok else "⚠ OVER LIMIT"
        ram_ok      = "✓" if self.ram_ok     else "⚠ OVER LIMIT"
        lines.append(f"  Storage:  {self.total_storage_mb_per_phone:,} MB used / {self.storage_available_mb:,} MB available  ({storage_pct}%)  {storage_ok}")
        lines.append(f"  Peak RAM: {self.peak_concurrent_ram_mb:,} MB used / {self.ram_available_mb:,} MB available  ({ram_pct}%)  {ram_ok}")
        lines.append("")

        lines.append(f"  FULL FARM TOTAL ({self.phone_count} phones)")
        lines.append("  " + "-" * 56)
        for a in self.allocations:
            fleet_start = a.start_accounts * self.phone_count
            fleet_max   = a.max_accounts   * self.phone_count
            lines.append(f"  {a.platform:<12}  {fleet_start:>4} accounts  (ceiling {fleet_max})")
        lines.append("  " + "-" * 56)
        fleet_start_total = self._start_total() * self.phone_count
        lines.append(f"  {'TOTAL':<12}  {fleet_start_total:>4} accounts  (ceiling {self.total_accounts_fleet})")
        lines.append("")

        if self.unsupported:
            lines.append("  UNSUPPORTED PLATFORMS (not in OFM build)")
            for p in self.unsupported:
                lines.append(f"    ✗  {p}")
            lines.append("")

        if self.general_brand_only:
            lines.append("  GENERAL BRAND ONLY (not in OFM build)")
            for p in self.general_brand_only:
                lines.append(f"    ○  {p}  — available in the B2B / general brand build")
            lines.append("")

        if self.warnings:
            lines.append("  WARNINGS")
            for w in self.warnings:
                lines.append(f"    ⚠  {w}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    def _start_total(self) -> int:
        return sum(a.start_accounts for a in self.allocations)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class CapacityPlanner:
    """
    Core capacity calculation engine.

    Call plan() with:
        platforms    — raw list of platform names from the agency
        phone_model  — key into PHONE_PROFILES (default: "samsung_s10_lite")
        phone_count  — how many phones in the farm
        custom_limits — optional dict overriding max_accounts per platform
                        (for agencies that want to run below the ceiling)
    """

    def plan(
        self,
        platforms: list[str],
        phone_model: str = "samsung_s10_lite",
        phone_count: int = 20,
        custom_limits: Optional[dict[str, int]] = None,
    ) -> CapacityReport:
        hw = PHONE_PROFILES.get(phone_model, PHONE_PROFILES["default"])
        supported, unsupported, general_only = resolve_platforms(platforms)
        warnings: list[str] = []

        allocations: list[PlatformAllocation] = []
        total_storage_mb = 0
        peak_ram_mb = RAM_OS_RESERVE_MB   # start from OS baseline

        # Foreground platforms share one slot — only the heaviest one runs at a time
        # We track peak, not sum, for foreground RAM
        foreground_ram_peak = 0

        for platform in supported:
            profile = PLATFORM_PROFILES.get(platform)
            if profile is None:
                warnings.append(f"No profile found for '{platform}' — skipped.")
                continue

            max_acc = profile.max_accounts
            if custom_limits and platform in custom_limits:
                requested = custom_limits[platform]
                if requested > max_acc:
                    warnings.append(
                        f"{platform}: requested {requested} exceeds safe ceiling "
                        f"{max_acc} — capped at {max_acc}."
                    )
                    requested = max_acc
                max_acc = requested

            start_acc = min(profile.start_accounts, max_acc)
            storage = profile.clone_storage_mb * max_acc
            total_storage_mb += storage

            if profile.execution_mode == "foreground_ui":
                foreground_ram_peak = max(foreground_ram_peak, profile.clone_ram_mb)
            else:
                # Background API workers add their worker RAM
                peak_ram_mb += profile.clone_ram_mb

            allocations.append(PlatformAllocation(
                platform=platform,
                max_accounts=max_acc,
                start_accounts=start_acc,
                execution_mode=profile.execution_mode,
                storage_mb=storage,
                peak_ram_mb=profile.clone_ram_mb * max_acc,
                is_free=profile.threads_free,
                notes=profile.notes,
            ))

        # Add one foreground slot RAM (highest single foreground platform)
        peak_ram_mb += foreground_ram_peak

        # Hardware checks
        storage_available = hw.storage_mb - STORAGE_OS_RESERVE_MB
        ram_available     = hw.ram_mb - RAM_OS_RESERVE_MB
        storage_ok        = total_storage_mb <= storage_available
        ram_ok            = peak_ram_mb <= hw.ram_mb   # vs total RAM (includes OS)

        if not storage_ok:
            warnings.append(
                f"Storage estimate ({total_storage_mb:,} MB) exceeds available "
                f"({storage_available:,} MB). Consider removing lower-priority platforms."
            )

        total_accounts_per_phone = sum(a.max_accounts for a in allocations)
        total_accounts_fleet     = total_accounts_per_phone * phone_count

        # Flag if no platforms resolved
        if not allocations:
            warnings.append("No supported platforms selected — nothing to plan.")

        # Flag dating app combos that hit the foreground bottleneck
        dating_platforms = [a for a in allocations if a.execution_mode == "foreground_ui"]
        tiktok_in = any(a.platform == "tiktok" for a in allocations)
        if tiktok_in and len(dating_platforms) > 1:
            warnings.append(
                "TikTok + multiple dating apps all need the foreground slot. "
                "They share one time window — the scheduler will interleave them. "
                "Total throughput per phone may feel lower than the sum suggests."
            )

        return CapacityReport(
            phone_model=hw.model,
            phone_count=phone_count,
            platforms_requested=platforms,
            allocations=allocations,
            unsupported=unsupported,
            general_brand_only=general_only,
            warnings=warnings,
            total_accounts_per_phone=total_accounts_per_phone,
            total_storage_mb_per_phone=total_storage_mb,
            storage_available_mb=storage_available,
            peak_concurrent_ram_mb=peak_ram_mb,
            ram_available_mb=ram_available,
            storage_ok=storage_ok,
            ram_ok=ram_ok,
            total_accounts_fleet=total_accounts_fleet,
        )
