"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { DataTable, Column } from "@/components/data-table";
import { Globe, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── IP Pool ──────────────────────────────────────────────────────────────────

type ProxyIP = {
  id: string;
  ip: string;
  provider: string;
  region: string;
  location: string;
  account: string;
  sessionAge: string;
  status: "active" | "rotating" | "flagged" | "cooldown";
};

const IP_POOL: ProxyIP[] = [
  { id: "1",  ip: "203.44.x.x",   provider: "IPRoyal",   region: "US-CA", location: "Los Angeles, CA",    account: "@tatiana_xo44",    sessionAge: "1h 22m", status: "active" },
  { id: "2",  ip: "198.12.x.x",   provider: "IPRoyal",   region: "US-NY", location: "New York, NY",       account: "@melodie_life",    sessionAge: "2h 05m", status: "active" },
  { id: "3",  ip: "104.28.x.x",   provider: "IPRoyal",   region: "US-TX", location: "Houston, TX",        account: "@kira_glow22",     sessionAge: "0h 47m", status: "rotating" },
  { id: "4",  ip: "172.58.x.x",   provider: "IPRoyal",   region: "US-FL", location: "Miami, FL",          account: "@daisy_vibesxx",   sessionAge: "3h 11m", status: "active" },
  { id: "5",  ip: "45.86.x.x",    provider: "IPRoyal",   region: "US-IL", location: "Chicago, IL",        account: "@noelle_rune",     sessionAge: "1h 55m", status: "active" },
  { id: "6",  ip: "203.44.17.x",  provider: "IPRoyal",   region: "US-CA", location: "San Francisco, CA",  account: "—",               sessionAge: "—",      status: "flagged" },
  { id: "7",  ip: "162.33.x.x",   provider: "IPRoyal",   region: "US-WA", location: "Seattle, WA",        account: "@piper_aura",      sessionAge: "0h 33m", status: "active" },
  { id: "8",  ip: "23.105.x.x",   provider: "IPRoyal",   region: "US-GA", location: "Atlanta, GA",        account: "@leila_xox3",      sessionAge: "2h 48m", status: "active" },
  { id: "9",  ip: "185.93.x.x",   provider: "IPRoyal",   region: "US-AZ", location: "Phoenix, AZ",        account: "@vivienne_co",     sessionAge: "1h 04m", status: "cooldown" },
  { id: "10", ip: "64.120.x.x",   provider: "IPRoyal",   region: "US-CO", location: "Denver, CO",         account: "@talia_xoxo",      sessionAge: "3h 30m", status: "active" },
  { id: "11", ip: "107.152.x.x",  provider: "IPRoyal",   region: "US-NV", location: "Las Vegas, NV",      account: "@luna.sweetie",    sessionAge: "0h 18m", status: "active" },
  { id: "12", ip: "138.199.x.x",  provider: "IPRoyal",   region: "US-OR", location: "Portland, OR",       account: "@ivy_bellexx",     sessionAge: "2h 22m", status: "active" },
  { id: "13", ip: "167.88.x.x",   provider: "IPRoyal",   region: "US-MN", location: "Minneapolis, MN",    account: "@sienna_xobaby",   sessionAge: "1h 41m", status: "active" },
  { id: "14", ip: "45.142.x.x",   provider: "IPRoyal",   region: "US-OH", location: "Columbus, OH",       account: "@ava_herworld",    sessionAge: "4h 02m", status: "active" },
  { id: "15", ip: "195.12.x.x",   provider: "IPRoyal",   region: "US-PA", location: "Philadelphia, PA",   account: "@chloe_kissxo",    sessionAge: "0h 55m", status: "active" },
];

function StatusBadge({ status }: { status: ProxyIP["status"] }) {
  return (
    <span
      className={cn(
        "inline-flex px-2 py-0.5 rounded text-[9px] font-mono tracking-wider border",
        status === "active"   && "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/30",
        status === "rotating" && "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/30",
        status === "flagged"  && "bg-phantom-red/10 text-phantom-red border-phantom-red/30",
        status === "cooldown" && "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/30",
      )}
    >
      {status.toUpperCase()}
    </span>
  );
}

const ipColumns: Column<ProxyIP>[] = [
  {
    key: "ip",
    header: "IP Address",
    render: (r) => <span className="font-mono text-white text-xs">{r.ip}</span>,
  },
  {
    key: "provider",
    header: "Provider",
    render: (r) => <span className="text-xs text-phantom-ghost">{r.provider}</span>,
  },
  {
    key: "location",
    header: "Location",
    render: (r) => (
      <div>
        <div className="text-xs text-white">{r.location}</div>
        <div className="text-[10px] font-mono text-phantom-ghost">{r.region}</div>
      </div>
    ),
  },
  {
    key: "account",
    header: "Assigned Account",
    render: (r) => (
      <span className={cn("font-mono text-xs", r.account === "—" ? "text-phantom-ghost" : "text-phantom-accent")}>
        {r.account}
      </span>
    ),
  },
  {
    key: "sessionAge",
    header: "Session Age",
    align: "right",
    render: (r) => <span className="font-mono text-xs text-phantom-ghost tabular-nums">{r.sessionAge}</span>,
  },
  {
    key: "status",
    header: "Status",
    render: (r) => <StatusBadge status={r.status} />,
  },
];

// ─── Rotation History ─────────────────────────────────────────────────────────

type RotationEvent = {
  id: string;
  time: string;
  oldIp: string;
  newIp: string;
  reason: "scheduled" | "banned" | "error";
};

const ROTATION_HISTORY: RotationEvent[] = [
  { id: "re1",  time: "06:42 UTC", oldIp: "203.44.17.89", newIp: "203.44.21.14", reason: "banned" },
  { id: "re2",  time: "06:00 UTC", oldIp: "45.86.22.101", newIp: "45.86.29.203", reason: "scheduled" },
  { id: "re3",  time: "05:57 UTC", oldIp: "172.58.9.77",  newIp: "172.58.14.33", reason: "scheduled" },
  { id: "re4",  time: "05:30 UTC", oldIp: "104.28.7.19",  newIp: "104.28.31.88", reason: "scheduled" },
  { id: "re5",  time: "04:15 UTC", oldIp: "23.105.44.12", newIp: "23.105.50.99", reason: "scheduled" },
  { id: "re6",  time: "03:44 UTC", oldIp: "162.33.8.204", newIp: "162.33.17.11", reason: "error" },
  { id: "re7",  time: "03:00 UTC", oldIp: "198.12.77.33", newIp: "198.12.80.51", reason: "scheduled" },
  { id: "re8",  time: "02:30 UTC", oldIp: "64.120.3.18",  newIp: "64.120.9.202", reason: "scheduled" },
  { id: "re9",  time: "02:14 UTC", oldIp: "107.152.6.44", newIp: "107.152.11.7", reason: "banned" },
  { id: "re10", time: "01:45 UTC", oldIp: "138.199.2.88", newIp: "138.199.8.14", reason: "scheduled" },
  { id: "re11", time: "01:30 UTC", oldIp: "167.88.5.101", newIp: "167.88.13.77", reason: "scheduled" },
  { id: "re12", time: "01:00 UTC", oldIp: "185.93.11.66", newIp: "185.93.19.34", reason: "scheduled" },
  { id: "re13", time: "00:45 UTC", oldIp: "45.142.3.201", newIp: "45.142.9.88",  reason: "scheduled" },
  { id: "re14", time: "00:15 UTC", oldIp: "195.12.44.9",  newIp: "195.12.50.22", reason: "scheduled" },
  { id: "re15", time: "23:50 UTC", oldIp: "203.44.21.55", newIp: "203.44.22.17", reason: "scheduled" },
  { id: "re16", time: "23:30 UTC", oldIp: "172.58.16.8",  newIp: "172.58.20.44", reason: "scheduled" },
  { id: "re17", time: "23:00 UTC", oldIp: "104.28.41.77", newIp: "104.28.45.13", reason: "scheduled" },
  { id: "re18", time: "22:15 UTC", oldIp: "23.105.52.88", newIp: "23.105.58.30", reason: "error" },
  { id: "re19", time: "22:00 UTC", oldIp: "162.33.22.19", newIp: "162.33.28.55", reason: "scheduled" },
  { id: "re20", time: "21:42 UTC", oldIp: "198.12.88.14", newIp: "198.12.92.77", reason: "scheduled" },
];

function ReasonBadge({ reason }: { reason: RotationEvent["reason"] }) {
  return (
    <span
      className={cn(
        "inline-flex px-1.5 py-0.5 rounded text-[9px] font-mono border",
        reason === "scheduled" && "text-phantom-accent border-phantom-accent/30 bg-phantom-accent/10",
        reason === "banned"    && "text-phantom-red border-phantom-red/30 bg-phantom-red/10",
        reason === "error"     && "text-phantom-amber border-phantom-amber/30 bg-phantom-amber/10",
      )}
    >
      {reason}
    </span>
  );
}

const rotationColumns: Column<RotationEvent>[] = [
  {
    key: "time",
    header: "Time",
    render: (r) => <span className="font-mono text-xs text-phantom-ghost">{r.time}</span>,
  },
  {
    key: "oldIp",
    header: "Old IP",
    render: (r) => <span className="font-mono text-xs text-phantom-red/80">{r.oldIp}</span>,
  },
  {
    key: "newIp",
    header: "New IP",
    render: (r) => <span className="font-mono text-xs text-phantom-alive">{r.newIp}</span>,
  },
  {
    key: "reason",
    header: "Reason",
    render: (r) => <ReasonBadge reason={r.reason} />,
  },
];

// ─── Flagged IPs ──────────────────────────────────────────────────────────────

type FlaggedIP = {
  id: string;
  ip: string;
  platform: string;
  flagType: "rate_limit" | "ban" | "captcha";
  flaggedAt: string;
  cooldownRemaining: string;
};

const FLAGGED: FlaggedIP[] = [
  { id: "f1", ip: "203.44.17.89", platform: "Instagram", flagType: "rate_limit", flaggedAt: "02:14 UTC", cooldownRemaining: "3h 46m" },
  { id: "f2", ip: "107.152.6.44", platform: "TikTok",    flagType: "captcha",   flaggedAt: "02:14 UTC", cooldownRemaining: "1h 12m" },
  { id: "f3", ip: "162.33.8.204", platform: "Threads",   flagType: "rate_limit", flaggedAt: "03:44 UTC", cooldownRemaining: "2h 28m" },
];

// ─── Geographic distribution data ────────────────────────────────────────────

const GEO_DIST = [
  { state: "CA", count: 187, pct: 22 },
  { state: "NY", count: 134, pct: 16 },
  { state: "TX", count: 118, pct: 14 },
  { state: "FL", count: 102, pct: 12 },
  { state: "IL", count: 76,  pct: 9  },
  { state: "WA", count: 59,  pct: 7  },
  { state: "GA", count: 51,  pct: 6  },
  { state: "Other", count: 120, pct: 14 },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ProxyPage() {
  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Infrastructure · proxy health
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Globe className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Proxy <span className="phantom-accent-text">Health</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          IPRoyal Royal Residential Unlimited pool. Rotation orchestrated by ProxyOrchestrator agent.
          LogNormal session lengths, per-account IP isolation, automatic cooldown on flag detection.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Active IPs"
          value="847"
          delta={0.014}
          sub="15 in use now · 832 standby"
          accent
        />
        <KPICard
          label="Flagged today"
          value="3"
          delta={-0.25}
          sub="2 rate-limit · 1 captcha"
        />
        <KPICard
          label="Avg rotation"
          value="42 min"
          delta={-0.044}
          sub="LogNormal μ=42 σ=8"
        />
        <KPICard
          label="Monthly cost"
          value="$62 / $200"
          delta={0}
          sub="31% of budget · 18 days in"
        />
      </div>

      {/* IP Pool table */}
      <Panel
        label="live ip pool"
        title="Active IP Pool"
        subtitle="Showing 15 representative IPs from the 847-IP pool. Session ages are LogNormal-sampled. Flagged IPs auto-removed and replaced."
        actions={
          <button className="px-3 py-1.5 rounded-lg bg-phantom-panelHi border border-phantom-border text-xs hover:border-phantom-accent/50 hover:text-phantom-accent transition-colors">
            Rotate All
          </button>
        }
      >
        <DataTable columns={ipColumns} rows={IP_POOL} />
      </Panel>

      {/* Provider info + Geo distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Provider panel */}
        <Panel label="provider" title="IPRoyal Royal Residential Unlimited">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Endpoint",          value: "geo.iproyal.com:12321" },
                { label: "Protocol",          value: "HTTP / SOCKS5" },
                { label: "Auth",              value: "username:password" },
                { label: "Country targeting", value: "US only" },
                { label: "Bandwidth used",    value: "3.12 GB / ∞" },
                { label: "Success rate",      value: "98.7%" },
                { label: "Ban rate",          value: "0.35%" },
                { label: "Avg latency",       value: "142 ms" },
              ].map((item) => (
                <div key={item.label} className="p-3 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
                  <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">{item.label}</div>
                  <div className="font-mono text-xs text-white mt-1">{item.value}</div>
                </div>
              ))}
            </div>
            {/* Success vs ban rate bar */}
            <div className="mt-2 p-3 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Success rate this month</span>
                <span className="font-mono text-xs text-phantom-alive">98.7%</span>
              </div>
              <div className="w-full h-2 rounded-full bg-phantom-panelHi overflow-hidden flex">
                <div className="h-full bg-phantom-alive" style={{ width: "98.7%" }} />
                <div className="h-full bg-phantom-red flex-1" />
              </div>
              <div className="flex items-center justify-between mt-1">
                <span className="text-[10px] text-phantom-alive">Success 98.7%</span>
                <span className="text-[10px] text-phantom-red">Ban 0.35%</span>
              </div>
            </div>
          </div>
        </Panel>

        {/* Geographic distribution */}
        <Panel label="geo distribution" title="Proxy Distribution by State">
          <div className="space-y-3">
            {GEO_DIST.map((g) => (
              <div key={g.state} className="flex items-center gap-3">
                <span className="font-mono text-xs text-phantom-ghost w-10 flex-shrink-0">{g.state}</span>
                <div className="flex-1 h-5 bg-phantom-panelHi rounded overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded transition-all flex items-center px-2",
                      g.state === "Other"
                        ? "bg-phantom-ghost/20"
                        : "bg-phantom-accent/20 border-r border-phantom-accent/50"
                    )}
                    style={{ width: `${g.pct * 4}%` }}
                  >
                    <span className="text-[9px] font-mono text-phantom-accent whitespace-nowrap">
                      {g.count} IPs
                    </span>
                  </div>
                </div>
                <span className="font-mono text-xs text-phantom-ghost w-8 text-right tabular-nums">{g.pct}%</span>
              </div>
            ))}
          </div>
          <div className="mt-4 p-3 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50 text-xs text-phantom-ghost">
            Distribution reflects real-world US residential coverage.
            Top 5 states cover 73% of pool. No single state exceeds 25%.
          </div>
        </Panel>
      </div>

      {/* Rotation history + Flagged IPs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Rotation history */}
        <Panel label="rotation log" title="Rotation History" subtitle="Last 20 rotation events. Scheduled = timer-triggered, banned = platform signal, error = connection failure.">
          <DataTable columns={rotationColumns} rows={ROTATION_HISTORY} />
        </Panel>

        {/* Flagged IPs */}
        <Panel
          label="flagged ips"
          title="Currently Flagged"
          subtitle="IPs in cooldown or banned state. ProxyOrchestrator auto-swaps on detection."
        >
          {FLAGGED.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-phantom-ghost text-sm">
              No flagged IPs — pool is clean.
            </div>
          ) : (
            <div className="space-y-3">
              {FLAGGED.map((f) => (
                <div
                  key={f.id}
                  className="flex items-start gap-3 p-4 rounded-lg bg-phantom-red/5 border border-phantom-red/20"
                >
                  <AlertTriangle className="w-4 h-4 text-phantom-red flex-shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs text-white">{f.ip}</span>
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded border text-phantom-red border-phantom-red/30 bg-phantom-red/10">
                        {f.platform.toUpperCase()}
                      </span>
                      <span
                        className={cn(
                          "text-[9px] font-mono px-1.5 py-0.5 rounded border",
                          f.flagType === "rate_limit" && "text-phantom-amber border-phantom-amber/30 bg-phantom-amber/10",
                          f.flagType === "ban"        && "text-phantom-red border-phantom-red/30 bg-phantom-red/10",
                          f.flagType === "captcha"    && "text-phantom-magenta border-phantom-magenta/30 bg-phantom-magenta/10",
                        )}
                      >
                        {f.flagType.replace("_", " ").toUpperCase()}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-[10px] text-phantom-ghost font-mono">
                      <span>flagged: {f.flaggedAt}</span>
                      <span className="text-phantom-amber">cooldown: {f.cooldownRemaining}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {/* Cooldown notice */}
          <div className="mt-4 p-3 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50 text-xs text-phantom-ghost">
            Flagged IPs are automatically quarantined and replaced with backup IPs from the standby pool.
            Cooldown period is platform-specific: IG 6h · Threads 4h · TikTok 2h · Reddit 8h.
          </div>
        </Panel>
      </div>
    </div>
  );
}
