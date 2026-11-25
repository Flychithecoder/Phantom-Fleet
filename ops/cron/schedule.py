"""The canonical schedule, shared by every platform-specific entry point.

One source of truth — if an interval changes it changes here and the
Linux crontab, Windows scheduled tasks, and the dev supervisor all
agree. The alternative (writing times in three files) drifts within a
week.

Rules:
 * Everything that TOUCHES phones runs frequently.
 * Everything that only reads/aggregates runs less often.
 * Nothing touches wall-clock time zones here; all intervals are in
   seconds, and cron/Task-Scheduler/supervisor translate accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    name: str
    interval_s: int
    argv: tuple[str, ...]  # python -m ...
    description: str


JOBS: tuple[Job, ...] = (
    Job(
        "dispatch",
        interval_s=60,
        argv=("python", "-m", "ops.dispatch.worker", "--apply", "--max", "25"),
        description="Drain action_queue -> companion APK; the hot path.",
    ),
    Job(
        "recovery",
        interval_s=300,  # 5 min
        argv=("python", "-m", "ops.sched.recovery", "--apply"),
        description="Account status transitions from action_results tail.",
    ),
    Job(
        "proxy",
        interval_s=900,  # 15 min
        argv=("python", "-m", "ops.sched.proxy", "--apply",
              "--register", "trumpproxies_yuge"),
        description="Proxy rotation + healthy-decay state machine.",
    ),
    Job(
        "scheduler_tick",
        interval_s=21_600,  # 6 h
        argv=("python", "-m", "ops.sched.tick", "--apply"),
        description="Enqueue the next day's actions for every alive account.",
    ),
    Job(
        "replacement",
        interval_s=21_600,  # 6 h
        argv=("python", "-m", "ops.sched.replacement", "--apply"),
        description="Emit replacements_needed rows for dead accounts.",
    ),
    Job(
        "weekly_commitment",
        interval_s=604_800,  # 7 d
        argv=("python", "-c",
              "from ops.intel import chain; "
              "print(chain.make_commitment())"),
        description="Sign the audit chain head for the week.",
    ),
)


def by_name(name: str) -> Job | None:
    for j in JOBS:
        if j.name == name:
            return j
    return None
