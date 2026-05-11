# Phantom Fleet

**Invisible automation at fleet scale.** A Scaler Pro product.

Phantom Fleet is the real-device social media automation platform for growth agencies,
brands, creators, dropshippers, OFM agencies, and lead-gen operators who need to scale
across every major platform without burning accounts. **15 autonomous AI agents**, live
fleet-scale cluster detection, a unified cross-platform persona primitive, and a
$500M-tier command dashboard — all running on the hardware you already own.

**Whatever your vertical.** Phantom Fleet is industry-neutral: what you run on it, and
what destination you funnel conversions to (store, subscription, lead capture, affiliate,
OF/Fanvue/ScaleHer, etc.) is up to you.

---

## Product family

- **Phantom Fleet** — the physical-device orchestrator (this repo)
- **Phantom Forge** — custom clone generation pipeline (Phase 3+)
- **Phantom Panel** — multi-tenant SaaS control plane (Phase 2+)
- **Phantom Prime** — enterprise tier (Phase 5+)

---

## Status (as of 2026-04-11)

**Phase 0 scaffolding complete.** Awaiting:

1. Proxy-state diagnostic (read-only verification of current phone routing)
2. IPRoyal Royal Residential Unlimited purchase (~$80/mo)
3. Login-survival test on all 16 authorized phones (blocked by proxy gate)
4. Full-box parallel Day 1 launch across 19 devices + 219 Tatiana/Melodie accounts

See [`PLAN.md`](./PLAN.md) for the complete executive plan.

---

## What's on disk

### Backend — Python 3.12 + FastAPI + Postgres (`backend/`)

- **Core libraries** (5):
  - `core/distributions.py` — LogNormal, Normal, Bimodal, WeightedCategorical. Banned raw `random.uniform` across identity code.
  - `core/warming_curve.py` — 7-day re-wake curve + 28-day fresh curve, all ranges sampled per-(account, date).
  - `core/persona.py` — Persona primitive with locked biometrics sampled from real distributions.
  - `core/source_scorer.py` — Female-US-creator classifier + engagement quality scorer.
  - `core/target_filter.py` — Male-US follower filter applied after source follower scraping.

- **Agent mesh** (15 agents, all with base `Agent` class enforcing CLAUDE.md agent-audit rules):
  - `warming` — Daily re-wake + warmup curve orchestration
  - `fresh_target` — Fresh unique targets per account per day, 90d dedup
  - `source_discovery` — Auto-discover female US high-engagement sources
  - `fingerprint_monitor` — Live 20-dim cluster detection every 5 min
  - `recovery` — Phone crash / session expire auto-heal
  - `replacement` — Dead-account detection + replacement provisioning
  - `proxy_orchestrator` — IPRoyal rotation + block recovery
  - `dm` — Fan DM + OF/Fanvue/ScaleHer funnel
  - `content` — Caption gen + post scheduling (hashtag-free, LLM-tell-free)
  - `account_setup` — Onboard imports + replacements
  - `persona_factory` — Generate new personas with audit validation
  - `growth_strategy` — Weekly KPI review + source reweighting
  - `funnel_conversion` — Fan → OF sub attribution
  - `content_scout` — Trending content discovery
  - `audit_harness` — 10K-persona Monte Carlo cluster gate

- **API layer** — FastAPI with routes for farms, phones, personas, accounts, agents, cluster histogram, funnel conversions
- **DB layer** — Postgres 16 schema (`migrations/001_initial_schema.sql`) with 11 tables + indexes
- **Proxy** — IPRoyal Royal Residential Unlimited orchestrator with sticky session + geo pinning
- **Phones** — ADB + Companion APK HTTP client with **hard safety gate** (no writes without proxy verified)
- **Tests** — 19 pytest tests passing, covering distributions, warming curve, source scoring

### Frontend — Next.js 15 + TypeScript + Tailwind (`frontend/`) · port 3016

**Design system:** Dark-first premium SaaS. Neon cyan-green signature accent
(`hsl(162 100% 54%)`). Inter display font. Glass panels with grid background.
Optimized for 14-24hr sessions in a dim room.

**Dashboard routes (11 pages):**
- `/` — Command center overview (fleet map, KPIs, agent feed, cluster heatmap, revenue, action stream)
- `/fleet` — Phone grid, per-device drill-in at `/fleet/[serial]`
- `/personas` — Persona profiles, detail at `/personas/[id]`
- `/accounts` — Full sortable account table with health + sparklines
- `/agents` — Agent mesh status + per-agent detail at `/agents/[name]`
- `/targets` — Fresh target queue + source pool rankings
- `/cluster` — Live 20-dim fingerprint heatmap
- `/alerts` — Alert timeline (auto-resolved + active)
- `/funnel` — OF/Fanvue/ScaleHer conversion waterfall
- `/content` — Content Vault browser
- `/analytics` — Cohort survival heatmap + historical KPIs
- `/settings` — Proxy / audit / database / agent cost config

**Marketing routes (4 pages):**
- `/welcome` — Landing with animated particle hero + 4-pillar features + architecture diagram + Onimator comparison + testimonials + FAQ
- `/features` — 12-feature deep dive grouped by category
- `/pricing` — 5 tiers ($79 → $6,500+)
- `/docs` — Documentation index

**Shared components (23 files):**
- `sidebar`, `top-bar`, `command-palette` — navigation chrome
- `panel`, `kpi-card`, `status-badge` — canonical layout primitives
- `fleet-grid` — 19-phone live status card grid
- `agent-feed`, `action-stream` — live agent + action firehoses
- `cluster-heatmap` — 20-dim fingerprint monitor
- `revenue-chart` — OF/Fanvue/ScaleHer stacked area
- `stat-ring`, `sparkline`, `heatmap-grid`, `funnel-viz` — data-viz primitives
- `data-table` — sortable table for accounts/sources
- `animated-hero-bg` — canvas particle system for landing page
- `comparison-table` — Onimator vs Phantom Fleet feature matrix
- `architecture-diagram` — 5-layer SVG diagram
- `faq-accordion`, `testimonials` — marketing components
- `live-ticker` — drifting numeric ticker

### Companion APK — Kotlin + Jetpack Compose (`companion-apk/`)

- `MainActivity.kt` — App entry with AccessibilityService enable button
- `PhantomAccessibilityService.kt` — Service skeleton with `tapAt(x, y, dwellMs)` primitive
- Gradle build config, AndroidManifest, accessibility config
- Phase 1 adds Ktor embedded HTTP server on 127.0.0.1:8765 with tap/type/scroll/screenshot/UI-inspect primitives

### Discord intel (`discord-export/`)

- 48,849 messages from the Onimator Discord exported (28 channels, 2023-2026)
- `_analysis/` contains `top_authors.md`, `keyword_index.md`, `pro_posts.md`, `channel_summaries.md`, `full_small.md`
- `_analysis/onimator_intel.md` (2.3 MB) + `onimator_intel.json` (7.3 MB) — full SQLite schema dumps
- `_analysis/onimator_summary.md` — concise 219-account + persona extraction

### Scripts (`backend/scripts/`)

- `migrate_onimator.py` — read-only import of 219 existing accounts + action history + target pool

### Infra

- `docker-compose.yml` — Postgres 5436 + Redis 6380 + backend 8000 + frontend 3016
- `backend/Dockerfile`, `backend/pyproject.toml`, `backend/.env.example`
- `frontend/package.json`, `frontend/.env.example`, `frontend/next.config.mjs`

---

## Start from zero

```bash
# 1. Bring up Postgres + Redis
docker compose up -d postgres redis

# 2. Install backend deps + run the API
cd backend
pip install -e .
uvicorn phantom_fleet.api.main:app --reload --port 8000

# 3. Install frontend deps + run the dashboard
cd frontend
npm install
npm run dev         # → http://localhost:3016
```

Hit `http://localhost:3016` and you'll see the command center.

Marketing routes at `http://localhost:3016/welcome`.

---

## Hard safety gates (non-negotiable)

1. **No IG clone launches until proxy routing is verified.** Enforced in
   `phones/__init__.py` at the method level — `PhoneController.tap()`,
   `.type_text()`, `.launch_clone()` all raise `RuntimeError` if
   `_proxy_verified[serial]` is not True. No bypass.

2. **No destructive Onimator writes.** `migrate_onimator.py` opens every
   SQLite DB in `mode=ro` URI mode. Never writes.

3. **Audit harness CI gate.** The `AuditHarnessAgent` runs 10,000-persona
   Monte Carlo cluster checks on every deploy. Any dimension clustering
   fails the build.

4. **Agent confirmation gates.** Destructive actions (`wipe_account_data`,
   `mass_dm_blast`, `purchase_new_accounts`, `factory_reset_phone`) require
   human confirmation via the `confirmation_required_for` allowlist.

5. **Hashtags banned in captions + DMs.** `ContentAgent._is_caption_valid()`
   and `DMAgent._contains_banned()` reject any output containing `#`, em-dashes,
   ellipses, or LLM detection tells.

6. **Distribution discipline.** `core/distributions.py` is the only entry
   point for random values on identity-contributing code paths. Raw
   `random.uniform()`, `Math.random()` are lint-banned.

---

## Key metrics (target)

| Metric | Value |
|---|---|
| Phones simultaneous | **19 of 19** |
| Accounts simultaneous | **219 existing + replacements** |
| Proxy IPs simultaneous (concurrent) | **up to 19 unique per session** via IPRoyal |
| Account 30-day survival target | **99.4%** |
| Account 6-month survival target | **60%+** |
| Daily fresh targets generated | **~4,000** |
| Approved source pool size target | **500+ female US creators** |
| Cluster detection latency | **< 5 minutes** |
| Agent mesh runs / day | **~2,000** |
| LLM cost cap / day | **$50** |
| Monthly proxy cost | **$80** (IPRoyal Unlimited) |
| Phase 1 revenue target | **$500-2,000/mo** OF funnel |

---

## The moat in one sentence

**Phantom Fleet is the only social media automation platform that runs
fleet-scale cluster detection on 20 fingerprint dimensions with a 10,000-
persona Monte Carlo CI gate, a unified cross-platform persona primitive, and
15 autonomous AI agents that replace every hour of manual operational
labor — all on hardware you already own.**

Onimator does none of this. Nothing else on the market does any of this.
