"""Reality-anchored simulate() — moonshot #5.

Exposes the 10K-persona Monte Carlo audit and the Causal Fleet Memory
outcome log as a runtime surface so a worker can ask, before it does
anything, what has historically happened for similar briefs — and what
the current fleet shape says about doing it now.

Two primitives:

- `simulate_fleet_shape(n=10000)` — wraps AuditHarnessAgent's
  `simulate_and_check()`. Returns the cluster metrics (device-model
  share, locale/timezone cross-field integrity, biometric spread). This
  is the live ground-truth answer to "is the fleet right now shaped
  like a realistic user base?"

- `simulate_action_sequence(brief, limit=5, cohort_hint=None)` — queries
  Staffroom's mission_memory for the top-K most similar prior missions,
  reads their stored outcome / owner_decision / contradiction state,
  and returns an outcome distribution. This is the reality-anchor: not
  a Monte Carlo over hypothetical personas but a lookup over what
  actually happened the last time the fleet tried something like this.

The two primitives compose: a worker calls action_sequence to get the
historical outcome-rate, then calls fleet_shape to confirm the
current persona distribution isn't itself drifting toward one of the
documented cluster bugs (CLAUDE.md §Known fleet bugs #1–#4). Together
they give a quantitative answer where before the model would have
guessed.

Both functions are side-effect-free and run in-process — no ADB, no
device touch, no billing. They read persona distributions and the
Staffroom mission_memory SQLite table.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..agents.audit_harness_agent import AuditHarnessAgent, HarnessResult


def _staffroom_db_path() -> Path:
    """Resolve the Staffroom sqlite that holds mission_memory.

    Env override: STAFFROOM_DB_PATH. Default: ../_staffroom/.data/staffroom.sqlite
    relative to the Fleet checkout.
    """
    env = os.environ.get("STAFFROOM_DB_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3].parent / "_staffroom" / ".data" / "staffroom.sqlite"


# ───────── Primitive 1: fleet shape ─────────────────────────────────────

def simulate_fleet_shape(n: int = 10_000) -> dict[str, Any]:
    """Run the audit harness over n synthetic personas.

    Honors the same clamps as the CI gate: n is bounded to [1000, 10000]
    so a worker can run a cheaper check for interactive calls while the
    hourly production sweep stays at the full 10K.
    """
    n = max(1000, min(int(n), 10_000))
    agent = AuditHarnessAgent()
    # Override N_SYNTHETIC_PERSONAS for this call only, without mutating
    # the class-level constant the CI runner depends on.
    original_n = agent.N_SYNTHETIC_PERSONAS
    try:
        type(agent).N_SYNTHETIC_PERSONAS = n
        t0 = time.monotonic()
        result: HarnessResult = agent.simulate_and_check()
        duration_ms = int((time.monotonic() - t0) * 1000)
    finally:
        type(agent).N_SYNTHETIC_PERSONAS = original_n
    return {
        "passed": result.passed,
        "total_personas": result.total_personas,
        "failures": result.failures,
        "warnings": result.warnings,
        "metrics": result.metrics,
        "duration_ms": duration_ms,
    }


# ───────── Primitive 2: action-sequence reality anchor ─────────────────

@dataclass
class HistoricalMatch:
    mission_id: str
    workflow: str | None
    role: str | None
    outcome: str
    owner_decision: str | None
    vendor: str | None
    team: str | None
    created_at: str
    excerpt_head: str


def _token_overlap(query: str, document: str) -> float:
    """Coverage-biased overlap — what fraction of the query tokens
    appear in the document. Asymmetric because briefs are long multi-KB
    prompts while queries are short phrases; symmetric Jaccard would
    always score near-zero against the huge union. Falls back to a
    minimum 0 for empty inputs.
    """
    if not query or not document:
        return 0.0
    tq = {t for t in query.lower().split() if len(t) >= 3}
    td = {t for t in document.lower().split() if len(t) >= 3}
    if not tq or not td:
        return 0.0
    return len(tq & td) / len(tq)


def simulate_action_sequence(
    brief: str,
    limit: int = 5,
    cohort_hint: str | None = None,
) -> dict[str, Any]:
    """Query mission_memory for the K most similar prior missions and
    return their aggregate outcome distribution.

    `cohort_hint` filters by workflow or role when the worker knows
    which subsystem it is simulating ("research_review", "coo_strategist").
    Omitting it uses the whole corpus.

    Confidence is capped by sample size: fewer than 5 matches → "low",
    5-15 → "medium", >15 → "high". The worker should treat anything
    below "medium" as "no prior art, operate from first principles".

    Vendor/team breakdown lets the caller see whether historical
    performance was uniform across teams or whether one team
    outperformed. Since Causal Fleet Memory now tags vendor on every
    row, this surfaces the A/B signal without a separate dashboard.
    """
    db_path = _staffroom_db_path()
    if not db_path.exists():
        return {
            "error": f"staffroom.sqlite not found at {db_path}",
            "matches": [],
            "outcome_distribution": {},
            "owner_decision_rate": None,
            "confidence": "none",
        }
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        q = """SELECT mission_id, workflow, role, outcome, owner_decision,
                      vendor, team, created_at, deliverable_excerpt, brief
                 FROM mission_memory
                WHERE excluded_from_recall = 0"""
        params: list[Any] = []
        if cohort_hint:
            q += " AND (workflow = ? OR role = ?)"
            params.extend([cohort_hint, cohort_hint])
        q += " ORDER BY created_at DESC LIMIT 200"
        rows = con.execute(q, params).fetchall()

    scored: list[tuple[float, sqlite3.Row]] = []
    for r in rows:
        s = _token_overlap(brief, (r["brief"] or "") + " " + (r["deliverable_excerpt"] or ""))
        if s >= 0.15:
            scored.append((s, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[: max(1, min(limit, 20))]

    outcome_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    by_vendor: dict[str, dict[str, int]] = {}
    matches: list[dict[str, Any]] = []
    for score, r in top:
        outcome_counts[r["outcome"]] = outcome_counts.get(r["outcome"], 0) + 1
        if r["owner_decision"]:
            decision_counts[r["owner_decision"]] = decision_counts.get(r["owner_decision"], 0) + 1
        v = r["vendor"] or "unknown"
        by_vendor.setdefault(v, {})
        by_vendor[v][r["outcome"]] = by_vendor[v].get(r["outcome"], 0) + 1
        matches.append({
            **asdict(HistoricalMatch(
                mission_id=r["mission_id"],
                workflow=r["workflow"],
                role=r["role"],
                outcome=r["outcome"],
                owner_decision=r["owner_decision"],
                vendor=r["vendor"],
                team=r["team"],
                created_at=r["created_at"],
                excerpt_head=(r["deliverable_excerpt"] or "")[:200],
            )),
            "similarity": round(score, 3),
        })

    total = sum(outcome_counts.values())
    outcome_rate = {k: v / total for k, v in outcome_counts.items()} if total else {}
    approve_rate: float | None = None
    if decision_counts:
        total_decisions = sum(decision_counts.values())
        approve_rate = decision_counts.get("approved", 0) / total_decisions
    confidence = "high" if total > 15 else ("medium" if total >= 5 else ("low" if total else "none"))

    return {
        "brief_head": brief[:200],
        "cohort_hint": cohort_hint,
        "matches": matches,
        "outcome_counts": outcome_counts,
        "outcome_distribution": outcome_rate,
        "owner_decision_rate": approve_rate,
        "by_vendor": by_vendor,
        "confidence": confidence,
        "sample_size": total,
    }


# Async wrappers so FastAPI routes can offload the simulate_fleet_shape
# CPU work to a thread. simulate_action_sequence is IO-bound (one SQLite
# query) and fast enough to run on the loop.
async def simulate_fleet_shape_async(n: int = 10_000) -> dict[str, Any]:
    return await asyncio.to_thread(simulate_fleet_shape, n)
