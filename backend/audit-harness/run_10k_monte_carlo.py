"""10K-persona Monte Carlo audit gate.

CLAUDE.md requires that this harness pass before any PR merges. It:

1. Generates 10,000 personas via `persona_cohort.generate_cohort`.
2. Runs `validate_cohort` across the whole batch.
3. Enforces the 4 CLAUDE.md fleet-scale invariants:
     - Every persona passes its own per-field pair-check.
     - App-signature salts are unique across the cohort (Onimator bug #2).
     - account_count is not fleet-wide static (bug #3).
     - Diurnal peak hours are not fleet-wide uniform (bug #4).

Exit code 0 only when every check passes. On any violation, prints a
compact diagnostic and exits non-zero so CI fails.

Run locally:

    python -m backend.audit_harness.run_10k_monte_carlo

Or via CI (see `.github/workflows/audit.yml`).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backend.phantom_fleet.core.persona_cohort import generate_cohort
from backend.phantom_fleet.core.persona_cohort_validators import validate_cohort


def _cli() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10_000,
                    help="cohort size (default 10000, max 10000)")
    ap.add_argument("--json", action="store_true",
                    help="emit full report as JSON instead of human output")
    return ap.parse_args()


def main() -> int:
    args = _cli()
    t0 = time.perf_counter()
    cohort = generate_cohort(args.n)
    gen_ms = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    report = validate_cohort(cohort["personas"])
    audit_ms = int((time.perf_counter() - t1) * 1000)

    full = {
        "n": args.n,
        "ok": bool(report["ok"]),
        "gen_ms": gen_ms,
        "audit_ms": audit_ms,
        **report,
        "generator_meta": {
            "entropy_source": cohort["entropy_source"],
            "unique_salts": cohort["unique_app_signature_salts"],
        },
    }

    if args.json:
        print(json.dumps(full, indent=2))
    else:
        print(f"10K Monte Carlo audit — n={args.n}")
        print(f"  generate: {gen_ms} ms")
        print(f"  audit:    {audit_ms} ms")
        print(f"  personas_with_violations: {report['personas_with_violations']}")
        print(f"  cohort_findings: {len(report['cohort_findings'])}")
        for f in report["cohort_findings"]:
            print(f"    - {f['code']}: {f['detail']}")
        if report["sample_violations"]:
            print(f"  sample persona violations:")
            for v in report["sample_violations"]:
                print(f"    - {v['persona_id']}: "
                      f"{[x['code'] for x in v['violations']]}")
        print(f"  verdict: {'PASS' if full['ok'] else 'FAIL'}")

    return 0 if full["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
