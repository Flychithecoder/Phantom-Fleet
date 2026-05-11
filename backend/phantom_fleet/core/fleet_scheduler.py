"""
FleetScheduler — 24-hour schedule coordinator for the entire fleet.

Key responsibility: ensure actions are spread across the diurnal curve
matching the *claimed timezone* of each account.

An account claiming NYC timezone should be most active 9am–11pm EST,
not all at 3am UTC.

Time windows (all in ACCOUNT LOCAL TIME):
    Morning   07:00–11:00  →  story_session
    Afternoon 13:00–17:00  →  follow_session  (2-4hr gap after morning)
    Evening   18:00–22:00  →  post, dm_check
    Quiet     23:00–07:00  →  NO actions (hard-enforced)

Each window is subdivided into jittered per-account slots so that
action bursts don't align at the window boundary (avoids timing clusters).
"""
from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUIET_START_HOUR = 23    # 11pm local — no actions after this
QUIET_END_HOUR   = 7     # 7am  local — no actions before this

# Action-type windows (hour_start, hour_end, exclusive)
_WINDOWS: dict[str, tuple[int, int]] = {
    "story_session": (7,  11),
    "follow_session": (13, 17),
    "post":           (18, 22),
    "dm_check":       (18, 22),
    "unfollow_session": (14, 18),
}

_PRIORITY_MAP: dict[str, int] = {
    "story_session":    2,
    "follow_session":   2,
    "unfollow_session": 3,
    "post":             2,
    "dm_check":         1,   # highest priority for revenue actions
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ScheduledAction:
    """One scheduled action for one account on one phone."""

    action_id:         str
    account_id:        str
    platform:          str
    action_type:       str          # "story_session" | "follow_session" | "post" | "dm_check" etc.
    scheduled_at_unix: float        # when to run (epoch seconds)
    priority:          int          # 1=highest, 5=lowest
    phone_serial:      str
    params:            dict = field(default_factory=dict)

    @property
    def scheduled_at_iso(self) -> str:
        return datetime.fromtimestamp(self.scheduled_at_unix, tz=timezone.utc).isoformat()


@dataclass
class FleetDailySchedule:
    """Full day's schedule for the entire fleet."""

    date_iso:  str
    actions:   list[ScheduledAction] = field(default_factory=list)
    built_at:  str = ""

    def actions_for_account(self, account_id: str) -> list[ScheduledAction]:
        return [a for a in self.actions if a.account_id == account_id]

    def actions_for_platform(self, platform: str) -> list[ScheduledAction]:
        return [a for a in self.actions if a.platform == platform]

    def pending_at(self, now_unix: float) -> list[ScheduledAction]:
        """Return actions due at or before now, sorted by priority then time."""
        due = [a for a in self.actions if a.scheduled_at_unix <= now_unix]
        return sorted(due, key=lambda a: (a.priority, a.scheduled_at_unix))


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class FleetScheduler:
    """
    Coordinates timing across the entire fleet.

    Usage:
        scheduler = FleetScheduler()
        schedule  = await scheduler.build_fleet_schedule("2026-04-11")
        actions   = await scheduler.get_next_actions(datetime.now(tz=timezone.utc))
    """

    def __init__(self) -> None:
        self._schedule: FleetDailySchedule | None = None
        self._completed_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Build schedule
    # ------------------------------------------------------------------

    async def build_fleet_schedule(
        self,
        date_iso: str,
        accounts: list[dict] | None = None,
    ) -> FleetDailySchedule:
        """
        Build today's full fleet schedule.

        accounts: list of dicts with keys:
            account_id, platform, phone_serial, timezone_offset_hours (int)
            Optional: action_types (list[str]) — override defaults
        """
        accounts = accounts or []
        schedule = FleetDailySchedule(
            date_iso=date_iso,
            built_at=datetime.now(tz=timezone.utc).isoformat(),
        )

        for acct in accounts:
            account_id     = acct.get("account_id", str(uuid.uuid4()))
            platform       = acct.get("platform", "instagram")
            phone_serial   = acct.get("phone_serial", "unknown")
            tz_offset_hrs  = acct.get("timezone_offset_hours", -5)   # default EST
            action_types   = acct.get("action_types") or list(_WINDOWS.keys())
            extra_params   = acct.get("params", {})

            for action_type in action_types:
                if action_type not in _WINDOWS:
                    continue

                scheduled_at = self._schedule_action(
                    date_iso=date_iso,
                    action_type=action_type,
                    account_id=account_id,
                    tz_offset_hrs=tz_offset_hrs,
                )
                if scheduled_at is None:
                    continue  # quiet hours

                schedule.actions.append(
                    ScheduledAction(
                        action_id=_deterministic_id(account_id, action_type, date_iso),
                        account_id=account_id,
                        platform=platform,
                        action_type=action_type,
                        scheduled_at_unix=scheduled_at,
                        priority=_PRIORITY_MAP.get(action_type, 3),
                        phone_serial=phone_serial,
                        params=extra_params,
                    )
                )

        self._schedule = schedule
        self._completed_ids.clear()
        return schedule

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    async def get_next_actions(self, now: datetime) -> list[ScheduledAction]:
        """Return due actions sorted by priority then scheduled time."""
        if self._schedule is None:
            return []
        now_unix = now.timestamp()
        return [
            a for a in self._schedule.pending_at(now_unix)
            if a.action_id not in self._completed_ids
        ]

    async def mark_completed(self, action_id: str) -> None:
        self._completed_ids.add(action_id)

    async def get_pending_count(self) -> int:
        if self._schedule is None:
            return 0
        now_unix = datetime.now(tz=timezone.utc).timestamp()
        return sum(
            1 for a in self._schedule.actions
            if a.action_id not in self._completed_ids and a.scheduled_at_unix > now_unix
        )

    def current_schedule(self) -> FleetDailySchedule | None:
        return self._schedule

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _schedule_action(
        self,
        date_iso: str,
        action_type: str,
        account_id: str,
        tz_offset_hrs: int,
    ) -> float | None:
        """
        Pick a time within the action's window, jittered per account.

        Returns UTC epoch seconds, or None if the window is in quiet hours.
        """
        hour_start, hour_end = _WINDOWS[action_type]

        # Enforce quiet hours in LOCAL time
        if _is_quiet_window(hour_start, hour_end):
            return None

        # Jitter within window: use account_id hash for determinism
        window_sec  = (hour_end - hour_start) * 3600
        jitter_frac = _hash_fraction(account_id + action_type + date_iso)
        offset_sec  = int(jitter_frac * window_sec)

        # Build local datetime at window start + jitter
        year, month, day = map(int, date_iso.split("-"))
        local_naive = datetime(year, month, day, hour_start, 0, 0)
        local_naive += timedelta(seconds=offset_sec)

        # Convert to UTC
        utc_offset = timedelta(hours=tz_offset_hrs)
        utc_dt = local_naive - utc_offset
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)

        return utc_dt.timestamp()


# ---------------------------------------------------------------------------
# Quiet-hours enforcement
# ---------------------------------------------------------------------------

def is_quiet_hour(local_hour: int) -> bool:
    """
    Return True if local_hour is in the no-action window (11pm–7am).
    QUIET_START_HOUR=23, QUIET_END_HOUR=7.
    """
    if QUIET_START_HOUR > QUIET_END_HOUR:
        # Wraps midnight
        return local_hour >= QUIET_START_HOUR or local_hour < QUIET_END_HOUR
    return QUIET_START_HOUR <= local_hour < QUIET_END_HOUR


def _is_quiet_window(hour_start: int, hour_end: int) -> bool:
    """Return True if the entire window falls within quiet hours."""
    return all(is_quiet_hour(h) for h in range(hour_start, hour_end))


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _hash_fraction(seed: str) -> float:
    """Deterministic float in [0, 1) from a string seed."""
    digest = hashlib.sha256(seed.encode()).digest()
    value  = int.from_bytes(digest[:4], "big")
    return value / (2**32)


def _deterministic_id(account_id: str, action_type: str, date_iso: str) -> str:
    raw = f"{account_id}:{action_type}:{date_iso}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
