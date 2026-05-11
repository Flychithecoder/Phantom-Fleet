"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Flame } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const WARMUP_PHASES = [
  { range: "Days 1–7",   label: "View Only",           actions: "Views: 50–100 / day",           color: "bg-blue-500/20 border-blue-500/30 text-blue-300",    barColor: "bg-blue-500" },
  { range: "Days 8–14",  label: "Like Only",           actions: "Likes: 20–40 / day",             color: "bg-cyan-500/20 border-cyan-500/30 text-cyan-300",    barColor: "bg-cyan-500" },
  { range: "Days 15–21", label: "Follow + Like",       actions: "Follows: 10–20 · Likes: 30–50", color: "bg-teal-500/20 border-teal-500/30 text-teal-300",    barColor: "bg-teal-500" },
  { range: "Days 22–30", label: "Comment + Follow",    actions: "Comments: 5–10 · Follows: 20–40", color: "bg-phantom-amber/20 border-phantom-amber/30 text-phantom-amber", barColor: "bg-phantom-amber" },
  { range: "Days 31–45", label: "Full Activity",       actions: "Posts: 2–4 · Follows: 50–80 · Full", color: "bg-phantom-alive/20 border-phantom-alive/30 text-phantom-alive", barColor: "bg-phantom-alive" },
];

// Daily action budget curve (views allowed per day 1–45, compressed to 15 representative points)
const CURVE_POINTS = [20, 35, 50, 50, 65, 80, 80, 60, 75, 90, 90, 100, 110, 110, 120];
const CURVE_MAX = Math.max(...CURVE_POINTS);

type WarmupStatus = "ON_TRACK" | "BEHIND" | "GRADUATING";

const STATUS_STYLES: Record<WarmupStatus, { bg: string; text: string; border: string }> = {
  ON_TRACK:   { bg: "bg-phantom-alive/10",  text: "text-phantom-alive",  border: "border-phantom-alive/20"  },
  BEHIND:     { bg: "bg-phantom-amber/10",  text: "text-phantom-amber",  border: "border-phantom-amber/20"  },
  GRADUATING: { bg: "bg-phantom-accent/10", text: "text-phantom-accent", border: "border-phantom-accent/20" },
};

const QUEUE = [
  { id: "1",  account: "@tiktok_warm_01", region: "US", device: "Samsung A54",   day: 3,  phase: "View Only",        dailyBudget: "Views: 60",          notes: "New SIM · monitor"   },
  { id: "2",  account: "@tiktok_warm_02", region: "UK", device: "iPhone 13",     day: 11, phase: "Like Only",        dailyBudget: "Likes: 28",          notes: ""                     },
  { id: "3",  account: "@tiktok_warm_03", region: "CA", device: "Pixel 7",       day: 18, phase: "Follow + Like",    dailyBudget: "Follows: 15 · Likes: 38", notes: "FBR climbing"     },
  { id: "4",  account: "@tiktok_warm_04", region: "AU", device: "iPhone 14",     day: 26, phase: "Comment + Follow", dailyBudget: "Comments: 7 · Follows: 30", notes: ""              },
  { id: "5",  account: "@tiktok_warm_05", region: "US", device: "Samsung S21",   day: 38, phase: "Full Activity",    dailyBudget: "Posts: 3 · Follows: 60", notes: "Graduating Fri"  },
  { id: "6",  account: "@tiktok_warm_06", region: "UK", device: "iPhone 12",     day: 44, phase: "Full Activity",    dailyBudget: "Posts: 4 · Follows: 75", notes: "Graduating Mon"  },
  { id: "7",  account: "@tiktok_warm_07", region: "CA", device: "OnePlus 11",    day: 9,  phase: "Like Only",        dailyBudget: "Likes: 22",          notes: "Slow FBR · watch"    },
  { id: "8",  account: "@tiktok_warm_08", region: "AU", device: "iPhone 15",     day: 31, phase: "Full Activity",    dailyBudget: "Posts: 2 · Follows: 52", notes: ""                },
];

const GRADUATING = [
  { id: "g1", account: "@tiktok_warm_05", region: "US", day: 38, graduateOn: "Fri Apr 18", targetState: "RUNNING" },
  { id: "g2", account: "@tiktok_warm_06", region: "UK", day: 44, graduateOn: "Mon Apr 21", targetState: "RUNNING" },
  { id: "g3", account: "@tiktok_warm_09", region: "CA", day: 45, graduateOn: "Today",      targetState: "RUNNING" },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TikTokWarmupPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          TikTok · warmup queue
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <Flame className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Warmup <span className="phantom-accent-text">Queue</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-amber/10 border border-phantom-amber/20 text-phantom-amber text-xs font-semibold">
            89 in warmup
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          45-day progressive warm-up curve for new TikTok accounts — phase-gated action budgets protect trust scores.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="In Warmup"            value="89"    sub="active accounts"                    />
        <KPICard label="Graduating This Week" value="12"    delta={0.2}    sub="moving to steady state" />
        <KPICard label="Avg Daily Views"      value="2,840" delta={0.047}  sub="across warmup fleet"  />
        <KPICard label="Completion Rate"      value="91%"   sub="day-45 pass rate"      accent        />
      </div>

      {/* Warmup phase curve */}
      <Panel label="phase curve" title="45-Day Action Budget Progression">
        <div className="space-y-4">
          {/* Phase legend */}
          <div className="grid grid-cols-1 sm:grid-cols-5 gap-2">
            {WARMUP_PHASES.map((p) => (
              <div key={p.range} className={cn("rounded-lg border p-3 space-y-1", p.color)}>
                <div className="text-[10px] uppercase tracking-wider font-semibold">{p.range}</div>
                <div className="text-xs font-bold">{p.label}</div>
                <div className="text-[10px] opacity-80">{p.actions}</div>
              </div>
            ))}
          </div>

          {/* Activity curve visualization */}
          <div>
            <div className="text-[11px] text-phantom-ghost mb-2 uppercase tracking-wider">Daily action capacity curve (15-day sample)</div>
            <div className="flex items-end gap-1.5 h-24">
              {CURVE_POINTS.map((val, i) => {
                const phasePct = i / CURVE_POINTS.length;
                const barColor =
                  phasePct < 0.155 ? "bg-blue-500" :
                  phasePct < 0.31  ? "bg-cyan-500" :
                  phasePct < 0.465 ? "bg-teal-500" :
                  phasePct < 0.67  ? "bg-phantom-amber" :
                                     "bg-phantom-alive";
                return (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1 group">
                    <div className="w-full relative flex items-end" style={{ height: "72px" }}>
                      <div
                        className={cn("w-full rounded-t transition-colors", barColor)}
                        style={{ height: `${(val / CURVE_MAX) * 100}%` }}
                      />
                    </div>
                    <span className="text-[9px] text-phantom-ghost tabular-nums">{(i + 1) * 3}d</span>
                  </div>
                );
              })}
            </div>
            <div className="flex justify-between text-[10px] text-phantom-ghost mt-1">
              <span>Day 1</span>
              <span>Day 45 (full activity)</span>
            </div>
          </div>
        </div>
      </Panel>

      {/* Queue table */}
      <Panel label="queue" title="Warmup Account Queue">
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Account", "Region", "Device", "Day", "Phase", "Daily Budget", "Notes"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {QUEUE.map((row) => {
                const status: WarmupStatus = row.day >= 44 ? "GRADUATING" : row.day < 5 ? "BEHIND" : "ON_TRACK";
                const s = STATUS_STYLES[status];
                return (
                  <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-3 font-mono text-xs text-phantom-accent">{row.account}</td>
                    <td className="px-3 py-3 text-xs text-white">{row.region}</td>
                    <td className="px-3 py-3 text-xs text-phantom-ghost">{row.device}</td>
                    <td className="px-3 py-3 text-xs font-bold tabular-nums text-white">Day {row.day}</td>
                    <td className="px-3 py-3">
                      <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-semibold border", s.bg, s.text, s.border)}>
                        {row.phase}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-xs text-phantom-ghost">{row.dailyBudget}</td>
                    <td className="px-3 py-3 text-xs text-phantom-ghost">{row.notes || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Graduation pipeline */}
      <Panel label="graduation pipeline" title="Graduating to Steady State This Week" accent>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {GRADUATING.map((g) => (
            <div key={g.id} className="rounded-lg bg-phantom-panelHi border border-phantom-border p-4 space-y-2">
              <div className="font-mono text-xs text-phantom-accent">{g.account}</div>
              <div className="flex items-center gap-2 text-xs text-phantom-ghost">
                <span className="text-white font-semibold">Day {g.day} / 45</span>
                <span>·</span>
                <span>{g.region}</span>
              </div>
              <div className="h-1.5 rounded-full bg-phantom-border overflow-hidden">
                <div
                  className="h-full rounded-full bg-phantom-alive"
                  style={{ width: `${(g.day / 45) * 100}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-phantom-ghost">Graduates: <span className="text-white font-semibold">{g.graduateOn}</span></span>
                <span className="px-2 py-0.5 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-[10px] font-bold">
                  {g.targetState}
                </span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
