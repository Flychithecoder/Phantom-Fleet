"""
IGFunnelEnrollmentAgent — enrolls new Instagram follow targets into DM funnel sequences.

Called by the follow agent (or API layer) after new follows are issued. For each
new (account_id, target_user_id) pair, creates a FunnelEnrollment record and
persists it to the JSON sidecar. Duplicate enrollments are silently skipped.

Fleet-scale design notes (CLAUDE.md 20K account rule):
    - Dedup is enforced across ALL sidecar files for the account (not just today's),
      preventing the same target from being enrolled twice from any date's file.
    - Sidecar file: {PHANTOM_STATE_DIR}/funnel_{account_id}_{date_iso}.json
    - enrollment_id is uuid4 hex so IDs are unique across the fleet with no
      central coordinator.

Agent audit table (CLAUDE.md agent-audit rules):
    ┌─────────────────────────┬──────────────────────────────────────────────┐
    │ Agent                   │ IGFunnelEnrollmentAgent                      │
    │ Purpose                 │ Create enrollment records for new targets    │
    │ Tools                   │ None — pure file I/O                         │
    │ Untrusted input         │ target_profile dicts from follow agent       │
    │ User isolation          │ Keyed by (account_id, target_user_id)        │
    │ Cost cap                │ None (no LLM calls)                          │
    │ Loop cap                │ One enrollment record per target per call    │
    │ Confirmation required   │ No (non-destructive write)                   │
    └─────────────────────────┴──────────────────────────────────────────────┘
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

from ...core.dm_funnel import (
    DEFAULT_OFM_SEQUENCE,
    SEQUENCE_REGISTRY,
    FunnelEnrollment,
)
from ...core.hybrid_runner import WorkerResult, WorkerTask

log = logging.getLogger(__name__)


class IGFunnelEnrollmentAgent:
    """
    Enrolls new follow targets into DM funnel sequences.

    Usage:
        agent = IGFunnelEnrollmentAgent()
        result = await agent.run_session(task)

    task.params must contain:
        new_follows:  list of dicts, each with keys:
                        target_user_id: str
                        target_profile: dict  (optional profile metadata)
        sequence_id:  str  — which sequence to enroll into (defaults to DEFAULT_OFM)

    task.params may optionally contain:
        date_iso:  str  — defaults to today UTC

    Returns WorkerResult with data keys:
        enrolled_count, duplicate_skips, errors
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_session(self, task: WorkerTask) -> WorkerResult:
        """
        Enroll a batch of new follow targets into the specified sequence.
        """
        account_id = task.account_id
        date_iso = task.params.get("date_iso") or datetime.now(timezone.utc).date().isoformat()
        sequence_id = task.params.get("sequence_id", DEFAULT_OFM_SEQUENCE.sequence_id)
        new_follows: list[dict] = task.params.get("new_follows", [])

        summary = {
            "enrolled_count": 0,
            "duplicate_skips": 0,
            "errors": [],
        }

        if not new_follows:
            return WorkerResult(
                task_id=task.task_id,
                platform="instagram",
                account_id=account_id,
                success=True,
                data={**summary, "note": "no_new_follows"},
            )

        # Validate sequence exists
        if sequence_id not in SEQUENCE_REGISTRY:
            err = f"sequence_not_found:{sequence_id}"
            log.error("[%s/enroll] %s", account_id, err)
            return WorkerResult(
                task_id=task.task_id,
                platform="instagram",
                account_id=account_id,
                success=False,
                error=err,
                data=summary,
            )

        # Load existing enrollments across ALL sidecar files for this account
        # (not just today) to enforce the cross-day dedup invariant.
        existing_targets = self._load_all_enrolled_targets(account_id)

        # Load today's sidecar to append new enrollments
        today_path = _sidecar_path(account_id, date_iso)
        today_enrollments = _load_sidecar(today_path)

        now_iso = datetime.now(timezone.utc).isoformat()

        for follow in new_follows:
            target_id = follow.get("target_user_id", "")
            if not target_id:
                summary["errors"].append("missing_target_user_id")
                continue

            # Dedup: never enroll same (account_id, target_user_id) twice
            if target_id in existing_targets:
                summary["duplicate_skips"] += 1
                log.debug(
                    "[%s/enroll] Skipping duplicate enrollment for target %s",
                    account_id, target_id,
                )
                continue

            enrollment = FunnelEnrollment(
                enrollment_id=uuid.uuid4().hex,
                account_id=account_id,
                target_user_id=target_id,
                sequence_id=sequence_id,
                enrolled_at_iso=now_iso,
                current_step_index=0,
                last_action_at_iso=None,
                completed=False,
                converted=False,
                state=_extract_profile_state(follow.get("target_profile", {})),
            )

            today_enrollments.append(enrollment)
            existing_targets.add(target_id)
            summary["enrolled_count"] += 1
            log.info(
                "[%s/enroll] Enrolled target %s into sequence %s (id=%s)",
                account_id, target_id, sequence_id, enrollment.enrollment_id,
            )

        # Persist
        _save_sidecar(today_path, today_enrollments)

        return WorkerResult(
            task_id=task.task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action": "ig_funnel_enroll",
                **summary,
            },
        )

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _load_all_enrolled_targets(self, account_id: str) -> set[str]:
        """
        Return a set of all target_user_ids already enrolled for this account,
        scanning every sidecar file matching funnel_{account_id}_*.json.

        This is the cross-day dedup guard — prevents re-enrolling a target
        that was enrolled on a previous date's sidecar file.
        """
        base = Path(os.environ.get("PHANTOM_STATE_DIR", "/tmp/phantom_state"))
        pattern = str(base / f"funnel_{account_id}_*.json")
        targets: set[str] = set()

        for filepath in _glob.glob(pattern):
            try:
                data = json.loads(Path(filepath).read_text(encoding="utf-8"))
                for record in data:
                    tid = record.get("target_user_id", "")
                    if tid:
                        targets.add(tid)
            except Exception as exc:
                log.warning("[enroll] Failed to read sidecar %s: %s", filepath, exc)

        return targets


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _sidecar_path(account_id: str, date_iso: str) -> Path:
    """Path to the JSON sidecar file for one account's funnel enrollments."""
    base = Path(os.environ.get("PHANTOM_STATE_DIR", "/tmp/phantom_state"))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"funnel_{account_id}_{date_iso}.json"


def _load_sidecar(path: Path) -> list[FunnelEnrollment]:
    """Load a list of FunnelEnrollment objects from a JSON sidecar file."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [FunnelEnrollment.from_dict(d) for d in data]
    except Exception as exc:
        log.warning("[enroll] Failed to load sidecar %s: %s", path, exc)
        return []


def _save_sidecar(path: Path, enrollments: list[FunnelEnrollment]) -> None:
    """Persist enrollment list to JSON sidecar."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([e.to_dict() for e in enrollments], indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.error("[enroll] Failed to save sidecar %s: %s", path, exc)


def _extract_profile_state(profile: dict) -> dict:
    """
    Extract useful cached fields from a target profile dict into enrollment.state.

    Stores last_media_id and story_reel_id if present so the funnel agent
    can execute story_view and like_post steps without an extra API call.
    """
    state: dict = {}
    if profile.get("last_media_id"):
        state["last_media_id"] = profile["last_media_id"]
    if profile.get("story_reel_id"):
        state["story_reel_id"] = profile["story_reel_id"]
    if profile.get("story_media_ids"):
        state["story_media_ids"] = profile["story_media_ids"]
    return state
