"""Supervisor smoke: build a fake JOBS list, fire tick_once, verify
state table updates + failure accounting + 'not yet due' logic.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(r"C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone")
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="pf-sup-"))
from ops.sched import _store  # noqa: E402
_store.STORE = tmp / "persona-store.sqlite"

from ops.cron import supervisor, schedule  # noqa: E402

passed = failed = 0


def check(name, cond, info=""):
    global passed, failed
    tag = "PASS" if cond else "FAIL"
    if cond: passed += 1
    else:    failed += 1
    print(f"  [{tag}] {name:60s} {info}")


# Swap JOBS for toy jobs we can fire instantly.
TOY_JOBS = (
    schedule.Job("toy_ok",  interval_s=60,
                 argv=(sys.executable, "-c", "print('hi')"),
                 description="x"),
    schedule.Job("toy_fail", interval_s=60,
                 argv=(sys.executable, "-c", "import sys; sys.exit(3)"),
                 description="x"),
)
supervisor.JOBS = TOY_JOBS

# First pass: both jobs are due (no prior state).
rep = supervisor.tick_once()
check("first pass runs both jobs", len(rep) == 2, f"ran={len(rep)}")
by_name = {r["job"]: r for r in rep}
check("toy_ok exits 0",   by_name["toy_ok"]["exit"] == 0, "")
check("toy_fail exits 3", by_name["toy_fail"]["exit"] == 3, "")

# Immediate second pass: nothing due (interval 60s not elapsed).
rep2 = supervisor.tick_once()
check("second pass fires nothing (interval not elapsed)",
      len(rep2) == 0, f"ran={len(rep2)}")

# speed=1000 collapses 60s to 0.06s; wait that long and both should fire.
time.sleep(0.1)
rep3 = supervisor.tick_once(speed=1000.0)
check("accelerated speed re-fires both",
      len(rep3) == 2, f"ran={len(rep3)}")

# State table: runs=2 each, failures=2 on toy_fail only.
with _store.connect() as con:
    rows = {r["job_name"]: dict(r) for r in con.execute(
        "SELECT * FROM supervisor_state"
    ).fetchall()}
check("runs counter is 2 for each", all(r["runs"] == 2 for r in rows.values()),
      f"runs={[r['runs'] for r in rows.values()]}")
check("failures counter is 2 on toy_fail, 0 on toy_ok",
      rows["toy_fail"]["failures"] == 2 and rows["toy_ok"]["failures"] == 0,
      f"fails={[(k, r['failures']) for k, r in rows.items()]}")

# Selection filter.
time.sleep(0.1)
rep4 = supervisor.tick_once(selected={"toy_ok"}, speed=1000.0)
check("selected={toy_ok} runs only that one",
      len(rep4) == 1 and rep4[0]["job"] == "toy_ok", f"ran={rep4}")

print(f"\n--- {passed} PASS / {failed} FAIL ---")
try: shutil.rmtree(tmp)
except Exception: pass
sys.exit(0 if failed == 0 else 1)
