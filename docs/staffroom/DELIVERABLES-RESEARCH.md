# Research-through-Staffroom-MCP — delivery status

## What's done this turn

**Design** · [05-research-access.md](05-research-access.md): maps Staffroom's
live capabilities (MCP catalog, tool gateway, Treg transport with receipt
check) against the brief; names what is **live** (MCP endpoint + 13
tools, tool gateway, `treg-transport.js`), **narrowly scoped live** (the
Treg research pilot, hard-wired to one project and one bot pair), **simulation**
(all new tool gateway execution, per `STAFFROOM_TOOL_GATEWAY.md`), and
**missing** (internet search, page reader, site crawler — not in the Staffroom
catalog today).

**Fleet backend** · `backend/phantom_fleet/platforms/staffroom.py`:
- Added `research_review` workflow. Its prompt explicitly names
  `staffroom_get_project`, `staffroom_read_artifact`, `staffroom_propose_work`
  so the runner's `needsStaffroomMcp` check attaches the MCP bridge for every
  subprocess on a research mission.
- Added `RESEARCH_GRANTS` — the 21-role × 4-tool × budget matrix. Any
  `research_review` dispatch validates the role's grant **before** calling
  Staffroom:

```
dispatch research_review role=executive_reporting
  → 400 "role 'executive_reporting' has no research grant"
dispatch research_review role=product_ops_lead
  → 201 Staffroom mission 8393656f-bfe4-43cf-acbd-04f3668e074c created
```

**Fleet API surface** · `backend/phantom_fleet/api/routes/staffroom_missions.py`:
- `GET /api/platforms/staffroom/research-grants` → 21 roles with
  `{internet_search, page_reader, site_crawler, treg, budget_micro_per_day}`

**Runner** · no changes needed. Phase D already loads the MCP spec and
attaches the stdio bridge for prompts that reference Staffroom tool names;
the new `research_review` prompt is the only workflow where that triggers.

## What needs the owner before the first live acceptance run

The acceptance test the brief names ("one mission where the COO and both
Sonnet workers use Treg through Staffroom MCP") requires live MCP reads of
the local Staffroom. Those need a scoped `sr_mcp_...` token Fleet can hold.
That token can only be minted in Staffroom's owner UI — Fleet can't bypass
it, and the runner correctly runs without MCP when the env isn't set.

**Owner steps (one-time):**
1. In local Staffroom at http://127.0.0.1:4321, Settings → MCP → New client.
   Label `phantom-fleet-research`, scope: the project Fleet will read.
   Expiry: 24h.
2. Copy the one-shot `sr_mcp_...` token.
3. In the runner shell, set env and restart the runner:

   ```powershell
   $env:PF_STAFFROOM_MCP_BRIDGE = "C:\Users\admin\Desktop\PhantomFleet\_staffroom\scripts\staffroom-mcp-stdio.mjs"
   $env:PF_STAFFROOM_MCP_URL    = "http://127.0.0.1:4321/mcp"
   $env:PF_STAFFROOM_MCP_TOKEN  = "sr_mcp_<43-char>"
   ```

4. Confirm: `curl http://127.0.0.1:4330/health` → `staffroom_mcp.configured:
   true` with a token hash.

Then the queued research mission can be approved and will run under live MCP.

## Queued mission (awaiting approval)

| Field | Value |
|---|---|
| Fleet request_id | `pf-research_review-bd3c843650e49416` |
| Staffroom mission id | `8393656f-bfe4-43cf-acbd-04f3668e074c` |
| Role | `product_ops_lead` |
| Status | `needs_approval` |
| Workflow | `research_review` |
| Open in Staffroom | http://127.0.0.1:4321/missions/8393656f-bfe4-43cf-acbd-04f3668e074c |
| Open in Fleet | http://localhost:3016/agents (row for `pf-research_review-bd3c843650e49416`) |

**Intentionally not approved this turn** because without the MCP token the
workers can't actually use Staffroom tools, which would make the
acceptance evidence misleading. After the token paste, approve this one:
its workers will exercise the full flow and produce the receipts the brief
asks for.

## What each check uses (per the brief's format)

| Check | Pilot run |
|---|---|
| Claude COO / review calls | **live** (subscription, paid fallback OFF) |
| Claude worker calls | **live** (subscription, paid fallback OFF) |
| Staffroom MCP reads (`staffroom_get_project`, `_read_artifact`) | **live** against local Staffroom — once owner token is pasted |
| `staffroom_propose_work` approvals | **live** (owner approves each in Needs you) |
| Internet search / page reader / site crawler | **simulation** (Staffroom's existing fixture adapter; no provider contracted) |
| Treg | **saved** (fixture; `treg-research.ready()` = `config.live && scope.token` which is false by design in the pilot) |

## Guardrails in effect

- Paid fallback OFF on Claude (runner returns 502 on failure, no reroute).
- Treg credentials stay in `_staffroom/server/treg-transport.js`.
- No change to the private Tailscale `:10444` route (held).
- No change to live deployments (held).
- Any URL a research tool receives is validated against private-IP /
  loopback / link-local / `file://` / `chrome://` / `data:` before the
  transport is invoked (the simulation adapter today enforces this; a live
  provider would require the same check wired in Staffroom before the
  transport call).
- Signed-in sources require a separately approved connector + scope — none
  enabled for the pilot.
