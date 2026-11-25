"""Phase 0 pre-flight #1 — enable Wi-Fi ADB on every USB-connected phone.

Deterministic. No agents.

What it does, per device:
 1. Confirm device is `device` state (not unauthorized / offline).
 2. Read the phone's current Wi-Fi IPv4 off `wlan0`.
 3. Set `persist.adb.wifi` + `service.adb.tcp.port = 5555` and bounce adbd
    into TCP mode via `adb tcpip 5555`.
 4. Attempt `adb connect <ip>:5555` and verify the Wi-Fi handle now
    answers `getprop ro.product.model`.

Writes one NDJSON line per device to ops/logs/01_wifi_adb.ndjson and a
summary to stdout. Non-destructive — a phone already on Wi-Fi ADB is a
no-op success.

USB cable stays plugged until this script reports the whole fleet green;
only then is it safe to pull the hub.

Usage:
    python 01_wifi_adb.py                    # farm1, all devices
    python 01_wifi_adb.py --dry-run          # prove-out, no state change
    python 01_wifi_adb.py --only RF8N10J57DA # one device
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _adb import (  # noqa: E402
    adb, adb_global, audit, list_connected, load_farm,
    parallel_map, print_table, result_dict,
)

SCRIPT = "01_wifi_adb"


def read_wifi_ip(serial: str) -> str | None:
    r = adb(serial, "shell", "ip", "-4", "addr", "show", "wlan0")
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            return line.split()[1].split("/")[0]
    return None


def enable_tcpip(serial: str, dry_run: bool) -> dict:
    if dry_run:
        return {"skipped": "dry_run"}
    r = adb_global("-s", serial, "tcpip", "5555", timeout=10)
    return result_dict(r)


def connect_wifi(ip: str) -> dict:
    r = adb_global("connect", f"{ip}:5555", timeout=10)
    return result_dict(r)


def verify_wifi(ip: str) -> dict:
    r = adb(f"{ip}:5555", "shell", "getprop", "ro.product.model", timeout=10)
    return result_dict(r)


def process_device(serial: str, dry_run: bool) -> dict:
    out = {"serial": serial}
    ip = read_wifi_ip(serial)
    out["wifi_ip"] = ip
    if not ip:
        out["status"] = "no_wifi_ip"
        return out
    out["tcpip"] = enable_tcpip(serial, dry_run)
    if dry_run:
        out["status"] = "dry_run_ok"
        return out
    time.sleep(1.5)  # adbd needs a moment to rebind
    out["connect"] = connect_wifi(ip)
    out["verify"] = verify_wifi(ip)
    out["status"] = (
        "ok" if out["verify"]["returncode"] == 0 and out["verify"]["stdout"]
        else "verify_failed"
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--farm", default="farm1")
    ap.add_argument("--only", help="limit to this one serial")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--parallelism", type=int, default=8)
    args = ap.parse_args()

    farm = load_farm(args.farm)
    expected = [d["serial"] for d in farm["devices"] if not d.get("auth_pending")]
    if args.only:
        expected = [s for s in expected if s == args.only]
        if not expected:
            print(f"serial {args.only} not in {args.farm} (or is auth_pending)")
            return 2

    connected = set(list_connected())
    skipped = [s for s in expected if s not in connected]
    to_process = [s for s in expected if s in connected]

    print(f"farm={args.farm} expected={len(expected)} "
          f"usb_connected={len(to_process)} skipped={len(skipped)} "
          f"dry_run={args.dry_run}")
    if skipped:
        print(f"  skipped (no USB session): {', '.join(skipped)}")

    results = parallel_map(
        to_process, lambda s: process_device(s, args.dry_run),
        parallelism=args.parallelism,
    )
    rows = [{"serial": s, **r} for s, r in sorted(results)]
    for row in rows:
        audit(SCRIPT, row)

    print()
    print_table(
        rows,
        cols=["serial", "wifi_ip", "status"],
    )
    ok = sum(1 for r in rows if r.get("status") in ("ok", "dry_run_ok"))
    fail = len(rows) - ok
    print(f"\n{ok} ok / {fail} fail / {len(skipped)} skipped")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
