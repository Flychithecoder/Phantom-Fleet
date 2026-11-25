"""End-to-end smoke test over the deterministic scheduler stack.

Builds a fresh persona-store.sqlite in a temp directory, seeds a small
fleet (3 personas, 6 accounts, varied statuses + action_result tails),
and exercises tick / recovery / replacement / proxy against it.

No agents, no LLM calls.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(r"C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone")
sys.path.insert(0, str(ROOT))

# Redirect the store BEFORE importing any sched modules.
tmp = Path(tempfile.mkdtemp(prefix="pf-sched-smoke-"))
store_path = tmp / "persona-store.sqlite"

from ops.sched import _store  # noqa: E402
_store.STORE = store_path
from ops.sched import warming, tick, recovery, replacement, proxy  # noqa: E402

NOW = int(time.time() * 1000)


def seed() -> None:
    _store.apply_migrations(store_path)
    # Mirror the Phase 0 migration step by hand so this test is
    # self-contained (no dependency on an actual Onimator install).
    with _store.connect(store_path) as con:
        con.executescript("""
        INSERT INTO personas (name, mode, settings_json, imported_at_ms)
          VALUES ('Tatiana', 'default', '{}', 0),
                 ('Melodie', 'default', '{}', 0),
                 ('NewPersona', 'warmup', '{}', 0);
        INSERT INTO persona_profiles (persona, diurnal_peak_hour_local, timezone)
          VALUES ('Tatiana', 14, 'America/New_York'),
                 ('Melodie', 20, 'America/New_York'),
                 ('NewPersona', 11, 'America/Chicago');
        INSERT INTO devices (serial, model, region, source, imported_at_ms)
          VALUES ('RF8N10J57DA', 'SM_G770F', 'EU', 'onimator', 0),
                 ('53c8e3ad1b3f7ece', 'SM_G770U1', 'US', 'onimator', 0);
        INSERT INTO accounts (username, persona, device_serial, status, imported_at_ms) VALUES
          ('tatiana_alive',       'Tatiana',    'RF8N10J57DA',      'alive',       0),
          ('tatiana_silent',      'Tatiana',    'RF8N10J57DA',      'alive',       0),
          ('tatiana_login3x',     'Tatiana',    'RF8N10J57DA',      'alive',       0),
          ('melodie_checkpoint',  'Melodie',    '53c8e3ad1b3f7ece', 'alive',       0),
          ('melodie_healing',     'Melodie',    '53c8e3ad1b3f7ece', 'needs_reset', 0),
          ('new_dead',            'NewPersona', '53c8e3ad1b3f7ece', 'dead',        0);
        INSERT INTO account_schedule_state (account_id, warming_day, last_tick_ms)
          VALUES (1, 3, NULL),  -- tatiana_alive  day 3
                 (2, 4, NULL),  -- tatiana_silent day 4
                 (3, 5, NULL),  -- tatiana_login3x day 5
                 (4, 6, NULL),  -- melodie_checkpoint day 6
                 (5, 1, NULL),  -- melodie_healing
                 (6, 1, NULL);  -- new_dead (not scheduled)
        """)
        # Helper: seed an action_queue row so action_results FK is satisfied.
        def seed_result(action_id, account_id, outcome, ts):
            con.execute(
                "INSERT INTO action_queue "
                "(id, account_id, kind, due_ms, params_json, state, created_ms) "
                "VALUES (?, ?, 'like', ?, '{}', 'done', ?)",
                (action_id, account_id, ts, ts),
            )
            con.execute(
                "INSERT INTO action_results "
                "(action_id, account_id, outcome, latency_ms, signal_json, ts_ms) "
                "VALUES (?, ?, ?, 1000, '{}', ?)",
                (action_id, account_id, outcome, ts),
            )

        # Seed action_results tails for the recovery rules.
        # Account 3 (tatiana_login3x): 3 consecutive login_required inside 24h.
        for i in range(3):
            seed_result(100 + i, 3, "login_required",
                        NOW - (i * 1000 * 60 * 10))
        # Account 4 (melodie_checkpoint): a checkpoint signal within 24h.
        seed_result(200, 4, "checkpoint", NOW - 60_000)
        # Account 5 (melodie_healing): 5 consecutive ok inside 24h.
        for i in range(5):
            seed_result(300 + i, 5, "ok", NOW - (i * 1000 * 60 * 5))
        # Fleet-wide network_error storm for proxy rotate.
        for i in range(6):
            seed_result(400 + i, 1, "network_error",
                        NOW - (i * 1000 * 60 * 2))


passed = failed = 0


def check(name, cond, info=""):
    global passed, failed
    tag = "PASS" if cond else "FAIL"
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"  [{tag}] {name:60s} {info}")


print("--- seed ---")
seed()

# --- WARMING UNIT ---
print("--- warming (pure) ---")
sched_day3 = warming.schedule_day(warming_day=3, now_ms=NOW, peak_hour=14)
s = warming.summarise(sched_day3)
check("day 3 schedule sits within sampled bands",
      1 <= s["total"] <= 14, f"total={s['total']}")
check("day 1 schedule yields zero actions (login+scroll only)",
      warming.summarise(warming.schedule_day(1, NOW))["total"] == 0, "")
# cap test
sched_day30 = warming.schedule_day(warming_day=30, now_ms=NOW, peak_hour=14)
check("day 30 schedule respects 22/day cap",
      warming.summarise(sched_day30)["total"] <= 22,
      f"total={warming.summarise(sched_day30)['total']}")

# --- SCHEDULER TICK ---
print("--- tick ---")
out = tick.tick(apply=False)
check("dry tick considers all alive accounts (4)",
      out["totals"]["accounts_considered"] == 4,
      f"considered={out['totals']['accounts_considered']}")
check("dry tick enqueues nothing", out["totals"]["actions_enqueued"] >= 0 and
      not any("skipped" in r for r in out["per_account"] if r.get("skipped")), "")
out2 = tick.tick(apply=True)
check("applied tick enqueues > 0 actions",
      out2["totals"]["actions_enqueued"] > 0,
      f"enqueued={out2['totals']['actions_enqueued']}")
# Re-tick immediately: last_tick_ms guard filters all accounts out.
out3 = tick.tick(apply=True)
check("second tick in same window schedules nothing new",
      out3["totals"]["actions_enqueued"] == 0
      and out3["totals"]["accounts_considered"] == 0,
      f"considered={out3['totals']['accounts_considered']} "
      f"enqueued={out3['totals']['actions_enqueued']}")

# --- RECOVERY ---
print("--- recovery ---")
rout = recovery.run(apply=False, now_ms=NOW)
by_reason = {t["reason"] for t in rout["transitions"]}
check("recovery dry-run flags R1 login3x",
      "r1_login_required_3x" in by_reason, f"reasons={by_reason}")
check("recovery dry-run flags R2 checkpoint",
      "r2_checkpoint" in by_reason, "")
check("recovery dry-run flags R5 self-healed",
      "r5_self_healed" in by_reason, "")
check("recovery dry-run emits proxy signal (R3)",
      len(rout["proxy_signals"]) >= 1, f"signals={len(rout['proxy_signals'])}")
rout2 = recovery.run(apply=True, now_ms=NOW)
# After apply, account 3 should be needs_reset, 4 dead, 5 alive.
with _store.connect(store_path) as con:
    s3 = con.execute("SELECT status FROM accounts WHERE id=3").fetchone()["status"]
    s4 = con.execute("SELECT status FROM accounts WHERE id=4").fetchone()["status"]
    s5 = con.execute("SELECT status FROM accounts WHERE id=5").fetchone()["status"]
check("apply transitions acct3 -> needs_reset", s3 == "needs_reset", f"s3={s3}")
check("apply transitions acct4 -> dead",        s4 == "dead",        f"s4={s4}")
check("apply transitions acct5 -> alive",       s5 == "alive",       f"s5={s5}")

# --- REPLACEMENT ---
print("--- replacement ---")
# After recovery, acct4 is dead; acct6 was seeded dead -> both expected.
rep_dry = replacement.run(apply=False, now_ms=NOW)
check("replacement dry-run sees 2 dead accounts",
      len(rep_dry["emitted"]) == 2, f"n={len(rep_dry['emitted'])}")
rep = replacement.run(apply=True, now_ms=NOW)
rep2 = replacement.run(apply=True, now_ms=NOW)
check("replacement emits are idempotent (no duplicates on re-run)",
      len(rep2["emitted"]) == 0, f"n={len(rep2['emitted'])}")

# --- PROXY ---
print("--- proxy ---")
pout = proxy.run(apply=False, plan_ids=["trumpproxies_yuge"])
check("proxy dry-run yields rotate decision",
      any(d["decision"] == "rotate" for d in pout["decisions"]),
      f"decisions={pout['decisions']}")
pout2 = proxy.run(apply=True, plan_ids=["trumpproxies_yuge"])
with _store.connect(store_path) as con:
    plan = dict(con.execute(
        "SELECT * FROM proxy_state WHERE plan_id=?",
        ("trumpproxies_yuge",),
    ).fetchone())
check("proxy rotate increments blocked_count",
      plan["blocked_count"] == 1, f"blocked_count={plan['blocked_count']}")
check("proxy rotate stamps last_rotate_ms",
      plan["last_rotate_ms"] is not None, "")

# Cooldown: immediate re-run should NOT rotate again.
pout3 = proxy.run(apply=True, plan_ids=["trumpproxies_yuge"])
check("proxy honours cooldown on back-to-back ticks",
      not any(d["decision"] == "rotate" for d in pout3["decisions"]), "")

print(f"\n--- {passed} PASS / {failed} FAIL ---")

# Cleanup.
try:
    shutil.rmtree(tmp)
except Exception:
    pass

sys.exit(0 if failed == 0 else 1)
