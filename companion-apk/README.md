# Phantom Fleet Companion APK

Kotlin + Jetpack Compose companion app that runs on every phone in the fleet.

## What it does

- Exposes a localhost HTTP server (Ktor) on 127.0.0.1:PORT
- Provides input primitives via Android Accessibility Service:
  - `/action/tap` — inject tap at (x, y) with persona-biometric timing
  - `/action/swipe` — Bezier-curve swipe with natural velocity profile
  - `/action/type` — per-char typing with LogNormal delays + 3% typo rate
  - `/action/navigate` — deep-link or activity launch
- Screen + UI inspection:
  - `/screen` — PNG pixel buffer for CV
  - `/ui` — accessibility tree dump
  - `/state` — foreground app, network, battery, signal, ATT status
- Clone management:
  - `/clone/launch` — bring a specific cloned IG package to foreground
  - `/clone/kill` — force-stop a clone
  - `/clone/session_check` — read login state without posting
- Recovery primitives:
  - `/recover/reboot`
  - `/recover/clear_cache`
  - `/recover/reauth`

## Why Kotlin + native over uiautomator2

- **5-10x faster** tap/type primitives via direct InputManager injection (when signed with signature permission) OR Accessibility Service fallback (Phase 1, no root required)
- **No Python dependency** on the phone — the only other process is the IG clone itself
- **Native coroutines** for parallel primitives
- **Embedded Ktor HTTP server** — no uiautomator2 RPC protocol
- **Gradle build** — one APK to deploy across the whole fleet

## Build

```bash
./gradlew assembleRelease
adb install -r app/build/outputs/apk/release/app-release.apk
```

## Safety

The Companion APK never accesses the network except to `127.0.0.1` and its
Accessibility Service can only read UI state — not post it externally. All IG
action execution is orchestrated by the Python backend over
`adb forward tcp:8765 tcp:8765` then HTTP, never via the APK itself initiating
network calls outbound.

## Phase 0 stubs

Phase 0 ships with just:
- `MainActivity.kt` — app entry + AccessibilityService enable prompt
- `PhantomAccessibilityService.kt` — service stub
- `HttpServer.kt` — Ktor stub with `/ping` + `/state` endpoints

Phase 1 adds the full primitive set.
