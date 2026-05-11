"""
Schedule routes — daily TimeSlotScheduler output.

Endpoints:
    GET  /api/schedule/today              — today's schedule for all known personas
    POST /api/schedule/generate           — generate schedule for a specific date + persona

The TimeSlotScheduler is purely deterministic (hash-seeded) so the same
(persona_id, date, phone_assignments) always produce the same schedule.
No DB write needed — the schedule can be regenerated on demand.

phone_assignments format (per scheduler):
    {
        "192.168.1.42:5555": {"instagram": 12, "telegram": 8},
        "192.168.1.43:5555": {"tiktok": 3, "reddit": 5},
    }
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.time_slot_scheduler import (
    TimeSlotScheduler,
    DailySchedule,
    SlotAssignment,
    slot_to_hour,
    is_quiet_hour,
)

log = logging.getLogger("phantom_fleet.api.schedule")

router = APIRouter()


# ---------------------------------------------------------------------------
# Default demo personas (mirrors the personas stub in legacy main.py)
# ---------------------------------------------------------------------------

_DEFAULT_PERSONAS: dict[str, dict] = {
    "tatiana": {
        "timezone": "America/New_York",
        "phone_assignments": {
            "demo-phone-01": {"instagram": 12, "threads": 12, "telegram": 8},
            "demo-phone-02": {"instagram": 12, "reddit": 5, "bluesky": 10},
        },
    },
    "melodie": {
        "timezone": "America/Los_Angeles",
        "phone_assignments": {
            "demo-phone-03": {"instagram": 12, "tiktok": 3, "threads": 12},
            "demo-phone-04": {"instagram": 12, "x": 4, "discord": 4},
        },
    },
}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SlotAssignmentOut(BaseModel):
    slot: int
    hour: int
    minute: int
    platform: str
    phone_serial: str
    persona_id: str
    expected_accounts: int
    is_quiet_hour: bool


class DailyScheduleOut(BaseModel):
    persona_id: str
    date_iso: str
    timezone: str
    proxy_budget_per_slot: int
    total_assignments: int
    assignments: list[SlotAssignmentOut]


class TodayScheduleOut(BaseModel):
    date_iso: str
    generated_at: str
    schedules: list[DailyScheduleOut]


class GenerateScheduleRequest(BaseModel):
    persona_id: str
    date_iso: Optional[str] = Field(
        default=None,
        description="ISO date YYYY-MM-DD. Defaults to today UTC.",
    )
    timezone: str = "America/New_York"
    phone_assignments: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Per-phone account counts: {serial: {platform: count}}",
    )
    proxy_budget_per_slot: int = Field(default=8, ge=1, le=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assignment_out(a: SlotAssignment) -> SlotAssignmentOut:
    h, m = slot_to_hour(a.slot)
    return SlotAssignmentOut(
        slot=a.slot,
        hour=h,
        minute=m,
        platform=a.platform,
        phone_serial=a.phone_serial,
        persona_id=a.persona_id,
        expected_accounts=a.expected_accounts,
        is_quiet_hour=is_quiet_hour(a.slot),
    )


def _schedule_out(sched: DailySchedule) -> DailyScheduleOut:
    return DailyScheduleOut(
        persona_id=sched.persona_id,
        date_iso=sched.date_iso,
        timezone=sched.timezone,
        proxy_budget_per_slot=sched.proxy_budget_per_slot,
        total_assignments=len(sched.assignments),
        assignments=[_assignment_out(a) for a in sched.assignments],
    )


def _build_schedule_for_persona(
    persona_id: str,
    persona_cfg: dict,
    date_iso: str,
) -> DailySchedule:
    scheduler = TimeSlotScheduler(
        persona_id=persona_id,
        timezone=persona_cfg["timezone"],
        phone_assignments=persona_cfg["phone_assignments"],
    )
    return scheduler.build_schedule(date_iso)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/today", response_model=TodayScheduleOut)
async def today_schedule() -> TodayScheduleOut:
    """
    Build today's schedule for all default personas.
    Deterministic — same output if called multiple times on the same day.
    """
    today = date.today().isoformat()
    schedules: list[DailyScheduleOut] = []

    for persona_id, cfg in _DEFAULT_PERSONAS.items():
        sched = _build_schedule_for_persona(persona_id, cfg, today)
        schedules.append(_schedule_out(sched))

    return TodayScheduleOut(
        date_iso=today,
        generated_at=datetime.now(timezone.utc).isoformat(),
        schedules=schedules,
    )


@router.post("/generate", response_model=DailyScheduleOut)
async def generate_schedule(body: GenerateScheduleRequest) -> DailyScheduleOut:
    """
    Generate a schedule for a specific (persona, date, phone_assignments) combination.

    If phone_assignments is empty, falls back to the default demo assignments
    for that persona_id if it exists in the built-in persona registry.
    """
    date_iso = body.date_iso or date.today().isoformat()

    phone_assignments = body.phone_assignments
    if not phone_assignments:
        # Fall back to demo persona config if available
        demo = _DEFAULT_PERSONAS.get(body.persona_id)
        if demo:
            phone_assignments = demo["phone_assignments"]
        else:
            phone_assignments = {}

    scheduler = TimeSlotScheduler(
        persona_id=body.persona_id,
        timezone=body.timezone,
        phone_assignments=phone_assignments,
        proxy_budget_per_slot=body.proxy_budget_per_slot,
    )
    sched = scheduler.build_schedule(date_iso)

    log.info(
        "Generated schedule for persona=%s date=%s assignments=%d",
        body.persona_id, date_iso, len(sched.assignments),
    )
    return _schedule_out(sched)
