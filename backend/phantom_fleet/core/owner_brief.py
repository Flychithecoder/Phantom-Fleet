"""Owner Decision Brief — moonshot #9.

One endpoint, six signals, under 500ms. Composes every earlier moonshot
into a single "what needs your attention right now" response so the
owner never has to walk the dashboards manually.

Signals:
  1. pending_tool_proposals       — tool_exchange needs_approval queue
  2. stale_approvals              — Staffroom missions in needs_approval > 2h
  3. cost_anomalies               — workflows whose last-24h p95 > 2x 7d median
  4. contradictions_flagged       — mission_memory outcomes with contradiction=1
                                    in last 24h
  5. snapshot_pressure            — time-machine + ghost-preview retention warn
  6. recent_forks                 — last 5 time-machine forks

Every signal is wrapped in a try/except so one failing source does not
blank the whole brief. Each returns `{count, items, status}` where
status is "ok" | "no_data" | "error".
"""

from __future__ import annotations

import os
import statistics
import time
from pathlib import Path
from typing import Any


_STALE_HOURS = 2


def _s(status: str, items: list[Any] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status, "count": len(items or []), "items": items or []}
    out.update(extra)
    return out


def _signal_pending_tool_proposals() -> dict[str, Any]:
    try:
        from . import tool_exchange as tx
        res = tx.list_proposals(status="needs_approval", limit=20)
        return _s("ok", res["proposals"])
    except Exception as e:
        return _s("error", error=str(e)[:200])


def _signal_stale_approvals() -> dict[str, Any]:
    try:
        import sqlite3
        from .simulate import _staffroom_db_path
        cutoff_ms = int(time.time() * 1000) - (_STALE_HOURS * 3600_000)
        with sqlite3.connect(_staffroom_db_path()) as con:
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT id, bot_id, created_at, status FROM missions "
                    "WHERE status='needs_approval' AND created_at <= ? "
                    "ORDER BY created_at ASC LIMIT 20",
                    (cutoff_ms,),
                ).fetchall()
            except sqlite3.OperationalError:
                # staffroom schema may differ; probe fallback
                rows = []
        items = [dict(r) for r in rows]
        return _s("ok" if items else "no_data", items, cutoff_ms=cutoff_ms)
    except Exception as e:
        return _s("error", error=str(e)[:200])


def _signal_cost_anomalies() -> dict[str, Any]:
    try:
        from .ghost_preview import _read_audit_log, _runner_audit_path
        rows = _read_audit_log(_runner_audit_path())
        now = time.time()
        day_ago = now - 86400
        week_ago = now - 7 * 86400
        by_wf_day: dict[str, list[float]] = {}
        by_wf_week: dict[str, list[float]] = {}
        for r in rows:
            wf = r.get("workflow")
            cost = r.get("cost_usd")
            ts = r.get("ts") or r.get("time")
            if not wf or cost is None or ts is None:
                continue
            try:
                t = float(ts) if isinstance(ts, (int, float)) else time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, TypeError):
                continue
            if t >= day_ago:
                by_wf_day.setdefault(wf, []).append(float(cost))
            if t >= week_ago:
                by_wf_week.setdefault(wf, []).append(float(cost))
        anomalies = []
        for wf, day_costs in by_wf_day.items():
            week_costs = by_wf_week.get(wf, [])
            if len(day_costs) < 3 or len(week_costs) < 10:
                continue
            day_p95 = statistics.quantiles(day_costs, n=20)[-1] if len(day_costs) >= 20 else max(day_costs)
            week_med = statistics.median(week_costs)
            if week_med > 0 and day_p95 >= 2 * week_med:
                anomalies.append({
                    "workflow": wf,
                    "day_p95_usd": round(day_p95, 4),
                    "week_median_usd": round(week_med, 4),
                    "ratio": round(day_p95 / week_med, 2),
                    "day_samples": len(day_costs),
                    "week_samples": len(week_costs),
                })
        anomalies.sort(key=lambda a: a["ratio"], reverse=True)
        return _s("ok" if anomalies else "no_data", anomalies[:10])
    except Exception as e:
        return _s("error", error=str(e)[:200])


def _signal_contradictions_flagged() -> dict[str, Any]:
    try:
        import sqlite3
        from .simulate import _staffroom_db_path
        cutoff_ms = int(time.time() * 1000) - 86400_000
        with sqlite3.connect(_staffroom_db_path()) as con:
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT mission_id, bot_id, outcome, created_at "
                    "FROM mission_memory "
                    "WHERE contradiction=1 AND created_at >= ? "
                    "ORDER BY created_at DESC LIMIT 10",
                    (cutoff_ms,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        items = [dict(r) for r in rows]
        return _s("ok" if items else "no_data", items)
    except Exception as e:
        return _s("error", error=str(e)[:200])


def _signal_snapshot_pressure() -> dict[str, Any]:
    try:
        warnings = []
        try:
            from .ghost_preview import _snapshot_gc
            gc = _snapshot_gc()
            if gc.get("warn"):
                warnings.append({"source": "ghost-preview", "warn": gc["warn"], "retained_mb": gc.get("retained_mb")})
        except Exception as e:
            warnings.append({"source": "ghost-preview", "error": str(e)[:200]})
        try:
            from . import time_machine as tm
            p = tm.prune_snapshots()
            if p.get("warn"):
                warnings.append({"source": "time-machine", "warn": p["warn"], "retained_mb": p.get("retained_mb")})
        except Exception as e:
            warnings.append({"source": "time-machine", "error": str(e)[:200]})
        return _s("ok" if warnings else "no_data", warnings)
    except Exception as e:
        return _s("error", error=str(e)[:200])


def _signal_recent_forks() -> dict[str, Any]:
    try:
        from . import time_machine as tm
        res = tm.list_forks()
        items = res["forks"][:5]
        return _s("ok" if items else "no_data", items)
    except Exception as e:
        return _s("error", error=str(e)[:200])


def _signal_pending_target_approvals() -> dict[str, Any]:
    try:
        from . import targets_admission as ta
        rows = ta.list_pending_targets(limit=20)
        return _s("ok" if rows else "no_data", rows)
    except Exception as e:
        return _s("error", error=str(e)[:200])


def _signal_pending_comment_approvals() -> dict[str, Any]:
    try:
        from . import targets_admission as ta
        rows = ta.list_pending_comments(limit=20)
        return _s("ok" if rows else "no_data", rows)
    except Exception as e:
        return _s("error", error=str(e)[:200])


_SIGNAL_RUNNERS = [
    ("pending_tool_proposals", _signal_pending_tool_proposals),
    ("stale_approvals", _signal_stale_approvals),
    ("cost_anomalies", _signal_cost_anomalies),
    ("contradictions_flagged", _signal_contradictions_flagged),
    ("snapshot_pressure", _signal_snapshot_pressure),
    ("recent_forks", _signal_recent_forks),
    ("pending_target_approvals", _signal_pending_target_approvals),
    ("pending_comment_approvals", _signal_pending_comment_approvals),
]


def owner_brief() -> dict[str, Any]:
    """Build the full owner brief in under 500ms. One failing signal
    does not blank the rest (each is wrapped in try/except at source)."""
    t0 = time.monotonic()
    signals: dict[str, Any] = {}
    needs_attention = 0
    # recent_forks is informational; it does not raise the attention count.
    _INFO_ONLY = {"recent_forks"}
    for name, fn in _SIGNAL_RUNNERS:
        sig = fn()
        signals[name] = sig
        if sig["status"] == "ok" and sig["count"] > 0 and name not in _INFO_ONLY:
            needs_attention += sig["count"]
    duration_ms = int((time.monotonic() - t0) * 1000)
    # One-line human summary for an owner glancing at the top of the card.
    headline_parts = []
    if signals["pending_tool_proposals"]["count"]:
        headline_parts.append(f"{signals['pending_tool_proposals']['count']} tool proposal(s)")
    if signals["stale_approvals"]["count"]:
        headline_parts.append(f"{signals['stale_approvals']['count']} stale approval(s)")
    if signals["cost_anomalies"]["count"]:
        headline_parts.append(f"{signals['cost_anomalies']['count']} cost anomaly(ies)")
    if signals["contradictions_flagged"]["count"]:
        headline_parts.append(f"{signals['contradictions_flagged']['count']} contradiction(s)")
    if signals["snapshot_pressure"]["count"]:
        headline_parts.append("snapshot pressure")
    if signals["pending_target_approvals"]["count"]:
        headline_parts.append(f"{signals['pending_target_approvals']['count']} target(s) to approve")
    if signals["pending_comment_approvals"]["count"]:
        headline_parts.append(f"{signals['pending_comment_approvals']['count']} comment(s) to approve")
    headline = "; ".join(headline_parts) if headline_parts else "all quiet"
    return {
        "headline": headline,
        "needs_attention_total": needs_attention,
        "signals": signals,
        "duration_ms": duration_ms,
        "generated_unix_ms": int(time.time() * 1000),
    }
