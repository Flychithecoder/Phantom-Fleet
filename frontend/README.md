# Phantom Fleet Panel

Premium fleet-command SaaS dashboard for Phantom Fleet.

A Scaler Pro product.

## Design system

- **Dark-first, premium aesthetic** — optimized for 14-24hr sessions in a dim room
- **Neon cyan-green signature accent** (`hsl(162 100% 54%)`)
- **Inter display font** with tight tracking, tabular nums for metrics
- **Glass panels** with subtle grid background + border glow
- **Live data** via WebSocket from Phantom Fleet backend (port 8000)
- **Cmd+K command palette** globally available
- **Framer Motion** animations + Recharts data viz

## Pages (Phase 1)

- `/` — Command center overview (fleet map, KPIs, agent feed, cluster heatmap, revenue)
- `/fleet` — Phone grid with live per-device state
- `/personas` — Persona profiles with per-persona KPI rollups
- `/accounts` — Full account table with health + re-wake day
- `/agents` — Live agent mesh activity feed + per-agent control panel
- `/targets` — Fresh target queue + source pool rankings
- `/cluster` — Live cluster monitor with 20-dim fingerprint heatmap
- `/funnel` — Fan → OF/Fanvue/ScaleHer conversion waterfall
- `/content` — Content Vault browser
- `/analytics` — Historical KPIs + cohort analysis
- `/settings` — Proxy config, persona tuning, audit harness controls

## Dev

```bash
npm install
npm run dev   # serves on http://localhost:3016
```

Requires the Phantom Fleet backend running on `http://localhost:8000`.
