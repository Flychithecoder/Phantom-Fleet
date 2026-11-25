# Phantom Fleet capability map

Snapshot of the current Fleet build as of 2026-11-24. Every capability lists
its code entry point, where it runs, current evidence, business owner (per the
roster in [01-team-roster.md](01-team-roster.md)), missing dependencies, and
status: **works** (verified running), **integ** (built but Staffroom wiring
missing), **planned** (not yet implemented).

Nothing on the Tailscale staging URL `desktop-c74bmhb.tail72dd7e.ts.net:10444`
has been touched by this map — the inventory is of the new Phantom Fleet
checkout at `C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone`.

## 1 Fleet operations

| Capability | Entry point | Runs on | Evidence | Owner | Missing deps | Status |
|---|---|---|---|---|---|---|
| Device fleet inventory (19 S21 FE) | `backend/phantom_fleet/api/routes/fleet.py`, `fleet_mirror.py` | backend :8000 | `/api/fleet/*` returns 19 devices; dashboard shows "19 phones online" | Device Inventory Specialist | ADB daemon on each phone; Magisk root roadmap | works |
| Fleet mirror relay | `routes/fleet_mirror.py`, companion-apk mirror worker | backend :8000 ↔ phone APK | WS loop logged earlier this session | Device Inventory Specialist | Companion APK pilot (1 phone) before fleet roll-out | integ |
| Capacity planning | `agents/capacity_planner_agent.py`, `routes/capacity.py`, `frontend/.../capacity` | backend :8000 | Agent registered, UI page renders | Maintenance Coordinator | None | works |
| Fleet health checks | `platforms/instagram_health.py`, `threads_health.py` | backend :8000 | Audit `_check_ig_health_score` passes | Fleet Health Specialist | Per-platform health across Reddit/TikTok (not built) | integ |
| Proxy pool + per-account pinning | `routes/proxy_pool.py`, `platforms/instagram_proxy.py` | backend :8000 | 31/31 audit green; pinning TTL 72h, quarantine 24h | Fleet Health Specialist | Live proxy provider adapter | integ |
| Device drift detection (10 dims) | `platforms/instagram_drift.py` | backend :8000 | `_check_ig_drift` passes | Fleet Health Specialist | None | works |

## 2 Instagram platform

| Capability | Entry point | Runs on | Evidence | Owner | Missing deps | Status |
|---|---|---|---|---|---|---|
| IG orchestrator + rebalancer | `platforms/instagram_orchestrator.py`, `instagram_rebalancer.py` | backend :8000 | audit checks `_check_ig_orchestrator`, `_check_ig_rebalancer_transitions` green | IG Platform Specialist | Live account warmup pilot | works |
| IG executor + diurnal | `instagram_executor.py`, `instagram_diurnal.py` | backend :8000 | LogNormal delays, chronotype buckets; audit green | IG Platform Specialist | None | works |
| IG identity pair-check | `instagram_identity.py` | backend :8000 | 6 rules (locale↔tz, device↔OS, carrier↔HNI, proxy↔tz, carrier↔country, AppCloner fingerprint) | Compliance Reviewer | None | works |
| IG engagement lattice | `instagram_lattice.py` | backend :8000 | 7 invariants, 4/6/day caps, audit green | IG Platform Specialist | None | works |
| IG checkpoint handler | `instagram_checkpoint.py` | backend :8000 | 10 checkpoint kinds, side-effects to recovery + session | Incident Triage Lead | None | works |
| IG session state machine | `instagram_session.py` | backend :8000 | 7 states, 2FA/password-reset/locked transitions | Fleet Health Specialist | None | works |
| IG unfollow discipline | `instagram_unfollow.py` | backend :8000 | dwell 48h, follow-back window 72h, ratio trip ≥3 | IG Platform Specialist | None | works |
| IG DM flow | `instagram_dm.py` | backend :8000 | 7 gates, 5 templates, audit green; cycle verified | IG Platform Specialist | None | works |
| IG funnel + probes | `instagram_funnel.py`, `instagram_probes.py` | backend :8000 | audit green | Ops Analyst | None | works |

## 3 Threads platform

| Capability | Entry point | Runs on | Evidence | Owner | Missing deps | Status |
|---|---|---|---|---|---|---|
| Threads audit harness (31 checks) | `platforms/threads_audit.py` | backend :8000 | `run_audit(500) → pass=31` at 2026-11-24 | QA Lead | None | works |
| Threads orchestrator/executor/health/funnel/rebalancer/recovery/probes | `platforms/threads_*.py` | backend :8000 | all audit checks green | Threads Platform Specialist | None | works |

## 4 Agents and managers

| Capability | Entry point | Runs on | Evidence | Owner | Missing deps | Status |
|---|---|---|---|---|---|---|
| Agent base framework (allowlist, iter cap, cost cap) | `agents/base.py` | backend :8000 | `ToolNotAllowed` raised correctly in logs | Opus COO | None | works |
| Chief manager | `agents/managers/chief.py` | backend :8000 | runs but failed earlier on missing `db.load_manager_reports` tool | Opus COO | `db.load_manager_reports` in tool registry | integ |
| Per-platform managers (14) | `agents/managers/{instagram,threads,reddit,tiktok,x,bluesky,linkedin,discord,telegram,dating,funnel,infrastructure,base}.py` | backend :8000 | managers registered | Opus COO | Per-platform tool registry completeness | integ |
| Recovery agent | `agents/recovery_agent.py` | backend :8000 | `_check_recovery_agent` green | Recovery Specialist | None | works |
| Audit harness agent | `agents/audit_harness_agent.py` | backend :8000 | 31/31 green | QA Lead | None | works |
| Persona factory agent | `agents/persona_factory_agent.py` | backend :8000 | 10K audit green | Data Quality Specialist | None | works |
| Content / Content-scout / Growth-strategy / Fresh-target / DM / Funnel-conversion / Fingerprint-monitor / Proxy-orchestrator / Account-setup agents | `agents/*_agent.py` | backend :8000 | registered | Product Operations Lead | Wiring into Staffroom missions | integ |

## 5 Data and reporting

| Capability | Entry point | Runs on | Evidence | Owner | Missing deps | Status |
|---|---|---|---|---|---|---|
| 10K-persona Monte Carlo audit | `platforms/threads_audit.py:run_audit` | backend :8000 | Required CI check per CLAUDE.md; 31/31 green | QA Lead | GitHub Actions wiring | integ |
| Activity log | `routes/activity_log.py` | backend :8000 | `/api/activity-log` | Ops Analyst | None | works |
| Cluster monitor | `routes/cluster_monitor.py` | backend :8000 | `/api/fleet/cluster/collisions` serving | Fleet Health Specialist | None | works |
| Executive overview dashboard | `frontend/src/app/page.tsx` | frontend :3016 | Command Center screenshot captured | Executive Reporting Worker | None | works |

## 6 Integrations

| Capability | Entry point | Runs on | Evidence | Owner | Missing deps | Status |
|---|---|---|---|---|---|---|
| HQ bridge | `routes/hq_bridge.py` | backend :8000 | mounted | Opus COO | Scaler Pro HQ auth | integ |
| Gmail→Reddit pipeline | `routes/gmail_reddit_pipeline.py` | backend :8000 | mounted | Reddit Platform Specialist | OAuth client, Reddit account pilot | integ |
| Staffroom integration | `platforms/staffroom.py`, `runner/` | backend :8000 + local runner :4330 | THIS work — wiring in progress | Opus COO | Local Staffroom instance start + bots/connections setup | integ |

## 7 Deployment surface

| Target | Entry point | Current state | Owner |
|---|---|---|---|
| Backend dev | `uvicorn phantom_fleet.api.main:app --port 8000` | running | Release Coordinator |
| Frontend dev | `npm run dev` in `frontend/` on :3016 | running | Release Coordinator |
| Electron desktop | `desktop/dist/Phantom Fleet Setup 0.1.0.exe` | installed under `C:\Program Files\Phantom Fleet\`, running | Release Coordinator |
| Owner runner | `runner/src/runner.mjs` on :4330 | implemented, not yet started | Release Coordinator |
| Local Staffroom | `_staffroom/` clone, port TBD | cloned, not yet started | Release Coordinator |
| Private Tailscale staging | `https://desktop-c74bmhb.tail72dd7e.ts.net:10444` | gateway responds, owner sign-in 502, Live Scouts 401 | Owner (held) |

## 8 Capabilities NOT present in this build

Explicitly called out so the roster can mark their owners as "placeholder":

- **Clipster** content-approval pipeline — the older Fleet had this; the new one does not. The roles Content Specialist / Research Specialist stay in the roster but are flagged **planned**.
- **Live billing** — Stripe wiring exists in Staffroom's env.example but no live keys here. Financial roles stay defensive-only.
- **Public publishing** — no fleet-to-provider publishing path on this checkout.
- **Customer-facing onboarding** — no multi-tenant customer UI yet; roles exist for the owner's own fleet first.
