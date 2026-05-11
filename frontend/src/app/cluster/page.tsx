"use client";

import { useState } from "react";
import { ClusterHeatmap } from "@/components/cluster-heatmap";
import { Panel } from "@/components/panel";
import { cn } from "@/lib/utils";
import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  Activity,
  Cpu,
  Smartphone,
  MessageSquare,
  Hash,
  Timer,
  TrendingUp,
  Layers,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Severity = "warning" | "critical";
type Health = "healthy" | "warning" | "critical";

type ClusterAlert = {
  alert_id: string;
  severity: Severity;
  dimension: string;
  finding: string;
  affected_count: number;
  affected_pct: number;
  recommendation: string;
  detected_at_iso: string;
  resolved: boolean;
};

type CheckResult = {
  id: number;
  label: string;
  description: string;
  icon: React.ReactNode;
  passed: boolean;
  alert?: ClusterAlert;
};

// ---------------------------------------------------------------------------
// Static mock data (replace with live API calls via SWR/React Query)
// ---------------------------------------------------------------------------

const MOCK_ALERTS: ClusterAlert[] = [
  {
    alert_id: "a1b2c3d4e5f6",
    severity: "critical",
    dimension: "device_model_monoculture",
    finding:
      "Device model 'Samsung Galaxy S21' appears on 142/200 accounts (71.0%). Threshold: 40%.",
    affected_count: 142,
    affected_pct: 71.0,
    recommendation:
      "Reseed device profiles using a weighted distribution matching real-world Android market share data.",
    detected_at_iso: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    resolved: false,
  },
  {
    alert_id: "b2c3d4e5f6a1",
    severity: "warning",
    dimension: "emoji_monoculture",
    finding: "❤️ accounts for 620/900 reactions (68.9%). Threshold: 50%.",
    affected_count: 620,
    affected_pct: 68.9,
    recommendation:
      "Implement weighted random emoji selection with ❤️ capped at 30%.",
    detected_at_iso: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    resolved: false,
  },
  {
    alert_id: "c3d4e5f6a1b2",
    severity: "warning",
    dimension: "comment_diversity_index_low",
    finding:
      "Comment diversity index is 0.34 (210 unique / 620 total). Threshold: 0.60.",
    affected_count: 620,
    affected_pct: 100.0,
    recommendation:
      "Use generative variation (LLM paraphrase) or expand the pool to 3× the expected daily comment volume.",
    detected_at_iso: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    resolved: true,
  },
];

const MOCK_HEALTH: Health = "critical";
const MOCK_AUDITED = 200;
const MOCK_CRITICAL = 1;
const MOCK_WARNINGS = 2;
const MOCK_LAST_RUN = new Date(Date.now() - 4 * 60 * 1000).toISOString();

// ---------------------------------------------------------------------------
// Check card mapping
// ---------------------------------------------------------------------------

function buildCheckResults(alerts: ClusterAlert[]): CheckResult[] {
  const alertMap = Object.fromEntries(alerts.map((a) => [a.dimension, a]));

  const checks: Omit<CheckResult, "passed" | "alert">[] = [
    {
      id: 1,
      label: "React Rate Distribution",
      description: "CV > 0.30 across all accounts",
      icon: <TrendingUp className="w-4 h-4" />,
    },
    {
      id: 2,
      label: "Follow Timing",
      description: "Log-normal delays, not uniform",
      icon: <Timer className="w-4 h-4" />,
    },
    {
      id: 3,
      label: "Device Model Diversity",
      description: "No model > 40%; 5+ distinct models",
      icon: <Smartphone className="w-4 h-4" />,
    },
    {
      id: 4,
      label: "OS Version Distribution",
      description: "No version > 50% of fleet",
      icon: <Cpu className="w-4 h-4" />,
    },
    {
      id: 5,
      label: "Emoji Distribution",
      description: "❤️ < 50%; 4+ distinct emojis",
      icon: <Activity className="w-4 h-4" />,
    },
    {
      id: 6,
      label: "Comment Diversity",
      description: "No template > 5%; diversity index > 0.60",
      icon: <MessageSquare className="w-4 h-4" />,
    },
    {
      id: 7,
      label: "Post Timing Spread",
      description: "No single hour > 30% of daily posts",
      icon: <Clock className="w-4 h-4" />,
    },
    {
      id: 8,
      label: "Hashtag Monoculture",
      description: "No hashtag used by > 30% of accounts",
      icon: <Hash className="w-4 h-4" />,
    },
    {
      id: 9,
      label: "Account Age Spread",
      description: "Creation dates not suspiciously uniform",
      icon: <Layers className="w-4 h-4" />,
    },
    {
      id: 10,
      label: "Action Velocity Outliers",
      description: "No account at > 3σ above fleet mean",
      icon: <ShieldAlert className="w-4 h-4" />,
    },
  ];

  const dimensionsByCheck: Record<number, string[]> = {
    1: ["react_rate_cv"],
    2: ["follow_timing_distribution"],
    3: ["device_model_monoculture", "device_model_insufficient_diversity"],
    4: ["os_version_monoculture"],
    5: ["emoji_monoculture", "emoji_insufficient_diversity"],
    6: ["comment_monoculture", "comment_diversity_index_low"],
    7: ["post_timing_cluster"],
    8: ["hashtag_monoculture"],
    9: ["account_age_uniformity"],
    10: ["action_velocity_outliers"],
  };

  return checks.map((c) => {
    const matchedAlert = (dimensionsByCheck[c.id] || [])
      .map((dim) => alertMap[dim])
      .find(Boolean);

    return {
      ...c,
      passed: !matchedAlert || matchedAlert.resolved,
      alert: matchedAlert,
    };
  });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const HEALTH_CONFIG: Record<
  Health,
  { label: string; color: string; bg: string; icon: React.ReactNode }
> = {
  healthy: {
    label: "HEALTHY",
    color: "text-phantom-alive",
    bg: "border-phantom-alive/30 bg-phantom-alive/5",
    icon: <ShieldCheck className="w-5 h-5" />,
  },
  warning: {
    label: "WARNING",
    color: "text-phantom-amber",
    bg: "border-phantom-amber/30 bg-phantom-amber/5",
    icon: <AlertTriangle className="w-5 h-5" />,
  },
  critical: {
    label: "CRITICAL",
    color: "text-phantom-red",
    bg: "border-phantom-red/30 bg-phantom-red/5",
    icon: <ShieldAlert className="w-5 h-5" />,
  },
};

const SEVERITY_COLORS: Record<Severity, string> = {
  warning: "border-phantom-amber/30 bg-phantom-amber/5",
  critical: "border-phantom-red/30 bg-phantom-red/5",
};

const SEVERITY_DOT: Record<Severity, string> = {
  warning: "bg-phantom-amber animate-phantom-pulse",
  critical: "bg-phantom-red animate-phantom-pulse",
};

function HealthBadge({ health }: { health: Health }) {
  const cfg = HEALTH_CONFIG[health];
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 px-4 py-2 rounded-lg border font-mono text-sm font-bold tracking-widest",
        cfg.bg,
        cfg.color,
      )}
    >
      {cfg.icon}
      {cfg.label}
    </div>
  );
}

function CheckCard({ check }: { check: CheckResult }) {
  const hasActiveAlert = check.alert && !check.alert.resolved;
  const severityBg = hasActiveAlert
    ? check.alert!.severity === "critical"
      ? "border-phantom-red/20 bg-phantom-red/5"
      : "border-phantom-amber/20 bg-phantom-amber/5"
    : "border-phantom-border bg-phantom-panelHi";

  return (
    <div className={cn("rounded-lg border p-4 transition-all", severityBg)}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "text-phantom-ghost",
              hasActiveAlert &&
                (check.alert!.severity === "critical"
                  ? "text-phantom-red"
                  : "text-phantom-amber"),
            )}
          >
            {check.icon}
          </span>
          <div>
            <div className="text-sm font-semibold text-white leading-tight">
              {check.label}
            </div>
            <div className="text-[11px] text-phantom-ghost mt-0.5">
              {check.description}
            </div>
          </div>
        </div>
        <div className="shrink-0">
          {check.passed ? (
            <CheckCircle2
              className="w-5 h-5 text-phantom-alive"
              strokeWidth={2}
            />
          ) : (
            <XCircle
              className={cn(
                "w-5 h-5",
                check.alert?.severity === "critical"
                  ? "text-phantom-red"
                  : "text-phantom-amber",
              )}
              strokeWidth={2}
            />
          )}
        </div>
      </div>
      {hasActiveAlert && (
        <div className="mt-3 pt-3 border-t border-white/5 space-y-1">
          <div className="text-[11px] text-phantom-ghost leading-relaxed">
            {check.alert!.finding}
          </div>
          <div className="text-[10px] text-phantom-ghost">
            affected ·{" "}
            <span className="text-white font-mono">
              {check.alert!.affected_count.toLocaleString()} (
              {check.alert!.affected_pct.toFixed(1)}%)
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert }: { alert: ClusterAlert }) {
  const isResolved = alert.resolved;

  return (
    <div
      className={cn(
        "p-4 rounded-lg border flex items-start gap-4 transition-all",
        isResolved
          ? "border-phantom-border bg-phantom-panel/50 opacity-60"
          : SEVERITY_COLORS[alert.severity],
      )}
    >
      <span
        className={cn(
          "phantom-dot mt-1.5 shrink-0",
          isResolved ? "bg-phantom-alive/60" : SEVERITY_DOT[alert.severity],
        )}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-mono text-[11px] uppercase tracking-wider text-phantom-accent">
            {alert.dimension}
          </span>
          <span className="text-[10px] text-phantom-ghost">·</span>
          <span
            className={cn(
              "text-[10px] font-semibold uppercase",
              alert.severity === "critical"
                ? "text-phantom-red"
                : "text-phantom-amber",
            )}
          >
            {alert.severity}
          </span>
          <span className="text-[10px] text-phantom-ghost">·</span>
          <span className="text-[10px] text-phantom-ghost">
            {new Date(alert.detected_at_iso).toLocaleTimeString()}
          </span>
          {isResolved && (
            <span className="text-[10px] text-phantom-alive flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" strokeWidth={2.5} />
              RESOLVED
            </span>
          )}
        </div>
        <div className="text-sm text-white mt-1 leading-snug">{alert.finding}</div>
        <div className="mt-2 text-[11px] text-phantom-ghost">
          <span className="text-phantom-accent font-mono">fix · </span>
          {alert.recommendation}
        </div>
        <div className="mt-2 text-[10px] text-phantom-ghost">
          affected ·{" "}
          <span className="text-white font-mono">
            {alert.affected_count.toLocaleString()} ({alert.affected_pct.toFixed(1)}%)
          </span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ClusterPage() {
  const [isRunning, setIsRunning] = useState(false);
  const [lastRun] = useState(MOCK_LAST_RUN);
  const [health] = useState<Health>(MOCK_HEALTH);
  const [alerts] = useState<ClusterAlert[]>(MOCK_ALERTS);
  const [audited] = useState(MOCK_AUDITED);
  const [criticalCount] = useState(MOCK_CRITICAL);
  const [warningCount] = useState(MOCK_WARNINGS);

  const checks = buildCheckResults(alerts);
  const passedCount = checks.filter((c) => c.passed).length;
  const activeAlerts = alerts.filter((a) => !a.resolved);

  function handleRunAudit() {
    setIsRunning(true);
    setTimeout(() => setIsRunning(false), 2000);
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Fleet intelligence · cluster health
        </div>
        <div className="flex items-start justify-between gap-4 mt-2 flex-wrap">
          <div>
            <h1 className="font-display text-4xl font-bold tracking-tight flex items-center gap-3">
              <Activity className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
              Cluster{" "}
              <span className="phantom-accent-text">Monitor</span>
            </h1>
            <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
              Phantom Fleet&apos;s moat. Runs the 20K-account cluster analysis
              continuously — distribution anomalies, monocultures, and
              cross-field contradictions caught before Meta does.
            </p>
          </div>
          <div className="flex items-center gap-3 pt-1 shrink-0">
            <HealthBadge health={health} />
            <button
              onClick={handleRunAudit}
              disabled={isRunning}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-all",
                "border-phantom-accent/40 text-phantom-accent hover:bg-phantom-accent/10",
                isRunning && "opacity-50 cursor-not-allowed",
              )}
            >
              <RefreshCw
                className={cn("w-4 h-4", isRunning && "animate-spin")}
                strokeWidth={2}
              />
              {isRunning ? "Running…" : "Run Audit Now"}
            </button>
          </div>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
            Accounts audited
          </div>
          <div className="phantom-metric-lg mt-2">{audited.toLocaleString()}</div>
          <div className="text-xs text-phantom-ghost">last run</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
            Checks passed
          </div>
          <div className="phantom-metric-lg mt-2 text-phantom-alive">
            {passedCount}/10
          </div>
          <div className="text-xs text-phantom-ghost">dimensions</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
            Critical
          </div>
          <div
            className={cn(
              "phantom-metric-lg mt-2",
              criticalCount > 0 ? "text-phantom-red" : "text-phantom-alive",
            )}
          >
            {criticalCount}
          </div>
          <div className="text-xs text-phantom-ghost">active alerts</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
            Warnings
          </div>
          <div
            className={cn(
              "phantom-metric-lg mt-2",
              warningCount > 0 ? "text-phantom-amber" : "text-phantom-alive",
            )}
          >
            {warningCount}
          </div>
          <div className="text-xs text-phantom-ghost">active alerts</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
            Last audit
          </div>
          <div className="phantom-metric-lg mt-2 text-phantom-accent text-2xl">
            {lastRun
              ? new Date(lastRun).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "—"}
          </div>
          <div className="text-xs text-phantom-ghost">auto every 5m</div>
        </div>
      </div>

      {/* 10-check grid */}
      <Panel label="fingerprint checks" title="10-dimension fleet audit">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {checks.map((check) => (
            <CheckCard key={check.id} check={check} />
          ))}
        </div>
      </Panel>

      {/* Active alerts */}
      {activeAlerts.length > 0 && (
        <Panel
          label="active alerts"
          title={`${activeAlerts.length} finding${activeAlerts.length !== 1 ? "s" : ""} requiring attention`}
        >
          <div className="space-y-3">
            {activeAlerts.map((a) => (
              <AlertRow key={a.alert_id} alert={a} />
            ))}
          </div>
        </Panel>
      )}

      {/* Heatmap (existing component) */}
      <Panel label="distribution heatmap" title="Cross-dimension fingerprint grid">
        <ClusterHeatmap />
      </Panel>

      {/* Full alert history */}
      <Panel label="alert history" title="All alerts · last 7 days">
        {alerts.length === 0 ? (
          <div className="py-8 text-center text-phantom-ghost text-sm">
            No alerts in the last 7 days.
          </div>
        ) : (
          <div className="space-y-3">
            {alerts.map((a) => (
              <AlertRow key={a.alert_id} alert={a} />
            ))}
          </div>
        )}
      </Panel>

      {/* Footer note */}
      <div className="text-[11px] text-phantom-ghost flex items-center gap-2">
        <Clock className="w-3 h-3" strokeWidth={2} />
        Dashboard auto-refreshes every 5 minutes. Resolve alerts via
        POST /api/cluster/alerts/&#123;id&#125;/resolve.
      </div>
    </div>
  );
}
