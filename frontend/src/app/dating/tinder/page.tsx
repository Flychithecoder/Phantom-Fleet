"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Flame } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type AcctStatus = "ACTIVE" | "PAUSED" | "BOOSTED" | "SHADOW";

const STATUS_STYLES: Record<AcctStatus, { bg: string; text: string; border: string }> = {
  ACTIVE:  { bg: "bg-phantom-alive/10",   text: "text-phantom-alive",   border: "border-phantom-alive/20"   },
  PAUSED:  { bg: "bg-phantom-ghost/10",   text: "text-phantom-ghost",   border: "border-phantom-ghost/20"   },
  BOOSTED: { bg: "bg-phantom-accent/10",  text: "text-phantom-accent",  border: "border-phantom-accent/20"  },
  SHADOW:  { bg: "bg-phantom-red/10",     text: "text-phantom-red",     border: "border-phantom-red/20"     },
};

const ACCOUNTS = [
  { id: "1",  name: "Sofia_T",     elo: 8.1, boost: true,  swipesToday: 98,  swipeLimit: 100, matches7d: 24, lastActive: "4m ago",  status: "BOOSTED" as AcctStatus },
  { id: "2",  name: "Ariana_T2",   elo: 7.4, boost: false, swipesToday: 87,  swipeLimit: 100, matches7d: 18, lastActive: "12m ago", status: "ACTIVE"  as AcctStatus },
  { id: "3",  name: "Mia_Gold",    elo: 9.2, boost: false, swipesToday: 100, swipeLimit: 100, matches7d: 31, lastActive: "28m ago", status: "ACTIVE"  as AcctStatus },
  { id: "4",  name: "Luna_Vibes",  elo: 6.3, boost: false, swipesToday: 0,   swipeLimit: 100, matches7d: 8,  lastActive: "3h ago",  status: "PAUSED"  as AcctStatus },
  { id: "5",  name: "Cass_T",      elo: 7.8, boost: true,  swipesToday: 72,  swipeLimit: 100, matches7d: 22, lastActive: "9m ago",  status: "BOOSTED" as AcctStatus },
  { id: "6",  name: "Jade_Rose",   elo: 5.1, boost: false, swipesToday: 44,  swipeLimit: 100, matches7d: 6,  lastActive: "1h ago",  status: "SHADOW"  as AcctStatus },
  { id: "7",  name: "Ellie_Blush", elo: 8.7, boost: false, swipesToday: 95,  swipeLimit: 100, matches7d: 28, lastActive: "2m ago",  status: "ACTIVE"  as AcctStatus },
  { id: "8",  name: "Nora_Gold2",  elo: 7.1, boost: false, swipesToday: 61,  swipeLimit: 100, matches7d: 15, lastActive: "22m ago", status: "ACTIVE"  as AcctStatus },
];

const ELO_TIERS = [
  { label: "1–4",  range: [1, 4],  count: 3, color: "bg-phantom-red"     },
  { label: "5–6",  range: [5, 6],  count: 7, color: "bg-phantom-amber"   },
  { label: "7–8",  range: [7, 8],  count: 18, color: "bg-phantom-accent" },
  { label: "9–10", range: [9, 10], count: 10, color: "bg-phantom-alive"  },
];
const MAX_ELO_COUNT = 18;

const BOOST_SCHEDULE = [
  { id: "1", account: "Sofia_T",     scheduledAt: "08:00",  duration: "30 min", status: "ACTIVE"    },
  { id: "2", account: "Cass_T",      scheduledAt: "09:30",  duration: "30 min", status: "ACTIVE"    },
  { id: "3", account: "Mia_Gold",    scheduledAt: "12:00",  duration: "30 min", status: "SCHEDULED" },
  { id: "4", account: "Ariana_T2",   scheduledAt: "17:00",  duration: "30 min", status: "SCHEDULED" },
  { id: "5", account: "Ellie_Blush", scheduledAt: "19:30",  duration: "30 min", status: "SCHEDULED" },
  { id: "6", account: "Nora_Gold2",  scheduledAt: "21:00",  duration: "30 min", status: "SCHEDULED" },
];

const PHOTO_SETS = [
  { id: "ps1", name: "Lifestyle A",  accounts: 14, preview: "Casual outdoor, golden hour",    topMatch: 38 },
  { id: "ps2", name: "Fitness Set",  accounts: 9,  preview: "Gym + active wear",               topMatch: 41 },
  { id: "ps3", name: "Professional", accounts: 8,  preview: "Office casual, confident",        topMatch: 31 },
  { id: "ps4", name: "Beach Vibes",  accounts: 7,  preview: "Summer beach, playful",           topMatch: 44 },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TinderManagementPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Dating · Tinder
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Flame className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Tinder <span className="phantom-accent-text">Management</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          38 active Tinder profiles — ELO optimization, boost scheduling, swipe quota tracking, and
          photo set performance analysis.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Active Profiles"  value="38"         sub="4 boosted now"         accent />
        <KPICard label="ELO Score Avg"    value="7.2"        delta={0.061}                      />
        <KPICard label="Daily Swipes"     value="1,140/1,200" sub="95% of quota used"           />
        <KPICard label="Matches Today"    value="17"         delta={0.133}                      />
      </div>

      {/* Account table */}
      <Panel label="accounts" title="Profile Health" subtitle="Real-time status for all 38 Tinder profiles">
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Profile", "ELO", "Boost", "Swipes Today", "Limit", "Matches 7d", "Last Active", "Status"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ACCOUNTS.map((row) => {
                const s = STATUS_STYLES[row.status];
                const swipePct = Math.round((row.swipesToday / row.swipeLimit) * 100);
                return (
                  <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-3 font-mono text-xs text-phantom-accent">{row.name}</td>
                    <td className="px-3 py-3 tabular-nums">
                      <span className={cn(
                        "font-bold text-sm",
                        row.elo >= 9 ? "text-phantom-alive" : row.elo >= 7 ? "phantom-accent-text" : row.elo >= 5 ? "text-phantom-amber" : "text-phantom-red"
                      )}>
                        {row.elo.toFixed(1)}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      {row.boost
                        ? <span className="px-2 py-0.5 rounded-full bg-phantom-amber/10 text-phantom-amber border border-phantom-amber/20 text-[10px] font-bold">LIVE</span>
                        : <span className="text-phantom-ghost text-xs">—</span>
                      }
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <span className="tabular-nums text-xs w-8">{row.swipesToday}</span>
                        <div className="h-1.5 w-16 rounded-full bg-phantom-border overflow-hidden">
                          <div
                            className={cn("h-full rounded-full", swipePct >= 95 ? "bg-phantom-amber" : "bg-phantom-accent")}
                            style={{ width: `${swipePct}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3 tabular-nums text-phantom-ghost text-xs">{row.swipeLimit}</td>
                    <td className="px-3 py-3 tabular-nums font-semibold">{row.matches7d}</td>
                    <td className="px-3 py-3 text-phantom-ghost text-xs">{row.lastActive}</td>
                    <td className="px-3 py-3">
                      <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", s.bg, s.text, s.border)}>
                        {row.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ELO Distribution + Boost Schedule */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ELO Histogram */}
        <Panel label="distribution" title="ELO Score Histogram" subtitle="Accounts per ELO tier">
          <div className="space-y-3 pt-2">
            {ELO_TIERS.map((tier) => (
              <div key={tier.label} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-phantom-ghost font-medium w-10">ELO {tier.label}</span>
                  <span className="tabular-nums font-bold">{tier.count} accts</span>
                </div>
                <div className="h-8 rounded-lg bg-phantom-panelHi overflow-hidden flex items-center">
                  <div
                    className={cn("h-full rounded-lg transition-all flex items-center pl-3", tier.color)}
                    style={{ width: `${(tier.count / MAX_ELO_COUNT) * 100}%` }}
                  >
                    {tier.count >= 6 && (
                      <span className="text-[10px] font-bold text-phantom-bg">{tier.count}</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-4 border-t border-phantom-border/40 grid grid-cols-4 gap-2">
            {ELO_TIERS.map((tier) => (
              <div key={tier.label} className="text-center">
                <div className={cn("text-lg font-bold", tier.color.replace("bg-", "text-"))}>{tier.count}</div>
                <div className="text-[10px] text-phantom-ghost">{tier.label}</div>
              </div>
            ))}
          </div>
        </Panel>

        {/* Boost Schedule */}
        <Panel label="scheduler" title="Boost Schedule" subtitle="Upcoming and active boosts">
          <div className="space-y-2">
            {BOOST_SCHEDULE.map((b) => (
              <div key={b.id} className="flex items-center gap-3 p-3 rounded-lg bg-phantom-panelHi border border-phantom-border/40">
                <div className={cn(
                  "w-2 h-2 rounded-full flex-shrink-0",
                  b.status === "ACTIVE" ? "bg-phantom-alive animate-pulse" : "bg-phantom-ghost"
                )} />
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs text-phantom-accent">{b.account}</div>
                  <div className="text-[11px] text-phantom-ghost">{b.duration}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs font-bold tabular-nums">{b.scheduledAt}</div>
                  <div className={cn(
                    "text-[10px] font-semibold",
                    b.status === "ACTIVE" ? "text-phantom-alive" : "text-phantom-ghost"
                  )}>
                    {b.status}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {/* Photo Sets */}
      <Panel label="creative" title="Photo Set Manager" subtitle="4 active photo sets across 38 profiles">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {PHOTO_SETS.map((ps) => (
            <div key={ps.id} className="rounded-xl bg-phantom-panelHi border border-phantom-border p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-xs font-bold">{ps.name}</div>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-phantom-accent/10 text-phantom-accent border border-phantom-accent/20 font-semibold">
                  {ps.accounts} accts
                </span>
              </div>
              <div className="text-[11px] text-phantom-ghost">{ps.preview}</div>
              <div className="pt-2 border-t border-phantom-border/40 flex items-center justify-between">
                <span className="text-[11px] text-phantom-ghost">Top match rate</span>
                <span className="phantom-accent-text font-bold text-sm tabular-nums">{ps.topMatch}%</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
