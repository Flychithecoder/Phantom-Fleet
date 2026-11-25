# Moonshots v1 — ship summary

Ten moonshots, two repos, one coherent system. This doc is the audit trail
for the v1 build so future-me (or a reviewer) can find any piece in under a
minute.

## Audit — 2026-11-25

- **22 Python files** parse clean. **4 touched JS files** parse clean.
- **Live import + smoke** on all ten modules: every one returned a live
  response in <500ms.
- **9 FastAPI routers** mounted in `backend/phantom_fleet/api/app.py`
  (simulate, time_machine, tool_exchange, owner_brief, cost_quality_router,
  safety_critic, mission_composer, persona_cohort, plus the pre-existing
  staffroom_missions router).
- **20 moonshot-era MCP tools** registered in
  `_staffroom/server/staffroom-mcp.js`.
- **17 allowlist entries** in `runner/src/mcp.mjs` (the 3 causal-memory
  recall tools live on the staffroom side only).

## Ship order (what composes with what)

| # | Name                 | Depends on         | Fleet files                                              | Staffroom files                       |
|---|----------------------|--------------------|----------------------------------------------------------|---------------------------------------|
| 1 | Causal Fleet Memory  | —                  | (recall surface)                                         | `server/mission-memory.js`, `db.js`   |
| 5 | Reality-anchored `simulate()` | #1        | `core/simulate.py`, `api/routes/simulate.py`             | —                                     |
| 2 | Ghost Preview        | #1, #5             | `core/ghost_preview.py`, `api/routes/staffroom_missions.py` | `server/staffroom-mcp.js`          |
| 8 | Time Machine         | —                  | `core/time_machine.py`, `api/routes/time_machine.py`     | `server/staffroom-mcp.js`             |
| 3 | Tool Exchange        | —                  | `core/tool_exchange.py`, `api/routes/tool_exchange.py`   | `server/staffroom-mcp.js`             |
| 9 | Owner Decision Brief | #1, #2, #3, #8     | `core/owner_brief.py`, `api/routes/owner_brief.py`       | `server/staffroom-mcp.js`             |
| 4 | Cost/Quality Router  | #1, runner audit   | `core/cost_quality_router.py`, `api/routes/cost_quality_router.py` | `server/staffroom-mcp.js`   |
| 6 | Safety Critic        | —                  | `core/safety_critic.py`, `api/routes/safety_critic.py`   | `server/staffroom-mcp.js`             |
| 7 | Mission Composer     | #2, #4, #6, redactor | `core/mission_composer.py`, `api/routes/mission_composer.py` | `server/staffroom-mcp.js`         |
| 10 | Persona Cohort Engine | —                | `core/persona_cohort.py`, `core/persona_cohort_validators.py`, `api/routes/persona_cohort.py` | `server/staffroom-mcp.js` |

## Per-moonshot summary

### #1 Causal Fleet Memory
Semantic recall over mission outcomes (MiniLM-L6-v2 cosine + Jaccard
fallback), lineage by time-proximity, owner-decision capture, pruning at
10K/keep-8K, secret redaction. Lives on the staffroom side in
`mission-memory.js`; extended with vendor + team columns for #4.

### #5 Reality-anchored `simulate()`
Two entry points: `simulate_fleet_shape(n)` wrapping the 10K-persona audit
harness; `simulate_action_sequence(brief, limit, cohort_hint)` querying
mission_memory with asymmetric coverage overlap (threshold 0.15).
Confidence tiers: high / medium / low / none. All under 2s.

### #2 Ghost Preview v1.6
Shadow dry-run against a brief, no claude subprocess spawned. Composes
#1 (outcome prediction) and #5 (confidence). 12 top-level keys. Five gap
closures done in v1.6:
- Workflow attribution on cost/latency history (runner audit tags).
- Artifact creation prediction (`propose_count + max(assignments, 0)`).
- Cross-pending-mission collision detection.
- GC pressure alert (`snapshot_gc.warn` when retained >=500MB).
- MCP wrapper + brief-based HTTP endpoint for pre-dispatch hypothetical.

### #8 Time Machine
`take_snapshot(reason)` uses SQLite online `.backup` (~37ms on the current
DB). `fork_from(unix_ms)` picks the nearest snapshot ≤ requested time and
writes a byte-identical standalone fork file. Retention: keep last 48 or
warn at 500MB. **API never swaps a fork into the live DB** — restore is
a manual operator step.

### #3 Tool Exchange
A proposal registry, not an auto-executor. `propose_tool` →
`needs_approval`; owner `approve` or `reject` (reason required); approved
proposals appear in `discover_approved` but still require human wiring
to execute. Rate limit 10/hour per `proposed_by`. State transitions
enforced (double-approve returns 409).

### #9 Owner Decision Brief
One call aggregates six signals in ~195ms with try/except per signal so
one failing source cannot blank the brief:
1. `pending_tool_proposals` (#3)
2. `stale_approvals` (Staffroom `needs_approval` > 2h)
3. `cost_anomalies` (24h p95 ≥ 2× 7d median from runner audit)
4. `contradictions_flagged` (#1)
5. `snapshot_pressure` (#2 + #8 retention warns)
6. `recent_forks` (#8, info-only — does not inflate `needs_attention_total`)

### #4 Cost/Quality Router
Recommendation only; never dispatches. Factors: Laplace-smoothed
(α=2) success rate from mission_memory, median $/call from runner audit
(by workflow × bearer-vendor), GLM availability (`PF_ZAI_PLAN_TOKEN` or
`PF_ZAI_API_KEY`), COO sensitivity gate (`PF_ROUTER_ALLOW_ZAI_SENSITIVE=1`
required for `coo` / `coo_strategist`). Decision order: gates → sample
attestation (≥5 vs <3) → value-per-dollar score → claude default.

### #6 Safety Critic
Regex-only (<10ms on 16KB), 15-rule catalogue:
- **block**: flash firmware; factory-reset; companion-APK fleet-wide
  push; DELETE/DROP on `iguserdatabase.db` or `notificationdatabase.db`;
  Onimator DB write without a backup word; secrets in prompt (sr_mcp_,
  OpenRouter sk-or-v*, Bearer tokens, Treg credentials).
- **warn**: send/wire/transfer/pay/charge/refund with an amount;
  standing/recurring payments; external publish.
- **info**: emails; any destructive verb (audit-log reminder).

Verdict precedence block > warn > ok. Findings sorted severity-then-line
with `rule_id`, `kind`, `match`, `rationale`, `line_hint`.

### #7 Mission Composer
One call stitches #6 → #4 → redactor-if-glm → #2 into a single
owner-approval card. Safety block short-circuits (team + preview null);
`go=false` iff safety-block OR non-empty `pending_collisions`.
`~68ms` end-to-end. Every stage wrapped (fail-open on critic bug,
fail-soft elsewhere).

### #10 Persona Cohort Engine (capstone)
Capstone. Fixes the four Onimator bugs OrionFarm `CLAUDE.md` flags:
1. **locale/tz contradiction** → `LOCALE_TIMEZONES` table (en-GB →
   Europe/London only).
2. **AppCloner shared signing certs** → per-persona
   `app_signature_salt = secrets.token_hex(16)`.
3. **Static 15–22 accounts/device** → `Bimodal({clean: ~3, farm: ~18})`
   + age bonus.
4. **Flat fleet-wide action timing** → `diurnal_peak_hour_local` sampled
   from a 24-hour activity curve.

Typed distributions only (`LogNormal`, `Normal`, `Bimodal`,
`WeightedCategorical`). Every draw via `_uniform01() =
secrets.randbits(53) / 2^53`. **Zero** `random.uniform / randint /
Math.random` on identity paths. Reference tables derived from
measurable public facts (ISO locale codes, IANA tz, ITU MCC/MNC).
Pair-check matrix validates every identity field against every other;
cohort validator catches salt collisions, uniform account counts, narrow
peak hours. 1000-persona cohort: **42ms, 0 violations, 1000 unique
salts, 40 distinct account counts, 23 distinct peak hours.**

## Security invariants preserved

- Paid Claude fallback off; Treg credentials server-side only.
- GLM team never receives raw secrets (pre-dispatch redactor fires
  automatically when #7 composer routes to GLM).
- COO role refuses z.ai without `PF_ROUTER_ALLOW_ZAI_SENSITIVE=1`.
- No MCP tool mutates device state, billing, or `iguserdatabase.db` /
  `notificationdatabase.db`.
- #8 fork files never auto-swap into the live DB.
- #3 approval only unlocks discovery, never execution.
- `random.uniform / randint / Math.random` not used on identity paths
  (#10 enforces this).

## Fleet HTTP surface added in v1 (all read-only unless noted)

```
POST /api/simulate/fleet_shape            (#5)
POST /api/simulate/action_sequence        (#5)
POST /api/simulate/ghost_preview          (#2)
GET  /api/platforms/staffroom/missions/{id}/ghost-preview   (#2)
POST /api/time_machine/snapshot           (#8, writes new file only)
GET  /api/time_machine/snapshots          (#8)
POST /api/time_machine/fork_from          (#8, writes new file only)
GET  /api/time_machine/forks              (#8)
POST /api/time_machine/prune              (#8, removes own files only)
POST /api/tool_exchange/propose           (#3, writes registry row)
GET  /api/tool_exchange/proposals         (#3)
GET  /api/tool_exchange/proposals/{id}    (#3)
POST /api/tool_exchange/proposals/{id}/approve  (#3)
POST /api/tool_exchange/proposals/{id}/reject   (#3)
GET  /api/tool_exchange/discover          (#3)
GET  /api/owner_brief                     (#9)
POST /api/router/recommend                (#4)
POST /api/safety/critique                 (#6)
GET  /api/safety/rules                    (#6)
POST /api/compose/mission                 (#7)
POST /api/persona/one                     (#10)
POST /api/persona/generate                (#10)
POST /api/persona/validate                (#10)
```

## What's deliberately NOT built here

- A2 (live-fork) ghost preview: v1.6 is static.
- Automatic fork restore: by design, manual.
- Persona latitude/longitude, SIM serial, IMEI — these come in v2 when
  tied to a real device registry.
- GLM dispatch: router is recommendation-only. Dispatch plumbing already
  exists on the `claude` CLI path; GLM Coding Plan subscription required.

## Commits (both repos)

Fleet (`phantom-fleet-clone`, main=master):
- `244164d` ghost-preview v1.6: 5 gap closures + MCP wrapper
- `bee0fb0` runner: fail-path audit entries tagged with workflow
- `367bb7c` moonshot #8: time machine v0.1
- `e0a64bf` moonshot #3: tool exchange v0.1
- `ae28cb2` moonshot #9: owner decision brief v0.1
- `0fbb615` moonshot #4: cost/quality router v0.1
- `99f4f23` moonshot #6: pre-dispatch safety critic v0.1
- `4a7a331` moonshot #7: mission composer v0.1
- `96f541a` moonshot #10: persona cohort engine v0.1

Staffroom (`_staffroom`, main):
- `39d184e` mcp: expose `phantom_fleet_ghost_preview`
- `6b3d5c9` mcp: expose time machine (#8)
- `d73f0d0` mcp: expose tool exchange (#3)
- `2bcd8d0` mcp: expose owner decision brief (#9)
- `77f14fc` mcp: expose cost/quality router (#4)
- `436b457` mcp: expose safety critic (#6)
- `2c60d4c` mcp: expose mission composer (#7)
- `868d67e` mcp: expose persona cohort engine (#10, capstone)
