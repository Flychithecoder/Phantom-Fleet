"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Zap } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const TRENDING_HASHTAGS = [
  { tag: "#softlife",        volume: "42.1K", engRate: "5.8%", ourActions: 1_240, direction: "up"   },
  { tag: "#richgirlera",     volume: "38.7K", engRate: "5.2%", ourActions: 1_080, direction: "up"   },
  { tag: "#wellnesstok",     volume: "31.4K", engRate: "4.9%", ourActions: 890,   direction: "up"   },
  { tag: "#mindsetshift",    volume: "28.9K", engRate: "4.3%", ourActions: 760,   direction: "same" },
  { tag: "#feministfinance", volume: "24.2K", engRate: "6.1%", ourActions: 630,   direction: "up"   },
  { tag: "#morningperson",   volume: "19.8K", engRate: "3.7%", ourActions: 540,   direction: "down" },
  { tag: "#girlboss",        volume: "18.1K", engRate: "3.2%", ourActions: 480,   direction: "down" },
  { tag: "#aestheticlife",   volume: "15.6K", engRate: "4.5%", ourActions: 410,   direction: "up"   },
];

const ENGAGEMENT_FEED = [
  { ts: "4s ago",   account: "@tatiannalifee",   action: "liked + replied",           target: "@softlife.ceo",    result: "+12 profile visits"  },
  { ts: "9s ago",   account: "@melodierose_",    action: "liked + reposted",          target: "@richgirlera",     result: "+8 new follows"      },
  { ts: "16s ago",  account: "@emilyx.official", action: "full engagement",           target: "@wellness_daily",  result: "+21 profile visits"  },
  { ts: "24s ago",  account: "@brianna.cxo",     action: "liked",                     target: "@honest.thoughts", result: "+3 profile visits"   },
  { ts: "31s ago",  account: "@jasminne.vibes",  action: "liked + replied",           target: "@femme.finance",   result: "+9 new follows"      },
  { ts: "40s ago",  account: "@xo.claramae",     action: "full engagement",           target: "@morning_rituals", result: "+18 profile visits"  },
  { ts: "48s ago",  account: "@novalynne_fit",   action: "liked + reposted",          target: "@gym_culture",     result: "+6 new follows"      },
  { ts: "57s ago",  account: "@sierraglows",     action: "liked",                     target: "@lifestyle_queen", result: "+4 profile visits"   },
];

const DEPTH_DISTRIBUTION = [
  { label: "Like only",                   actions: "1 action",  count: 3_210, color: "bg-blue-400/60"   },
  { label: "Like + Reply",                actions: "2 actions", count: 2_840, color: "bg-purple-400/60" },
  { label: "Like + Repost",               actions: "2 actions", count: 1_680, color: "bg-orange-400/60" },
  { label: "Like + Reply + Repost",       actions: "3 actions", count: 690,   color: "bg-phantom-accent/80" },
];
const MAX_DEPTH = Math.max(...DEPTH_DISTRIBUTION.map((d) => d.count));

const TOP_NICHES = [
  { niche: "Mindset & Growth",   accounts: 312, engRate: "5.4%", color: "text-purple-400"   },
  { niche: "Finance & Wealth",   accounts: 284, engRate: "5.1%", color: "text-green-400"    },
  { niche: "Wellness & Health",  accounts: 241, engRate: "4.8%", color: "text-teal-400"     },
  { niche: "Lifestyle & Luxury", accounts: 198, engRate: "4.3%", color: "text-yellow-400"   },
  { niche: "Fitness",            accounts: 164, engRate: "3.9%", color: "text-orange-400"   },
  { niche: "Relationships",      accounts: 142, engRate: "4.6%", color: "text-pink-400"     },
];

const ALGO_NOTES = [
  "Threads rewards replies more than likes — aim for 2-action min engagement.",
  "Accounts that post daily get 2.3× more algorithmic distribution.",
  "Quote reposts create secondary reach loops — 1 quote = avg 3.2× original reach.",
  "Replying within 30 min of a thread posting puts you in 'early reply' boost window.",
  "Following 80–120 accounts/day signals healthy growth without triggering review.",
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function FeedEngagementPage() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Threads · feed engagement
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <Zap className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Feed <span className="phantom-accent-text">Engagement</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-xs font-semibold">
            8,420 threads hit today
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Deep engagement with trending threads — multi-action farming to maximize algorithmic surface area and explore reach.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Threads Engaged Today"   value="8,420"  delta={0.103}            />
        <KPICard label="Avg Engagement Depth"    value="3.2"    sub="actions per thread"  />
        <KPICard label="Trending Hashtags Hit"   value="47"     sub="today"               />
        <KPICard label="Explore Reach"           value="124K"   delta={0.187}             />
      </div>

      {/* Main + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main */}
        <div className="lg:col-span-2 space-y-6">
          {/* Trending hashtags */}
          <Panel label="trending" title="Trending Hashtags & Topics">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-phantom-border">
                    {["Hashtag", "Volume", "Eng Rate", "Our Actions", "Trend"].map((h) => (
                      <th
                        key={h}
                        className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-4 font-medium last:text-right last:pr-0"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-phantom-border/40">
                  {TRENDING_HASHTAGS.map((row) => (
                    <tr key={row.tag} className="hover:bg-phantom-panelHi/30 transition-colors">
                      <td className="py-3 pr-4 font-mono text-xs text-phantom-accent">{row.tag}</td>
                      <td className="py-3 pr-4 text-xs text-phantom-ghost tabular-nums">{row.volume}</td>
                      <td className="py-3 pr-4 text-xs font-semibold tabular-nums text-white">{row.engRate}</td>
                      <td className="py-3 pr-4 text-xs text-white tabular-nums font-mono">
                        {row.ourActions.toLocaleString()}
                      </td>
                      <td className="py-3 text-right text-base">
                        {row.direction === "up"   && <span className="text-phantom-alive">↑</span>}
                        {row.direction === "down" && <span className="text-red-400">↓</span>}
                        {row.direction === "same" && <span className="text-phantom-ghost">→</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {/* Engagement activity feed */}
          <Panel label="real-time" title="Engagement Activity Feed">
            <div className="space-y-0">
              {ENGAGEMENT_FEED.map((entry, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 py-3 border-b border-phantom-border/30 last:border-0 hover:bg-phantom-panelHi/20 rounded px-1 transition-colors"
                >
                  <span className="w-2 h-2 mt-1.5 rounded-full bg-cyan-400 flex-shrink-0 animate-pulse" />
                  <div className="flex-1 min-w-0 space-y-0.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs text-phantom-accent">{entry.account}</span>
                      <span
                        className={cn(
                          "px-1.5 py-0.5 rounded text-[10px] font-semibold",
                          entry.action === "full engagement"
                            ? "bg-phantom-accent/10 text-phantom-accent"
                            : "bg-phantom-panelHi text-phantom-ghost border border-phantom-border"
                        )}
                      >
                        {entry.action}
                      </span>
                      <span className="text-xs text-phantom-ghost">{entry.target}</span>
                    </div>
                    <span className="text-[11px] text-phantom-alive">{entry.result}</span>
                  </div>
                  <span className="text-[11px] text-phantom-ghost tabular-nums flex-shrink-0">{entry.ts}</span>
                </div>
              ))}
            </div>
          </Panel>

          {/* Engagement depth distribution */}
          <Panel label="depth analysis" title="Engagement Depth Distribution">
            <div className="space-y-3">
              {DEPTH_DISTRIBUTION.map((row) => (
                <div key={row.label} className="space-y-1.5">
                  <div className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-2">
                      <span className={cn("w-2 h-2 rounded-full", row.color)} />
                      <span className="text-white">{row.label}</span>
                      <span className="text-phantom-ghost">({row.actions})</span>
                    </div>
                    <span className="text-phantom-ghost tabular-nums">{row.count.toLocaleString()}</span>
                  </div>
                  <div className="h-2 rounded-full bg-phantom-border overflow-hidden">
                    <div
                      className={cn("h-full rounded-full", row.color)}
                      style={{ width: `${(row.count / MAX_DEPTH) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-4 border-t border-phantom-border/40 grid grid-cols-3 gap-4 text-center">
              <div>
                <div className="text-lg font-bold text-white tabular-nums">8,420</div>
                <div className="text-[11px] text-phantom-ghost">total threads</div>
              </div>
              <div>
                <div className="text-lg font-bold phantom-accent-text tabular-nums">3.2×</div>
                <div className="text-[11px] text-phantom-ghost">avg depth</div>
              </div>
              <div>
                <div className="text-lg font-bold text-purple-400 tabular-nums">690</div>
                <div className="text-[11px] text-phantom-ghost">full engagement</div>
              </div>
            </div>
          </Panel>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Top niches */}
          <Panel label="performance" title="Top Content Niches">
            <div className="space-y-3">
              {TOP_NICHES.map((n, i) => (
                <div key={i} className="space-y-1">
                  <div className="flex items-center justify-between">
                    <span className={cn("text-xs font-medium", n.color)}>{n.niche}</span>
                    <span className="text-xs text-phantom-alive tabular-nums font-semibold">{n.engRate}</span>
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-phantom-ghost">
                    <span>{n.accounts} accounts</span>
                  </div>
                  <div className="h-1 rounded-full bg-phantom-border overflow-hidden">
                    <div
                      className="h-full rounded-full bg-phantom-accent/50"
                      style={{ width: `${(n.accounts / 312) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          {/* Algo notes */}
          <Panel label="intel" title="Algorithm Notes">
            <div className="space-y-3">
              {ALGO_NOTES.map((note, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <span className="text-phantom-accent text-xs flex-shrink-0 mt-0.5">▸</span>
                  <p className="text-xs text-phantom-ghost leading-relaxed">{note}</p>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
