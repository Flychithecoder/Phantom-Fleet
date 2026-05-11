"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { MessageCircle } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types & mock data
// ---------------------------------------------------------------------------

type ActionType = "follow" | "like" | "reply" | "repost" | "post";

const ACTION_COLORS: Record<ActionType, string> = {
  follow:  "bg-green-400",
  like:    "bg-blue-400",
  reply:   "bg-purple-400",
  repost:  "bg-orange-400",
  post:    "bg-cyan-400",
};

const ACTIVITY_FEED: {
  id: number;
  account: string;
  action: string;
  type: ActionType;
  ts: string;
}[] = [
  { id: 1,  account: "@tatiannalifee",     action: "followed @fitness_motivation",         type: "follow",  ts: "2s ago"  },
  { id: 2,  account: "@melodierose_",      action: "liked thread by @gym_culture",          type: "like",    ts: "5s ago"  },
  { id: 3,  account: "@emilyx.official",   action: "replied to @wellness_daily",            type: "reply",   ts: "8s ago"  },
  { id: 4,  account: "@brianna.cxo",       action: "reposted thread from @lifestyle_queen", type: "repost",  ts: "11s ago" },
  { id: 5,  account: "@jasminne.vibes",    action: "posted new thread",                     type: "post",    ts: "14s ago" },
  { id: 6,  account: "@xo.claramae",       action: "followed @morning_rituals",             type: "follow",  ts: "18s ago" },
  { id: 7,  account: "@novalynne_fit",     action: "liked thread by @mindset_shift",        type: "like",    ts: "23s ago" },
  { id: 8,  account: "@sierraglows",       action: "replied to @honest.thoughts",           type: "reply",   ts: "29s ago" },
  { id: 9,  account: "@kali.aesthetics",   action: "reposted thread from @softlife.ceo",    type: "repost",  ts: "34s ago" },
  { id: 10, account: "@tatiannalifee",     action: "posted new thread",                     type: "post",    ts: "38s ago" },
  { id: 11, account: "@remi.blossoms",     action: "followed @femme.finance",               type: "follow",  ts: "43s ago" },
  { id: 12, account: "@melodierose_",      action: "liked thread by @dailymotivation",      type: "like",    ts: "48s ago" },
  { id: 13, account: "@emilyx.official",   action: "replied to @growth_mindset_ig",         type: "reply",   ts: "54s ago" },
  { id: 14, account: "@brianna.cxo",       action: "reposted thread from @richgirlera",     type: "repost",  ts: "1m ago"  },
  { id: 15, account: "@jasminne.vibes",    action: "followed @luxe.living.co",              type: "follow",  ts: "1m ago"  },
];

type AccountStatus = "RUNNING" | "PAUSED" | "WARMING";

const STATUS_STYLES: Record<AccountStatus, { bg: string; text: string; border: string }> = {
  RUNNING: { bg: "bg-phantom-alive/10",  text: "text-phantom-alive",  border: "border-phantom-alive/20"  },
  PAUSED:  { bg: "bg-yellow-500/10",     text: "text-yellow-400",     border: "border-yellow-500/20"     },
  WARMING: { bg: "bg-blue-500/10",       text: "text-blue-400",       border: "border-blue-500/20"       },
};

const ACCOUNT_HEALTH = [
  { username: "@tatiannalifee",   status: "RUNNING" as AccountStatus, threadsToday: 4,  followsToday: 120, quotaUsed: 82 },
  { username: "@melodierose_",    status: "RUNNING" as AccountStatus, threadsToday: 3,  followsToday: 98,  quotaUsed: 71 },
  { username: "@emilyx.official", status: "PAUSED"  as AccountStatus, threadsToday: 0,  followsToday: 0,   quotaUsed: 34 },
  { username: "@brianna.cxo",     status: "RUNNING" as AccountStatus, threadsToday: 5,  followsToday: 145, quotaUsed: 90 },
  { username: "@jasminne.vibes",  status: "WARMING" as AccountStatus, threadsToday: 1,  followsToday: 40,  quotaUsed: 22 },
  { username: "@xo.claramae",     status: "RUNNING" as AccountStatus, threadsToday: 3,  followsToday: 112, quotaUsed: 67 },
  { username: "@novalynne_fit",   status: "WARMING" as AccountStatus, threadsToday: 2,  followsToday: 55,  quotaUsed: 18 },
  { username: "@sierraglows",     status: "RUNNING" as AccountStatus, threadsToday: 4,  followsToday: 130, quotaUsed: 78 },
];

const PLATFORM_COMPARISON = [
  { metric: "Follow-Back Rate",  threads: "18.3%", ig: "11.2%" },
  { metric: "Engagement Rate",   threads: "4.2%",  ig: "2.8%"  },
  { metric: "Explore Reach",     threads: "124K",  ig: "89K"   },
  { metric: "DM Conversion",     threads: "2.1%",  ig: "1.4%"  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ThreadsCommandPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Threads · command center
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <MessageCircle className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Threads <span className="phantom-accent-text">Command</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-xs font-semibold">
            847 accounts live
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Cross-account Threads automation at fleet scale — follows, replies, reposts, and feed engagement.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <KPICard label="Active Accounts"       value="847"    sub="fleet-wide"          />
        <KPICard label="Threads Posted Today"  value="2,340"  delta={0.124}             />
        <KPICard label="Replies Sent"          value="5,810"  delta={0.087}             />
        <KPICard label="Reposts"               value="1,230"  sub="today"               />
        <KPICard label="New Follows"           value="4,200"  delta={0.091}             />
        <KPICard label="Follow-Back Rate"      value="18.3%"  sub="vs 11.2% IG"         />
      </div>

      {/* Main two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Live Activity Feed — 2/3 */}
        <div className="lg:col-span-2">
          <Panel label="real-time" title="Live Activity Feed">
            <div className="space-y-1">
              {ACTIVITY_FEED.map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-center gap-3 py-2.5 border-b border-phantom-border/30 last:border-0 hover:bg-phantom-panelHi/30 rounded px-1 transition-colors"
                >
                  <span
                    className={cn(
                      "w-2 h-2 rounded-full flex-shrink-0 animate-pulse",
                      ACTION_COLORS[entry.type]
                    )}
                  />
                  <span className="font-mono text-xs text-phantom-accent w-36 flex-shrink-0 truncate">
                    {entry.account}
                  </span>
                  <span className="text-xs text-white flex-1 truncate">{entry.action}</span>
                  <span className="text-[11px] text-phantom-ghost tabular-nums flex-shrink-0">
                    {entry.ts}
                  </span>
                </div>
              ))}
            </div>
            {/* Legend */}
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

        {/* Account Health — 1/3 */}
        <div>
          <Panel label="fleet" title="Account Health">
            <div className="space-y-4">
              {ACCOUNT_HEALTH.map((acct) => {
                const s = STATUS_STYLES[acct.status];
                return (
                  <div key={acct.username} className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-phantom-accent truncate">
                        {acct.username}
                      </span>
                      <span
                        className={cn(
                          "px-2 py-0.5 rounded-full text-[10px] font-bold border",
                          s.bg, s.text, s.border
                        )}
                      >
                        {acct.status}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-phantom-ghost">
                      <span>{acct.threadsToday} threads</span>
                      <span>{acct.followsToday} follows</span>
                      <span className="tabular-nums">{acct.quotaUsed}% quota</span>
                    </div>
                    <div className="h-1 rounded-full bg-phantom-border overflow-hidden">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all",
                          acct.quotaUsed >= 85 ? "bg-phantom-amber" : "bg-phantom-accent"
                        )}
                        style={{ width: `${acct.quotaUsed}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>
      </div>

      {/* Platform Comparison */}
      <Panel label="benchmarks" title="Threads vs Instagram">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {PLATFORM_COMPARISON.map((row) => (
            <div
              key={row.metric}
              className="rounded-lg bg-phantom-panelHi border border-phantom-border p-4 space-y-3"
            >
              <div className="text-[11px] uppercase tracking-[0.12em] text-phantom-ghost font-medium">
                {row.metric}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <div className="text-[10px] text-phantom-ghost">Threads</div>
                  <div className="text-lg font-bold phantom-accent-text tabular-nums">
                    {row.threads}
                  </div>
                </div>
                <div className="space-y-1">
                  <div className="text-[10px] text-phantom-ghost">Instagram</div>
                  <div className="text-lg font-bold text-white tabular-nums">{row.ig}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
