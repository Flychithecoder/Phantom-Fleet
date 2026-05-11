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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import fleet, accounts, capacity, agents, schedule, funnel, ig_growth
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

    # Attempt to connect Redis (optional — ops brain works without it)
    redis_client = None
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        import aioredis  # type: ignore[import]
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        log.info("Redis connected: %s", redis_url)
    except Exception as exc:
        log.warning("Redis unavailable (%s) — ops brain will run without pub/sub", exc)

    # Boot proxy orchestrator — Smartproxy static pool takes priority over IPRoyal residential
    from ..proxy import smartproxy_pool_from_env, iproyal_from_env
    sp_pool = smartproxy_pool_from_env()
    if sp_pool:
        app.state.proxy = sp_pool
        log.info("Smartproxy pool ready (%d proxies)", sp_pool.fleet_status()["pool_size"])
    else:
        try:
            proxy_orch = iproyal_from_env()
            app.state.proxy = proxy_orch
            log.info("IPRoyal proxy orchestrator ready")
        except RuntimeError as exc:
            app.state.proxy = None
            log.warning("Proxy orchestrator not started: %s", exc)

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

    yield

    # Shutdown
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

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    @application.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "product": "phantom_fleet", "version": "0.1.0"}

    return application


app = create_app()
