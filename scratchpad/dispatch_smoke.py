"""End-to-end dispatcher smoke test.

Spins up a mock APK HTTP server on localhost that replays the same
response shapes the real companion APK does (ok, login_required,
checkpoint, 429). Seeds a persona-store with alive accounts pointing
at that server, enqueues one action per outcome scenario, runs the
dispatcher, asserts every outcome row + chain row + tick_log row.

No phones involved.
"""
from __future__ import annotations

import http.server
import json
import shutil
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(r"C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone")
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="pf-dispatch-"))
store = tmp / "persona-store.sqlite"

from ops.sched import _store  # noqa: E402
_store.STORE = store

from ops.dispatch import worker  # noqa: E402
from ops.intel import chain as intel_chain  # noqa: E402

NOW = int(time.time() * 1000)
passed = failed = 0


def check(name, cond, info=""):
    global passed, failed
    tag = "PASS" if cond else "FAIL"
    if cond: passed += 1
    else:    failed += 1
    print(f"  [{tag}] {name:62s} {info}")


# ---------- mock APK ----------
# Every POST handler reads the path and returns a canned response.
SCENARIOS = {
    "/instagram/engage/follow": (200, {"ok": True, "status": "followed"}),
    "/instagram/engage/like":   (200, {"ok": True}),
    "/instagram/engage/view_stories": (200, {"error": "accessibility_unbound"}),
    "/instagram/engage/comment": (200, {"ok": False, "error": "checkpoint",
                                        "message": "checkpoint required"}),
    "/instagram/engage/unfollow": (429, {"error": "rate_limited"}),
}


class MockAPKHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass  # silence

    def do_POST(self):
        status, body = SCENARIOS.get(self.path, (404, {"error": "no_route"}))
        self._reply(status, body)

    def do_GET(self):
        self._reply(200, {"ok": True})

    def _reply(self, status, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_mock(port: int) -> socketserver.TCPServer:
    srv = socketserver.TCPServer(("127.0.0.1", port), MockAPKHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv


PORT = 18775
srv = start_mock(PORT)
time.sleep(0.1)


# ---------- seed ----------
_store.apply_migrations()
with _store.connect() as con:
    con.executescript(f"""
    INSERT INTO personas (name, mode, settings_json, imported_at_ms)
      VALUES ('Tatiana','default','{{}}',0);
    INSERT INTO devices (serial, model, region, source, imported_at_ms)
      VALUES ('MOCK-DEV-1', 'SM_G770F', 'EU', 'onimator', 0);
    INSERT INTO device_endpoints (serial, wifi_ip, port, last_seen_ms)
      VALUES ('MOCK-DEV-1', '127.0.0.1', {PORT}, 0);
    INSERT INTO accounts (username, persona, device_serial, status, imported_at_ms) VALUES
      ('acct_follow',   'Tatiana', 'MOCK-DEV-1', 'alive', 0),
      ('acct_like',     'Tatiana', 'MOCK-DEV-1', 'alive', 0),
      ('acct_story',    'Tatiana', 'MOCK-DEV-1', 'alive', 0),
      ('acct_comment',  'Tatiana', 'MOCK-DEV-1', 'alive', 0),
      ('acct_rl',       'Tatiana', 'MOCK-DEV-1', 'alive', 0);
    INSERT INTO clone_assignments (account_id, clone_package, assigned_ms) VALUES
      (1, 'com.instagram.android', 0),
      (2, 'com.instagram.android.clone1', 0),
      (3, 'com.instagram.android.clone2', 0),
      (4, 'com.instagram.android.clone3', 0),
      (5, 'com.instagram.android.clone4', 0);
    """)
    # Build queue rows, each with the right params for its endpoint.
    cases = [
        (1, "follows",   {"targetUsername": "trending_account"}),
        (2, "likes",     {"mediaCode": "ABCXYZ"}),
        (3, "stories",   {"usernames": ["x", "y"]}),
        (4, "comments",  {"mediaCode": "ABCXYZ", "text": "hey"}),
        (5, "unfollow",  {"targetUsername": "cold_lead"}),
    ]
    for acct_id, kind, params in cases:
        con.execute(
            "INSERT INTO action_queue (account_id, kind, due_ms, params_json, state, created_ms) "
            "VALUES (?, ?, ?, ?, 'due', ?)",
            (acct_id, kind, NOW - 1000, json.dumps(params), NOW),
        )
    # And one 'missing target' row: likes with no mediaCode.
    con.execute(
        "INSERT INTO action_queue (account_id, kind, due_ms, params_json, state, created_ms) "
        "VALUES (1, 'likes', ?, '{}', 'due', ?)",
        (NOW - 500, NOW),
    )
    # And one 'no endpoint' row: a nonsense kind.
    con.execute(
        "INSERT INTO action_queue (account_id, kind, due_ms, params_json, state, created_ms) "
        "VALUES (1, 'nonsense', ?, '{}', 'due', ?)",
        (NOW - 400, NOW),
    )


# ---------- dry-run first ----------
dry = worker.run(apply=False, max_actions=50, now_ms=NOW)
check("dry-run claims every due row",
      dry["totals"]["claimed"] == 7, f"claimed={dry['totals']['claimed']}")
check("dry-run dispatches zero", dry["totals"]["dispatched"] == 0, "")
# All claimed rows should be released back to 'due'.
with _store.connect() as con:
    still_due = con.execute(
        "SELECT COUNT(*) FROM action_queue WHERE state='due'"
    ).fetchone()[0]
check("dry-run releases every claim back to due", still_due == 7,
      f"still_due={still_due}")


# ---------- apply ----------
# PER_DEVICE_COOLDOWN is 150ms; 7 rows share one device, so most will
# be skipped by cooldown. Run the worker in a loop until the queue is
# drained.
total_dispatched = 0
total_ok = 0
total_err = 0
total_runs = 0
for _ in range(40):
    out = worker.run(apply=True, max_actions=50)
    total_dispatched += out["totals"]["dispatched"]
    total_ok += out["totals"]["ok"]
    total_err += out["totals"]["err"]
    total_runs += 1
    with _store.connect() as con:
        still_due = con.execute(
            "SELECT COUNT(*) FROM action_queue WHERE state='due'"
        ).fetchone()[0]
    if still_due == 0:
        break
    time.sleep(0.2)   # let per-device cooldown expire

check("every due row drained after N dispatcher loops",
      still_due == 0, f"still_due={still_due} runs={total_runs}")
check("5 real actions + 2 pre-HTTP (missing/nonsense) handled",
      total_dispatched == 5 and total_ok >= 1 and total_err >= 2,
      f"disp={total_dispatched} ok={total_ok} err={total_err}")


# ---------- verify outcomes landed ----------
# Key by (account_id, outcome) presence — account 1 has 3 rows (one real
# follow, one missing-target garbage, one unknown-kind garbage), so the
# follow-ok outcome must appear among them even if it isn't "latest".
with _store.connect() as con:
    pairs = {(r["account_id"], r["outcome"]) for r in con.execute(
        "SELECT account_id, outcome FROM action_results"
    ).fetchall()}
check("follow -> ok lands for acct 1", (1, "ok") in pairs, f"pairs={sorted(pairs)}")
check("like -> ok lands for acct 2",   (2, "ok") in pairs, "")
check("story -> accessibility_unbound lands for acct 3",
      (3, "accessibility_unbound") in pairs, "")
check("comment -> checkpoint lands for acct 4",
      (4, "checkpoint") in pairs, "")
check("unfollow -> ig_rate_limited lands for acct 5",
      (5, "ig_rate_limited") in pairs, "")
check("pre-HTTP garbage recorded as missing_target + unknown",
      (1, "missing_target") in pairs and (1, "unknown") in pairs, "")


# ---------- every live dispatch wrote a chain row ----------
with _store.connect() as con:
    chain_rows = int(con.execute(
        "SELECT COUNT(*) FROM audit_chain WHERE kind='dispatch'"
    ).fetchone()[0])
    tick_rows = int(con.execute(
        "SELECT COUNT(*) FROM tick_log WHERE kind='dispatch' AND is_shadow=0"
    ).fetchone()[0])
check("every live dispatcher pass landed a chain row",
      chain_rows >= 1 and chain_rows == tick_rows,
      f"chain={chain_rows} tick={tick_rows}")

v = intel_chain.verify_chain()
check("audit_chain verifies clean across dispatcher activity",
      v["ok"], f"rows={v['rows']} tampered={len(v['tampered'])}")


# ---------- dispatcher is replayable ----------
with _store.connect() as con:
    first_dispatch = dict(con.execute(
        "SELECT * FROM tick_log WHERE kind='dispatch' AND is_shadow=0 "
        "ORDER BY id LIMIT 1"
    ).fetchone())
replay_decisions = json.loads(first_dispatch["decisions_json"])
check("dispatcher tick stored decisions",
      "totals" in replay_decisions and "results" in replay_decisions,
      f"keys={list(replay_decisions)}")

srv.shutdown()
print(f"\n--- {passed} PASS / {failed} FAIL ---")

try: shutil.rmtree(tmp)
except Exception: pass

sys.exit(0 if failed == 0 else 1)
