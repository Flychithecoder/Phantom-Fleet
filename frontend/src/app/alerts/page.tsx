import { Panel } from "@/components/panel";
import { StatusBadge } from "@/components/status-badge";
import { ShieldAlert, Check } from "lucide-react";
import { cn } from "@/lib/utils";

type Alert = {
  id: string;
  severity: "low" | "medium" | "high" | "critical" | "resolved";
  dimension: string;
  description: string;
  affectedCount: number;
  action: string;
  raisedAt: string;
  resolvedAt?: string;
};

const ALERTS: Alert[] = [
  { id: "1", severity: "high", dimension: "proxy_ip_reputation", description: "IPRoyal pool IP 142.182.x.x flagged by IPQualityScore · fraud_score=81", affectedCount: 2, action: "auto-rotated", raisedAt: "4m ago" },
  { id: "2", severity: "medium", dimension: "locale_tz_contradiction", description: "6 accounts detected with en-GB locale on America/New_York timezone · AUTO-FIXED", affectedCount: 6, action: "locale updated to en-US", raisedAt: "1h ago", resolvedAt: "58m ago" },
  { id: "3", severity: "resolved", dimension: "action_timing", description: "Hourly action distribution uniformity (cv=0.18) flagged · dispersed across diurnal curve", affectedCount: 219, action: "timing redistributed", raisedAt: "3h ago", resolvedAt: "2h ago" },
  { id: "4", severity: "low", dimension: "content_pool_diversity", description: "Melodie content pool <50 items · recommend Content Vault refill", affectedCount: 122, action: "monitor", raisedAt: "5h ago" },
  { id: "5", severity: "resolved", dimension: "clone_crash", description: "com.instagram.andrvws crashed on RF8N11BB1MN · Recovery Agent reauth'd", affectedCount: 1, action: "auto-recovered", raisedAt: "8h ago", resolvedAt: "8h ago" },
];

const SEVERITY_COLORS: Record<Alert["severity"], string> = {
  low: "border-phantom-ghost/30 bg-phantom-panelHi",
  medium: "border-phantom-amber/30 bg-phantom-amber/5",
  high: "border-phantom-accent/30 bg-phantom-accent/5",
  critical: "border-phantom-red/30 bg-phantom-red/5",
  resolved: "border-phantom-border bg-phantom-panel/50 opacity-60",
};

const SEVERITY_DOT: Record<Alert["severity"], string> = {
  low: "bg-phantom-ghost",
  medium: "phantom-dot-warning",
  high: "phantom-dot-accent animate-phantom-pulse",
  critical: "phantom-dot-critical animate-phantom-pulse",
  resolved: "bg-phantom-alive/60",
};

export default function AlertsPage() {
  const active = ALERTS.filter((a) => a.severity !== "resolved");
  const resolved = ALERTS.filter((a) => a.severity === "resolved");

  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Fleet intelligence · alerts
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <ShieldAlert className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <span className="phantom-accent-text">Alerts</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Fingerprint Monitor Agent and Proxy Orchestrator raise alerts in real time.
          Auto-fix actions are applied before the alert even reaches you — this feed
          shows everything that happened, whether or not human action was required.
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">Active alerts</div>
          <div className="phantom-metric-lg mt-2">{active.length}</div>
          <div className="text-xs text-phantom-ghost">last 24h</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">Auto-resolved</div>
          <div className="phantom-metric-lg mt-2 text-phantom-alive">{resolved.length}</div>
          <div className="text-xs text-phantom-ghost">no human needed</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">Critical</div>
          <div className="phantom-metric-lg mt-2">0</div>
          <div className="text-xs text-phantom-ghost">last 30d</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">MTTR</div>
          <div className="phantom-metric-lg mt-2 text-phantom-accent">47s</div>
          <div className="text-xs text-phantom-ghost">auto-recovery</div>
        </div>
      </div>

      <Panel label="alert timeline" title="Live + recently resolved">
        <div className="space-y-3">
          {ALERTS.map((a) => (
            <div
              key={a.id}
              className={cn(
                "p-4 rounded-lg border flex items-start gap-4 transition-all",
                SEVERITY_COLORS[a.severity],
              )}
            >
              <span className={cn("phantom-dot mt-1.5 shrink-0", SEVERITY_DOT[a.severity])} />
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-phantom-accent">
                    {a.dimension}
                  </span>
                  <span className="text-[10px] text-phantom-ghost">·</span>
                  <span className="text-[10px] text-phantom-ghost">{a.raisedAt}</span>
                  {a.resolvedAt && (
                    <>
                      <span className="text-[10px] text-phantom-ghost">· resolved</span>
                      <span className="text-[10px] text-phantom-alive">{a.resolvedAt}</span>
                    </>
                  )}
                </div>
                <div className="text-sm text-white mt-1">{a.description}</div>
                <div className="flex items-center gap-3 mt-2 text-[11px]">
                  <span className="text-phantom-ghost">affected · <span className="text-white font-mono">{a.affectedCount}</span></span>
                  <span className="text-phantom-ghost">action · <span className="text-phantom-accent font-mono">{a.action}</span></span>
                  {a.severity === "resolved" && (
                    <span className="text-phantom-alive flex items-center gap-1 font-mono text-[10px]">
                      <Check className="w-3 h-3" strokeWidth={2.5} />
                      AUTO-HEALED
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
