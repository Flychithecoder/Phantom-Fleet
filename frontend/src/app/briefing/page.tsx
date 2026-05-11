"use client";

import { Panel } from "@/components/panel";
import { DataTable, Column } from "@/components/data-table";
import { Newspaper, RefreshCw, CheckCircle, AlertTriangle, Circle } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Fleet Health ────────────────────────────────────────────────────────────

type PlatformHealth = {
  id: string;
  platform: string;
  status: "healthy" | "degraded" | "paused";
  online: number;
  total: number;
  paused: number;
  note: string;
};

const PLATFORM_HEALTH: PlatformHealth[] = [
  { id: "ig",      platform: "Instagram",  status: "healthy",  online: 97,  total: 97,  paused: 0,  note: "All 97 accounts posting normally. Avg session 38min." },
  { id: "threads", platform: "Threads",    status: "healthy",  online: 122, total: 122, paused: 0,  note: "DM pipeline running. 14 conversations in Stage 3." },
  { id: "tiktok",  platform: "TikTok",     status: "degraded", online: 41,  total: 44,  paused: 3,  note: "3 accounts held: warmup graduation pending manual approval." },
  { id: "dating",  platform: "Dating",     status: "healthy",  online: 28,  total: 28,  paused: 0,  note: "Tinder + Hinge feeds active. 6 matches converted yesterday." },
  { id: "reddit",  platform: "Reddit",     status: "paused",   online: 0,   total: 12,  paused: 12, note: "Scheduled maintenance window 06:00–10:00 UTC. Resuming." },
];

function StatusDot({ status }: { status: PlatformHealth["status"] }) {
  return (
    <span
      className={cn(
        "inline-block w-2.5 h-2.5 rounded-full ring-2 ring-offset-1 ring-offset-phantom-panel",
        status === "healthy"  && "bg-phantom-alive ring-phantom-alive/30 shadow-[0_0_6px_hsl(120_100%_50%/0.5)]",
        status === "degraded" && "bg-phantom-amber ring-phantom-amber/30 animate-pulse",
        status === "paused"   && "bg-phantom-ghost ring-phantom-ghost/20",
      )}
    />
  );
}

// ─── Yesterday's Performance ──────────────────────────────────────────────────

type PerfMetric = {
  id: string;
  label: string;
  value: string;
  prev: string;
  delta: number;
  positive: boolean;
};

const PERF: PerfMetric[] = [
  { id: "follows",  label: "Follows sent",   value: "3,841",  prev: "3,620",  delta: +6.1,  positive: true  },
  { id: "dms",      label: "DMs sent",       value: "2,109",  prev: "1,974",  delta: +6.8,  positive: true  },
  { id: "clicks",   label: "Link clicks",    value: "847",    prev: "791",    delta: +7.1,  positive: true  },
  { id: "convs",    label: "Conversions",    value: "29",     prev: "31",     delta: -6.5,  positive: false },
  { id: "revenue",  label: "Revenue",        value: "$1,247", prev: "$1,138", delta: +9.6,  positive: true  },
];

// ─── Today's Priorities ───────────────────────────────────────────────────────

type Priority = {
  id: string;
  urgency: "high" | "medium" | "low";
  title: string;
  detail: string;
  agent: string;
};

const PRIORITIES: Priority[] = [
  {
    id: "p1",
    urgency: "high",
    title: "3 TikTok accounts graduating warmup — approve for steady state",
    detail: "@kira_glow22, @daisy_vibesxx, @noelle_rune have cleared 21-day warmup with zero flags. Recommend approval.",
    agent: "WarmupAgent",
  },
  {
    id: "p2",
    urgency: "high",
    title: "Shadowban probe due for 23 Threads accounts",
    detail: "Weekly probe window opens at 10:00 UTC. Probe takes ~45 min. BanGuard will auto-pause if positive rate >8%.",
    agent: "BanGuardAgent",
  },
  {
    id: "p3",
    urgency: "medium",
    title: "DM template A/B test at 95% confidence — declare winner",
    detail: "Template B (friendly intro variant) achieved 34.2% reply rate vs Template A at 28.7%. Recommend promoting B.",
    agent: "CopyAgent",
  },
  {
    id: "p4",
    urgency: "medium",
    title: "Proxy pool rotation review — 14 IPs aged 72h+",
    detail: "14 residential IPs approaching optimal 72h cycle. ProxyOrchestrator recommends scheduled swap during next low-traffic window (03:00 UTC).",
    agent: "ProxyOrchestrator",
  },
  {
    id: "p5",
    urgency: "low",
    title: "Content pool refresh — 11 personas below 48h buffer",
    detail: "IG personas: @vivienne_co, @leila_xox3, @piper_aura have <48h of queued content. ContentAgent ready to generate on approval.",
    agent: "ContentAgent",
  },
];

function UrgencyBadge({ urgency }: { urgency: Priority["urgency"] }) {
  return (
    <span
      className={cn(
        "inline-flex px-1.5 py-0.5 rounded text-[9px] font-mono tracking-wider border",
        urgency === "high"   && "bg-phantom-red/10 text-phantom-red border-phantom-red/30",
        urgency === "medium" && "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/30",
        urgency === "low"    && "bg-phantom-ghost/10 text-phantom-ghost border-phantom-ghost/20",
      )}
    >
      {urgency.toUpperCase()}
    </span>
  );
}

// ─── Anomalies & Alerts ───────────────────────────────────────────────────────

type Alert = {
  id: string;
  severity: "warning" | "info" | "resolved";
  time: string;
  message: string;
  action: string;
};

const ALERTS: Alert[] = [
  {
    id: "a1",
    severity: "warning",
    time: "02:14 UTC",
    message: "Proxy IP 203.44.17.89 rate-limited on IG — 429 errors from 3 accounts over 12 min.",
    action: "Swapped to backup IP 203.44.21.14. Affected accounts resumed at 02:19 UTC.",
  },
  {
    id: "a2",
    severity: "warning",
    time: "04:38 UTC",
    message: "Account @melodie_xx soft-limited on Threads — engagement reach dropped ~70%.",
    action: "Holding 24h. Scheduled shadowban probe at 10:00 UTC. DM activity paused.",
  },
  {
    id: "a3",
    severity: "info",
    time: "05:55 UTC",
    message: "IG session token refreshed for 97 accounts — nightly rotation completed.",
    action: "All 97 tokens valid. Next rotation: 06:00 UTC tomorrow.",
  },
  {
    id: "a4",
    severity: "resolved",
    time: "01:02 UTC",
    message: "TikTok upload queue stalled — 3 videos pending >15 min.",
    action: "Resolved by ContentAgent retry at 01:07 UTC. All 3 uploads confirmed.",
  },
];

function AlertIcon({ severity }: { severity: Alert["severity"] }) {
  if (severity === "resolved") return <CheckCircle className="w-4 h-4 text-phantom-alive flex-shrink-0" />;
  if (severity === "warning")  return <AlertTriangle className="w-4 h-4 text-phantom-amber flex-shrink-0" />;
  return <Circle className="w-4 h-4 text-phantom-accent flex-shrink-0" />;
}

// ─── Cost Summary ─────────────────────────────────────────────────────────────

const COSTS = [
  { label: "OpenRouter (yesterday)",   value: "$3.84",  sub: "2.1M tokens · avg $1.83/1M" },
  { label: "Proxy bandwidth (Apr)",    value: "$62.40", sub: "IPRoyal Residential · 3.12GB" },
  { label: "Estimated daily run rate", value: "$7.20",  sub: "LLM $3.80 + proxy $2.40 + misc $1.00" },
  { label: "MoM projection (Apr)",     value: "$216",   sub: "Budget: $300 · 72% utilization" },
];

// ─── Agent Run Log ────────────────────────────────────────────────────────────

type AgentRun = {
  id: string;
  agent: string;
  started: string;
  duration: string;
  actions: number;
  status: "success" | "partial" | "failed";
  cost: string;
  note: string;
};

const AGENT_RUNS: AgentRun[] = [
  { id: "r1",  agent: "TargetDiscoveryAgent",   started: "00:01 UTC", duration: "18 min", actions: 14620, status: "success", cost: "$0.21", note: "14,620 raw targets scraped. 4,280 passed filters." },
  { id: "r2",  agent: "FollowAgent (Tatiana)",   started: "00:30 UTC", duration: "4h 12m", actions: 1920,  status: "success", cost: "$0.04", note: "1,920 follows dispatched. 0 blocks." },
  { id: "r3",  agent: "FollowAgent (Melodie)",   started: "00:30 UTC", duration: "4h 08m", actions: 1921,  status: "success", cost: "$0.04", note: "1,921 follows dispatched. 0 blocks." },
  { id: "r4",  agent: "DMAgent (Stage 1→2)",     started: "01:00 UTC", duration: "2h 44m", actions: 847,   status: "success", cost: "$0.38", note: "847 DMs sent. 291 opens (34.4%)." },
  { id: "r5",  agent: "ContentAgent",            started: "02:00 UTC", duration: "31 min", actions: 143,   status: "success", cost: "$1.12", note: "143 captions + 28 bio variants generated." },
  { id: "r6",  agent: "BanGuardAgent",           started: "03:00 UTC", duration: "9 min",  actions: 219,   status: "success", cost: "$0.07", note: "219 accounts probed. 1 soft-limit detected." },
  { id: "r7",  agent: "ProxyOrchestrator",       started: "03:15 UTC", duration: "4 min",  actions: 14,    status: "success", cost: "$0.01", note: "14 IPs rotated on schedule." },
  { id: "r8",  agent: "WarmupAgent (TikTok)",    started: "04:00 UTC", duration: "12 min", actions: 3,     status: "partial", cost: "$0.02", note: "3 accounts ready for graduation — awaiting manual approval." },
  { id: "r9",  agent: "SessionRefreshAgent",     started: "06:00 UTC", duration: "7 min",  actions: 97,    status: "success", cost: "$0.00", note: "97 IG session tokens refreshed." },
  { id: "r10", agent: "AnalyticsAggregator",     started: "06:30 UTC", duration: "3 min",  actions: 219,   status: "success", cost: "$0.03", note: "Daily metrics aggregated. Report ready." },
];

const agentColumns: Column<AgentRun>[] = [
  {
    key: "agent",
    header: "Agent",
    render: (r) => <span className="font-mono text-white text-xs">{r.agent}</span>,
  },
  {
    key: "started",
    header: "Started",
    render: (r) => <span className="font-mono text-phantom-ghost text-xs">{r.started}</span>,
  },
  {
    key: "duration",
    header: "Duration",
    render: (r) => <span className="font-mono text-xs tabular-nums">{r.duration}</span>,
  },
  {
    key: "actions",
    header: "Actions",
    align: "right",
    render: (r) => <span className="font-mono text-xs tabular-nums">{r.actions.toLocaleString()}</span>,
  },
  {
    key: "status",
    header: "Status",
    render: (r) => (
      <span
        className={cn(
          "inline-flex px-2 py-0.5 rounded text-[9px] font-mono tracking-wider border",
          r.status === "success" && "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/30",
          r.status === "partial" && "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/30",
          r.status === "failed"  && "bg-phantom-red/10 text-phantom-red border-phantom-red/30",
        )}
      >
        {r.status.toUpperCase()}
      </span>
    ),
  },
  {
    key: "cost",
    header: "Cost",
    align: "right",
    render: (r) => <span className="font-mono text-xs text-phantom-ghost tabular-nums">{r.cost}</span>,
  },
  {
    key: "note",
    header: "Note",
    render: (r) => <span className="text-xs text-phantom-ghost">{r.note}</span>,
  },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BriefingPage() {
  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Chief Agent · daily briefing
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <Newspaper className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            Daily <span className="phantom-accent-text">Briefing</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm">
            Monday, April 13, 2026
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <button className="flex items-center gap-2 px-4 py-2 rounded-lg bg-phantom-panelHi border border-phantom-border text-sm font-medium hover:border-phantom-accent/50 hover:text-phantom-accent transition-colors">
            <RefreshCw className="w-4 h-4" />
            Regenerate
          </button>
          <div className="text-[10px] text-phantom-ghost font-mono">
            Generated at 07:00 UTC · Next: 07:00 tomorrow
          </div>
        </div>
      </div>

      {/* 1. Fleet Health */}
      <Panel label="section 1 of 6" title="Fleet Health" subtitle="Real-time status per platform as of briefing generation time.">
        <div className="space-y-3">
          {PLATFORM_HEALTH.map((p) => (
            <div
              key={p.id}
              className="flex items-start gap-4 p-4 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50"
            >
              <StatusDot status={p.status} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="font-medium text-sm text-white">{p.platform}</span>
                  <span
                    className={cn(
                      "text-[9px] font-mono px-1.5 py-0.5 rounded border",
                      p.status === "healthy"  && "text-phantom-alive border-phantom-alive/30 bg-phantom-alive/10",
                      p.status === "degraded" && "text-phantom-amber border-phantom-amber/30 bg-phantom-amber/10",
                      p.status === "paused"   && "text-phantom-ghost border-phantom-ghost/20 bg-phantom-ghost/10",
                    )}
                  >
                    {p.status.toUpperCase()}
                  </span>
                  <span className="text-xs font-mono text-phantom-ghost tabular-nums">
                    {p.online}/{p.total} online
                    {p.paused > 0 && (
                      <span className="text-phantom-amber ml-2">· {p.paused} paused</span>
                    )}
                  </span>
                </div>
                <p className="text-xs text-phantom-ghost mt-1">{p.note}</p>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* 2. Yesterday's Performance */}
      <Panel label="section 2 of 6" title="Yesterday's Performance" subtitle="Apr 12 vs Apr 11 across all platforms and personas.">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          {PERF.map((m) => (
            <div key={m.id} className="phantom-panel p-4">
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">{m.label}</div>
              <div className="phantom-metric-lg mt-2">{m.value}</div>
              <div className={cn(
                "text-xs font-mono mt-1 flex items-center gap-1",
                m.positive ? "text-phantom-alive" : "text-phantom-red",
              )}>
                {m.positive ? "↑" : "↓"} {Math.abs(m.delta).toFixed(1)}%
                <span className="text-phantom-ghost normal-case font-sans text-[10px]">vs {m.prev}</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* 3. Today's Priorities */}
      <Panel label="section 3 of 6" title="Today's Priorities" subtitle="5 recommended actions from the Chief Agent for the current operational day.">
        <div className="space-y-3">
          {PRIORITIES.map((p, i) => (
            <div key={p.id} className="flex gap-4 p-4 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
              <div className="flex-shrink-0 flex items-center justify-center w-7 h-7 rounded-full bg-phantom-panelHi border border-phantom-border font-mono text-xs text-phantom-ghost">
                {i + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start gap-2 flex-wrap">
                  <UrgencyBadge urgency={p.urgency} />
                  <span className="text-sm text-white font-medium leading-snug">{p.title}</span>
                </div>
                <p className="text-xs text-phantom-ghost mt-1.5">{p.detail}</p>
                <div className="text-[10px] font-mono text-phantom-accent mt-1.5">
                  agent: {p.agent}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* 4. Anomalies & Alerts */}
      <Panel label="section 4 of 6" title="Anomalies & Alerts" subtitle="Flags detected overnight by BanGuardAgent, ProxyOrchestrator, and SessionAgent.">
        <div className="space-y-3">
          {ALERTS.map((a) => (
            <div key={a.id} className="flex gap-3 p-4 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
              <AlertIcon severity={a.severity} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 flex-wrap mb-1">
                  <span className="text-[10px] font-mono text-phantom-ghost">{a.time}</span>
                  <span
                    className={cn(
                      "text-[9px] font-mono px-1.5 py-0.5 rounded border",
                      a.severity === "warning"  && "text-phantom-amber border-phantom-amber/30 bg-phantom-amber/10",
                      a.severity === "info"     && "text-phantom-accent border-phantom-accent/30 bg-phantom-accent/10",
                      a.severity === "resolved" && "text-phantom-alive border-phantom-alive/30 bg-phantom-alive/10",
                    )}
                  >
                    {a.severity.toUpperCase()}
                  </span>
                </div>
                <p className="text-sm text-white leading-snug">{a.message}</p>
                <p className="text-xs text-phantom-ghost mt-1">
                  <span className="text-phantom-accent font-mono">→</span> {a.action}
                </p>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* 5. Cost Summary */}
      <Panel label="section 5 of 6" title="Cost Summary" subtitle="Yesterday's operational spend and monthly projection.">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {COSTS.map((c) => (
            <div key={c.label} className="phantom-panel p-4">
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">{c.label}</div>
              <div className="phantom-metric-lg mt-2 text-phantom-accent">{c.value}</div>
              <div className="text-[10px] text-phantom-ghost mt-1">{c.sub}</div>
            </div>
          ))}
        </div>
        {/* Budget bar */}
        <div className="mt-5 p-4 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-phantom-ghost">April budget utilization</span>
            <span className="text-xs font-mono text-white">$216 / $300 <span className="text-phantom-ghost">(72%)</span></span>
          </div>
          <div className="w-full h-2 rounded-full bg-phantom-panelHi overflow-hidden">
            <div
              className="h-full rounded-full bg-phantom-accent shadow-[0_0_8px_hsl(162_100%_54%/0.4)]"
              style={{ width: "72%" }}
            />
          </div>
          <div className="flex items-center justify-between mt-1.5">
            <span className="text-[10px] text-phantom-ghost">18 days elapsed</span>
            <span className="text-[10px] text-phantom-ghost">~$84 remaining · on track</span>
          </div>
        </div>
      </Panel>

      {/* 6. Agent Run Log */}
      <Panel label="section 6 of 6" title="Overnight Agent Run Log" subtitle="All agent executions since 00:00 UTC today. Cost attribution by agent.">
        <DataTable columns={agentColumns} rows={AGENT_RUNS} />
        {/* Totals row */}
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-phantom-border">
          <span className="text-xs text-phantom-ghost font-mono">10 agents · 100% success rate (1 partial)</span>
          <span className="text-xs font-mono text-phantom-accent">Total: $1.92</span>
        </div>
      </Panel>
    </div>
  );
}
