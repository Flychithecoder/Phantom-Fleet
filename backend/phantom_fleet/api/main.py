"""
Phantom Fleet FastAPI entrypoint.

Routes:
    GET  /health                       — liveness probe
    GET  /api/v1/farms                 — list farms
    GET  /api/v1/phones                — list phones + live state
    GET  /api/v1/personas              — list personas
    GET  /api/v1/personas/:id          — persona detail
    GET  /api/v1/accounts              — paginated account list
    GET  /api/v1/accounts/:id          — account detail + history
    GET  /api/v1/agents                — agent mesh status
    POST /api/v1/agents/:name/run      — kick an agent (subject to confirmation gates)
    POST /api/v1/agents/chat           — chat with an agent (mock responses)
    GET  /api/v1/cluster/histogram     — fingerprint histograms (live)
    GET  /api/v1/targets/today         — today's fresh target slices
    GET  /api/v1/funnel/conversions    — funnel attribution data
    GET  /api/v1/alerts                — fleet alerts feed
    POST /api/v1/settings/openrouter   — save OpenRouter settings
    POST /api/v1/settings/openrouter/test — verify OpenRouter API key
    WS   /ws/fleet                     — real-time fleet state stream

    GET  /api/pipeline/gmail/stats         — Gmail pool statistics
    POST /api/pipeline/gmail/create        — trigger Gmail creation on a phone
    POST /api/pipeline/reddit/register     — register Reddit accounts from pool
    GET  /api/pipeline/reddit/accounts     — list Reddit accounts with status
    POST /api/pipeline/reddit/export       — export Reddit credentials as CSV

Everything that writes to the fleet goes through the agent mesh — the API
never executes raw IG actions. That's the safety gate.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .routes.gmail_reddit_pipeline import router as gmail_reddit_router

log = logging.getLogger("phantom_fleet.api")


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Phantom Fleet API starting up")
    # TODO: init db pool, redis, load agent registry, start background tasks
    yield
    log.info("Phantom Fleet API shutting down")


app = FastAPI(
    title="Phantom Fleet API",
    description="Invisible automation at fleet scale. A Scaler Pro product.",
    version="0.0.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3016"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(gmail_reddit_router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "product": "phantom_fleet", "version": "0.0.1"}


# ---------------------------------------------------------------------------
# Farms + phones
# ---------------------------------------------------------------------------


@app.get("/api/v1/farms")
async def list_farms():
    # Stub — wire to db.farms query
    return {
        "farms": [
            {"id": "farm-1", "name": "Farm 1", "phones": 17, "state": "active"},
        ]
    }


@app.get("/api/v1/phones")
async def list_phones():
    return {"phones": [], "count": 0}


# ---------------------------------------------------------------------------
# Personas + accounts
# ---------------------------------------------------------------------------


@app.get("/api/v1/personas")
async def list_personas():
    return {"personas": [
        {"id": "tatiana", "name": "Tatiana", "account_count": 97, "target_funnel": "onlyfans"},
        {"id": "melodie", "name": "Melodie", "account_count": 122, "target_funnel": "onlyfans"},
    ]}


@app.get("/api/v1/accounts")
async def list_accounts(persona_id: str | None = None, status: str | None = None):
    return {"accounts": [], "count": 0}


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@app.get("/api/v1/agents")
async def list_agents():
    from ..agents.registry import AGENT_CLASSES
    return {
        "agents": [
            {"name": name, "config": {
                "max_iterations": cls.config.max_iterations,
                "max_usd_per_run": cls.config.max_usd_per_run,
                "allowed_tools": list(cls.config.allowed_tools),
            }}
            for name, cls in AGENT_CLASSES.items()
        ]
    }


class AgentRunRequest(BaseModel):
    ctx: dict = {}
    confirm_destructive: bool = False


@app.post("/api/v1/agents/{name}/run")
async def run_agent(name: str, req: AgentRunRequest):
    from ..agents.registry import AGENT_CLASSES
    if name not in AGENT_CLASSES:
        raise HTTPException(404, f"unknown agent: {name}")
    # Agents need a tool_registry wired up in production; stubbed here
    agent_cls = AGENT_CLASSES[name]
    agent = agent_cls(tool_registry={}, audit_sink=lambda e: log.info("audit: %s", e))
    run = await agent.run(req.ctx)
    return {"run_id": run.run_id, "status": run.status, "cost_usd": run.cost_usd}


# ---------------------------------------------------------------------------
# Cluster monitor
# ---------------------------------------------------------------------------


@app.get("/api/v1/cluster/histogram")
async def cluster_histogram():
    return {"dimensions": [], "max_score": 0.0}


# ---------------------------------------------------------------------------
# Funnel
# ---------------------------------------------------------------------------


@app.get("/api/v1/funnel/conversions")
async def funnel_conversions(days: int = 30):
    return {"conversions": [], "total_usd": 0.0}


# ---------------------------------------------------------------------------
# Agent chat — LLM-powered via OpenRouter, mocks as fallback
# ---------------------------------------------------------------------------

_AGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "chief": (
        "You are Chief, the operations AI assistant for a digital media agency called Phantom Fleet. "
        "You help the agency operator manage their daily workflow, track tasks, assign work to specialists, "
        "and make decisions about platform operations. You are direct, concise, and action-oriented. "
        "You have specialist team members: Instagram, Reddit, TikTok, and Dating. "
        "Respond in 1-3 sentences. Plain text only, no markdown headers."
    ),
    "instagram": (
        "You are the Instagram operations specialist for a digital media agency. "
        "You manage account health, content scheduling, engagement tracking, and growth metrics "
        "for a portfolio of creator accounts. You give clear, metric-driven operational updates. "
        "Respond in 1-3 sentences. Plain text only, no markdown headers."
    ),
    "reddit": (
        "You are the Reddit operations specialist for a digital media agency. "
        "You manage account pipeline stages, community engagement, content timing, and account health. "
        "You track stage progression, activity metrics, and flag issues. "
        "Respond in 1-3 sentences. Plain text only, no markdown headers."
    ),
    "tiktok": (
        "You are the TikTok operations specialist for a digital media agency. "
        "You manage content schedules, account warming queues, engagement rates, and geo-distribution. "
        "Respond in 1-3 sentences. Plain text only, no markdown headers."
    ),
    "dating": (
        "You are the dating platform operations specialist for a digital media agency. "
        "You manage creator profiles across platforms, verification workflows, and funnel performance. "
        "Respond in 1-3 sentences. Plain text only, no markdown headers."
    ),
}

_FALLBACK_REPLIES: dict[str, list[str]] = {
    "chief": [
        "Acknowledged. Running cross-platform sync now. ETA: 2 minutes.",
        "Noted. Delegating to the relevant sub-agent. I'll surface the result here.",
        "Fleet health is green across all 12 platforms. No anomalies in the last 6 hours.",
        "Understood. Queueing the task with priority: normal. 3 agents available to pick it up.",
        "All systems nominal. Fingerprint variance is within bounds. No cluster flags from the monitor.",
    ],
    "instagram": [
        "Story batch queued for next rotation window. Estimated dispatch: 14 minutes.",
        "Follow ratio looks healthy. 3 accounts flagged for soft-limit — holding them for 24h.",
        "Warming cohort on track. 45 accounts at day 6 of 14. No temp bans in the last 48h.",
        "Engagement is up. Top performing persona: Melodie, 4.8% ER on stories this week.",
        "Proxy rotation clean. 0 IP collisions detected across the farm.",
    ],
    "reddit": [
        "Karma farming queue has 34 accounts. Average daily karma gain: 38 pts/account.",
        "2 accounts in shadowban queue — initiating check via r/ShadowBan probe now.",
        "Subreddit targeting updated. New slice: r/OnlyFansAdvice — 47K subs, low mod activity.",
        "Post timing spread across a 6-hour diurnal window. No clustering detected.",
        "Stage 4 accounts (89 total) are hitting comment threads. Engagement rate: 6.1%.",
    ],
    "tiktok": [
        "FBR holding steady at 4.2% 7-day average. No geo flags from the mesh.",
        "12 dormant accounts completing warm-up. Day 9 of 14 for the current cohort.",
        "Content rotation running. 44 accounts in steady state posting 2x/day.",
        "Device fingerprint variance is healthy. No monoculture flags from the cluster monitor.",
        "Geo distribution: 62% US, 18% UK, 11% CA, 9% AU. All within expected ranges.",
    ],
    "dating": [
        "SIM pool at 8/12 available. 4 SIMs locked in active verification flows.",
        "14 verification clips queued. Processing at 2 clips/hour to stay under platform limits.",
        "Match rate this week: Tinder 34%, Bumble 28%, Hinge 41%, Grindr 67%.",
        "38 Tinder accounts in rotation. 3 paused pending re-verification.",
        "Bumble profile refresh scheduled for tonight's maintenance window.",
    ],
}


def _load_openrouter_key() -> str | None:
    """Load API key from saved config file, then env var."""
    import os
    if _OPENROUTER_SETTINGS_PATH.exists():
        try:
            data = json.loads(_OPENROUTER_SETTINGS_PATH.read_text(encoding="utf-8"))
            key = data.get("api_key", "").strip()
            if key:
                return key
        except Exception:
            pass
    return os.environ.get("OPENROUTER_API_KEY") or None


def _fallback_reply(agent_key: str, message: str) -> str:
    replies = _FALLBACK_REPLIES.get(agent_key, _FALLBACK_REPLIES["chief"])
    return replies[len(message) % len(replies)]


class ChatMessage(BaseModel):
    role: str   # "user" | "agent"
    text: str


class AgentChatRequest(BaseModel):
    agent: str
    message: str
    history: list[ChatMessage] = []


class AgentChatResponse(BaseModel):
    agent: str
    reply: str
    timestamp: str


@app.post("/api/v1/agents/chat", response_model=AgentChatResponse)
async def agent_chat(req: AgentChatRequest):
    agent_key = req.agent.lower()
    if agent_key not in _AGENT_SYSTEM_PROMPTS:
        agent_key = "chief"

    api_key = _load_openrouter_key()

    if api_key:
        # Build OpenRouter messages array
        messages = [{"role": "system", "content": _AGENT_SYSTEM_PROMPTS[agent_key]}]
        # Inject conversation history (last 10 turns max to control tokens)
        for h in req.history[-10:]:
            role = "user" if h.role == "user" else "assistant"
            messages.append({"role": role, "content": h.text})
        messages.append({"role": "user", "content": req.message})

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://phantomfleet.scalerpro.io",
                        "X-Title": "Phantom Fleet",
                    },
                    json={
                        "model": "x-ai/grok-beta",
                        "messages": messages,
                        "max_tokens": 256,
                        "temperature": 0.7,
                    },
                )
            if resp.status_code == 200:
                data = resp.json()
                reply_text = data["choices"][0]["message"]["content"].strip()
                return AgentChatResponse(
                    agent=agent_key,
                    reply=reply_text,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as exc:
            log.warning("OpenRouter chat failed: %s — falling back to mock", exc)

    # Fallback to static replies when no API key or request failed
    return AgentChatResponse(
        agent=agent_key,
        reply=_fallback_reply(agent_key, req.message),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Settings — OpenRouter
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_OPENROUTER_SETTINGS_PATH = _CONFIG_DIR / "openrouter_settings.json"


class OpenRouterSettingsRequest(BaseModel):
    api_key: str
    model: str
    daily_cap_usd: float = 50.0


class OpenRouterTestRequest(BaseModel):
    api_key: str
    model: str


@app.post("/api/v1/settings/openrouter")
async def save_openrouter_settings(req: OpenRouterSettingsRequest):
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_key": req.api_key,
        "model": req.model,
        "daily_cap_usd": req.daily_cap_usd,
    }
    _OPENROUTER_SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"success": True}


@app.post("/api/v1/settings/openrouter/test")
async def test_openrouter_settings(req: OpenRouterTestRequest):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {req.api_key}"},
            )
        if resp.status_code == 200:
            return {"success": True, "model": req.model}
        else:
            return {"success": False, "error": f"OpenRouter returned HTTP {resp.status_code}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out after 10 seconds"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# IG specialist agent queues (stub endpoints — wire to real DB queries)
# ---------------------------------------------------------------------------


@app.get("/api/v1/ig/unfollow/queue")
async def ig_unfollow_queue(account_id: str | None = None, limit: int = 50):
    """
    Return the current unfollow candidate queue for one or all accounts.

    In production this queries the follow-history DB (or reads sidecar files)
    and returns accounts that didn't follow back after N days, sorted by
    unfollow priority (non-followers first, then inactive accounts).
    """
    return {
        "queue": [
            {
                "account_id":        "acct_demo_001",
                "target_user_id":    "ig_user_88123",
                "followed_at_iso":   "2026-04-01T09:14:22Z",
                "followed_back":     False,
                "days_since_follow": 10.2,
                "is_inactive":       False,
                "priority_score":    1,
            },
            {
                "account_id":        "acct_demo_001",
                "target_user_id":    "ig_user_77509",
                "followed_at_iso":   "2026-03-29T11:00:00Z",
                "followed_back":     False,
                "days_since_follow": 13.0,
                "is_inactive":       True,
                "priority_score":    2,
            },
        ],
        "total": 2,
        "account_id": account_id,
    }


@app.get("/api/v1/ig/notes/today")
async def ig_notes_today(account_id: str | None = None):
    """
    Return today's Note status for one or all accounts.

    In production this queries the notes_log table to show which accounts
    have already posted today's Note and what text was used.
    """
    from datetime import date as _date
    return {
        "date_iso": _date.today().isoformat(),
        "notes": [
            {
                "account_id":    "acct_demo_001",
                "note_text":     "running on caffeine and delusion ☕",
                "mood_category": "funny",
                "posted_at":     "2026-04-11T10:04:38Z",
                "status":        "posted",
            },
            {
                "account_id":    "acct_demo_002",
                "note_text":     None,
                "mood_category": None,
                "posted_at":     None,
                "status":        "pending",
            },
        ],
        "posted_count": 1,
        "pending_count": 1,
        "total": 2,
    }


@app.get("/api/v1/ig/saves/queue")
async def ig_saves_queue(account_id: str | None = None, limit: int = 20):
    """
    Return the save queue: creator posts eligible to be saved by child accounts.

    In production this queries the creator post cache and cross-references
    each child account's already_saved_media_ids set to return posts that
    still need saves, prioritised by freshness (newest first).
    """
    return {
        "queue": [
            {
                "media_id":         "3456789012345678",
                "creator_user_id":  "creator_tatiana_001",
                "posted_at_iso":    "2026-04-11T07:30:00Z",
                "age_hours":        2.6,
                "is_fresh":         True,
                "accounts_to_save": ["acct_demo_002", "acct_demo_003"],
                "fleet_offsets":    {"acct_demo_002": 14, "acct_demo_003": 87},
            },
            {
                "media_id":         "3456700011122233",
                "creator_user_id":  "creator_tatiana_001",
                "posted_at_iso":    "2026-04-10T18:00:00Z",
                "age_hours":        16.2,
                "is_fresh":         True,
                "accounts_to_save": ["acct_demo_001"],
                "fleet_offsets":    {"acct_demo_001": 203},
            },
        ],
        "total": 2,
        "account_id": account_id,
    }


# ---------------------------------------------------------------------------
# Reel view queue
# ---------------------------------------------------------------------------


@app.get("/api/v1/ig/reels/queue")
async def ig_reels_queue(creator_user_id: str | None = None, limit: int = 10):
    """
    Return the current reel watch queue: creator Reels eligible to receive
    coordinated watch-through from child accounts, with per-account fleet
    stagger offsets.

    fleet_watch_offsets maps account_id → seconds_after_post_published at
    which that account should begin watching. Computed via
    reel_view_offset_seconds(account_id, media_id) — deterministic, SHA-256
    based, spreads views across a 2-hour window to produce an organic
    view-arrival curve.

    In production this queries the creator post cache, filters to Reels
    (media_type == 2, product_type == "clips"), and computes per-account
    offsets for all child accounts assigned to the creator's funnel.
    """
    from ..agents.specialists.ig_reel_view_agent import reel_view_offset_seconds

    # Mock child accounts for demo — replace with DB query in production
    demo_accounts = [f"acct_child_{i:03d}" for i in range(1, 6)]

    mock_reels = [
        {
            "media_id": "3512345678901234",
            "creator_user_id": creator_user_id or "creator_tatiana_001",
            "duration_seconds": 28,
            "posted_at_iso": "2026-04-11T09:00:00Z",
            "age_minutes": 65,
            "is_fresh": True,
            "fleet_watch_offsets": {
                acct: reel_view_offset_seconds(acct, "3512345678901234")
                for acct in demo_accounts
            },
        },
        {
            "media_id": "3512300099887766",
            "creator_user_id": creator_user_id or "creator_tatiana_001",
            "duration_seconds": 45,
            "posted_at_iso": "2026-04-11T07:30:00Z",
            "age_minutes": 155,
            "is_fresh": True,
            "fleet_watch_offsets": {
                acct: reel_view_offset_seconds(acct, "3512300099887766")
                for acct in demo_accounts
            },
        },
    ]

    return {
        "queue": mock_reels[:limit],
        "total": len(mock_reels),
        "creator_user_id": creator_user_id,
        "accounts_in_pool": len(demo_accounts),
        "stagger_window_seconds": 7200,
    }


# ---------------------------------------------------------------------------
# Engagement Pods
# ---------------------------------------------------------------------------


class PodRebuildRequest(BaseModel):
    confirm: bool = False


@app.get("/api/v1/ig/pods")
async def list_pods():
    """
    List all engagement pods with member counts and recent engagement stats.

    Returns pod_id, niche, member_count, and mock engagement stats for
    dashboard visibility. In production, stats are pulled from the
    pod_engagement_records table.
    """
    from ..core.pod_registry import PodRegistry
    registry = PodRegistry()
    pods = registry.load_pods()

    return {
        "pods": [
            {
                "pod_id": pod.pod_id,
                "niche": pod.niche,
                "member_count": len(pod.member_account_ids),
                "created_at": pod.created_at_iso,
                # Mock engagement stats — replace with DB query in production
                "stats": {
                    "likes_last_24h": 0,
                    "comments_last_24h": 0,
                    "avg_engagement_delay_seconds": 900,
                },
            }
            for pod in pods
        ],
        "total_pods": len(pods),
        "total_accounts_in_pods": sum(len(p.member_account_ids) for p in pods),
    }


@app.post("/api/v1/ig/pods/rebuild")
async def rebuild_pods(req: PodRebuildRequest):
    """
    Trigger pod reassignment for all accounts.

    DESTRUCTIVE: existing pod assignments are overwritten. Requires
    {"confirm": true} in the request body to prevent accidental calls.
    Pod membership is stable by design — only rebuild when replacing a
    significant batch of dead accounts.
    """
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Pod rebuild is destructive — it resets all pod memberships. "
                "Pass {'confirm': true} to proceed."
            ),
        )

    # In production: pull live account_ids from DB, call registry.build_pods()
    # and registry.save_pods(). Stubbed here — wire to account repository.
    return {
        "success": False,
        "message": (
            "Pod rebuild stub: wire account_ids from DB in production. "
            "Call PodRegistry().build_pods(account_ids) then save_pods()."
        ),
    }


# ---------------------------------------------------------------------------
# Fleet phone management  (/api/fleet/...)
# ---------------------------------------------------------------------------


@app.get("/api/fleet/phones")
async def fleet_list_phones():
    return {"phones": [], "count": 0}


@app.post("/api/fleet/scan")
async def fleet_scan():
    return {"ok": True, "found": 0}


@app.post("/api/fleet/verify-all")
async def fleet_verify_all():
    return {"ok": True, "verified": 0}


@app.delete("/api/fleet/phones/{serial}")
async def fleet_delete_phone(serial: str):
    return {"ok": True, "serial": serial}


@app.get("/api/fleet/{serial}/accounts")
async def fleet_serial_accounts(serial: str):
    return {"accounts": [], "serial": serial}


@app.post("/api/fleet/{serial}/verify-proxy")
async def fleet_serial_verify_proxy(serial: str):
    return {"ok": True, "serial": serial, "proxy": "clean"}


# ---------------------------------------------------------------------------
# Account CRUD  (/api/accounts/...)
# ---------------------------------------------------------------------------


class AccountProvisionRequest(BaseModel):
    serial: str
    username: str = ""
    persona_id: str = ""


@app.post("/api/accounts/provision")
async def accounts_provision(req: AccountProvisionRequest):
    import uuid
    return {"ok": True, "id": str(uuid.uuid4()), "serial": req.serial}


@app.get("/api/accounts")
async def accounts_list(serial: str | None = None, persona_id: str | None = None, status: str | None = None):
    return {"accounts": [], "count": 0}


@app.get("/api/accounts/{account_id}")
async def accounts_get(account_id: str):
    return {
        "id": account_id, "username": "", "persona_id": "", "serial": "",
        "status": "active", "loggedIn": False, "proxy": "",
        "ig": {}, "threads": {}, "targets": [],
    }


@app.put("/api/accounts/{account_id}")
async def accounts_update(account_id: str, body: dict):
    return {"ok": True, "id": account_id}


@app.delete("/api/accounts/{account_id}")
async def accounts_delete(account_id: str):
    return {"ok": True, "id": account_id}


@app.post("/api/accounts/{account_id}/clone")
async def accounts_clone(account_id: str):
    import uuid
    return {"ok": True, "new_id": str(uuid.uuid4()), "cloned_from": account_id}


@app.post("/api/accounts/{account_id}/detect-clone")
async def accounts_detect_clone(account_id: str):
    return {"is_clone": False, "confidence": 0.0, "account_id": account_id}


@app.post("/api/accounts/{account_id}/login")
async def accounts_login(account_id: str):
    return {"ok": True, "account_id": account_id}


@app.post("/api/accounts/{account_id}/logout")
async def accounts_logout(account_id: str):
    return {"ok": True, "account_id": account_id}


@app.post("/api/accounts/{account_id}/scrape-follow-source")
async def accounts_scrape_follow_source(account_id: str, body: dict = {}):
    return {"ok": True, "queued": True, "account_id": account_id}


# ---------------------------------------------------------------------------
# Per-account targets
# ---------------------------------------------------------------------------


@app.get("/api/accounts/{account_id}/targets")
async def account_targets_list(account_id: str):
    return {"targets": [], "account_id": account_id}


@app.post("/api/accounts/{account_id}/targets")
async def account_targets_add(account_id: str, body: dict = {}):
    import uuid
    return {"ok": True, "id": str(uuid.uuid4()), "account_id": account_id}


@app.delete("/api/accounts/{account_id}/targets/{target_id}")
async def account_targets_delete(account_id: str, target_id: str):
    return {"ok": True, "account_id": account_id, "target_id": target_id}


@app.post("/api/accounts/{account_id}/targets/ai-scrape")
async def account_targets_ai_scrape(account_id: str, body: dict = {}):
    return {"ok": True, "queued": True, "account_id": account_id, "estimated_results": 0}


# ---------------------------------------------------------------------------
# Per-account stats
# ---------------------------------------------------------------------------


@app.get("/api/accounts/{account_id}/stats")
async def account_stats(account_id: str, days: int = 30):
    return {
        "account_id": account_id,
        "days": days,
        "follows": 0, "unfollows": 0, "likes": 0, "comments": 0,
        "story_views": 0, "dm_sent": 0, "dm_received": 0,
        "follow_back_rate": 0.0, "funnel_conversions": 0,
        "daily": [],
    }


# ---------------------------------------------------------------------------
# Capacity planner + schedule generator
# ---------------------------------------------------------------------------


@app.post("/api/capacity-plan")
async def capacity_plan(body: dict = {}):
    return {
        "ok": True,
        "plan": {
            "total_accounts": 0, "active_accounts": 0,
            "daily_follows": 0, "daily_unfollows": 0,
            "estimated_monthly_revenue_usd": 0.0,
        },
    }


@app.post("/api/schedule/generate")
async def schedule_generate(body: dict = {}):
    return {"ok": True, "schedule": [], "generated_at": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Ops Brain  (/api/ops/...)
# ---------------------------------------------------------------------------


@app.get("/api/ops/status")
async def ops_status():
    return {
        "running": False, "paused": False,
        "active_agents": 0, "queued_tasks": 0,
        "last_cycle_at": None, "next_cycle_at": None,
    }


@app.get("/api/ops/cycle/latest")
async def ops_cycle_latest():
    return {"cycle": None}


@app.get("/api/ops/cycle/history")
async def ops_cycle_history():
    return {"cycles": [], "count": 0}


@app.post("/api/ops/pause")
async def ops_pause():
    return {"ok": True, "paused": True}


@app.post("/api/ops/resume")
async def ops_resume():
    return {"ok": True, "paused": False}


@app.post("/api/ops/cycle/trigger")
async def ops_cycle_trigger():
    return {"ok": True, "queued": True}


# ---------------------------------------------------------------------------
# Onboarding helpers  (/api/fleet/... extras)
# ---------------------------------------------------------------------------


@app.post("/api/fleet/{serial}/install-apk")
async def fleet_install_apk(serial: str, body: dict = {}):
    return {"ok": True, "serial": serial, "status": "queued"}


@app.post("/api/fleet/start-warming")
async def fleet_start_warming():
    return {"ok": True, "warming_started": True}


@app.get("/api/fleet/{serial}/apk-health")
async def fleet_apk_health(serial: str):
    return {"serial": serial, "apk_installed": False, "version": None, "last_checked": None}


# ---------------------------------------------------------------------------
# Content vault  (/api/content-vault/...)
# ---------------------------------------------------------------------------


@app.get("/api/content-vault")
async def content_vault_list(page: int = 1, limit: int = 20, tag: str | None = None, nsfw: str | None = None):
    return {"items": [], "total": 0, "page": page, "limit": limit}


@app.post("/api/content-vault/upload")
async def content_vault_upload():
    import uuid
    return {"ok": True, "id": str(uuid.uuid4())}


@app.get("/api/content-vault/stats")
async def content_vault_stats():
    return {"total_items": 0, "total_size_mb": 0.0, "sfw_count": 0, "nsfw_count": 0}


@app.post("/api/content-vault/schedule")
async def content_vault_schedule(body: dict = {}):
    return {"ok": True, "scheduled": 0}


@app.get("/api/content-vault/media/{filename}")
async def content_vault_media(filename: str):
    raise HTTPException(404, "media not found")


@app.get("/api/content-vault/{item_id}")
async def content_vault_get(item_id: str):
    raise HTTPException(404, "item not found")


@app.post("/api/content-vault/{item_id}/deliver")
async def content_vault_deliver(item_id: str, phone_serial: str | None = None):
    return {"ok": True, "item_id": item_id, "delivered_to": phone_serial}
