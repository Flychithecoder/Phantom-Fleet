"""
Phase 2 — parity expansion readiness + launch.

Phase 2 covers the roster from PLAN.md §Phase 2 (Weeks 7-12):
  - Threads, Reddit, TikTok, Snapchat, X/Twitter support
  - DM Agent cross-platform
  - Content Agent via ModelForge + Chat AI
  - Funnel Conversion Agent cross-platform
  - Full fleet deployment (180 phones target)
  - Mobile proxy modem farm (20 DIY IPs)

The readiness dashboard aggregates per-platform scaffold status + the
cross-cutting agent/fleet/revenue gates. A platform is "ready" when its
companion APK primitives land, its warming curve is defined, and at least
one account is provisioned for it.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...agents.registry import AGENT_CLASSES
from ...platforms import PHASE_2_PLATFORMS, PlatformSpec, by_key

log = logging.getLogger("phantom_fleet.api.phase2")
router = APIRouter()


PHASE_2_AGENTS: tuple[str, ...] = (
    "dm",
    "content",
    "funnel_conversion",
    "content_scout",
    "source_discovery",
    "fingerprint_monitor",
)


class PlatformGate(BaseModel):
    key:            str
    label:          str
    status:         str                 # "scaffold" | "primitives" | "warming" | "ready"
    account_source: str
    warming_days:   int
    account_count:  int                 # accounts provisioned for this platform
    detail:         str
    blocking:       bool                # blocking for Phase 2 launch


class Gate(BaseModel):
    key:      str
    label:    str
    status:   str                       # "pass" | "warn" | "fail" | "pending"
    detail:   str
    blocking: bool


class ReadinessOut(BaseModel):
    ready:            bool
    phase1_ready:     bool               # Phase 1 must be cleared first
    platforms:        list[PlatformGate]
    gates:            list[Gate]
    agents_total:     int
    agents_available: int
    summary:          str


class LaunchOut(BaseModel):
    started:         bool
    platforms_enabled: list[str]
    agents_started:  list[str]
    message:         str


def _accounts_by_platform(request: Request) -> dict[str, int]:
    from .accounts import _store
    counts: dict[str, int] = {}
    for row in _store().values():
        p = row.get("platform", "instagram")
        counts[p] = counts.get(p, 0) + 1
    return counts


def _platform_gate(spec: PlatformSpec, account_count: int) -> PlatformGate:
    # Status progression. Any platform with >=1 real account provisioned
    # for it moves up at least one tier regardless of scaffold flag.
    status = spec.status
    if account_count > 0 and status == "scaffold":
        status = "primitives"
    blocking = False                # Phase 2 does not hard-block on any single platform
    detail_bits: list[str] = []
    if account_count:
        detail_bits.append(f"{account_count} accounts")
    else:
        detail_bits.append("no accounts yet")
    detail_bits.append(f"warming: {spec.warming_days}d")
    detail_bits.append(f"source: {spec.account_source}")
    detail_bits.append(spec.funnel_path)
    return PlatformGate(
        key=spec.key,
        label=spec.display_name,
        status=status,
        account_source=spec.account_source,
        warming_days=spec.warming_days,
        account_count=account_count,
        detail=" · ".join(detail_bits),
        blocking=blocking,
    )


async def _gate_phase1_cleared(request: Request) -> Gate:
    # Phase 2 must not start until Phase 1 is at least cleared for launch.
    from .phase1 import readiness as phase1_readiness
    try:
        rpt = await phase1_readiness(request)
    except Exception as exc:
        return Gate(key="phase1", label="Phase 1 cleared",
                   status="fail", detail=f"Phase 1 readiness query failed: {exc}",
                   blocking=True)
    if not rpt.ready:
        return Gate(key="phase1", label="Phase 1 cleared",
                   status="fail",
                   detail=f"Phase 1 is not cleared: {rpt.summary}",
                   blocking=True)
    return Gate(key="phase1", label="Phase 1 cleared",
               status="pass", detail="Phase 1 blocking gates are all green.",
               blocking=True)


async def _gate_agents(request: Request) -> Gate:
    missing = [n for n in PHASE_2_AGENTS if AGENT_CLASSES.get(n) is None]
    if missing:
        return Gate(key="agents", label="Phase 2 agents registered",
                   status="fail",
                   detail=f"Missing from registry: {', '.join(missing)}",
                   blocking=True)
    return Gate(key="agents", label="Phase 2 agents registered",
               status="pass",
               detail=f"All {len(PHASE_2_AGENTS)} Phase 2 agents in registry.",
               blocking=True)


async def _gate_fleet_scale(request: Request) -> Gate:
    # Phase 2 target: 180 phones across 9 farms.
    fleet = request.app.state.ctx.fleet
    size = len(fleet.all_phones())
    if size < 17:
        return Gate(key="fleet_scale", label="Fleet scale (Phase 2)",
                   status="fail",
                   detail=f"Only {size} phones online; Phase 2 targets 180 across 9 farms.",
                   blocking=True)
    if size < 180:
        return Gate(key="fleet_scale", label="Fleet scale (Phase 2)",
                   status="warn",
                   detail=f"{size} phones online; full Phase 2 target is 180.",
                   blocking=False)
    return Gate(key="fleet_scale", label="Fleet scale (Phase 2)",
               status="pass",
               detail=f"{size} phones online — full fleet.", blocking=True)


async def _gate_proxy_farm(request: Request) -> Gate:
    # Phase 2 target: 20 DIY mobile IPs in the modem farm.
    pool = getattr(request.app.state, "proxy", None)
    if pool is None:
        return Gate(key="proxy_farm", label="Mobile proxy farm",
                   status="fail", detail="No proxy pool attached.",
                   blocking=True)
    try:
        size = pool.fleet_status().get("pool_size", 0)
    except Exception:
        size = 0
    if size < 5:
        return Gate(key="proxy_farm", label="Mobile proxy farm",
                   status="fail",
                   detail=f"{size} proxies in rotation; need at least 5 for Phase 2 cutover.",
                   blocking=True)
    if size < 20:
        return Gate(key="proxy_farm", label="Mobile proxy farm",
                   status="warn",
                   detail=f"{size} proxies; Phase 2 target is 20 DIY mobile IPs.",
                   blocking=False)
    return Gate(key="proxy_farm", label="Mobile proxy farm",
               status="pass",
               detail=f"{size} proxies — full Phase 2 target.", blocking=True)


async def _gate_revenue_trigger(request: Request) -> Gate:
    # Phase 2 trigger: >= $500/mo from Phase 1 (per PLAN.md §Phase 2).
    # Pull from funnel route if available; otherwise mark pending.
    try:
        from .funnel import revenue_summary          # type: ignore[attr-defined]
        rev = await revenue_summary(request)
        monthly = float(getattr(rev, "monthly_usd", 0.0))
    except Exception:
        monthly = 0.0
    if monthly < 500:
        return Gate(key="revenue_trigger", label="Revenue trigger ($500/mo)",
                   status="warn" if monthly > 0 else "pending",
                   detail=(f"${monthly:.0f}/mo — Phase 2 locked until ≥$500/mo "
                           "from Phase 1 (PLAN.md §Phase 2 trigger)."),
                   blocking=False)
    return Gate(key="revenue_trigger", label="Revenue trigger ($500/mo)",
               status="pass",
               detail=f"${monthly:.0f}/mo — Phase 2 trigger met.", blocking=False)


async def _gate_at_least_one_platform(request: Request, platforms: list[PlatformGate]) -> Gate:
    with_accounts = [p for p in platforms if p.account_count > 0]
    if not with_accounts:
        return Gate(key="platform_accounts",
                   label="Any Phase 2 platform has accounts",
                   status="fail",
                   detail="No Phase 2 platform has any accounts provisioned.",
                   blocking=True)
    return Gate(key="platform_accounts",
               label="Any Phase 2 platform has accounts",
               status="pass",
               detail=f"{len(with_accounts)} platform(s) with accounts: "
                      f"{', '.join(p.key for p in with_accounts)}",
               blocking=True)


_CROSS_GATES = (_gate_phase1_cleared, _gate_agents, _gate_fleet_scale,
                _gate_proxy_farm, _gate_revenue_trigger)


@router.get("/readiness", response_model=ReadinessOut)
async def readiness(request: Request) -> ReadinessOut:
    counts = _accounts_by_platform(request)
    platforms = [_platform_gate(spec, counts.get(spec.key, 0))
                 for spec in PHASE_2_PLATFORMS]

    gates: list[Gate] = []
    for fn in _CROSS_GATES:
        try:
            gates.append(await fn(request))
        except Exception as exc:
            log.exception("phase2 gate %s raised", fn.__name__)
            gates.append(Gate(
                key=fn.__name__.removeprefix("_gate_"),
                label=fn.__name__.removeprefix("_gate_").replace("_", " ").title(),
                status="fail", detail=f"Gate check raised: {exc}", blocking=True,
            ))
    gates.append(await _gate_at_least_one_platform(request, platforms))

    # Phase 1 must be cleared first (a Phase 2 launch is a no-op otherwise).
    phase1_gate = next(g for g in gates if g.key == "phase1")

    ready = all(g.status == "pass" for g in gates if g.blocking)

    agents_ok = sum(1 for n in PHASE_2_AGENTS if AGENT_CLASSES.get(n) is not None)

    if ready:
        summary = "All blocking gates green — Phase 2 is cleared for launch."
    else:
        blockers = [g.label for g in gates if g.blocking and g.status != "pass"]
        summary = f"Blocked by: {', '.join(blockers)}"

    return ReadinessOut(
        ready=ready,
        phase1_ready=phase1_gate.status == "pass",
        platforms=platforms,
        gates=gates,
        agents_total=len(PHASE_2_AGENTS),
        agents_available=agents_ok,
        summary=summary,
    )


@router.post("/start", response_model=LaunchOut)
async def start_phase2(request: Request) -> LaunchOut:
    rpt = await readiness(request)
    if not rpt.ready:
        raise HTTPException(
            status_code=409,
            detail={"reason": "readiness_blocked", "summary": rpt.summary,
                    "blockers": [g.label for g in rpt.gates
                                 if g.blocking and g.status != "pass"]},
        )

    # Enable platforms (just flag on app.state — the executors read this).
    enabled_platforms = set(
        getattr(request.app.state, "phase2_platforms_enabled", set())
    )
    newly_enabled: list[str] = []
    for p in rpt.platforms:
        if p.key not in enabled_platforms:
            enabled_platforms.add(p.key)
            newly_enabled.append(p.key)
    request.app.state.phase2_platforms_enabled = enabled_platforms

    # Enable Phase 2 agents the same way Phase 1 did.
    enabled_agents = set(getattr(request.app.state, "phase2_agents_enabled", set()))
    started_agents: list[str] = []
    for name in PHASE_2_AGENTS:
        if name not in enabled_agents:
            enabled_agents.add(name)
            started_agents.append(name)
    request.app.state.phase2_agents_enabled = enabled_agents

    return LaunchOut(
        started=True,
        platforms_enabled=newly_enabled or list(enabled_platforms),
        agents_started=started_agents,
        message=(f"Phase 2 launched — {len(newly_enabled)} new platform(s) enabled, "
                 f"{len(started_agents)} agent(s) started."),
    )
