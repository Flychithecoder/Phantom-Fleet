# OrionFarm — Claude Code instructions

**Panel:** OrionFarm — physical device farm automation + hybrid mobile-API router
**Port:** 3016
**Depends on:** Scaler Pro ecosystem (HQ, Chat AI, ModelForge, Content Vault, unified model registry, cross-panel proxy sharing)
**Complements (does not replace):** `meta/`, `instagram/`, `threads/`, `reddit/`, `x-panel/`, `tiktok/`

---

## Read these first

Before any work in this panel, read:
1. `PLAN.md` — full executive plan, 5-layer architecture, phases, $100M business model
2. `HARDWARE.md` — fleet intel, root status, Wi-Fi ADB, known fleet-cluster bugs, Onimator stack analysis
3. Global `~\.claude\CLAUDE.md` — scale-level audit rule + agent audit rule. Both apply here with full force.

---

## Hard rules specific to OrionFarm

### Distribution discipline
- `random.uniform()`, `random.randint()`, `Math.random()` are **lint-banned** on any code path that touches persona identity, fingerprint fields, scheduling, or inter-action delays.
- Every random value must come from a typed distribution class: `LogNormal`, `Normal`, `Bimodal`, `WeightedCategorical`. The distribution parameters must be derivable from real-world measurements — not guessed.
- Use `secrets.randbits()` / `crypto.randomBytes()` as the underlying entropy source for anything uniqueness-contributing. Never seed from `time()` or process state.

### Fleet-scale audit gate
- The 10,000-persona Monte Carlo harness is a **required CI check**. No PR merges with a failing audit run.
- The 10 cluster-analysis checks from global CLAUDE.md are not optional — all 10 must pass.
- Any new persona field, fingerprint dimension, or action primitive requires an audit-harness test case covering its distribution shape.

### Cross-field consistency
- If a persona claims a locale, the timezone must be consistent with the locale.
- If a persona claims a device model, the OS version must be in the range that model actually shipped with.
- If a persona claims a carrier, the HNI must match that carrier and country.
- If a persona claims a proxy location, the persona's timezone must be consistent with that geography.
- **Every field that contributes to identity must pair-check against every other field that contributes to identity.** Build this into the persona factory, not as a downstream fixer.

### Agent rules
- All orchestration agents follow the global CLAUDE.md agent-audit rules in full.
- Each agent has: a named tool allowlist, a hard iteration cap (≤5 typical, ≤20 absolute max), a per-run cost cap, a per-session cost cap, a per-user cost cap.
- Destructive actions (delete account, factory-reset phone, wipe cache, revoke session) require confirmation gates in code, not just in prompt.
- Every agent action writes to an event-sourced audit log before execution, and writes the result after.
- Agents cannot call each other without going through the central orchestrator's routing layer.

### Known fleet bugs (from existing Onimator deployment on user's farm)
Fix these before shipping, even if not directly related to the PR:
1. **Locale/timezone cross-field contradiction** — every phone has `en-GB` locale with `America/New_York` timezone. Fix at persona factory level.
2. **AppCloner fingerprint** — all 22 IG clones share common signing certificate patterns. OrionFarm companion APK must not replicate this.
3. **Static per-device account count of 15-22** — real users don't share this exact number across a fleet. Vary by device-aging persona.
4. **Flat fleet-wide action timing** — current Onimator uses uniform delays per persona regardless of claimed timezone. OrionFarm must schedule against the persona's diurnal curve.

---

## Stack decisions (locked)

| Layer | Technology | Reason |
|---|---|---|
| Core orchestrator | Rust | Latency + throughput for hot path (device control, action queue) |
| Agents | Go | Concurrency for long-running supervisors (proxy orchestrator, recovery agent) |
| ML / content generation | Python | ModelForge, Chat AI, OpenRouter integration already Python |
| Web UI | TypeScript / Next.js | Matches Scaler Pro panel convention |
| Android companion APK | Kotlin + Jetpack | Native performance + modern Android APIs |
| Event bus | NATS or Redis Streams | Decision made at Phase 0 scaffolding; prefer NATS for durability |
| Database | Postgres 16 | Matches existing Scaler Pro panels, cross-panel queries via schema links |
| Cache | Redis | Standard |
| CI | GitHub Actions | Audit harness runs here as required check |

---

## Folder convention

```
orionfarm/
├── .claude/
│   └── CLAUDE.md         (this file)
├── PLAN.md               (executive plan)
├── HARDWARE.md           (fleet intel)
├── backend/
│   ├── core-rs/          (Rust orchestrator core)
│   ├── agents-go/        (Go agent supervisors)
│   ├── ml-py/            (Python ML + content generation)
│   ├── audit-harness/    (10K-persona Monte Carlo CI gate)
│   ├── persona-factory/  (Python persona generator)
│   └── migrations/       (Postgres schema migrations)
├── frontend/             (Next.js + WebSocket dashboard)
├── companion-apk/        (Android Studio project)
├── farm-agents/          (per-farm edge agent binaries + configs)
├── docs/
│   ├── architecture/     (diagrams, decision records)
│   ├── playbooks/        (operational runbooks)
│   └── api/              (OpenAPI specs)
└── logs/
```

Do NOT create `backend/`, `frontend/`, `companion-apk/`, etc. until the user signs off on `PLAN.md`. Only the top-level planning docs exist at the moment.

---

## Working mode

The user's global CLAUDE.md rule is **full autonomy, no permission requests except for irreversible destructive actions on shared infrastructure**. Apply that here.

For OrionFarm specifically:
- Never flash a phone without user confirmation (irreversible)
- Never factory-reset a phone without user confirmation (destroys accounts)
- Never push a companion APK to the whole fleet without user confirmation (must pilot on 1 phone first)
- Never modify the existing Onimator deployment's databases without backing them up first
- Never delete account data from `iguserdatabase.db` or `notificationdatabase.db`

Everything else (write code, run audits, refactor, add features, build infrastructure) proceeds without confirmation.

---

## Business context reminder

This is not a hobby project. Target is $100M valuation at ~$10M ARR via multi-tenant SaaS + hosted-farm leasing + API tier + white-label licensing. Every architectural choice should be evaluated against: does this scale to 1,000 tenants × 100 phones each?

If the answer is no, rethink.

---

## Open questions tracked in PLAN.md §12

Before Phase 1 implementation:
- [ ] Plan approval
- [ ] Pilot farm selection
- [ ] Pilot persona (new vs migrate Tatiana/Melodie)
- [ ] Magisk rollout plan
- [ ] Stack confirmation
- [ ] Monorepo vs polyrepo
- [ ] Phase 0 scaffolding go-ahead
