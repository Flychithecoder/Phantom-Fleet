"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { TrendingUp, Clock, Zap, RotateCcw, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type WarmupAccount = {
  id: string;
  username: string;
  persona: string;
  warmupType: "new" | "rewake" | "steady";
  currentDay: number;
  targetDay: number;
  actionsToday: number;
  maxToday: number;
  status: "ramping" | "steady" | "completed" | "paused";
};

const ACCOUNTS: WarmupAccount[] = [
  { id: "1",  username: "@luna_aesthetic_47",  persona: "Lifestyle / Wellness",      warmupType: "new",    currentDay: 3,  targetDay: 28, actionsToday: 18,  maxToday: 20,  status: "ramping"   },
  { id: "2",  username: "@mia_vibes_real",     persona: "Fitness / Motivation",      warmupType: "new",    currentDay: 11, targetDay: 28, actionsToday: 62,  maxToday: 65,  status: "ramping"   },
  { id: "3",  username: "@nova_daily_x",       persona: "Fashion / Style",           warmupType: "rewake", currentDay: 4,  targetDay: 7,  actionsToday: 85,  maxToday: 90,  status: "ramping"   },
  { id: "4",  username: "@jade_glowup_22",     persona: "Beauty / Skincare",         warmupType: "steady", currentDay: 28, targetDay: 28, actionsToday: 120, maxToday: 120, status: "steady"    },
  { id: "5",  username: "@swift_emma_fit",     persona: "Fitness / Nutrition",       warmupType: "new",    currentDay: 22, targetDay: 28, actionsToday: 108, maxToday: 110, status: "ramping"   },
  { id: "6",  username: "@aria_content_hub",   persona: "Travel / Adventure",        warmupType: "new",    currentDay: 28, targetDay: 28, actionsToday: 120, maxToday: 120, status: "completed" },
  { id: "7",  username: "@grace_fit_life",     persona: "Wellness / Mindfulness",    warmupType: "rewake", currentDay: 2,  targetDay: 7,  actionsToday: 55,  maxToday: 60,  status: "ramping"   },
  { id: "8",  username: "@stella_vibes_co",    persona: "Lifestyle / Parenting",     warmupType: "new",    currentDay: 7,  targetDay: 28, actionsToday: 38,  maxToday: 40,  status: "ramping"   },
  { id: "9",  username: "@zoe_aesthetic_91",   persona: "Art / Photography",         warmupType: "steady", currentDay: 28, targetDay: 28, actionsToday: 118, maxToday: 120, status: "steady"    },
  { id: "10", username: "@ivy_wellness_page",  persona: "Health / Supplements",      warmupType: "new",    currentDay: 15, targetDay: 28, actionsToday: 82,  maxToday: 85,  status: "ramping"   },
  { id: "11", username: "@rose_style_daily",   persona: "Fashion / Luxury",          warmupType: "rewake", currentDay: 6,  targetDay: 7,  actionsToday: 108, maxToday: 110, status: "ramping"   },
  { id: "12", username: "@cleo_fitness_93",    persona: "CrossFit / Sports",         warmupType: "new",    currentDay: 1,  targetDay: 28, actionsToday: 8,   maxToday: 10,  status: "ramping"   },
  { id: "13", username: "@maya_journal_co",    persona: "Journaling / Productivity", warmupType: "new",    currentDay: 19, targetDay: 28, actionsToday: 95,  maxToday: 98,  status: "ramping"   },
  { id: "14", username: "@bella_eats_daily",   persona: "Food / Recipes",            warmupType: "steady", currentDay: 28, targetDay: 28, actionsToday: 120, maxToday: 120, status: "steady"    },
  { id: "15", username: "@poppy_travel_77",    persona: "Travel / Bucket List",      warmupType: "rewake", currentDay: 1,  targetDay: 7,  actionsToday: 40,  maxToday: 45,  status: "paused"    },
  { id: "16", username: "@sage_mind_co",       persona: "Mental Health / CBT",       warmupType: "new",    currentDay: 24, targetDay: 28, actionsToday: 112, maxToday: 115, status: "ramping"   },
  { id: "17", username: "@fern_aesthetic_33",  persona: "Home Decor / Interior",     warmupType: "new",    currentDay: 8,  targetDay: 28, actionsToday: 45,  maxToday: 48,  status: "ramping"   },
  { id: "18", username: "@lila_sport_daily",   persona: "Yoga / Pilates",            warmupType: "rewake", currentDay: 5,  targetDay: 7,  actionsToday: 100, maxToday: 100, status: "ramping"   },
];

// Day-in-curve distribution buckets (847 accounts)
const DAY_BUCKETS = [
  { label: "Day 1–7",       count: 156, pct: 18.4 },
  { label: "Day 8–14",      count: 189, pct: 22.3 },
  { label: "Day 15–21",     count: 201, pct: 23.7 },
  { label: "Day 22–28",     count: 167, pct: 19.7 },
  { label: "Steady State",  count: 134, pct: 15.8 },
];
const MAX_BUCKET_COUNT = Math.max(...DAY_BUCKETS.map((b) => b.count));

// New account 28-day curve: [follows, likes, comments] per stage
const NEW_ACCOUNT_STAGES = [
  { label: "Day 1–2",   follows: 5,   likes: 10,  comments: 2  },
  { label: "Day 3–5",   follows: 10,  likes: 20,  comments: 4  },
  { label: "Day 6–9",   follows: 20,  likes: 35,  comments: 8  },
  { label: "Day 10–14", follows: 35,  likes: 55,  comments: 12 },
  { label: "Day 15–20", follows: 55,  likes: 80,  comments: 18 },
  { label: "Day 21–25", follows: 75,  likes: 100, comments: 24 },
  { label: "Day 26–28", follows: 90,  likes: 115, comments: 28 },
  { label: "Steady",    follows: 100, likes: 120, comments: 30 },
];

const NEW_MAX = 120;

// Re-wake 7-day curve
const REWAKE_STAGES = [
  { label: "Day 1",   follows: 30,  likes: 45,  comments: 8  },
  { label: "Day 2",   follows: 45,  likes: 65,  comments: 12 },
  { label: "Day 3",   follows: 60,  likes: 80,  comments: 16 },
  { label: "Day 4",   follows: 75,  likes: 95,  comments: 20 },
  { label: "Day 5",   follows: 88,  likes: 108, comments: 24 },
  { label: "Day 6",   follows: 95,  likes: 115, comments: 27 },
  { label: "Day 7",   follows: 100, likes: 120, comments: 30 },
];

const REWAKE_MAX = 120;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: WarmupAccount["status"] }) {
  const map = {
    ramping:   { label: "Ramping",   cls: "bg-phantom-amber/10 border-phantom-amber/20 text-phantom-amber" },
    steady:    { label: "Steady",    cls: "bg-phantom-alive/10 border-phantom-alive/20 text-phantom-alive" },
    completed: { label: "Completed", cls: "bg-phantom-accent/10 border-phantom-accent/20 text-phantom-accent" },
    paused:    { label: "Paused",    cls: "bg-phantom-ghost/10 border-phantom-border text-phantom-ghost" },
  };
  const { label, cls } = map[status];
  return (
    <span className={cn("px-2 py-0.5 rounded-full border text-[10px] font-semibold whitespace-nowrap", cls)}>
      {label}
    </span>
  );
}

function TypeBadge({ type }: { type: WarmupAccount["warmupType"] }) {
  const map = {
    new:    { label: "New",     cls: "text-phantom-magenta" },
    rewake: { label: "Re-wake", cls: "text-phantom-amber" },
    steady: { label: "Steady",  cls: "text-phantom-alive" },
  };
  const { label, cls } = map[type];
  return <span className={cn("text-xs font-semibold", cls)}>{label}</span>;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WarmupPage() {
  const [filter, setFilter] = useState<"all" | "new" | "rewake" | "steady">("all");

  const filtered = filter === "all" ? ACCOUNTS : ACCOUNTS.filter((a) => a.warmupType === filter);

  const completingThisWeek = ACCOUNTS.filter(
    (a) => a.warmupType === "new" && a.targetDay - a.currentDay <= 7 && a.currentDay < a.targetDay
  ).length + ACCOUNTS.filter(
    (a) => a.warmupType === "rewake" && a.targetDay - a.currentDay <= 3
  ).length;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Instagram · account safety
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <TrendingUp className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Warm-up <span className="phantom-accent-text">Curve</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-accent/10 border border-phantom-accent/20 text-phantom-accent text-xs font-semibold">
            847 accounts tracked
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Every account is positioned on its warm-up curve. Actions are throttled daily by stage to avoid action-block triggers on new and re-woken accounts.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Accounts in Warm-up"
          value="713"
          sub="new + re-wake curves"
          delta={0.041}
        />
        <KPICard
          label="Avg Day in Curve"
          value="14.3"
          sub="across all active accounts"
          accent
        />
        <KPICard
          label="Completing This Week"
          value={String(completingThisWeek + 38)}
          sub="transition to steady state"
          delta={0.12}
        />
        <KPICard
          label="Re-wake Queue"
          value="94"
          sub="accounts pending re-activation"
        />
      </div>

      {/* Day-in-curve distribution bar chart */}
      <Panel
        label="distribution"
        title="Accounts by Day-in-Curve"
        subtitle="Distribution of all 847 accounts across warm-up stages"
      >
        <div className="space-y-3">
          {DAY_BUCKETS.map((bucket) => (
            <div key={bucket.label} className="flex items-center gap-4">
              <span className="text-[11px] text-phantom-ghost font-mono w-24 shrink-0">{bucket.label}</span>
              <div className="flex-1 h-7 bg-phantom-border/30 rounded overflow-hidden relative">
                <div
                  className="h-full rounded bg-gradient-to-r from-phantom-accent/80 to-phantom-accent/50 transition-all"
                  style={{ width: `${(bucket.count / MAX_BUCKET_COUNT) * 100}%` }}
                />
                <span className="absolute inset-0 flex items-center pl-3 text-[11px] font-semibold text-white/80">
                  {bucket.count} accounts
                </span>
              </div>
              <span className="text-[11px] text-phantom-ghost tabular-nums w-10 text-right shrink-0 font-mono">
                {bucket.pct}%
              </span>
            </div>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-3 gap-4 pt-4 border-t border-phantom-border">
          <div className="text-center">
            <div className="text-phantom-accent font-bold text-lg tabular-nums">156</div>
            <div className="text-[10px] text-phantom-ghost mt-0.5">Early stage (1–7d)</div>
          </div>
          <div className="text-center">
            <div className="text-phantom-amber font-bold text-lg tabular-nums">557</div>
            <div className="text-[10px] text-phantom-ghost mt-0.5">Mid-late ramp (8–28d)</div>
          </div>
          <div className="text-center">
            <div className="text-phantom-alive font-bold text-lg tabular-nums">134</div>
            <div className="text-[10px] text-phantom-ghost mt-0.5">Steady state</div>
          </div>
        </div>
      </Panel>

      {/* Per-curve visualizers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* New Account 28-day curve */}
        <Panel
          label="new account curve"
          title={<>New Account <span className="phantom-accent-text">28-Day</span> Ramp</>}
          subtitle="Daily action budgets per stage — follows / likes / comments"
        >
          <div className="space-y-2.5 mt-1">
            {NEW_ACCOUNT_STAGES.map((stage, i) => (
              <div key={stage.label} className="space-y-1">
                <div className="flex items-center justify-between text-[10px] text-phantom-ghost">
                  <span className="font-mono w-16 shrink-0">{stage.label}</span>
                  <div className="flex gap-3 text-[10px] tabular-nums">
                    <span className="text-phantom-accent">{stage.follows}F</span>
                    <span className="text-phantom-alive">{stage.likes}L</span>
                    <span className="text-phantom-amber">{stage.comments}C</span>
                  </div>
                </div>
                <div className="flex gap-1 h-4">
                  <div
                    className="h-full rounded-sm bg-phantom-accent/60"
                    style={{ width: `${(stage.follows / NEW_MAX) * 100}%` }}
                  />
                  <div
                    className="h-full rounded-sm bg-phantom-alive/50"
                    style={{ width: `${(stage.likes / NEW_MAX) * 100}%` }}
                  />
                  <div
                    className="h-full rounded-sm bg-phantom-amber/50"
                    style={{ width: `${(stage.comments / NEW_MAX) * 100}%` }}
                  />
                </div>
                {i < NEW_ACCOUNT_STAGES.length - 1 && (
                  <div className="flex justify-center">
                    <ChevronRight className="w-3 h-3 text-phantom-border rotate-90" />
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="flex gap-4 mt-4 pt-3 border-t border-phantom-border text-[10px] text-phantom-ghost">
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-phantom-accent/60" />Follows</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-phantom-alive/50" />Likes</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-phantom-amber/50" />Comments</span>
          </div>
        </Panel>

        {/* Re-wake 7-day curve */}
        <Panel
          label="re-wake curve"
          title={<>Re-wake <span className="phantom-accent-text">7-Day</span> Recovery</>}
          subtitle="Faster ramp for accounts returning from rest — day-by-day budget"
        >
          <div className="space-y-2.5 mt-1">
            {REWAKE_STAGES.map((stage, i) => (
              <div key={stage.label} className="space-y-1">
                <div className="flex items-center justify-between text-[10px] text-phantom-ghost">
                  <span className="font-mono w-10 shrink-0">{stage.label}</span>
                  <div className="flex gap-3 text-[10px] tabular-nums">
                    <span className="text-phantom-accent">{stage.follows}F</span>
                    <span className="text-phantom-alive">{stage.likes}L</span>
                    <span className="text-phantom-amber">{stage.comments}C</span>
                  </div>
                </div>
                <div className="flex gap-1 h-5">
                  <div
                    className="h-full rounded-sm bg-phantom-accent/60"
                    style={{ width: `${(stage.follows / REWAKE_MAX) * 100}%` }}
                  />
                  <div
                    className="h-full rounded-sm bg-phantom-alive/50"
                    style={{ width: `${(stage.likes / REWAKE_MAX) * 100}%` }}
                  />
                  <div
                    className="h-full rounded-sm bg-phantom-amber/50"
                    style={{ width: `${(stage.comments / REWAKE_MAX) * 100}%` }}
                  />
                </div>
                {i < REWAKE_STAGES.length - 1 && (
                  <div className="flex justify-center">
                    <ChevronRight className="w-3 h-3 text-phantom-border rotate-90" />
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-phantom-border text-[11px] text-phantom-ghost">
            Re-wake hits <span className="text-phantom-alive font-semibold">full budget by Day 7</span> vs Day 28 for new accounts.
          </div>
        </Panel>
      </div>

      {/* Accounts table */}
      <Panel
        label="account list"
        title="Warm-up Account Detail"
        subtitle={`Showing ${filtered.length} accounts · daily action progress vs budget`}
        actions={
          <div className="flex gap-1.5">
            {(["all", "new", "rewake", "steady"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "px-3 py-1 rounded text-xs font-medium transition-all border",
                  filter === f
                    ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                    : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                )}
              >
                {f === "rewake" ? "Re-wake" : f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Account", "Persona", "Type", "Day", "Progress", "Actions Today", "Status"].map((h) => (
                  <th
                    key={h}
                    className="text-left text-[10px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-3 font-medium whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-phantom-border/40">
              {filtered.map((acc) => {
                const pct = Math.round((acc.currentDay / acc.targetDay) * 100);
                const actionPct = Math.round((acc.actionsToday / acc.maxToday) * 100);
                return (
                  <tr
                    key={acc.id}
                    className="hover:bg-phantom-panelHi/30 transition-colors"
                  >
                    <td className="py-3 pr-3 font-mono text-xs text-phantom-accent whitespace-nowrap">
                      {acc.username}
                    </td>
                    <td className="py-3 pr-3 text-xs text-phantom-ghost whitespace-nowrap max-w-[160px] truncate">
                      {acc.persona}
                    </td>
                    <td className="py-3 pr-3">
                      <TypeBadge type={acc.warmupType} />
                    </td>
                    <td className="py-3 pr-3 text-xs tabular-nums font-mono whitespace-nowrap">
                      <span className="text-white">{acc.currentDay}</span>
                      <span className="text-phantom-ghost">/{acc.targetDay}d</span>
                    </td>
                    <td className="py-3 pr-3 min-w-[100px]">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-phantom-border/50 rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full bg-phantom-accent"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-phantom-ghost tabular-nums w-8 text-right">{pct}%</span>
                      </div>
                    </td>
                    <td className="py-3 pr-3 min-w-[120px]">
                      <div className="flex items-center gap-2">
                        <span className="text-xs tabular-nums font-mono text-white">{acc.actionsToday}</span>
                        <span className="text-[10px] text-phantom-ghost">/ {acc.maxToday}</span>
                        <div className="flex-1 h-1.5 bg-phantom-border/50 rounded-full overflow-hidden min-w-[40px]">
                          <div
                            className={cn(
                              "h-full rounded-full",
                              actionPct >= 90 ? "bg-phantom-alive" : actionPct >= 60 ? "bg-phantom-amber" : "bg-phantom-accent/60"
                            )}
                            style={{ width: `${actionPct}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="py-3">
                      <StatusBadge status={acc.status} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-4 pt-3 border-t border-phantom-border flex items-center gap-6 text-[10px] text-phantom-ghost">
          <span className="flex items-center gap-1.5">
            <Clock className="w-3 h-3" />
            Actions reset daily at <span className="text-white font-semibold">00:00 UTC</span>
          </span>
          <span className="flex items-center gap-1.5">
            <Zap className="w-3 h-3 text-phantom-amber" />
            Budgets calculated per-stage with ±8% jitter
          </span>
          <span className="flex items-center gap-1.5">
            <RotateCcw className="w-3 h-3 text-phantom-accent" />
            Re-wake triggers after 14d rest minimum
          </span>
        </div>
      </Panel>
    </div>
  );
}
