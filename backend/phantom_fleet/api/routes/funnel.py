"""
DM Funnel API routes.

Endpoints:
    GET  /api/funnel/sequences                   — list all registered sequences
    POST /api/funnel/sequences                   — create and register a new sequence
    GET  /api/funnel/enrollments/{account_id}    — active enrollments for an account
    GET  /api/funnel/stats                       — conversion rates, step completion rates
    POST /api/funnel/enrollments/bulk            — enroll a list of targets into a sequence

Design notes:
    - Sequence registry is in-memory (SEQUENCE_REGISTRY dict in dm_funnel.py).
      A future iteration can back this with Postgres; the dict is the interface.
    - Enrollment sidecar files are read from PHANTOM_STATE_DIR — same location
      the agents use, so API reads are always consistent with agent writes.
    - Stats are computed on-read from sidecar files (no separate aggregation store).
      This is correct for current scale; cache if needed at >10K accounts.
    - All HTTP in tests is mocked at the agent/client layer — this router is
      tested via FastAPI TestClient with sidecar files in a temp directory.
"""
from __future__ import annotations

import glob as _glob
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from ...core.dm_funnel import (
    DEFAULT_OFM_SEQUENCE,
    SEQUENCE_REGISTRY,
    FunnelEnrollment,
    FunnelSequence,
    FunnelStep,
)
from ...core.chat_modes import ChatTier
from ..schemas import (
    SequenceStepIn,
    SequenceCreateIn,
    SequenceOut,
    EnrollmentOut,
    BulkEnrollIn,
    BulkEnrollOut,
    FunnelStatsOut,
)

log = logging.getLogger("phantom_fleet.api.funnel")

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/funnel/sequences
# ---------------------------------------------------------------------------


@router.get("/sequences", response_model=list[SequenceOut])
async def list_sequences() -> list[SequenceOut]:
    """Return all registered funnel sequences."""
    return [_sequence_to_out(seq) for seq in SEQUENCE_REGISTRY.values()]


# ---------------------------------------------------------------------------
# POST /api/funnel/sequences
# ---------------------------------------------------------------------------


@router.post("/sequences", response_model=SequenceOut, status_code=201)
async def create_sequence(body: SequenceCreateIn) -> SequenceOut:
    """
    Create and register a new funnel sequence.

    The sequence is added to SEQUENCE_REGISTRY (in-memory) immediately
    and is available to all running agents. Sequence IDs must be unique.
    """
    if body.sequence_id in SEQUENCE_REGISTRY:
        raise HTTPException(
            status_code=409,
            detail=f"Sequence {body.sequence_id!r} already exists",
        )

    steps: list[FunnelStep] = []
    for i, s in enumerate(body.steps):
        try:
            step = FunnelStep(
                day_offset=s.day_offset,
                action=s.action,
                dm_template_pool=s.dm_template_pool or None,
                condition=s.condition or None,
                max_tokens=s.max_tokens,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Step {i}: {exc}") from exc
        steps.append(step)

    try:
        sequence = FunnelSequence(
            sequence_id=body.sequence_id,
            name=body.name,
            steps=steps,
            chat_tier=ChatTier(body.chat_tier),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    SEQUENCE_REGISTRY[sequence.sequence_id] = sequence
    log.info("Registered new funnel sequence: %s (%s)", sequence.sequence_id, sequence.name)
    return _sequence_to_out(sequence)


# ---------------------------------------------------------------------------
# GET /api/funnel/enrollments/{account_id}
# ---------------------------------------------------------------------------


@router.get("/enrollments/{account_id}", response_model=list[EnrollmentOut])
async def get_enrollments(account_id: str) -> list[EnrollmentOut]:
    """
    Return all active (non-completed, non-converted) enrollments for an account.

    Scans all sidecar files matching funnel_{account_id}_*.json so the caller
    gets a full cross-date view.
    """
    enrollments = _load_all_enrollments(account_id)
    active = [e for e in enrollments if not e.completed and not e.converted]
    return [_enrollment_to_out(e) for e in active]


# ---------------------------------------------------------------------------
# GET /api/funnel/stats
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=FunnelStatsOut)
async def funnel_stats(account_id: Optional[str] = None) -> FunnelStatsOut:
    """
    Return aggregated funnel performance stats.

    Optional query param: account_id — scope stats to one account.
    If omitted, aggregate across all accounts.

    Metrics:
        total_enrolled:     all enrollment records
        total_completed:    enrollments that ran all steps
        total_converted:    enrollments where target DM'd with conversion signal
        conversion_rate:    total_converted / total_enrolled (0.0 if none)
        step_completion_rate: total_completed / total_enrolled
        by_sequence:        per-sequence breakdown
    """
    enrollments = _load_all_enrollments(account_id) if account_id else _load_all_enrollments_all()

    total = len(enrollments)
    completed = sum(1 for e in enrollments if e.completed)
    converted = sum(1 for e in enrollments if e.converted)

    # Per-sequence breakdown
    by_sequence: dict[str, dict] = {}
    for e in enrollments:
        seq_id = e.sequence_id
        if seq_id not in by_sequence:
            by_sequence[seq_id] = {"enrolled": 0, "completed": 0, "converted": 0}
        by_sequence[seq_id]["enrolled"] += 1
        if e.completed:
            by_sequence[seq_id]["completed"] += 1
        if e.converted:
            by_sequence[seq_id]["converted"] += 1

    # Add conversion_rate per sequence
    for seq_id, stats in by_sequence.items():
        n = stats["enrolled"]
        stats["conversion_rate"] = round(stats["converted"] / n, 4) if n else 0.0

    return FunnelStatsOut(
        total_enrolled=total,
        total_completed=completed,
        total_converted=converted,
        conversion_rate=round(converted / total, 4) if total else 0.0,
        step_completion_rate=round(completed / total, 4) if total else 0.0,
        by_sequence=by_sequence,
    )


# ---------------------------------------------------------------------------
# POST /api/funnel/enrollments/bulk
# ---------------------------------------------------------------------------


@router.post("/enrollments/bulk", response_model=BulkEnrollOut, status_code=201)
async def bulk_enroll(body: BulkEnrollIn) -> BulkEnrollOut:
    """
    Enroll a list of targets into a funnel sequence.

    Deduplication is enforced: if a (account_id, target_user_id) pair is already
    enrolled in any sidecar file for that account, it is silently skipped.

    This endpoint is a thin HTTP wrapper over the same dedup logic that
    IGFunnelEnrollmentAgent uses, so results are consistent with agent-level enrollments.
    """
    sequence_id = body.sequence_id or DEFAULT_OFM_SEQUENCE.sequence_id

    if sequence_id not in SEQUENCE_REGISTRY:
        raise HTTPException(
            status_code=422,
            detail=f"Sequence {sequence_id!r} not found in registry",
        )

    account_id = body.account_id
    date_iso = datetime.now(timezone.utc).date().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Load existing targets for dedup
    existing_targets = _load_all_enrolled_target_ids(account_id)

    # Load today's sidecar
    today_path = _sidecar_path(account_id, date_iso)
    today_enrollments = _load_sidecar(today_path)

    enrolled_ids: list[str] = []
    duplicate_skips = 0
    errors: list[str] = []

    for target_id in body.target_user_ids:
        if not target_id:
            errors.append("empty_target_id")
            continue

        if target_id in existing_targets:
            duplicate_skips += 1
            continue

        enrollment = FunnelEnrollment(
            enrollment_id=uuid.uuid4().hex,
            account_id=account_id,
            target_user_id=target_id,
            sequence_id=sequence_id,
            enrolled_at_iso=now_iso,
        )
        today_enrollments.append(enrollment)
        existing_targets.add(target_id)
        enrolled_ids.append(enrollment.enrollment_id)

    _save_sidecar(today_path, today_enrollments)

    return BulkEnrollOut(
        enrolled_count=len(enrolled_ids),
        enrollment_ids=enrolled_ids,
        duplicate_skips=duplicate_skips,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sidecar_path(account_id: str, date_iso: str) -> Path:
    base = Path(os.environ.get("PHANTOM_STATE_DIR", "/tmp/phantom_state"))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"funnel_{account_id}_{date_iso}.json"


def _load_sidecar(path: Path) -> list[FunnelEnrollment]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [FunnelEnrollment.from_dict(d) for d in data]
    except Exception as exc:
        log.warning("[funnel_api] Failed to load sidecar %s: %s", path, exc)
        return []


def _save_sidecar(path: Path, enrollments: list[FunnelEnrollment]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([e.to_dict() for e in enrollments], indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.error("[funnel_api] Failed to save sidecar %s: %s", path, exc)


def _load_all_enrollments(account_id: str) -> list[FunnelEnrollment]:
    """Load all enrollment records for one account across all sidecar dates."""
    base = Path(os.environ.get("PHANTOM_STATE_DIR", "/tmp/phantom_state"))
    pattern = str(base / f"funnel_{account_id}_*.json")
    results: list[FunnelEnrollment] = []
    for filepath in _glob.glob(pattern):
        try:
            data = json.loads(Path(filepath).read_text(encoding="utf-8"))
            results.extend(FunnelEnrollment.from_dict(d) for d in data)
        except Exception as exc:
            log.warning("[funnel_api] Failed to read %s: %s", filepath, exc)
    return results


def _load_all_enrollments_all() -> list[FunnelEnrollment]:
    """Load all enrollment records for all accounts."""
    base = Path(os.environ.get("PHANTOM_STATE_DIR", "/tmp/phantom_state"))
    pattern = str(base / "funnel_*.json")
    results: list[FunnelEnrollment] = []
    for filepath in _glob.glob(pattern):
        try:
            data = json.loads(Path(filepath).read_text(encoding="utf-8"))
            results.extend(FunnelEnrollment.from_dict(d) for d in data)
        except Exception as exc:
            log.warning("[funnel_api] Failed to read %s: %s", filepath, exc)
    return results


def _load_all_enrolled_target_ids(account_id: str) -> set[str]:
    """Return set of all target_user_ids already enrolled for this account."""
    return {e.target_user_id for e in _load_all_enrollments(account_id)}


def _sequence_to_out(seq: FunnelSequence) -> "SequenceOut":
    from ..schemas import SequenceOut, SequenceStepOut

    return SequenceOut(
        sequence_id=seq.sequence_id,
        name=seq.name,
        chat_tier=int(seq.chat_tier),
        step_count=len(seq.steps),
        steps=[
            SequenceStepOut(
                day_offset=s.day_offset,
                action=s.action,
                condition=s.condition,
                template_pool_size=len(s.dm_template_pool) if s.dm_template_pool else 0,
                max_tokens=s.max_tokens,
            )
            for s in seq.steps
        ],
    )


def _enrollment_to_out(e: FunnelEnrollment) -> "EnrollmentOut":
    from ..schemas import EnrollmentOut

    return EnrollmentOut(
        enrollment_id=e.enrollment_id,
        account_id=e.account_id,
        target_user_id=e.target_user_id,
        sequence_id=e.sequence_id,
        enrolled_at_iso=e.enrolled_at_iso,
        current_step_index=e.current_step_index,
        last_action_at_iso=e.last_action_at_iso,
        completed=e.completed,
        converted=e.converted,
    )
