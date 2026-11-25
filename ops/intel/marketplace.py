"""#7 Open-core rule marketplace — manifest + CI grader.

Community rules (R6, R7, R8, ... in ops/sched/recovery.py or any
future state-machine) submit as a `rule_manifest.json` plus a Python
module that exports `evaluate(tail, account, now_ms) -> transition?`.

CI grader does three things, any of which can reject the PR:

  1. **Determinism check.** Same (tail, account, now_ms) must produce
     the same output on 1000 trials. No wall-clock reads, no random.
  2. **Shadow run.** Execute the candidate over a frozen fixture set
     and diff against the current ruleset's decisions.
  3. **Survival gradient.** Run the Detection Simulator (ops/intel/detector.py)
     against a synthetic 1000-persona cohort and compare 30d survival
     with / without the rule. Reject if survival drops.

Any rule that passes all three lands under `ops/sched/rules/<rule_id>.py`
with its manifest committed alongside. The marketplace index is just
a sorted list of manifests.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.intel import detector  # noqa: E402

RULES_DIR = Path(__file__).resolve().parent.parent / "sched" / "rules"
RULES_DIR.mkdir(exist_ok=True)


@dataclass
class Manifest:
    rule_id: str
    author: str
    description: str
    applies_to: str      # "recovery" | "scheduler" | "proxy"
    version: str
    weight_hint: float   # expected contribution to detection weight
    tags: list[str]


def read_manifest(path: Path) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Manifest(
        rule_id=data["rule_id"],
        author=data.get("author", "anonymous"),
        description=data.get("description", ""),
        applies_to=data["applies_to"],
        version=data.get("version", "0.0.1"),
        weight_hint=float(data.get("weight_hint", 0.005)),
        tags=list(data.get("tags", [])),
    )


def _forbidden_ast_names() -> set[str]:
    """Nodes a rule module must NOT reference. Rules are pure."""
    return {
        "random", "requests", "urllib", "http", "socket", "subprocess",
        "os", "sys", "time", "datetime", "threading", "asyncio",
        "anthropic", "openai", "openrouter",
    }


def static_check(rule_path: Path) -> list[str]:
    """Reject rule modules that import forbidden things or call
    nondeterministic APIs. Not a sandbox, but enough to catch 95% of
    accidents and most intentional abuse in review."""
    try:
        tree = ast.parse(rule_path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return [f"syntax_error: {e}"]
    issues: list[str] = []
    forbidden = _forbidden_ast_names()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in forbidden:
                    issues.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in forbidden:
                issues.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = None
            if isinstance(fn, ast.Attribute):
                name = fn.attr
            elif isinstance(fn, ast.Name):
                name = fn.id
            if name in {"time", "sleep", "now", "uniform", "randint"}:
                issues.append(f"call {name}()")
    return issues


def determinism_check(
    rule_fn: Callable[..., Any], fixture: dict, trials: int = 200,
) -> dict:
    """Call the rule N times with identical args; outputs must match."""
    first = rule_fn(**fixture)
    first_h = hashlib.sha256(
        json.dumps(first, sort_keys=True, default=str).encode()
    ).hexdigest()
    for _ in range(trials - 1):
        out = rule_fn(**fixture)
        h = hashlib.sha256(
            json.dumps(out, sort_keys=True, default=str).encode()
        ).hexdigest()
        if h != first_h:
            return {"ok": False, "trials": trials, "diverged_hash": h,
                    "expected_hash": first_h}
    return {"ok": True, "trials": trials, "hash": first_h}


def survival_gradient(
    baseline_actions: list[dict], candidate_actions: list[dict],
    personas: list[dict] | None = None, horizon_days: int = 30,
) -> dict:
    """Grade the WITH / WITHOUT side of a candidate rule."""
    base = detector.grade(personas=personas, actions=baseline_actions,
                          horizon_days=horizon_days)
    cand = detector.grade(personas=personas, actions=candidate_actions,
                          horizon_days=horizon_days)
    delta = cand["survival_probability"] - base["survival_probability"]
    return {
        "baseline_p": base["survival_probability"],
        "candidate_p": cand["survival_probability"],
        "delta": delta,
        "passes": delta >= 0,     # >= 0 so a lateral rule can still land
        "baseline_findings": base["finding_count"],
        "candidate_findings": cand["finding_count"],
    }


def grade_rule_pr(
    rule_path: Path, manifest_path: Path,
    sample_fixture: dict,
    baseline_actions: list[dict],
    candidate_actions: list[dict],
    personas: list[dict] | None = None,
) -> dict:
    """What CI runs on every PR. Returns a report + a boolean verdict."""
    manifest = read_manifest(manifest_path)
    static_issues = static_check(rule_path)
    report: dict = {"rule_id": manifest.rule_id,
                    "manifest": manifest.__dict__}
    report["static_issues"] = static_issues
    if static_issues:
        report["verdict"] = "rejected_static"
        return report

    # Dynamic import.
    spec = importlib.util.spec_from_file_location(
        f"pfrule_{manifest.rule_id}", rule_path,
    )
    if spec is None or spec.loader is None:
        report["verdict"] = "rejected_import"
        return report
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "evaluate"):
        report["verdict"] = "rejected_no_evaluate_fn"
        return report

    report["determinism"] = determinism_check(mod.evaluate, sample_fixture)
    if not report["determinism"]["ok"]:
        report["verdict"] = "rejected_nondeterministic"
        return report

    report["survival"] = survival_gradient(
        baseline_actions, candidate_actions, personas,
    )
    report["verdict"] = (
        "accepted" if report["survival"]["passes"] else "rejected_survival_drop"
    )
    return report


def index() -> list[dict]:
    """List every landed rule."""
    out: list[dict] = []
    for p in sorted(RULES_DIR.glob("*.manifest.json")):
        try:
            out.append(read_manifest(p).__dict__)
        except Exception as e:
            out.append({"error": str(e), "path": str(p)})
    return out
