"""Cost/Quality router — moonshot #4.

Given (workflow, role), recommend a team (claude|glm) grounded in real
history: Laplace-smoothed success rate from mission_memory, median
cost per call from the runner audit log, and the two availability
gates (GLM plan token present; COO sensitivity gate).

The router NEVER dispatches. It returns a recommendation with the
factors that drove it, so the owner (or an agent writing a mission)
can see why and override.
"""

from __future__ import annotations

import os
import sqlite3
import statistics
import time
from pathlib import Path
from typing import Any, Optional

from .simulate import _staffroom_db_path
from .ghost_preview import _read_audit_log, _runner_audit_path, _bearer_to_vendor


_LAPLACE_ALPHA = 2  # smoothing so a team with zero runs isn't zeroed
_SENSITIVE_ROLES = {"coo", "coo_strategist"}


def _glm_available() -> dict[str, Any]:
    plan = bool(os.environ.get("PF_ZAI_PLAN_TOKEN"))
    api = bool(os.environ.get("PF_ZAI_API_KEY"))
    return {
        "available": plan or api,
        "has_plan_token": plan,
        "has_api_key": api,
    }


def _sensitivity_block(role: Optional[str]) -> dict[str, Any]:
    if not role:
        return {"blocked": False, "reason": None}
    if role.lower() in _SENSITIVE_ROLES and os.environ.get("PF_ROUTER_ALLOW_ZAI_SENSITIVE") != "1":
        return {
            "blocked": True,
            "reason": f"role '{role}' is sensitivity-gated for zai; "
                      f"set PF_ROUTER_ALLOW_ZAI_SENSITIVE=1 to override",
        }
    return {"blocked": False, "reason": None}


def _success_rate(workflow: str, team: str) -> dict[str, Any]:
    """Laplace-smoothed success rate for (workflow, team) from
    mission_memory. `outcome` values treated as success: {'approved',
    'posted', 'ok', 'success'}; failures: {'rejected', 'blocked',
    'failed', 'error'}; anything else ignored."""
    success_set = {"approved", "posted", "ok", "success"}
    fail_set = {"rejected", "blocked", "failed", "error"}
    try:
        with sqlite3.connect(_staffroom_db_path()) as con:
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT outcome FROM mission_memory "
                    "WHERE team=? AND workflow=?",
                    (team, workflow),
                ).fetchall()
            except sqlite3.OperationalError:
                # mission_memory may not have workflow/team columns yet
                rows = []
    except (sqlite3.OperationalError, FileNotFoundError):
        rows = []
    succ = sum(1 for r in rows if (r["outcome"] or "").lower() in success_set)
    fail = sum(1 for r in rows if (r["outcome"] or "").lower() in fail_set)
    n = succ + fail
    rate = (succ + _LAPLACE_ALPHA) / (n + 2 * _LAPLACE_ALPHA) if (n + 2 * _LAPLACE_ALPHA) else 0.5
    return {
        "rate": round(rate, 4),
        "successes": succ,
        "failures": fail,
        "samples": n,
    }


def _median_cost(workflow: str, team: str) -> dict[str, Any]:
    """Median cost_usd per call for (workflow, team-vendor) from runner
    audit. Returns null median if < 3 samples (noisy)."""
    vendor_wanted = "anthropic" if team == "claude" else "zai"
    try:
        rows = _read_audit_log(_runner_audit_path())
    except Exception:
        rows = []
    costs: list[float] = []
    for r in rows:
        if r.get("event") != "ok":
            continue
        if r.get("workflow") != workflow:
            continue
        bt = r.get("bearer_tail") or ""
        vendor, _ = _bearer_to_vendor(bt)
        if vendor != vendor_wanted:
            continue
        c = r.get("cost_usd")
        if c is None:
            continue
        try:
            costs.append(float(c))
        except (TypeError, ValueError):
            continue
    median = statistics.median(costs) if len(costs) >= 3 else None
    return {
        "median_usd": round(median, 5) if median is not None else None,
        "samples": len(costs),
    }


def _score(success_rate: float, median_cost: Optional[float]) -> float:
    """value-per-dollar heuristic. Missing cost treated as a fixed
    0.005 placeholder so cold-start teams aren't infinitely scored."""
    c = median_cost if median_cost is not None else 0.005
    return success_rate / max(c, 0.0001)


def recommend_team(workflow: str, role: Optional[str] = None) -> dict[str, Any]:
    """Return {recommended_team, reasoning, teams: {claude: {...}, glm: {...}}}.
    The recommendation accounts for availability + sensitivity gates;
    claude is the safe default when nothing else gives signal."""
    t0 = time.monotonic()
    if not workflow or not isinstance(workflow, str):
        raise ValueError("workflow required")
    if len(workflow) > 80:
        raise ValueError("workflow must be <=80 chars")

    glm_avail = _glm_available()
    sens = _sensitivity_block(role)

    teams = {}
    for team in ("claude", "glm"):
        sr = _success_rate(workflow, team)
        mc = _median_cost(workflow, team)
        teams[team] = {
            "success_rate": sr,
            "cost": mc,
            "score": round(_score(sr["rate"], mc["median_usd"]), 4),
        }

    # Pick, honoring gates. claude is the default if nothing decides.
    reasoning: list[dict[str, Any]] = []
    glm_eligible = glm_avail["available"] and not sens["blocked"]
    if not glm_avail["available"]:
        reasoning.append({
            "factor": "glm_availability",
            "value": "unavailable",
            "weight": "exclude_glm",
        })
    if sens["blocked"]:
        reasoning.append({
            "factor": "sensitivity_gate",
            "value": sens["reason"],
            "weight": "exclude_glm",
        })

    if not glm_eligible:
        pick = "claude"
        reasoning.append({
            "factor": "fallback_default",
            "value": "glm not eligible; defaulting to claude",
            "weight": "decisive",
        })
    else:
        c_score = teams["claude"]["score"]
        g_score = teams["glm"]["score"]
        c_samples = teams["claude"]["success_rate"]["samples"]
        g_samples = teams["glm"]["success_rate"]["samples"]
        # If one team has >=5 samples and the other has <3, favor the
        # better-attested one even if its score is slightly lower.
        if c_samples >= 5 and g_samples < 3:
            pick = "claude"
            reasoning.append({"factor": "sample_attestation",
                              "value": f"claude has {c_samples} samples, glm has {g_samples}",
                              "weight": "decisive"})
        elif g_samples >= 5 and c_samples < 3:
            pick = "glm"
            reasoning.append({"factor": "sample_attestation",
                              "value": f"glm has {g_samples} samples, claude has {c_samples}",
                              "weight": "decisive"})
        elif g_score > c_score:
            pick = "glm"
            reasoning.append({"factor": "value_per_dollar",
                              "value": f"glm score {g_score} > claude {c_score}",
                              "weight": "decisive"})
        elif c_score > g_score:
            pick = "claude"
            reasoning.append({"factor": "value_per_dollar",
                              "value": f"claude score {c_score} > glm {g_score}",
                              "weight": "decisive"})
        else:
            pick = "claude"
            reasoning.append({"factor": "tie_default",
                              "value": "scores equal; default claude",
                              "weight": "decisive"})

    duration_ms = int((time.monotonic() - t0) * 1000)
    return {
        "recommended_team": pick,
        "role": role,
        "workflow": workflow,
        "glm_availability": glm_avail,
        "sensitivity_gate": sens,
        "teams": teams,
        "reasoning": reasoning,
        "duration_ms": duration_ms,
    }
