# ops/ — deterministic farm operations

Everything in this tree is a **pure function + state transition**. No
LLM calls, no agents, no non-determinism beyond the typed distributions
in `backend/phantom_fleet/core/`.

Architectural rule (locked 2026-11-25):

> AI is used for **research and oversight only** — never for farm
> control. Device actions, scheduling, recovery, replacement, and proxy
> rotation are deterministic state machines reading Postgres (Phase 1)
> or SQLite (Phase 0) and writing next-action rows. Content generation
> and anomaly review are the two carve-outs.

## Layout

```
ops/
  devices/farm1.json              fleet registry (serials, models, regions)
  preflight/
    _adb.py                       shared ADB wrapper + NDJSON audit
    01_wifi_adb.py                enable Wi-Fi ADB on every USB phone
    02_fix_locale.py              en-GB -> en-US fleet-wide
    03_onimator_migrate.py        read Onimator SQLite into persona-store.sqlite
    04_login_survival.py          parallel silent-login diagnostic
  logs/                           NDJSON audit per script + survival_report.json
```

## Order of operations (first-boot)

```
cd ops/preflight
python 01_wifi_adb.py --dry-run
python 01_wifi_adb.py              # requires USB cable, applies tcpip + verifies

python 02_fix_locale.py --dry-run
python 02_fix_locale.py --apply

python 03_onimator_migrate.py --dry-run
python 03_onimator_migrate.py --apply

python 04_login_survival.py        # produces survival_report.json
```

Every script is idempotent and writes `ops/logs/<name>.ndjson` so a
second run reproduces the same state (or no-ops on already-good rows).

## Safety

- `01` and `02` are device-side but non-destructive (settings and
  property writes only; no app data touched).
- `03` opens Onimator's SQLite **read-only** (`?mode=ro&immutable=1`).
  The target DB is created fresh under `backend/.data/`; a pre-existing
  one is renamed `.bak-<ts>`, never overwritten.
- `04` only reads the UI dump; it never types, taps, or swipes.

## Dependencies

- Python 3.10+ (stdlib only; no pip install needed)
- `adb` on PATH, or set `PF_ADB_BIN` to the adb binary
- SM-G770 stock firmware with Developer Options + USB Debugging on

## Non-goals

- These are not agents. They do not loop, retry forever, or make
  judgment calls. A failed row stays failed and surfaces in the
  audit log for an operator to act on.
- They do not import the FastAPI app or any moonshot code. Pre-flight
  runs before the backend is up.
