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
PHANTOM_MIRROR_URL=http://127.0.0.1:8766

# phone actions + live screen through the hub
FLEET_MIRROR_URL=https://192.168.1.16:22300          # or http://127.0.0.1:22301 on the hub PC
FLEET_MIRROR_API_KEY_FILE=C:\Users\admin\Projects\PhantomFleet\fleet-mirror\run\api-key.txt
#   ^ a file holding the hub's API key, outside this repo: backend/.env is tracked in git, so never put the key in it.
#   The mirror bridge sends the key as a header, so PHANTOM_MIRROR_URL needs no key in it.
FLEET_MIRROR_AGENTS_API_KEY_FILE=C:\Users\admin\Projects\PhantomFleet\fleet-mirror\run\api-key-agents.txt
#   ^ the hub's "agents" key: AI agents, automations and every adb command the backend runs use this one.
FLEET_MIRROR_CERT_SHA256=EC:12:E7:D3:AC:FD:42:8F:2A:B0:6F:67:23:52:C0:7C:CF:47:9F:3B:4D:7F:05:CC:75:D8:07:82:32:91:8B:37
FLEET_MIRROR_ADB=1                                   # 0 = old behaviour (local adb)
FLEET_MIRROR_ADB_FALLBACK=0                          # adb forward/connect: 0 = refuse (recommended), 1 = local adb
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

- **Control.** The hub gives the Phantom Fleet API key its own device allowlist (Fleet Mirror →
  More → Settings → *Local API (Phantom Fleet) → May control*). It is currently **R5CRC08L4QM,
  R5CRC0GACCK, R5CRC10PTEV**. Input, shell, installs, file transfers, tasks and control embeds on any
  other phone are refused with code 10004 and surface here as `ADBCommandFailed` / `FleetMirrorError`;
  those phones stay visible (list, screenshots, view-only live screen). Widen the list in Fleet Mirror's
  Settings when Phantom Fleet should drive more phones. With `FLEET_MIRROR_ADB=1`, executors aiming at
  other phones get errors instead of acting.
- **Timing.** The hub adds no randomness. Taps and swipes use exactly the points and delays Phantom
  Fleet computes (`FleetMirrorClient.swipe(points, durations_ms)`).
- **Companion APK.** `adb forward tcp:… tcp:8090` only works for phones on this PC's adb server. Phones
  on other host PCs should use the companion APK over WiFi (contract §7).
- **Live screen.** Each browser that shows it must trust the hub certificate once; see Fleet
  Mirror's `integrations/phantomfleet/README.md` ("Trusting the hub certificate").
- **Push.** `adb push` is staged through `/sdcard/Download` and then moved to the target folder on
  the phone.
- The unused `phantom_fleet/phones/__init__.py` helper (Onimator adb path) is unchanged.


## Two keys: people and agents

The hub has two keys, each with its own "may control" list (Fleet Mirror → More → Settings → Local API keys):

| Key | Used by | File setting |
|---|---|---|
| `ui` | People: the Phone Wall, Live screen panels, buttons on Phantom Fleet's pages | `FLEET_MIRROR_API_KEY_FILE` |
| `agents` | AI agents (`agents/device_tools.py`), automations, every adb command the backend runs | `FLEET_MIRROR_AGENTS_API_KEY_FILE` |

Phones outside a key's list are view-only for it: live screen, screenshots and lists work. Input, shell,
installs, file transfers and tasks are refused with code 10004. Both lists currently hold the 3 test phones.
The Mirroring → Device Access page shows both lists.

## Mirroring section

- **Phone Wall** (`/mirroring`): the whole Fleet Mirror wall inside Phantom Fleet, in Phantom Fleet's
  style. It covers every phone on every host PC: tiles, large view, control, drag-select, sync, batch
  tools, sliders, tabs, tags and dialogs.
  - It opens with a one-time link minted by the backend (`GET /api/fleet-mirror/embed-wall`, `ui` key);
    the session lasts 8 hours.
  - Control works only on the `ui` key's phones.
  - Hub administration isn't available here: keys, Add PC, sharing, adb restart, removing phones.
  - It has Full screen and Reconnect buttons.
- **Device Access** (`/mirroring/access`): which phones people and agents may control
  (`GET /api/fleet-mirror/access`), plus the list of agent device tools.

## Agent device tools (`agents/device_tools.py`)

`build_device_tool_registry()` returns 21 keyword-only async tools, using the `agents` key:

- `device.list`
- `device.screenshot`, `device.ui_dump`, `device.screen_size`
- `device.tap`, `device.swipe`, `device.long_press`, `device.key`, `device.text`
- `device.clipboard_set`, `device.clipboard_get`
- `device.shell`, `device.apps`
- `device.app_install`, `device.app_start`, `device.app_stop`
- `device.file_push`, `device.file_pull`
- `device.task_run`, `device.task_status`, `device.task_stop`

Add the ones an agent needs to its `AgentConfig.allowed_tools`; `DEVICE_TOOLS` lists them all. For LLM tool
use, `llm_tool_specs()` gives name, description and JSON schema for each tool (`device_tap`, ...), and
`call_llm_tool(name, args)` runs one and returns errors as `{"error", "code"}`.

The hub adds no randomness: swipe and tap timing comes from the agent (use `core.distributions`).
