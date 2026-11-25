# ops/sched/ — deterministic farm control plane

Replaces the agent layer PLAN.md §5 originally specced. No LLM calls,
no retries driven by a model, no fuzzy judgment. Every decision is a
pure function of (DB state, now).

## Modules

| Module | What it replaces | Shape |
|---|---|---|
| `warming.py` | Warming Agent | pure function `(day, now, tz, peak) -> [ScheduledAction]` |
| `tick.py` | Warming Agent dispatch | SELECT alive -> warming.schedule_day -> INSERT action_queue |
| `recovery.py` | Recovery Agent | tail(action_results) -> status transition + proxy signal |
| `replacement.py` | Replacement Agent | dead accounts -> replacements_needed row |
| `proxy.py` | Proxy Orchestrator Agent | error window -> rotate / heal state transition |

## Store

`backend/.data/persona-store.sqlite` holds every table. `_store.py`
owns migrations; running any module auto-applies them. Phase 1 swaps
this for Postgres by changing the DSN in `_store.connect`.

Tables beyond the base `personas / devices / accounts`:

- `warming_curves`, `account_schedule_state`, `persona_profiles` — scheduler
- `action_queue`, `action_results` — the queue + its outcomes
- `account_status_history` — append-only audit of every status transition
- `proxy_state` — per-plan block counter + rotation cooldown
- `replacements_needed` — dead-account queue for operator pickup

## Running the control loop

Cron (Phase 0, Linux/Mac/WSL; Windows Task Scheduler works the same):

```
30 4 * * *   python -m ops.sched.tick --apply        # fresh day
*/5 * * * *  python -m ops.sched.recovery --apply    # status transitions
*/15 * * * * python -m ops.sched.proxy --apply --register trumpproxies_yuge
0 */6 * * *  python -m ops.sched.replacement --apply # dead -> queue
```

All four scripts are idempotent across runs. Each writes to NDJSON for
auditability only when the `--apply` form actually mutates state.

## The agents that no longer exist

- **Warming Agent** -> `tick.py` as a cron job
- **Recovery Agent** -> `recovery.py` as a cron job
- **Replacement Agent** -> `replacement.py` as a cron job
- **Proxy Orchestrator Agent** -> `proxy.py` as a cron job
- **Fingerprint Monitor Agent** -> `persona_cohort_validators.py` (already built, moonshot #10) + the `#9` owner_brief surfaces anomalies
- **Account Setup Agent** -> replaced by a one-shot provisioning script per batch
- **DM Agent** / **Content Agent** -> keep AI (the two legitimate carve-outs: content generation only)
- **Funnel Conversion Agent** -> a SQL report, not an agent

## Smoke test

`scratchpad/sched_smoke.py` builds a fresh DB, seeds 6 accounts
covering every recovery rule, and exercises all four modules end-to-end.
Currently green at 20/20.

## What's NOT here

- No action **dispatcher**. The queue holds rows; a separate (still
  deterministic) worker reads them and talks to the companion APK over
  ADB. That worker is the next piece to build.
- No proxy **upstream API call**. `proxy.py` writes the decision; a
  thin dispatcher calls the TrumpProxies rotation endpoint.
- No content generation. That's the one place AI stays.
