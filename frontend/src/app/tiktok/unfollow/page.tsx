"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { RotateCcw, CheckCircle2, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type Priority = "HIGH" | "MED" | "LOW";
type FollowBack = "YES" | "NO" | "PENDING";

const PRIORITY_STYLES: Record<Priority, string> = {
  HIGH: "text-phantom-red",
  MED:  "text-phantom-amber",
  LOW:  "text-phantom-ghost",
};

const FB_STYLES: Record<FollowBack, { bg: string; text: string; border: string }> = {
  YES:     { bg: "bg-phantom-alive/10",  text: "text-phantom-alive",  border: "border-phantom-alive/20"  },
  NO:      { bg: "bg-phantom-ghost/10",  text: "text-phantom-ghost",  border: "border-phantom-border"    },
  PENDING: { bg: "bg-phantom-amber/10",  text: "text-phantom-amber",  border: "border-phantom-amber/20"  },
};

const UNFOLLOW_QUEUE = [
  { id: "1",  account: "@tiktok_luna_us",    targets: 148, daysSince: 14, followBack: "NO"      as FollowBack, priority: "HIGH" as Priority, scheduled: "Today 14:00"  },
  { id: "2",  account: "@nova_daily_uk",     targets: 92,  daysSince: 10, followBack: "PENDING" as FollowBack, priority: "MED"  as Priority, scheduled: "Today 15:30"  },
  { id: "3",  account: "@mia_vibes_ca",      targets: 211, daysSince: 21, followBack: "NO"      as FollowBack, priority: "HIGH" as Priority, scheduled: "Today 16:00"  },
  { id: "4",  account: "@jade_glowup_au",    targets: 64,  daysSince: 7,  followBack: "YES"     as FollowBack, priority: "LOW"  as Priority, scheduled: "Tomorrow"     },
  { id: "5",  account: "@swift_emma_us",     targets: 176, daysSince: 18, followBack: "NO"      as FollowBack, priority: "HIGH" as Priority, scheduled: "Today 17:00"  },
  { id: "6",  account: "@stella_fit_uk",     targets: 88,  daysSince: 9,  followBack: "PENDING" as FollowBack, priority: "MED"  as Priority, scheduled: "Tomorrow"     },
  { id: "7",  account: "@aria_content_ca",   targets: 53,  daysSince: 6,  followBack: "YES"     as FollowBack, priority: "LOW"  as Priority, scheduled: "Tomorrow"     },
  { id: "8",  account: "@grace_daily_us",    targets: 134, daysSince: 15, followBack: "NO"      as FollowBack, priority: "MED"  as Priority, scheduled: "Today 18:00"  },
  { id: "9",  account: "@remi_blossoms_au",  targets: 97,  daysSince: 12, followBack: "NO"      as FollowBack, priority: "MED"  as Priority, scheduled: "Today 19:00"  },
  { id: "10", account: "@kali_aesthetics_us",targets: 72,  daysSince: 8,  followBack: "PENDING" as FollowBack, priority: "LOW"  as Priority, scheduled: "Tomorrow"     },
];

// Daily budget per account (consumed / total)
const RATE_LIMIT_STATUS = [
  { id: "r1", account: "@tiktok_luna_us",    consumed: 312, budget: 400, pct: 78 },
  { id: "r2", account: "@nova_daily_uk",     consumed: 88,  budget: 300, pct: 29 },
  { id: "r3", account: "@mia_vibes_ca",      consumed: 390, budget: 400, pct: 97 },
  { id: "r4", account: "@swift_emma_us",     consumed: 220, budget: 400, pct: 55 },
  { id: "r5", account: "@grace_daily_us",    consumed: 184, budget: 400, pct: 46 },
  { id: "r6", account: "@remi_blossoms_au",  consumed: 145, budget: 300, pct: 48 },
];

// Settings state (static display — toggle is visual only)
const SETTINGS = [
  { key: "gracePeriod",     label: "Grace Period",                  value: "14 days",  type: "text"   },
  { key: "maxPerDay",       label: "Max Unfollows / Day / Account", value: "400",      type: "text"   },
  { key: "skipFollowBack",  label: "Skip if Followed Back",         value: true,       type: "toggle" },
  { key: "whitelist",       label: "Whitelist Protection",          value: true,       type: "toggle" },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TikTokUnfollowPage() {
  const [priorityFilter, setPriorityFilter] = useState<"All" | Priority>("All");

  const filtered = priorityFilter === "All"
    ? UNFOLLOW_QUEUE
    : UNFOLLOW_QUEUE.filter((r) => r.priority === priorityFilter);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          TikTok · unfollow engine
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <RotateCcw className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Unfollow <span className="phantom-accent-text">Engine</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-amber/10 border border-phantom-amber/20 text-phantom-amber text-xs font-semibold">
            1,240 in queue
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Follow-back detection, grace-period management, and safe unfollow scheduling across the TikTok fleet.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Queue Size"          value="1,240"  sub="pending unfollows"                  />
        <KPICard label="Unfollowed Today"    value="384"    delta={0.063}  sub="vs yesterday"         />
        <KPICard label="FBR Preserved"       value="94.2%"  delta={0.011}  sub="follow-back protected" />
        <KPICard label="Next Run"            value="2h"     sub="14:00 UTC batch"     accent          />
      </div>

      {/* Queue table */}
      <Panel
        label="queue"
        title="Unfollow Queue"
        actions={
          <div className="flex gap-1.5">
            {(["All", "HIGH", "MED", "LOW"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setPriorityFilter(f)}
                className={cn(
                  "px-3 py-1 rounded text-xs font-medium transition-all border",
                  priorityFilter === f
                    ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                    : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                )}
              >
                {f}
              </button>
            ))}
          </div>
        }
      >
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Account", "Targets", "Days Since Follow", "Follow Back", "Priority", "Scheduled"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const fb = FB_STYLES[row.followBack];
                return (
                  <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-3 font-mono text-xs text-phantom-accent">{row.account}</td>
                    <td className="px-3 py-3 text-xs tabular-nums font-bold text-white">{row.targets}</td>
                    <td className="px-3 py-3 text-xs tabular-nums text-phantom-ghost">{row.daysSince}d</td>
                    <td className="px-3 py-3">
                      <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border", fb.bg, fb.text, fb.border)}>
                        {row.followBack === "YES" && <CheckCircle2 className="w-3 h-3" strokeWidth={2.5} />}
                        {row.followBack === "PENDING" && <Clock className="w-3 h-3" strokeWidth={2.5} />}
                        {row.followBack}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <span className={cn("text-xs font-bold", PRIORITY_STYLES[row.priority])}>
                        {row.priority}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-xs text-phantom-ghost tabular-nums">{row.scheduled}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Settings + rate limits */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Settings */}
        <Panel label="configuration" title="Unfollow Settings">
          <div className="space-y-4">
            {SETTINGS.map((s) => (
              <div key={s.key} className="flex items-center justify-between py-3 border-b border-phantom-border/40 last:border-0">
                <span className="text-sm text-white">{s.label}</span>
                {s.type === "toggle" ? (
                  <div className={cn(
                    "relative w-10 h-5 rounded-full transition-colors cursor-pointer",
                    s.value ? "bg-phantom-accent" : "bg-phantom-border"
                  )}>
                    <div className={cn(
                      "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                      s.value ? "translate-x-5" : "translate-x-0.5"
                    )} />
                  </div>
                ) : (
                  <span className="font-mono text-xs font-bold text-phantom-accent bg-phantom-panelHi border border-phantom-border px-3 py-1.5 rounded">
                    {s.value as string}
                  </span>
                )}
              </div>
            ))}
            <div className="pt-2 text-[11px] text-phantom-ghost">
              Follow-back skip prevents unfollowing accounts that followed back · whitelist protects high-value targets
            </div>
          </div>
        </Panel>

        {/* Rate limit status */}
        <Panel label="rate limits" title="Per-Account Daily Budget">
          <div className="space-y-4">
            {RATE_LIMIT_STATUS.map((r) => (
              <div key={r.id} className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-phantom-accent truncate">{r.account}</span>
                  <span className={cn(
                    "text-xs tabular-nums font-semibold",
                    r.pct >= 90 ? "text-phantom-red" : r.pct >= 70 ? "text-phantom-amber" : "text-phantom-alive"
                  )}>
                    {r.consumed}/{r.budget}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-phantom-border overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      r.pct >= 90 ? "bg-phantom-red" : r.pct >= 70 ? "bg-phantom-amber" : "bg-phantom-alive"
                    )}
                    style={{ width: `${r.pct}%` }}
                  />
                </div>
                <div className="text-[10px] text-phantom-ghost">{r.pct}% daily budget consumed</div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
