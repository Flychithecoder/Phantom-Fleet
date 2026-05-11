"""
WarmingOrchestrator — daily warming cycle runner for the Phantom Fleet.

Responsibilities:
    1. Accept a list of account dicts with their warmup_day numbers.
    2. For each account, produce a DailyPlan via plan_daily_actions().
    3. Translate each DailyPlan into WorkerTask objects (follows, story_views,
       likes, dms) and enqueue them into the correct PhoneHybridRunner.
    4. Respect the TimeSlotScheduler's DailySchedule — only run actions in
       slots that are assigned for the account's phone on this day.
    5. Skip any slot that falls within QUIET_HOURS_START..QUIET_HOURS_END.
    6. Run all phone background workers concurrently, drain results.
    7. Return a WarmingCycleReport with per-account and aggregate tallies.

Account dict format (required keys):
    account_id:    str           — stable internal ID
    ig_user_id:    str           — Instagram numeric user ID
    username:      str           — Instagram @handle
    phone_serial:  str           — ADB serial of the hosting phone
    warmup_day:    int           — day index into the warming curve (0-based)
    platform:      str           — "instagram"
    session:       IGSession | None — live authenticated session; None = skip

Target selection:
    The orchestrator uses stub target IDs by default. In production the
    FreshTargetAgent writes today's approved target pool to the DB and the
    orchestrator should receive targets via task.params["target_user_id"].
    The FRESH_TARGET_ID_KEY constant names the params key callers must set.

Quiet-hour logic:
    A task is quiet-hour-skipped if the account's phone has NO non-quiet-hour
    slot assignments in the DailySchedule for the "instagram" platform.
    If the schedule has at least one valid slot for that phone+platform, the
    orchestrator enqueues ALL planned tasks for that account (individual
    task timing is the BackgroundWorker's responsibility, not ours).
    The skipped_quiet_hours counter counts accounts, not slots.

Design note on targets:
    For warming actions that require a target (follows, likes, story_views,
    send_dm), the orchestrator expects the account dict to carry a
    "targets" list of {"user_id": str} dicts.  If no targets are supplied,
    those action types are silently skipped and noted in errors[].
    get_followers tasks use the account's own ig_user_id as the subject.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .hybrid_runner import PhoneHybridRunner, WorkerTask
from .time_slot_scheduler import DailySchedule, is_quiet_hour
from .warming_curve import plan_daily_actions, FRESH_WARMUP_CURVE, RE_WAKE_CURVE


# Key in task.params that holds the IGSession object
SESSION_PARAM_KEY = "session"

# Sentinel target user ID used when no real targets are in the account dict
# (in production, FreshTargetAgent populates real IDs)
_STUB_MEDIA_ID = "stub_media_000"
_STUB_REEL_ID  = "stub_reel_000"
_STUB_DM_TEXT  = "Hey, love your content!"


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class WarmingCycleReport:
    """Aggregate result of one full warming cycle run."""

    date_iso:              str
    accounts_attempted:    int = 0
    accounts_succeeded:    int = 0
    total_follows:         int = 0
    total_story_views:     int = 0
    total_likes:           int = 0
    total_dms:             int = 0
    skipped_quiet_hours:   int = 0    # accounts skipped (no active slot on schedule)
    skipped_no_session:    int = 0    # accounts skipped because session is None
    session_expired_count: int = 0
    rate_limited_count:    int = 0
    errors:                list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class WarmingOrchestrator:
    """
    Daily warming cycle coordinator.

    Usage:
        orchestrator = WarmingOrchestrator(fleet_runners, schedule)
        report = await orchestrator.run_warming_cycle(accounts, "2026-04-11")

    Parameters:
        fleet_runners: dict mapping phone_serial → PhoneHybridRunner.
                       Built by hybrid_runner.build_fleet_runners().
        schedule:      DailySchedule produced by TimeSlotScheduler.build_schedule()
                       for today's date.  Used to gate which phones may act.
    """

    def __init__(
        self,
        fleet_runners: dict[str, PhoneHybridRunner],
        schedule: DailySchedule,
    ) -> None:
        self._runners  = fleet_runners
        self._schedule = schedule

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_warming_cycle(
        self,
        accounts: list[dict],
        date_iso: str,
    ) -> WarmingCycleReport:
        """
        Run one full day of warming for the given account list.

        Steps:
            1. For each account, produce a DailyPlan.
            2. Gate on session presence + schedule slot availability.
            3. Build WorkerTask objects and enqueue to each phone's runner.
            4. Run all runners concurrently, drain results.
            5. Aggregate into WarmingCycleReport.
        """
        report = WarmingCycleReport(date_iso=date_iso)

        # Enqueue tasks per account
        for acct in accounts:
            self._enqueue_account_tasks(acct, date_iso, report)

        # Run all runners that received tasks
        all_results_by_runner: dict[str, dict] = {}
        runners_with_tasks = {
            serial: runner
            for serial, runner in self._runners.items()
            if runner._workers.get("instagram") and
               not runner._workers["instagram"]._task_queue.empty()
        }

        # Run concurrently across all phones
        runner_outputs = await asyncio.gather(
            *[runner.run_background_workers() for runner in runners_with_tasks.values()],
            return_exceptions=True,
        )

        for serial, output in zip(runners_with_tasks.keys(), runner_outputs):
            if isinstance(output, Exception):
                report.errors.append(f"runner_{serial}_exception:{output}")
                continue
            all_results_by_runner[serial] = output

        # Tally results
        _tally_results(all_results_by_runner, report)

        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _enqueue_account_tasks(
        self,
        acct: dict,
        date_iso: str,
        report: WarmingCycleReport,
    ) -> None:
        """
        Produce a DailyPlan for one account and enqueue WorkerTasks.
        Updates report in-place for skip/error accounting.
        """
        account_id   = acct["account_id"]
        phone_serial = acct["phone_serial"]
        warmup_day   = acct.get("warmup_day", 0)
        session      = acct.get("session")
        platform     = acct.get("platform", "instagram")
        targets      = acct.get("targets", [])

        report.accounts_attempted += 1

        # Gate 1: session must be present and valid
        if session is None or not getattr(session, "is_valid", True):
            report.skipped_no_session += 1
            return

        # Gate 2: schedule must have at least one non-quiet slot for this phone
        if not self._has_active_slot(phone_serial, platform):
            report.skipped_quiet_hours += 1
            return

        # Produce the daily plan
        curve_type = acct.get("curve_type", "fresh_warmup")
        curve = RE_WAKE_CURVE if curve_type == "re_wake" else FRESH_WARMUP_CURVE
        plan = plan_daily_actions(
            account_id=account_id,
            date_iso=date_iso,
            day_in_curve=warmup_day,
            curve=curve,
        )

        runner = self._runners.get(phone_serial)
        if runner is None:
            report.errors.append(f"no_runner_for_phone:{phone_serial} account:{account_id}")
            return

        enqueued = self._build_and_enqueue_tasks(
            runner=runner,
            acct=acct,
            plan_follows=plan.follows,
            plan_story_views=plan.story_views,
            plan_likes=plan.likes,
            plan_dms=plan.dms,
            session=session,
            targets=targets,
            report=report,
        )

        if enqueued > 0:
            report.accounts_succeeded += 1

    def _has_active_slot(self, phone_serial: str, platform: str) -> bool:
        """
        Return True if the DailySchedule has at least one non-quiet-hour
        slot assignment for this (phone, platform) pair.
        """
        for assignment in self._schedule.assignments:
            if (
                assignment.phone_serial == phone_serial
                and assignment.platform == platform
                and not is_quiet_hour(assignment.slot)
            ):
                return True
        return False

    def _build_and_enqueue_tasks(
        self,
        runner: PhoneHybridRunner,
        acct: dict,
        plan_follows: int,
        plan_story_views: int,
        plan_likes: int,
        plan_dms: int,
        session,
        targets: list[dict],
        report: WarmingCycleReport,
    ) -> int:
        """
        Build WorkerTask objects from a DailyPlan and enqueue them.
        Returns the number of tasks successfully enqueued.
        """
        account_id   = acct["account_id"]
        phone_serial = acct["phone_serial"]
        enqueued     = 0

        def _make_task(action: str, params: dict) -> WorkerTask:
            return WorkerTask(
                task_id=f"{account_id}_{action}_{uuid.uuid4().hex[:8]}",
                platform="instagram",
                account_id=account_id,
                phone_serial=phone_serial,
                action=action,
                params={SESSION_PARAM_KEY: session, **params},
            )

        # --- Follows ---
        if plan_follows > 0:
            follow_targets = [t["user_id"] for t in targets if "user_id" in t]
            if not follow_targets:
                if plan_follows > 0:
                    report.errors.append(
                        f"account:{account_id} planned {plan_follows} follows but no targets"
                    )
            else:
                count = min(plan_follows, len(follow_targets))
                for target_id in follow_targets[:count]:
                    task = _make_task("follow", {"target_user_id": target_id})
                    if runner.enqueue_api_task(task):
                        enqueued += 1

        # --- Story views ---
        if plan_story_views > 0:
            story_targets = [t["user_id"] for t in targets if "user_id" in t]
            if not story_targets:
                report.errors.append(
                    f"account:{account_id} planned {plan_story_views} story_views but no targets"
                )
            else:
                count = min(plan_story_views, len(story_targets))
                for target_id in story_targets[:count]:
                    task = _make_task(
                        "story_view",
                        {"reel_id": target_id, "media_ids": [target_id]},
                    )
                    if runner.enqueue_api_task(task):
                        enqueued += 1

        # --- Likes ---
        if plan_likes > 0:
            like_targets = [
                t.get("media_id", t.get("user_id", _STUB_MEDIA_ID))
                for t in targets
            ]
            if not like_targets:
                report.errors.append(
                    f"account:{account_id} planned {plan_likes} likes but no targets"
                )
            else:
                count = min(plan_likes, len(like_targets))
                for media_id in like_targets[:count]:
                    task = _make_task("like", {"media_id": media_id})
                    if runner.enqueue_api_task(task):
                        enqueued += 1

        # --- DMs ---
        if plan_dms > 0:
            dm_targets = [t["user_id"] for t in targets if "user_id" in t]
            if not dm_targets:
                report.errors.append(
                    f"account:{account_id} planned {plan_dms} dms but no targets"
                )
            else:
                count = min(plan_dms, len(dm_targets))
                dm_text = acct.get("dm_text", _STUB_DM_TEXT)
                for target_id in dm_targets[:count]:
                    task = _make_task(
                        "send_dm",
                        {"recipient_user_id": target_id, "text": dm_text},
                    )
                    if runner.enqueue_api_task(task):
                        enqueued += 1

        return enqueued


# ---------------------------------------------------------------------------
# Result tallying (pure function — easy to test in isolation)
# ---------------------------------------------------------------------------


def _tally_results(
    results_by_runner: dict[str, dict[str, list]],
    report: WarmingCycleReport,
) -> None:
    """
    Walk all WorkerResults from every runner/platform and update the report.

    results_by_runner layout:
        {
            "phone_serial": {
                "instagram": [WorkerResult, ...],
                "threads":   [...],
                ...
            }
        }
    """
    for _serial, platform_results in results_by_runner.items():
        ig_results = platform_results.get("instagram", [])
        for result in ig_results:
            if result.success:
                action = result.data.get("action", "")
                if action == "follow":
                    report.total_follows += 1
                elif action == "story_view":
                    report.total_story_views += 1
                elif action == "like":
                    report.total_likes += 1
                elif action == "send_dm":
                    report.total_dms += 1
            else:
                error = result.error or ""
                if error == "session_expired":
                    report.session_expired_count += 1
                elif error == "rate_limited":
                    report.rate_limited_count += 1
                elif error not in (
                    "no_device_headers_extracted",
                    "account_locked_by_foreground",
                    "no_session_in_task_params",
                ):
                    report.errors.append(
                        f"worker_error account:{result.account_id} error:{error}"
                    )
