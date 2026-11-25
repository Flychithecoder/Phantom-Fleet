"""Ghost preview — moonshot #2 (shadow-execution dry runs).

v1 (static) — ships now.
  Produces an owner-facing preview card for a pending-approval mission
  WITHOUT spawning a real claude subprocess. Uses four cheap signals:
    1. SQLite snapshot of staffroom.sqlite (baseline for conflict diff)
    2. Prompt static analysis (regex scan for staffroom_* tool refs,
       assignment count, workflow extraction)
    3. Historical cost + outcome from Causal Fleet Memory (mission_memory)
    4. Artifact conflict scan — names the brief references, cross-checked
       against the live artifacts table

v2 (live fork) — future.
  Same contract but `run_live=True` would spawn a real claude subprocess
  pointed at an MCP server whose tools are gated to read from the
  snapshot DB only. Token cost per preview = ~$0.10 but accuracy is
  perfect. The v1 output shape already includes a `method:"static"` tag
  so a v2 fork can set `method:"live_fork"` and the UI code is forward-
  compatible.

The preview is read-only: snapshotting uses SQLite's online .backup API,
no device touch, no mutation of mission_memory or artifacts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .simulate import simulate_action_sequence, _staffroom_db_path


# Runner audit log — source of truth for per-call cost + latency. Lives
# on the Fleet side at runner/logs/runner-audit.ndjson. Each line is a
# {event, pinned_model, bearer_tail, cost_usd, duration_ms, ...} record.
def _runner_audit_path() -> Path:
    env = os.environ.get("PF_RUNNER_AUDIT_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "runner" / "logs" / "runner-audit.ndjson"


def _bearer_to_vendor(bearer_tail: str) -> str:
    """Runner only logs the last 4 chars of the bearer. Map common suffixes
    to vendors. pf-opus → 'opus', pf-sonnet → 'onet', pf-glm-plan → 'plan',
    pf-glm-plan-max → '-max'. 'local' bearer logs as 'ocal'."""
    m = {
        "opus": ("anthropic", "claude-opus-4-7"),
        "onet": ("anthropic", "claude-sonnet-4-6"),
        "plan": ("zai", "glm-plan"),
        "-max": ("zai", "glm-plan-max"),
        "ocal": ("anthropic", "auto"),
    }
    return m.get(bearer_tail, ("unknown", "unknown"))[0]


def _read_audit_log(path: Path, limit_bytes: int = 2_000_000) -> list[dict]:
    """Stream the last ~2MB of the audit ndjson so a 100MB log stays
    cheap to parse. Lines must be valid JSON; malformed lines skipped."""
    if not path.exists():
        return []
    out: list[dict] = []
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > limit_bytes:
            f.seek(size - limit_bytes)
            f.readline()  # discard partial first line
        for raw in f:
            try:
                row = json.loads(raw)
                if isinstance(row, dict) and row.get("event") == "ok":
                    out.append(row)
            except Exception:  # noqa: BLE001
                continue
    return out


def _cost_latency_history(workflow: str | None) -> dict[str, Any]:
    """Aggregate historical cost + latency per workflow from the runner
    audit log. Groups by vendor so the preview can say "Claude: $0.11
    median / 38s; GLM-plan: $0.00 flat / 42s median"."""
    rows = _read_audit_log(_runner_audit_path())
    if not rows:
        return {"sample_size": 0, "note": "runner audit log empty or missing"}
    # We can't tie an audit row back to a specific workflow without a
    # join key; the audit log doesn't carry the Fleet request_id. What
    # it DOES carry is prompt_hash. For v1.5 we aggregate ACROSS all
    # calls as a conservative upper bound; v2 will plumb the request_id
    # through as an audit field for precise workflow attribution.
    by_vendor: dict[str, list[dict]] = {}
    for r in rows:
        v = _bearer_to_vendor(r.get("bearer_tail", ""))
        by_vendor.setdefault(v, []).append(r)
    result: dict[str, Any] = {"sample_size": len(rows), "by_vendor": {}}
    total_costs: list[float] = []
    for vendor, calls in by_vendor.items():
        costs = [float(c.get("cost_usd") or 0) for c in calls]
        durs = [int(c.get("duration_ms") or 0) for c in calls]
        if not costs:
            continue
        total_costs.extend(costs)
        result["by_vendor"][vendor] = {
            "calls": len(calls),
            "median_cost_usd": round(statistics.median(costs), 4),
            "mean_cost_usd": round(statistics.mean(costs), 4),
            "p95_cost_usd": round(_p95(costs), 4),
            "median_duration_ms": int(statistics.median(durs)) if durs else None,
            "p95_duration_ms": int(_p95(durs)) if durs else None,
        }
    # Overall projection — the preview shows one headline number.
    if total_costs:
        result["projected_cost_usd_median"] = round(statistics.median(total_costs), 4)
        result["projected_cost_usd_p95"] = round(_p95(total_costs), 4)
    return result


def _p95(xs: list[float] | list[int]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = max(0, min(len(s) - 1, int(0.95 * len(s))))
    return s[idx]


# Regex catalogue — mirrors the allow-list in runner/src/mcp.mjs.
# A brief that references a tool outside this set would be blocked at
# spawn time anyway, so we only count what will actually be callable.
_TOOL_PATTERN = re.compile(
    r"\bstaffroom_(?:workspace|list_projects|get_project|list_bots|"
    r"list_chats|read_chat|list_pending_decisions|get_run|read_artifact|"
    r"recall_similar|recall_contradictions|recall_lineage|"
    r"list_computers|discover_tools|tool_details|tool_status|propose_work)"
    r"|\bphantom_fleet_simulate_(?:shape|actions)\b"
)

# "Assignment: <text>" or "- assignment N:" shape produced by COO plan.
_ASSIGNMENT_PATTERN = re.compile(r"(?mi)^\s*(?:-\s*)?assignment(?:\s+\w+)?\s*:")

# Workflow tag the Fleet always embeds: [fleet request_id=pf-<workflow>-<hash>]
_WORKFLOW_PATTERN = re.compile(r"pf-([a-z_]+)-[a-f0-9]+")

# Artifact-ID shape: "artifact `<uuid-ish>`" or bare uuid when brief cites
# prior deliverables. 32-hex or uuid-4 with dashes.
_ARTIFACT_REF_PATTERN = re.compile(
    r"\b([0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12})\b",
    re.I,
)


@dataclass
class ArtifactConflict:
    name: str
    live_count: int
    last_updated: str | None
    note: str


def _snapshot_path(mission_id: str) -> Path:
    """Where this preview's snapshot lands. One file per mission; later
    runs overwrite so we keep snapshot disk bounded."""
    base = Path(os.environ.get(
        "GHOST_PREVIEW_SNAPSHOT_DIR",
        str(Path(__file__).resolve().parents[2] / ".data" / "ghost-snapshots"),
    ))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"ghost-{mission_id}.sqlite"


def _take_snapshot(src: Path, dst: Path) -> dict[str, Any]:
    """Online-backup the Staffroom sqlite to a side file. Uses SQLite's
    .backup API so a concurrent writer never sees inconsistent state."""
    if not src.exists():
        return {"ok": False, "error": f"source not found: {src}"}
    t0 = time.monotonic()
    try:
        with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
            source.backup(target)
        size_kb = dst.stat().st_size // 1024
        return {
            "ok": True,
            "path": str(dst),
            "size_kb": size_kb,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except sqlite3.Error as err:
        return {"ok": False, "error": str(err)}


def _scan_prompt(prompt: str) -> dict[str, Any]:
    """Static analysis — what will the mission probably do?"""
    hits = _TOOL_PATTERN.findall(prompt)
    by_tool = Counter(hits)
    assignments = len(_ASSIGNMENT_PATTERN.findall(prompt))
    wf_match = _WORKFLOW_PATTERN.search(prompt)
    workflow = wf_match.group(1) if wf_match else None
    cited_artifacts = sorted(set(m.lower() for m in _ARTIFACT_REF_PATTERN.findall(prompt)))
    # Policy signals — surface anything owner would care about for approval.
    signals = []
    if re.search(r"\b(flash|factory[- ]reset|wipe)\b", prompt, re.I):
        signals.append("device_destructive_hint")
    if re.search(r"\bpurchase|checkout|charge|invoice|bill\b", prompt, re.I):
        signals.append("billing_hint")
    if re.search(r"\bpublish|post|dm\b", prompt, re.I):
        signals.append("external_publish_hint")
    return {
        "workflow": workflow,
        "distinct_tools_referenced": len(by_tool),
        "tool_calls_expected": len(hits),
        "tool_breakdown": dict(by_tool.most_common()),
        "assignments_hinted": assignments,
        "cited_artifact_ids": cited_artifacts,
        "policy_signals": signals,
    }


def _snapshot_gc(keep_last: int = 20) -> dict[str, Any]:
    """Keep only the N most recent snapshots so disk stays bounded.
    Runs lazily on each preview call; cheap because it just stat()s
    the ghost-snapshots directory."""
    base = Path(os.environ.get(
        "GHOST_PREVIEW_SNAPSHOT_DIR",
        str(Path(__file__).resolve().parents[2] / ".data" / "ghost-snapshots"),
    ))
    if not base.exists():
        return {"removed": 0, "kept": 0}
    files = sorted(base.glob("ghost-*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for old in files[keep_last:]:
        try: old.unlink(); removed += 1
        except OSError: pass
    return {"removed": removed, "kept": min(len(files), keep_last)}


def _historical_cost(workflow: str | None, snapshot_db: Path) -> dict[str, Any]:
    """Average cost/duration from Causal Fleet Memory for prior missions
    of the same workflow. Reads the snapshot (not live) so a long-running
    preview can't skew mid-flight by racing against a concurrent commit.
    """
    if not workflow or not snapshot_db.exists():
        return {"sample_size": 0}
    with sqlite3.connect(snapshot_db) as con:
        con.row_factory = sqlite3.Row
        # cost_usd and duration aren't stored in mission_memory today;
        # we use outcome counts as a proxy signal and leave cost as
        # "unknown" until a per-call cost column is added. This is
        # explicit so the owner card doesn't fabricate a dollar figure.
        rows = con.execute(
            """SELECT outcome, owner_decision, vendor
                 FROM mission_memory
                WHERE workflow = ? AND excluded_from_recall = 0
                ORDER BY created_at DESC LIMIT 50""",
            (workflow,),
        ).fetchall()
    if not rows:
        return {"sample_size": 0}
    completed = sum(1 for r in rows if r["outcome"] == "completed")
    failed = sum(1 for r in rows if r["outcome"] == "failed")
    approved = sum(1 for r in rows if r["owner_decision"] == "approved")
    declined = sum(1 for r in rows if r["owner_decision"] == "declined")
    return {
        "sample_size": len(rows),
        "completion_rate": round(completed / len(rows), 3),
        "failure_rate": round(failed / len(rows), 3),
        "approval_rate_when_decided": (
            round(approved / (approved + declined), 3) if (approved + declined) else None
        ),
        "note": (
            "Per-mission cost is not yet columnated on mission_memory; "
            "cost estimate will activate once the runner audit cost rolls "
            "into the memory row."
        ),
    }


def _scan_conflicts(cited_ids: list[str], snapshot_db: Path) -> list[ArtifactConflict]:
    """For each cited-artifact id in the brief, check the snapshot
    artifacts table to see if (a) it exists and (b) the brief would
    produce a conflicting write. v1 only reports on referenced ids; v2
    will add predicted-name collision detection from the COO plan."""
    if not cited_ids or not snapshot_db.exists():
        return []
    out: list[ArtifactConflict] = []
    with sqlite3.connect(snapshot_db) as con:
        con.row_factory = sqlite3.Row
        try:
            for aid in cited_ids:
                row = con.execute(
                    "SELECT COUNT(*) c FROM artifacts WHERE id = ? OR id LIKE ?",
                    (aid, f"{aid}%"),
                ).fetchone()
                if row and row["c"]:
                    out.append(ArtifactConflict(
                        name=aid,
                        live_count=row["c"],
                        last_updated=None,
                        note="brief references a live artifact; a write of the same id would overwrite it",
                    ))
        except sqlite3.OperationalError:
            # artifacts table may not exist on a fresh snapshot
            return []
    return out


def preview_mission(mission_id: str, prompt: str) -> dict[str, Any]:
    """Build a ghost preview card for a pending-approval mission.

    Returns a dict the owner UI renders directly:
        {
          method: "static",
          snapshot: {ok, path, size_kb, duration_ms},
          plan: {workflow, assignments_hinted, tool_calls_expected, ...},
          history: {sample_size, completion_rate, ...},
          outcome_prediction: <simulate_action_sequence output>,
          conflicts: [...],
          generated_at: ISO8601,
        }
    """
    t0 = time.monotonic()
    live_db = _staffroom_db_path()
    snapshot_file = _snapshot_path(mission_id)
    snap = _take_snapshot(live_db, snapshot_file)
    gc_stats = _snapshot_gc()
    plan = _scan_prompt(prompt)
    history = _historical_cost(plan["workflow"], snapshot_file if snap["ok"] else live_db)
    cost_latency = _cost_latency_history(plan["workflow"])
    # Compose with simulate #5 — reality-anchored outcome prediction.
    outcome = simulate_action_sequence(brief=prompt, limit=5, cohort_hint=plan["workflow"])
    conflicts = _scan_conflicts(
        plan["cited_artifact_ids"],
        snapshot_file if snap["ok"] else live_db,
    )
    return {
        "method": "static",
        "mission_id": mission_id,
        "snapshot": snap,
        "snapshot_gc": gc_stats,
        "plan": plan,
        "history": history,
        "cost_latency": cost_latency,
        "outcome_prediction": {
            "sample_size": outcome["sample_size"],
            "confidence": outcome["confidence"],
            "outcome_distribution": outcome["outcome_distribution"],
            "owner_decision_rate": outcome["owner_decision_rate"],
            "by_vendor": outcome["by_vendor"],
            "top_matches": outcome["matches"][:3],
        },
        "conflicts": [
            {"name": c.name, "live_count": c.live_count,
             "last_updated": c.last_updated, "note": c.note}
            for c in conflicts
        ],
        "total_duration_ms": int((time.monotonic() - t0) * 1000),
        "upgrade_path": (
            "v2 will spawn a real claude subprocess against the snapshot "
            "MCP server for exact tool-call counts and dollar cost; v1 "
            "uses prompt scan + historical memory to avoid token spend."
        ),
    }
