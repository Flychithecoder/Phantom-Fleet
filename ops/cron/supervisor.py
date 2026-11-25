"""In-process supervisor — cross-platform dev convenience.

Runs the schedule in a single foreground process. No systemd, no
Task Scheduler. Ctrl-C to stop. Use when iterating locally; use cron
or Task Scheduler for production.

Guarantees:
 * Deterministic firing order (sorted by job name on tie).
 * Never runs the same job twice concurrently (one subprocess per job).
 * Persists last_run_ms per job so a restart doesn't re-fire
   everything within the first second (the "thundering restart" bug).
 * Surfaces non-zero exits + stderr tails in the console.

Usage:
    python -m ops.cron.supervisor              # fire all jobs
    python -m ops.cron.supervisor --only dispatch,recovery
    python -m ops.cron.supervisor --speed 60   # 60x time (dev smoke)
    python -m ops.cron.supervisor --once       # fire everything due now and exit
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.cron.schedule import JOBS, Job  # noqa: E402
from ops.sched import _store  # noqa: E402


SUPERVISOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS supervisor_state (
    job_name TEXT PRIMARY KEY,
    last_run_ms INTEGER NOT NULL,
    last_exit INTEGER,
    last_duration_ms INTEGER,
    runs INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0
);
"""


def _init() -> None:
    _store.apply_migrations()
    with _store.connect() as con:
        con.executescript(SUPERVISOR_SCHEMA)


def _last_run(con, job_name: str) -> int:
    row = con.execute(
        "SELECT last_run_ms FROM supervisor_state WHERE job_name = ?",
        (job_name,),
    ).fetchone()
    return int(row["last_run_ms"]) if row else 0


def _record_run(con, job_name: str, exit_code: int, duration_ms: int) -> None:
    con.execute(
        "INSERT INTO supervisor_state "
        "(job_name, last_run_ms, last_exit, last_duration_ms, runs, failures) "
        "VALUES (?, ?, ?, ?, 1, ?) "
        "ON CONFLICT(job_name) DO UPDATE SET "
        "  last_run_ms = excluded.last_run_ms, "
        "  last_exit = excluded.last_exit, "
        "  last_duration_ms = excluded.last_duration_ms, "
        "  runs = runs + 1, "
        "  failures = failures + CASE WHEN excluded.last_exit = 0 THEN 0 ELSE 1 END",
        (job_name, int(time.time() * 1000), exit_code, duration_ms,
         1 if exit_code else 0),
    )


def _due_jobs(now_ms: int, selected: set[str] | None,
              speed: float) -> list[Job]:
    _init()
    out: list[Job] = []
    with _store.connect() as con:
        for job in sorted(JOBS, key=lambda j: j.name):
            if selected and job.name not in selected:
                continue
            last = _last_run(con, job.name)
            effective_interval_ms = int(job.interval_s * 1000 / speed)
            if now_ms - last >= effective_interval_ms:
                out.append(job)
    return out


def _run_job(job: Job) -> tuple[int, int, str]:
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            list(job.argv), capture_output=True, text=True,
            timeout=1200,
        )
    except subprocess.TimeoutExpired:
        return 124, int((time.monotonic() - t0) * 1000), "timeout"
    except FileNotFoundError:
        return 127, 0, f"executable not on PATH: {job.argv[0]}"
    dur_ms = int((time.monotonic() - t0) * 1000)
    tail = (proc.stderr or proc.stdout or "")[-500:]
    return proc.returncode, dur_ms, tail


def tick_once(selected: set[str] | None = None, speed: float = 1.0) -> list[dict]:
    """Fire every due job once; return a run report."""
    now_ms = int(time.time() * 1000)
    out: list[dict] = []
    for job in _due_jobs(now_ms, selected, speed):
        code, dur_ms, tail = _run_job(job)
        with _store.connect() as con:
            _record_run(con, job.name, code, dur_ms)
        out.append({"job": job.name, "exit": code, "duration_ms": dur_ms,
                    "tail": tail[-200:]})
    return out


def loop(
    selected: set[str] | None = None, speed: float = 1.0,
    poll_interval_s: float = 1.0,
) -> None:
    """Supervisor main loop. Ctrl-C to stop."""
    print(f"supervisor: {len(JOBS)} jobs, speed={speed}x")
    for j in sorted(JOBS, key=lambda j: j.name):
        print(f"  {j.name:<20} every {j.interval_s}s  {' '.join(j.argv)}")
    print("")
    try:
        while True:
            report = tick_once(selected, speed)
            for r in report:
                stamp = time.strftime("%H:%M:%S")
                mark = "ok" if r["exit"] == 0 else f"FAIL(exit={r['exit']})"
                print(f"[{stamp}] {r['job']:<20} {mark:<8} {r['duration_ms']}ms")
                if r["exit"] and r["tail"]:
                    for line in r["tail"].splitlines()[-4:]:
                        print(f"             {line}")
            time.sleep(poll_interval_s / speed)
    except KeyboardInterrupt:
        print("\nsupervisor: stopped")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated job names")
    ap.add_argument("--once", action="store_true",
                    help="fire every due job once, then exit")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="interval multiplier (60 = 1 min becomes 1 s)")
    ap.add_argument("--status", action="store_true",
                    help="print last-run report and exit")
    args = ap.parse_args()

    selected = set(args.only.split(",")) if args.only else None

    if args.status:
        _init()
        with _store.connect() as con:
            rows = con.execute(
                "SELECT * FROM supervisor_state ORDER BY job_name"
            ).fetchall()
        if not rows:
            print("no runs yet")
            return 0
        print(f"{'job':<20} {'last_exit':<10} {'last_dur_ms':<12} {'runs':<6} {'fails':<6}")
        for r in rows:
            print(f"{r['job_name']:<20} {r['last_exit']:<10} "
                  f"{r['last_duration_ms']:<12} {r['runs']:<6} {r['failures']:<6}")
        return 0

    if args.once:
        for r in tick_once(selected, args.speed):
            print(json.dumps(r))
        return 0

    loop(selected, speed=args.speed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
