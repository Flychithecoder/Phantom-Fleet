"""Online backup of the persona-store SQLite DB.

Uses SQLite's online backup API so writers (the sched/dispatch stack)
do not need to be stopped. Writes a timestamped `.sqlite` into the
backups directory; keeps the most recent N.

CLAUDE.md: "Never modify the existing Onimator deployment's databases
without backing them up first." This script is what satisfies that
rule for the Fleet store.

Usage:

    python ops/backup/backup_persona_store.py
    python ops/backup/backup_persona_store.py --keep 14
    python ops/backup/backup_persona_store.py --dest /some/other/dir
    python ops/backup/backup_persona_store.py --verify

The default destination is `backend/.data/backups/`. Default retention
is the last 7 backups. `--verify` runs `PRAGMA integrity_check` on the
just-written file; non-zero exit on anything but "ok".

Pair with a cron job: see ops/cron/README.md for the entry.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_STORE = _REPO / "backend" / ".data" / "persona-store.sqlite"
_DEFAULT_DEST = _REPO / "backend" / ".data" / "backups"


def _backup(src: Path, dst: Path) -> None:
    src_con = sqlite3.connect(src)
    dst_con = sqlite3.connect(dst)
    try:
        with dst_con:
            src_con.backup(dst_con)
    finally:
        src_con.close()
        dst_con.close()


def _integrity_check(path: Path) -> str:
    con = sqlite3.connect(path)
    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "no-result"
    finally:
        con.close()


def _prune(dest: Path, keep: int) -> list[Path]:
    """Keep the N newest backups; delete the rest. Returns deleted paths."""
    files = sorted(
        dest.glob("persona-store-*.sqlite"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    to_delete = files[keep:]
    for p in to_delete:
        try:
            p.unlink()
        except OSError:
            pass
    return to_delete


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=_STORE,
                    help=f"source DB (default {_STORE})")
    ap.add_argument("--dest", type=Path, default=_DEFAULT_DEST,
                    help=f"backup directory (default {_DEFAULT_DEST})")
    ap.add_argument("--keep", type=int, default=7,
                    help="retain the N newest backups (default 7)")
    ap.add_argument("--verify", action="store_true",
                    help="run PRAGMA integrity_check on the new backup")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.src.exists():
        print(f"source DB not found: {args.src}", file=sys.stderr)
        return 2

    args.dest.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.dest / f"persona-store-{ts}.sqlite"

    _backup(args.src, out)

    verdict = "ok"
    if args.verify:
        verdict = _integrity_check(out)

    pruned = _prune(args.dest, args.keep)

    if not args.quiet:
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"wrote {out} ({size_mb:.2f} MB)")
        if args.verify:
            print(f"integrity_check: {verdict}")
        if pruned:
            print(f"pruned {len(pruned)} old backup(s)")

    return 0 if verdict == "ok" else 4


if __name__ == "__main__":
    sys.exit(main())
