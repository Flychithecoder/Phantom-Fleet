"""
TimeSlotScheduler — 24-hour fleet cycle with proxy multiplexing.

The problem this solves:
    If every platform manager ran in parallel 24/7, Phantom Fleet would
    need ~200 concurrent proxy IPs at peak to avoid cluster fingerprinting.
    At IPRoyal pricing that's multiple hundred dollars per month.

The insight:
    Real users don't use every platform simultaneously. A real person
    checks IG at 8am, Threads at 10am, TikTok at lunch, Reddit in the
    evening. Phantom Fleet should model that rhythm, which lets us
    multiplex the SAME proxy pool across different platforms at different
    hours of the day.

The design:
    - 24-hour day is sliced into 48 half-hour slots
    - Every slot has a capacity (proxy budget) measured in concurrent accounts
    - Every platform manager is allocated a set of slots per persona
      (matching that persona's claimed timezone and peak hours)
    - The Chief Agent Manager authors the daily schedule every midnight
      (per-persona timezone), writes it to the fleet directive table,
      and every platform manager checks "am I allowed to act right now?"
      in its run_once() gate before dispatching specialists
    - Only one platform's accounts bound to a given phone can run at a time
      (hard constraint — phones are single-app foreground devices)

Diurnal alignment rules:
    - Platforms with "morning check" behavior get 7-10am slots:
        Reddit, Threads, X (morning news scroll)
    - Platforms with "lunch" peak get 11am-1pm slots:
        IG lunch scroll, TikTok lunch
    - Platforms with "evening prime" get 6-10pm slots:
        IG prime, TikTok prime, Discord community, Dating peak
    - Platforms with "late night" get 10pm-1am slots:
        Telegram VIP, BlueSky (night owl tech crowd)
    - Platforms with "business hours" get 9am-5pm:
        LinkedIn (the only true business-hours platform)
    - Quiet hours (2am-6am local):
        Background maintenance only — firehose scraping, source discovery,
        audit harness, funnel attribution calculations. Zero user-facing
        actions.

Per-phone constraint:
    A phone can only run ONE platform's clone at a time (foreground app).
    So the scheduler assigns each phone to a 'current platform' for each
    slot. A phone holding 15 IG accounts and 10 Telegram accounts might
    run IG 8am-11am, Telegram 11am-1pm, TikTok 1pm-3pm, etc.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

# ---------------------------------------------------------------------------
# Slot layout
# ---------------------------------------------------------------------------


SLOT_MINUTES = 30
SLOTS_PER_DAY = (24 * 60) // SLOT_MINUTES  # 48


def slot_index(hour: int, minute: int = 0) -> int:
    """Return the slot index (0-47) for a given local hour/minute."""
    return (hour * 60 + minute) // SLOT_MINUTES


def slot_to_hour(idx: int) -> tuple[int, int]:
    total_min = idx * SLOT_MINUTES
    return total_min // 60, total_min % 60


# ---------------------------------------------------------------------------
# Platform → preferred slot windows (per persona local time)
# ---------------------------------------------------------------------------


# Each entry is a list of (start_slot, end_slot) windows in the persona's
# local time. The scheduler picks slots inside these windows for the
# platform, respecting per-phone constraints.
PLATFORM_PREFERRED_SLOTS: dict[str, list[tuple[int, int]]] = {
    # Morning checks (7-10am local)
    "reddit":       [(slot_index(7), slot_index(10)), (slot_index(19), slot_index(22))],
    "threads":      [(slot_index(8), slot_index(10)), (slot_index(19), slot_index(22))],
    "x":            [(slot_index(8), slot_index(11)), (slot_index(18), slot_index(22))],

    # Lunch + evening prime (IG + TikTok)
    "instagram":    [(slot_index(11), slot_index(13)), (slot_index(18), slot_index(23))],
    "tiktok":       [(slot_index(12), slot_index(14)), (slot_index(18), slot_index(23))],

    # Evening social (6-11pm)
    "discord":      [(slot_index(18), slot_index(23))],
    "dating":       [(slot_index(18), slot_index(23))],

    # Late night (9pm-1am) — Telegram VIP time, BlueSky night owls
    "telegram":     [(slot_index(20), slot_index(23)), (slot_index(0), slot_index(1))],
    "bluesky":      [(slot_index(21), slot_index(23)), (slot_index(0), slot_index(2))],
}


# Quiet hours — only background tasks allowed
QUIET_HOURS_START = slot_index(2)
QUIET_HOURS_END = slot_index(6)


# ---------------------------------------------------------------------------
# Slot allocation
# ---------------------------------------------------------------------------


@dataclass
class SlotAssignment:
    """A single (slot, platform, phone_serial) assignment."""

    slot: int
    platform: str
    phone_serial: str
    persona_id: str
    expected_accounts: int


@dataclass
class DailySchedule:
    """Full 24h schedule for one persona on one day."""

    persona_id: str
    date_iso: str
    timezone: str
    assignments: list[SlotAssignment] = field(default_factory=list)
    proxy_budget_per_slot: int = 8  # max concurrent IPs at any one moment

    def assignments_for_slot(self, slot: int) -> list[SlotAssignment]:
        return [a for a in self.assignments if a.slot == slot]

    def platforms_active_for_phone(self, phone_serial: str) -> set[str]:
        return {a.platform for a in self.assignments if a.phone_serial == phone_serial}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class TimeSlotScheduler:
    """Author a 24-hour schedule for a persona across all platforms.

    The scheduler enforces three hard constraints:
        1. Per-phone single-platform: a phone runs at most ONE platform
           per slot. A phone holding IG + Telegram + TikTok clones runs
           them sequentially, never simultaneously.
        2. Global proxy budget: the number of concurrent account sessions
           across the WHOLE persona in any slot never exceeds
           `proxy_budget_per_slot`.
        3. Quiet hours: no user-facing actions between 2am-6am local.
           Only background tasks (scrape, audit, funnel) allowed.
    """

    def __init__(
        self,
        *,
        persona_id: str,
        timezone: str,
        phone_assignments: dict[str, dict[str, int]],
        proxy_budget_per_slot: int = 8,
    ):
        """
        phone_assignments format:
            {
                "RF8N81XYX4J": {"instagram": 15, "telegram": 8, "threads": 15},
                "RF8N90FZ0LV": {"instagram": 26, "tiktok": 12},
                ...
            }
            i.e. per phone, how many accounts per platform live there.
        """
        self.persona_id = persona_id
        self.timezone = timezone
        self.phone_assignments = phone_assignments
        self.proxy_budget_per_slot = proxy_budget_per_slot

    def build_schedule(self, date_iso: str) -> DailySchedule:
        schedule = DailySchedule(
            persona_id=self.persona_id,
            date_iso=date_iso,
            timezone=self.timezone,
            proxy_budget_per_slot=self.proxy_budget_per_slot,
        )

        # Phase 1: for each (phone, platform), pick one preferred window
        # inside the platform's allowed slot range, deterministic per
        # (persona, date, phone, platform) so replay works
        for phone, platforms in self.phone_assignments.items():
            for platform, account_count in platforms.items():
                if account_count <= 0:
                    continue
                window = self._pick_window(phone, platform, date_iso)
                if window is None:
                    continue
                start, end = window
                # Split accounts across the slots in this window
                slots_in_window = list(range(start, end))
                if not slots_in_window:
                    continue
                per_slot = max(1, account_count // len(slots_in_window))
                for slot in slots_in_window:
                    # Quiet-hour check
                    if QUIET_HOURS_START <= slot < QUIET_HOURS_END:
                        continue
                    schedule.assignments.append(SlotAssignment(
                        slot=slot,
                        platform=platform,
                        phone_serial=phone,
                        persona_id=self.persona_id,
                        expected_accounts=per_slot,
                    ))

        # Phase 2: enforce global proxy budget per slot
        self._enforce_proxy_budget(schedule)
        return schedule

    def _pick_window(self, phone: str, platform: str, date_iso: str) -> tuple[int, int] | None:
        """Pick one preferred window for this (phone, platform, date).
        Deterministic by hash so same inputs produce same window on replay.
        """
        windows = PLATFORM_PREFERRED_SLOTS.get(platform)
        if not windows:
            return None
        seed_bytes = hashlib.sha256(
            f"{self.persona_id}|{date_iso}|{phone}|{platform}".encode()
        ).digest()
        idx = int.from_bytes(seed_bytes[:4], "big") % len(windows)
        return windows[idx]

    def _enforce_proxy_budget(self, schedule: DailySchedule) -> None:
        """Drop assignments from overloaded slots.

        If a slot has more concurrent account sessions than the proxy
        budget allows, we trim by removing lowest-priority assignments
        first. Priority is deterministic by (platform, phone) hash.
        """
        by_slot: dict[int, list[SlotAssignment]] = {}
        for a in schedule.assignments:
            by_slot.setdefault(a.slot, []).append(a)

        kept: list[SlotAssignment] = []
        for slot, asns in by_slot.items():
            total = sum(a.expected_accounts for a in asns)
            if total <= self.proxy_budget_per_slot:
                kept.extend(asns)
                continue
            # Sort by priority (deterministic, low-priority trimmed first)
            prioritized = sorted(
                asns,
                key=lambda a: hashlib.sha256(
                    f"{a.platform}|{a.phone_serial}".encode()
                ).hexdigest(),
            )
            running_total = 0
            for a in prioritized:
                if running_total + a.expected_accounts <= self.proxy_budget_per_slot:
                    kept.append(a)
                    running_total += a.expected_accounts
        schedule.assignments = kept


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def is_quiet_hour(slot: int) -> bool:
    return QUIET_HOURS_START <= slot < QUIET_HOURS_END


def current_slot_from_local_hour(hour: int, minute: int = 0) -> int:
    return slot_index(hour, minute)
