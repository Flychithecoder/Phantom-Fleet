# ops/cron/ — scheduling the deterministic control plane

One canonical schedule, three ways to run it.

## The schedule

| Job | Interval | What |
|---|---|---|
| `target_hydrate` | **30 s** | `ops.targets.hydrator --apply --max 200` fills targetUsername/mediaCode/text/usernames on due queue rows from `target_pool` + `comment_pool` (Staffroom-approved only) |
| `dispatch` | **1 min** | `ops.dispatch.worker --apply --max 25` drains action_queue to the APK |
| `recovery` | 5 min | `ops.sched.recovery --apply` account status transitions |
| `proxy` | 15 min | `ops.sched.proxy --apply --register trumpproxies_yuge` rotation / heal |
| `scheduler_tick` | 6 h | `ops.sched.tick --apply` enqueue next day's actions per account |
| `replacement` | 6 h | `ops.sched.replacement --apply` dead → replacements_needed |
| `weekly_commitment` | 7 d | `chain.make_commitment()` sign the audit chain head |

Defined once in `ops/cron/schedule.py` and reused by every entry point.

## Three ways to run it

### 1. Linux cron (production)

```
# edit the three paths at the top first
crontab -u pf-fleet ops/cron/crontab.example
tail -F /var/log/phantom-fleet/cron.log
```

### 2. Windows Task Scheduler (dev)

```powershell
# elevated PowerShell
.\ops\cron\windows-tasks.ps1

# tail the hot path
Get-Content -Wait -Tail 20 .\logs\cron-dispatch.log

# tear down
.\ops\cron\windows-tasks.ps1 -Unregister
```

### 3. In-process supervisor (iterating locally)

```
python -m ops.cron.supervisor              # foreground, Ctrl-C to stop
python -m ops.cron.supervisor --status     # last run report
python -m ops.cron.supervisor --once       # fire everything due now
python -m ops.cron.supervisor --speed 60   # 60x time (dev smoke)
python -m ops.cron.supervisor --only dispatch,recovery
```

The supervisor persists `last_run_ms` per job in SQLite
(`supervisor_state`), so a restart doesn't re-fire everything in the
first second.

## Safety

- Every job is already idempotent at the module level — firing one
  twice is a no-op if nothing changed.
- `--apply` vs `--dry-run` is per-module; the schedule here always
  uses `--apply`. Switch individual jobs to dry-run in the cron file
  to shadow a candidate without changing live state.
- Hot path is 1 minute because `action_queue` due times are in ms;
  a 5-min cron would miss up to 5 min of actions.
- `weekly_commitment` needs `PF_AUDIT_SIGNER_KEY` in its environment
  (or it mints a fresh ephemeral key every week, which defeats the
  audit purpose).

## Smoke test

`scratchpad/supervisor_smoke.py` exercises the supervisor with toy
jobs: 8/8 PASS (first-pass fire, interval honoring, accelerated speed,
run + failure accounting, selection filter).
