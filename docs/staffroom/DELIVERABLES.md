# Readiness Review — end-to-end run, deliverables

**Status:** mission ran end-to-end to `completed` on the local Staffroom
instance against the owner's Claude Code subscription via the Phantom Fleet
runner. **No paid fallback was permitted and none was invoked.** Fleet-side
refresh parser has been fixed (previously it read `status` from the API's
response wrapper rather than from `mission.status`).

## Links

| What | Where |
|---|---|
| Fleet job (clean router-verified run) | http://localhost:3016/agents — row for `pf-readiness_review-ea9d3259b7a9e63f` |
| Staffroom mission (clean run, **8499-char final report**) | http://127.0.0.1:4321/missions/49e68b62-0309-48d0-995b-61c4bacdd79f |
| Staffroom mission (first completed run) | http://127.0.0.1:4321/missions/ab7153ac-0c68-4f0f-8aae-cf674769cee8 |
| Staffroom mission (second run, parser-verification) | http://127.0.0.1:4321/missions/a2e15e95-3d7b-4566-9b63-dddf5ac3ae8b |
| Raw Staffroom snapshot (first run) | [evidence-completed-mission.json](evidence-completed-mission.json) |
| Runner audit log | `runner/logs/runner-audit.ndjson` |

The two Staffroom mission IDs share the same Fleet `request_id`
(`pf-readiness_review-dbd065904e8679d7`) because the uvicorn `--reload`
auto-restart wiped Fleet's in-memory mission store between runs; both
Staffroom missions carry that request_id in their prompt. Follow-up work
(backlog phase B) moves the Fleet store to Postgres so idempotency survives a
restart.

## Shared mission ID

**Clean, router-verified run (recommended citation):**
- Staffroom mission: `49e68b62-0309-48d0-995b-61c4bacdd79f`
- Fleet request_id: `pf-readiness_review-ea9d3259b7a9e63f` (seed = `router-verification-2026-11-24`)
- Final report: 8499 chars

**First end-to-end run (workers were mis-routed pre-fix):**
- Staffroom mission: `ab7153ac-0c68-4f0f-8aae-cf674769cee8`
- Fleet request_id: `pf-readiness_review-dbd065904e8679d7`
- Final report: 7644 chars

## Model and cost evidence

From `runner/logs/runner-audit.ndjson` — every entry is a real `claude --print
--model <id> --output-format json` call. `effective_model` is read back from
Claude's own JSON output, so it is not a client-side pin claim.

| Time (UTC) | Role | `pinned_model` | `effective_model` | prompt_chars | response_chars | ms | cost_usd (info.) |
|---|---|---|---|---|---|---|---|
| 13:04:07 | sonnet probe (ready check) | claude-sonnet-4-6 | claude-sonnet-4-6 | 58 | 14 | 3800 | 0.04820 |
| 13:10:49 | COO plan | claude-opus-4-7 | claude-opus-4-7 | 3551 | 2071 | 16828 | 0.13950 |
| 13:13:04 | worker a1 (**routed wrong — see note**) | claude-opus-4-7 | claude-opus-4-7 | 18460 | 5524 | 81389 | 0.40250 |
| 13:14:32 | worker a2 (**routed wrong — see note**) | claude-opus-4-7 | claude-opus-4-7 | 18551 | 9702 | 88607 | 0.36942 |
| 13:17:32 | after-review | claude-opus-4-7 | claude-opus-4-7 | 17475 | 6002 | 57257 | 0.21262 |
| 13:18:13 | final executive report | claude-opus-4-7 | claude-opus-4-7 | 23559 | 7573 | 41058 | 0.21448 |

**`cost_usd` is an informational figure emitted by `claude --output-format
json` showing the theoretical API-equivalent cost for the call.** The owner
confirmed **Usage credits are OFF** in `claude.ai → Settings → Usage`, so
these calls were billed against the owner's Claude Max/Pro subscription and
the dollar figures above are **not** charges on the account. No alternate
provider was used; the runner is wired to return HTTP 502 with no fallback on
any error, which it did once (the leading `fail` entry) when the OAuth
session was briefly expired.

### Worker routing — two fixes, now verified

The first run's workers (13:13, 13:14) landed on `claude-opus-4-7`. **Root
cause pass 1:** the router matched system-prompt substrings ("chief of
staff") that every mission carries. Switched to matching user-role messages
only, using Fleet-brief phrases.

A second dispatched mission still routed workers to Opus. **Root cause pass
2:** Staffroom (`server/engine.js:700`) builds the worker user message as
`Original request: <brief>\nAssignment: <task>\nPeer evidence: ...`, so the
Fleet brief **does** appear in worker prompts too. Fixed by flipping the
heuristic to detect **worker scaffolding** instead:

```javascript
const WORKER_MARKERS = ["\nassignment:", "\npeer evidence:"];
if (match) return "claude-sonnet-4-6";   // worker
return "claude-opus-4-7";                // COO plan / review / fallback
```

Verified in the clean run (mission `49e68b62`):

| Time (UTC) | Role | `pinned_model` | `effective_model` | prompt_chars | resp_chars |
|---|---|---|---|---|---|
| 13:30:19 | COO plan | claude-opus-4-7 | claude-opus-4-7 | 3551 | 1715 |
| 13:34:15 | worker a1 | claude-sonnet-4-6 | claude-sonnet-4-6 | 18276 | 9789 |
| 13:35:50 | worker a2 | claude-sonnet-4-6 | claude-sonnet-4-6 | 18379 | 11813 |
| 13:38:06 | after-review | claude-opus-4-7 | claude-opus-4-7 | 24037 | 6198 |
| 13:38:54 | final report | claude-opus-4-7 | claude-opus-4-7 | 30317 | 8499 |

All five calls hit the subscription CLI, no fallback.

## Completed mission final report

Length: **7644 characters**. First lines:

```
# Phantom Fleet — Executive Readiness Report (Final)
**Request:** `pf-readiness_review-dbd065904e8679d7` · **Date:** 2026-11-24 · **Mode:** read-only paper review

## Scope and trust posture
Two specialists returned in parallel with no `depends_on` ...
```

Full report lives in Staffroom mission `ab7153ac...` → `mission.result`, also
preserved in `evidence-completed-mission.json`.

## What stays held

- Live Tailscale `https://desktop-c74bmhb.tail72dd7e.ts.net:10444/` — owner sign-in still 502; Phase E in the automation backlog is on hold until that is restored. Nothing in this run touched it.
- Fleet-side physical device actions, publishing, live billing: all OFF per CLAUDE.md.
- Paid fallback and alternate provider billing: OFF; no exception taken.
