"use client";

import { useState, useEffect } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Sparkline } from "@/components/sparkline";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
} from "recharts";
import { LineChart as LineChartIcon, Download, Calendar } from "lucide-react";
import { cn, fmtRelative } from "@/lib/utils";

// ─── Static mock data ────────────────────────────────────────────────────────

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const ACTION_TREND = DAYS.map((day, i) => ({
  day,
  follows: 580 + Math.round(Math.sin(i * 0.9) * 80 + i * 12),
  storyViews: 1200 + Math.round(Math.cos(i * 0.7) * 150 + i * 20),
  likes: 320 + Math.round(Math.sin(i * 1.2) * 60 + i * 8),
  dms: 90 + Math.round(Math.cos(i * 0.8) * 20 + i * 4),
}));

const PLATFORM_DISTRIBUTION = [
  { name: "Instagram", value: 97, color: "#E1306C" },
  { name: "Threads", value: 97, color: "#ffffff" },
  { name: "Reddit", value: 25, color: "#FF4500" },
];

const PHONE_HEALTH = [
  { serial: "RF8N81XYX4J", accounts: 12, label: "Phone 1" },
  { serial: "RF8N90FZ0LV", accounts: 11, label: "Phone 2" },
  { serial: "RF8N71RBF2H", accounts: 12, label: "Phone 3" },
  { serial: "RF8N50EM1WK", accounts: 12, label: "Phone 4" },
  { serial: "RF8N11BB1MN", accounts: 11, label: "Phone 5" },
  { serial: "RF8N22CC2OP", accounts: 12, label: "Phone 6" },
  { serial: "RF8N33DD3QR", accounts: 11, label: "Phone 7" },
  { serial: "RF8N44EE4ST", accounts: 12, label: "Phone 8" },
  { serial: "RF8N55FF5UV", accounts: 12, label: "Phone 9" },
  { serial: "RF8N66GG6WX", accounts: 11, label: "Phone 10" },
];

type ActionLog = {
  id: string;
  account: string;
  platform: string;
  action: string;
  status: "success" | "failed" | "throttled";
  ts: Date;
};

function generateActionLogs(): ActionLog[] {
  const platforms = ["instagram", "threads", "reddit"];
  const actions = ["follow", "story_view", "like", "dm_sent", "profile_visit", "unfollow"];
  const accounts = [
    "tatiannalifee", "tatianamusee", "tatianazenn",
    "melodieeeprincesss", "melodieeedream", "cutie.melodieee",
    "hackerhoneytatii", "softiemelodieee",
  ];
  const statuses: ActionLog["status"][] = ["success", "success", "success", "success", "failed", "throttled"];
  return Array.from({ length: 100 }, (_, i) => ({
    id: String(i),
    account: accounts[i % accounts.length],
    platform: platforms[i % platforms.length],
    action: actions[i % actions.length],
    status: statuses[i % statuses.length],
    ts: new Date(Date.now() - i * 47_000 - Math.random() * 30_000),
  }));
}

const ACTION_LOGS = generateActionLogs();

const DATE_RANGES = ["Last 24h", "Last 7d", "Last 30d", "Last 90d"] as const;
type DateRange = (typeof DATE_RANGES)[number];

// ─── Tooltip styles ──────────────────────────────────────────────────────────

const tooltipStyle = {
  contentStyle: {
    background: "hsl(240 6% 8%)",
    border: "1px solid hsl(240 6% 18%)",
    borderRadius: "0.5rem",
    fontSize: "12px",
  },
  labelStyle: { color: "hsl(240 5% 64.9%)" },
};

// ─── Page ────────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [dateRange, setDateRange] = useState<DateRange>("Last 7d");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  function exportCSV() {
    const rows = [
      ["Timestamp", "Account", "Platform", "Action", "Status"],
      ...ACTION_LOGS.map((l) => [
        l.ts.toISOString(),
        l.account,
        l.platform,
        l.action,
        l.status,
      ]),
    ];
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `phantom-fleet-actions-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Performance data
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <LineChartIcon className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            <span className="phantom-accent-text">Analytics</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            Action throughput, platform distribution, phone health, and the complete
            action firehose — all in one view.
          </p>
        </div>
        {/* Date range + export */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 bg-phantom-panelHi border border-phantom-border rounded-lg p-1">
            {DATE_RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setDateRange(r)}
                className={cn(
                  "px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150",
                  dateRange === r
                    ? "bg-phantom-accent text-phantom-bg shadow-[0_0_12px_hsl(162_100%_54%/0.3)]"
                    : "text-phantom-ghost hover:text-white"
                )}
              >
                {r}
              </button>
            ))}
          </div>
          <button
            onClick={exportCSV}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-phantom-panelHi border border-phantom-border text-phantom-ghost hover:text-white hover:border-phantom-accent/40 text-xs font-medium transition-all"
          >
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <KPICard label="Active accounts" value="219" delta={0.023} accent />
        <KPICard label="Follows today" value="4,280" delta={0.112} />
        <KPICard label="Story views today" value="8,840" delta={0.064} />
        <KPICard label="DMs sent" value="384" delta={0.031} />
        <KPICard label="Success rate" value="97.8%" delta={0.002} />
      </div>

      {/* Action trend line chart */}
      <Panel
        label="action throughput · 7-day"
        title="Account actions over last 7 days"
        subtitle="Follows, story views, likes, and DMs — all platforms combined."
      >
        {mounted ? (
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={ACTION_TREND} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid stroke="hsl(240 6% 18%)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="day"
                  stroke="hsl(240 5% 64.9%)"
                  fontSize={10}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="hsl(240 5% 64.9%)"
                  fontSize={10}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip {...tooltipStyle} />
                <Legend
                  iconType="circle"
                  iconSize={8}
                  wrapperStyle={{ fontSize: "11px", paddingTop: "12px" }}
                />
                <Line
                  type="monotone"
                  dataKey="follows"
                  stroke="hsl(162 100% 54%)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="storyViews"
                  stroke="hsl(292 91% 68%)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="likes"
                  stroke="hsl(38 92% 58%)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="dms"
                  stroke="hsl(0 91% 65%)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="phantom-skeleton h-[300px] rounded-lg" />
        )}
      </Panel>

      {/* Platform distribution + Phone fleet health */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Platform donut */}
        <Panel
          label="accounts by platform"
          title="Platform distribution"
          subtitle="Total configured accounts per platform."
        >
          {mounted ? (
            <div className="flex items-center gap-8">
              <div className="h-[220px] w-[220px] shrink-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={PLATFORM_DISTRIBUTION}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={95}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {PLATFORM_DISTRIBUTION.map((entry, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={entry.color}
                          stroke="transparent"
                          style={{ filter: `drop-shadow(0 0 6px ${entry.color}60)` }}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={tooltipStyle.contentStyle}
                      formatter={(v) => [`${v} accounts`, ""]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex-1 space-y-3">
                {PLATFORM_DISTRIBUTION.map((p) => (
                  <div key={p.name} className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ background: p.color, boxShadow: `0 0 6px ${p.color}80` }}
                      />
                      <span className="text-sm text-phantom-ghost">{p.name}</span>
                    </div>
                    <div className="text-sm font-mono tabular-nums font-semibold">{p.value}</div>
                  </div>
                ))}
                <div className="pt-3 border-t border-phantom-border flex items-center justify-between">
                  <span className="text-xs text-phantom-ghost">Total</span>
                  <span className="text-sm font-mono tabular-nums font-bold text-phantom-accent">
                    {PLATFORM_DISTRIBUTION.reduce((s, p) => s + p.value, 0)}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="phantom-skeleton h-[220px] rounded-lg" />
          )}
        </Panel>

        {/* Phone fleet health bar chart */}
        <Panel
          label="accounts per phone"
          title="Phone fleet health"
          subtitle="Active accounts currently on each device."
        >
          {mounted ? (
            <div className="h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={PHONE_HEALTH}
                  margin={{ top: 4, right: 4, left: -30, bottom: 0 }}
                  barSize={18}
                >
                  <CartesianGrid stroke="hsl(240 6% 18%)" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="label"
                    stroke="hsl(240 5% 64.9%)"
                    fontSize={9}
                    tickLine={false}
                    axisLine={false}
                    interval={0}
                  />
                  <YAxis
                    stroke="hsl(240 5% 64.9%)"
                    fontSize={9}
                    tickLine={false}
                    axisLine={false}
                    domain={[0, 15]}
                  />
                  <Tooltip
                    {...tooltipStyle}
                    formatter={(v) => [`${v} accounts`, "Accounts"]}
                    labelFormatter={(l) => `Phone: ${l}`}
                  />
                  <Bar
                    dataKey="accounts"
                    fill="hsl(162 100% 54%)"
                    radius={[3, 3, 0, 0]}
                    style={{ filter: "drop-shadow(0 0 4px hsl(162 100% 54% / 0.4))" }}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="phantom-skeleton h-[220px] rounded-lg" />
          )}
        </Panel>
      </div>

      {/* Action log table */}
      <Panel
        label="last 100 actions"
        title="Action firehose"
        subtitle="Most recent actions across all accounts and platforms."
        actions={
          <div className="flex items-center gap-1.5 text-[10px] text-phantom-ghost">
            <Calendar className="w-3 h-3" />
            <span>{dateRange}</span>
          </div>
        }
      >
        <div className="overflow-x-auto -mx-2 max-h-[480px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-phantom-panel z-10">
              <tr className="border-b border-phantom-border">
                {["Account", "Platform", "Action", "Status", "Time"].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ACTION_LOGS.map((log) => (
                <tr
                  key={log.id}
                  className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors"
                >
                  <td className="px-3 py-2.5 font-mono text-xs text-white">@{log.account}</td>
                  <td className="px-3 py-2.5">
                    <span className="text-xs capitalize text-phantom-ghost">{log.platform}</span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="font-mono text-xs text-phantom-accent">{log.action}</span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className={cn(
                        "text-[9px] font-mono tracking-wider px-1.5 py-0.5 rounded border",
                        log.status === "success"
                          ? "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/25"
                          : log.status === "failed"
                          ? "bg-phantom-red/10 text-phantom-red border-phantom-red/25"
                          : "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/25"
                      )}
                    >
                      {log.status.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[10px] text-phantom-ghost tabular-nums">
                    {fmtRelative(log.ts)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
