# Two-team A/B runbook (Claude vs GLM)

Phantom Fleet now ships two parallel Staffroom teams. Pick which team
runs a mission at dispatch time. Memory, recall, and scoring are tagged
by vendor/team so the Causal Fleet Memory outcome log can score A/B
performance.

## Team layout

| Team | Vendor | COO | Workers | Auth | Endpoint |
|---|---|---|---|---|---|
| `claude` (default) | anthropic | claude-opus-4-7 | claude-sonnet-4-6 | signed-in CLI | Anthropic |
| `glm` | zai | glm-5.4 | glm-4.6 | GLM Coding Plan key | `https://api.z.ai/api/anthropic` |

Both teams run through the **same `claude` CLI**. The GLM team uses the
`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` swap, so all MCP wiring,
`--allowedTools`, and the Causal Fleet Memory tool chain work unchanged —
**pending** the smoke test confirming z.ai honors `tool_use` round-trips.

## One-time provisioning

```powershell
# Claude team (already provisioned in your current state)
$env:STAFFROOM_SESSION_COOKIE = "staffroom_session=<raw-token>"
node scripts/provision-staffroom-roster.mjs
```

```powershell
# GLM team — creates the parallel bots
$env:STAFFROOM_SESSION_COOKIE = "staffroom_session=<raw-token>"
node scripts/provision-staffroom-glm-team.mjs
```

Writes `backend/.data/staffroom_roster_glm.json`.

## Runner env (GLM path)

Add to `backend/.env`:

```
PF_ZAI_PLAN_TOKEN=<GLM Coding Plan key>
PF_ZAI_ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
```

Runner restart picks these up on first `pf-glm-plan` / `pf-glm-plan-max`
bearer call.

## Smoke-test MCP through z.ai

Before running real missions on the GLM team:

```powershell
$env:PF_ZAI_PLAN_TOKEN = "<plan key>"
node scripts/smoke-test-glm-mcp.mjs
```

Exit 0 + "model echoed back: YES" means MCP round-trips work and the
Causal Fleet Memory tool chain (`staffroom_recall_similar`,
`staffroom_recall_contradictions`, `staffroom_recall_lineage`) will
function on the GLM team. Exit 1 means we need an MCP → function-call
adapter before proceeding.

## Dispatch (pick a team)

```powershell
# Claude team (default — omit `team` for identical behavior)
curl -X POST http://127.0.0.1:8000/api/platforms/staffroom/missions/dispatch `
  -H "Content-Type: application/json" `
  -d '{"workflow":"research_review","seed":"ab-test-01","team":"claude"}'

# GLM team
curl -X POST http://127.0.0.1:8000/api/platforms/staffroom/missions/dispatch `
  -H "Content-Type: application/json" `
  -d '{"workflow":"research_review","seed":"ab-test-01","team":"glm"}'
```

GLM-team briefs are pre-redacted by
`backend/phantom_fleet/core/brief_redactor.py` — secrets, Authorization
headers, env paths, owner emails, and known fleet DB names are replaced
by shape before the brief crosses the wire.

## A/B scoring

Each `mission_memory` row now carries `vendor`, `team`, and `model_id`.
Compare matched pairs:

```sql
SELECT team, vendor, outcome, COUNT(*) AS n,
       AVG(CASE WHEN owner_decision='approved' THEN 1.0 ELSE 0.0 END) AS approve_rate
FROM mission_memory
WHERE created_at > datetime('now', '-7 days')
GROUP BY team, vendor, outcome;
```

Approval rate is the headline metric. Worker-contradiction density
(rows where `recall_contradictions` returned overlap &lt;0.5) is the
quality floor.

## Safety posture

- GLM team **never** receives raw secrets (pre-dispatch redactor)
- GLM team's COO has a hard 8K thinking token budget baked into
  `instructions` to prevent the "marathon thinking" failure mode
- The `model_router.py` sensitivity gate still refuses
  `PF_ROUTER_ROLE_COO=zai` unless `PF_ROUTER_ALLOW_ZAI_SENSITIVE=1`
  (that env path is the API router, not the CLI team path; the CLI
  team path's safety layer is the redactor + the GLM team's own
  bot-level instructions)
- Audit logs tag `vendor` on every `mission_memory` insert — grep the
  log to confirm the right team ran each mission

## Deprovision / rollback

To decommission the GLM team temporarily: stop dispatching with
`team:"glm"`. The bots stay in Staffroom (keep their chat history).
To hard-remove: delete the GLM team's bot rows via Staffroom's UI and
delete `backend/.data/staffroom_roster_glm.json`.
