"""Tests for the CapacityPlanner and plan_from_request helper."""
import pytest

from phantom_fleet.core.capacity_planner import (
    CapacityPlanner,
    CapacityReport,
    resolve_platforms,
    PLATFORM_PROFILES,
    PHONE_PROFILES,
)
from phantom_fleet.agents.capacity_planner_agent import plan_from_request


# ---------------------------------------------------------------------------
# Platform alias resolver
# ---------------------------------------------------------------------------

def test_resolve_instagram_aliases():
    supported, _, _ = resolve_platforms(["ig"])
    assert "instagram" in supported
    # Threads should auto-add when IG is selected
    assert "threads" in supported

def test_resolve_tg_alias():
    supported, _, _ = resolve_platforms(["tg"])
    assert "telegram" in supported

def test_resolve_twitter_alias():
    supported, _, _ = resolve_platforms(["twitter"])
    assert "x" in supported

def test_resolve_bsky_alias():
    supported, _, _ = resolve_platforms(["bsky"])
    assert "bluesky" in supported

def test_resolve_dating_bundle():
    supported, _, _ = resolve_platforms(["dating"])
    for p in ("tinder", "bumble", "hinge", "grindr"):
        assert p in supported

def test_resolve_snapchat_unsupported():
    supported, unsupported, _ = resolve_platforms(["snap"])
    assert "snap" in unsupported
    assert len(supported) == 0

def test_resolve_facebook_unsupported():
    _, unsupported, _ = resolve_platforms(["facebook"])
    assert "facebook" in unsupported

def test_resolve_linkedin_general_brand_only():
    supported, _, general_only = resolve_platforms(["linkedin"])
    assert len(supported) == 0
    assert "linkedin" in general_only

def test_resolve_no_duplicates():
    # IG added twice + via alias
    supported, _, _ = resolve_platforms(["ig", "instagram", "instagram"])
    assert supported.count("instagram") == 1

def test_threads_added_once_with_ig():
    supported, _, _ = resolve_platforms(["instagram", "threads"])
    assert supported.count("threads") == 1


# ---------------------------------------------------------------------------
# CapacityPlanner core
# ---------------------------------------------------------------------------

def plan(platforms, phone_count=20, phone_model="samsung_s10_lite", custom_limits=None):
    return CapacityPlanner().plan(
        platforms=platforms,
        phone_model=phone_model,
        phone_count=phone_count,
        custom_limits=custom_limits,
    )


def test_instagram_only_plan():
    report = plan(["instagram"])
    ig = next(a for a in report.allocations if a.platform == "instagram")
    th = next(a for a in report.allocations if a.platform == "threads")
    assert ig.max_accounts == 12
    assert th.max_accounts == 12
    assert th.is_free is True   # Threads shares IG session — no extra storage cost
    assert th.storage_mb == 0   # zero disk — no separate clone needed


def test_full_ofm_stack():
    """Typical OFM agency: IG + Reddit + TikTok + Telegram + Grindr."""
    report = plan(["ig", "reddit", "tiktok", "tg", "grindr"])
    platforms = {a.platform for a in report.allocations}
    assert "instagram" in platforms
    assert "threads" in platforms   # auto-added
    assert "reddit" in platforms
    assert "tiktok" in platforms
    assert "telegram" in platforms
    assert "grindr" in platforms


def test_account_ceilings_match_profiles():
    report = plan(list(PLATFORM_PROFILES.keys()))
    for allocation in report.allocations:
        profile = PLATFORM_PROFILES[allocation.platform]
        assert allocation.max_accounts == profile.max_accounts


def test_custom_limit_respected():
    report = plan(["instagram"], custom_limits={"instagram": 8})
    ig = next(a for a in report.allocations if a.platform == "instagram")
    assert ig.max_accounts == 8


def test_custom_limit_capped_at_ceiling():
    """If agency requests more than the safe ceiling, cap it and warn."""
    report = plan(["tiktok"], custom_limits={"tiktok": 10})
    tiktok = next(a for a in report.allocations if a.platform == "tiktok")
    assert tiktok.max_accounts == 3   # capped at ceiling
    assert any("capped" in w for w in report.warnings)


def test_fleet_total_calculation():
    report = plan(["instagram"], phone_count=20)
    ig = next(a for a in report.allocations if a.platform == "instagram")
    threads = next(a for a in report.allocations if a.platform == "threads")
    expected = (ig.max_accounts + threads.max_accounts) * 20
    assert report.total_accounts_fleet == expected


def test_phone_count_reflected():
    r20 = plan(["instagram"], phone_count=20)
    r17 = plan(["instagram"], phone_count=17)
    assert r20.total_accounts_fleet > r17.total_accounts_fleet
    assert r20.phone_count == 20
    assert r17.phone_count == 17


def test_storage_check_passes_typical_load():
    """Normal OFM stack should fit easily in 128GB."""
    report = plan(["instagram", "reddit", "tiktok", "telegram", "grindr"])
    assert report.storage_ok, (
        f"Storage exceeded: {report.total_storage_mb_per_phone}MB / "
        f"{report.storage_available_mb}MB"
    )


def test_ram_check_passes():
    report = plan(list(PLATFORM_PROFILES.keys()))
    assert report.ram_ok, (
        f"RAM exceeded: {report.peak_concurrent_ram_mb}MB peak"
    )


def test_unsupported_platforms_surfaced():
    report = plan(["instagram", "snap", "youtube"])
    assert "snap" in report.unsupported
    assert "youtube" in report.unsupported


def test_general_brand_only_surfaced():
    report = plan(["instagram", "linkedin"])
    assert "linkedin" in report.general_brand_only


def test_render_produces_non_empty_string():
    report = plan(["ig", "tg", "grindr"])
    text = report.render()
    assert "PHANTOM FLEET" in text
    assert "instagram" in text
    assert "telegram" in text
    assert "grindr" in text
    assert "FULL FARM TOTAL" in text


def test_empty_plan_warns():
    report = plan([])
    assert any("No supported platforms" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# plan_from_request (natural language shortcut)
# ---------------------------------------------------------------------------

def test_plan_from_natural_language_basic():
    report = plan_from_request("I want Instagram, Threads and Telegram")
    platforms = {a.platform for a in report.allocations}
    assert "instagram" in platforms
    assert "telegram" in platforms


def test_plan_from_aliases():
    report = plan_from_request("ig, tg, tiktok, grindr")
    platforms = {a.platform for a in report.allocations}
    assert "instagram" in platforms
    assert "telegram" in platforms
    assert "tiktok" in platforms
    assert "grindr" in platforms


def test_plan_from_request_with_phone_count():
    report = plan_from_request("IG and Reddit", phone_count=17)
    assert report.phone_count == 17
    assert report.total_accounts_fleet == (
        sum(a.max_accounts for a in report.allocations) * 17
    )


def test_plan_from_request_flags_snap():
    report = plan_from_request("instagram, snap, twitter")
    assert "snap" in report.unsupported


def test_plan_from_request_dating_bundle():
    report = plan_from_request("IG, dating apps and telegram")
    platforms = {a.platform for a in report.allocations}
    for p in ("tinder", "bumble", "hinge", "grindr"):
        assert p in platforms


# ---------------------------------------------------------------------------
# Specific platform ceiling assertions (regression tests)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("platform,expected_ceiling", [
    ("instagram", 12),
    ("threads",   12),
    ("telegram",  10),
    ("bluesky",   15),
    ("reddit",     8),
    ("x",          6),
    ("discord",    6),
    ("grindr",     8),
    ("tiktok",     3),
    ("tinder",     3),
    ("bumble",     3),
    ("hinge",      2),
])
def test_platform_ceiling(platform, expected_ceiling):
    report = plan([platform])
    alloc = next((a for a in report.allocations if a.platform == platform), None)
    assert alloc is not None, f"No allocation found for {platform}"
    assert alloc.max_accounts == expected_ceiling, (
        f"{platform}: expected ceiling {expected_ceiling}, got {alloc.max_accounts}"
    )
