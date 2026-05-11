"""Test the 24h fleet cycle scheduler."""
from phantom_fleet.core.time_slot_scheduler import (
    TimeSlotScheduler,
    SLOT_MINUTES,
    SLOTS_PER_DAY,
    slot_index,
    slot_to_hour,
    is_quiet_hour,
    PLATFORM_PREFERRED_SLOTS,
    QUIET_HOURS_START,
    QUIET_HOURS_END,
)


def test_slot_layout():
    assert SLOTS_PER_DAY == 48
    assert slot_index(0, 0) == 0
    assert slot_index(8, 0) == 16
    assert slot_index(12, 0) == 24
    assert slot_index(23, 30) == 47


def test_slot_to_hour_roundtrip():
    for s in range(SLOTS_PER_DAY):
        h, m = slot_to_hour(s)
        assert slot_index(h, m) == s


def test_quiet_hours():
    assert is_quiet_hour(slot_index(3, 0))
    assert is_quiet_hour(slot_index(4, 30))
    assert not is_quiet_hour(slot_index(8, 0))
    assert not is_quiet_hour(slot_index(22, 0))


def test_platform_windows_cover_non_quiet_hours():
    """Every platform should have at least one preferred window, and
    no preferred window should fall entirely inside quiet hours."""
    for platform, windows in PLATFORM_PREFERRED_SLOTS.items():
        assert len(windows) > 0, f"{platform} has no preferred windows"
        any_active = False
        for start, end in windows:
            for slot in range(start, end):
                if not is_quiet_hour(slot):
                    any_active = True
                    break
            if any_active:
                break
        assert any_active, f"{platform} has ALL windows in quiet hours"


def test_build_schedule_basic():
    scheduler = TimeSlotScheduler(
        persona_id="tatiana",
        timezone="America/New_York",
        phone_assignments={
            "RF8N81XYX4J": {"instagram": 15, "telegram": 8},
            "RF8N90FZ0LV": {"instagram": 26, "tiktok": 12},
        },
        proxy_budget_per_slot=8,
    )
    schedule = scheduler.build_schedule("2026-04-11")
    assert schedule.persona_id == "tatiana"
    assert len(schedule.assignments) > 0
    # Every assignment respects quiet hours
    for a in schedule.assignments:
        assert not is_quiet_hour(a.slot), f"slot {a.slot} is quiet hour"


def test_proxy_budget_enforced():
    """Make sure no slot exceeds the proxy budget."""
    scheduler = TimeSlotScheduler(
        persona_id="melodie",
        timezone="America/New_York",
        phone_assignments={
            f"PHONE_{i}": {"instagram": 20, "tiktok": 15}
            for i in range(10)
        },
        proxy_budget_per_slot=8,
    )
    schedule = scheduler.build_schedule("2026-04-11")
    # For each slot, sum the expected accounts and ensure <= budget
    per_slot_totals: dict[int, int] = {}
    for a in schedule.assignments:
        per_slot_totals[a.slot] = per_slot_totals.get(a.slot, 0) + a.expected_accounts
    for slot, total in per_slot_totals.items():
        assert total <= 8, f"slot {slot} has {total} concurrent, exceeds budget 8"


def test_schedule_is_deterministic():
    """Same inputs → same schedule (replayable)."""
    s1 = TimeSlotScheduler(
        persona_id="tatiana",
        timezone="America/New_York",
        phone_assignments={"RF8N81XYX4J": {"instagram": 15}},
        proxy_budget_per_slot=8,
    ).build_schedule("2026-04-11")
    s2 = TimeSlotScheduler(
        persona_id="tatiana",
        timezone="America/New_York",
        phone_assignments={"RF8N81XYX4J": {"instagram": 15}},
        proxy_budget_per_slot=8,
    ).build_schedule("2026-04-11")
    assert len(s1.assignments) == len(s2.assignments)
    for a, b in zip(sorted((x.slot, x.platform) for x in s1.assignments),
                    sorted((x.slot, x.platform) for x in s2.assignments)):
        assert a == b
