# Fleet Mirror integration

Phantom Fleet uses the Fleet Mirror hub (the phone-wall app on the main PC) for three things:

1. **Device discovery** through the hub's Mirror contract server (`docs/architecture/MIRROR_CONTRACT.md`).
   It covers every phone on every host PC.
2. **Phone actions without a local adb client.** `adb shell`, `adb install`, `adb push` and
   `adb devices` go to the hub, which runs them on the right PC. This avoids the shared adb server
   being restarted by an adb of another version, which would drop every phone on it.
3. **Live screen** on the device page (`/fleet/[serial]`). The "Show live screen" panel embeds that
   phone's screen from the hub, view-only by default, with optional control.

## Settings (backend environment, e.g. `backend/.env`)

```
# discovery: the hub's Mirror contract server (runs on the hub PC, 127.0.0.1 only)
PHANTOM_MIRROR_URL=http://127.0.0.1:8766/k/<FLEET MIRROR API KEY>

# phone actions + live screen through the hub
FLEET_MIRROR_URL=https://192.168.1.16:22300          # or http://127.0.0.1:22301 on the hub PC
FLEET_MIRROR_API_KEY=<FLEET MIRROR API KEY>          # Fleet Mirror: right-click a phone > Local API
FLEET_MIRROR_CERT_SHA256=EC:12:E7:D3:AC:FD:42:8F:2A:B0:6F:67:23:52:C0:7C:CF:47:9F:3B:4D:7F:05:CC:75:D8:07:82:32:91:8B:37
FLEET_MIRROR_ADB=1                                   # 0 = old behaviour (local adb)
FLEET_MIRROR_ADB_FALLBACK=1                          # adb forward/connect: 1 = local adb, 0 = refuse
```

Keep the API key out of git and out of the browser. The frontend only ever receives one-time embed links.

## What changed

| File | Change |
|---|---|
| `backend/phantom_fleet/fleet_mirror_client.py` | new: async client for the hub (httpx, pinned certificate, API key) |
| `backend/phantom_fleet/core/adb_router.py` | new: maps adb commands to hub calls; `FLEET_MIRROR_ADB` / `_FALLBACK` switches |
| `backend/phantom_fleet/core/phone_controller.py` | `_run_adb()` goes through the router when `FLEET_MIRROR_ADB=1` |
| `backend/phantom_fleet/core/apk_client.py` | `_run_adb_cmd()` likewise. `adb forward` for the companion APK isn't routable and uses local adb only if fallback is on |
| `backend/phantom_fleet/agents/specialists/gmail_creation_agent.py` | its own `_adb()` likewise |
| `backend/phantom_fleet/api/routes/fleet_mirror.py` | new: `GET /api/fleet-mirror/status`, `GET /api/fleet-mirror/embed?serial=&control=&minutes=` |
| `backend/phantom_fleet/api/app.py` | registers the router at `/api/fleet-mirror` |
| `frontend/src/components/FleetMirrorView.tsx` | new: iframe component; asks the backend for a one-time embed link |
| `frontend/src/app/fleet/[serial]/page.tsx` | "Live screen" panel (Show/Hide, "allow control") above the hardware panel |

With `FLEET_MIRROR_ADB` unset, the backend behaves exactly as before.

## Things to know

- **Control.** Phone input (taps, swipes, text, installs, shell commands that change the phone) only
  reaches phones the hub allows control on (hub config `control_enabled` + `control_serials`;
  currently `"*"`, all phones). With `FLEET_MIRROR_ADB=1`, every agent and executor that runs adb
  reaches every phone on every PC. Narrow `control_serials` on the hub if Phantom Fleet should only
  drive some phones.
- **Timing.** The hub adds no randomness. Taps and swipes use exactly the points and delays Phantom
  Fleet computes (`FleetMirrorClient.swipe(points, durations_ms)`).
- **Companion APK.** `adb forward tcp:… tcp:8090` only works for phones on this PC's adb server. Phones
  on other host PCs should use the companion APK over WiFi (contract §7).
- **Live screen.** Each browser that shows it must trust the hub certificate once; see Fleet
  Mirror's `integrations/phantomfleet/README.md` ("Trusting the hub certificate").
- **Push.** `adb push` is staged through `/sdcard/Download` and then moved to the target folder on
  the phone.
- The unused `phantom_fleet/phones/__init__.py` helper (Onimator adb path) is unchanged.
