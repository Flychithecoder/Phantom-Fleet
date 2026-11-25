# Research access through Staffroom MCP — pilot design

**Status (2026-11-24):** design + Fleet-side wiring done. **Blocked on owner
action**: mint Fleet-scoped `sr_mcp_...` token in Staffroom Settings and
paste into runner env. See [04-owner-runbook.md](04-owner-runbook.md) §Phase
D.

## What's live in Staffroom today

Read from `_staffroom/STAFFROOM_MCP.md`, `_staffroom/STAFFROOM_TOOL_GATEWAY.md`,
`_staffroom/server/treg-research.js`, `_staffroom/server/treg-transport.js`.

### Live (enabled by default once `STAFFROOM_MCP_ENABLED=true`)

| Capability | Where | Notes |
|---|---|---|
| MCP endpoint + scoped tokens | `server/staffroom-mcp.js` `installTransport` | 24h expiry, revocable, project or workspace scope |
| Tool catalog discovery | MCP `staffroom_workspace`, `staffroom_list_projects`, `_get_project`, `_list_bots`, `_list_chats`, `_read_chat`, `_list_pending_decisions`, `_get_run`, `_read_artifact` | Read-only project/workspace reads |
| Propose work (handoff) | MCP `staffroom_propose_work` | Owner approval card in **Needs you** |
| Computer actions (approval-gated) | MCP `staffroom_request_computer_action`, `_get_computer_action` | Owner approves each op; held per computer |
| Tool gateway discovery | HTTP `GET /api/tools/capabilities`, `/api/tools/catalog` | Public catalog metadata, opaque Staffroom IDs |
| Tool jobs (quote / approval / receipt) | HTTP `/api/tools/*`, catalog-priced | **Simulation adapter only** for execution |
| Saved search attachments | HTTP `/api/search-attachments/*` | Idempotent per project, bounded evidence |
| Treg transport (server-side only) | `server/treg-transport.js` | Enforces `https://treg.to/call/...`, Idempotency-Key, X-Treg-Route-Max-Cost, backend customer attribution. Credentials never leave the server. |

### Live but narrowly scoped

| Capability | Where | Scope |
|---|---|---|
| Treg research pilot | `server/treg-research.js` | **Only** the "Viral Content Finder → Brand & Shop Scout" handoff in one configured project. Endpoint hard-wired to `tikhub.tiktok.search.videos`, `max_micro=1000` ($0.001), count=5, region US. Gated by `scope.token && config.live`. Owner approves `{confirm:true, max_micro:1000}` per call. Produces a receipt + handoff message in both chats. |

### Simulated (no live calls today)

Per `STAFFROOM_TOOL_GATEWAY.md`: "All new execution is simulation-only in
this release. New per-tool retail prices have not been approved; unpriced
operations fail closed." The injected simulation adapter supports
execution, pending results, holds, failure settlement, ambiguous outcomes,
overrun freezes — against fixtures, not live endpoints.

### Missing (named in the brief, not in the catalog today)

| Brief capability | Status | Reason |
|---|---|---|
| Internet search (no-cost route) | **not implemented** | Only `treg.to` is wired; no generic search provider |
| Page reader (fetch a public URL, capture text/title/canonical/retrieval time) | **not implemented** | No URL-fetch tool in MCP catalog |
| Site crawler (bounded follow-links on an approved domain) | **not implemented** | No crawler in MCP catalog |
| Broad Treg access for the 21 roles | **not implemented** | `treg-research.js` is wired to one project and one bot pair |
| Per-role tool budgets | **not implemented** | Tool gateway has per-org budgets; no per-role split |

## Pilot design (keeps private Tailscale `:10444` held)

### Guardrails taken from the brief

1. **Claude paid fallback stays OFF.** Runner's `--no-paid-fallback` behavior is unchanged; a failed `claude` call returns 502.
2. **Treg stays server-side with its existing receipts.** Credentials remain in `treg-transport.js`. Any live Treg call Fleet triggers must come through the existing `/api/treg-research/:id/approve` path with its max-cost + receipt check.
3. **Pilot uses no-cost routes + saved/simulated results.** No live internet-search or crawler provider is contracted; Fleet will drive the simulation adapter until the owner names a provider and approves a cap.
4. **Workspace / mission / role / tool / destination permissions are checked before dispatch.** The Fleet dispatch path validates `role ∈ roster`, the role has a declared research grant, the destination (if any) is on the allowlist, and the standing budget is non-zero.
5. **Private network addresses + local files blocked.** Any URL in a research request is rejected if it resolves to RFC1918, loopback, link-local, metadata IPs, or `file:` / `chrome:` / `data:` schemes.
6. **Redirects validated before following.** Honored at the page-reader / crawler level in simulation adapter.
7. **Signed-in sources require a separately approved connector + scope.** None are enabled for the pilot.
8. **Instructions in retrieved pages are treated as untrusted content** — same rule as system prompt text.

### Role × research-tool matrix

Per-role budget (`max_micro_per_day`) is informational in the pilot — the
live tool gateway enforces its own org-level cap. The destination allowlist
is a proposal that becomes authoritative once the owner approves it in
Staffroom Settings.

| Role slug | Treg scopes | Internet search | Page reader | Site crawler | Budget / day |
|---|---|---|---|---|---|
| `opus_coo` | discovery + review of worker evidence only | ✓ (plans + verifies) | ✓ | — | 10,000 µ$ |
| `operations_coordinator` | — | ✓ | ✓ | — | 2,000 |
| `device_inventory` | — | ✓ (model/OS lookups) | ✓ | — | 1,000 |
| `fleet_health` | — | ✓ | ✓ | — | 1,000 |
| `maintenance_coordinator` | — | ✓ | ✓ | — | 1,000 |
| `incident_triage` | — | ✓ | ✓ | ✓ (vendor status pages) | 3,000 |
| `recovery_specialist` | — | ✓ (restore-tool docs) | ✓ | — | 1,000 |
| `product_ops_lead` | `tikhub.*` (market signal) | ✓ | ✓ | ✓ (competitor site, ≤50 pages) | 4,000 |
| `engineering_specialist` | — | ✓ (docs) | ✓ | — | 2,000 |
| `qa_lead` | — | ✓ | ✓ | — | 1,000 |
| `release_coordinator` | — | ✓ | ✓ | — | 1,000 |
| `data_quality` | — | ✓ | ✓ | — | 500 |
| `operations_analyst` | — | ✓ | ✓ | ✓ (≤20 pages) | 2,000 |
| `executive_reporting` | review of others only | — | — | — | 0 |
| `access_reviewer` | — | ✓ | ✓ | — | 500 |
| `compliance_reviewer` | — | ✓ | ✓ | — | 500 |
| `onboarding_specialist` | — | ✓ | ✓ | — | 1,000 |
| `support_triage` | — | ✓ | ✓ | — | 1,000 |
| `customer_success` | `tikhub.*` | ✓ | ✓ | — | 2,000 |
| `cost_analyst` | — | ✓ (pricing pages) | ✓ | — | 500 |
| `reconciliation_specialist` | — | ✓ | ✓ | — | 500 |

Treg scopes map to the project Staffroom already restricts
`treg-research.js` to. Workers outside the two configured bots (`Viral
Content Finder`, `Brand & Shop Scout`) receive a 404 from the existing
`channelScope()` check — they can't initiate a Treg call even if a prompt
asks them to.

### What Fleet needs to do once the owner MCP token is pasted

1. **Add `research_review` workflow** (Fleet side) — prompt tells the COO to decompose into two specialist assignments whose task text explicitly says "use Staffroom MCP tools (`staffroom_get_project`, `staffroom_read_artifact`) to pull context, then save findings via `staffroom_propose_work`". This alone trips the runner's `needsStaffroomMcp` check and attaches the bridge.
2. **Save findings into the same Staffroom mission** — Staffroom's `_propose_work` + its mission `result` field already hold free-form text. Fleet's `MissionStore.refresh` already carries `result_excerpt` and `events`; the role card's Open-in-Staffroom link already resolves to the mission view where receipts live.
3. **Audit cross-call dedup** — on every call the runner already computes a `prompt_hash`; a research review that re-runs within one mission replays identical worker prompts and should hit the Staffroom catalog cache. The runner's audit log records `prompt_hash` + `cost_usd` so Fleet can reconcile.

## First acceptance test (queued)

**Goal:** one mission where the COO + two Sonnet workers use Treg through
Staffroom MCP; findings saved to Staffroom; receipts visible in both Fleet
and Staffroom after reload.

**Preconditions (owner action required):**
1. Mint `sr_mcp_...` token in Staffroom Settings → MCP, scoped to a project
   Fleet can read. **Set runner env** `PF_STAFFROOM_MCP_URL`,
   `PF_STAFFROOM_MCP_TOKEN`, `PF_STAFFROOM_MCP_BRIDGE` (see runbook).
2. Confirm `STAFFROOM_MCP_ENABLED=true` on the local Staffroom
   (`c43 _staffroom` tab already has this set). ✓
3. Confirm `config.live=false` on the Staffroom env (keeps
   `treg-research.ready()` false → saved/simulated path). ✓

**Steps:**
1. Dispatch `research_review` workflow with `role=opus_coo`.
2. Approve brief → COO plans with Staffroom MCP attached (runner audit
   shows `mcp_attached: true`).
3. Each worker calls `staffroom_get_project` + `staffroom_read_artifact`
   for context; each independently queries the simulation adapter for one
   internet-search + one page-read + optionally one bounded crawl, with
   `max_pages`, `max_depth`, `max_concurrency`, `per_domain_cap`.
4. Workers call `staffroom_propose_work` with `brief` = their cited
   findings. Owner approves each. Staffroom saves the artifact + receipts.
5. COO reviews, writes final report that cites each worker's artifact id.
6. Mission `completed`. Fleet row refreshes. Role cards show `last:
   completed` with Open-in-Staffroom link.

**Unauthorized checks (must deny before any provider dispatch):**
- A role without the grant for `site_crawler` that proposes a crawl → MCP
  returns 403 (catalog-side) **or** the runner declines to attach MCP (no
  tool in the prompt will match `needsStaffroomMcp`).
- A cross-workspace request: issuing an `sr_mcp_...` token scoped to
  project A and then referencing project B's artifact → Staffroom 404 per
  `same-workspace isolation test` in `tests/staffroom-mcp.test.js:L168`.
- A page-reader request to `127.0.0.1`, `169.254.169.254`, or `file://` →
  blocked at the research adapter before any transport call.

**Return** (what the acceptance test produces):
- Fleet job link: `http://localhost:3016/agents` (role card for `opus_coo`)
- Staffroom mission link: `http://127.0.0.1:4321/missions/<id>`
- Which checks used **live** vs **saved** vs **simulation**:
  - COO + worker Claude calls: **live** (subscription, no paid fallback)
  - Staffroom MCP reads (`staffroom_get_project`, `staffroom_read_artifact`): **live** (local Staffroom)
  - Internet search / page reader / crawler: **simulation** (Staffroom's existing fixture adapter)
  - Treg: **saved** fixture (`ready()` = false while `config.live=false`)

## Files touched / to touch

- Backend workflow: `backend/phantom_fleet/platforms/staffroom.py`
  `WORKFLOWS["research_review"]` (next PR — gated on owner MCP token)
- Runner: no changes; `mcp.mjs` `needsStaffroomMcp` already matches
  Staffroom tool names
- Docs: this file; runbook §Phase D; roster has the role list

## Not in scope here (held)

- Live Treg call cap approval for a role other than the existing pilot
- Any change to the private Tailscale `:10444` route
- Enabling `STAFFROOM_MCP_SHELL` or `STAFFROOM_MCP_VM_ACTIONS` (both default off; stay off for this pilot)
