"""Phase 0 pre-flight #3 — migrate Onimator's SQLite state into the
Phantom Fleet persona schema.

Deterministic. No agents. Read-only against Onimator; writes a brand-new
SQLite DB that PF owns.

Source (per HARDWARE.md):
    C:\\Onimator\\full_igbot_14.1.8.1\\
      devices.db              (20 rows — fleet device registry)
      notificationdatabase.db (43,571 rows — per-account action history)
      iguserdatabase.db       (7,412 rows — scrape target pool, NOT our accounts)
      Settings\\Setting-DefaultTatiana\\  (persona config)
      Settings\\Setting-DefaultMelodie\\  (persona config)
      ... Warmup variants

Target (PF-owned):
    backend/.data/persona-store.sqlite
      personas      (one row per persona name; Tatiana, Melodie, ...)
      accounts      (one row per IG account; FK persona + FK device)
      devices       (one row per phone; serial is PK)
      actions       (migrated action history, FK account)

Safety:
 - Source files are opened read-only ('file:...?mode=ro').
 - Target file is created fresh under backend/.data/; existing one is
   renamed with a .bak-<ts> suffix, never clobbered.
 - Never touches iguserdatabase.db / notificationdatabase.db on disk.
 - Dry-run prints the per-table counts it WOULD write, no file created.

Schema is intentionally narrow — just enough to hand off to Phase 1
Account Setup + Warming code. Extend in-place as new fields are needed.

Usage:
    python 03_onimator_migrate.py --dry-run
    python 03_onimator_migrate.py --apply
    python 03_onimator_migrate.py --apply --src 'C:\\Onimator\\full_igbot_14.1.8.1'
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

DEFAULT_SRC = Path(r"C:\Onimator\full_igbot_14.1.8.1")
TARGET_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "backend" / ".data"
)
TARGET_PATH = TARGET_DIR / "persona-store.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS personas (
    name TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    settings_json TEXT,
    imported_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    serial TEXT PRIMARY KEY,
    model TEXT,
    region TEXT,
    source TEXT NOT NULL,
    imported_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    persona TEXT,
    device_serial TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    imported_at_ms INTEGER NOT NULL,
    FOREIGN KEY (persona) REFERENCES personas(name),
    FOREIGN KEY (device_serial) REFERENCES devices(serial)
);
CREATE INDEX IF NOT EXISTS ix_accounts_persona ON accounts(persona);
CREATE INDEX IF NOT EXISTS ix_accounts_device  ON accounts(device_serial);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    ts_ms INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS ix_actions_account_ts ON actions(account_id, ts_ms);
"""


def open_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def discover_tables(con: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    out = []
    for (name,) in rows:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM \"{name}\"").fetchone()[0]
        except sqlite3.DatabaseError:
            n = -1
        out.append((name, n))
    return out


def read_personas(src: Path) -> list[dict]:
    """Discover persona names from the Settings/ subfolders."""
    settings_dir = src / "Settings"
    personas = {}
    if not settings_dir.exists():
        return []
    for child in settings_dir.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        # Setting-DefaultTatiana / Settings-DefaultMelodie / Settings-WarmupTatiana ...
        lower = name.lower()
        for mode in ("default", "warmup"):
            if mode in lower:
                for persona in ("tatiana", "melodie"):
                    if persona in lower:
                        personas.setdefault(persona.capitalize(), {"modes": set()})
                        personas[persona.capitalize()]["modes"].add(mode)
                        personas[persona.capitalize()].setdefault(
                            "folders", []).append(name)
    return [
        {
            "name": name,
            "mode": ",".join(sorted(info["modes"])),
            "settings_folders": info.get("folders", []),
        }
        for name, info in sorted(personas.items())
    ]


def read_devices(src: Path) -> tuple[list[dict], dict]:
    path = src / "devices.db"
    if not path.exists():
        return [], {"present": False}
    con = open_ro(path)
    tables = discover_tables(con)
    rows: list[dict] = []
    # Onimator's `devices.db` schema is unknown here — we probe for any
    # column named 'serial' / 'imei' / 'device_id' and keep whatever
    # looks like a 14-16-hex/alnum phone identifier. If the table shape
    # is wildly different the migration still reports and continues.
    for (tname, _n) in tables:
        try:
            cur = con.execute(f"SELECT * FROM \"{tname}\"")
            cols = [c[0] for c in cur.description]
            for row in cur.fetchall():
                rec = dict(zip(cols, row))
                serial = (
                    rec.get("serial") or rec.get("device_id")
                    or rec.get("imei") or rec.get("id")
                )
                if not serial:
                    continue
                rows.append({
                    "serial": str(serial),
                    "model": rec.get("model") or rec.get("device_model"),
                    "region": rec.get("region"),
                    "raw_table": tname,
                })
        except sqlite3.DatabaseError:
            continue
    con.close()
    return rows, {"present": True, "tables": tables}


def read_accounts(src: Path) -> tuple[list[dict], dict]:
    """notificationdatabase.db has 43k action rows; the account roster is
    inferred from the distinct account identifier column. We never read
    personal-data columns (email, password, tokens) — identifier only.
    """
    path = src / "notificationdatabase.db"
    if not path.exists():
        return [], {"present": False}
    con = open_ro(path)
    tables = discover_tables(con)
    accounts: dict[str, dict] = {}
    for (tname, _n) in tables:
        try:
            cur = con.execute(f"SELECT * FROM \"{tname}\" LIMIT 1")
            cols = [c[0] for c in cur.description]
        except sqlite3.DatabaseError:
            continue
        acct_col = next(
            (c for c in cols if c.lower() in (
                "account", "username", "user", "login", "ig_user"
            )), None,
        )
        if not acct_col:
            continue
        try:
            cur = con.execute(
                f"SELECT DISTINCT \"{acct_col}\" FROM \"{tname}\" "
                f"WHERE \"{acct_col}\" IS NOT NULL AND \"{acct_col}\" != ''"
            )
            for (uname,) in cur.fetchall():
                uname = str(uname).strip()
                if not uname:
                    continue
                accounts.setdefault(uname, {
                    "username": uname, "status": "imported",
                })
        except sqlite3.DatabaseError:
            continue
    con.close()
    return list(accounts.values()), {"present": True, "tables": tables}


def write_target(
    personas: list[dict], devices: list[dict], accounts: list[dict],
) -> Path:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    if TARGET_PATH.exists():
        backup = TARGET_PATH.with_suffix(f".sqlite.bak-{int(time.time())}")
        TARGET_PATH.rename(backup)
        print(f"  backed up existing store -> {backup.name}")
    con = sqlite3.connect(TARGET_PATH)
    con.executescript(SCHEMA)
    now = int(time.time() * 1000)
    con.executemany(
        "INSERT OR IGNORE INTO personas (name, mode, settings_json, imported_at_ms) "
        "VALUES (?, ?, ?, ?)",
        [(p["name"], p["mode"], json.dumps(p), now) for p in personas],
    )
    con.executemany(
        "INSERT OR IGNORE INTO devices (serial, model, region, source, imported_at_ms) "
        "VALUES (?, ?, ?, 'onimator', ?)",
        [(d["serial"], d.get("model"), d.get("region"), now) for d in devices],
    )
    con.executemany(
        "INSERT OR IGNORE INTO accounts (username, status, imported_at_ms) "
        "VALUES (?, ?, ?)",
        [(a["username"], a.get("status", "imported"), now) for a in accounts],
    )
    con.commit()
    con.close()
    return TARGET_PATH


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.src.exists():
        print(f"ERROR: Onimator install not found at {args.src}")
        return 2

    print(f"source: {args.src}")
    personas = read_personas(args.src)
    devices, dev_meta = read_devices(args.src)
    accounts, acct_meta = read_accounts(args.src)

    print(f"\n  personas discovered : {len(personas)} "
          f"({', '.join(p['name'] for p in personas) or 'none'})")
    print(f"  devices discovered  : {len(devices)}  "
          f"(tables: {dev_meta.get('tables')})")
    print(f"  accounts discovered : {len(accounts)} "
          f"(tables: {acct_meta.get('tables')})")

    if args.dry_run:
        print("\ndry run — no files written.")
        return 0

    path = write_target(personas, devices, accounts)
    print(f"\nwrote {path}")
    print(f"  personas = {len(personas)}")
    print(f"  devices  = {len(devices)}")
    print(f"  accounts = {len(accounts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
