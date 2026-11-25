"""
Phantom Fleet FastAPI application.

Single responsibility: wire the app together.
    - CORSMiddleware (localhost:3016 + configurable via PHANTOM_ALLOWED_ORIGINS)
    - Lifespan: initialise the PhoneFleet singleton, log startup/shutdown
    - Router registration: fleet, accounts, capacity, agents, schedule
    - /health liveness probe

Everything that *executes* platform actions flows through the agent mesh —
the API never calls IG/Reddit/etc directly. That constraint lives in the
provisioner (proxy gate) and the agent dispatch layer (tool allowlist).

Start with:
    uvicorn phantom_fleet.api.app:app --port 8000 --reload
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
except Exception:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import fleet, accounts, capacity, agents, schedule, funnel, ig_growth, phase1, phase2
from .routes import fleet_mirror as fleet_mirror_routes
from .routes import proxy_pool as proxy_pool_routes
from .routes import threads as threads_routes
from .routes import instagram as instagram_routes
from .routes import replacement as replacement_routes
from .routes import cluster_monitor as cluster_monitor_routes
from .routes import content_vault as content_vault_routes
from .routes import ops as ops_routes
from .routes import hq_bridge as hq_bridge_routes
from .routes import ig_intelligence as ig_intelligence_routes
from .routes import comment_pods as comment_pods_routes
from .routes import gmail_reddit_pipeline as gmail_reddit_pipeline_routes
from .routes import groups as groups_routes
from .routes import warmup as warmup_routes
from .routes import scraper as scraper_routes
from .routes import strategy as strategy_routes
from .routes import staffroom_missions as staffroom_routes
from .routes import simulate as simulate_routes
from .routes import time_machine as time_machine_routes
from .routes import scheduler_pro as scheduler_pro_routes
from .routes import ai_agent_routes
from .routes import pods as pods_routes
from .routes import ab_tests as ab_tests_routes
from .routes import settings as settings_routes
from .routes import activity_log as activity_log_routes
from .routes import profiles as profiles_routes
from .routes import trending as trending_routes
from .routes import learning as learning_routes
from .routes import reddit as reddit_routes

log = logging.getLogger("phantom_fleet.api")


# ---------------------------------------------------------------------------
# App-level state (dependency-injected into routes via request.app.state)
# ---------------------------------------------------------------------------

class AppState:
    """Lightweight singleton that routes can pull from app.state."""

    def __init__(self) -> None:
        from ..core.phone_controller import PhoneFleet
        self.fleet = PhoneFleet()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    from ..core.ops_brain import PhantomFleetOpsBrain
    from ..core.fleet_scheduler import FleetScheduler
    from ..core.hq_bridge import HQBridge

    log.info("Phantom Fleet API starting up")

    # Boot DB pool and run pending migrations
    from ..db.connection import get_pool, run_migrations, close_pool
    try:
        db_pool = await get_pool()
        migrated = await run_migrations()
        if migrated:
            log.info("Migrations applied: %s", migrated)
        log.info("DB pool ready")
    except Exception as exc:
        log.warning("DB unavailable (%s) — running without DB persistence", exc)
        db_pool = None

    ctx = AppState()
    app.state.ctx = ctx
    app.state.db_pool = db_pool

    # Attach Phantom Fleet Mirror bridge if PHANTOM_MIRROR_URL is set.
    # The fleet prefers the mirror for scan() and falls back to local adb.
    from ..mirror_bridge import mirror_bridge_from_env
    mirror = mirror_bridge_from_env()
    if mirror is not None:
        reachable = await mirror.start()
        if reachable:
            mirror.start_event_stream()
            ctx.fleet.set_mirror(mirror)
        app.state.mirror = mirror
    else:
        app.state.mirror = None
        log.info("PHANTOM_MIRROR_URL not set — using local adb for discovery")

    # Attempt to connect Redis (optional — ops brain works without it)
    redis_client = None
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        import aioredis  # type: ignore[import]
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        log.info("Redis connected: %s", redis_url)
    except Exception as exc:
        log.warning("Redis unavailable (%s) — ops brain will run without pub/sub", exc)

    # Boot proxy pool — provider-agnostic, always editable.
    # Priority: PHANTOM_PROXY_POOL (any vendor) → legacy vendor env vars
    # (IPROYAL_ISP_PROXIES, SMARTPROXY_PROXIES) migrated into a GenericProxyPool
    # for continuity. Empty pool is fine — UI can add proxies at runtime.
    from ..proxy import (
        generic_pool_from_env, smartproxy_pool_from_env,
        isp_pool_from_env, GenericProxyPool,
    )
    pool: GenericProxyPool = generic_pool_from_env() or GenericProxyPool()
    if len(pool._pool) == 0:
        legacy = smartproxy_pool_from_env() or isp_pool_from_env()
        if legacy is not None:
            for p in legacy._pool:
                pool._pool.append(p)
            log.info("Migrated %d legacy proxies into generic pool", len(pool._pool))
    app.state.proxy = pool
    log.info("Proxy pool ready: %s", pool.fleet_status())

    # Daily LLM cap from env
    daily_llm_cap = float(os.getenv("PHANTOM_DAILY_LLM_CAP_USD", "25.0"))

    # Boot ops brain
    brain = PhantomFleetOpsBrain(
        fleet=ctx.fleet,
        redis=redis_client,
        db_pool=db_pool,
        daily_llm_cap_usd=daily_llm_cap,
    )
    app.state.brain = brain
    await brain.start()

    # Boot fleet scheduler
    scheduler = FleetScheduler()
    app.state.scheduler = scheduler

    # Boot HQ bridge
    hq_bridge = HQBridge(fleet=ctx.fleet, db_pool=db_pool)
    app.state.hq_bridge = hq_bridge

    # Boot Scheduler Executor (fires Scheduler Pro posts on time)
    if db_pool is not None:
        from ..core.scheduler_executor import SchedulerExecutor
        sched_executor = SchedulerExecutor(db_pool)
        await sched_executor.start()
        app.state.scheduler_executor = sched_executor
    else:
        app.state.scheduler_executor = None

    # Boot Engagement Executor (60-second loop: story/like/follow/unfollow/comment/dm)
    if db_pool is not None:
        from ..core.engagement_executor import EngagementExecutor
        engagement_executor = EngagementExecutor(db_pool)
        await engagement_executor.start()
        app.state.engagement_executor = engagement_executor
    else:
        app.state.engagement_executor = None

    log.info("OpsBrain, FleetScheduler, HQBridge, SchedulerExecutor, EngagementExecutor initialised")

    # Threads executor + funnel tracker. Executor drains the pending
    # queue through the mirror bridge; tracker records reply_posted +
    # downstream profile_view / bio_link_click / subscribe events.
    from ..platforms.threads_executor import ThreadsExecutor
    from ..platforms.threads_funnel import ThreadsFunnelTracker
    def _threads_queue_getter():
        q = getattr(app.state, "threads_queue", None)
        if q is None:
            q = []
            app.state.threads_queue = q
        return q
    # Persistence: optional, no-op when DB pool is None. Each in-memory
    # tracker/agent gets a write-through to this repo; restore_* runs
    # before the agents' loops start so they rehydrate state.
    from ..db.repositories.threads_persistence import ThreadsRepository
    threads_repo = ThreadsRepository(db_pool)
    app.state.threads_repo = threads_repo

    threads_funnel = ThreadsFunnelTracker(repo=threads_repo)
    # Replay durable counters so a restart doesn't zero attribution.
    if threads_repo.enabled:
        try:
            snapshot = await threads_repo.restore_funnel_counters()
            threads_funnel.restore_counters(snapshot)
        except Exception:
            log.exception("Threads funnel restore failed")
    threads_exec = ThreadsExecutor(
        fleet=ctx.fleet,
        mirror=app.state.mirror,
        queue_getter=_threads_queue_getter,
        funnel=threads_funnel,
    )
    await threads_exec.start()
    app.state.threads_funnel = threads_funnel
    app.state.threads_executor = threads_exec

    # Orchestrator plans actions into the queue every tick based on
    # per-account budget + funnel performance.
    from ..platforms.threads_orchestrator import ThreadsOrchestrator
    from .routes.accounts import _store as _accounts_store
    # Health monitor: funnel-decay / dispatch-failure / queue-stall scorer.
    # Orchestrator reads it on every tick to skip shadowbanned accounts
    # and dampen the share given to at_risk ones.
    from ..platforms.threads_health import ThreadsHealthMonitor
    threads_health = ThreadsHealthMonitor(
        accounts_store_getter=_accounts_store,
        queue_getter=_threads_queue_getter,
        funnel=threads_funnel,
        repo=threads_repo,
    )
    app.state.threads_health = threads_health

    # Active shadowban probes — searcher-side look-ups that detect
    # search-hidden / hashtag-ghosted / reply-hidden before the funnel
    # even has time to decay.
    from ..platforms.threads_probes import ThreadsProbeScheduler
    threads_probes = ThreadsProbeScheduler(
        accounts_store_getter=_accounts_store,
        health_monitor=threads_health,
        tick_sec=90.0,
    )
    threads_health.set_probes(threads_probes)
    await threads_probes.start()
    app.state.threads_probes = threads_probes

    # Recovery agent: enrolls shadowbanned accounts, pauses them, runs a
    # cool-down + rewarm loop, graduates or retires on health signal.
    from ..platforms.threads_recovery import ThreadsRecoveryAgent
    threads_recovery = ThreadsRecoveryAgent(
        accounts_store_getter=_accounts_store,
        health=threads_health,
        funnel=threads_funnel,
        tick_sec=30.0,
        repo=threads_repo,
    )
    if threads_repo.enabled:
        try:
            threads_recovery.restore_records(
                await threads_repo.restore_recovery_records())
        except Exception:
            log.exception("Threads recovery restore failed")
    await threads_recovery.start()
    app.state.threads_recovery = threads_recovery

    # ThreadsAgent — wraps every dispatch in the CLAUDE.md agent frame
    # (allowlist, iteration cap, cost caps, audit sink). Orchestrator
    # routes planned actions through this; raw /post /reply etc. still
    # go through the direct queue append for dev-tool ergonomics.
    from ..agents.threads_agent import (
        ThreadsAgent, AgentRunsRing, build_tool_registry,
    )
    from ..platforms import threads as _threads_mod
    threads_agent_ring = AgentRunsRing()
    threads_agent = ThreadsAgent(
        tool_registry=build_tool_registry(
            _threads_mod, _accounts_store, _threads_queue_getter),
        audit_sink=lambda e: None,          # Per-run audit collected in ring.
    )
    app.state.threads_agent = threads_agent
    app.state.threads_agent_ring = threads_agent_ring

    # Fleet rebalancer — upstream throttle when shadowban rate / probe
    # hidden rate / enrollment burst cross thresholds. Hooks into both
    # orchestrator.plan_per_tick_multiplier and /link gating.
    from ..platforms.threads_rebalancer import ThreadsFleetRebalancer
    def _rebalancer_alert_sink(evt: dict) -> None:
        # Lightweight alert sink — writes to OpsBrain if present; real wire
        # into HQ / Slack goes here later.
        log.warning("REBALANCER ALERT %s: %s", evt.get("topic"), evt.get("reason"))
    threads_rebalancer = ThreadsFleetRebalancer(
        health=threads_health,
        probes=threads_probes,
        recovery=threads_recovery,
        tick_sec=20.0,
        alert_sink=_rebalancer_alert_sink,
    )
    app.state.threads_rebalancer = threads_rebalancer
    await threads_rebalancer.start()

    threads_orch = ThreadsOrchestrator(
        accounts_store_getter=_accounts_store,
        queue_getter=_threads_queue_getter,
        funnel=threads_funnel,
        tick_sec=60.0,
        health=threads_health,
        agent=threads_agent,
        agent_ring=threads_agent_ring,
        rebalancer=threads_rebalancer,
    )
    await threads_orch.start()
    app.state.threads_orchestrator = threads_orch

    # IG → Threads auto cross-post bus. The bridge subscribes and enqueues
    # a reply from the linked Threads account whenever IG posts.
    from ..platforms.ig_bridge import IGEventBus, ThreadsCrossPostBridge
    ig_bus = IGEventBus(repo=threads_repo)
    if threads_repo.enabled:
        try:
            ig_bus.restore_events(await threads_repo.recent_ig_events(limit=200))
        except Exception:
            log.exception("IG event bus restore failed")
    ig_bridge = ThreadsCrossPostBridge(
        accounts_store_getter=_accounts_store,
        queue_getter=_threads_queue_getter,
        funnel=threads_funnel,
    )
    ig_bus.subscribe(ig_bridge)
    app.state.ig_event_bus = ig_bus
    app.state.ig_bridge = ig_bridge

    # Instagram health / shadowban detector. Mirrors ThreadsHealthMonitor
    # but scored off the IG event bus + cross-post bridge counters.
    from ..platforms.instagram_health import InstagramHealthMonitor
    ig_health = InstagramHealthMonitor(
        accounts_store_getter=_accounts_store,
        ig_bus=ig_bus,
        bridge=ig_bridge,
    )
    app.state.ig_health = ig_health

    from ..platforms.instagram_funnel import InstagramFunnelTracker
    ig_funnel = InstagramFunnelTracker()
    app.state.ig_funnel = ig_funnel

    # Shared in-memory IG action queue — mirror of threads_queue.
    def _ig_queue_getter() -> list[dict]:
        q = getattr(app.state, "ig_queue", None)
        if q is None:
            q = []
            app.state.ig_queue = q
        return q
    app.state.ig_queue_getter = _ig_queue_getter

    # InstagramAgent — wraps every IG dispatch in the CLAUDE.md agent frame
    # (allowlist=5, max_iterations=3, max_usd_per_run=0.05, per-session=2.00).
    from ..agents.instagram_agent import (
        InstagramAgent, IGAgentRunsRing,
        build_tool_registry as _build_ig_tools,
    )
    from ..platforms import instagram as _ig_mod
    ig_agent_ring = IGAgentRunsRing()
    ig_agent = InstagramAgent(
        tool_registry=_build_ig_tools(_ig_mod, _accounts_store, _ig_queue_getter),
        audit_sink=lambda e: None,
    )
    app.state.ig_agent = ig_agent
    app.state.ig_agent_ring = ig_agent_ring

    # Instagram orchestrator — planner loop.
    from ..platforms.instagram_orchestrator import InstagramOrchestrator
    ig_orch = InstagramOrchestrator(
        accounts_store_getter=_accounts_store,
        queue_getter=_ig_queue_getter,
        funnel=ig_funnel,
        health=ig_health,
        tick_sec=60.0,
        agent=ig_agent,
        agent_ring=ig_agent_ring,
    )
    await ig_orch.start()
    app.state.ig_orchestrator = ig_orch

    # Instagram active shadowban probes — upstream detector feeding health.
    from ..platforms.instagram_probes import InstagramProbeScheduler
    ig_probes = InstagramProbeScheduler(
        accounts_store_getter=_accounts_store,
        health_monitor=ig_health,
        tick_sec=120.0,
    )
    ig_health.set_probes(ig_probes)
    await ig_probes.start()
    app.state.ig_probes = ig_probes

    # Instagram recovery agent — IG counterpart of ThreadsRecoveryAgent.
    from ..platforms.instagram_recovery import InstagramRecoveryAgent
    ig_recovery = InstagramRecoveryAgent(
        accounts_store_getter=_accounts_store,
        health=ig_health,
        ig_bus=ig_bus,
        tick_sec=30.0,
    )
    await ig_recovery.start()
    app.state.ig_recovery = ig_recovery

    # Instagram fleet rebalancer — IG counterpart of ThreadsFleetRebalancer.
    from ..platforms.instagram_rebalancer import InstagramFleetRebalancer
    def _ig_rebalancer_alert_sink(evt: dict) -> None:
        log.warning("IG REBALANCER ALERT %s: %s", evt.get("topic"), evt.get("reason"))
    ig_rebalancer = InstagramFleetRebalancer(
        health=ig_health,
        probes=ig_probes,
        recovery=ig_recovery,
        tick_sec=20.0,
        alert_sink=_ig_rebalancer_alert_sink,
    )
    ig_orch.rebalancer = ig_rebalancer           # late-bind into orchestrator
    await ig_rebalancer.start()
    app.state.ig_rebalancer = ig_rebalancer

    # Instagram proxy pool — provider-agnostic in-memory list the scheduler
    # draws from. Seeded from the generic ISP pool where host:port doubles
    # as proxy_id; country is parsed from the username's "country-XX" token
    # if present, else defaults to US.
    import re as _re
    def _seed_ig_proxy_pool() -> list[dict]:
        rows: list[dict] = []
        try:
            for p in getattr(pool, "_pool", []):
                m = _re.search(r"country-([A-Za-z]{2})", getattr(p, "username", "") or "")
                country = m.group(1).upper() if m else "US"
                rows.append({
                    "proxy_id": f"{p.host}:{p.port}",
                    "host":     p.host,
                    "port":     p.port,
                    "country":  country,
                    "label":    f"{p.host}:{p.port}/{country}",
                })
        except Exception:
            pass
        return rows
    app.state.ig_proxy_pool = _seed_ig_proxy_pool()
    def _ig_proxy_pool_getter() -> list[dict]:
        return app.state.ig_proxy_pool
    app.state.ig_proxy_pool_getter = _ig_proxy_pool_getter

    from ..platforms.instagram_proxy import InstagramProxyScheduler
    ig_proxy = InstagramProxyScheduler(
        accounts_store_getter=_accounts_store,
        proxy_pool_getter=_ig_proxy_pool_getter,
    )
    app.state.ig_proxy = ig_proxy

    # Instagram device-drift detector — catches mid-session fingerprint
    # shifts (persona-factory re-roll, phone flash/reroot, IG integrity
    # sweep forcing patch bump). Hysteretic: 2-scan trip streak.
    from ..platforms.instagram_drift import InstagramDriftDetector
    ig_drift = InstagramDriftDetector(accounts_store_getter=_accounts_store)
    app.state.ig_drift = ig_drift

    # Instagram identity pair-check scanner — fixes CLAUDE.md bugs #1 + #2.
    from ..platforms.instagram_identity import InstagramIdentityScanner
    ig_identity = InstagramIdentityScanner(accounts_store_getter=_accounts_store)
    app.state.ig_identity = ig_identity

    # Instagram DM flow — dedupe, template rotation, opt-out detection.
    from ..platforms.instagram_dm import InstagramDMFlow
    ig_dm = InstagramDMFlow(
        accounts_store_getter=_accounts_store,
        queue_getter=_ig_queue_getter,
        health=ig_health,
    )
    app.state.ig_dm = ig_dm

    # Instagram unfollow discipline — follow-back tracker + paced staged
    # unfollows to keep follow:follower ratios clean.
    from ..platforms.instagram_unfollow import InstagramUnfollowDiscipline
    ig_unfollow = InstagramUnfollowDiscipline(
        accounts_store_getter=_accounts_store,
        queue_getter=_ig_queue_getter,
        health=ig_health,
    )
    app.state.ig_unfollow = ig_unfollow

    # Instagram session manager — per-account login state, TTL, 2FA.
    from ..platforms.instagram_session import InstagramSessionManager
    ig_session = InstagramSessionManager(accounts_store_getter=_accounts_store)
    app.state.ig_session = ig_session

    # Staffroom integration — Staffroom is the system of record for missions,
    # assignments, and artifacts. Fleet keeps only the stable request-id ↔
    # mission-id mapping plus cached status. Base URL is env-controlled so the
    # pilot runs against local Staffroom and can swing to the Tailscale
    # staging URL once owner sign-in is unblocked.
    import os as _os
    from ..platforms.staffroom import StaffroomClient, StaffroomMissionStore
    _sf_base = _os.environ.get("STAFFROOM_BASE_URL", "http://127.0.0.1:4321")
    _sf_cookie = _os.environ.get("STAFFROOM_SESSION_COOKIE", "")
    _sf_bot = _os.environ.get("STAFFROOM_COO_BOT_ID", "bot-coo")
    app.state.staffroom = StaffroomMissionStore(
        client=StaffroomClient(_sf_base, session_cookie=_sf_cookie),
        coo_bot_id=_sf_bot,
        config_source="env",
    )

    # Optional cadence loop — stays off by default. Owner flips
    # STAFFROOM_CADENCE_LOOP=1 after the standing-grant approval in phase C.
    # Tick is cheap (one SQLite read per registered cadence) and the
    # dispatch is quantised to the interval window, so an extra tick on
    # restart cannot spawn duplicates.
    if _os.environ.get("STAFFROOM_CADENCE_LOOP") == "1":
        import asyncio as _asyncio
        _interval_s = int(_os.environ.get("STAFFROOM_CADENCE_TICK_SECONDS", "60"))
        async def _cadence_loop() -> None:
            while True:
                try:
                    app.state.staffroom.cadence_tick()
                except Exception as exc:  # noqa: BLE001
                    log.warning("staffroom cadence tick failed: %s", exc)
                await _asyncio.sleep(_interval_s)
        app.state.staffroom_cadence_task = _asyncio.create_task(_cadence_loop())
        log.info("staffroom cadence loop running (tick every %ds)", _interval_s)

    # Instagram checkpoint handler — classifies IG challenge screens and
    # routes them (self_resolve / operator_review / enroll_recovery /
    # retire). Fires a REBALANCER alert on burst.
    from ..platforms.instagram_checkpoint import InstagramCheckpointHandler
    def _checkpoint_burst_alert(evt: dict) -> None:
        log.warning("IG CHECKPOINT BURST %s: %s",
                    evt.get("topic"), evt.get("reason"))
    ig_checkpoint = InstagramCheckpointHandler(
        recovery=ig_recovery,
        rebalancer_alert=_checkpoint_burst_alert,
    )
    app.state.ig_checkpoint = ig_checkpoint
    # Bridge: 2FA and password_reset checkpoints flow into the session mgr
    _orig_observe = ig_checkpoint.observe
    def _observe_with_session(account_id: str, signature: str, *, kind_override=None):
        evt = _orig_observe(account_id, signature, kind_override=kind_override)
        if evt.kind == "two_factor_prompt":
            ig_session.mark_2fa_pending(account_id, note=evt.signature[:80])
        elif evt.kind == "password_change":
            ig_session.mark_password_reset(account_id, note=evt.signature[:80])
        elif evt.kind == "account_locked":
            ig_session.mark_locked(account_id, reason="checkpoint:account_locked")
        return evt
    ig_checkpoint.observe = _observe_with_session  # type: ignore[assignment]

    # Instagram engagement lattice — planned inter-account likes/story-views
    # inside hard safety caps (in/out degree, reciprocity, proxy diversity,
    # country affinity, health gate, chronotype gate).
    from ..platforms.instagram_lattice import InstagramEngagementLattice
    ig_lattice = InstagramEngagementLattice(
        accounts_store_getter=_accounts_store,
        queue_getter=_ig_queue_getter,
        health=ig_health,
        proxy=ig_proxy,
    )
    app.state.ig_lattice = ig_lattice

    # Instagram executor — drains ig_queue → mirror bridge → companion APK.
    from ..platforms.instagram_executor import InstagramExecutor
    ig_exec = InstagramExecutor(
        fleet=ctx.fleet,
        mirror=app.state.mirror,
        queue_getter=_ig_queue_getter,
        funnel=ig_funnel,
        session=ig_session,
        tick_sec=2.0,
    )
    await ig_exec.start()
    app.state.ig_executor = ig_exec

    log.info("ThreadsExecutor + funnel + orchestrator + IG bridge + IG health + IG recovery + IG rebalancer started")

    yield

    # Shutdown
    threads_orch = getattr(app.state, "threads_orchestrator", None)
    if threads_orch is not None:
        await threads_orch.stop()
    threads_recovery = getattr(app.state, "threads_recovery", None)
    if threads_recovery is not None:
        await threads_recovery.stop()
    threads_probes = getattr(app.state, "threads_probes", None)
    if threads_probes is not None:
        await threads_probes.stop()
    threads_rebalancer = getattr(app.state, "threads_rebalancer", None)
    if threads_rebalancer is not None:
        await threads_rebalancer.stop()
    ig_recovery = getattr(app.state, "ig_recovery", None)
    if ig_recovery is not None:
        await ig_recovery.stop()
    ig_probes = getattr(app.state, "ig_probes", None)
    if ig_probes is not None:
        await ig_probes.stop()
    ig_orch = getattr(app.state, "ig_orchestrator", None)
    if ig_orch is not None:
        await ig_orch.stop()
    ig_rebalancer = getattr(app.state, "ig_rebalancer", None)
    if ig_rebalancer is not None:
        await ig_rebalancer.stop()
    ig_exec = getattr(app.state, "ig_executor", None)
    if ig_exec is not None:
        await ig_exec.stop()
    threads_exec = getattr(app.state, "threads_executor", None)
    if threads_exec is not None:
        await threads_exec.stop()
    if app.state.engagement_executor is not None:
        await app.state.engagement_executor.stop()
    if app.state.scheduler_executor is not None:
        await app.state.scheduler_executor.stop()
    await brain.stop()
    await close_pool()
    if redis_client is not None:
        try:
            await redis_client.close()
        except Exception:
            pass
    if app.state.mirror is not None:
        try:
            await app.state.mirror.close()
        except Exception:
            log.warning("mirror bridge close raised", exc_info=True)
    log.info("Phantom Fleet API shutting down")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    allowed_origins_raw = os.getenv(
        "PHANTOM_ALLOWED_ORIGINS",
        "http://localhost:3016",
    )
    allowed_origins = [o.strip() for o in allowed_origins_raw.split(",") if o.strip()]

    application = FastAPI(
        title="Phantom Fleet API",
        description="Invisible automation at fleet scale. A Scaler Pro product.",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    application.include_router(fleet.router,    prefix="/api/fleet",     tags=["fleet"])
    application.include_router(phase1.router,   prefix="/api/phase1",    tags=["phase1"])
    application.include_router(phase2.router,   prefix="/api/phase2",    tags=["phase2"])
    application.include_router(proxy_pool_routes.router, prefix="/api/proxy", tags=["proxy"])
    application.include_router(threads_routes.router, prefix="/api/platforms/threads", tags=["threads"])
    application.include_router(instagram_routes.router, prefix="/api/platforms/instagram", tags=["instagram-platform"])
    application.include_router(accounts.router, prefix="/api/accounts",  tags=["accounts"])
    application.include_router(capacity.router, prefix="/api",           tags=["capacity"])
    application.include_router(agents.router,   prefix="/api/agents",    tags=["agents"])
    application.include_router(schedule.router, prefix="/api/schedule",  tags=["schedule"])
    application.include_router(funnel.router,     prefix="/api/funnel",          tags=["funnel"])
    application.include_router(ig_growth.router, prefix="/api/ig/growth",       tags=["ig-growth"])
    application.include_router(replacement_routes.router, prefix="/api/accounts", tags=["replacement"])
    application.include_router(cluster_monitor_routes.router, prefix="/api/cluster", tags=["cluster"])
    application.include_router(content_vault_routes.router, prefix="/api/content-vault", tags=["content-vault"])
    application.include_router(ops_routes.router,           prefix="/api/ops",          tags=["ops"])
    application.include_router(hq_bridge_routes.router,           prefix="/api/hq",           tags=["hq-bridge"])
    application.include_router(ig_intelligence_routes.router,     prefix="/api/ig",           tags=["ig-intelligence"])
    application.include_router(comment_pods_routes.router,        prefix="/api/comment-pods", tags=["comment-pods"])
    application.include_router(gmail_reddit_pipeline_routes.router, prefix="/api/pipeline",   tags=["pipeline"])
    application.include_router(groups_routes.router,         prefix="/api/groups",           tags=["groups"])
    application.include_router(warmup_routes.router,         prefix="/api/warmup",           tags=["warmup"])
    application.include_router(scraper_routes.router,        prefix="/api/scraper",          tags=["scraper"])
    application.include_router(strategy_routes.router,       prefix="/api/strategy",         tags=["strategy"])
    application.include_router(staffroom_routes.router)
    application.include_router(simulate_routes.router)
    application.include_router(time_machine_routes.router)
    application.include_router(scheduler_pro_routes.router,  prefix="/api/scheduler-pro",    tags=["scheduler-pro"])
    application.include_router(ai_agent_routes.router,       prefix="/api/ai-agent",         tags=["ai-agent"])
    application.include_router(pods_routes.router,           prefix="/api/pods",             tags=["pods"])
    application.include_router(ab_tests_routes.router,       prefix="/api/ab-tests",         tags=["ab-tests"])
    application.include_router(settings_routes.router,       prefix="/api/settings",         tags=["settings"])
    application.include_router(activity_log_routes.router,   prefix="/api/activity",         tags=["activity"])
    application.include_router(profiles_routes.router,       prefix="/api/profiles",         tags=["profiles"])
    application.include_router(trending_routes.router,       prefix="/api/trending",         tags=["trending"])
    application.include_router(learning_routes.router,       prefix="/api/learning",         tags=["learning"])
    application.include_router(reddit_routes.router,         prefix="/api/reddit",           tags=["reddit"])
    application.include_router(fleet_mirror_routes.router,   prefix="/api/fleet-mirror",     tags=["fleet-mirror"])

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    @application.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "product": "phantom_fleet", "version": "0.1.0"}

    return application


app = create_app()
