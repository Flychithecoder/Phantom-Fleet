"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { RotateCcw, CheckCircle2, PauseCircle, AlertTriangle } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const UNFOLLOW_QUEUE = [
  { id: "1", account: "@tatiannalifee",   following: 4_820, queued: 140, daysSince: 3, status: "Active",  warning: false },
  { id: "2", account: "@melodierose_",    following: 5_910, queued: 200, daysSince: 2, status: "Active",  warning: true  },
  { id: "3", account: "@emilyx.official", following: 3_240, queued: 80,  daysSince: 5, status: "Paused",  warning: false },
  { id: "4", account: "@brianna.cxo",     following: 6_100, queued: 220, daysSince: 1, status: "Active",  warning: true  },
  { id: "5", account: "@jasminne.vibes",  following: 2_180, queued: 60,  daysSince: 7, status: "Active",  warning: false },
  { id: "6", account: "@xo.claramae",     following: 4_460, queued: 110, daysSince: 4, status: "Active",  warning: false },
  { id: "7", account: "@novalynne_fit",   following: 1_940, queued: 45,  daysSince: 6, status: "Paused",  warning: false },
  { id: "8", account: "@sierraglows",     following: 5_840, queued: 190, daysSince: 2, status: "Active",  warning: true  },
];

const FOLLOW_BACK_CONVERTS = [
  { id: "1", account: "@tatiannalifee",   followedBackBy: "@fitness_motivation",  date: "Apr 11", daysToConvert: 2, dmInitiated: true  },
  { id: "2", account: "@melodierose_",    followedBackBy: "@gym_culture",          date: "Apr 10", daysToConvert: 3, dmInitiated: true  },
  { id: "3", account: "@emilyx.official", followedBackBy: "@wellness_daily",       date: "Apr 9",  daysToConvert: 1, dmInitiated: false },
  { id: "4", account: "@brianna.cxo",     followedBackBy: "@lifestyle_queen",      date: "Apr 8",  daysToConvert: 4, dmInitiated: true  },
  { id: "5", account: "@jasminne.vibes",  followedBackBy: "@morning_rituals",      date: "Apr 7",  daysToConvert: 2, dmInitiated: true  },
  { id: "6", account: "@xo.claramae",     followedBackBy: "@softlife.ceo",         date: "Apr 6",  daysToConvert: 5, dmInitiated: false },
];

const DAILY_UNFOLLOWS = [
  { day: "Apr 7",  count: 1_840 },
  { day: "Apr 8",  count: 2_410 },
  { day: "Apr 9",  count: 2_180 },
  { day: "Apr 10", count: 2_760 },
  { day: "Apr 11", count: 2_100 },
  { day: "Apr 12", count: 2_490 },
  { day: "Apr 13", count: 2_340 },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ThreadsUnfollowPage() {
  const [statusFilter, setStatusFilter] = useState<"All" | "Active" | "Paused">("All");

  const filteredQueue =
    statusFilter === "All"
      ? UNFOLLOW_QUEUE
      : UNFOLLOW_QUEUE.filter((r) => r.status === statusFilter);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Threads · unfollow engine
        </div>
        <div className="flex items-center gap-3 mt-2">
          <RotateCcw className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Unfollow <span className="phantom-accent-text">Queue</span>
          </h1>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Automated follow-back detection, follow-wall management, and safe unfollow scheduling across the Threads fleet.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Unfollowed Today"        value="2,340"  delta={0.076} sub="vs yesterday"           />
        <KPICard label="Follow-Back Protected"   value="847"    sub="safe from unfollow"                   />
        <KPICard label="Avg Following Count"     value="4,210"  sub="across fleet"                         />
        <KPICard label="Accounts Near Wall"      value="3"      sub="following >5.8K — act now" accent     />
      </div>

      {/* Two tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Unfollow Queue */}
        <Panel
          label="queue"
          title="Unfollow Queue"
          actions={
            <div className="flex gap-1.5">
              {(["All", "Active", "Paused"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={`px-3 py-1 rounded text-xs font-medium transition-all border ${
                    statusFilter === f
                      ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                      : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-phantom-border">
                  <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-4 font-medium">Account</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-4 font-medium">Following</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-4 font-medium">Queued</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-4 font-medium">Days</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-phantom-border/40">
                {filteredQueue.map((row) => (
                  <tr key={row.id} className="hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs text-phantom-accent">{row.account}</span>
                        {row.warning && (
                          <AlertTriangle className="w-3 h-3 text-phantom-amber flex-shrink-0" strokeWidth={2.5} />
                        )}
                      </div>
                    </td>
                    <td className="py-3 pr-4 text-right font-mono text-xs tabular-nums">
                      <span className={row.following > 5_800 ? "text-phantom-amber font-semibold" : "text-white"}>
                        {row.following.toLocaleString()}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-right font-mono text-xs text-phantom-ghost tabular-nums">
                      {row.queued}
                    </td>
                    <td className="py-3 pr-4 text-right text-xs text-phantom-ghost tabular-nums">
                      {row.daysSince}d
                    </td>
                    <td className="py-3 text-right">
                      {row.status === "Active" ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-[10px] font-semibold">
                          <CheckCircle2 className="w-3 h-3" strokeWidth={2.5} />
                          Active
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-phantom-ghost/10 border border-phantom-border text-phantom-ghost text-[10px] font-semibold">
                          <PauseCircle className="w-3 h-3" strokeWidth={2.5} />
                          Paused
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* Follow-Back Converts */}
        <Panel label="conversions" title="Follow-Back Converts">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-phantom-border">
                  <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-3 font-medium">Account</th>
                  <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-3 font-medium">Followed Back By</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-3 font-medium">Date</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-3 font-medium">Days</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">DM</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-phantom-border/40">
                {FOLLOW_BACK_CONVERTS.map((row) => (
                  <tr key={row.id} className="hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="py-3 pr-3 font-mono text-xs text-phantom-accent">{row.account}</td>
                    <td className="py-3 pr-3 font-mono text-xs text-phantom-magenta truncate max-w-[120px]">
                      {row.followedBackBy}
                    </td>
                    <td className="py-3 pr-3 text-right text-xs text-phantom-ghost">{row.date}</td>
                    <td className="py-3 pr-3 text-right font-mono text-xs text-white tabular-nums">
                      {row.daysToConvert}d
                    </td>
                    <td className="py-3 text-right">
                      {row.dmInitiated ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-phantom-accent/10 border border-phantom-accent/20 text-phantom-accent text-[10px] font-semibold">
                          Sent
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-phantom-ghost/10 border border-phantom-border text-phantom-ghost text-[10px] font-semibold">
                          No
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* 7-day bar chart */}
      <Panel label="7-day trend" title="Daily Unfollow Volume">
        <div className="h-52 mt-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={DAILY_UNFOLLOWS} barCategoryGap="30%">
              <XAxis
                dataKey="day"
                tick={{ fill: "hsl(var(--phantom-ghost))", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "hsl(var(--phantom-ghost))", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => `${(v / 1000).toFixed(1)}K`}
              />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--phantom-panel))",
                  border: "1px solid hsl(var(--phantom-border))",
                  borderRadius: "8px",
                  color: "white",
                  fontSize: 12,
                }}
                cursor={{ fill: "hsl(var(--phantom-panelHi))" }}
                formatter={(value: number) => [value.toLocaleString(), "Unfollows"]}
              />
              <Bar dataKey="count" fill="hsl(var(--phantom-accent))" radius={[4, 4, 0, 0]} opacity={0.8} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
    </div>
  );
}
