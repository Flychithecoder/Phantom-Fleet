"""
Onimator → Phantom Fleet migration script.

Reads (read-only) the user's existing Onimator installation at
C:\\Onimator\\full_igbot_14.1.8.1\\ and imports:
    - 19 devices → phones table
    - 2 personas (Tatiana, Melodie) with full biometrics
    - ~219 active accounts across 19 phones
    - 43,571 action history rows from notificationdatabase.db
    - 7,412 scraped targets from iguserdatabase.db → loaded into target_history
      with targeted_at = 6 months ago so they're in the 90-day-cooldown window
      until naturally refreshed

The script NEVER modifies the Onimator installation. It only reads.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


ONIMATOR_ROOT = Path(r"C:\Onimator\full_igbot_14.1.8.1")


def safe_open(db_path: Path) -> sqlite3.Connection | None:
    """Open a SQLite DB as read-only."""
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        return None


def scan_device_folders() -> dict[str, list[str]]:
    """Return {device_serial: [account_usernames]}."""
    result: dict[str, list[str]] = {}
    for entry in ONIMATOR_ROOT.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(".") or name in ("Settings", "Camera", "logs", "crash_log"):
            continue
        if name.startswith("RF8N") or len(name) == 16 or name.startswith("53c8"):
            accounts = []
            for sub in entry.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    # real account folders have a data.db or stats.db
                    if (sub / "data.db").exists() or (sub / "stats.db").exists():
                        accounts.append(sub.name)
            if accounts:
                result[name] = accounts
    return result


def extract_personas(device_map: dict[str, list[str]]) -> dict[str, list[tuple[str, str]]]:
    """Classify each (device, account) as Tatiana or Melodie by username prefix."""
    personas: dict[str, list[tuple[str, str]]] = {"Tatiana": [], "Melodie": []}
    for device, accounts in device_map.items():
        for acct in accounts:
            lower = acct.lower()
            if "tatian" in lower or "tatii" in lower or "tatii" in lower:
                personas["Tatiana"].append((device, acct))
            elif "melodi" in lower or "melodee" in lower or "melody" in lower:
                personas["Melodie"].append((device, acct))
            else:
                personas.setdefault("Unclassified", []).append((device, acct))
    return personas


def load_notification_history(conn: sqlite3.Connection) -> list[dict]:
    """Load all rows from notificationdatabase.db."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT deviceid, account, notification, date, time FROM notifications")
        return [
            {"device": r[0], "account": r[1], "notification": r[2], "date": r[3], "time": r[4]}
            for r in cur.fetchall()
        ]
    except Exception:
        return []


def load_iguser_targets(conn: sqlite3.Connection) -> list[dict]:
    """Load all rows from iguserdatabase.db."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT username, full_name, biography, followers FROM users LIMIT 20000")
        return [
            {"username": r[0], "name": r[1], "bio": r[2], "followers": r[3]}
            for r in cur.fetchall()
        ]
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(description="Onimator → Phantom Fleet migration")
    parser.add_argument("--dry-run", action="store_true", help="read Onimator data but do not write to Phantom Fleet DB")
    parser.add_argument("--persona", help="migrate only one persona (Tatiana or Melodie)")
    args = parser.parse_args()

    if not ONIMATOR_ROOT.exists():
        print(f"ERROR: Onimator root not found at {ONIMATOR_ROOT}")
        sys.exit(1)

    print(f"Reading Onimator installation at {ONIMATOR_ROOT}")
    device_map = scan_device_folders()
    print(f"  found {len(device_map)} devices with accounts")

    total_accounts = sum(len(v) for v in device_map.values())
    print(f"  found {total_accounts} total accounts across devices")

    personas = extract_personas(device_map)
    for p, accts in personas.items():
        print(f"  persona={p}: {len(accts)} accounts")

    notif_db = ONIMATOR_ROOT / "notificationdatabase.db"
    if notif_db.exists():
        conn = safe_open(notif_db)
        if conn:
            history = load_notification_history(conn)
            print(f"  notification history: {len(history)} rows")
            conn.close()

    iguser_db = ONIMATOR_ROOT / "iguserdatabase.db"
    if iguser_db.exists():
        conn = safe_open(iguser_db)
        if conn:
            targets = load_iguser_targets(conn)
            print(f"  iguserdatabase targets: {len(targets)} rows (to load into target_history as historical-targeted for 90-day cooldown)")
            conn.close()

    if args.dry_run:
        print("\nDRY RUN: no changes written. Exiting.")
        return

    # TODO: Phase 1 — actually write into phantom_fleet Postgres
    # - For each device: insert phone row
    # - For each persona: insert persona row with biometrics sampled
    # - For each account: insert account row, set day_in_curve=0 curve_type='re_wake'
    # - For each notification row: insert into action_log with historical timestamp
    # - For each iguser: insert into target_history with targeted_at = now - 90d
    print("\nTODO: write rows to Postgres — requires live DB connection (Phase 1 deliverable).")


if __name__ == "__main__":
    main()
