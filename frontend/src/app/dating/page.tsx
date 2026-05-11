"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Heart } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type PlatformHealth = "healthy" | "degraded" | "offline";

const PLATFORM_STATS = [
  { id: "tinder",  label: "Tinder",  accounts: 38, matchRate7d: 34, msgToday: 412, verifyPending: 3, health: "healthy"  as PlatformHealth },
  { id: "bumble",  label: "Bumble",  accounts: 31, matchRate7d: 28, msgToday: 287, verifyPending: 4, health: "healthy"  as PlatformHealth },
  { id: "hinge",   label: "Hinge",   accounts: 44, matchRate7d: 41, msgToday: 523, verifyPending: 2, health: "healthy"  as PlatformHealth },
  { id: "grindr",  label: "Grindr",  accounts: 35, matchRate7d: 67, msgToday: 698, verifyPending: 3, health: "degraded" as PlatformHealth },
];

const HEALTH_STYLES: Record<PlatformHealth, { bg: string; text: string; border: string; label: string }> = {
  healthy:  { bg: "bg-phantom-alive/10",   text: "text-phantom-alive",   border: "border-phantom-alive/20",   label: "HEALTHY"  },
  degraded: { bg: "bg-phantom-amber/10",   text: "text-phantom-amber",   border: "border-phantom-amber/20",   label: "DEGRADED" },
  offline:  { bg: "bg-phantom-red/10",     text: "text-phantom-red",     border: "border-phantom-red/20",     label: "OFFLINE"  },
};

const PLATFORM_ICONS: Record<string, string> = {
  tinder: "🔥",
  bumble: "🐝",
  hinge:  "💛",
  grindr: "🟡",
};

const RECENT_MATCHES = [
  { id: "1",  platform: "Hinge",   persona: "Sofia_H",       name: "Mackenzie R.",  time: "2m ago",   score: 92 },
  { id: "2",  platform: "Tinder",  persona: "Ariana_T",      name: "Jake L.",        time: "5m ago",   score: 87 },
  { id: "3",  platform: "Grindr",  persona: "Alex_G",        name: "Tyler M.",       time: "7m ago",   score: 95 },
  { id: "4",  platform: "Bumble",  persona: "Chloe_B",       name: "Noah W.",        time: "11m ago",  score: 74 },
  { id: "5",  platform: "Tinder",  persona: "Ariana_T",      name: "Ethan K.",       time: "14m ago",  score: 81 },
  { id: "6",  platform: "Hinge",   persona: "Madison_H",     name: "Liam S.",        time: "18m ago",  score: 68 },
  { id: "7",  platform: "Grindr",  persona: "Jordan_G",      name: "Cameron P.",     time: "22m ago",  score: 90 },
  { id: "8",  platform: "Tinder",  persona: "Sofia_H",       name: "Hunter B.",      time: "25m ago",  score: 77 },
  { id: "9",  platform: "Bumble",  persona: "Chloe_B",       name: "Mason T.",       time: "29m ago",  score: 83 },
  { id: "10", platform: "Hinge",   persona: "Madison_H",     name: "Aiden F.",       time: "34m ago",  score: 71 },
];

const FUNNEL = [
  { label: "Matches",           value: 847,  pct: 100, color: "bg-phantom-accent" },
  { label: "Conversations",     value: 412,  pct: 49,  color: "bg-phantom-alive"  },
  { label: "Link Shared",       value: 198,  pct: 23,  color: "bg-phantom-amber"  },
  { label: "Converted",         value: 89,   pct: 11,  color: "bg-phantom-magenta"},
];

const PLATFORM_COLORS: Record<string, string> = {
  Tinder: "bg-phantom-red/80",
  Bumble:  "bg-phantom-amber/80",
  Hinge:   "bg-phantom-magenta/80",
  Grindr:  "bg-yellow-500/80",
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DatingCommandPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Dating · command center
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Heart className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Dating <span className="phantom-accent-text">Command</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Cross-platform dating automation — Tinder, Bumble, Hinge, and Grindr managed from a single
          command center. Monitor match rates, verification queues, and conversion funnels.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Active Profiles"    value="148"    sub="across 4 platforms"      accent />
        <KPICard label="Matches Today"      value="47"     delta={0.183}                        />
        <KPICard label="Verification Queue" value="12"     sub="awaiting SIM"                   />
        <KPICard label="Conversion Rate"    value="34.2%"  delta={0.054}                        />
      </div>

      {/* Platform table + Recent matches */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Platform status table */}
        <div className="lg:col-span-2">
          <Panel label="platforms" title="Platform Status">
            <div className="overflow-x-auto -mx-2">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-phantom-border">
                    {["Platform", "Accounts", "Match Rate 7d", "Msgs Today", "Verify Queue", "Health"].map((h) => (
                      <th key={h} className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {PLATFORM_STATS.map((row) => {
                    const hs = HEALTH_STYLES[row.health];
                    return (
                      <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                        <td className="px-3 py-3 font-medium">
                          {PLATFORM_ICONS[row.id]} {row.label}
                        </td>
                        <td className="px-3 py-3 tabular-nums text-phantom-ghost">{row.accounts}</td>
                        <td className="px-3 py-3 tabular-nums phantom-accent-text font-semibold">{row.matchRate7d}%</td>
                        <td className="px-3 py-3 tabular-nums">{row.msgToday.toLocaleString()}</td>
                        <td className="px-3 py-3 tabular-nums">
                          <span className={cn(
                            "px-2 py-0.5 rounded-full text-[10px] font-bold border",
                            row.verifyPending > 3 ? "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/20" : "bg-phantom-border/30 text-phantom-ghost border-phantom-border"
                          )}>
                            {row.verifyPending}
                          </span>
                        </td>
                        <td className="px-3 py-3">
                          <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", hs.bg, hs.text, hs.border)}>
                            {hs.label}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        {/* Recent Matches Feed */}
        <div>
          <Panel label="live" title="Recent Matches">
            <div className="space-y-1">
              {RECENT_MATCHES.map((m) => (
                <div key={m.id} className="flex items-center gap-2 py-2 border-b border-phantom-border/30 last:border-0">
                  <span className={cn("w-2 h-2 rounded-full flex-shrink-0", PLATFORM_COLORS[m.platform])} />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium truncate">{m.name}</div>
                    <div className="text-[11px] text-phantom-ghost truncate">{m.persona} · {m.platform}</div>
                  </div>
                  <div className="flex flex-col items-end gap-0.5">
                    <span className={cn(
                      "text-[10px] font-bold tabular-nums",
                      m.score >= 90 ? "text-phantom-alive" : m.score >= 75 ? "phantom-accent-text" : "text-phantom-amber"
                    )}>
                      {m.score}
                    </span>
                    <span className="text-[10px] text-phantom-ghost">{m.time}</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>

      {/* Conversion Funnel */}
      <Panel label="conversion" title="Match → Conversion Funnel" subtitle="Fleet-wide funnel across all 148 active profiles today">
        <div className="space-y-4">
          {FUNNEL.map((step, i) => (
            <div key={step.label} className="space-y-1.5">
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-phantom-ghost font-medium w-4 text-center">{i + 1}</span>
                  <span className="font-medium">{step.label}</span>
                </div>
                <div className="flex items-center gap-4 tabular-nums">
                  <span className="text-phantom-ghost text-xs">{step.pct}%</span>
                  <span className="font-bold w-16 text-right">{step.value.toLocaleString()}</span>
                </div>
              </div>
              <div className="h-8 rounded-lg bg-phantom-panelHi overflow-hidden">
                <div
                  className={cn("h-full rounded-lg transition-all flex items-center pl-3", step.color)}
                  style={{ width: `${step.pct}%` }}
                >
                  {step.pct > 20 && (
                    <span className="text-[10px] font-bold text-phantom-bg">{step.value.toLocaleString()}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
          <div className="pt-2 border-t border-phantom-border/40 flex items-center justify-between text-xs text-phantom-ghost">
            <span>Overall conversion rate</span>
            <span className="phantom-accent-text font-bold text-sm">10.5% matches → converted</span>
          </div>
        </div>
      </Panel>
    </div>
  );
}
