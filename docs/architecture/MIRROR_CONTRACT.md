# Phantom Fleet Mirroring — integration contract

This document pins down everything **Phantom Fleet Mirror** must expose so the
**Phantom Fleet** automation panel can drive 19+ phones concurrently without
racing WhiteTiger (or any other existing mirror) and without breaking any of
the CLAUDE.md fleet-scale rules.

The mirror does three jobs:

1. **Discover** every connected phone (USB + WiFi) and keep the list current.
2. **Stream** screen + input to the operator (humans at consoles).
3. **Share USB/ADB access** with the automation panel without fighting it.

If all three jobs work together, the panel can treat the mirror like a passive
device registry during pilot and migrate to the companion APK + WiFi ADB
architecture later with no backend changes.

---

## 1. Discovery API (required)

A local HTTP + WebSocket server. Default bind: `127.0.0.1:8765`. Must support
both HTTP polling and a WS event stream so the panel can show live state
without polling at > 1 Hz.

### 1.1 GET `/devices`

Returns the full inventory.

```json
{
  "schema_version": 1,
  "host_id": "farm-01-dell-7920",
  "server_time": "2026-11-23T21:04:17Z",
  "devices": [
    {
      "serial": "R5CRC0J6CGT",
      "state": "online",
      "connection": "usb",
      "mirror_slot": 1,
      "model": "SM-G990U1",
      "product": "r9quew",
      "device_codename": "r9q",
      "android_version": "13",
      "build_id": "TP1A.220624.014",
      "wifi_ip": "192.168.1.42",
      "battery_pct": 87,
      "screen_on": true,
      "disconnected_reason": null,
      "adb_claim": {
        "holder": "mirror",
        "released_until": null
      }
    }
  ]
}
```

**Field rules Phantom Fleet enforces downstream** (break these and personas
fail the cross-field audit in `audit_harness_agent`):

| Field | Required | Rule |
|---|---|---|
| `serial` | yes | Exact ADB serial. **Never rename, never truncate, never share across devices.** |
| `model` | yes | Samsung/Google model code as the device reports it (`SM-G990U1`, not "Galaxy S21 FE 5G"). |
| `android_version` | yes | Major version only (`"13"`, not `"13.0.0"` — minor in `build_id`). Must be inside the model's shipping range (see `MODEL_OS_RANGES` in `phantom_fleet/core/persona.py`). |
| `build_id` | yes | Real Samsung build ID. Used for GSF ID generation; a fabricated ID is a cluster-detection tell. |
| `connection` | yes | `"usb"` or `"wifi"`. Transition between them is allowed; `serial` must survive. |
| `mirror_slot` | yes | Position in the grid (1-based). Stable for the session — never renumbered when a phone drops. |

### 1.2 GET `/devices/{serial}`

Same device object as above, 404 if not connected.

### 1.3 WS `/events`

A phone's state change emits one line:

```json
{"ts":"2026-11-23T21:04:17Z","type":"device.connected","serial":"R5CRC0J6CGT"}
{"ts":"2026-11-23T21:05:02Z","type":"device.disconnected","serial":"R5CRC0J6CGT","reason":"usb_cable_removed"}
{"ts":"2026-11-23T21:05:30Z","type":"adb.released","serial":"R5CRC0J6CGT","holder":"panel","ttl_sec":120}
{"ts":"2026-11-23T21:07:30Z","type":"adb.reclaimed","serial":"R5CRC0J6CGT","holder":"mirror"}
```

Event types the panel listens for:
- `device.connected`
- `device.disconnected`
- `device.state_changed` (battery, screen_on, wifi_ip)
- `adb.released` / `adb.reclaimed` (see §3)
- `mirror.focus_changed` (which tile the operator is looking at)

---

## 2. Identity exposure (hard requirement)

Each device entry in `/devices` must also expose, under a `hw` sub-object, the
hardware fingerprint primitives the persona factory needs. **The mirror must
read these from the device itself, not cache a hard-coded value.** If a value
is unknown, return `null` — never fabricate.

```json
"hw": {
  "manufacturer": "samsung",
  "brand": "samsung",
  "device": "r9q",
  "fingerprint": "samsung/r9quew/r9q:13/TP1A.220624.014/G990U1UES4GWC1:user/release-keys",
  "advertising_id": "a1b2c3d4-...",
  "android_id": "a9f0...hex16",
  "gsf_id": "3fa2...hex16",
  "imei": null,
  "wifi_mac": "02:00:00:00:00:00",
  "bluetooth_mac": "02:00:00:00:00:00",
  "serialno_prop": "R5CRC0J6CGT"
}
```

Rules:

- `fingerprint` is the exact string `ro.build.fingerprint` returns. Do not
  modify case or spacing.
- `android_id` and `gsf_id` are the account-visible identifiers Instagram
  and Meta use for device clustering. If the mirror ever randomises these
  on behalf of the operator, it **must** record which values it wrote so
  the panel can keep them stable across restarts. Changing these mid-life
  is the single fastest way to burn an account cluster.
- Never return the same `android_id` for two devices. The panel treats a
  duplicate across serials as a mirror bug and will refuse to warm either
  account until it's resolved.
- Mock / spoofed values (for test devices) must be flagged:
  `"hw": { ..., "spoofed": true }`. The panel will refuse to put a real
  OnlyFans funnel account on a spoofed device.

---

## 3. ADB sharing protocol (the WhiteTiger problem solved)

USB can only be claimed by one driver at a time. The mirror holds the claim
by default so its screen stream keeps working. The panel asks for the claim
when it needs to run an ADB action, releases it when done, and the mirror
reclaims it automatically.

### 3.1 POST `/devices/{serial}/adb/acquire`

```json
Request:  {"holder": "phantom-fleet-panel", "ttl_sec": 60, "reason": "warming.like"}
Response: {"granted": true, "released_until": "2026-11-23T21:08:17Z", "adb_server_port": 5037}
         or {"granted": false, "reason": "busy", "retry_after_sec": 2}
```

The mirror MUST:

- Suspend its own screen pull on that device.
- Leave the ADB server on `:5037` reachable (do not kill the server — only
  release this device's USB handle).
- Auto-reclaim after `ttl_sec` if the panel hasn't called `release`. This
  guards against a crashed panel locking a phone forever.

### 3.2 POST `/devices/{serial}/adb/release`

```json
Request:  {"holder": "phantom-fleet-panel"}
Response: {"released": true}
```

The mirror resumes streaming within 1 second.

### 3.3 Why this matters

Without this contract, every action the panel runs (`adb shell input tap`,
`adb push`, `pm install`) either (a) fights the mirror for the USB handle
and causes random black frames and "Phone disconnected" tiles, or (b) kills
the entire ADB server and drops all 19 phones at once. Tile 05 going
"Phone disconnected" in the WhiteTiger screenshot is this exact bug.

**Companion APK + WiFi ADB sidesteps the whole fight** — see §7. The
`adb/acquire` protocol is only needed for phones not yet on WiFi ADB.

---

## 4. Per-device proxy routing

The mirror must not interfere with the panel's per-device proxy. The
`SmartproxyPool` / `IPRoyal` setup in `phantom_fleet/proxy/` assigns a
distinct SOCKS5 endpoint per phone (static-ISP sticky) and loads it onto
the phone's WiFi settings.

The mirror must:

- Read `proxy_host:proxy_port` from `/devices/{serial}/proxy` if asked; the
  panel may push an updated proxy here when it rotates.
- Never alter the phone's WiFi proxy settings on its own.
- Never route its own traffic through the device's configured proxy — the
  mirror talks over USB/LAN, not through the phone's residential IP.

### GET `/devices/{serial}/proxy`
### POST `/devices/{serial}/proxy`

```json
{"type": "socks5", "host": "89.38.228.5", "port": 12321, "username": "...", "password": "..."}
```

Password is accepted but the mirror must store it encrypted at rest with a
per-host key, never log it, and redact it from `/devices` responses.

---

## 5. Clone-slot awareness (AppCloner replacement)

Phantom Fleet runs 15–22 IG clones per phone via a bespoke companion APK —
NOT AppCloner (CLAUDE.md hard rule: AppCloner shares signing cert patterns
across clones and is the biggest cluster-detection tell on the current
Onimator fleet).

The mirror must surface the clone list per device without assuming the
AppCloner convention:

### GET `/devices/{serial}/clones`

```json
{
  "serial": "R5CRC0J6CGT",
  "clones": [
    {
      "package_name": "com.instagram.android.pf1",
      "clone_index": 0,
      "signing_cert_sha256": "4f2a...distinct per clone",
      "install_source": "phantom_companion",
      "foreground_now": false
    }
  ]
}
```

- `signing_cert_sha256` must be **unique per clone across the whole fleet**.
  If the mirror sees two clones share one, it must emit a
  `cluster.cert_collision` event — this is an existing Onimator bug the
  panel's `fingerprint_monitor_agent` expects to catch.
- Clones NOT installed by Phantom's companion (`install_source != "phantom_companion"`)
  are ignored for warming but still reported.

---

## 6. Capacity + telemetry

### GET `/health`

```json
{"status":"ok","uptime_sec":84213,"devices_total":19,"devices_online":18,"adb_server_pid":18240}
```

### GET `/metrics` (Prometheus text, optional)

The panel scrapes this every 15 s for the Ops Brain dashboard. Minimum set:

```
mirror_devices_online{host="farm-01-dell-7920"} 18
mirror_adb_claim_busy{serial="R5CRC0J6CGT"} 0
mirror_frame_drops_total{serial="R5CRC0J6CGT"} 42
mirror_disconnect_events_total{serial="R5CRC0J6CGT",reason="usb_cable"} 2
```

---

## 7. WiFi ADB handoff (the end state)

Once a phone has the Phantom Companion APK installed and has reported a
heartbeat (`POST /api/fleet/heartbeat` with `serial`, `wifi_ip`,
`apk_version`, `companion_port`), the panel prefers WiFi ADB over USB for
everything — scheduler actions, APK installs, device info extraction.

The mirror at that point:

- Keeps the USB stream for operator eyes-on monitoring only.
- No longer needs `adb/acquire` — the panel isn't on USB.
- Should emit `device.wifi_adb_ready{serial, wifi_ip}` once it sees the
  companion APK's `/health` respond on `http://{wifi_ip}:{companion_port}/health`.

This is the migration path: ship the mirror with the §3 ADB-sharing protocol
first, then as fleets move to companion APK + WiFi ADB, the §3 traffic
drops to zero on its own.

---

## 8. Hard non-negotiables

Breaking any of these turns the mirror into a liability:

1. **No fingerprint homogenisation.** The mirror must never write identical
   values of `ANDROID_ID`, `GSF_ID`, `build.fingerprint`, locale, or
   timezone across devices. If an operator asks for a bulk value change,
   refuse and route through the panel's persona factory — which pair-checks
   model ↔ OS, locale ↔ timezone, carrier ↔ HNI.
2. **No AppCloner-style clone creation.** Clones must be made via the
   Phantom Companion APK, each with a distinct signing cert.
3. **No bulk APK pushes without panel approval.** Pushing a companion APK
   or any IG clone to the whole fleet from inside the mirror is prohibited
   — the panel enforces a "pilot on 1 phone first" gate (CLAUDE.md hard
   rule for OrionFarm) and the mirror must honour it.
4. **No factory reset / flashing** from inside the mirror UI without an
   explicit panel-side confirm token in the request. Accidental taps on a
   grid of 19 tiles must not nuke accounts.
5. **No logging of proxy passwords, 2FA secrets, or session cookies.**
6. **Stable serials across reconnects.** A phone reconnecting after a USB
   drop must keep the same `serial` — the panel's warming schedule is
   keyed on it, and a serial change counts as a new device for the first
   28 days (warming curve restart).
7. **No `rng.uniform()` / `Math.random()` for anything timing-related.**
   If the mirror ever adds humanised input (bezel swipes, random tap jitter
   for operator demo), the distributions have to come from the panel's
   `LogNormal` / `Normal` / `Bimodal` classes. Flat-uniform jitter is a
   cluster-detection signature.

---

## 9. Minimum MVP checklist

For the first bridge drop to be useful, the mirror only needs:

- [ ] `GET /devices` returning `serial`, `model`, `android_version`, `connection`
- [ ] `WS /events` for `device.connected` / `device.disconnected`
- [ ] `POST /devices/{serial}/adb/acquire` with TTL auto-release
- [ ] `POST /devices/{serial}/adb/release`
- [ ] `GET /health`

The rest (hw identity, clones, proxy, metrics, WiFi handoff) can land in
follow-up releases. The panel degrades gracefully on missing fields.

---

## 10. How the panel will consume this

Reference implementation path, so the mirror team knows what's calling what:

1. `phantom_fleet/core/phone_controller.py::PhoneFleet.scan()` — swap the
   current `adb devices` call for `GET http://127.0.0.1:8765/devices`.
2. New module `phantom_fleet/mirror_bridge.py` — thin async httpx client,
   subscribes to `WS /events`, emits internal state changes.
3. Every ADB call in `phantom_fleet/core/` is wrapped by an
   `acquire_adb(serial, ttl, reason)` context manager that hits §3.
4. `phantom_fleet/api/routes/fleet.py::list_fleet` and `scan_fleet` expose
   the mirror's view unchanged to the frontend — no UI code changes.

---

*Maintained alongside `phantom_fleet/core/phone_controller.py` and
`phantom_fleet/core/persona.py`. Any breaking change to this contract
must land simultaneously in both the mirror and the panel.*
