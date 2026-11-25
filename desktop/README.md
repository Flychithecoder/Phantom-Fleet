# Phantom Fleet desktop

Electron shell around the Next.js dashboard + FastAPI backend.

## Dev

```powershell
cd desktop
npm install
npm run start:dev   # loads http://localhost:3016
```

Assumes:
- Next.js dev server running on :3016
- FastAPI backend running on :8000

## Pack a distributable (Windows)

```powershell
npm run dist
```

Produces an NSIS installer under `dist/`.

## Architecture

- `src/main.js` — main process, menu, tray, window-state store (via `electron-store`).
- `src/preload.js` — exposes `window.phantomFleet` to the renderer (isDesktop flag, config, setTarget).
- Renderer is the live Next.js app — no second UI codebase.

Env overrides: `PF_TARGET` (dashboard URL), `PF_BACKEND` (FastAPI URL).
