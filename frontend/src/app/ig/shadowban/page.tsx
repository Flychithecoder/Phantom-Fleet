"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { ShieldAlert, RefreshCw, CheckCircle2, XCircle, AlertTriangle, Circle } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type ProbeResult = "clean" | "shadowbanned" | "under_review" | "pending";
type ProbeType = "hashtag" | "explore" | "search";

type ProbeEntry = {
  id: string;
  account: string;
  probeType: ProbeType;
  lastProbe: string;
  result: ProbeResult;
  actionTaken: string;
};

const PROBE_QUEUE: ProbeEntry[] = [
  { id: "1",  account: "@luna_aesthetic_47",  probeType: "hashtag", lastProbe: "4m ago",   result: "clean",         actionTaken: "None — resumed" },
  { id: "2",  account: "@swift_emma_fit",     probeType: "explore", lastProbe: "8m ago",   result: "under_review",  actionTaken: "Rate reduced 50%" },
  { id: "3",  account: "@nova_daily_x",       probeType: "search",  lastProbe: "12m ago",  result: "shadowbanned",  actionTaken: "Paused + recovery queue" },
  { id: "4",  account: "@jade_glowup_22",     probeType: "hashtag", lastProbe: "15m ago",  result: "clean",         actionTaken: "None — resumed" },
  { id: "5",  account: "@grace_fit_life",     probeType: "explore", lastProbe: "21m ago",  result: "under_review",  actionTaken: "Cooldown 24h" },
  { id: "6",  account: "@aria_content_hub",   probeType: "hashtag", lastProbe: "28m ago",  result: "clean",         actionTaken: "None — resumed" },
  { id: "7",  account: "@stella_vibes_co",    probeType: "search",  lastProbe: "33m ago",  result: "pending",       actionTaken: "Awaiting probe result" },
  { id: "8",  account: "@zoe_aesthetic_91",   probeType: "explore", lastProbe: "38m ago",  result: "shadowbanned",  actionTaken: "Paused + recovery queue" },
  { id: "9",  account: "@ivy_wellness_page",  probeType: "hashtag", lastProbe: "45m ago",  result: "under_review",  actionTaken: "Watchlist — 12h hold" },
  { id: "10", account: "@rose_style_daily",   probeType: "search",  lastProbe: "51m ago",  result: "clean",         actionTaken: "None — resumed" },
  { id: "11", account: "@cleo_fitness_93",    probeType: "hashtag", lastProbe: "58m ago",  result: "pending",       actionTaken: "Probe queued" },
  { id: "12", account: "@maya_journal_co",    probeType: "explore", lastProbe: "1h ago",   result: "clean",         actionTaken: "None — resumed" },
];

type ShadowbanEvent = {
  id: string;
  account: string;
  detectedAt: string;
  timeline: { ts: string; event: string; type: "detect" | "pause" | "action" | "clear" }[];
  resolved: boolean;
};

const SHADOWBAN_HISTORY: ShadowbanEvent[] = [
  {
    id: "h1",
    account: "@nova_daily_x",
    detectedAt: "Apr 13, 09:14",
    resolved: false,
    timeline: [
      { ts: "09:14", event: "Hashtag visibility probe returned 0 posts — shadowban detected",  type: "detect" },
      { ts: "09:15", event: "Account paused. All scheduled actions halted immediately",         type: "pause" },
      { ts: "09:20", event: "Recovery protocol started: 72h rest + remove recent hashtags",    type: "action" },
      { ts: "09:21", event: "3 high-risk hashtags purged from post queue",                     type: "action" },
    ],
  },
  {
    id: "h2",
    account: "@zoe_aesthetic_91",
    detectedAt: "Apr 13, 07:52",
    resolved: false,
    timeline: [
      { ts: "07:52", event: "Explore feed probe: account not surfacing for any tested query",  type: "detect" },
      { ts: "07:53", event: "Account paused. DM quota set to 0",                               type: "pause" },
      { ts: "08:00", event: "Proxy rotated to fresh 4G residential IP",                        type: "action" },
      { ts: "08:05", event: "Bio link temporarily removed — platform link-spam trigger check", type: "action" },
    ],
  },
  {
    id: "h3",
    account: "@fern_aesthetic_33",
    detectedAt: "Apr 12, 14:30",
    resolved: true,
    timeline: [
      { ts: "14:30", event: "Search-visibility probe failed: account not discoverable by handle", type: "detect" },
      { ts: "14:31", event: "Account paused for 48h rest period",                                type: "pause" },
      { ts: "14:35", event: "Unblocked 12 ghost followers — report cluster suspected",           type: "action" },
      { ts: "Apr 13 10:20", event: "Re-probe passed all 3 checks — account cleared",           type: "clear" },
    ],
  },
];

type RiskFactor = {
  label: string;
  description: string;
  level: "safe" | "warning" | "danger";
  value: string;
  threshold: string;
};

const RISK_FACTORS: RiskFactor[] = [
  {
    label: "Follow Velocity",
    description: "Follows per hour across fleet",
    level: "safe",
    value: "4.2/hr avg",
    threshold: "< 6/hr safe",
  },
  {
    label: "Hashtag Density",
    description: "Avg hashtags per post in queue",
    level: "warning",
    value: "18.4 avg",
    threshold: "< 12 recommended",
  },
  {
    label: "DM Rate",
    description: "Cold DMs per account per day",
    level: "safe",
    value: "3.1/day avg",
    threshold: "< 5/day safe",
  },
  {
    label: "Report Velocity",
    description: "Estimated report signals (proxy metric)",
    level: "danger",
    value: "2.3 flags/day",
    threshold: "< 0.5/day safe",
  },
  {
    label: "Comment Repetition",
    description: "Template reuse rate across accounts",
    level: "warning",
    value: "34% similar",
    threshold: "< 20% safe",
  },
  {
    label: "Action Block Rate",
    description: "Soft blocks hit per 1000 actions",
    level: "safe",
    value: "0.8 per 1K",
    threshold: "< 2 per 1K safe",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ResultBadge({ result }: { result: ProbeResult }) {
  const map: Record<ProbeResult, { label: string; cls: string; icon: React.ReactNode }> = {
    clean:        { label: "Clean",        cls: "bg-phantom-alive/10 border-phantom-alive/20 text-phantom-alive",        icon: <CheckCircle2 className="w-3 h-3" /> },
    shadowbanned: { label: "Shadowbanned", cls: "bg-phantom-red/10 border-phantom-red/20 text-phantom-red",             icon: <XCircle className="w-3 h-3" /> },
    under_review: { label: "Under Review", cls: "bg-phantom-amber/10 border-phantom-amber/20 text-phantom-amber",       icon: <AlertTriangle className="w-3 h-3" /> },
    pending:      { label: "Pending",      cls: "bg-phantom-ghost/10 border-phantom-border text-phantom-ghost",         icon: <Circle className="w-3 h-3" /> },
  };
  const { label, cls, icon } = map[result];
  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold", cls)}>
      {icon}{label}
    </span>
  );
}

function ProbeTypeBadge({ type }: { type: ProbeType }) {
  const map: Record<ProbeType, string> = {
    hashtag: "text-phantom-magenta",
    explore: "text-phantom-accent",
    search:  "text-phantom-amber",
  };
  return <span className={cn("text-xs font-semibold capitalize", map[type])}>{type}</span>;
}

function TrafficLight({ level }: { level: RiskFactor["level"] }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className={cn("w-2.5 h-2.5 rounded-full", level === "safe" ? "bg-phantom-alive" : "bg-phantom-border/30")} />
      <div className={cn("w-2.5 h-2.5 rounded-full", level === "warning" ? "bg-phantom-amber" : "bg-phantom-border/30")} />
      <div className={cn("w-2.5 h-2.5 rounded-full", level === "danger" ? "bg-phantom-red" : "bg-phantom-border/30")} />
    </div>
  );
}

function TimelineEventDot({ type }: { type: ShadowbanEvent["timeline"][0]["type"] }) {
  const map = {
    detect: "bg-phantom-red",
    pause:  "bg-phantom-amber",
    action: "bg-phantom-accent",
    clear:  "bg-phantom-alive",
  };
  return <div className={cn("w-2 h-2 rounded-full shrink-0 mt-1", map[type])} />;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ShadowbanPage() {
  const [scanning, setScanning] = useState(false);
  const [probeFilter, setProbeFilter] = useState<"all" | "shadowbanned" | "under_review" | "clean">("all");

  const filteredProbes =
    probeFilter === "all" ? PROBE_QUEUE : PROBE_QUEUE.filter((p) => p.result === probeFilter);

  function handleFleetProbe() {
    setScanning(true);
    setTimeout(() => setScanning(false), 2800);
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Instagram · health monitoring
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <ShieldAlert className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Shadowban <span className="phantom-accent-text">Detector</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-red/10 border border-phantom-red/20 text-phantom-red text-xs font-semibold">
            4 shadowbanned
          </span>
          <span className="px-3 py-1 rounded-full bg-phantom-amber/10 border border-phantom-amber/20 text-phantom-amber text-xs font-semibold">
            23 under review
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Automated hashtag, Explore, and search-visibility probes run every 6 hours per account. Detections trigger immediate pause + recovery protocol.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Clean Accounts" value="820" sub="out of 847 total" delta={0.008} accent />
        <KPICard label="Under Review"  value="23"  sub="probe inconclusive" />
        <KPICard label="Shadowbanned"  value="4"   sub="paused + recovery active" />
        <KPICard label="Auto-Recovered (7d)" value="17" sub="cleared probe + resumed" delta={0.062} />
      </div>

      {/* Fleet-wide probe trigger */}
      <Panel
        label="probe control"
        title="Fleet-Wide Probe"
        subtitle="Dispatches a 3-check probe (hashtag / explore / search) to all 847 accounts over the next 45–90 minutes with randomized dispatch timing."
        actions={
          <button
            onClick={handleFleetProbe}
            disabled={scanning}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold border transition-all",
              scanning
                ? "bg-phantom-amber/10 border-phantom-amber/20 text-phantom-amber cursor-not-allowed"
                : "bg-phantom-accent/10 border-phantom-accent/20 text-phantom-accent hover:bg-phantom-accent/20"
            )}
          >
            <RefreshCw className={cn("w-4 h-4", scanning && "animate-spin")} />
            {scanning ? "Dispatching probes…" : "Run Fleet-Wide Probe"}
          </button>
        }
      >
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-lg bg-phantom-bg border border-phantom-border p-4">
            <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-2">Hashtag Probe</div>
            <div className="text-2xl font-bold tabular-nums text-phantom-accent">847</div>
            <div className="text-[11px] text-phantom-ghost mt-1">Posts hashtag, checks own visibility after 90s</div>
          </div>
          <div className="rounded-lg bg-phantom-bg border border-phantom-border p-4">
            <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-2">Explore Probe</div>
            <div className="text-2xl font-bold tabular-nums text-phantom-accent">847</div>
            <div className="text-[11px] text-phantom-ghost mt-1">Second account checks Explore feed surfacing</div>
          </div>
          <div className="rounded-lg bg-phantom-bg border border-phantom-border p-4">
            <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-2">Search Probe</div>
            <div className="text-2xl font-bold tabular-nums text-phantom-accent">847</div>
            <div className="text-[11px] text-phantom-ghost mt-1">Search-by-handle discoverability check</div>
          </div>
        </div>
      </Panel>

      {/* Live probe queue + risk factors */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Probe queue — 2/3 width */}
        <div className="lg:col-span-2">
          <Panel
            label="probe queue"
            title="Live Probe Results"
            subtitle={`${filteredProbes.length} entries · last 2 hours`}
            actions={
              <div className="flex gap-1.5">
                {(["all", "shadowbanned", "under_review", "clean"] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setProbeFilter(f)}
                    className={cn(
                      "px-2.5 py-1 rounded text-[10px] font-medium transition-all border",
                      probeFilter === f
                        ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                        : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                    )}
                  >
                    {f === "under_review" ? "Review" : f.charAt(0).toUpperCase() + f.slice(1)}
                  </button>
                ))}
              </div>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-phantom-border">
                    {["Account", "Probe", "Last Run", "Result", "Action Taken"].map((h) => (
                      <th key={h} className="text-left text-[10px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-3 font-medium whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-phantom-border/40">
                  {filteredProbes.map((row) => (
                    <tr key={row.id} className="hover:bg-phantom-panelHi/30 transition-colors">
                      <td className="py-3 pr-3 font-mono text-xs text-phantom-accent whitespace-nowrap">{row.account}</td>
                      <td className="py-3 pr-3"><ProbeTypeBadge type={row.probeType} /></td>
                      <td className="py-3 pr-3 text-xs text-phantom-ghost tabular-nums whitespace-nowrap font-mono">{row.lastProbe}</td>
                      <td className="py-3 pr-3"><ResultBadge result={row.result} /></td>
                      <td className="py-3 text-xs text-phantom-ghost">{row.actionTaken}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        {/* Risk factors — 1/3 */}
        <Panel
          label="risk factors"
          title="Fleet Risk Indicators"
          subtitle="Traffic-light per risk category across all 847 accounts"
        >
          <div className="space-y-4">
            {RISK_FACTORS.map((rf) => (
              <div key={rf.label} className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-white">{rf.label}</span>
                  <TrafficLight level={rf.level} />
                </div>
                <div className="text-[11px] text-phantom-ghost">{rf.description}</div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className={cn(
                    "font-semibold tabular-nums font-mono",
                    rf.level === "safe" ? "text-phantom-alive" : rf.level === "warning" ? "text-phantom-amber" : "text-phantom-red"
                  )}>
                    {rf.value}
                  </span>
                  <span className="text-phantom-ghost/60">{rf.threshold}</span>
                </div>
                <div className="h-1 bg-phantom-border/30 rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      rf.level === "safe" ? "bg-phantom-alive/60 w-[28%]" :
                      rf.level === "warning" ? "bg-phantom-amber/70 w-[62%]" :
                      "bg-phantom-red/70 w-[88%]"
                    )}
                  />
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {/* Shadowban event history with timeline */}
      <Panel
        label="event history"
        title="Recent Shadowban Events"
        subtitle="Detected events with full remediation timeline"
      >
        <div className="space-y-6">
          {SHADOWBAN_HISTORY.map((event) => (
            <div
              key={event.id}
              className="rounded-lg border border-phantom-border bg-phantom-bg p-5 space-y-4"
            >
              <div className="flex items-start justify-between flex-wrap gap-2">
                <div>
                  <div className="font-mono text-sm text-phantom-accent font-bold">{event.account}</div>
                  <div className="text-[11px] text-phantom-ghost mt-0.5">Detected: {event.detectedAt}</div>
                </div>
                {event.resolved ? (
                  <span className="px-2.5 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-[10px] font-semibold flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> Resolved
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-full bg-phantom-red/10 border border-phantom-red/20 text-phantom-red text-[10px] font-semibold flex items-center gap-1">
                    <XCircle className="w-3 h-3" /> Active
                  </span>
                )}
              </div>

              <div className="space-y-2.5 pl-1">
                {event.timeline.map((step, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <div className="flex flex-col items-center gap-0">
                      <TimelineEventDot type={step.type} />
                      {i < event.timeline.length - 1 && (
                        <div className="w-px h-5 bg-phantom-border/50 mt-0.5" />
                      )}
                    </div>
                    <div className="pb-1">
                      <span className="text-[10px] font-mono text-phantom-ghost/60 mr-2">{step.ts}</span>
                      <span className="text-xs text-phantom-ghost leading-relaxed">{step.event}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 pt-3 border-t border-phantom-border flex items-center gap-6 text-[10px] text-phantom-ghost flex-wrap">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-phantom-red" />Detected</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-phantom-amber" />Paused</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-phantom-accent" />Recovery action</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-phantom-alive" />Cleared</span>
        </div>
      </Panel>
    </div>
  );
}
