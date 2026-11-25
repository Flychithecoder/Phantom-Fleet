"""Phase 0 pre-flight #4 — parallel login-survival diagnostic.

Per PLAN.md Day 0 brief: open each cloned Instagram app on its assigned
phone, probe whether a session is alive, categorise:
    alive       - IG opens past the login screen, feed container visible
    needs_reset - stuck on login screen or "sign in again" prompt
    dead        - checkpoint / suspended / "we noticed unusual activity"
    unknown     - clone package missing, phone offline, or probe timed out

Zero actions are taken. Login only. No scroll, no follow, no like.

Deterministic. No agents.

Design:
 - The persona-store DB (`accounts` table) says which (device, package) pairs
   to probe. In Phase 0 the Onimator migration populates this.
 - For each clone we `am start` the package's main activity, wait a fixed
   dwell, then grab the Accessibility window dump and pattern-match it.
 - Pattern catalogue is version-pinned to the UI strings observed on
   Onimator's IG clones (as of 2026-04-11). Future IG UI drift gets a new
   pattern row — behaviour stays deterministic.

Output:
    ops/logs/04_login_survival.ndjson  (per-probe row)
    survival_report.json               (aggregate counts, per-persona)

Usage:
    python 04_login_survival.py                 # whole fleet
    python 04_login_survival.py --only RF8N10J57DA
    python 04_login_survival.py --limit 5       # first N accounts (smoke)
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _adb import (  # noqa: E402
    adb, audit, list_connected, parallel_map, print_table,
)

SCRIPT = "04_login_survival"

STORE = (
    Path(__file__).resolve().parent.parent.parent
    / "backend" / ".data" / "persona-store.sqlite"
)
REPORT = (
    Path(__file__).resolve().parent.parent / "logs" / "survival_report.json"
)

DWELL_S = 4.5
PROBE_TIMEOUT_S = 25

# Pattern catalogue — order matters, first match wins.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("dead", re.compile(
        r"(We noticed unusual activity|Your account has been disabled|"
        r"checkpoint required|Help us confirm|suspicious login)",
        re.IGNORECASE,
    )),
    ("needs_reset", re.compile(
        r"(Log in|Log In|Sign in|Forgot password|Can't log in|"
        r"Phone number, username, or email)",
        re.IGNORECASE,
    )),
    ("alive", re.compile(
        r"(Home feed|Stories tray|Search and explore|For you|"
        r"Create a reel|Direct|Notifications)",
        re.IGNORECASE,
    )),
]


def load_targets(limit: int | None) -> list[dict]:
    """A target is a (device_serial, package_name, username) triple.

    If the store hasn't been populated yet (common before migration), we
    fall back to a single-probe mode where the user passes
    --package=com.instagram.android on a specific --only serial.
    """
    if not STORE.exists():
        return []
    con = sqlite3.connect(f"file:{STORE.as_posix()}?mode=ro", uri=True)
    cur = con.execute(
        "SELECT username, persona, device_serial "
        "FROM accounts WHERE device_serial IS NOT NULL "
        "ORDER BY device_serial, username"
    )
    rows = [
        {"username": u, "persona": p, "serial": s, "package": "com.instagram.android"}
        for (u, p, s) in cur.fetchall()
    ]
    con.close()
    if limit:
        rows = rows[:limit]
    return rows


def start_package(serial: str, package: str) -> bool:
    r = adb(
        serial, "shell", "monkey", "-p", package, "-c",
        "android.intent.category.LAUNCHER", "1",
        timeout=PROBE_TIMEOUT_S,
    )
    return r.returncode == 0 and "No activities found" not in r.stderr


def dump_ui(serial: str) -> str:
    adb(serial, "shell", "uiautomator", "dump", "/sdcard/win.xml",
        timeout=PROBE_TIMEOUT_S)
    r = adb(serial, "shell", "cat", "/sdcard/win.xml",
            timeout=PROBE_TIMEOUT_S)
    return r.stdout


def classify(xml: str) -> str:
    if not xml or len(xml) < 200:
        return "unknown"
    for label, pat in PATTERNS:
        if pat.search(xml):
            return label
    return "unknown"


def stop_package(serial: str, package: str) -> None:
    adb(serial, "shell", "am", "force-stop", package, timeout=10)


def probe(target: dict) -> dict:
    serial = target["serial"]
    package = target["package"]
    t0 = time.monotonic()
    started = start_package(serial, package)
    if not started:
        return {**target, "verdict": "unknown",
                "reason": "package_not_installed",
                "duration_ms": int((time.monotonic() - t0) * 1000)}
    time.sleep(DWELL_S)
    xml = dump_ui(serial)
    verdict = classify(xml)
    stop_package(serial, package)
    return {
        **target,
        "verdict": verdict,
        "xml_chars": len(xml),
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="limit to this one device serial")
    ap.add_argument("--limit", type=int, help="smoke-test first N accounts")
    ap.add_argument("--parallelism", type=int, default=4,
                    help="parallel probes (keep low; uiautomator dumps are heavy)")
    args = ap.parse_args()

    targets = load_targets(args.limit)
    if not targets:
        print("no accounts in persona-store.sqlite — run 03_onimator_migrate.py "
              "--apply first.")
        return 2
    if args.only:
        targets = [t for t in targets if t["serial"] == args.only]

    connected = set(list_connected())
    runnable = [t for t in targets if t["serial"] in connected]
    skipped = [t for t in targets if t["serial"] not in connected]

    print(f"targets={len(targets)} online={len(runnable)} "
          f"skipped={len(skipped)} parallelism={args.parallelism}")

    results = parallel_map(
        runnable, probe, parallelism=args.parallelism,
    )
    rows = [r for _, r in results if isinstance(r, dict)]
    for row in rows:
        audit(SCRIPT, row)

    buckets: dict[str, int] = {}
    per_persona: dict[str, dict[str, int]] = {}
    for r in rows:
        v = r.get("verdict", "unknown")
        buckets[v] = buckets.get(v, 0) + 1
        pp = per_persona.setdefault(r.get("persona") or "unassigned", {})
        pp[v] = pp.get(v, 0) + 1

    report = {
        "ts_ms": int(time.time() * 1000),
        "total_targets": len(targets),
        "probed": len(rows),
        "skipped_offline": len(skipped),
        "verdict_counts": buckets,
        "per_persona": per_persona,
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print_table(
        rows[:40],
        cols=["serial", "username", "persona", "verdict", "duration_ms"],
    )
    if len(rows) > 40:
        print(f"  ... {len(rows) - 40} more rows in {REPORT.parent}/{SCRIPT}.ndjson")

    print()
    print("verdict counts:")
    for k in ("alive", "needs_reset", "dead", "unknown"):
        print(f"  {k:12s} {buckets.get(k, 0)}")
    print(f"\nreport -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
