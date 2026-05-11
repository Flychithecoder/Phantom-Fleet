"""
Ops dashboard routes — real-time autonomous operations control plane.

Endpoints:
    GET  /api/ops/status              — current ops brain status
    GET  /api/ops/cycle/latest        — latest cycle report
    GET  /api/ops/cycle/history       — last 24 cycle reports
    POST /api/ops/pause               — pause all operations
    POST /api/ops/resume              — resume operations
    POST /api/ops/cycle/trigger       — manually trigger a cycle now
    GET  /api/ops/schedule/today      — today's fleet schedule
    GET  /api/ops/alerts/live         — SSE stream of real-time alerts
    WebSocket /ws/ops                 — real-time ops feed
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, date
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("phantom_fleet.api.ops")

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class OpsStatusOut(BaseModel):
    status: str                  # "running" | "paused" | "error" | "stopped"
    cycle_count: int
    consecutive_failures: int
    rule_based_mode: bool
    last_cycle_iso: str | None
    next_cycle_in_sec: float | None


class CycleReportOut(BaseModel):
    cycle_id: str
    started_at_iso: str
    completed_at_iso: str
    duration_sec: float
    phones_online: int
    accounts_active: int
    accounts_dead_this_cycle: int
    accounts_replaced_this_cycle: int
    platform_cycles_completed: dict[str, bool]
    alerts_fired: int
    llm_cost_usd: float
    status: str
    errors: list[str]


class PauseResumeOut(BaseModel):
    ok: bool
    status: str
    message: str


class TriggerCycleOut(BaseModel):
    ok: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_brain(request: Request) -> Any:
    """Pull the OpsBrain from app.state, or raise 503 if not booted."""
    brain = getattr(request.app.state, "brain", None)
    if brain is None:
        raise HTTPException(
            status_code=503,
            detail="OpsBrain not initialised — server may still be booting",
        )
    return brain


def _get_scheduler(request: Request) -> Any:
    """Pull FleetScheduler from app.state, or None."""
    return getattr(request.app.state, "scheduler", None)


def _report_to_out(report: Any) -> CycleReportOut:
    return CycleReportOut(
        cycle_id=report.cycle_id,
        started_at_iso=report.started_at_iso,
        completed_at_iso=report.completed_at_iso,
        duration_sec=report.duration_sec,
        phones_online=report.phones_online,
        accounts_active=report.accounts_active,
        accounts_dead_this_cycle=report.accounts_dead_this_cycle,
        accounts_replaced_this_cycle=report.accounts_replaced_this_cycle,
        platform_cycles_completed=report.platform_cycles_completed,
        alerts_fired=report.alerts_fired,
        llm_cost_usd=report.llm_cost_usd,
        status=report.status,
        errors=report.errors,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status", response_model=OpsStatusOut)
async def ops_status(request: Request) -> OpsStatusOut:
    """Current ops brain status."""
    brain = _get_brain(request)
    report = brain.latest_report()
    return OpsStatusOut(
        status=brain.status(),
        cycle_count=brain._cycle_count,
        consecutive_failures=brain._consecutive_failures,
        rule_based_mode=brain.is_rule_based_mode(),
        last_cycle_iso=report.completed_at_iso if report else None,
        next_cycle_in_sec=None,  # populated by client via countdown
    )


@router.get("/cycle/latest", response_model=CycleReportOut | None)
async def ops_cycle_latest(request: Request) -> CycleReportOut | None:
    """Latest completed cycle report."""
    brain  = _get_brain(request)
    report = brain.latest_report()
    if report is None:
        return None
    return _report_to_out(report)


@router.get("/cycle/history", response_model=list[CycleReportOut])
async def ops_cycle_history(request: Request) -> list[CycleReportOut]:
    """Last 24 cycle reports (most recent first)."""
    brain = _get_brain(request)
    return [_report_to_out(r) for r in reversed(brain.cycle_history())]


@router.post("/pause", response_model=PauseResumeOut)
async def ops_pause(request: Request) -> PauseResumeOut:
    """Emergency stop — pause all ops cycles. Health checks continue."""
    brain = _get_brain(request)
    if brain._paused:
        return PauseResumeOut(ok=True, status="paused", message="Already paused")
    brain.pause()
    return PauseResumeOut(ok=True, status="paused", message="Fleet operations paused")


@router.post("/resume", response_model=PauseResumeOut)
async def ops_resume(request: Request) -> PauseResumeOut:
    """Resume operations after a pause."""
    brain = _get_brain(request)
    if not brain._paused:
        return PauseResumeOut(ok=True, status="running", message="Already running")
    brain.resume()
    return PauseResumeOut(ok=True, status="running", message="Fleet operations resumed")


@router.post("/cycle/trigger", response_model=TriggerCycleOut)
async def ops_cycle_trigger(request: Request) -> TriggerCycleOut:
    """Manually trigger an ops cycle immediately (runs in background)."""
    brain = _get_brain(request)
    if brain._paused:
        raise HTTPException(status_code=409, detail="Brain is paused — resume first")
    asyncio.create_task(brain._run_ops_cycle())
    return TriggerCycleOut(ok=True, message="Cycle triggered — results available at /cycle/latest")


@router.get("/schedule/today")
async def ops_schedule_today(request: Request) -> dict:
    """Today's fleet schedule."""
    scheduler = _get_scheduler(request)
    if scheduler is None:
        return {"date_iso": date.today().isoformat(), "actions": [], "note": "Scheduler not initialised"}

    schedule = scheduler.current_schedule()
    if schedule is None:
        return {"date_iso": date.today().isoformat(), "actions": [], "note": "No schedule built yet"}

    pending_count = await scheduler.get_pending_count()
    return {
        "date_iso":      schedule.date_iso,
        "built_at":      schedule.built_at,
        "total_actions": len(schedule.actions),
        "pending":       pending_count,
        "completed":     len(schedule.actions) - pending_count,
        "actions":       [
            {
                "action_id":         a.action_id,
                "account_id":        a.account_id,
                "platform":          a.platform,
                "action_type":       a.action_type,
                "scheduled_at_iso":  a.scheduled_at_iso,
                "priority":          a.priority,
                "phone_serial":      a.phone_serial,
            }
            for a in sorted(schedule.actions, key=lambda x: x.scheduled_at_unix)[:200]
        ],
    }


@router.get("/alerts/live")
async def ops_alerts_live(request: Request) -> StreamingResponse:
    """
    SSE stream of real-time alerts from the ops brain.

    Clients connect and receive alerts as they are published.
    Falls back to polling brain._active_alerts if Redis is unavailable.
    """
    brain = _get_brain(request)

    async def event_generator() -> AsyncGenerator[str, None]:
        last_alert_count = -1
        try:
            while True:
                if await request.is_disconnected():
                    break

                alerts = brain.active_alerts()
                if len(alerts) != last_alert_count:
                    last_alert_count = len(alerts)
                    payload = json.dumps({"alerts": alerts, "ts_iso": _now_iso()})
                    yield f"data: {payload}\n\n"

                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# WebSocket — real-time ops feed
# ---------------------------------------------------------------------------

_ws_clients: list[WebSocket] = []


@router.websocket("/ws/ops")
async def ops_websocket(websocket: WebSocket) -> None:
    """
    WebSocket feed: cycle updates, health changes, alerts.
    Broadcasts to all connected clients from the brain's Redis pub/sub channel.
    Falls back to polling brain state every 5 seconds.
    """
    await websocket.accept()
    _ws_clients.append(websocket)
    log.info("WebSocket /ws/ops: client connected (total=%d)", len(_ws_clients))

    brain = getattr(websocket.app.state, "brain", None)

    try:
        while True:
            # Snapshot current state and push
            payload: dict[str, Any] = {
                "type": "ops_snapshot",
                "ts_iso": _now_iso(),
            }
            if brain:
                health = brain.latest_health()
                report = brain.latest_report()
                payload.update({
                    "status":          brain.status(),
                    "cycle_count":     brain._cycle_count,
                    "rule_based_mode": brain.is_rule_based_mode(),
                    "health": {
                        "online_phones":   health.online_phones   if health else 0,
                        "proxy_ready":     health.proxy_ready     if health else 0,
                        "active_accounts": health.active_accounts if health else 0,
                        "dead_accounts":   health.dead_accounts   if health else 0,
                        "sessions_valid":  health.sessions_valid  if health else 0,
                    },
                    "alerts": brain.active_alerts()[:10],
                    "last_cycle": {
                        "status":      report.status       if report else None,
                        "completed_at": report.completed_at_iso if report else None,
                        "duration_sec": report.duration_sec    if report else None,
                    },
                })
            await websocket.send_json(payload)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("WebSocket /ws/ops error: %s", exc)
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
        log.info("WebSocket /ws/ops: client disconnected (total=%d)", len(_ws_clients))


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
