"""Verify ops/sched/* ticks auto-log to tick_log + audit_chain."""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(r"C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone")
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="pf-wired-"))
store = tmp / "persona-store.sqlite"

from ops.sched import _store  # noqa: E402
_store.STORE = store

from ops.sched import tick as sched_tick  # noqa: E402
from ops.sched import recovery, replacement, proxy  # noqa: E402
from ops.intel import replay as intel_replay  # noqa: E402
from ops.intel import chain as intel_chain  # noqa: E402

NOW = int(time.time() * 1000)
passed = failed = 0


def check(name, cond, info=""):
    global passed, failed
    tag = "PASS" if cond else "FAIL"
    if cond: passed += 1
    else:    failed += 1
    print(f"  [{tag}] {name:60s} {info}")


def seed():
    _store.apply_migrations()
    with _store.connect() as con:
        con.executescript("""
        INSERT INTO personas (name, mode, settings_json, imported_at_ms)
          VALUES ('Tatiana','default','{}',0);
        INSERT INTO persona_profiles (persona,diurnal_peak_hour_local,timezone)
          VALUES ('Tatiana', 14, 'America/New_York');
        INSERT INTO devices (serial, model, region, source, imported_at_ms)
          VALUES ('RF8N10J57DA', 'SM_G770F', 'EU', 'onimator', 0);
        INSERT INTO accounts (username, persona, device_serial, status, imported_at_ms)
          VALUES ('acct_a', 'Tatiana', 'RF8N10J57DA', 'alive', 0),
                 ('acct_b', 'Tatiana', 'RF8N10J57DA', 'dead',  0);
        INSERT INTO account_schedule_state (account_id, warming_day, last_tick_ms)
          VALUES (1, 3, NULL);
        """)
        # one action_result on the alive account so proxy has a feed
        con.execute(
            "INSERT INTO action_queue "
            "(id, account_id, kind, due_ms, params_json, state, created_ms) "
            "VALUES (1, 1, 'like', ?, '{}', 'done', ?)",
            (NOW, NOW),
        )
        con.execute(
            "INSERT INTO action_results "
            "(action_id, account_id, outcome, latency_ms, signal_json, ts_ms) "
            "VALUES (1, 1, 'ok', 900, '{}', ?)", (NOW,),
        )


def count(table: str, where: str = "1=1") -> int:
    with _store.connect() as con:
        return int(con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])


seed()

# --- scheduler tick (apply) ---
r = sched_tick.tick(apply=True)
check("tick returns tick_id + chain_head", bool(r.get("tick_id")) and bool(r.get("chain_head")),
      f"tid={r.get('tick_id')} head={str(r.get('chain_head'))[:12]}...")
check("tick_log has 1 live scheduler row",
      count("tick_log", "kind='scheduler' AND is_shadow=0") == 1, "")
check("audit_chain has 1 scheduler row",
      count("audit_chain", "kind='scheduler'") == 1, "")

# --- scheduler dry-run (shadow) ---
# Reset last_tick_ms so accounts_due returns the account again.
with _store.connect() as con:
    con.execute("UPDATE account_schedule_state SET last_tick_ms = NULL")
r2 = sched_tick.tick(apply=False)
check("dry-run tick logs as is_shadow=1",
      count("tick_log", "kind='scheduler' AND is_shadow=1") >= 1, "")
check("dry-run does NOT touch audit_chain",
      count("audit_chain", "kind='scheduler'") == 1, "")

# --- recovery (apply) ---
rec = recovery.run(apply=True)
check("recovery writes tick_log + chain",
      count("tick_log", "kind='recovery'") >= 1
      and count("audit_chain", "kind='recovery'") == 1,
      f"tick_id={rec.get('tick_id')}")

# --- replacement (apply) ---
rep = replacement.run(apply=True)
check("replacement writes tick_log + chain",
      count("tick_log", "kind='replacement'") >= 1
      and count("audit_chain", "kind='replacement'") == 1,
      f"emitted={len(rep['emitted'])}")

# --- proxy (apply) ---
pr = proxy.run(apply=True, plan_ids=["trumpproxies_yuge"])
check("proxy writes tick_log + chain",
      count("tick_log", "kind='proxy'") >= 1
      and count("audit_chain", "kind='proxy'") == 1,
      f"decisions={len(pr['decisions'])}")

# --- chain integrity across heterogeneous kinds ---
v = intel_chain.verify_chain()
check("audit_chain verifies clean across all kinds",
      v["ok"], f"rows={v['rows']} tampered={len(v['tampered'])}")

# --- replay round-trip for the first scheduler tick ---
latest = None
with _store.connect() as con:
    latest = con.execute(
        "SELECT id FROM tick_log WHERE kind='scheduler' AND is_shadow=0 "
        "ORDER BY id LIMIT 1"
    ).fetchone()
rp = intel_replay.replay(latest["id"])
check("replay returns the scheduler decisions",
      "totals" in rp["decisions"]
      and rp["decisions"]["totals"]["accounts_scheduled"] >= 1,
      "")

# --- weekly commitment + verify ---
import os
os.environ["PF_AUDIT_SIGNER_KEY"] = "c" * 64
commit = intel_chain.make_commitment()
vc = intel_chain.verify_commitment(commit["commitment_id"], "c" * 64)
check("weekly commitment verifies", vc["ok"], "")

# --- tamper -> verify fails ---
with _store.connect() as con:
    con.execute("UPDATE audit_chain SET record_json=? WHERE id=1",
                ('{"tampered":true}',))
v2 = intel_chain.verify_chain()
check("chain detects tampering after live edit",
      not v2["ok"] and len(v2["tampered"]) >= 1,
      f"tampered_from_id={v2['tampered'][0]['id']}")

print(f"\n--- {passed} PASS / {failed} FAIL ---")

try: shutil.rmtree(tmp)
except Exception: pass

sys.exit(0 if failed == 0 else 1)
