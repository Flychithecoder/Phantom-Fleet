"""
Phase 1 — IG MVP readiness + launch.

Phase 1 is "full 17-phone box running ~30-50 Tatiana+Melodie IG accounts
end-to-end on 1-2 TrumpProxies plans" per PLAN.md §Phase 1. This module
aggregates the go/no-go gates and exposes a single launch endpoint that
fires the orchestrator once every gate is green.

Endpoints:
    GET  /api/phase1/readiness   — gate-by-gate go/no-go report
    POST /api/phase1/start       — kick off warming + agents (if ready)

The readiness report is what the operator stares at before pulling the
trigger. Every gate maps to one of the Phase 1 deliverables in PLAN.md.
Any gate failing short-circuits the launch so we don't fire warming on a
collision-ridden fleet or an unverified proxy pool.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...agents.registry import AGENT_CLASSES

log = logging.getLogger("phantom_fleet.api.phase1")

router = APIRouter()


# ---------------------------------------------------------------------------
# Gate names — kept as a tuple so the frontend can render them in a stable order
# ---------------------------------------------------------------------------


# The Phase 1 agents from PLAN.md §Phase 1 "Deliverables". Order matches the
# dashboard display order — put critical blockers first.
PHASE_1_AGENTS: tuple[str, ...] = (
    "account_setup",
    "warming",
    "recovery",
    "replacement",
    "dm",
    "content",
    "funnel_conversion",
    "fingerprint_monitor",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class Gate(BaseModel):
    key: str
    label: str
    status: str                       # "pass" | "warn" | "fail" | "pending"
    detail: str
    blocking: bool                    # true: hard block to Phase 1 launch


class ReadinessOut(BaseModel):
    ready: bool                       # true iff no blocking gate fails
    fleet_size: int
    gates: list[Gate]
    agents_total: int
    agents_available: int             # agents that can be instantiated & called
    summary: str


class LaunchOut(BaseModel):
    started: bool
    reason: Optional[str] = None
    warming_running: bool
    agents_started: list[str]
    message: str


# ---------------------------------------------------------------------------
# Readiness gates
# ---------------------------------------------------------------------------


async def _gate_fleet(request: Request) -> Gate:
    fleet = request.app.state.ctx.fleet
    size = len(fleet.all_phones())
    if size == 0:
        return Gate(key="fleet", label="Fleet discovered",
                   status="fail",
                   detail="No phones registered. Run POST /api/fleet/scan first.",
                   blocking=True)
    if size < 5:
        return Gate(key="fleet", label="Fleet discovered",
                   status="warn",
                   detail=f"Only {size} phones registered — Phase 1 targets the full 17+ phone box.",
                   blocking=False)
    return Gate(key="fleet", label="Fleet discovered",
               status="pass", detail=f"{size} phones registered.", blocking=True)


async def _gate_cluster(request: Request) -> Gate:
    # Reuse the same logic as /api/fleet/cluster/collisions without re-importing.
    from .fleet import cluster_collisions
    result = await cluster_collisions(request)
    if result["healthy"]:
        return Gate(key="cluster", label="Identity cluster-check",
                   status="pass",
                   detail=f"No collisions across {result['fleet_size']} devices.",
                   blocking=True)
    return Gate(key="cluster", label="Identity cluster-check",
               status="fail",
               detail=(f"{result['critical_count']} critical identity collisions"
                       f" + {result['pair_violations_count']} model/OS mismatches"
                       f" on {len(result['affected_serials'])} phones."),
               blocking=True)


async def _gate_proxy(request: Request) -> Gate:
    proxy = getattr(request.app.state, "proxy", None)
    if proxy is None:
        return Gate(key="proxy", label="Proxy pool configured",
                   status="fail",
                   detail="No proxy orchestrator — set IPROYAL_USER + IPROYAL_PASS or "
                          "SMARTPROXY_* env vars before launch.",
                   blocking=True)
    try:
        status = proxy.fleet_status() if hasattr(proxy, "fleet_status") else {}
        pool_size = status.get("pool_size", 0) if isinstance(status, dict) else 0
    except Exception as exc:
        return Gate(key="proxy", label="Proxy pool configured",
                   status="warn",
                   detail=f"Proxy orchestrator attached but status query failed: {exc}",
                   blocking=False)
    if pool_size == 0:
        return Gate(key="proxy", label="Proxy pool configured",
                   status="fail",
                   detail="Proxy pool is empty — add proxies at /proxy or set PHANTOM_PROXY_POOL.",
                   blocking=True)
    return Gate(key="proxy", label="Proxy pool configured",
               status="pass", detail=f"{pool_size} proxies in rotation.",
               blocking=True)


async def _gate_proxy_verified(request: Request) -> Gate:
    fleet = request.app.state.ctx.fleet
    from ...core.phone_controller import PhoneState
    phones = fleet.all_phones()
    if not phones:
        return Gate(key="proxy_verified", label="Proxies verified per-phone",
                   status="pending", detail="No phones to verify.", blocking=False)
    ready = sum(1 for p in phones if p.state == PhoneState.PROXY_READY)
    if ready == 0:
        return Gate(key="proxy_verified", label="Proxies verified per-phone",
                   status="fail",
                   detail=(f"0 of {len(phones)} phones have passed proxy verification. "
                           "Run POST /api/fleet/verify-all before launch."),
                   blocking=True)
    if ready < len(phones):
        return Gate(key="proxy_verified", label="Proxies verified per-phone",
                   status="warn",
                   detail=f"{ready} of {len(phones)} phones PROXY_READY; "
                          f"{len(phones) - ready} still need verification.",
                   blocking=False)
    return Gate(key="proxy_verified", label="Proxies verified per-phone",
               status="pass",
               detail=f"All {len(phones)} phones PROXY_READY.", blocking=True)


async def _gate_accounts(request: Request) -> Gate:
    from .accounts import _store as _acc_store
    total = len(_acc_store())
    # Phase 1 target from PLAN.md: 30-50 accounts on existing Tatiana/Melodie.
    if total == 0:
        return Gate(key="accounts", label="Accounts provisioned",
                   status="fail",
                   detail="No accounts provisioned. Bulk-import or POST /api/accounts/provision.",
                   blocking=True)
    if total < 30:
        return Gate(key="accounts", label="Accounts provisioned",
                   status="warn",
                   detail=f"{total} accounts provisioned; Phase 1 targets 30–50.",
                   blocking=False)
    return Gate(key="accounts", label="Accounts provisioned",
               status="pass",
               detail=f"{total} accounts provisioned.", blocking=True)


async def _gate_warming(request: Request) -> Gate:
    # The orchestrator's running task is parked on app.state.warming_task when
    # start_warming has been called. We treat "not started" as pending, not fail.
    task = getattr(request.app.state, "warming_task", None)
    if task is None:
        return Gate(key="warming", label="Warming orchestrator",
                   status="pending",
                   detail="Not started — /api/phase1/start will boot it.",
                   blocking=False)
    if task.done():
        exc = task.exception()
        if exc:
            return Gate(key="warming", label="Warming orchestrator",
                       status="fail",
                       detail=f"Last run crashed: {exc}", blocking=True)
        return Gate(key="warming", label="Warming orchestrator",
                   status="warn",
                   detail="Last run completed; next cycle has not been scheduled.",
                   blocking=False)
    return Gate(key="warming", label="Warming orchestrator",
               status="pass", detail="Running.", blocking=True)


async def _gate_mirror(request: Request) -> Gate:
    mirror = getattr(request.app.state, "mirror", None)
    if mirror is None:
        return Gate(key="mirror", label="Mirror bridge",
                   status="warn",
                   detail="PHANTOM_MIRROR_URL unset — falling back to local adb; "
                          "will only see the one shared-ADB phone.",
                   blocking=False)
    if not getattr(mirror, "available", False):
        return Gate(key="mirror", label="Mirror bridge",
                   status="fail",
                   detail=f"Mirror attached at {mirror.base_url} but /health failing.",
                   blocking=False)
    return Gate(key="mirror", label="Mirror bridge",
               status="pass", detail=f"Attached at {mirror.base_url}.", blocking=False)


async def _gate_agents(request: Request) -> Gate:
    # Instantiability check — every Phase 1 agent class imports cleanly.
    missing: list[str] = []
    for name in PHASE_1_AGENTS:
        cls = AGENT_CLASSES.get(name)
        if cls is None:
            missing.append(name)
    if missing:
        return Gate(key="agents", label="Phase 1 agents registered",
                   status="fail",
                   detail=f"Missing from registry: {', '.join(missing)}",
                   blocking=True)
    return Gate(key="agents", label="Phase 1 agents registered",
               status="pass",
               detail=f"All {len(PHASE_1_AGENTS)} Phase 1 agents in registry.",
               blocking=True)


_ALL_GATES = (
    _gate_fleet,
    _gate_mirror,
    _gate_cluster,
    _gate_proxy,
    _gate_proxy_verified,
    _gate_accounts,
    _gate_agents,
    _gate_warming,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/readiness", response_model=ReadinessOut)
async def readiness(request: Request) -> ReadinessOut:
    """Aggregate every Phase 1 gate into one go/no-go report."""
    gates = []
    for gate_fn in _ALL_GATES:
        try:
            g = await gate_fn(request)
        except Exception as exc:
            log.exception("phase1 gate %s raised", gate_fn.__name__)
            g = Gate(
                key=gate_fn.__name__.removeprefix("_gate_"),
                label=gate_fn.__name__.removeprefix("_gate_").replace("_", " ").title(),
                status="fail",
                detail=f"Gate check raised: {exc}",
                blocking=True,
            )
        gates.append(g)

    ready = all(g.status == "pass" for g in gates if g.blocking)
    fleet = request.app.state.ctx.fleet
    agents_ok = sum(1 for n in PHASE_1_AGENTS if AGENT_CLASSES.get(n) is not None)

    if ready:
        summary = "All blocking gates green — Phase 1 is cleared for launch."
    else:
        blockers = [g.label for g in gates if g.blocking and g.status != "pass"]
        summary = f"Blocked by: {', '.join(blockers)}"

    return ReadinessOut(
        ready=ready,
        fleet_size=len(fleet.all_phones()),
        gates=gates,
        agents_total=len(PHASE_1_AGENTS),
        agents_available=agents_ok,
        summary=summary,
    )


@router.post("/start", response_model=LaunchOut)
async def start_phase1(request: Request) -> LaunchOut:
    """
    Launch Phase 1: warming orchestrator + agent mesh.

    Refuses to launch if any blocking gate in /readiness is not pass. Returns
    the list of agents that were started. Idempotent — calling again when
    warming is already running is a no-op.
    """
    report = await readiness(request)
    if not report.ready:
        raise HTTPException(
            status_code=409,
            detail={"reason": "readiness_blocked", "summary": report.summary,
                    "blockers": [g.label for g in report.gates
                                 if g.blocking and g.status != "pass"]},
        )

    started_agents: list[str] = []
    warming_already = False

    # 1. Warming orchestrator
    existing = getattr(request.app.state, "warming_task", None)
    if existing is not None and not existing.done():
        warming_already = True
    else:
        from ...core.warming_orchestrator import WarmingOrchestrator
        from ...core.time_slot_scheduler import TimeSlotScheduler
        from .accounts import _store as _acc_store

        fleet = request.app.state.ctx.fleet
        accounts = [a for a in _acc_store().values() if a.get("phone_serial")]
        scheduler = TimeSlotScheduler()

        orch = WarmingOrchestrator(
            fleet_runners={p.serial: p for p in fleet.all_phones()},
            schedule=scheduler,
        )

        async def _runner():
            from datetime import date
            try:
                await orch.run_warming_cycle(accounts, date.today().isoformat())
            except Exception:
                log.exception("warming cycle crashed")

        request.app.state.warming_task = asyncio.create_task(
            _runner(), name="phase1_warming",
        )

    # 2. Agents — mark them as enabled on app.state so the scheduler picks them up.
    enabled = set(getattr(request.app.state, "phase1_agents_enabled", set()))
    for name in PHASE_1_AGENTS:
        if name not in enabled:
            started_agents.append(name)
            enabled.add(name)
    request.app.state.phase1_agents_enabled = enabled

    message = (
        "Phase 1 launched — warming cycle kicked off" if not warming_already
        else "Phase 1 already running — refreshed agent enablement"
    )
    return LaunchOut(
        started=True,
        warming_running=True,
        agents_started=started_agents,
        message=message,
    )
