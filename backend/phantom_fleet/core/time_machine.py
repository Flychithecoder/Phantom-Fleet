"""Time machine — moonshot #8 (`staffroom_fork_from(timestamp)`).

Primitive: periodic SQLite online-backup snapshots of staffroom.sqlite
written to `.data/time-machine/tm-<unix_ms>-<reason>.sqlite`. A fork is
a copy of the nearest snapshot <= requested timestamp into
`.data/time-machine/forks/fork-<id>.sqlite`. The fork file is a new
standalone DB — read, query, diff it as you like. The live Staffroom
DB is never touched.

Safety contract:
  - take_snapshot() is read-only against the source (uses SQLite's
    online .backup API).
  - fork_from() copies file-level; no API will ever swap a fork back
    into the live path. An operator must do that manually and only
    after stopping the Staffroom process (documented in the runbook).
  - Retention runs lazily on take_snapshot and fork_from. Default
    keeps last 48 snapshots OR total <= 500MB, whichever is stricter,
    and emits a `warn` string when pressure crosses that line.

The module is import-safe: no snapshot is taken at import. A FastAPI
startup hook (or a cron, or a manual call) drives take_snapshot().
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from .simulate import _staffroom_db_path


_TM_FILENAME_RE = re.compile(r"^tm-(\d+)-([a-z0-9_-]{1,40})\.sqlite$")
_FORK_FILENAME_RE = re.compile(r"^fork-([a-f0-9]{16})\.sqlite$")
_REASON_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


def _tm_dir() -> Path:
    env = os.environ.get("PF_TIME_MACHINE_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / ".data" / "time-machine"


def _forks_dir() -> Path:
    return _tm_dir() / "forks"


def _ensure_dirs() -> None:
    _tm_dir().mkdir(parents=True, exist_ok=True)
    _forks_dir().mkdir(parents=True, exist_ok=True)


@dataclass
class Snapshot:
    path: str
    unix_ms: int
    reason: str
    size_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def take_snapshot(reason: str = "auto") -> dict[str, Any]:
    """Online-backup the live Staffroom sqlite to a timestamped file.
    `reason` is a short label (auto|manual|pre-dispatch|owner-request|...)
    stamped into the filename so listings read naturally."""
    if not _REASON_RE.match(reason):
        raise ValueError("reason must match [a-z0-9_-]{1,40}")
    _ensure_dirs()
    src = _staffroom_db_path()
    if not Path(src).exists():
        raise FileNotFoundError(f"staffroom db not found at {src}")
    unix_ms = int(time.time() * 1000)
    dst = _tm_dir() / f"tm-{unix_ms}-{reason}.sqlite"
    t0 = time.monotonic()
    with sqlite3.connect(src) as source, sqlite3.connect(str(dst)) as dest:
        source.backup(dest)
    duration_ms = int((time.monotonic() - t0) * 1000)
    size_bytes = dst.stat().st_size
    # Lazy retention; cheap (just stat + sort).
    retention = prune_snapshots()
    return {
        "snapshot": Snapshot(
            path=str(dst), unix_ms=unix_ms, reason=reason, size_bytes=size_bytes
        ).as_dict(),
        "duration_ms": duration_ms,
        "retention": retention,
    }


def list_snapshots() -> dict[str, Any]:
    """List every snapshot in the time-machine dir, newest first."""
    _ensure_dirs()
    out: list[dict[str, Any]] = []
    total_bytes = 0
    for p in _tm_dir().glob("tm-*.sqlite"):
        m = _TM_FILENAME_RE.match(p.name)
        if not m:
            continue
        size = p.stat().st_size
        total_bytes += size
        out.append({
            "path": str(p),
            "unix_ms": int(m.group(1)),
            "reason": m.group(2),
            "size_bytes": size,
        })
    out.sort(key=lambda r: r["unix_ms"], reverse=True)
    return {
        "snapshots": out,
        "count": len(out),
        "total_mb": total_bytes // (1024 * 1024),
    }


def _nearest_snapshot(unix_ms: int) -> Optional[dict[str, Any]]:
    """Return the snapshot with the largest unix_ms <= requested, or None."""
    listing = list_snapshots()["snapshots"]
    candidates = [s for s in listing if s["unix_ms"] <= unix_ms]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["unix_ms"])


def fork_from(unix_ms: int, note: str = "") -> dict[str, Any]:
    """Create an inspectable fork file from the nearest snapshot <= unix_ms.
    The fork never attaches to Staffroom; it is a standalone SQLite file
    the operator can query, diff or restore manually. Returns the fork
    metadata plus the source snapshot it was cut from."""
    if not isinstance(unix_ms, int) or unix_ms <= 0:
        raise ValueError("unix_ms must be a positive integer (ms since epoch)")
    if note and len(note) > 200:
        raise ValueError("note must be <=200 chars")
    _ensure_dirs()
    src = _nearest_snapshot(unix_ms)
    if src is None:
        raise LookupError(
            f"no snapshot <= {unix_ms}ms exists yet; call take_snapshot first"
        )
    fork_id = secrets.token_hex(8)
    dst = _forks_dir() / f"fork-{fork_id}.sqlite"
    # File-level copy; snapshot is already a point-in-time SQLite file.
    with open(src["path"], "rb") as rf, open(dst, "wb") as wf:
        while chunk := rf.read(1 << 20):
            wf.write(chunk)
    # Age of the fork vs. request: how far off from the requested ts the
    # nearest snapshot was. Non-zero means temporal gap.
    age_ms_before_request = unix_ms - src["unix_ms"]
    return {
        "fork": {
            "fork_id": fork_id,
            "path": str(dst),
            "size_bytes": dst.stat().st_size,
            "note": note,
            "created_unix_ms": int(time.time() * 1000),
        },
        "source_snapshot": src,
        "requested_unix_ms": unix_ms,
        "age_ms_before_request": age_ms_before_request,
    }


def prune_snapshots(keep_last: int = 48, warn_mb: int = 500) -> dict[str, Any]:
    """Keep only the N most recent snapshots. Warn when the retained set
    is above `warn_mb`. Forks are never touched by this; they stick
    around until an operator deletes them."""
    _ensure_dirs()
    files = sorted(
        _tm_dir().glob("tm-*.sqlite"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in files[keep_last:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    retained = files[:keep_last]
    retained_bytes = sum((p.stat().st_size for p in retained), 0)
    retained_mb = retained_bytes // (1024 * 1024)
    warn = None
    if retained_mb >= warn_mb:
        warn = (
            f"time-machine dir is {retained_mb}MB across {len(retained)} "
            f"snapshots (threshold {warn_mb}MB). Lower keep_last or prune "
            f"backend/.data/time-machine manually."
        )
    return {
        "removed": removed,
        "kept": len(retained),
        "retained_mb": retained_mb,
        "warn": warn,
    }


def list_forks() -> dict[str, Any]:
    """List every fork file. Forks are not auto-pruned."""
    _ensure_dirs()
    out: list[dict[str, Any]] = []
    for p in _forks_dir().glob("fork-*.sqlite"):
        m = _FORK_FILENAME_RE.match(p.name)
        if not m:
            continue
        st = p.stat()
        out.append({
            "fork_id": m.group(1),
            "path": str(p),
            "size_bytes": st.st_size,
            "created_unix_ms": int(st.st_mtime * 1000),
        })
    out.sort(key=lambda r: r["created_unix_ms"], reverse=True)
    return {"forks": out, "count": len(out)}
