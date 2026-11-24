"""
Threads platform routes — Phase 2 first unlock.

Endpoints:
    GET  /api/platforms/threads/accounts       — list linked Threads accounts
    POST /api/platforms/threads/link           — link an IG account to Threads
    POST /api/platforms/threads/post           — enqueue a post
    POST /api/platforms/threads/reply          — enqueue a reply
    POST /api/platforms/threads/repost         — enqueue a repost
    POST /api/platforms/threads/follow         — enqueue a follow
    GET  /api/platforms/threads/budget/{id}    — daily budget for an account
    GET  /api/platforms/threads/curve/{id}     — full warming curve preview
    GET  /api/platforms/threads/status         — platform rollup
    POST /api/platforms/threads/advance-day/{id} — dev helper, bumps warmup_day

Writes land in the in-memory account store (same as /api/accounts). The
executor is a stub — actions queue as pending entries on app.state.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...platforms import threads as threads_mod
from ...platforms.threads_funnel import FunnelEvent, ThreadsFunnelTracker
from ...platforms.ig_bridge import IGPostEvent

log = logging.getLogger("phantom_fleet.api.platforms.threads")
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ThreadsAccountOut(BaseModel):
    account_id:     str
    handle:         str
    ig_account_id:  str
    linked_at:      str
    warmup_day:     int
    can_cross_post: bool


class ThreadsListOut(BaseModel):
    accounts: list[ThreadsAccountOut]
    total:    int


class LinkIn(BaseModel):
    ig_account_id: str
    handle:        Optional[str] = None   # Defaults to IG handle


class LinkOut(BaseModel):
    account_id:    str
    handle:        str
    ig_account_id: str


class ActionIn(BaseModel):
    account_id: str
    target:     str = ""        # @handle for follow/reply/repost
    body:       str = ""        # post/reply text


class ActionOut(BaseModel):
    queued:     bool
    action_id:  str
    kind:       str
    budget_remaining: dict


class BudgetOut(BaseModel):
    day:        int
    follow:     int
    reply:      int
    repost:     int
    post:       int
    total:      int


class CurveOut(BaseModel):
    account_id: str
    warming_days: int
    days:       list[BudgetOut]


class StatusOut(BaseModel):
    platform:     str = "threads"
    linked_accounts: int
    pending_actions: int
    warming_days: int
    status:       str
    package:      str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _acc_store(request: Request) -> dict:
    from .accounts import _store
    return _store()


def _pending_queue(request: Request) -> list[dict]:
    """Per-process in-memory queue of actions the executor will consume."""
    q = getattr(request.app.state, "threads_queue", None)
    if q is None:
        q = []
        request.app.state.threads_queue = q
    return q


def _threads_rows(store: dict) -> list[dict]:
    return [r for r in store.values() if r.get("platform") == "threads"]


def _as_out(row: dict) -> ThreadsAccountOut:
    return ThreadsAccountOut(
        account_id=row["account_id"],
        handle=row.get("username", ""),
        ig_account_id=row.get("ig_account_id", ""),
        linked_at=row.get("created_at", ""),
        warmup_day=int(row.get("warmup_day", 1)),
        can_cross_post=threads_mod.can_cross_post(row),
    )


def _used_today(request: Request, account_id: str) -> dict[str, int]:
    """Count actions already dispatched today for one account."""
    today = datetime.now(timezone.utc).date().isoformat()
    used = {"follow": 0, "reply": 0, "repost": 0, "post": 0}
    for entry in _pending_queue(request):
        if entry["account_id"] != account_id:
            continue
        if entry["date"] != today:
            continue
        used[entry["kind"]] = used.get(entry["kind"], 0) + 1
    return used


def _remaining(request: Request, row: dict) -> dict[str, int]:
    b = threads_mod.budget_for(row["account_id"], int(row.get("warmup_day", 1)))
    used = _used_today(request, row["account_id"])
    return {
        "follow": max(0, b.follow - used["follow"]),
        "reply":  max(0, b.reply  - used["reply"]),
        "repost": max(0, b.repost - used["repost"]),
        "post":   max(0, b.post   - used["post"]),
    }


def _enqueue(request: Request, row: dict, kind: str,
             target: str, body: str) -> ActionOut:
    remaining = _remaining(request, row)
    if remaining.get(kind, 0) <= 0:
        raise HTTPException(
            status_code=429,
            detail={"reason": "budget_exhausted", "kind": kind,
                    "day": int(row.get("warmup_day", 1)),
                    "remaining": remaining},
        )
    if kind == "reply" and not threads_mod.can_cross_post(row):
        # Reuse the IG-warm-day guard: reply engagement should wait for the
        # IG parent to pass day 7 of its own warming curve.
        raise HTTPException(
            status_code=409,
            detail="Linked IG account below day 7 of IG warming — reply blocked.",
        )
    action_id = f"th-{uuid.uuid4().hex[:12]}"
    entry = {
        "action_id":  action_id,
        "account_id": row["account_id"],
        "kind":       kind,
        "target":     target,
        "body":       body[:500],
        "route":      threads_mod.ACTION_ROUTES[kind],
        "date":       datetime.now(timezone.utc).date().isoformat(),
        "queued_at":  datetime.now(timezone.utc).isoformat(),
        "status":     "queued",
    }
    _pending_queue(request).append(entry)
    log.info("Threads %s queued for %s (route=%s)",
             kind, row["account_id"], entry["route"])
    remaining[kind] -= 1
    return ActionOut(queued=True, action_id=action_id, kind=kind,
                     budget_remaining=remaining)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/accounts", response_model=ThreadsListOut)
async def list_accounts(request: Request) -> ThreadsListOut:
    rows = _threads_rows(_acc_store(request))
    accounts = [_as_out(r) for r in rows]
    return ThreadsListOut(accounts=accounts, total=len(accounts))


@router.post("/link", response_model=LinkOut)
async def link_ig(body: LinkIn, request: Request) -> LinkOut:
    # Fleet rebalancer gate — refuse new links while the fleet is yellow/red.
    rb = getattr(request.app.state, "threads_rebalancer", None)
    if rb is not None and not rb.linking_allowed():
        raise HTTPException(
            status_code=429,
            detail=f"Fleet throttled: rebalancer level={rb.stats.level}. "
                   f"New linking is paused until the fleet returns to green.",
        )
    store = _acc_store(request)
    ig = store.get(body.ig_account_id)
    if ig is None:
        raise HTTPException(status_code=404,
                            detail=f"IG account {body.ig_account_id!r} not found")
    if ig.get("platform") != "instagram":
        raise HTTPException(status_code=422,
                            detail=f"Account {body.ig_account_id!r} is not an IG account.")
    handle = body.handle or ig.get("username", "")
    account_id = f"th-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    store[account_id] = {
        "account_id":     account_id,
        "username":       handle,
        "platform":       "threads",
        "phone_serial":   ig.get("phone_serial"),
        "clone_index":    ig.get("clone_index"),
        "warmup_day":     1,
        "status":         "active",
        "created_at":     now,
        "session_valid":  None,
        "ig_account_id":  body.ig_account_id,
        "package":        threads_mod.THREADS_PACKAGE,
    }
    log.info("Threads account %s linked to IG %s on %s",
             account_id, body.ig_account_id, ig.get("phone_serial"))
    return LinkOut(account_id=account_id, handle=handle,
                   ig_account_id=body.ig_account_id)


def _row(request: Request, account_id: str) -> dict:
    row = _acc_store(request).get(account_id)
    if row is None or row.get("platform") != "threads":
        raise HTTPException(status_code=404,
                            detail=f"Threads account {account_id!r} not found")
    return row


@router.post("/post", response_model=ActionOut)
async def post(body: ActionIn, request: Request) -> ActionOut:
    return _enqueue(request, _row(request, body.account_id),
                    "post", target="", body=body.body)


@router.post("/reply", response_model=ActionOut)
async def reply(body: ActionIn, request: Request) -> ActionOut:
    return _enqueue(request, _row(request, body.account_id),
                    "reply", target=body.target, body=body.body)


@router.post("/repost", response_model=ActionOut)
async def repost(body: ActionIn, request: Request) -> ActionOut:
    return _enqueue(request, _row(request, body.account_id),
                    "repost", target=body.target, body="")


@router.post("/follow", response_model=ActionOut)
async def follow(body: ActionIn, request: Request) -> ActionOut:
    return _enqueue(request, _row(request, body.account_id),
                    "follow", target=body.target, body="")


@router.get("/budget/{account_id}", response_model=BudgetOut)
async def budget(account_id: str, request: Request) -> BudgetOut:
    row = _row(request, account_id)
    b = threads_mod.budget_for(account_id, int(row.get("warmup_day", 1)))
    return BudgetOut(**b.as_dict())


@router.get("/curve/{account_id}", response_model=CurveOut)
async def curve(account_id: str, request: Request) -> CurveOut:
    _row(request, account_id)  # existence check
    days = [BudgetOut(**b.as_dict())
            for b in threads_mod.budgets_across_curve(account_id)]
    return CurveOut(account_id=account_id,
                    warming_days=threads_mod.WARMING_DAYS, days=days)


@router.get("/status", response_model=StatusOut)
async def status(request: Request) -> StatusOut:
    linked = len(_threads_rows(_acc_store(request)))
    enabled = "threads" in getattr(request.app.state, "phase2_platforms_enabled", set())
    return StatusOut(
        linked_accounts=linked,
        pending_actions=len(_pending_queue(request)),
        warming_days=threads_mod.WARMING_DAYS,
        status="warming" if enabled or linked > 0 else "scaffold",
        package=threads_mod.THREADS_PACKAGE,
    )


@router.post("/advance-day/{account_id}")
async def advance_day(account_id: str, request: Request) -> dict:
    """Dev helper: bump warmup_day by 1 (clamped to WARMING_DAYS)."""
    row = _row(request, account_id)
    new = min(int(row.get("warmup_day", 1)) + 1, threads_mod.WARMING_DAYS)
    row["warmup_day"] = new
    return {"account_id": account_id, "warmup_day": new}


# ---------------------------------------------------------------------------
# Queue + executor
# ---------------------------------------------------------------------------


class QueueEntry(BaseModel):
    action_id:   str
    account_id:  str
    kind:        str
    target:      str
    body:        str
    route:       str
    status:      str
    date:        str
    queued_at:   str
    dispatched_at: Optional[str] = None
    phone_serial: Optional[str] = None
    error:       Optional[str] = None


class QueueOut(BaseModel):
    queued:      int
    dispatched:  int
    failed:      int
    entries:     list[QueueEntry]


class ExecStatusOut(BaseModel):
    running:     bool
    started_at:  Optional[str] = None
    stopped_at:  Optional[str] = None
    dispatched:  int
    failed:      int
    last_error:  Optional[str] = None


class CrossPostIn(BaseModel):
    ig_account_id: str
    reply_body:    str
    target:        str = ""     # @handle whose IG post you're replying to


class CrossPostOut(BaseModel):
    queued:       bool
    action_id:    str
    threads_account_id: str
    ig_account_id: str


def _executor(request: Request):
    return getattr(request.app.state, "threads_executor", None)


@router.get("/queue", response_model=QueueOut)
async def queue(request: Request) -> QueueOut:
    q = _pending_queue(request)
    entries = [QueueEntry(**{
        "action_id":     e["action_id"],
        "account_id":    e["account_id"],
        "kind":          e["kind"],
        "target":        e.get("target", ""),
        "body":          e.get("body", ""),
        "route":         e.get("route", ""),
        "status":        e.get("status", "queued"),
        "date":          e.get("date", ""),
        "queued_at":     e.get("queued_at", ""),
        "dispatched_at": e.get("dispatched_at"),
        "phone_serial":  e.get("phone_serial"),
        "error":         e.get("error"),
    }) for e in q[-100:]]
    def count(s: str) -> int:
        return sum(1 for e in q if e.get("status") == s)
    return QueueOut(
        queued=count("queued"),
        dispatched=count("dispatched"),
        failed=count("failed"),
        entries=entries,
    )


@router.post("/executor/start", response_model=ExecStatusOut)
async def executor_start(request: Request) -> ExecStatusOut:
    ex = _executor(request)
    if ex is None:
        raise HTTPException(status_code=503, detail="Executor not attached.")
    await ex.start()
    return ExecStatusOut(
        running=ex.running(),
        started_at=ex.stats.started_at, stopped_at=ex.stats.stopped_at,
        dispatched=ex.stats.dispatched, failed=ex.stats.failed,
        last_error=ex.stats.last_error,
    )


@router.post("/executor/stop", response_model=ExecStatusOut)
async def executor_stop(request: Request) -> ExecStatusOut:
    ex = _executor(request)
    if ex is None:
        raise HTTPException(status_code=503, detail="Executor not attached.")
    await ex.stop()
    return ExecStatusOut(
        running=ex.running(),
        started_at=ex.stats.started_at, stopped_at=ex.stats.stopped_at,
        dispatched=ex.stats.dispatched, failed=ex.stats.failed,
        last_error=ex.stats.last_error,
    )


@router.get("/executor/status", response_model=ExecStatusOut)
async def executor_status(request: Request) -> ExecStatusOut:
    ex = _executor(request)
    if ex is None:
        return ExecStatusOut(running=False, dispatched=0, failed=0)
    return ExecStatusOut(
        running=ex.running(),
        started_at=ex.stats.started_at, stopped_at=ex.stats.stopped_at,
        dispatched=ex.stats.dispatched, failed=ex.stats.failed,
        last_error=ex.stats.last_error,
    )


class FunnelEventIn(BaseModel):
    kind:               str                     # profile_view | bio_link_click | subscribe
    threads_account_id: str
    target:             str = ""
    meta:               dict = {}


class FunnelCountsOut(BaseModel):
    reply_posted:   int
    post_posted:    int
    profile_view:   int
    bio_link_click: int
    subscribe:      int


class FunnelRatesOut(BaseModel):
    reply_to_view:  float
    view_to_click:  float
    click_to_sub:   float
    reply_to_sub:   float


class AccountFunnelOut(BaseModel):
    threads_account_id: str
    counts: FunnelCountsOut
    rates:  FunnelRatesOut


class FunnelSummaryOut(BaseModel):
    totals:    AccountFunnelOut
    accounts:  int
    top:       list[AccountFunnelOut]
    ring_size: int


class FunnelActivityOut(BaseModel):
    events: list[dict]
    count:  int


def _tracker(request: Request) -> ThreadsFunnelTracker:
    t = getattr(request.app.state, "threads_funnel", None)
    if t is None:
        raise HTTPException(status_code=503, detail="Funnel tracker not attached.")
    return t


_ALLOWED_INBOUND_KINDS = {"profile_view", "bio_link_click", "subscribe"}


@router.post("/funnel/event", response_model=AccountFunnelOut)
async def funnel_event(body: FunnelEventIn, request: Request) -> AccountFunnelOut:
    """
    Record a downstream funnel event (profile view / bio-link click /
    subscribe). reply_posted and post_posted are emitted by the executor
    itself on dispatch — callers can't inject them here, to keep the
    attribution chain honest.
    """
    if body.kind not in _ALLOWED_INBOUND_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"kind must be one of {sorted(_ALLOWED_INBOUND_KINDS)} — "
                   "reply_posted/post_posted are emitted by the executor.",
        )
    th_row = _acc_store(request).get(body.threads_account_id)
    if th_row is None or th_row.get("platform") != "threads":
        raise HTTPException(status_code=404,
                            detail="Threads account not found.")
    counter = _tracker(request).record(FunnelEvent(
        kind=body.kind,                              # type: ignore[arg-type]
        threads_account_id=body.threads_account_id,
        ig_account_id=th_row.get("ig_account_id"),
        target=body.target,
        meta=body.meta,
    ))
    d = counter.as_dict()
    return AccountFunnelOut(**d)


@router.get("/funnel/summary", response_model=FunnelSummaryOut)
async def funnel_summary(request: Request) -> FunnelSummaryOut:
    s = _tracker(request).summary()
    return FunnelSummaryOut(
        totals=AccountFunnelOut(**s["totals"]),
        accounts=s["accounts"],
        top=[AccountFunnelOut(**r) for r in s["top"]],
        ring_size=s["ring_size"],
    )


@router.get("/funnel/{account_id}", response_model=AccountFunnelOut)
async def funnel_for_account(account_id: str, request: Request) -> AccountFunnelOut:
    _row(request, account_id)  # existence check
    return AccountFunnelOut(**_tracker(request).for_account(account_id).as_dict())


class PlanEntryOut(BaseModel):
    account_id: str
    kind:       str
    target:     str
    body:       str
    reason:     str


class OrchestratorOut(BaseModel):
    running:        bool
    last_run_at:    Optional[str] = None
    total_runs:     int
    total_enqueued: int
    last_plan:      list[PlanEntryOut]


def _orchestrator(request: Request):
    o = getattr(request.app.state, "threads_orchestrator", None)
    if o is None:
        raise HTTPException(status_code=503, detail="Orchestrator not attached.")
    return o


@router.get("/orchestrator/status", response_model=OrchestratorOut)
async def orchestrator_status(request: Request) -> OrchestratorOut:
    o = _orchestrator(request)
    return OrchestratorOut(
        running=o.running(),
        last_run_at=o.stats.last_run_at,
        total_runs=o.stats.total_runs,
        total_enqueued=o.stats.total_enqueued,
        last_plan=[PlanEntryOut(account_id=p.account_id, kind=p.kind,
                                 target=p.target, body=p.body, reason=p.reason)
                   for p in o.stats.last_plan],
    )


@router.post("/orchestrator/run", response_model=OrchestratorOut)
async def orchestrator_run(request: Request) -> OrchestratorOut:
    """Trigger one planner tick now (does not restart the loop)."""
    o = _orchestrator(request)
    await o.run_once()
    return await orchestrator_status(request)


@router.post("/orchestrator/start", response_model=OrchestratorOut)
async def orchestrator_start(request: Request) -> OrchestratorOut:
    o = _orchestrator(request)
    await o.start()
    return await orchestrator_status(request)


@router.post("/orchestrator/stop", response_model=OrchestratorOut)
async def orchestrator_stop(request: Request) -> OrchestratorOut:
    o = _orchestrator(request)
    await o.stop()
    return await orchestrator_status(request)


@router.get("/funnel/activity/stream", response_model=FunnelActivityOut)
async def funnel_activity(
    request: Request, limit: int = 50,
    threads_account_id: Optional[str] = None,
) -> FunnelActivityOut:
    rows = _tracker(request).recent(
        limit=max(1, min(limit, 500)),
        threads_account_id=threads_account_id,
    )
    return FunnelActivityOut(events=rows, count=len(rows))


class IGEventIn(BaseModel):
    ig_account_id: str
    post_id:       str = ""
    caption:       str = ""
    source:        str = "manual"


class IGEventOut(BaseModel):
    published:  bool
    post_id:    str
    outcomes:   list[dict]


class BridgeStatsOut(BaseModel):
    events_in:   int
    replies_out: int
    skipped_budget:  int
    skipped_no_link: int
    skipped_gate:    int
    last_action_id:  Optional[str] = None


@router.post("/ig-event", response_model=IGEventOut)
async def ig_event(body: IGEventIn, request: Request) -> IGEventOut:
    """
    Publish an IG post event onto the bus. Any Threads subscriber picks
    it up and may enqueue a cross-post reply. Returns a per-subscriber
    outcome list so the caller sees exactly what each handler did.
    """
    bus = getattr(request.app.state, "ig_event_bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="IG event bus not attached.")
    event = IGPostEvent(
        ig_account_id=body.ig_account_id,
        post_id=body.post_id or f"sim-{uuid.uuid4().hex[:10]}",
        caption=body.caption, source=body.source,
    )
    outcomes = await bus.publish(event)
    return IGEventOut(published=True, post_id=event.post_id, outcomes=outcomes)


@router.get("/ig-events", response_model=list[dict])
async def ig_events_recent(request: Request, limit: int = 50) -> list[dict]:
    bus = getattr(request.app.state, "ig_event_bus", None)
    if bus is None:
        return []
    return bus.recent(limit=max(1, min(limit, 200)))


@router.get("/bridge/status", response_model=BridgeStatsOut)
async def bridge_status(request: Request) -> BridgeStatsOut:
    bridge = getattr(request.app.state, "ig_bridge", None)
    if bridge is None:
        return BridgeStatsOut(events_in=0, replies_out=0, skipped_budget=0,
                              skipped_no_link=0, skipped_gate=0)
    s = bridge.stats
    return BridgeStatsOut(
        events_in=s.events_in, replies_out=s.replies_out,
        skipped_budget=s.skipped_budget, skipped_no_link=s.skipped_no_link,
        skipped_gate=s.skipped_gate, last_action_id=s.last_action_id,
    )


@router.post("/accounts/{account_id}/warmup", response_model=dict)
async def set_warmup(account_id: str, day: int, request: Request) -> dict:
    """Dev helper: set an IG or Threads account's warmup_day directly."""
    row = _acc_store(request).get(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="account not found")
    row["warmup_day"] = max(0, min(int(day), 28))
    return {"account_id": account_id, "warmup_day": row["warmup_day"],
            "platform": row.get("platform")}


class AuditCheckOut(BaseModel):
    key:    str
    label:  str
    status: str
    detail: str
    metrics: dict


class AuditReportOut(BaseModel):
    ran_at:      str
    n_personas:  int
    pass_count:  int
    warn_count:  int
    fail_count:  int
    duration_ms: float
    passed:      bool
    checks:      list[AuditCheckOut]


@router.post("/audit/run", response_model=AuditReportOut)
async def audit_run(request: Request, n: int = 10_000) -> AuditReportOut:
    """
    Run the Threads Monte Carlo audit. CLAUDE.md requires an audit-harness
    test case covering every distribution any new primitive introduces;
    this endpoint is how CI (and this UI) runs it. Default N=10k matches
    the fleet-scale audit gate.
    """
    import asyncio
    from ...platforms.threads_audit import run_audit
    # Hop to a thread so the audit CPU doesn't block the loop at N=10k+.
    n_clamped = max(100, min(int(n), 50_000))
    report = await asyncio.to_thread(run_audit, n_clamped)
    d = report.as_dict()
    request.app.state.threads_last_audit = d
    return AuditReportOut(**d)


@router.get("/audit/last", response_model=Optional[AuditReportOut])
async def audit_last(request: Request):
    d = getattr(request.app.state, "threads_last_audit", None)
    return d


@router.post("/cross-post", response_model=CrossPostOut)
async def cross_post(body: CrossPostIn, request: Request) -> CrossPostOut:
    """
    Enqueue a Threads reply from the Threads account linked to an IG account.

    This is the whole reason Threads ships first in Phase 2: an IG post goes
    out, the linked Threads account replies in the discussion thread, and
    the reply is where the bio link / funnel lives. If the IG parent hasn't
    reached day 7 of its own warming, we 409 — same guard as a raw reply.
    """
    store = _acc_store(request)
    ig = store.get(body.ig_account_id)
    if ig is None or ig.get("platform") != "instagram":
        raise HTTPException(status_code=404, detail="IG account not found.")
    # Find the Threads account linked to this IG account.
    th = next((r for r in store.values()
               if r.get("platform") == "threads"
               and r.get("ig_account_id") == body.ig_account_id), None)
    if th is None:
        raise HTTPException(
            status_code=409,
            detail=f"No Threads account linked to {body.ig_account_id!r}. "
                   "Call /api/platforms/threads/link first.",
        )
    out = _enqueue(request, th, "reply", body.target, body.reply_body)
    return CrossPostOut(
        queued=out.queued, action_id=out.action_id,
        threads_account_id=th["account_id"], ig_account_id=body.ig_account_id,
    )


# ---------------------------------------------------------------------------
# Health / shadowban detector
# ---------------------------------------------------------------------------


class HealthSignalsOut(BaseModel):
    reply_posted:          int
    profile_view:          int
    bio_link_click:        int
    subscribe:             int
    reply_to_view_rate:    float
    dispatched:            int
    failed:                int
    dispatch_failure_rate: float
    queued_pending:        int
    stalled_count:         int
    warmup_day:            int
    hours_since_dispatch:  float


class AccountHealthOut(BaseModel):
    account_id:  str
    status:      str
    score:       int
    flags:       list[str]
    signals:     HealthSignalsOut
    computed_at: str


class HealthRollupOut(BaseModel):
    healthy:       int
    watch:         int
    at_risk:       int
    shadowbanned:  int
    total:         int
    last_scan_at:  Optional[str] = None
    total_scans:   int


class HealthSummaryOut(BaseModel):
    rollup:      HealthRollupOut
    at_risk:     list[AccountHealthOut]
    flag_counts: dict


def _health(request: Request):
    h = getattr(request.app.state, "threads_health", None)
    if h is None:
        raise HTTPException(status_code=503, detail="Health monitor not attached.")
    return h


@router.post("/health/scan", response_model=HealthSummaryOut)
async def health_scan(request: Request) -> HealthSummaryOut:
    """Recompute health for every active Threads account."""
    h = _health(request)
    h.scan_all()
    return HealthSummaryOut(**h.summary())


@router.get("/health/summary", response_model=HealthSummaryOut)
async def health_summary(request: Request) -> HealthSummaryOut:
    h = _health(request)
    return HealthSummaryOut(**h.summary())


@router.get("/health/{account_id}", response_model=AccountHealthOut)
async def health_for(account_id: str, request: Request) -> AccountHealthOut:
    h = _health(request)
    store = _acc_store(request)
    row = store.get(account_id)
    if row is None or row.get("platform") != "threads":
        raise HTTPException(status_code=404, detail="Threads account not found.")
    return AccountHealthOut(**h.compute(row).as_dict())


class HealthSimulateIn(BaseModel):
    account_id: str
    scenario:   str = "funnel_ghost"    # funnel_ghost | reply_sink | dispatch_fail | queue_stall


@router.post("/health/simulate", response_model=AccountHealthOut)
async def health_simulate(body: HealthSimulateIn, request: Request) -> AccountHealthOut:
    """
    Dev helper: synthesize events that should trip a specific health
    flag, then recompute. Lets the UI prove the detector catches each
    failure mode without waiting for real decay.
    """
    from ...platforms.threads_funnel import FunnelEvent
    h = _health(request)
    tracker = _tracker(request)
    store = _acc_store(request)
    row = store.get(body.account_id)
    if row is None or row.get("platform") != "threads":
        raise HTTPException(status_code=404, detail="Threads account not found.")

    if body.scenario == "funnel_ghost":
        # 25 replies, zero downstream — the ghost pattern.
        for _ in range(25):
            tracker.record(FunnelEvent(kind="reply_posted",
                                        threads_account_id=body.account_id))
    elif body.scenario == "reply_sink":
        # 20 replies but only 1 view — low rate, below floor.
        for _ in range(20):
            tracker.record(FunnelEvent(kind="reply_posted",
                                        threads_account_id=body.account_id))
        tracker.record(FunnelEvent(kind="profile_view",
                                    threads_account_id=body.account_id))
    elif body.scenario == "dispatch_fail":
        q = _pending_queue(request)
        for _ in range(7):
            q.append({"account_id": body.account_id, "status": "failed",
                      "kind": "reply", "date": datetime.now(timezone.utc).date().isoformat()})
        for _ in range(5):
            q.append({"account_id": body.account_id, "status": "dispatched",
                      "kind": "reply", "date": datetime.now(timezone.utc).date().isoformat(),
                      "dispatched_at": datetime.now(timezone.utc).isoformat()})
    elif body.scenario == "queue_stall":
        q = _pending_queue(request)
        stale = (datetime.now(timezone.utc)
                 .replace(microsecond=0)).isoformat().replace("+00:00", "Z")
        # Queued two hours ago — qualifies as stalled.
        from datetime import timedelta
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        for _ in range(6):
            q.append({"account_id": body.account_id, "status": "queued",
                      "kind": "reply", "date": datetime.now(timezone.utc).date().isoformat(),
                      "queued_at": old})
    else:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {body.scenario}")
    return AccountHealthOut(**h.compute(row).as_dict())


# ---------------------------------------------------------------------------
# Recovery agent
# ---------------------------------------------------------------------------


class RecoveryRecordOut(BaseModel):
    account_id:              str
    phase:                   str
    strikes:                 int
    entered_at:              str
    cool_down_until:         str
    original_warmup_day:     int
    rewarm_baseline_replies: int
    rewarm_actions_observed: int
    graduated_at:            Optional[str] = None
    retired_at:              Optional[str] = None
    notes:                   list[str]


class RecoveryStatsOut(BaseModel):
    total_enrolled:  int
    total_graduated: int
    total_retired:   int
    cooling_down:    int
    rewarming:       int
    last_tick_at:    Optional[str] = None
    total_ticks:     int


class RecoverySummaryOut(BaseModel):
    running: bool
    stats:   RecoveryStatsOut
    config:  dict
    records: list[RecoveryRecordOut]


def _recovery(request: Request):
    r = getattr(request.app.state, "threads_recovery", None)
    if r is None:
        raise HTTPException(status_code=503, detail="Recovery agent not attached.")
    return r


@router.get("/recovery/status", response_model=RecoverySummaryOut)
async def recovery_status(request: Request) -> RecoverySummaryOut:
    r = _recovery(request)
    return RecoverySummaryOut(**r.summary())


@router.post("/recovery/tick", response_model=RecoverySummaryOut)
async def recovery_tick(request: Request) -> RecoverySummaryOut:
    """Trigger one recovery tick now (does not restart the loop)."""
    r = _recovery(request)
    _health(request).scan_all()
    r.tick()
    return RecoverySummaryOut(**r.summary())


@router.post("/recovery/{account_id}/graduate", response_model=Optional[RecoveryRecordOut])
async def recovery_graduate(account_id: str, request: Request):
    """Dev override: graduate an account back to active now."""
    r = _recovery(request)
    rec = r.force_graduate(account_id)
    return rec.as_dict() if rec else None


@router.post("/recovery/{account_id}/skip-cooldown", response_model=Optional[RecoveryRecordOut])
async def recovery_skip_cooldown(account_id: str, request: Request):
    """Dev override: jump straight to the rewarm phase."""
    r = _recovery(request)
    rec = r.force_rewarm(account_id)
    return rec.as_dict() if rec else None


# ---------------------------------------------------------------------------
# Persistence status
# ---------------------------------------------------------------------------


class PersistenceOut(BaseModel):
    enabled:          bool
    funnel_events:    int
    health_snapshots: int
    recovery_records: int
    ig_events:        int
    error:            Optional[bool] = None


# ---------------------------------------------------------------------------
# Fleet rebalancer
# ---------------------------------------------------------------------------


class RebalancerSummaryOut(BaseModel):
    running:    bool
    stats:      dict
    thresholds: dict
    snapshot:   Optional[dict] = None
    throttles:  dict
    events:     list[dict]


def _rebalancer(request: Request):
    r = getattr(request.app.state, "threads_rebalancer", None)
    if r is None:
        raise HTTPException(status_code=503, detail="Rebalancer not attached.")
    return r


@router.get("/rebalancer/status", response_model=RebalancerSummaryOut)
async def rebalancer_status(request: Request) -> RebalancerSummaryOut:
    return RebalancerSummaryOut(**_rebalancer(request).summary())


@router.post("/rebalancer/tick", response_model=RebalancerSummaryOut)
async def rebalancer_tick(request: Request) -> RebalancerSummaryOut:
    """Trigger one rebalancer classification now."""
    rb = _rebalancer(request)
    _health(request).scan_all()         # refresh rollup first
    rb.tick()
    return RebalancerSummaryOut(**rb.summary())


# ---------------------------------------------------------------------------
# Active shadowban probes
# ---------------------------------------------------------------------------


class ProbeResultOut(BaseModel):
    probe_id:    str
    kind:        str
    account_id:  str
    searcher_id: str
    found:       bool
    detail:      str
    checked_at:  str


class ProbeSummaryOut(BaseModel):
    running:     bool
    stats:       dict
    tick_sec:    float
    recent:      list[ProbeResultOut]


def _probes(request: Request):
    p = getattr(request.app.state, "threads_probes", None)
    if p is None:
        raise HTTPException(status_code=503, detail="Probe scheduler not attached.")
    return p


@router.get("/probes/status", response_model=ProbeSummaryOut)
async def probes_status(request: Request, limit: int = 30) -> ProbeSummaryOut:
    p = _probes(request)
    return ProbeSummaryOut(
        running=p.running(), stats=p.stats.as_dict(),
        tick_sec=p.tick_sec,
        recent=[ProbeResultOut(**r)
                for r in p.recent(limit=max(1, min(limit, 200)))],
    )


@router.post("/probes/tick", response_model=dict)
async def probes_tick(request: Request) -> dict:
    """Run one probe sweep now (does not restart the loop)."""
    p = _probes(request)
    _health(request).scan_all()         # refresh health first for searcher-pool filter
    moved = await p.tick()
    return {"moved": moved, "stats": p.stats.as_dict()}


@router.get("/probes/{account_id}", response_model=list[ProbeResultOut])
async def probes_for(account_id: str, request: Request,
                      limit: int = 10) -> list[ProbeResultOut]:
    p = _probes(request)
    return [ProbeResultOut(**r)
            for r in p.for_account(account_id, limit=max(1, min(limit, 50)))]


# ---------------------------------------------------------------------------
# Agent runs (ThreadsAgent — CLAUDE.md agent-audit frame)
# ---------------------------------------------------------------------------


class AgentRunOut(BaseModel):
    run_id:     str
    agent_name: str
    account_id: str
    kind:       str
    status:     str
    iterations: int
    cost_usd:   float
    started_at: str
    ended_at:   Optional[str] = None
    error:      str
    audit:      list[dict]


class AgentSummaryOut(BaseModel):
    config: dict
    runs:   dict
    recent: list[AgentRunOut]


def _agent(request: Request):
    a = getattr(request.app.state, "threads_agent", None)
    if a is None:
        raise HTTPException(status_code=503, detail="Threads agent not attached.")
    return a


def _agent_ring(request: Request):
    r = getattr(request.app.state, "threads_agent_ring", None)
    if r is None:
        raise HTTPException(status_code=503, detail="Agent runs ring not attached.")
    return r


@router.get("/agent/runs", response_model=AgentSummaryOut)
async def agent_runs(request: Request, limit: int = 30,
                      account_id: Optional[str] = None) -> AgentSummaryOut:
    a = _agent(request)
    ring = _agent_ring(request)
    cfg = {
        "name":                  a.config.name,
        "max_iterations":        a.config.max_iterations,
        "max_usd_per_run":       a.config.max_usd_per_run,
        "max_usd_per_session":   a.config.max_usd_per_session,
        "allowed_tools":         list(a.config.allowed_tools),
        "confirmation_required": list(a.config.confirmation_required_for),
    }
    return AgentSummaryOut(
        config=cfg,
        runs=ring.summary(),
        recent=[AgentRunOut(**r)
                for r in ring.recent(limit=max(1, min(limit, 200)),
                                      account_id=account_id)],
    )


@router.get("/persistence/status", response_model=PersistenceOut)
async def persistence_status(request: Request) -> PersistenceOut:
    """
    Row counts across every Threads durable table, or enabled=false
    when the DB pool is unavailable. Lets the UI show at a glance
    whether a restart will keep history.
    """
    repo = getattr(request.app.state, "threads_repo", None)
    if repo is None:
        return PersistenceOut(enabled=False, funnel_events=0,
                              health_snapshots=0, recovery_records=0,
                              ig_events=0)
    return PersistenceOut(**(await repo.summary()))


# ---------------------------------------------------------------------------
# Per-account dossier — everything about one Threads account in one payload
# ---------------------------------------------------------------------------


class DossierOut(BaseModel):
    account:    dict
    budget:     dict
    curve:      list[dict]
    funnel:     dict
    health:     Optional[dict] = None
    recovery:   Optional[dict] = None
    queue:      list[dict]
    bridge_events: list[dict]


@router.get("/accounts/{account_id}/dossier", response_model=DossierOut)
async def account_dossier(account_id: str, request: Request) -> DossierOut:
    """
    One-shot aggregate for the drill page. Returns everything the UI
    needs to render /threads/[id] without 7 parallel fetches.
    """
    store = _acc_store(request)
    row = store.get(account_id)
    if row is None or row.get("platform") != "threads":
        raise HTTPException(status_code=404, detail="Threads account not found.")

    ig = store.get(row.get("ig_account_id", ""))
    warmup_day = int(row.get("warmup_day", 1))
    budget = threads_mod.budget_for(account_id, warmup_day)
    curve = [b.as_dict() for b in threads_mod.budgets_across_curve(account_id)]

    funnel = _tracker(request).for_account(account_id).as_dict()

    health_obj = None
    h = getattr(request.app.state, "threads_health", None)
    if h is not None:
        health_obj = h.compute(row).as_dict()

    recovery_obj = None
    r = getattr(request.app.state, "threads_recovery", None)
    if r is not None:
        rec = r.for_account(account_id)
        if rec is not None:
            recovery_obj = rec.as_dict()

    queue = [e for e in _pending_queue(request)
             if e.get("account_id") == account_id]

    bus = getattr(request.app.state, "ig_event_bus", None)
    bridge_events: list[dict] = []
    if bus is not None and ig is not None:
        bridge_events = [e for e in bus.recent(limit=200)
                         if e.get("ig_account_id") == row.get("ig_account_id")]

    account = {
        "account_id":     row["account_id"],
        "handle":         row.get("handle", ""),
        "platform":       row.get("platform"),
        "status":         row.get("status", "active"),
        "ig_account_id":  row.get("ig_account_id", ""),
        "ig_handle":      (ig or {}).get("username", ""),
        "ig_warmup_day":  int((ig or {}).get("warmup_day", 0)),
        "linked_at":      row.get("linked_at", ""),
        "warmup_day":     warmup_day,
        "can_cross_post": threads_mod.can_cross_post(ig or {}),
    }
    return DossierOut(
        account=account,
        budget=budget.as_dict(),
        curve=curve,
        funnel=funnel,
        health=health_obj,
        recovery=recovery_obj,
        queue=queue,
        bridge_events=bridge_events,
    )

