"""
Cluster health monitor routes.

Endpoints:
    GET  /api/cluster/health              — latest health report
    POST /api/cluster/health/run          — trigger fresh audit
    GET  /api/cluster/alerts              — all active (unresolved) alerts
    POST /api/cluster/alerts/{id}/resolve — mark alert resolved
    GET  /api/cluster/alerts/history      — alert history (last 30 days)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core.cluster_monitor import ClusterHealthMonitor, ClusterHealthReport, ClusterAlert

log = logging.getLogger("phantom_fleet.api.cluster_monitor")

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory alert store
# Keyed by alert_id. In production back this with a DB table.
# ---------------------------------------------------------------------------

_LATEST_REPORT: Optional[ClusterHealthReport] = None
_ALERT_STORE: dict[str, ClusterAlert] = {}   # alert_id → ClusterAlert


def _latest_report() -> Optional[ClusterHealthReport]:
    return _LATEST_REPORT


def _alert_store() -> dict[str, ClusterAlert]:
    return _ALERT_STORE


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ClusterAlertOut(BaseModel):
    alert_id: str
    severity: str
    dimension: str
    finding: str
    affected_count: int
    affected_pct: float
    recommendation: str
    detected_at_iso: str
    resolved: bool


class ClusterHealthReportOut(BaseModel):
    generated_at_iso: str
    accounts_audited: int
    alerts: list[ClusterAlertOut]
    critical_count: int
    warning_count: int
    overall_health: str
    next_audit_recommended_iso: str


class AlertListOut(BaseModel):
    alerts: list[ClusterAlertOut]
    total: int


class ResolveOut(BaseModel):
    alert_id: str
    resolved: bool
    resolved_at_iso: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alert_to_out(a: ClusterAlert) -> ClusterAlertOut:
    return ClusterAlertOut(
        alert_id=a.alert_id,
        severity=a.severity,
        dimension=a.dimension,
        finding=a.finding,
        affected_count=a.affected_count,
        affected_pct=a.affected_pct,
        recommendation=a.recommendation,
        detected_at_iso=a.detected_at_iso,
        resolved=a.resolved,
    )


def _report_to_out(r: ClusterHealthReport) -> ClusterHealthReportOut:
    return ClusterHealthReportOut(
        generated_at_iso=r.generated_at_iso,
        accounts_audited=r.accounts_audited,
        alerts=[_alert_to_out(a) for a in r.alerts],
        critical_count=r.critical_count,
        warning_count=r.warning_count,
        overall_health=r.overall_health,
        next_audit_recommended_iso=r.next_audit_recommended_iso,
    )


def _load_accounts_for_audit(request: Request) -> list[dict]:
    """
    Load account data for the cluster audit from the app context.

    In production this would query the DB for all active accounts plus their
    today-aggregates (story views, reactions, posts, comments, hashtags, etc.).
    Here we fall back to the in-memory account store from the accounts route
    when no account_repo is available on app.state.ctx.
    """
    ctx = getattr(request.app.state, "ctx", None)
    if ctx and hasattr(ctx, "account_repo"):
        # Production path: caller should have loaded accounts synchronously
        # or via a background task.  For now we return empty and let the caller
        # decide (the POST /health/run endpoint should pre-load them).
        return getattr(ctx, "_cluster_audit_accounts", [])

    # Fallback: use the in-memory store from the accounts route layer
    try:
        from .accounts import _store
        rows = list(_store().values())
        return rows
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health", response_model=ClusterHealthReportOut)
async def get_cluster_health() -> ClusterHealthReportOut:
    """
    Return the most recent cluster health report.

    If no audit has been run yet, returns a placeholder report indicating
    that an audit is needed.
    """
    report = _latest_report()
    if report is None:
        now_iso = datetime.now(timezone.utc).isoformat()
        placeholder = ClusterHealthReport(
            generated_at_iso=now_iso,
            accounts_audited=0,
            alerts=[],
            critical_count=0,
            warning_count=0,
            overall_health="healthy",
            next_audit_recommended_iso=now_iso,
        )
        return _report_to_out(placeholder)

    return _report_to_out(report)


@router.post("/health/run", response_model=ClusterHealthReportOut)
async def run_cluster_audit(request: Request) -> ClusterHealthReportOut:
    """
    Trigger a fresh cluster health audit against the live account fleet.

    Runs synchronously (pure Python, < 5s for 1,000 accounts).
    Persists the new report and merges alerts into the alert store.
    """
    global _LATEST_REPORT

    accounts = _load_accounts_for_audit(request)

    monitor = ClusterHealthMonitor()
    report = monitor.run_full_audit(accounts)

    _LATEST_REPORT = report

    # Merge new alerts into the store (dedupe by alert_id)
    store = _alert_store()
    for alert in report.alerts:
        store[alert.alert_id] = alert

    log.info(
        "Cluster audit complete: %d accounts, %d critical, %d warnings, health=%s",
        report.accounts_audited,
        report.critical_count,
        report.warning_count,
        report.overall_health,
    )

    return _report_to_out(report)


@router.get("/alerts", response_model=AlertListOut)
async def list_active_alerts() -> AlertListOut:
    """Return all active (unresolved) cluster alerts."""
    store = _alert_store()
    active = [a for a in store.values() if not a.resolved]
    return AlertListOut(
        alerts=[_alert_to_out(a) for a in active],
        total=len(active),
    )


@router.post("/alerts/{alert_id}/resolve", response_model=ResolveOut)
async def resolve_alert(alert_id: str) -> ResolveOut:
    """Mark a cluster alert as resolved."""
    store = _alert_store()
    alert = store.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id!r} not found.")

    alert.resolved = True
    now_iso = datetime.now(timezone.utc).isoformat()

    log.info("Alert %s resolved at %s", alert_id, now_iso)

    return ResolveOut(
        alert_id=alert_id,
        resolved=True,
        resolved_at_iso=now_iso,
    )


@router.get("/alerts/history", response_model=AlertListOut)
async def alert_history(days: int = 30) -> AlertListOut:
    """
    Return all alerts (both active and resolved) from the last N days.

    Defaults to 30 days.  In production this would query a time-series DB table.
    Here we return everything in the in-memory store that falls within the window.
    """
    store = _alert_store()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    historical: list[ClusterAlert] = []
    for a in store.values():
        try:
            dt = datetime.fromisoformat(a.detected_at_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                historical.append(a)
        except (ValueError, TypeError):
            historical.append(a)  # include if we can't parse the timestamp

    return AlertListOut(
        alerts=[_alert_to_out(a) for a in historical],
        total=len(historical),
    )
