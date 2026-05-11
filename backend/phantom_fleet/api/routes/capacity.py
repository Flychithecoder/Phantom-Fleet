"""
Capacity planner route.

POST /api/capacity-plan
    Body: {request: str, phone_count: int, phone_model: str}

    `request` is a free-text field like "IG, Threads, TikTok, Telegram"
    that gets tokenised by the CapacityPlanner's resolve_platforms() function.

    Returns both the JSON-serialisable CapacityReport fields AND the
    human-readable rendered text string so the frontend can show the
    formatted report without re-rendering it.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.capacity_planner import CapacityPlanner, CapacityReport, PlatformAllocation

log = logging.getLogger("phantom_fleet.api.capacity")

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CapacityPlanRequest(BaseModel):
    request: str = Field(
        ...,
        description=(
            "Free-text list of platforms the agency wants to run, "
            "e.g. 'IG, Threads, TikTok, Telegram, Reddit'"
        ),
    )
    phone_count: int = Field(default=20, ge=1, le=500)
    phone_model: str = Field(default="samsung_s10_lite")
    custom_limits: Optional[dict[str, int]] = Field(
        default=None,
        description="Optional per-platform account limit overrides, e.g. {'tiktok': 2}",
    )


class PlatformAllocationOut(BaseModel):
    platform: str
    max_accounts: int
    start_accounts: int
    execution_mode: str
    storage_mb: int
    peak_ram_mb: int
    is_free: bool
    notes: str


class CapacityReportOut(BaseModel):
    phone_model: str
    phone_count: int
    platforms_requested: list[str]
    allocations: list[PlatformAllocationOut]
    unsupported: list[str]
    general_brand_only: list[str]
    warnings: list[str]
    total_accounts_per_phone: int
    total_storage_mb_per_phone: int
    storage_available_mb: int
    peak_concurrent_ram_mb: int
    ram_available_mb: int
    storage_ok: bool
    ram_ok: bool
    total_accounts_fleet: int
    rendered_text: str    # human-readable formatted report


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _report_to_out(report: CapacityReport) -> CapacityReportOut:
    return CapacityReportOut(
        phone_model=report.phone_model,
        phone_count=report.phone_count,
        platforms_requested=report.platforms_requested,
        allocations=[
            PlatformAllocationOut(
                platform=a.platform,
                max_accounts=a.max_accounts,
                start_accounts=a.start_accounts,
                execution_mode=a.execution_mode,
                storage_mb=a.storage_mb,
                peak_ram_mb=a.peak_ram_mb,
                is_free=a.is_free,
                notes=a.notes,
            )
            for a in report.allocations
        ],
        unsupported=report.unsupported,
        general_brand_only=report.general_brand_only,
        warnings=report.warnings,
        total_accounts_per_phone=report.total_accounts_per_phone,
        total_storage_mb_per_phone=report.total_storage_mb_per_phone,
        storage_available_mb=report.storage_available_mb,
        peak_concurrent_ram_mb=report.peak_concurrent_ram_mb,
        ram_available_mb=report.ram_available_mb,
        storage_ok=report.storage_ok,
        ram_ok=report.ram_ok,
        total_accounts_fleet=report.total_accounts_fleet,
        rendered_text=report.render(),
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/capacity-plan", response_model=CapacityReportOut)
async def capacity_plan(body: CapacityPlanRequest) -> CapacityReportOut:
    """
    Run the CapacityPlanner against a free-text platform request.

    Tokenises the `request` string on commas, resolves aliases
    (e.g. "IG" → "instagram"), applies hardware profiles for the
    given phone model, and returns a full capacity report.
    """
    # Tokenise the free-text request
    raw_platforms = [p.strip() for p in body.request.replace("/", ",").split(",") if p.strip()]

    planner = CapacityPlanner()
    report = planner.plan(
        platforms=raw_platforms,
        phone_model=body.phone_model,
        phone_count=body.phone_count,
        custom_limits=body.custom_limits,
    )
    log.info(
        "Capacity plan: %d platforms, %d phones → %d total accounts",
        len(report.allocations),
        body.phone_count,
        report.total_accounts_fleet,
    )
    return _report_to_out(report)
