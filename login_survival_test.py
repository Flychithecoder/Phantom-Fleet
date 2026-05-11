"""
Phantom Fleet — Login Survival Test (read-only diagnostic)

Purpose:
    After 6 months of dormancy, verify which of the ~219 existing Tatiana/Melodie
    accounts still have valid sessions on their cloned IG apps.

What it does:
    1. Enumerates all authorized phones via ADB
    2. For each phone, lists all cloned Instagram packages (com.instagram.*)
    3. For each clone, attempts to launch the app and read the UI state
    4. Classifies every clone as:
        - alive          (logged in, feed visible, ready for actions)
        - needs_reset    (login screen visible, session expired)
        - checkpoint     (IG security challenge, phone/email verification)
        - suspended      (account suspended message)
        - launch_error   (app crashed, won't launch)
        - unknown        (couldn't determine state)
    5. Writes a CSV + JSON report and prints a summary

What it does NOT do:
    - No follow/like/comment/DM actions
    - No account creation or modification
    - No settings changes
    - Nothing written to IG
    - Nothing persisted on the phones (screenshots saved locally only)

Requirements:
    - adb.exe accessible (uses Onimator's bundled adb by default)
    - Python 3.10+, uiautomator2 installed
    - Phones authorized for USB debugging

Usage:
    python login_survival_test.py              # run on all authorized phones
    python login_survival_test.py --dry-run    # list clones only, don't launch
    python login_survival_test.py --phone RF8N10J57DA  # single phone
"""
import argparse
import asyncio
import csv
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

# Companion APK fast-path: if the APK is installed and forwarded, use
# ig_check_session() instead of slow uiautomator dump. Falls back gracefully.
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent / "backend"))
    from phantom_fleet.core.apk_client import APKClient as _APKClient
    _APK_AVAILABLE = True
except ImportError:
    _APKClient = None  # type: ignore[assignment]
    _APK_AVAILABLE = False

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

ADB_PATH = r"C:\Onimator\full_igbot_14.1.8.1\adb.exe"
OUT_DIR = Path(r"C:\Users\User\Desktop\Scaler Pro\orionfarm\survival_reports")
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR = OUT_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

# State detection rules — check UI dump for these patterns
STATE_RULES = [
    # (state_name, [list of substrings to match in UI dump, case-insensitive])
    ("suspended", [
        "account has been disabled",
        "we suspended your account",
        "we've suspended your account",
        "tell us you didn't do",
        "appeal",
    ]),
    ("checkpoint", [
        "help us confirm",
        "confirm it's you",
        "enter the code",
        "security code",
        "unusual login attempt",
        "we detected an unusual",
        "verify your account",
        "two-factor",
    ]),
    ("needs_reset", [
        "log into your account",
        "log in",
        "sign up",
        "forgot password",
        "create new account",
        "switch accounts",
    ]),
    ("alive", [
        # Feed state indicators — home tab, stories tray, etc.
        "home",
        "direct",
        "reels",
        "search",
        "new post",
        "your story",
        "feed",
    ]),
]

LAUNCH_WAIT_SECONDS = 6  # time to wait after launching clone before reading UI
UI_DUMP_RETRIES = 2


# -----------------------------------------------------------------------------
# Data types
# -----------------------------------------------------------------------------

@dataclass
class CloneResult:
    phone_serial: str
    package: str
    state: str  # alive / needs_reset / checkpoint / suspended / launch_error / unknown
    matched_rule: str = ""
    screenshot: str = ""
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# -----------------------------------------------------------------------------
# ADB helpers
# -----------------------------------------------------------------------------

def adb_run(args, serial=None, timeout=30):
    """Run an adb command and return (stdout, stderr, returncode)."""
    cmd = [ADB_PATH]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return (
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
            proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return ("", f"TIMEOUT after {timeout}s", 124)
    except FileNotFoundError:
        return ("", f"adb not found at {ADB_PATH}", 127)


def list_authorized_phones():
    """Return list of (serial, model) tuples for phones in 'device' state."""
    stdout, _, _ = adb_run(["devices", "-l"])
    phones = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        if state != "device":
            continue
        model = ""
        for p in parts[2:]:
            if p.startswith("model:"):
                model = p.split(":", 1)[1]
                break
        phones.append((serial, model))
    return phones


def list_ig_clones(serial):
    """Return list of cloned IG package names on a phone."""
    stdout, _, _ = adb_run(
        ["shell", "pm", "list", "packages", "com.instagram"],
        serial=serial,
    )
    packages = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            packages.append(line[len("package:"):])
    # Sort for stable order
    return sorted(packages)


def force_stop_package(serial, package):
    """Force-stop a package to ensure clean launch state."""
    adb_run(["shell", "am", "force-stop", package], serial=serial, timeout=10)


def launch_package(serial, package):
    """Launch the main activity of a package. Returns True on success."""
    # Use monkey as a universal launcher that doesn't require knowing the activity name
    stdout, stderr, rc = adb_run(
        ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        serial=serial,
        timeout=15,
    )
    return rc == 0 and "Events injected: 1" in stdout


def dump_ui_text(serial):
    """Dump the current UI hierarchy as XML and return the text content."""
    # uiautomator dump writes to /sdcard then we pull it
    for attempt in range(UI_DUMP_RETRIES):
        stdout, stderr, rc = adb_run(
            ["shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"],
            serial=serial,
            timeout=20,
        )
        if rc == 0 and ("UI hierchary dumped" in stdout or "dumped" in stdout.lower()):
            pull_stdout, _, pull_rc = adb_run(
                ["exec-out", "cat", "/sdcard/ui_dump.xml"],
                serial=serial,
                timeout=15,
            )
            if pull_rc == 0 and pull_stdout:
                return pull_stdout
        time.sleep(1)
    return ""


def take_screenshot(serial, out_path):
    """Capture a screenshot from the phone for manual review."""
    try:
        stdout, _, rc = adb_run(
            ["exec-out", "screencap", "-p"],
            serial=serial,
            timeout=15,
        )
        if rc == 0 and stdout:
            # Raw PNG bytes come back as latin1-encoded string from our subprocess wrapper
            # Re-run as bytes capture for reliability
            proc = subprocess.run(
                [ADB_PATH, "-s", serial, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=15,
            )
            if proc.returncode == 0:
                out_path.write_bytes(proc.stdout)
                return True
    except Exception:
        pass
    return False


# -----------------------------------------------------------------------------
# State classification
# -----------------------------------------------------------------------------

def classify_ui_dump(dump_text):
    """Return (state, matched_rule) from a UI dump."""
    if not dump_text:
        return ("unknown", "empty_dump")
    lower = dump_text.lower()
    # Strip XML tags for cleaner matching on visible text
    text_only = re.sub(r"<[^>]+>", " ", lower)
    text_only = re.sub(r"\s+", " ", text_only)

    for state_name, patterns in STATE_RULES:
        for pat in patterns:
            if pat.lower() in text_only:
                return (state_name, pat)
    return ("unknown", "no_rule_matched")


# -----------------------------------------------------------------------------
# Main test loop
# -----------------------------------------------------------------------------

async def test_phone(serial, model, dry_run=False):
    """Run the survival test on all clones of a single phone."""
    results = []
    clones = list_ig_clones(serial)
    print(f"[{serial}] model={model} clones={len(clones)}")

    if not clones:
        return results

    if dry_run:
        for pkg in clones:
            results.append(CloneResult(phone_serial=serial, package=pkg, state="dry_run"))
        return results

    # Try APK fast path first: if the Companion APK is installed and
    # port-forwarded, ig_check_session() returns in ~1s vs ~15s for UI dump.
    apk_ok = False
    if _APK_AVAILABLE and not dry_run:
        try:
            async with _APKClient(serial) as apk:  # type: ignore[union-attr]
                await apk.setup_forward()
                apk_ok = True
                print(f"  [{serial}] APK fast-path active on port {apk.host_port}")
        except Exception as exc:
            print(f"  [{serial}] APK not available ({exc}), using ADB UI dump")
            apk_ok = False

    for i, pkg in enumerate(clones, 1):
        print(f"  [{serial}] {i}/{len(clones)} {pkg}")
        try:
            # --- APK fast path ---------------------------------------------------
            if apk_ok and _APK_AVAILABLE and _APKClient is not None:
                try:
                    async with _APKClient(serial) as apk:
                        status = await apk.ig_check_session(pkg)
                    if status.get("loggedIn") is True:
                        state, matched = "alive", "apk_check_session"
                    elif status.get("needsReauth") is True:
                        state, matched = "checkpoint", "apk_check_session"
                    else:
                        state, matched = "needs_reset", "apk_check_session"
                    results.append(CloneResult(
                        phone_serial=serial, package=pkg,
                        state=state, matched_rule=matched,
                    ))
                    continue
                except Exception as exc:
                    print(f"  [{serial}] APK fast-path failed for {pkg}: {exc}, falling back")

            # --- ADB UI dump fallback --------------------------------------------
            # 1. Force-stop anything running so we get a clean launch
            force_stop_package(serial, pkg)
            await asyncio.sleep(0.5)

            # 2. Launch the clone
            launched = launch_package(serial, pkg)
            if not launched:
                results.append(CloneResult(
                    phone_serial=serial, package=pkg,
                    state="launch_error", error="monkey failed",
                ))
                continue

            # 3. Wait for UI to settle
            await asyncio.sleep(LAUNCH_WAIT_SECONDS)

            # 4. Dump UI state
            dump = dump_ui_text(serial)

            # 5. Save screenshot for manual review
            screenshot_path = SCREENSHOT_DIR / f"{serial}__{pkg}.png"
            take_screenshot(serial, screenshot_path)

            # 6. Classify
            state, matched = classify_ui_dump(dump)
            results.append(CloneResult(
                phone_serial=serial, package=pkg,
                state=state, matched_rule=matched,
                screenshot=str(screenshot_path),
            ))

            # 7. Force-stop to conserve memory
            force_stop_package(serial, pkg)
            await asyncio.sleep(0.3)

        except Exception as e:
            results.append(CloneResult(
                phone_serial=serial, package=pkg,
                state="launch_error", error=str(e)[:200],
            ))

    return results


async def main():
    parser = argparse.ArgumentParser(description="Phantom Fleet login-survival test")
    parser.add_argument("--dry-run", action="store_true", help="List clones but don't launch")
    parser.add_argument("--phone", help="Test a specific phone serial only")
    parser.add_argument("--max-phones", type=int, default=99, help="Max phones to test in parallel")
    args = parser.parse_args()

    print(f"Phantom Fleet Login Survival Test — {datetime.now().isoformat()}")
    print(f"ADB: {ADB_PATH}")
    print(f"Output: {OUT_DIR}")
    print()

    phones = list_authorized_phones()
    if args.phone:
        phones = [(s, m) for s, m in phones if s == args.phone]

    if not phones:
        print("No authorized phones found. Check adb devices output.")
        sys.exit(1)

    print(f"Authorized phones: {len(phones)}")
    for serial, model in phones:
        print(f"  {serial}  {model}")
    print()

    # Run phone tests in parallel (each phone is serialized internally)
    tasks = [test_phone(s, m, dry_run=args.dry_run) for s, m in phones[:args.max_phones]]
    all_results = []
    for task_results in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(task_results, Exception):
            print(f"Phone task failed: {task_results}")
            continue
        all_results.extend(task_results)

    # Save reports
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUT_DIR / f"survival_report_{timestamp}.csv"
    json_path = OUT_DIR / f"survival_report_{timestamp}.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "phone_serial", "package", "state", "matched_rule",
            "screenshot", "error", "timestamp",
        ])
        writer.writeheader()
        for r in all_results:
            writer.writerow(asdict(r))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in all_results], f, indent=2)

    # Print summary
    print()
    print("=" * 60)
    print("SURVIVAL REPORT SUMMARY")
    print("=" * 60)
    state_counts = {}
    per_phone = {}
    for r in all_results:
        state_counts[r.state] = state_counts.get(r.state, 0) + 1
        per_phone.setdefault(r.phone_serial, {}).setdefault(r.state, 0)
        per_phone[r.phone_serial][r.state] += 1

    print(f"Total clones tested: {len(all_results)}")
    for state, count in sorted(state_counts.items(), key=lambda x: -x[1]):
        print(f"  {state:15s} {count:4d}")

    print()
    print("Per-phone breakdown:")
    print(f"  {'Phone':22s} {'alive':>6} {'reset':>6} {'chkpt':>6} {'susp':>6} {'err':>5} {'unk':>5}")
    for phone, states in sorted(per_phone.items()):
        alive = states.get("alive", 0)
        reset = states.get("needs_reset", 0)
        chkpt = states.get("checkpoint", 0)
        susp = states.get("suspended", 0)
        err = states.get("launch_error", 0)
        unk = states.get("unknown", 0)
        print(f"  {phone:22s} {alive:6d} {reset:6d} {chkpt:6d} {susp:6d} {err:5d} {unk:5d}")

    print()
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    print(f"Screenshots: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
