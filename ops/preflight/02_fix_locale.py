"""Phase 0 pre-flight #2 — fix the fleet-wide en-GB / America/New_York
contradiction flagged in HARDWARE.md.

Deterministic. No agents.

Strategy:
 - Phones live in New York (TrumpProxies NYC personas). The whole fleet
   should look like native US users. Locale -> en-US, country -> US.
 - Timezone stays America/New_York (correct already) but we assert it
   rather than assume — measure, don't assume.
 - Executed via the Android `BOOT_COMPLETED`-style locale broadcast; on
   SM-G770 stock firmware the reliable lever is
   `settings put system system_locales en-US` + `setprop persist.sys.locale en-US`
   + a `am broadcast android.intent.action.LOCALE_CHANGED` to repaint UIs
   without a reboot.

Non-destructive: writes the new locale, reads it back, and reports. If
the phone is already en-US it's a no-op success. No account data
touched.

Usage:
    python 02_fix_locale.py --dry-run
    python 02_fix_locale.py --apply
    python 02_fix_locale.py --apply --only RF8N10J57DA
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _adb import (  # noqa: E402
    adb, audit, list_connected, load_farm, parallel_map, print_table,
    result_dict,
)

SCRIPT = "02_fix_locale"

TARGET_LOCALE = "en-US"
TARGET_TZ = "America/New_York"


def read_state(serial: str) -> dict:
    locale = adb(serial, "shell", "getprop", "persist.sys.locale").stdout
    sys_locale = adb(serial, "shell", "getprop", "ro.product.locale").stdout
    tz = adb(serial, "shell", "getprop", "persist.sys.timezone").stdout
    country = adb(serial, "shell", "getprop", "persist.sys.country").stdout
    return {
        "locale_before": locale or sys_locale,
        "country_before": country,
        "timezone_before": tz,
    }


def apply_locale(serial: str) -> list[dict]:
    steps = []
    steps.append(result_dict(adb(
        serial, "shell", "settings", "put", "system", "system_locales",
        TARGET_LOCALE,
    )))
    steps.append(result_dict(adb(
        serial, "shell", "setprop", "persist.sys.locale", TARGET_LOCALE,
    )))
    steps.append(result_dict(adb(
        serial, "shell", "setprop", "persist.sys.country", "US",
    )))
    steps.append(result_dict(adb(
        serial, "shell", "am", "broadcast", "-a",
        "android.intent.action.LOCALE_CHANGED",
    )))
    return steps


def verify(serial: str) -> dict:
    return {
        "locale_after": adb(serial, "shell", "getprop", "persist.sys.locale").stdout,
        "country_after": adb(serial, "shell", "getprop", "persist.sys.country").stdout,
        "timezone_after": adb(serial, "shell", "getprop", "persist.sys.timezone").stdout,
    }


def process_device(serial: str, apply: bool) -> dict:
    before = read_state(serial)
    out = {"serial": serial, **before}
    if not apply:
        out["status"] = "dry_run"
        return out
    if before["locale_before"] == TARGET_LOCALE and before["country_before"] == "US":
        out["status"] = "already_ok"
        out["locale_after"] = TARGET_LOCALE
        out["country_after"] = "US"
        return out
    out["apply_steps"] = apply_locale(serial)
    out.update(verify(serial))
    out["status"] = (
        "ok"
        if out["locale_after"] == TARGET_LOCALE and out["country_after"] == "US"
        else "verify_failed"
    )
    out["tz_matches"] = out.get("timezone_after", "") == TARGET_TZ
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--farm", default="farm1")
    ap.add_argument("--only", help="limit to this one serial")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--parallelism", type=int, default=8)
    args = ap.parse_args()

    farm = load_farm(args.farm)
    expected = [d["serial"] for d in farm["devices"] if not d.get("auth_pending")]
    if args.only:
        expected = [s for s in expected if s == args.only]

    connected = set(list_connected())
    to_process = [s for s in expected if s in connected]
    skipped = [s for s in expected if s not in connected]

    print(f"farm={args.farm} expected={len(expected)} "
          f"online={len(to_process)} skipped={len(skipped)} apply={args.apply}")

    results = parallel_map(
        to_process, lambda s: process_device(s, args.apply),
        parallelism=args.parallelism,
    )
    rows = [{"serial": s, **r} for s, r in sorted(results)]
    for row in rows:
        audit(SCRIPT, row)
    print()
    print_table(
        rows,
        cols=["serial", "locale_before", "locale_after",
              "country_after", "timezone_before", "status"],
    )
    ok = sum(1 for r in rows if r.get("status") in ("ok", "already_ok", "dry_run"))
    fail = len(rows) - ok
    print(f"\n{ok} ok / {fail} fail / {len(skipped)} skipped")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
