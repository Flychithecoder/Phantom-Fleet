# Owner runbook — Staffroom pilot

Everything up to "dispatch the mission" is built, installed, and running. The
runbook below is the step list the brief reserves for the owner.

## What's live right now

| Piece | Where | Status |
|---|---|---|
| Fleet backend (`app:app`) | 127.0.0.1:8000 | up (terminal tab c41) |
| Fleet frontend | http://localhost:3016 | up (terminal tab c4) |
| Owner runner | 127.0.0.1:4330 | up (terminal tab c37) |
| Local Staffroom | http://127.0.0.1:4321 | up (terminal tab c39) |
| Fleet Agents panel | http://localhost:3016/agents | shows **STAFFROOM UP** |
| Fleet mission store | `backend/.data/staffroom_missions.sqlite` | SQLite-backed, survives backend restart (phase B done 2026-11-24) |
| Cadence registry | `platforms/staffroom.py` `STANDING_GRANTS` | `fleet_health_sweep_hourly`, `audit_nightly_0200` — stay **disabled** until owner flips `STAFFROOM_CADENCE_LOOP=1` (phase C done 2026-11-24) |

### Phase C — cadence endpoints

| Call | What |
|---|---|
| `GET  /api/platforms/staffroom/cadences` | list cadences + state (`last_dispatched_at`, `disabled`, `due_at`) |
| `POST /api/platforms/staffroom/cadences/toggle` `{grant_name, disabled}` | enable/disable a cadence |
| `POST /api/platforms/staffroom/cadences/tick` `{force}` | run one tick now; dispatches each cadence whose interval has elapsed |

Background loop: set `STAFFROOM_CADENCE_LOOP=1` before `uvicorn …app:app` to
tick every `STAFFROOM_CADENCE_TICK_SECONDS` (default 60s). The loop only
dispatches cadences the owner has explicitly left enabled and whose window
has elapsed. Each dispatch uses a deterministic seed (`cadence:<name>:<window
index>`), so the same window never spawns two missions even if the loop
double-ticks across a backend restart.

### Phase D — Staffroom MCP bridge (runner side wired, token paste remains)

The runner knows how to attach the Staffroom MCP stdio bridge to a `claude`
subprocess, but only when (a) the owner has pasted a scoped token into the
runner env **and** (b) the prompt actually references a Staffroom tool name
(`staffroom_get_project`, `staffroom_list_artifacts`, …). Both guards must
be true, otherwise the call runs without MCP, exactly as phases A–C did.

Env contract (the three are set together or not at all):

```powershell
$env:PF_STAFFROOM_MCP_BRIDGE = "C:\Users\admin\Desktop\PhantomFleet\_staffroom\scripts\staffroom-mcp-stdio.mjs"
$env:PF_STAFFROOM_MCP_URL    = "http://127.0.0.1:4310/mcp"   # Staffroom MCP endpoint
$env:PF_STAFFROOM_MCP_TOKEN  = "sr_mcp_<43-char>"            # from Staffroom Settings → MCP
```

Owner steps (one-time, in Staffroom):
1. Settings → MCP → New client. Label: `phantom-fleet-pilot`. Scope: the
   project you want Fleet to read. Expiry: short (e.g. 24 h).
2. Copy the one-shot `sr_mcp_...` token from the response; it is never shown
   again.
3. Paste it into the runner env above and restart the runner. The health
   endpoint will then show `staffroom_mcp.configured = true` with a token
   hash (never the full token).

What the audit log records per MCP-attached call:
- `mcp_attached: true`
- `mcp_token_hash` (first 8 chars of sha256 of the token) — the raw token
  is never written.

The runner falls back to no-MCP whenever the env is incomplete, the bridge
file is missing, or the token format fails validation (`^sr_mcp_[\w-]{43}$`).

### Phase F — Roster provisioning (21 specialists)

Source of truth: [`scripts/provision-staffroom-roster.mjs`](../../scripts/provision-staffroom-roster.mjs).
Idempotent: a stable `request_id` per role (`pf-role-<slug>-v1`) makes a
second run a no-op; a drifted roster entry returns HTTP 409 and aborts the
script with the offending slug.

Run:

```powershell
$env:STAFFROOM_BASE_URL       = "http://127.0.0.1:4321"
$env:STAFFROOM_SESSION_COOKIE = "staffroom_session=<raw-token>"
node scripts/provision-staffroom-roster.mjs
```

Output file: `backend/.data/staffroom_roster.json` — Fleet reads this on
dispatch to resolve `role=<slug>` into a Staffroom bot id. The Fleet API
surface added:

| Call | What |
|---|---|
| `GET  /api/platforms/staffroom/roster` | the provisioned roster (slug → bot_id, name, role, model_pin) |
| `POST /api/platforms/staffroom/missions/dispatch` with `{role: "<slug>"}` | dispatch against that bot instead of the default COO |

**Verified** 2026-11-24: 21/21 created on first run, 21/21 existing on
second run, unknown-role dispatch rejected with 400, role-targeted
dispatch produced a real Staffroom mission (`f0cc391b-8d99-46e5-a043-
04b94c030980`, operations_coordinator). Local pilot stays read-only: roles
never own device, publishing, or billing actions — those remain gated by
the owner.
| Capability map | [docs/staffroom/00-capability-map.md](00-capability-map.md) | written |
| Team roster | [docs/staffroom/01-team-roster.md](01-team-roster.md) | written |
| MCP matrix | [docs/staffroom/02-mcp-matrix.md](02-mcp-matrix.md) | written |
| Automation backlog | [docs/staffroom/03-automation-backlog.md](03-automation-backlog.md) | written |

## Known blocker: Claude Code OAuth token is expired on this box

A direct subscription probe just now returned:

```
{"is_error":true,"api_error_status":401,"result":"Failed to authenticate. API Error: 401 OAuth access token is invalid."}
```

The runner correctly **blocked** the dispatch (exit 1, audit log entry under
`runner/logs/runner-audit.ndjson`, 502 to Fleet, no paid fallback). This is
exactly the gate the brief asks for.

### Owner step 1 — refresh the Claude CLI session

In a terminal on this Windows box:

```powershell
claude auth login
```

Then confirm:

```powershell
claude auth status
```

Both should report your Max/Pro subscription account and no API-key fallback.

### Owner step 2 — confirm Usage credits are OFF

You already confirmed this earlier. Re-check at **claude.ai → Settings → Usage**
before the first live mission so the runner audit log can cite the state.

### Owner step 3 — set up two Staffroom bots and two connections

1. Open http://127.0.0.1:4321 and sign in (first user becomes the owner).
2. **Settings → Connections → New connection** × 2:
   - Name: `pf-opus-runner`. API key: `pf-opus`. Base URL: `http://127.0.0.1:4330/v1`. Save.
   - Name: `pf-sonnet-runner`. API key: `pf-sonnet`. Base URL: `http://127.0.0.1:4330/v1`. Save.
3. **Bots → New bot** × 2:
   - Name: `COO (Opus)`. Role: `Chief of staff`. Connection: `pf-opus-runner`. Note the bot id.
   - Name: `Worker (Sonnet)`. Role: `Specialist`. Connection: `pf-sonnet-runner`. Note the bot id.
4. In Staffroom, open the COO bot's URL to copy its id, then set the Fleet env:

```powershell
# stop the current backend (tab c41) then:
cd C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone\backend
$env:STAFFROOM_BASE_URL = 'http://127.0.0.1:4321'
$env:STAFFROOM_COO_BOT_ID = '<paste-COO-bot-id>'
uvicorn phantom_fleet.api.app:app --host 127.0.0.1 --port 8000 --reload
```

### Owner step 4 — dispatch the Readiness Review

- Open http://localhost:3016/agents.
- Scroll to the **Staffroom · system of record** panel.
- Click **Launch Readiness Review**.
- Fleet creates a mission on Staffroom with a stable request_id. Retrying is safe — the same workflow seed resolves to the same Staffroom mission id.

### Owner step 5 — approve the plan in Staffroom

- The mission lands in Staffroom with status `needs_approval`.
- Open the **Open in Staffroom** link on the Fleet row.
- Review the plan: 2 assignments (`readiness_summary`, `blocker_ranking`) with no cross-dependency.
- Approve.

### Owner step 6 — verify the end-to-end

After Staffroom runs the mission:

- Fleet row status moves to `running` → `completed`.
- The Staffroom mission view shows the two worker artifacts and the final executive report.
- `runner/logs/runner-audit.ndjson` has 3 entries with `effective_model` starting with `claude-opus` and `claude-sonnet`, and `cost_usd: 0`.

## What stays held

- The Tailscale private staging URL `https://desktop-c74bmhb.tail72dd7e.ts.net:10444/`: owner sign-in is still 502. Phase E of the backlog is on hold until that's restored.
- All Fleet-side writes: still owner-approval only during pilot.
- Physical device actions, publishing, live billing: all off, per CLAUDE.md.

## Deliverables (for the owner to forward)

- **Fleet job link:** http://localhost:3016/agents → row for `pf-readiness_review-<hash>`
- **Staffroom mission link:** http://127.0.0.1:4321/missions/<mission-id> (filled once mission created)
- **Shared mission ID:** `staffroom_mission_id` in the Fleet row equals the `id` in the Staffroom mission view
- **Model and cost evidence:** `runner/logs/runner-audit.ndjson` (effective model, `cost_usd`, duration per call) + `claude auth status` snapshot at run start
