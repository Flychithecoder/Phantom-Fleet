"""End-to-end smoke across all 7 intel capabilities."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(r"C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone")
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="pf-intel-smoke-"))
store = tmp / "persona-store.sqlite"

from ops.sched import _store  # noqa: E402
_store.STORE = store

from ops.intel import detector, replay, clone, chain, swarm, marketplace  # noqa: E402

NOW = int(time.time() * 1000)
passed = failed = 0


def check(name, cond, info=""):
    global passed, failed
    tag = "PASS" if cond else "FAIL"
    if cond: passed += 1
    else:    failed += 1
    print(f"  [{tag}] {name:62s} {info}")


# ---- #3 Detector ----
print("--- #3 Detector ---")
clean_cohort = [{
    "username": f"u{i}", "locale": "en-US", "timezone": "America/New_York",
    "country": "US", "mcc": "310",
    "device_model": "SM_G770F", "android_version": 12,
    "app_signature_salt": f"{i:032x}",
    "account_count": 3 + (i % 20),
    "diurnal_peak_hour_local": 10 + (i % 10),
} for i in range(100)]
clean = detector.grade(personas=clean_cohort)
check("clean cohort ~1.0 survival over 30d",
      clean["survival_probability"] > 0.95,
      f"P={clean['survival_probability']:.4f}")

# Inject one Onimator bug at a time, confirm gradient.
onimator_cohort = [{**p, "locale": "en-GB"} for p in clean_cohort]
dirty1 = detector.grade(personas=onimator_cohort)
check("locale/tz injection drops survival",
      dirty1["survival_probability"] < clean["survival_probability"],
      f"P={dirty1['survival_probability']:.4f}")

# Cohort-level F2 cert collision
onimator2 = [{**p, "app_signature_salt": "shared"} for p in clean_cohort]
dirty2 = detector.grade(personas=onimator2)
check("shared cert collision drops survival",
      dirty2["survival_probability"] < clean["survival_probability"],
      f"P={dirty2['survival_probability']:.4f}")

# Schedule-level checks
actions = [{"account": "u0", "kind": "like", "ts_ms": NOW + i * 10_000,
            "tap_offset_ms": 42, "dwell_ms": 100}
           for i in range(30)]
sched_grade = detector.grade(actions=actions)
check("schedule with same tap offset flags F5",
      "F5_tap_jitter_floor" in sched_grade["by_rule"],
      f"rules={list(sched_grade['by_rule'])}")

# Rules catalogue
check("detector has 14 rules in catalogue",
      len(detector.rules_catalogue()) == 14, "")


# ---- #1 Replay ----
print("--- #1 Replay engine ---")

def dummy_tick(inputs, seed, now_ms):
    return {"transitions": [{"account_id": 1, "to": "needs_reset"}],
            "n_inputs": len(inputs.get("accounts", []))}

# Seed the base schema so snapshot_inputs can query it.
_store.apply_migrations()
seed = replay.mint_seed()
check("mint_seed yields 32 hex chars", len(seed) == 32, "")

# Log a tick, then replay it with the same fn.
tick_id = replay.log_tick(
    "recovery", NOW, seed, "v0",
    inputs={"accounts": []},
    decisions=dummy_tick({"accounts": []}, seed, NOW),
    duration_ms=1,
)
check("tick_log row persists", tick_id > 0, f"id={tick_id}")
r = replay.replay(tick_id)
check("replay returns the stored decisions",
      r["decisions"]["transitions"][0]["account_id"] == 1, "")
v = replay.verify(tick_id, dummy_tick)
check("verify finds a deterministic match", v["match"], "")

# Shadow: a different fn produces a different decision.
def shadow_fn(inputs, seed, now_ms):
    return {"transitions": [{"account_id": 2, "to": "dead"}]}
shadow_id = replay.shadow_run("recovery", shadow_fn, "candidate")
diff = replay.compare(tick_id, shadow_id)
check("shadow compare shows a divergence",
      diff["only_live_sample"] and diff["only_shadow_sample"], "")


# ---- #2 Behavioral clone (MLE fit against synthetic input) ----
print("--- #2 Behavioral clone (MLE) ---")
# Build a synthetic 30-day action timeline with 4 personas.
synthetic = {}
base_ms = NOW - 30 * 86400 * 1000
for acct, (daily_rate, peak_h) in [
    ("tatiana_001", (12, 14)),
    ("tatiana_002", (8, 15)),
    ("melodie_001", (18, 20)),
    ("melodie_002", (14, 21)),
]:
    ts_list = []
    for day in range(30):
        for _ in range(daily_rate):
            # Jitter around the peak hour.
            h = peak_h + int(((hash((acct, day)) % 300) - 150) / 60)
            ms = base_ms + day * 86400_000 + (h % 24) * 3600_000 + \
                 (hash((acct, day, _)) % 3600_000)
            ts_list.append(ms)
    synthetic[acct] = sorted(ts_list)

fits = [clone.fit_account(a, ts) for a, ts in synthetic.items()]
fits = [f for f in fits if f]
check("MLE fits all 4 synthetic accounts", len(fits) == 4,
      f"n={len(fits)}")
summary_fits = clone.summary(fits)
check("fit summary has peak hour spread > 0",
      summary_fits["peak_hour_spread"] > 0,
      f"spread={summary_fits['peak_hour_spread']}h")


# ---- #5 Merkle audit chain ----
print("--- #5 Merkle audit chain ---")
first = chain.append("recovery", {"transition": "t1", "account": 1})
second = chain.append("recovery", {"transition": "t2", "account": 2})
check("first head is non-genesis",
      first["head"] != "0" * 64 and len(first["head"]) == 64, "")
check("second head chains off the first",
      second["head"] != first["head"], "")
v = chain.verify_chain()
check("verify_chain passes on a fresh chain",
      v["ok"] and v["rows"] == 2, f"rows={v['rows']}")

key_hex = "a" * 64
os.environ["PF_AUDIT_SIGNER_KEY"] = key_hex
commit = chain.make_commitment()
verify_c = chain.verify_commitment(commit["commitment_id"], key_hex)
check("commitment verifies with the signing key",
      verify_c["ok"], f"ok={verify_c['ok']}")
wrong = chain.verify_commitment(commit["commitment_id"], "b" * 64)
check("commitment REJECTS a wrong key", not wrong["ok"], "")

# Tamper: edit a row and re-verify.
with _store.connect() as con:
    con.execute("UPDATE audit_chain SET record_json=? WHERE id=1",
                ('{"transition":"TAMPERED"}',))
v2 = chain.verify_chain()
check("verify_chain DETECTS tampering",
      not v2["ok"] and len(v2["tampered"]) >= 1,
      f"tampered={len(v2['tampered'])}")


# ---- #4 Swarm primitive ----
print("--- #4 Swarm primitive ---")
accts = [{"username": f"swarm_{i}", "tz_offset_hours": -5} for i in range(50)]
slots = swarm.trending_view("story://x", accts, window_s=90)
s = swarm.summary(slots)
check("trending_view produces 50 slots within window",
      s["n"] == 50 and s["span_ms"] <= 90_000 * 2, f"span={s['span_ms']}ms")

edges = swarm.community_graph(200, m=3)
g = swarm.summary(edges)
expected_edges = 3 + (200 - 3) * 3  # m-clique + m new edges per added node
check("community_graph produces non-trivial power-law shape",
      g["edges"] == expected_edges
      and g["max_in_degree"] > g["min_in_degree"] * 3,
      f"edges={g['edges']} max_in={g['max_in_degree']} min_in={g['min_in_degree']}")

sync = swarm.synchrony_offsets(accts, "like", persona_local_ms=NOW)
sy = swarm.summary(sync)
check("synchrony_offsets gives >95% unique tap offsets",
      sy["unique_tap_offsets"] >= int(0.95 * len(sync)),
      f"unique={sy['unique_tap_offsets']}/{len(sync)}")


# ---- #7 Marketplace ----
print("--- #7 Rule marketplace ---")
# Write a candidate rule + manifest in a temp dir.
rule_file = tmp / "r6_example.py"
rule_file.write_text(
    "def evaluate(tail, account, now_ms):\n"
    "    # Reject any account whose tail begins with 10x 'login_required'.\n"
    "    if sum(1 for r in tail[:10] if r.get('outcome') == 'login_required') >= 10:\n"
    "        return {'status': 'needs_reset', 'reason': 'r6_strong_lockout'}\n"
    "    return None\n",
    encoding="utf-8",
)
manifest_file = tmp / "r6_example.manifest.json"
manifest_file.write_text(
    '{"rule_id": "r6_example", "author": "test", "applies_to": "recovery",'
    ' "description": "stricter login lockout", "version": "0.1.0",'
    ' "weight_hint": 0.003, "tags": ["login", "stricter"]}',
    encoding="utf-8",
)
fixture = {
    "tail": [{"outcome": "login_required"}] * 10,
    "account": {"id": 1},
    "now_ms": NOW,
}
baseline_a = []
candidate_a = []
report = marketplace.grade_rule_pr(
    rule_file, manifest_file, fixture,
    baseline_actions=baseline_a, candidate_actions=candidate_a,
    personas=clean_cohort,
)
check("marketplace static check clears a pure rule",
      report["static_issues"] == [], f"issues={report['static_issues']}")
check("determinism check passes 200 trials",
      report["determinism"]["ok"], "")
check("grader accepts a lateral rule",
      report["verdict"] in ("accepted",), f"verdict={report['verdict']}")

# A rule that imports `random` must be rejected static.
bad_rule = tmp / "r_bad.py"
bad_rule.write_text("import random\n\ndef evaluate(**kw): return random.random()\n")
bad_manifest = tmp / "r_bad.manifest.json"
bad_manifest.write_text(
    '{"rule_id":"r_bad","author":"a","applies_to":"recovery",'
    '"description":"","version":"0","weight_hint":0.001,"tags":[]}',
    encoding="utf-8",
)
bad_report = marketplace.grade_rule_pr(
    bad_rule, bad_manifest, {"tail": [], "account": {}, "now_ms": 0},
    [], [], clean_cohort,
)
check("marketplace rejects rule that imports random",
      bad_report["verdict"] == "rejected_static",
      f"verdict={bad_report['verdict']}")


print(f"\n--- {passed} PASS / {failed} FAIL ---")

try: shutil.rmtree(tmp)
except Exception: pass

sys.exit(0 if failed == 0 else 1)
