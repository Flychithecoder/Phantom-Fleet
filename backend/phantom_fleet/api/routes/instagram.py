"""
Instagram platform routes — just the health detector for now.

/health/scan      — recompute every active IG account's score
/health/summary   — rollup + at-risk list + flag counts
/health/{id}      — one account's detailed signals + flags
/health/simulate  — build an IGSignals in-memory and score it (dev tool)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...platforms.instagram_health import IGSignals, score_signals
from ...platforms import instagram as ig_mod
from ...platforms.instagram_funnel import IGFunnelEvent

router = APIRouter()


class SimulateIn(BaseModel):
    warmup_day:            int = 1
    posts_in_ring:         int = 0
    posts_last_48h:        int = 0
    hours_since_last_post: float = 0.0
    has_threads_link:      bool = True
    bridge_skipped_recent: int = 0
    bridge_queued_recent:  int = 0


def _monitor(request: Request):
    m = getattr(request.app.state, "ig_health", None)
    if m is None:
        raise HTTPException(503, "IG health monitor not initialised")
    return m


@router.post("/health/scan")
async def scan(request: Request) -> dict:
    results = _monitor(request).scan_all()
    return {
        "scanned": len(results),
        "rollup":  _monitor(request).rollup.as_dict(),
    }


@router.get("/health/summary")
async def summary(request: Request) -> dict:
    return _monitor(request).summary()


@router.get("/health/{account_id}")
async def one(request: Request, account_id: str) -> dict:
    h = _monitor(request).for_account(account_id)
    if h is None:
        raise HTTPException(404, f"no health record for {account_id}")
    return h.as_dict()


@router.post("/health/simulate")
async def simulate(body: SimulateIn) -> dict:
    signals = IGSignals(**body.model_dump())
    score, flags, status = score_signals(signals)
    return {
        "signals": signals.as_dict(),
        "score":   score,
        "flags":   flags,
        "status":  status,
    }


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def _recovery(request: Request):
    r = getattr(request.app.state, "ig_recovery", None)
    if r is None:
        raise HTTPException(503, "IG recovery agent not initialised")
    return r


@router.get("/recovery/status")
async def recovery_status(request: Request) -> dict:
    return _recovery(request).summary()


@router.post("/recovery/tick")
async def recovery_tick(request: Request) -> dict:
    return _recovery(request).tick()


@router.post("/recovery/{account_id}/graduate")
async def recovery_graduate(request: Request, account_id: str) -> dict:
    rec = _recovery(request).force_graduate(account_id)
    if rec is None:
        raise HTTPException(404, f"no recovery record for {account_id}")
    return rec.as_dict()


@router.post("/recovery/{account_id}/skip-cooldown")
async def recovery_skip(request: Request, account_id: str) -> dict:
    rec = _recovery(request).force_rewarm(account_id)
    if rec is None:
        raise HTTPException(404, f"no recovery record for {account_id}")
    return rec.as_dict()


# ---------------------------------------------------------------------------
# Budgets + warming curve
# ---------------------------------------------------------------------------


@router.get("/budget/{account_id}")
async def budget(request: Request, account_id: str, warmup_day: int | None = None) -> dict:
    from .accounts import _store as _acc_store_fn
    row = _acc_store_fn().get(account_id)
    if row is None or row.get("platform") != "instagram":
        raise HTTPException(404, "Instagram account not found")
    day = int(warmup_day if warmup_day is not None else row.get("warmup_day", 1))
    return ig_mod.budget_for(account_id, day).as_dict()


@router.get("/curve/{account_id}")
async def curve(request: Request, account_id: str) -> dict:
    from .accounts import _store as _acc_store_fn
    row = _acc_store_fn().get(account_id)
    if row is None or row.get("platform") != "instagram":
        raise HTTPException(404, "Instagram account not found")
    return {
        "warming_days": ig_mod.WARMING_DAYS,
        "days": [b.as_dict() for b in ig_mod.budgets_across_curve(account_id)],
    }


# ---------------------------------------------------------------------------
# Fleet rebalancer
# ---------------------------------------------------------------------------


def _reb(request: Request):
    r = getattr(request.app.state, "ig_rebalancer", None)
    if r is None:
        raise HTTPException(503, "IG rebalancer not initialised")
    return r


@router.get("/rebalancer/status")
async def rebalancer_status(request: Request) -> dict:
    return _reb(request).summary()


@router.post("/rebalancer/tick")
async def rebalancer_tick(request: Request) -> dict:
    return _reb(request).tick()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _orch(request: Request):
    o = getattr(request.app.state, "ig_orchestrator", None)
    if o is None:
        raise HTTPException(503, "IG orchestrator not initialised")
    return o


@router.get("/orchestrator/status")
async def orch_status(request: Request) -> dict:
    return _orch(request).status()


@router.post("/orchestrator/plan-now")
async def orch_plan(request: Request) -> dict:
    plan = await _orch(request).run_once()
    return {
        "planned": len(plan),
        "entries": [
            {"account_id": p.account_id, "kind": p.kind,
             "target": p.target, "reason": p.reason}
            for p in plan
        ],
    }


@router.get("/queue")
async def queue(request: Request, limit: int = 30) -> dict:
    q = getattr(request.app.state, "ig_queue", None) or []
    return {"queued": len(q), "entries": list(reversed(q))[:limit]}


# ---------------------------------------------------------------------------
# Active probes
# ---------------------------------------------------------------------------


def _probes(request: Request):
    p = getattr(request.app.state, "ig_probes", None)
    if p is None:
        raise HTTPException(503, "IG probe scheduler not initialised")
    return p


@router.get("/probes/status")
async def probes_status(request: Request, limit: int = 20) -> dict:
    p = _probes(request)
    return {
        "running": p.running(),
        "stats":   p.stats.as_dict(),
        "recent":  p.recent(limit=limit),
    }


@router.post("/probes/tick")
async def probes_tick(request: Request) -> dict:
    return await _probes(request).tick()


@router.get("/probes/{account_id}")
async def probes_for_account(request: Request, account_id: str) -> dict:
    p = _probes(request)
    return {
        "results": p.for_account(account_id, limit=20),
        "flags":   p.flags_for(account_id),
        "penalty": p.penalty_for(account_id),
    }


# ---------------------------------------------------------------------------
# Funnel
# ---------------------------------------------------------------------------


class FunnelRecordIn(BaseModel):
    kind: str
    ig_account_id: str
    post_id: str | None = None
    target: str = ""


def _funnel(request: Request):
    f = getattr(request.app.state, "ig_funnel", None)
    if f is None:
        raise HTTPException(503, "IG funnel not initialised")
    return f


@router.get("/funnel/summary")
async def funnel_summary(request: Request) -> dict:
    return _funnel(request).summary()


@router.get("/funnel/{account_id}")
async def funnel_for_account(request: Request, account_id: str) -> dict:
    return _funnel(request).for_account(account_id).as_dict()


@router.post("/funnel/record")
async def funnel_record(request: Request, body: FunnelRecordIn) -> dict:
    """Dev / executor hook: synthesise a funnel event."""
    ev = IGFunnelEvent(
        kind=body.kind,         # type: ignore[arg-type]
        ig_account_id=body.ig_account_id,
        post_id=body.post_id,
        target=body.target,
    )
    counter = _funnel(request).record(ev)
    return counter.as_dict()


# ---------------------------------------------------------------------------
# DM flow
# ---------------------------------------------------------------------------


def _dm(request: Request):
    d = getattr(request.app.state, "ig_dm", None)
    if d is None:
        raise HTTPException(503, "IG DM flow not initialised")
    return d


class _DMDraftIn(BaseModel):
    actor_id:         str
    recipient_handle: str


class _DMReplyIn(BaseModel):
    actor_id:         str
    recipient_handle: str
    body:             str


@router.get("/dm/summary")
async def dm_summary(request: Request) -> dict:
    return _dm(request).summary()


@router.post("/dm/tick")
async def dm_tick(request: Request) -> dict:
    return _dm(request).tick()


@router.post("/dm/draft")
async def dm_draft(request: Request, body: _DMDraftIn) -> dict:
    return _dm(request).draft(body.actor_id, body.recipient_handle).as_dict()


@router.post("/dm/{dm_id}/sent")
async def dm_mark_sent(request: Request, dm_id: str) -> dict:
    rec = _dm(request).record_sent(dm_id)
    if rec is None:
        raise HTTPException(404, "no dm record")
    return rec.as_dict()


@router.post("/dm/reply")
async def dm_reply(request: Request, body: _DMReplyIn) -> dict:
    rec = _dm(request).record_reply(body.actor_id, body.recipient_handle, body.body)
    if rec is None:
        raise HTTPException(404, "no matching dm")
    return rec.as_dict()


@router.get("/dm/{actor_id}")
async def dm_for_actor(request: Request, actor_id: str) -> dict:
    return _dm(request).for_actor(actor_id)


# ---------------------------------------------------------------------------
# Unfollow discipline
# ---------------------------------------------------------------------------


def _unfollow(request: Request):
    u = getattr(request.app.state, "ig_unfollow", None)
    if u is None:
        raise HTTPException(503, "IG unfollow discipline not initialised")
    return u


@router.get("/unfollow/summary")
async def unfollow_summary(request: Request) -> dict:
    return _unfollow(request).summary()


@router.post("/unfollow/tick")
async def unfollow_tick(request: Request) -> dict:
    return _unfollow(request).tick()


class _UnfollowFollowIn(BaseModel):
    actor_id:      str
    target_handle: str
    followed_at:   str | None = None


@router.post("/unfollow/record-follow")
async def unfollow_record_follow(request: Request,
                                  body: _UnfollowFollowIn) -> dict:
    rec = _unfollow(request).record_follow(
        body.actor_id, body.target_handle, followed_at=body.followed_at,
    )
    return rec.as_dict()


@router.post("/unfollow/record-follow-back")
async def unfollow_record_follow_back(request: Request,
                                       body: _UnfollowFollowIn) -> dict:
    rec = _unfollow(request).record_follow_back(
        body.actor_id, body.target_handle, when=body.followed_at,
    )
    return rec.as_dict() if rec else {"matched": False}


@router.post("/unfollow/mark-retained")
async def unfollow_mark_retained(request: Request,
                                  body: _UnfollowFollowIn) -> dict:
    rec = _unfollow(request).mark_retained(body.actor_id, body.target_handle)
    return rec.as_dict() if rec else {"matched": False}


@router.get("/unfollow/{actor_id}")
async def unfollow_for_actor(request: Request, actor_id: str) -> dict:
    return _unfollow(request).for_actor(actor_id)


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------


def _session(request: Request):
    s = getattr(request.app.state, "ig_session", None)
    if s is None:
        raise HTTPException(503, "IG session manager not initialised")
    return s


@router.get("/session/summary")
async def session_summary(request: Request) -> dict:
    return _session(request).summary()


@router.post("/session/tick")
async def session_tick(request: Request) -> dict:
    return _session(request).tick()


class _SessionLoginIn(BaseModel):
    ok:        bool
    token:     str | None = None
    needs_2fa: bool = False
    note:      str = ""


@router.post("/session/{account_id}/login")
async def session_login(request: Request, account_id: str,
                         body: _SessionLoginIn) -> dict:
    rec = _session(request).login(
        account_id, ok=body.ok, token=body.token,
        needs_2fa=body.needs_2fa, note=body.note,
    )
    return rec.as_dict()


@router.post("/session/{account_id}/complete-2fa")
async def session_complete_2fa(request: Request, account_id: str) -> dict:
    rec = _session(request).complete_2fa(account_id)
    if rec is None:
        raise HTTPException(404, "no session record")
    return rec.as_dict()


@router.post("/session/{account_id}/expire")
async def session_expire(request: Request, account_id: str) -> dict:
    rec = _session(request).expire(account_id)
    if rec is None:
        raise HTTPException(404, "no session record")
    return rec.as_dict()


@router.get("/session/{account_id}")
async def session_for_account(request: Request, account_id: str) -> dict:
    rec = _session(request).for_account(account_id)
    if rec is None:
        raise HTTPException(404, "no session record")
    return rec


# ---------------------------------------------------------------------------
# Checkpoint handler
# ---------------------------------------------------------------------------


def _checkpoint(request: Request):
    c = getattr(request.app.state, "ig_checkpoint", None)
    if c is None:
        raise HTTPException(503, "IG checkpoint handler not initialised")
    return c


class _CheckpointObserveIn(BaseModel):
    account_id: str
    signature:  str
    kind_override: str | None = None


@router.get("/checkpoint/summary")
async def checkpoint_summary(request: Request) -> dict:
    return _checkpoint(request).summary()


@router.post("/checkpoint/observe")
async def checkpoint_observe(request: Request,
                              body: _CheckpointObserveIn) -> dict:
    evt = _checkpoint(request).observe(
        body.account_id, body.signature,
        kind_override=body.kind_override,
    )
    return {
        "event_id":  evt.event_id, "kind": evt.kind,
        "severity":  evt.severity, "action": evt.action,
        "observed_at": evt.observed_at,
    }


@router.get("/checkpoint/{account_id}")
async def checkpoint_for_account(request: Request, account_id: str) -> dict:
    return {"events": _checkpoint(request).for_account(account_id, limit=20)}


# ---------------------------------------------------------------------------
# Engagement lattice
# ---------------------------------------------------------------------------


def _lattice(request: Request):
    l = getattr(request.app.state, "ig_lattice", None)
    if l is None:
        raise HTTPException(503, "IG lattice not initialised")
    return l


@router.get("/lattice/summary")
async def lattice_summary(request: Request) -> dict:
    return _lattice(request).summary()


@router.post("/lattice/plan")
async def lattice_plan(request: Request) -> dict:
    plan = _lattice(request).plan_tick()
    return {"planned": len(plan), "entries": plan,
            "stats": _lattice(request).summary()["stats"]}


# ---------------------------------------------------------------------------
# Device drift detector
# ---------------------------------------------------------------------------


def _drift(request: Request):
    d = getattr(request.app.state, "ig_drift", None)
    if d is None:
        raise HTTPException(503, "IG drift detector not initialised")
    return d


@router.get("/drift/summary")
async def drift_summary(request: Request) -> dict:
    return _drift(request).summary()


@router.post("/drift/scan")
async def drift_scan(request: Request) -> dict:
    events = _drift(request).scan_all()
    return {
        "new_trips":  len(events),
        "events":     [e.as_dict() for e in events],
        "stats":      _drift(request).summary()["stats"],
    }


@router.post("/drift/{phone_serial}/snapshot")
async def drift_snapshot(request: Request, phone_serial: str) -> dict:
    bl = _drift(request).snapshot(phone_serial)
    if bl is None:
        raise HTTPException(404, "no IG account bound to that phone")
    return {
        "phone_serial": bl.phone_serial,
        "first_seen":   bl.first_seen,
        "baseline":     bl.snapshot,
    }


@router.get("/drift/{phone_serial}")
async def drift_for_phone(request: Request, phone_serial: str) -> dict:
    info = _drift(request).for_phone(phone_serial)
    if info is None:
        raise HTTPException(404, "no baseline for that phone")
    return info


# ---------------------------------------------------------------------------
# Proxy pinning
# ---------------------------------------------------------------------------


def _proxy(request: Request):
    p = getattr(request.app.state, "ig_proxy", None)
    if p is None:
        raise HTTPException(503, "IG proxy scheduler not initialised")
    return p


@router.get("/proxy/summary")
async def proxy_summary(request: Request) -> dict:
    s = _proxy(request).summary()
    s["events"] = _proxy(request).recent_events(limit=20)
    return s


@router.post("/proxy/tick")
async def proxy_tick(request: Request) -> dict:
    return _proxy(request).tick()


@router.post("/proxy/{account_id}/rotate")
async def proxy_rotate(request: Request, account_id: str) -> dict:
    pin = _proxy(request).rotate(account_id)
    if pin is None:
        raise HTTPException(409, "rotation denied — no candidate or all quarantined")
    return {
        "account_id": pin.account_id, "proxy_id": pin.proxy_id,
        "country": pin.country, "rotations": pin.rotations,
        "expires_at": pin.expires_at,
    }


class _ProxyManualIn(BaseModel):
    proxy_id: str


@router.post("/proxy/{account_id}/pin")
async def proxy_pin_manual(request: Request, account_id: str,
                            body: _ProxyManualIn) -> dict:
    pin = _proxy(request).pin_manual(account_id, body.proxy_id)
    if pin is None:
        raise HTTPException(409, "manual pin denied — not in pool or quarantined")
    return {
        "account_id": pin.account_id, "proxy_id": pin.proxy_id,
        "country": pin.country, "source": pin.source,
    }


@router.post("/proxy/{account_id}/release")
async def proxy_release(request: Request, account_id: str) -> dict:
    ok = _proxy(request).release(account_id)
    return {"released": ok}


class _ProxyAddIn(BaseModel):
    proxy_id: str
    country:  str
    label:    str = ""


@router.post("/proxy/pool/add")
async def proxy_pool_add(request: Request, body: _ProxyAddIn) -> dict:
    """Dev helper — append a proxy to the in-memory IG pool."""
    pool: list = request.app.state.ig_proxy_pool
    if any(p.get("proxy_id") == body.proxy_id for p in pool):
        return {"added": False, "reason": "already in pool"}
    pool.append({"proxy_id": body.proxy_id, "country": body.country.upper(),
                 "label": body.label or body.proxy_id})
    return {"added": True, "pool_size": len(pool)}


# ---------------------------------------------------------------------------
# Identity pair-check
# ---------------------------------------------------------------------------


def _identity(request: Request):
    i = getattr(request.app.state, "ig_identity", None)
    if i is None:
        raise HTTPException(503, "IG identity scanner not initialised")
    return i


@router.get("/identity/summary")
async def identity_summary(request: Request) -> dict:
    return _identity(request).summary()


@router.post("/identity/scan")
async def identity_scan(request: Request) -> dict:
    results = _identity(request).scan_all()
    return {"scanned": len(results), "stats": {
        "clean": _identity(request).stats.clean,
        "warn":  _identity(request).stats.warn,
        "fail":  _identity(request).stats.fail,
    }}


@router.get("/identity/{account_id}")
async def identity_for_account(request: Request, account_id: str) -> dict:
    s = _identity(request).for_account(account_id)
    if s is None:
        raise HTTPException(404, f"no identity scan for {account_id}")
    return s.as_dict()


# ---------------------------------------------------------------------------
# Diurnal schedule
# ---------------------------------------------------------------------------


@router.get("/diurnal/summary")
async def diurnal_summary(request: Request) -> dict:
    from .accounts import _store as _acc_store_fn
    from ...platforms import instagram_diurnal as ig_diurnal
    from datetime import datetime, timezone as _tz
    rows = [r for r in _acc_store_fn().values()
            if r.get("platform") == "instagram"]
    now = datetime.now(_tz.utc)
    buckets = ig_diurnal.fleet_chronotype_breakdown(rows)
    mean_w = ig_diurnal.fleet_mean_weight_now(rows)
    awake = sum(1 for r in rows
                if ig_diurnal.weight_now(r["account_id"], r) >= 0.10)
    active = sum(1 for r in rows
                 if ig_diurnal.weight_now(r["account_id"], r) >= 0.50)
    return {
        "total":             len(rows),
        "now_utc":           now.isoformat(),
        "hour_utc":          now.hour,
        "chronotypes":       buckets,
        "mean_weight_now":   round(mean_w, 3),
        "awake":             awake,
        "active":            active,
        "skip_threshold":    0.10,
    }


@router.get("/diurnal/{account_id}")
async def diurnal_for_account(request: Request, account_id: str) -> dict:
    from .accounts import _store as _acc_store_fn
    from ...platforms import instagram_diurnal as ig_diurnal
    row = _acc_store_fn().get(account_id)
    if row is None or row.get("platform") != "instagram":
        raise HTTPException(404, "Instagram account not found")
    curve = ig_diurnal.curve_for(account_id, row)
    curve["weight_now"] = round(ig_diurnal.weight_now(account_id, row), 3)
    return curve


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def _executor(request: Request):
    e = getattr(request.app.state, "ig_executor", None)
    if e is None:
        raise HTTPException(503, "IG executor not initialised")
    return e


@router.get("/executor/status")
async def executor_status(request: Request) -> dict:
    return _executor(request).status()


@router.post("/executor/start")
async def executor_start(request: Request) -> dict:
    await _executor(request).start()
    return _executor(request).status()


@router.post("/executor/stop")
async def executor_stop(request: Request) -> dict:
    await _executor(request).stop()
    return _executor(request).status()


# ---------------------------------------------------------------------------
# Agent frame
# ---------------------------------------------------------------------------


def _agent(request: Request):
    a = getattr(request.app.state, "ig_agent", None)
    if a is None:
        raise HTTPException(503, "IG agent not initialised")
    return a


def _agent_ring(request: Request):
    r = getattr(request.app.state, "ig_agent_ring", None)
    if r is None:
        raise HTTPException(503, "IG agent ring not initialised")
    return r


@router.get("/agent/config")
async def agent_config(request: Request) -> dict:
    a = _agent(request)
    return {
        "name":                a.config.name,
        "max_iterations":      a.config.max_iterations,
        "max_usd_per_run":     a.config.max_usd_per_run,
        "max_usd_per_session": a.config.max_usd_per_session,
        "allowed_tools":       list(a.config.allowed_tools),
        "confirmation_required_for": list(a.config.confirmation_required_for),
    }


@router.get("/agent/runs")
async def agent_runs(request: Request, limit: int = 50,
                     account_id: str | None = None) -> dict:
    r = _agent_ring(request)
    return {
        "summary": r.summary(),
        "recent":  r.recent(limit=limit, account_id=account_id),
    }


# ---------------------------------------------------------------------------
# Per-account dossier
# ---------------------------------------------------------------------------


@router.get("/accounts/{account_id}/dossier")
async def account_dossier(request: Request, account_id: str) -> dict:
    """
    Aggregate payload for the /instagram/[account_id] drill page:
    account row + linked Threads account + health + recovery + recent
    IG bus posts.
    """
    from .accounts import _store as _acc_store_fn
    store = _acc_store_fn()
    row = store.get(account_id)
    if row is None or row.get("platform") != "instagram":
        raise HTTPException(404, "Instagram account not found")

    health_obj = None
    h = getattr(request.app.state, "ig_health", None)
    if h is not None:
        health_obj = h.compute(row).as_dict()

    recovery_obj = None
    r = getattr(request.app.state, "ig_recovery", None)
    if r is not None:
        rec = r.for_account(account_id)
        if rec is not None:
            recovery_obj = rec.as_dict()

    bus = getattr(request.app.state, "ig_event_bus", None)
    bus_events = []
    if bus is not None:
        bus_events = [e for e in bus.recent(limit=200)
                      if e.get("ig_account_id") == account_id]

    linked_threads = next(
        (r for r in store.values()
         if r.get("platform") == "threads"
         and r.get("ig_account_id") == account_id),
        None,
    )

    bridge_stats = None
    br = getattr(request.app.state, "ig_bridge", None)
    if br is not None:
        s = br.stats
        bridge_stats = {
            "events_in":        s.events_in,
            "replies_out":      s.replies_out,
            "skipped_budget":   s.skipped_budget,
            "skipped_no_link":  s.skipped_no_link,
            "skipped_gate":     s.skipped_gate,
            "last_action_id":   s.last_action_id,
        }

    warmup_day = int(row.get("warmup_day", 1))
    budget_obj = ig_mod.budget_for(account_id, warmup_day).as_dict()
    curve_obj = [b.as_dict() for b in ig_mod.budgets_across_curve(account_id)]

    funnel_obj = None
    f = getattr(request.app.state, "ig_funnel", None)
    if f is not None:
        funnel_obj = f.for_account(account_id).as_dict()

    return {
        "account": {
            "account_id":  row["account_id"],
            "username":    row.get("username", ""),
            "platform":    row.get("platform"),
            "status":      row.get("status", "active"),
            "warmup_day":  warmup_day,
        },
        "budget": budget_obj,
        "curve":  curve_obj,
        "funnel": funnel_obj,
        "linked_threads": {
            "account_id": linked_threads["account_id"],
            "handle":     linked_threads.get("handle", ""),
            "warmup_day": int(linked_threads.get("warmup_day", 1)),
            "status":     linked_threads.get("status", "active"),
        } if linked_threads else None,
        "health":        health_obj,
        "recovery":      recovery_obj,
        "bus_events":    bus_events,
        "bridge_stats":  bridge_stats,
    }
