# Prioritized automation backlog

Six phases. Each phase lists **dependencies**, **exact changes**, **acceptance
tests**, and **evidence needed to advance**. Phases A and B are the
local-only pilot (owner-approved). C onward needs new owner approvals called
out at the top of each phase.

Live `10444` route, both live deployments, publishing, billing, and physical
device changes stay on hold until the owner lifts them per-phase.

---

## Phase A — Local pilot: COO + two workers end-to-end

**Why first:** this is the deliverable the brief asks for before anything else
runs. Everything below assumes the pilot proved subscription routing works.

**Dependencies:**
- Owner has verified Usage credits are OFF at claude.ai → Settings → Usage. **Confirmed.**
- `claude auth login` completed on this Windows PC, `claude auth status` reports a signed-in subscription account. **Needs owner on this box.**
- Node 24.14+ installed for the Staffroom clone. **Owner to confirm.**

**Exact changes (in this checkout):**
1. `runner/` — Node runner at 127.0.0.1:4330, Bearer → model pin. **Done.**
2. `backend/phantom_fleet/platforms/staffroom.py` — StaffroomClient + MissionStore. **Done.**
3. `backend/phantom_fleet/api/routes/staffroom_missions.py` — `/api/platforms/staffroom/*` routes. **Pending this phase.**
4. `backend/phantom_fleet/api/app.py` — lifespan init of the store. **Pending.**
5. `frontend/src/app/agents/page.tsx` — Staffroom panel with "Launch Readiness Review" button, mission table, Open-in-Staffroom link. **Pending.**
6. `_staffroom/` — clone with isolated data dir (`.data/pf-pilot`), run on 127.0.0.1:4321, two bots ("COO (Opus)" and "Worker (Sonnet)") configured by owner through Staffroom Settings, two Connections with keys `pf-opus` and `pf-sonnet` pointing at the runner. **Pending owner UI steps.**

**Acceptance tests:**
- A1. `curl http://127.0.0.1:4330/health` returns 200 with `runner`, `models` keys.
- A2. `POST http://127.0.0.1:4330/v1/chat/completions` with `Authorization: Bearer pf-opus` and a trivial message returns a response whose `model` field starts with `claude-opus`.
- A3. Same with `pf-sonnet` returns a `claude-sonnet` model.
- A4. `POST /api/platforms/staffroom/missions/dispatch` with `{workflow:"readiness_review"}` creates a Staffroom mission and returns a Fleet record with matching `staffroom_mission_id`.
- A5. Retrying A4 with the same workflow seed returns the same `staffroom_mission_id` (idempotency).
- A6. The Fleet UI shows the mission row with an "Open in Staffroom" link that opens the correct mission page in the local Staffroom.
- A7. Staffroom's mission view shows two assignments with no `depends_on` between them.
- A8. After both workers return and Opus writes the final report, Fleet's refresh shows `status: completed` and the report excerpt.
- A9. The runner audit log has entries for all three calls (plan, two workers, final) with `cost_usd: 0` or null.
- A10. No `POST /chat/completions` call on the runner was made without a pinned Bearer.

**Evidence to advance:**
- Screenshot of Fleet Agents panel showing one completed mission with the Staffroom link.
- Screenshot of the same mission inside Staffroom with COO plan, two assignments, two artifacts, and the final decision.
- `runner/logs/runner-audit.ndjson` lines for the mission, with effective-model names.
- Confirmation from `claude auth status` captured at the start of the run.

---

## Phase B — Chief manager + Operations Coordinator wired to Staffroom

**Why:** the existing Fleet Chief manager (`agents/managers/chief.py`) already
failed in this session with `ToolNotAllowed: 'db.load_manager_reports'`. Wiring
it to Staffroom as the COO's reporting layer closes that gap.

**Dependencies:** Phase A done. Owner approval to add `db.load_manager_reports`
to the chief's tool registry (read-only DB query of recent manager reports).

**Exact changes:**
1. `agents/base.py` — permit a new read-only tool `db.load_manager_reports`.
2. `agents/managers/chief.py` — on run, propose a Staffroom "operations-coordinator" work item summarising blocked work; attach as an artifact.
3. `routes/staffroom_missions.py` — add `/api/platforms/staffroom/ops/blocked` returning the coordinator's latest artifact.

**Acceptance tests:**
- Chief runs for 60 min without `ToolNotAllowed`.
- Blocked-work digest appears as a Staffroom artifact on cadence.
- Fleet `/ops` page shows the digest with the Open-in-Staffroom link.

**Evidence to advance:** 24h log of Chief runs, Staffroom artifact IDs, and a
sample blocked-work digest.

---

## Phase C — Scheduled cadences (Fleet Health hourly, Audit nightly)

**Needs new owner approval:** permission for the Staffroom scheduler to
dispatch missions without owner approval for these two **read-only** cadences.
Everything else still goes through "Needs you".

**Dependencies:** Phase A done; Staffroom has `scheduler_pro` for cadence
dispatch (already in `routes/scheduler_pro.py`).

**Exact changes:**
1. `routes/scheduler_pro.py` — register two cadences: `fleet_health_sweep` hourly and `audit_nightly` at 02:00 owner-local.
2. `platforms/staffroom.py` — accept `standing_grant: str` on dispatch; refuse unknown grants.
3. `docs/staffroom/02-mcp-matrix.md` — update the standing-permission section.

**Acceptance tests:**
- 72 hours of hourly fleet-health runs with ≤ 1 skipped slot.
- Nightly audit runs 7 days straight with pass rate reported in the briefing.
- Owner sees a daily summary, not per-run notifications.

**Evidence to advance:** cadence run log, briefing with the week's metric.

---

## Phase D — MCP bridge to Staffroom tools (Claude Code CLI client side)

**Why:** gives COO and specialists direct scoped reads of Staffroom projects
and artifacts via the documented stdio bridge, rather than Fleet-mediated
proxying.

**Dependencies:** Phase A proven; `_staffroom/scripts/staffroom-mcp-stdio.mjs`
reviewed; one-time MCP token issuance in Staffroom Settings.

**Exact changes:**
1. `runner/src/mcp.mjs` — invoke `claude mcp add --transport stdio --scope local staffroom-pilot -- node $BRIDGE` on provisioning.
2. `runner/src/runner.mjs` — when the pinned model is called with messages that reference Staffroom resources, pass the MCP server to the subprocess.
3. `docs/staffroom/02-mcp-matrix.md` — move cells from `—` to `R` where this exposes real reads.

**Acceptance tests:**
- A COO call that references `staffroom_get_project` actually reads the local project.
- A worker without the right grant receives a Staffroom-side 403.

**Evidence to advance:** MCP tool-call trace captured from `--output-format stream-json`.

---

## Phase E — Tailscale private staging live-mission

**Needs new owner approval:** owner sign-in at `https://desktop-c74bmhb.tail72dd7e.ts.net:10444/`
currently returns 502; Live Scouts returns 401. Phase E does not start until
sign-in is restored and the runner here can reach the private host.

**Dependencies:** Phase A green locally. Phases B–D optional.

**Exact changes:**
1. Fleet `platforms/staffroom.py` — accept `STAFFROOM_BASE_URL` env; default swings from loopback to the Tailscale URL only when the owner sets it.
2. New Staffroom Connection on the private instance pointing at the local runner (over Tailscale) — or a second runner co-located with Staffroom.
3. Readiness Review mission re-dispatched against the private instance.

**Acceptance tests:**
- Fleet creates a mission on the private instance with matching mission ID.
- Final report visible in both apps at the same time.
- Runner audit log shows the same three-call pattern.

**Evidence to advance:** Fleet job link, Staffroom mission link, shared ID,
model/cost evidence. **This is the milestone the brief names.**

---

## Phase F — Role expansion: all 21 specialists wired

**Dependencies:** Phase E proven; Staffroom bot creation scripted.

**Exact changes:**
1. `scripts/provision-staffroom-roster.mjs` — idempotent script to create / update the 21 bots from the roster doc.
2. `routes/staffroom_missions.py` — accept `role` on dispatch, route to the matching bot.
3. Fleet UI — each role gets a card in `/agents` showing its KPI + last mission.

**Acceptance tests:**
- All 21 bots present in Staffroom.
- Each role has at least one successful mission in the week after provisioning.

**Evidence to advance:** per-role mission log, per-role KPI chart in briefing.
