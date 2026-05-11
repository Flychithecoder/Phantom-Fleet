"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Video } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type ActionType = "upload" | "follow" | "like" | "comment";

const ACTION_COLORS: Record<ActionType, string> = {
  upload:  "bg-phantom-accent",
  follow:  "bg-green-400",
  like:    "bg-pink-400",
  comment: "bg-purple-400",
};

const LIVE_FEED: {
  id: number;
  account: string;
  action: string;
  type: ActionType;
  ts: string;
}[] = [
  { id:  1, account: "@tiktok_luna_us",    action: "uploaded video #lifestyle #morning",       type: "upload",  ts: "2s ago"  },
  { id:  2, account: "@nova_daily_uk",     action: "followed @gymculture.uk",                  type: "follow",  ts: "5s ago"  },
  { id:  3, account: "@mia_vibes_ca",      action: "liked video by @fitlife_canada",            type: "like",    ts: "9s ago"  },
  { id:  4, account: "@jade_glowup_au",    action: "commented on @aussie_lifestyle",            type: "comment", ts: "13s ago" },
  { id:  5, account: "@swift_emma_us",     action: "uploaded video #wellness #selfcare",        type: "upload",  ts: "17s ago" },
  { id:  6, account: "@stella_fit_uk",     action: "followed @morning_run_london",              type: "follow",  ts: "21s ago" },
  { id:  7, account: "@aria_content_ca",   action: "liked video by @plantbased.ca",             type: "like",    ts: "27s ago" },
  { id:  8, account: "@grace_daily_us",    action: "commented on @skincare.tips.usa",           type: "comment", ts: "33s ago" },
  { id:  9, account: "@tiktok_luna_us",    action: "followed @aesthetic.nyc",                  type: "follow",  ts: "39s ago" },
  { id: 10, account: "@remi_blossoms_au",  action: "uploaded video #outdoors #adventure",       type: "upload",  ts: "44s ago" },
];

type AccountStatus = "RUNNING" | "PAUSED" | "WARMING";

const STATUS_STYLES: Record<AccountStatus, { bg: string; text: string; border: string }> = {
  RUNNING: { bg: "bg-phantom-alive/10",  text: "text-phantom-alive",  border: "border-phantom-alive/20"  },
  PAUSED:  { bg: "bg-yellow-500/10",     text: "text-yellow-400",     border: "border-yellow-500/20"     },
  WARMING: { bg: "bg-blue-500/10",       text: "text-blue-400",       border: "border-blue-500/20"       },
};

const ACCOUNT_HEALTH = [
  { id: "1", username: "@tiktok_luna_us",   region: "US", os: "Android 14", warmupDay: "--", fbr7d: "4.8%", status: "RUNNING" as AccountStatus, lastActive: "1m ago"  },
  { id: "2", username: "@nova_daily_uk",    region: "UK", os: "iOS 17.4",   warmupDay: "--", fbr7d: "3.9%", status: "RUNNING" as AccountStatus, lastActive: "3m ago"  },
  { id: "3", username: "@mia_vibes_ca",     region: "CA", os: "Android 13", warmupDay: "--", fbr7d: "5.1%", status: "RUNNING" as AccountStatus, lastActive: "2m ago"  },
  { id: "4", username: "@jade_warmup_au",   region: "AU", os: "iOS 17.3",   warmupDay: "18", fbr7d: "1.2%", status: "WARMING" as AccountStatus, lastActive: "8m ago"  },
  { id: "5", username: "@swift_emma_us",    region: "US", os: "iOS 17.5",   warmupDay: "--", fbr7d: "4.4%", status: "RUNNING" as AccountStatus, lastActive: "5m ago"  },
  { id: "6", username: "@stella_fit_uk",    region: "UK", os: "Android 14", warmupDay: "7",  fbr7d: "0.8%", status: "WARMING" as AccountStatus, lastActive: "12m ago" },
  { id: "7", username: "@aria_content_ca",  region: "CA", os: "iOS 17.2",   warmupDay: "--", fbr7d: "3.6%", status: "RUNNING" as AccountStatus, lastActive: "4m ago"  },
  { id: "8", username: "@grace_daily_us",   region: "US", os: "Android 13", warmupDay: "--", fbr7d: "2.9%", status: "PAUSED"  as AccountStatus, lastActive: "2h ago"  },
];

const PLATFORM_COMPARISON = [
  { metric: "Follow-Back Rate",  tiktok: "4.2%",  ig: "11.2%", threads: "18.3%" },
  { metric: "Avg Views / Post",  tiktok: "8.4K",  ig: "3.1K",  threads: "2.8K"  },
  { metric: "Engagement Rate",   tiktok: "6.8%",  ig: "2.8%",  threads: "4.2%"  },
  { metric: "Comment Rate",      tiktok: "1.4%",  ig: "0.6%",  threads: "1.1%"  },
];

const GEO_DIST = [
  { label: "US", pct: 62, color: "bg-phantom-accent" },
  { label: "UK", pct: 18, color: "bg-phantom-amber"  },
  { label: "CA", pct: 11, color: "bg-blue-400"       },
  { label: "AU", pct:  9, color: "bg-purple-400"     },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TikTokCommandPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          TikTok · command center
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <Video className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            TikTok <span className="phantom-accent-text">Command</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-xs font-semibold">
            312 accounts live
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Mass TikTok account management — content scheduling, follow engine, engagement, and fleet health across all regions.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Active Accounts"     value="312"   delta={0.063}  sub="fleet-wide"            />
        <KPICard label="In Warmup"           value="89"    sub="45-day curve active"                  />
        <KPICard label="Avg FBR 7d"          value="4.2%"  delta={0.018}  sub="follow-back rate"      />
        <KPICard label="Content Scheduled"   value="847"   sub="posts in queue"        accent         />
      </div>

      {/* Live feed + account health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Live Activity Feed — 2/3 */}
        <div className="lg:col-span-2">
          <Panel label="real-time" title="Live Activity Feed">
            <div className="space-y-0.5">
              {LIVE_FEED.map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-center gap-3 py-2.5 border-b border-phantom-border/30 last:border-0 hover:bg-phantom-panelHi/30 rounded px-1 transition-colors"
                >
                  <span className={cn("w-2 h-2 rounded-full flex-shrink-0 animate-pulse", ACTION_COLORS[entry.type])} />
                  <span className="font-mono text-xs text-phantom-accent w-36 flex-shrink-0 truncate">{entry.account}</span>
                  <span className="text-xs text-white flex-1 truncate">{entry.action}</span>
                  <span className="text-[11px] text-phantom-ghost tabular-nums flex-shrink-0">{entry.ts}</span>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-3 mt-4 pt-4 border-t border-phantom-border/40">
              {(Object.entries(ACTION_COLORS) as [ActionType, string][]).map(([type, color]) => (
                <div key={type} className="flex items-center gap-1.5">
                  <span className={cn("w-2 h-2 rounded-full", color)} />
                  <span className="text-[11px] text-phantom-ghost capitalize">{type}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        {/* Geo distribution — 1/3 */}
        <div>
          <Panel label="geography" title="Geo Distribution">
            <div className="space-y-4">
              {GEO_DIST.map((g) => (
                <div key={g.label} className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-white">{g.label}</span>
                    <span className="tabular-nums text-phantom-ghost">{g.pct}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-phantom-border overflow-hidden">
                    <div className={cn("h-full rounded-full", g.color)} style={{ width: `${g.pct}%` }} />
                  </div>
                </div>
              ))}
              <div className="pt-2 text-[11px] text-phantom-ghost">
                Total: 312 accounts across 4 regions
              </div>
            </div>
          </Panel>
        </div>
      </div>

      {/* Account health table */}
      <Panel label="fleet health" title="Account Health Table">
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Account", "Region", "Device OS", "Warmup Day", "FBR 7d", "Status", "Last Active"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ACCOUNT_HEALTH.map((row) => {
                const s = STATUS_STYLES[row.status];
                return (
                  <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-3 font-mono text-xs text-phantom-accent">{row.username}</td>
                    <td className="px-3 py-3 text-xs text-white">{row.region}</td>
                    <td className="px-3 py-3 text-xs text-phantom-ghost">{row.os}</td>
                    <td className="px-3 py-3 text-xs tabular-nums text-center text-white">{row.warmupDay}</td>
                    <td className="px-3 py-3 text-xs tabular-nums text-white font-semibold">{row.fbr7d}</td>
                    <td className="px-3 py-3">
                      <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", s.bg, s.text, s.border)}>
                        {row.status}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-xs text-phantom-ghost tabular-nums">{row.lastActive}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Platform comparison */}
      <Panel label="benchmarks" title="Platform Comparison">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {PLATFORM_COMPARISON.map((row) => (
            <div key={row.metric} className="rounded-lg bg-phantom-panelHi border border-phantom-border p-4 space-y-3">
              <div className="text-[11px] uppercase tracking-[0.12em] text-phantom-ghost font-medium">{row.metric}</div>
              <div className="grid grid-cols-3 gap-1">
                {[
                  { label: "TikTok",   val: row.tiktok,  accent: true  },
                  { label: "IG",       val: row.ig,       accent: false },
                  { label: "Threads",  val: row.threads,  accent: false },
                ].map((p) => (
                  <div key={p.label} className="space-y-0.5">
                    <div className="text-[9px] text-phantom-ghost uppercase tracking-wider">{p.label}</div>
                    <div className={cn("text-base font-bold tabular-nums", p.accent ? "phantom-accent-text" : "text-white")}>
                      {p.val}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
