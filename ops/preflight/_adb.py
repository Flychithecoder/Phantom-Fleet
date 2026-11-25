"""Deterministic ADB helpers for Phase 0 pre-flight.

No agents, no AI. Pure subprocess wrappers + NDJSON audit trail.

Design rules:
- Every call to adb is captured: stdout, stderr, returncode, ms.
- Every run writes one NDJSON line per (device, command) to the run log.
- No command is destructive by default; destructive ops are gated behind
  an explicit `dry_run=False` + an operator-supplied `confirm_token`.
- Concurrency is bounded (default 8 parallel devices) so a USB hub or
  router's ARP table doesn't thrash.
- Timeouts are mandatory; adb hangs are the single biggest source of
  farm-ops wall-clock loss.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Iterable

ADB = os.environ.get("PF_ADB_BIN", "adb")
DEFAULT_TIMEOUT_S = 15
DEFAULT_PARALLELISM = 8

OPS_DIR = Path(__file__).resolve().parent.parent
RUN_LOG_DIR = OPS_DIR / "logs"
RUN_LOG_DIR.mkdir(exist_ok=True)


@dataclass
class AdbResult:
    serial: str | None
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


def _run(cmd: list[str], timeout: int = DEFAULT_TIMEOUT_S) -> AdbResult:
    t0 = time.monotonic()
    serial = None
    if cmd[:2] == [ADB, "-s"]:
        serial = cmd[2]
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return AdbResult(
            serial=serial, cmd=cmd, returncode=p.returncode,
            stdout=p.stdout.strip(), stderr=p.stderr.strip(),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except subprocess.TimeoutExpired:
        return AdbResult(
            serial=serial, cmd=cmd, returncode=-1,
            stdout="", stderr=f"timeout after {timeout}s",
            duration_ms=int((time.monotonic() - t0) * 1000),
            timed_out=True,
        )
    except FileNotFoundError:
        return AdbResult(
            serial=serial, cmd=cmd, returncode=-2,
            stdout="", stderr=f"{ADB} not on PATH; set PF_ADB_BIN",
            duration_ms=0,
        )


def adb(serial: str, *args: str, timeout: int = DEFAULT_TIMEOUT_S) -> AdbResult:
    return _run([ADB, "-s", serial, *args], timeout=timeout)


def adb_global(*args: str, timeout: int = DEFAULT_TIMEOUT_S) -> AdbResult:
    return _run([ADB, *args], timeout=timeout)


def list_connected() -> list[str]:
    r = adb_global("devices")
    serials: list[str] = []
    for line in r.stdout.splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        serial, state = line.split("\t", 1)
        if state.strip() == "device":
            serials.append(serial)
    return serials


def load_farm(farm_id: str = "farm1") -> dict[str, Any]:
    with (OPS_DIR / "devices" / f"{farm_id}.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def parallel_map(
    serials: Iterable[str],
    fn: Callable[[str], Any],
    parallelism: int = DEFAULT_PARALLELISM,
) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    with ThreadPoolExecutor(max_workers=parallelism) as ex:
        futures = {ex.submit(fn, s): s for s in serials}
        for fut in as_completed(futures):
            serial = futures[fut]
            try:
                out.append((serial, fut.result()))
            except Exception as e:
                out.append((serial, {"error": str(e)}))
    return out


def audit(script: str, record: dict[str, Any]) -> None:
    path = RUN_LOG_DIR / f"{script}.ndjson"
    record = {"ts_ms": int(time.time() * 1000), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def result_dict(r: AdbResult) -> dict[str, Any]:
    d = asdict(r)
    d["cmd"] = " ".join(r.cmd)
    return d


def print_table(rows: list[dict[str, Any]], cols: list[str]) -> None:
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))
