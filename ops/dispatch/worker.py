"""Queue dispatcher worker.

Reads ops/sched/'s action_queue, calls the companion APK's engagement
endpoints over HTTP, records outcomes into action_results. Atomic
claim prevents double dispatch under parallel workers.

Deterministic at the dispatcher level; outcomes come from real phone
state so they aren't bit-reproducible, but every decision this module
makes (which row to claim, which endpoint to hit, how to classify the
response) is a pure function logged via ops/sched/_telemetry.

Usage (cron, once per minute):
    python -m ops.dispatch.worker --once --max 25

    # Single-serial smoke
    python -m ops.dispatch.worker --once --max 1 --only RF8N10J57DA

    # Dry-run: classify what it WOULD dispatch, no HTTP calls.
    python -m ops.dispatch.worker --dry-run --max 25

No LLM calls.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.sched import _store  # noqa: E402
from ops.sched._telemetry import instrument  # noqa: E402
from ops.dispatch import _endpoints, _outcome, _transport  # noqa: E402

DEFAULT_CLONE_PACKAGE = "com.instagram.android"
DEFAULT_PORT = 8080
PER_DEVICE_COOLDOWN_MS = 150  # minimum gap between actions on the same phone


def _resolve_clone(row: dict) -> str:
    return row.get("clone_package") or DEFAULT_CLONE_PACKAGE


def dispatch_one(con, row: dict, apply: bool, now_ms: int) -> dict:
    """Pure-function dispatch decision for one claimed row.

    Returns a result dict the worker loop records. On `apply=False`
    nothing is posted and nothing is persisted — the caller must
    release_claim() the row.
    """
    action_id = row["id"]
    kind = row["kind"]
    params = json.loads(row.get("params_json") or "{}")
    clone = _resolve_clone(row)
    endpoint = _endpoints.spec_for_kind(kind)
    if endpoint is None:
        return {"action_id": action_id, "outcome": "unknown",
                "signal": {"reason": "no_endpoint", "kind": kind},
                "latency_ms": 0, "dispatched": False}

    payload, missing = _endpoints.build_payload(endpoint, clone, params)
    if payload is None:
        return {"action_id": action_id, "outcome": "missing_target",
                "signal": {"missing": missing},
                "latency_ms": 0, "dispatched": False}

    ip_port = _transport.resolve_device(con, row["device_serial"])
    if ip_port is None:
        return {"action_id": action_id, "outcome": "network_error",
                "signal": {"reason": "no_endpoint_for_serial",
                           "serial": row["device_serial"]},
                "latency_ms": 0, "dispatched": False}
    ip, port = ip_port
    url = f"http://{ip}:{port}{endpoint.path}"

    if not apply:
        return {"action_id": action_id, "outcome": "ok",
                "signal": {"would_dispatch": True, "url": url,
                           "payload": payload},
                "latency_ms": 0, "dispatched": False}

    t0 = time.monotonic()
    status, body, err = _transport.do_request(
        endpoint.method, url,
        _endpoints.dumps(payload) if endpoint.method != "GET" else None,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    outcome, signal = _outcome.classify(status, body, err)
    return {
        "action_id": action_id, "outcome": outcome,
        "signal": {**signal, "status": status, "endpoint": endpoint.path},
        "latency_ms": latency_ms, "dispatched": True,
    }


def run(
    apply: bool, max_actions: int = 25, only_serial: str | None = None,
    now_ms: int | None = None,
) -> dict:
    now_ms = now_ms if now_ms is not None else _store.now_ms()
    _store.apply_migrations()
    results: list[dict] = []
    last_dispatch_ms: dict[str, int] = {}
    totals = {"claimed": 0, "dispatched": 0, "skipped_cooldown": 0,
              "ok": 0, "err": 0}

    with instrument("dispatch", apply=apply) as rec:
        rec["now_ms"] = now_ms
        with _store.connect() as con:
            # Snapshot inputs for the replay/chain record.
            rec["inputs"] = {
                "due_count": int(con.execute(
                    "SELECT COUNT(*) FROM action_queue "
                    "WHERE state='due' AND due_ms <= ?", (now_ms,),
                ).fetchone()[0]),
                "alive_accounts": int(con.execute(
                    "SELECT COUNT(*) FROM accounts WHERE status='alive'",
                ).fetchone()[0]),
            }
            claimed = _transport.claim(con, max_actions, now_ms)
            totals["claimed"] = len(claimed)

            for row in claimed:
                if only_serial and row["device_serial"] != only_serial:
                    _transport.release_claim(con, row["id"])
                    continue
                # Per-device cooldown: never pound the same phone.
                last = last_dispatch_ms.get(row["device_serial"], 0)
                if now_ms - last < PER_DEVICE_COOLDOWN_MS:
                    _transport.release_claim(con, row["id"])
                    totals["skipped_cooldown"] += 1
                    continue
                result = dispatch_one(con, row, apply=apply, now_ms=now_ms)
                results.append({**row, **result})
                last_dispatch_ms[row["device_serial"]] = _store.now_ms()
                if apply and result["dispatched"]:
                    _store.record_result(
                        con, row["id"], row["account_id"],
                        result["outcome"], result["latency_ms"],
                        result["signal"],
                    )
                    totals["dispatched"] += 1
                    if result["outcome"] == "ok":
                        totals["ok"] += 1
                    else:
                        totals["err"] += 1
                elif apply and result["outcome"] in (
                    "missing_target", "unknown",
                ):
                    # Permanent failures that never reached HTTP: mark
                    # them terminally so they don't re-enter the queue.
                    _store.record_result(
                        con, row["id"], row["account_id"],
                        result["outcome"], 0, result["signal"],
                    )
                    totals["err"] += 1
                else:
                    _transport.release_claim(con, row["id"])

            rec["decisions"] = {
                "totals": totals,
                "results": [
                    {"action_id": r["action_id"], "kind": r["kind"],
                     "outcome": r["outcome"], "latency_ms": r["latency_ms"]}
                    for r in results
                ],
            }

    return {"now_ms": now_ms, "apply": apply, "totals": totals,
            "results": results,
            "tick_id": rec.get("tick_id"),
            "chain_head": rec.get("chain_head")}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=25)
    ap.add_argument("--only", help="limit to one device serial")
    ap.add_argument("--now-ms", type=int)
    ap.add_argument("--once", action="store_true",
                    help="exit after one pass (cron mode; default)")
    args = ap.parse_args()

    out = run(apply=args.apply, max_actions=args.max, only_serial=args.only,
              now_ms=args.now_ms)
    t = out["totals"]
    print(f"dispatch @ {out['now_ms']}  apply={out['apply']}")
    print(f"  claimed   : {t['claimed']}")
    print(f"  dispatched: {t['dispatched']}")
    print(f"  ok        : {t['ok']}")
    print(f"  err       : {t['err']}")
    print(f"  skipped   : {t['skipped_cooldown']} (per-device cooldown)")
    for r in out["results"][:15]:
        print(f"    #{r['action_id']:<5} {r['kind']:<8} "
              f"serial={r['device_serial'][:12]:<12} "
              f"-> {r['outcome']:<22} ({r['latency_ms']}ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
