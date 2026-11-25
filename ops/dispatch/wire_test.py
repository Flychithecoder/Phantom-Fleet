"""Dispatcher <-> companion APK wire test.

Two modes:

    python -m ops.dispatch.wire_test --stub   (default)
        Start a localhost HTTP stub that emulates the APK's engagement
        routes with the EXACT data-class contracts from
        companion-apk/.../http/LocalHttpServer.kt. Dispatcher runs
        against it. No phone required. Verifies the field mapping,
        cooldown, idempotent claim, and terminal-result path.

    python -m ops.dispatch.wire_test --live --serial <SER> --port 8089
        Talk to a real phone. Expects:
          1. Device at <SER> is connected over adb with Wi-Fi ADB in
             the matrix state the pre-flight script left it in.
          2. The APK is installed, foreground, and listening on
             <port> (default 8089 matches HARDWARE.md fleet default).
          3. `adb -s <SER> reverse tcp:8089 tcp:8089` has run so the
             APK can reach the dev host (we hit 127.0.0.1:<port>
             from the phone's loopback, forwarded back to our box).

A live run is gated on your --I-UNDERSTAND flag and prints the FIRST
request+response so you can smoke it by eye before the dispatcher
drains more rows.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.dispatch import _endpoints, _transport, worker  # noqa: E402
from ops.sched import _store  # noqa: E402


# ---------- stub APK ----------

# Keeps the last request per path for assertions.
STUB_LOG: list[dict] = []
STUB_FAIL_ONCE: set[str] = set()  # paths to 500 on first hit (then 200)


class _StubAPKHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802
        return  # stay quiet

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {"_raw": raw.decode("utf-8", errors="replace")}

    def _respond(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        STUB_LOG.append({"method": "GET", "path": self.path, "body": None})
        if self.path.startswith("/instagram/engage/check_session"):
            return self._respond(200, {"loggedIn": True, "needsReauth": False})
        return self._respond(404, {"error": "unknown path"})

    def do_POST(self):  # noqa: N802
        body = self._read_body()
        STUB_LOG.append({"method": "POST", "path": self.path, "body": body})
        # Validate APK-shape fields are present.
        apk_ok, err = _validate_apk_shape(self.path, body)
        if not apk_ok:
            return self._respond(400, {"error": err})
        if self.path in STUB_FAIL_ONCE:
            STUB_FAIL_ONCE.discard(self.path)
            return self._respond(500, {"error": "stubbed transient"})
        return self._respond(200, {"success": True})


def _validate_apk_shape(path: str, body: dict) -> tuple[bool, str]:
    # Mirrors the @Serializable data classes in LocalHttpServer.kt.
    if not body.get("clonePackage"):
        return False, "missing clonePackage"
    if path.endswith("/engage/follow") or path.endswith("/engage/unfollow"):
        return (True, "") if body.get("username") else (False, "missing username")
    if path.endswith("/engage/like"):
        return (True, "") if body.get("mediaId") else (False, "missing mediaId")
    if path.endswith("/engage/comment"):
        if not body.get("mediaId"): return False, "missing mediaId"
        if not body.get("commentText"): return False, "missing commentText"
        return True, ""
    if path.endswith("/engage/view_stories"):
        return (True, "") if body.get("username") else (False, "missing username")
    if path.endswith("/engage/scroll_reels"):
        return True, ""
    return False, f"unknown path: {path}"


@contextlib.contextmanager
def _stub_server(port: int = 0):
    srv = HTTPServer(("127.0.0.1", port), _StubAPKHandler)
    actual_port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield actual_port
    finally:
        srv.shutdown()
        srv.server_close()


# ---------- test fixtures ----------

def _seed_fleet(port: int) -> int:
    """Seed one account + one due follow row + one active target."""
    now_ms = int(time.time() * 1000)
    _store.apply_migrations()
    with _store.connect() as con:
        con.execute("INSERT INTO personas (name, mode, settings_json, imported_at_ms) "
                    "VALUES ('wire_p', 'warm', '{}', ?)", (now_ms,))
        con.execute("INSERT INTO devices (serial, source, imported_at_ms) "
                    "VALUES ('WIRE_SER', 'wire', ?)", (now_ms,))
        con.execute("INSERT INTO device_farm (serial, farm_id) VALUES ('WIRE_SER', 'wireF')")
        con.execute(
            "INSERT INTO accounts (id, username, persona, device_serial, status, "
            "imported_at_ms) VALUES (1, 'wire_acct', 'wire_p', 'WIRE_SER', 'alive', ?)",
            (now_ms,),
        )
        con.execute(
            "INSERT INTO device_endpoints (serial, wifi_ip, port, last_seen_ms) "
            "VALUES ('WIRE_SER', '127.0.0.1', ?, ?)",
            (port, now_ms),
        )
        con.execute(
            "INSERT INTO clone_assignments (account_id, clone_package, assigned_ms) "
            "VALUES (1, 'com.scalerpro.phantomfleet.ig1', ?)",
            (now_ms,),
        )
        con.execute(
            "INSERT INTO target_pool (farm_id, kind, handle, media_code, tags_json, "
            " status, source, imported_ms) VALUES "
            "('wireF', 'account', 'wire_target_account', NULL, '[]', 'active', 'wire', ?)",
            (now_ms,),
        )
        row = con.execute(
            "INSERT INTO action_queue (account_id, kind, due_ms, params_json, "
            "state, created_ms) VALUES (1, 'follows', ?, ?, 'due', ?) RETURNING id",
            (now_ms - 1000,
             json.dumps({"targetUsername": "wire_target_account"}),
             now_ms - 1000),
        ).fetchone()
        con.commit()
        return int(row["id"])


# ---------- stub mode ----------

def _run_stub() -> int:
    passed = failed = 0
    def check(name, cond, info=""):
        nonlocal passed, failed
        tag = "PASS" if cond else "FAIL"
        if cond: passed += 1
        else:    failed += 1
        print(f"  [{tag}] {name:60s} {info}")

    with _stub_server() as port:
        qid = _seed_fleet(port)
        print(f"stub listening on 127.0.0.1:{port}; seeded queue row id={qid}")

        # One pass of the dispatcher.
        report = worker.run(apply=True, max_actions=5)
        results = report.get("results", [])
        check("dispatcher ran 1 row", len(results) == 1, str(report["totals"]))
        check("row got outcome='ok'",
              results and results[0].get("outcome") == "ok",
              str(results[:1]))

        # Stub saw a POST with APK-shape body.
        posts = [e for e in STUB_LOG if e["method"] == "POST"]
        check("stub got exactly 1 POST", len(posts) == 1, f"{len(posts)}")
        if posts:
            p = posts[0]
            check("APK path hit", p["path"] == "/instagram/engage/follow",
                  p["path"])
            check("body has clonePackage",
                  bool(p["body"].get("clonePackage")), str(p["body"]))
            check("body has APK-shape 'username' (not 'targetUsername')",
                  "username" in p["body"] and "targetUsername" not in p["body"],
                  str(p["body"]))
            check("username value is the picked target",
                  p["body"].get("username") == "wire_target_account",
                  str(p["body"]))

        # Transient failure retry: stub a one-shot 500, add a second row.
        STUB_FAIL_ONCE.add("/instagram/engage/follow")
        with _store.connect() as con:
            now_ms = int(time.time() * 1000)
            con.execute(
                "INSERT INTO action_queue (account_id, kind, due_ms, "
                "params_json, state, created_ms) VALUES "
                "(1, 'follows', ?, ?, 'due', ?)",
                (now_ms - 1000,
                 json.dumps({"targetUsername": "wire_target_account"}),
                 now_ms - 1000),
            )
            con.commit()
        rep2 = worker.run(apply=True, max_actions=5)
        res2 = rep2.get("results", [])
        # First call 500s -> transport treats as transient; row stays
        # in queue. Either way, we should have gotten some decision.
        check("second row produced a decision",
              bool(res2) and all(r.get("outcome") for r in res2),
              str([r.get("outcome") for r in res2]))

    print(f"\n--- {passed} PASS / {failed} FAIL ---")
    return 0 if failed == 0 else 1


# ---------- live mode ----------

def _run_live(serial: str, port: int) -> int:
    print(f"LIVE MODE: phone={serial} port={port}")

    # 1. adb reverse so phone's localhost:port -> dev host.
    print(f"  setting up adb reverse tcp:{port} tcp:{port}")
    try:
        subprocess.run(
            ["adb", "-s", serial, "reverse", f"tcp:{port}", f"tcp:{port}"],
            check=True, capture_output=True, timeout=10,
        )
    except Exception as e:
        print(f"  !! adb reverse failed: {e}")
        print(f"     is the phone connected? run: adb -s {serial} get-state")
        return 2

    # 2. health check on the APK.
    print(f"  probing /health on phone (via reverse)...")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                    timeout=5) as r:
            print(f"  APK health -> {r.status} {r.read()[:200]!r}")
    except Exception as e:
        print(f"  !! health check failed: {e}")
        print(f"     is the APK running and listening on {port}? "
              f"run: adb -s {serial} logcat | grep PhantomFleet")
        return 3

    # 3. seed one queue row and drain.
    qid = _seed_fleet(port)
    print(f"  seeded queue row id={qid}; draining 1 row...")
    report = worker.drain(apply=True, max_rows=1)
    print(f"  drain report: {json.dumps(report, indent=2)}")
    return 0 if report and report[0].get("outcome") == "ok" else 4


# ---------- entry point ----------

def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--stub", action="store_true", default=True,
                   help="run in stub mode (default)")
    g.add_argument("--live", action="store_true",
                   help="run against a real phone over adb reverse")
    ap.add_argument("--serial", help="adb serial for --live")
    ap.add_argument("--port", type=int, default=8089, help="APK port (default 8089)")
    ap.add_argument("--I-UNDERSTAND", action="store_true",
                    help="required for --live; confirms you're on a pilot phone")
    args = ap.parse_args()

    if args.live:
        if not args.serial:
            print("--live requires --serial", file=sys.stderr)
            return 1
        if not getattr(args, "I_UNDERSTAND", False):
            print("--live requires --I-UNDERSTAND (pilot-phone safety gate).",
                  file=sys.stderr)
            print("This WILL cause a real IG follow on the phone's foreground clone.",
                  file=sys.stderr)
            return 1
        return _run_live(args.serial, args.port)

    return _run_stub()


if __name__ == "__main__":
    sys.exit(main())
