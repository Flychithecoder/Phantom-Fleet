"""
Platform specs — Phase 2 parity expansion.

Per-platform configuration: warming curve, action primitives, companion-APK
needs, account provisioning source, cost/account. One PlatformSpec per
platform the fleet can act on; the Phase 2 readiness dashboard reads these.

Each platform is a scaffold until the companion APK primitives + warming
curve + funnel path are live. The `status` field is what the readiness gate
pings — "scaffold" | "primitives" | "warming" | "ready".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PlatformStatus = Literal["scaffold", "primitives", "warming", "ready"]


@dataclass(frozen=True)
class PlatformSpec:
    key:              str
    display_name:     str
    phase:            int                       # Earliest phase this platform targets
    account_source:   str                       # "aged" | "self_created" | "linked" | "sim_required"
    account_cost_usd: tuple[float, float]       # (low, high) per account
    warming_days:     int                       # Length of warming curve, days
    companion_apk:    bool                      # Requires platform-specific APK primitives
    funnel_path:      str                       # Human-readable funnel path
    status:           PlatformStatus = "scaffold"
    notes:            str = ""


# Phase 1 anchor (IG is already the baseline; included here for parity math).
IG = PlatformSpec(
    key="instagram",      display_name="Instagram",
    phase=1, account_source="aged", account_cost_usd=(2.0, 15.0),
    warming_days=28, companion_apk=True,
    funnel_path="Bio link → Linktree → OF/Fanvue",
    status="warming",     notes="Phase 1 baseline; 28-day warming curve LOCKED 2026-04-11.",
)

# Phase 2 — parity expansion
THREADS = PlatformSpec(
    key="threads",        display_name="Threads",
    phase=2, account_source="linked", account_cost_usd=(0.0, 0.0),
    warming_days=14, companion_apk=True,
    funnel_path="IG cross-post → Threads reply → bio link",
    status="warming",     notes="14-day LogNormal warming curve; 4 action primitives wired.",
)

REDDIT = PlatformSpec(
    key="reddit",         display_name="Reddit",
    phase=2, account_source="aged", account_cost_usd=(0.5, 2.0),
    warming_days=21, companion_apk=True,
    funnel_path="Subreddit post → profile view → DM → bio link",
    status="scaffold",    notes="Cheapest aged-account market. Loose detection; shorter warm.",
)

TIKTOK = PlatformSpec(
    key="tiktok",         display_name="TikTok",
    phase=2, account_source="aged", account_cost_usd=(8.0, 30.0),
    warming_days=21, companion_apk=True,
    funnel_path="Bio link → mass follow → DM → OF",
    status="scaffold",    notes="Needs FBR tracking in companion APK.",
)

SNAPCHAT = PlatformSpec(
    key="snapchat",       display_name="Snapchat",
    phase=2, account_source="sim_required", account_cost_usd=(10.0, 40.0),
    warming_days=30, companion_apk=True,
    funnel_path="Snap add → AI chat → CTA → OF",
    status="scaffold",    notes="Real SIM required — hardest Phase 2 unlock.",
)

X = PlatformSpec(
    key="x",              display_name="X / Twitter",
    phase=2, account_source="aged", account_cost_usd=(3.0, 20.0),
    warming_days=21, companion_apk=False,     # Web path via x-panel/
    funnel_path="Bio link → reply engagement → DM",
    status="scaffold",    notes="Routes through existing x-panel/ + Xmator web pattern.",
)


PHASE_2_PLATFORMS: tuple[PlatformSpec, ...] = (THREADS, REDDIT, TIKTOK, SNAPCHAT, X)

# Everything the fleet can touch in this build
ALL_PLATFORMS: tuple[PlatformSpec, ...] = (IG, *PHASE_2_PLATFORMS)


def by_key(key: str) -> PlatformSpec | None:
    for p in ALL_PLATFORMS:
        if p.key == key:
            return p
    return None
