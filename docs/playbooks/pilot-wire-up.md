# Pilot wire-up: dispatcher ↔ companion APK on one real phone

Prereqs on the phone:
- APK installed (`com.scalerpro.phantomfleet`), foreground after boot.
- Accessibility service granted for the clone you want to drive.
- The clone (e.g. `com.scalerpro.phantomfleet.ig1`) is logged into a
  throwaway test account. **Do not pilot on an account that matters.**

Prereqs on the dev host:
- `adb` on PATH, phone shows in `adb devices` as "device".
- Python venv for this repo active.

## 1. Stub-mode confidence check (no phone)

```
python -m ops.dispatch.wire_test --stub
```

Expected: 8/8 PASS. Proves the dispatcher sends APK-shape JSON
(`username`, not `targetUsername`; `mediaId`, not `mediaCode`; etc.).

## 2. Set up adb reverse port forward

The APK listens on `localhost:8089` on the phone. We let the phone
reach our dev host via that same loopback:

```
adb -s <SERIAL> reverse tcp:8089 tcp:8089
```

Verify from the phone's shell:

```
adb -s <SERIAL> shell curl -s http://127.0.0.1:8089/health
```

Expected: `{"ok":true,"port":8089,...}`.

## 3. Seed Fleet with ONE active target and ONE pilot account

See `ops/dispatch/wire_test.py::_seed_fleet` — it seeds
`accounts(id=1, status='alive')`, `device_endpoints`,
`clone_assignments`, `target_pool(status='active')`, and one due
`action_queue` row. Adapt the `WIRE_SER` and the clone package to the
real values for your pilot phone.

## 4. First real-phone action (one row, with the safety gate)

```
python -m ops.dispatch.wire_test --live --serial <SERIAL> --port 8089 --I-UNDERSTAND
```

This WILL cause one real IG follow on the pilot clone. The flag is
there so you don't run this by reflex.

## 5. Watch what happened

- Phone: `adb -s <SERIAL> logcat -s PhantomFleet:V IGEngagementHandler:V`
- Fleet: `tail -n 50 backend/.data/dispatch.ndjson` (every claim/
  dispatch/result lands here via `ops/sched/_telemetry.py`).
- IG: open the test account on another phone; confirm the follow is
  on the picker's chosen target_pool row.

## 6. Handing over to the cron supervisor

Once one row works end-to-end:

```
python -m ops.cron.supervisor --only target_hydrate,dispatch
```

Runs on a 30s/60s cadence. Stop it with Ctrl-C.

## Rollback

If the APK does the wrong thing:
- Revoke accessibility for the clone from Android Settings.
- `adb -s <SERIAL> shell am force-stop com.scalerpro.phantomfleet`.
- `adb reverse --remove tcp:8089`.
- In Fleet: `UPDATE accounts SET status='paused' WHERE id=1` and
  `UPDATE target_pool SET status='rejected' WHERE farm_id='wireF'`.

No row is dispatched again while the account is `paused`.
