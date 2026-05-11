"use client";

import { useEffect, useState, useRef } from "react";
import {
  Brain,
  Pause,
  Play,
  RefreshCw,
  Smartphone,
  Users,
  Zap,
  DollarSign,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Activity,
  Layers,
} from "lucide-react";
import { Panel } from "@/components/panel";
import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BrainStatus = "running" | "paused" | "error" | "stopped";

type OpsStatus = {
  status: BrainStatus;
  cycle_count: number;
  consecutive_failures: number;
  rule_based_mode: boolean;
  last_cycle_iso: string | null;
  next_cycle_in_sec: number | null;
};

type CycleReport = {
  cycle_id: string;
  started_at_iso: string;
  completed_at_iso: string;
  duration_sec: number;
  phones_online: number;
  accounts_active: number;
  accounts_dead_this_cycle: number;
  accounts_replaced_this_cycle: number;
  platform_cycles_completed: Record<string, boolean>;
  alerts_fired: number;
  llm_cost_usd: number;
  status: "success" | "partial" | "failed";
  errors: string[];
};

type HealthSnapshot = {
  online_phones: number;
  proxy_ready: number;
  active_accounts: number;
  dead_accounts: number;
  sessions_valid: number;
};

type Alert = {
  alert_id: string;
  severity: string;
  dimension: string;
  description: string;
  ts_iso: string;
};

type ActivityItem = {
  id: string;
  text: string;
  ts: string;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

const PLATFORMS = [
  "instagram", "threads", "reddit", "x", "tiktok",
  "telegram", "discord", "dating", "bluesky",
];

const CYCLE_INTERVAL_MS = 600_000; // 10 min

// ---------------------------------------------------------------------------
// Status badge helpers
// ---------------------------------------------------------------------------

function BrainStatusBadge({ status }: { status: BrainStatus }) {
  const cfg = {
    running: { label: "RUNNING",  dot: "phantom-dot-accent animate-phantom-pulse", text: "text-phantom-accent" },
    paused:  { label: "PAUSED",   dot: "phantom-dot-warning",                       text: "text-phantom-amber" },
    error:   { label: "ERROR",    dot: "phantom-dot-critical animate-phantom-pulse", text: "text-phantom-red" },
    stopped: { label: "STOPPED",  dot: "bg-phantom-ghost",                           text: "text-phantom-ghost" },
  } as const;
  const c = cfg[status] ?? cfg.stopped;
  return (
    <div className={cn("flex items-center gap-2 font-mono text-xs font-bold tracking-widest", c.text)}>
      <span className={cn("phantom-dot", c.dot)} />
      {c.label}
    </div>
  );
}

function CycleStatusPill({ status }: { status: "success" | "partial" | "failed" }) {
  const cfg = {
    success: "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/30",
    partial: "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/30",
    failed:  "bg-phantom-red/10  text-phantom-red  border-phantom-red/30",
  };
  return (
    <span className={cn("px-2 py-0.5 rounded border text-[10px] font-mono uppercase tracking-wider", cfg[status])}>
      {status}
    </span>
  );
}

function PlatformCard({
  platform,
  completed,
  report,
}: {
  platform: string;
  completed: boolean | undefined;
  report: CycleReport | null;
}) {
  const active = completed === true;
  const failed = completed === false;
  return (
    <div className={cn(
      "phantom-panel p-4 border rounded-xl flex flex-col gap-2",
      active ? "border-phantom-alive/20" : failed ? "border-phantom-red/20" : "border-phantom-border"
    )}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium capitalize tracking-wide">{platform}</span>
        {active
          ? <CheckCircle2 className="w-3.5 h-3.5 text-phantom-alive" />
          : failed
          ? <XCircle className="w-3.5 h-3.5 text-phantom-red" />
          : <Clock className="w-3.5 h-3.5 text-phantom-ghost" />}
      </div>
      <div className={cn(
        "text-[10px] font-mono uppercase tracking-wider",
        active ? "text-phantom-alive" : failed ? "text-phantom-red" : "text-phantom-ghost"
      )}>
        {active ? "cycle ok" : failed ? "cycle failed" : "pending"}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Countdown hook
// ---------------------------------------------------------------------------

function useCountdown(lastCycleIso: string | null) {
  const [secsLeft, setSecsLeft] = useState<number | null>(null);

  useEffect(() => {
    if (!lastCycleIso) { setSecsLeft(null); return; }
    const update = () => {
      const last = new Date(lastCycleIso).getTime();
      const next = last + CYCLE_INTERVAL_MS;
      const diff = Math.round((next - Date.now()) / 1000);
      setSecsLeft(Math.max(0, diff));
    };
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, [lastCycleIso]);

  return secsLeft;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OpsPage() {
  const [opsStatus,  setOpsStatus]  = useState<OpsStatus | null>(null);
  const [latestCycle, setLatestCycle] = useState<CycleReport | null>(null);
  const [cycleHistory, setCycleHistory] = useState<CycleReport[]>([]);
  const [health, setHealth]         = useState<HealthSnapshot | null>(null);
  const [alerts, setAlerts]         = useState<Alert[]>([]);
  const [activityFeed, setActivityFeed] = useState<ActivityItem[]>([]);
  const [loading, setLoading]       = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const countdown = useCountdown(opsStatus?.last_cycle_iso ?? null);

  // ------------------------------------------------------------------
  // Fetch
  // ------------------------------------------------------------------

  async function fetchAll() {
    try {
      const [statusRes, cycleRes, historyRes] = await Promise.all([
        fetch(`${API_BASE}/api/ops/status`),
        fetch(`${API_BASE}/api/ops/cycle/latest`),
        fetch(`${API_BASE}/api/ops/cycle/history`),
      ]);
      if (statusRes.ok)  setOpsStatus(await statusRes.json());
      if (cycleRes.ok)   setLatestCycle(await cycleRes.json());
      if (historyRes.ok) setCycleHistory(await historyRes.json());
    } catch {
      // API might not be running in dev
    } finally {
      setLoading(false);
    }
  }

  // ------------------------------------------------------------------
  // WebSocket for live feed
  // ------------------------------------------------------------------

  useEffect(() => {
    fetchAll();
    const poll = setInterval(fetchAll, 30_000);

    const wsUrl = API_BASE.replace(/^http/, "ws") + "/ws/ops";
    try {
      const ws = new WebSocket(wsUrl);
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "ops_snapshot") {
            if (msg.status)  setOpsStatus((prev) => prev ? { ...prev, status: msg.status, cycle_count: msg.cycle_count ?? prev.cycle_count, rule_based_mode: msg.rule_based_mode ?? prev.rule_based_mode } : null);
            if (msg.health)  setHealth(msg.health);
            if (msg.alerts)  setAlerts(msg.alerts ?? []);
            // Add to activity feed
            if (msg.last_cycle?.status) {
              const item: ActivityItem = {
                id:   Date.now().toString(),
                text: `Cycle ${msg.cycle_count} — ${msg.last_cycle.status} (${msg.last_cycle.duration_sec?.toFixed(1)}s)`,
                ts:   msg.ts_iso ?? new Date().toISOString(),
              };
              setActivityFeed((prev) => [item, ...prev].slice(0, 40));
            }
          }
        } catch { /* ignore */ }
      };
      wsRef.current = ws;
    } catch { /* WS not available in SSR */ }

    return () => {
      clearInterval(poll);
      wsRef.current?.close();
    };
  }, []);

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  async function handlePause() {
    setActionLoading(true);
    try {
      await fetch(`${API_BASE}/api/ops/pause`, { method: "POST" });
      await fetchAll();
    } finally { setActionLoading(false); }
  }

  async function handleResume() {
    setActionLoading(true);
    try {
      await fetch(`${API_BASE}/api/ops/resume`, { method: "POST" });
      await fetchAll();
    } finally { setActionLoading(false); }
  }

  async function handleTriggerCycle() {
    setActionLoading(true);
    try {
      await fetch(`${API_BASE}/api/ops/cycle/trigger`, { method: "POST" });
      const item: ActivityItem = {
        id:   Date.now().toString(),
        text: "Manual cycle triggered",
        ts:   new Date().toISOString(),
      };
      setActivityFeed((prev) => [item, ...prev].slice(0, 40));
      setTimeout(fetchAll, 3000);
    } finally { setActionLoading(false); }
  }

  // ------------------------------------------------------------------
  // Derived values
  // ------------------------------------------------------------------

  const status  = opsStatus?.status ?? "stopped";
  const isPaused = status === "paused";
  const isError  = status === "error";

  const actionsToday = cycleHistory.reduce(
    (acc, r) => acc + (r.accounts_active ?? 0),
    0
  );
  const llmCostToday = cycleHistory.reduce(
    (acc, r) => acc + (r.llm_cost_usd ?? 0),
    0
  );

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Autonomous operations
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <Brain className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            Ops <span className="phantom-accent-text">Brain</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            Zero-watch operations layer. Chief → platform managers → specialists running 24/7.
            Set it and forget it for days at a time.
          </p>
        </div>

        {/* Control buttons */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={handleTriggerCycle}
            disabled={actionLoading || isPaused || isError}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-phantom-accent/30 text-phantom-accent hover:bg-phantom-accent/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw className={cn("w-4 h-4", actionLoading && "animate-spin")} strokeWidth={1.75} />
            Trigger Cycle
          </button>
          {isPaused ? (
            <button
              onClick={handleResume}
              disabled={actionLoading}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-phantom-alive/30 text-phantom-alive hover:bg-phantom-alive/10 disabled:opacity-40 transition-colors"
            >
              <Play className="w-4 h-4" strokeWidth={1.75} />
              Resume
            </button>
          ) : (
            <button
              onClick={handlePause}
              disabled={actionLoading}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-phantom-amber/30 text-phantom-amber hover:bg-phantom-amber/10 disabled:opacity-40 transition-colors"
            >
              <Pause className="w-4 h-4" strokeWidth={1.75} />
              Pause Fleet
            </button>
          )}
        </div>
      </div>

      {/* Top bar: Brain status + cycle info */}
      <div className="phantom-panel p-5 flex items-center justify-between flex-wrap gap-4 border-phantom-border">
        <div className="flex items-center gap-6 flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">Brain status</div>
            <BrainStatusBadge status={status} />
          </div>
          <div className="w-px h-8 bg-phantom-border hidden sm:block" />
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">Cycle #</div>
            <div className="font-mono font-bold text-lg tabular-nums">
              {loading ? "—" : (opsStatus?.cycle_count ?? 0)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">Last cycle</div>
            <div className="font-mono text-sm text-phantom-subtext">
              {latestCycle?.completed_at_iso
                ? new Date(latestCycle.completed_at_iso).toLocaleTimeString()
                : "—"}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">Next cycle</div>
            <div className="font-mono text-sm tabular-nums">
              {countdown !== null
                ? countdown > 0
                  ? `${Math.floor(countdown / 60)}m ${countdown % 60}s`
                  : "now"
                : "—"}
            </div>
          </div>
          {opsStatus?.rule_based_mode && (
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-phantom-amber/10 border border-phantom-amber/30 text-phantom-amber text-xs font-medium">
              <AlertTriangle className="w-3 h-3" />
              Rule-based mode (LLM cap)
            </div>
          )}
        </div>
        {latestCycle && (
          <CycleStatusPill status={latestCycle.status} />
        )}
      </div>

      {/* Live metrics strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="phantom-panel p-5 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-phantom-alive/10 flex items-center justify-center shrink-0">
            <Smartphone className="w-4 h-4 text-phantom-alive" strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-2xl font-display font-bold tabular-nums text-phantom-alive">
              {health?.online_phones ?? latestCycle?.phones_online ?? "—"}
            </div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Phones online</div>
          </div>
        </div>
        <div className="phantom-panel p-5 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-phantom-accent/10 flex items-center justify-center shrink-0">
            <Users className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-2xl font-display font-bold tabular-nums">
              {health?.active_accounts ?? latestCycle?.accounts_active ?? "—"}
            </div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Accounts active</div>
          </div>
        </div>
        <div className="phantom-panel p-5 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-phantom-magenta/10 flex items-center justify-center shrink-0">
            <Zap className="w-4 h-4 text-phantom-magenta" strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-2xl font-display font-bold tabular-nums">
              {actionsToday.toLocaleString()}
            </div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Actions today</div>
          </div>
        </div>
        <div className="phantom-panel p-5 flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-phantom-amber/10 flex items-center justify-center shrink-0">
            <DollarSign className="w-4 h-4 text-phantom-amber" strokeWidth={1.75} />
          </div>
          <div>
            <div className="text-2xl font-display font-bold tabular-nums font-mono">
              ${llmCostToday.toFixed(2)}
            </div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">LLM cost today</div>
          </div>
        </div>
      </div>

      {/* Platform grid + Activity feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Platform grid */}
        <div className="lg:col-span-2">
          <Panel label="platform managers" title="Current cycle status by platform">
            <div className="grid grid-cols-3 gap-3">
              {PLATFORMS.map((p) => (
                <PlatformCard
                  key={p}
                  platform={p}
                  completed={latestCycle?.platform_cycles_completed?.[p]}
                  report={latestCycle}
                />
              ))}
            </div>
            {latestCycle && (
              <div className="mt-4 pt-4 border-t border-phantom-border flex items-center justify-between text-xs text-phantom-ghost">
                <span>Cycle <span className="font-mono">{latestCycle.cycle_id.slice(0, 8)}</span></span>
                <span>{latestCycle.duration_sec.toFixed(1)}s</span>
                {latestCycle.accounts_dead_this_cycle > 0 && (
                  <span className="text-phantom-amber">{latestCycle.accounts_dead_this_cycle} dead, {latestCycle.accounts_replaced_this_cycle} replaced</span>
                )}
              </div>
            )}
          </Panel>
        </div>

        {/* Live activity feed */}
        <div className="flex flex-col gap-6">
          <Panel label="live feed" title="Activity stream">
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {activityFeed.length === 0 ? (
                <div className="text-xs text-phantom-ghost py-4 text-center">
                  Waiting for WebSocket connection…
                </div>
              ) : (
                activityFeed.map((item) => (
                  <div key={item.id} className="flex items-start gap-2 text-xs">
                    <span className="phantom-dot phantom-dot-accent mt-1.5 shrink-0" />
                    <span className="text-phantom-subtext leading-relaxed">{item.text}</span>
                  </div>
                ))
              )}
            </div>
          </Panel>
        </div>
      </div>

      {/* Alert panel */}
      <Panel label="fleet alerts" title="Active alerts">
        {alerts.length === 0 && !loading ? (
          <div className="flex items-center gap-2 text-sm text-phantom-alive py-2">
            <CheckCircle2 className="w-4 h-4" />
            No active alerts
          </div>
        ) : (
          <div className="space-y-2">
            {alerts.map((alert, i) => (
              <div
                key={alert.alert_id ?? i}
                className={cn(
                  "flex items-start gap-3 p-3 rounded-lg border text-sm",
                  alert.severity === "critical" && "border-phantom-red/30 bg-phantom-red/5",
                  alert.severity === "high"     && "border-phantom-accent/30 bg-phantom-accent/5",
                  alert.severity === "medium"   && "border-phantom-amber/30 bg-phantom-amber/5",
                  alert.severity === "low"      && "border-phantom-border bg-phantom-panelHi",
                )}
              >
                <AlertTriangle className={cn(
                  "w-4 h-4 mt-0.5 shrink-0",
                  alert.severity === "critical" && "text-phantom-red",
                  alert.severity === "high"     && "text-phantom-accent",
                  alert.severity === "medium"   && "text-phantom-amber",
                  alert.severity === "low"      && "text-phantom-ghost",
                )} />
                <div className="flex-1 min-w-0">
                  <div className="font-medium capitalize text-xs tracking-wide">
                    {alert.dimension?.replace(/_/g, " ")}
                  </div>
                  <div className="text-phantom-ghost text-xs mt-0.5 leading-relaxed">
                    {alert.description}
                  </div>
                </div>
                <div className="text-[10px] text-phantom-ghost font-mono shrink-0">
                  {alert.ts_iso ? new Date(alert.ts_iso).toLocaleTimeString() : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {/* Cycle history */}
      <Panel label="cycle history" title="Last 24 cycles">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-phantom-ghost uppercase tracking-[0.1em] border-b border-phantom-border">
                <th className="text-left pb-3 font-medium">Cycle</th>
                <th className="text-left pb-3 font-medium">Started</th>
                <th className="text-right pb-3 font-medium">Duration</th>
                <th className="text-right pb-3 font-medium">Phones</th>
                <th className="text-right pb-3 font-medium">Accounts</th>
                <th className="text-right pb-3 font-medium">Dead→Replaced</th>
                <th className="text-right pb-3 font-medium">Alerts</th>
                <th className="text-right pb-3 font-medium">LLM $</th>
                <th className="text-right pb-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {cycleHistory.length === 0 ? (
                <tr>
                  <td colSpan={9} className="text-phantom-ghost py-4 text-center">
                    No cycles yet
                  </td>
                </tr>
              ) : (
                cycleHistory.map((r, i) => (
                  <tr key={r.cycle_id} className={cn(
                    "border-b border-phantom-border/40 hover:bg-phantom-panelHi/40 transition-colors",
                    i === 0 && "bg-phantom-panelHi/20"
                  )}>
                    <td className="py-3 font-mono text-phantom-ghost">{r.cycle_id.slice(0, 8)}</td>
                    <td className="py-3 text-phantom-subtext">
                      {new Date(r.started_at_iso).toLocaleTimeString()}
                    </td>
                    <td className="py-3 text-right font-mono tabular-nums">{r.duration_sec.toFixed(1)}s</td>
                    <td className="py-3 text-right tabular-nums">{r.phones_online}</td>
                    <td className="py-3 text-right tabular-nums">{r.accounts_active}</td>
                    <td className="py-3 text-right tabular-nums">
                      {r.accounts_dead_this_cycle > 0
                        ? <span className="text-phantom-amber">{r.accounts_dead_this_cycle}→{r.accounts_replaced_this_cycle}</span>
                        : <span className="text-phantom-ghost">—</span>}
                    </td>
                    <td className="py-3 text-right tabular-nums">
                      {r.alerts_fired > 0
                        ? <span className="text-phantom-amber">{r.alerts_fired}</span>
                        : "—"}
                    </td>
                    <td className="py-3 text-right font-mono tabular-nums">${r.llm_cost_usd.toFixed(3)}</td>
                    <td className="py-3 text-right">
                      <CycleStatusPill status={r.status} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
