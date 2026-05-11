"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Repeat2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const TRACKED_CREATORS = [
  { creator: "@softlife.ceo",       followers: "284K", threadType: "Mindset",   repostsToday: 48,  reachBoost: "+320%", lastAction: "2min ago"  },
  { creator: "@richgirlera",        followers: "512K", threadType: "Finance",   repostsToday: 62,  reachBoost: "+410%", lastAction: "4min ago"  },
  { creator: "@wellness_daily",     followers: "198K", threadType: "Wellness",  repostsToday: 37,  reachBoost: "+240%", lastAction: "7min ago"  },
  { creator: "@femme.finance",      followers: "341K", threadType: "Finance",   repostsToday: 55,  reachBoost: "+370%", lastAction: "11min ago" },
  { creator: "@lifestyle_queen",    followers: "423K", threadType: "Lifestyle", repostsToday: 71,  reachBoost: "+490%", lastAction: "14min ago" },
  { creator: "@morning_rituals",    followers: "167K", threadType: "Wellness",  repostsToday: 29,  reachBoost: "+180%", lastAction: "18min ago" },
  { creator: "@honest.thoughts",    followers: "89K",  threadType: "Relatable", repostsToday: 22,  reachBoost: "+140%", lastAction: "23min ago" },
  { creator: "@gym_culture",        followers: "256K", threadType: "Fitness",   repostsToday: 44,  reachBoost: "+290%", lastAction: "28min ago" },
];

const REPOST_FEED = [
  { ts: "just now",  account: "@tatiannalifee",   creator: "@softlife.ceo",    thread: "the era of knowing your worth and acting accordingly" },
  { ts: "18s ago",   account: "@melodierose_",    creator: "@richgirlera",     thread: "daily habits of women who are quietly building wealth" },
  { ts: "34s ago",   account: "@emilyx.official", creator: "@wellness_daily",  thread: "your body keeps score. rest is not laziness." },
  { ts: "52s ago",   account: "@brianna.cxo",     creator: "@femme.finance",   thread: "3 money moves i made at 25 that changed everything" },
  { ts: "1m ago",    account: "@jasminne.vibes",  creator: "@lifestyle_queen", thread: "soft life is a mindset before it's a lifestyle" },
  { ts: "2m ago",    account: "@xo.claramae",     creator: "@softlife.ceo",    thread: "the version of you who isn't afraid of success" },
  { ts: "2m ago",    account: "@sierraglows",     creator: "@honest.thoughts", thread: "you can be kind and still have standards" },
];

type QuoteTone = "Hype" | "Agree" | "Preach" | "Facts" | "Needed";

const QUOTE_STYLES: Record<QuoteTone, { bg: string; text: string; border: string }> = {
  Hype:    { bg: "bg-orange-500/10",  text: "text-orange-400",  border: "border-orange-500/20"  },
  Agree:   { bg: "bg-teal-500/10",    text: "text-teal-400",    border: "border-teal-500/20"    },
  Preach:  { bg: "bg-purple-500/10",  text: "text-purple-400",  border: "border-purple-500/20"  },
  Facts:   { bg: "bg-blue-500/10",    text: "text-blue-400",    border: "border-blue-500/20"    },
  Needed:  { bg: "bg-green-500/10",   text: "text-green-400",   border: "border-green-500/20"   },
};

const QUOTE_TEMPLATES = [
  { id: 1, text: "this 👆",                                      tone: "Agree"   as QuoteTone, accounts: 102, reposts: 1_840 },
  { id: 2, text: "exactly what I needed to see today",           tone: "Needed"  as QuoteTone, accounts: 88,  reposts: 1_420 },
  { id: 3, text: "say it louder 🙏",                             tone: "Preach"  as QuoteTone, accounts: 95,  reposts: 1_690 },
  { id: 4, text: "not enough people are talking about this",     tone: "Hype"    as QuoteTone, accounts: 76,  reposts: 1_230 },
  { id: 5, text: "FACTS. no further questions.",                 tone: "Facts"   as QuoteTone, accounts: 84,  reposts: 1_380 },
  { id: 6, text: "bookmarking this and rereading it weekly 🤍",  tone: "Needed"  as QuoteTone, accounts: 91,  reposts: 1_510 },
  { id: 7, text: "the community needed this thread fr",          tone: "Preach"  as QuoteTone, accounts: 69,  reposts: 1_090 },
  { id: 8, text: "she said what she said 🔥",                    tone: "Hype"    as QuoteTone, accounts: 110, reposts: 2_010 },
];

// Hourly repost distribution — natural bell peaking 6pm-10pm (18:00–22:00)
const HOURLY_REPOSTS = [
  8, 5, 4, 3, 4, 7, 14, 28, 44, 52, 58, 61, 63, 64, 62, 58, 72, 88, 102, 110, 98, 74, 48, 22,
];
const MAX_HOURLY = Math.max(...HOURLY_REPOSTS);

// Top creators by repost performance
const TOP_CREATORS = [
  { creator: "@lifestyle_queen", reachBoost: "+490%", reposts: 71  },
  { creator: "@richgirlera",     reachBoost: "+410%", reposts: 62  },
  { creator: "@softlife.ceo",    reachBoost: "+320%", reposts: 48  },
  { creator: "@femme.finance",   reachBoost: "+370%", reposts: 55  },
  { creator: "@gym_culture",     reachBoost: "+290%", reposts: 44  },
];

function boostBadge(boost: string) {
  const val = parseInt(boost);
  if (val >= 400) return "bg-phantom-alive/10 border-phantom-alive/20 text-phantom-alive";
  if (val >= 250) return "bg-phantom-accent/10 border-phantom-accent/20 text-phantom-accent";
  return "bg-phantom-ghost/10 border-phantom-border text-phantom-ghost";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RepostsPage() {
  const [activeTab, setActiveTab] = useState<"feed" | "quotes">("feed");

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Threads · repost engine
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <Repeat2 className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Repost <span className="phantom-accent-text">Engine</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-xs font-semibold">
            1,230 reposts today
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Repost farming from high-performing creator accounts to compound algorithmic reach across the fleet.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Reposts Today"          value="1,230"  delta={0.094}           />
        <KPICard label="Reach Multiplier"       value="3.2×"   sub="avg per repost"    />
        <KPICard label="Quote Reposts"          value="340"    delta={0.071}           />
        <KPICard label="Creator Posts Tracked"  value="89"     sub="across 8 niches"  />
      </div>

      {/* Main + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main panel */}
        <div className="lg:col-span-2 space-y-6">
          {/* Creator table */}
          <Panel label="tracking" title="Tracked Creator Accounts">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-phantom-border">
                    {["Creator", "Followers", "Thread Type", "Reposts Today", "Reach Boost", "Last Action"].map((h) => (
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
                  {TRACKED_CREATORS.map((row) => (
                    <tr key={row.creator} className="hover:bg-phantom-panelHi/30 transition-colors">
                      <td className="py-3 pr-4 font-mono text-xs text-phantom-accent">{row.creator}</td>
                      <td className="py-3 pr-4 text-xs text-phantom-ghost tabular-nums">{row.followers}</td>
                      <td className="py-3 pr-4">
                        <span className="px-2 py-0.5 rounded bg-phantom-panelHi border border-phantom-border text-[10px] text-phantom-ghost">
                          {row.threadType}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-xs text-white tabular-nums font-mono">{row.repostsToday}</td>
                      <td className="py-3 pr-4">
                        <span className={cn("px-2 py-0.5 rounded-full border text-[10px] font-semibold", boostBadge(row.reachBoost))}>
                          {row.reachBoost}
                        </span>
                      </td>
                      <td className="py-3 text-right text-xs text-phantom-ghost tabular-nums">{row.lastAction}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {/* Tab: feed or quote templates */}
          <Panel
            label="activity"
            title={activeTab === "feed" ? "Repost Activity Feed" : "Quote Repost Templates"}
            actions={
              <div className="flex gap-1.5">
                {(["feed", "quotes"] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setActiveTab(t)}
                    className={cn(
                      "px-3 py-1 rounded text-xs font-medium border transition-all capitalize",
                      activeTab === t
                        ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                        : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                    )}
                  >
                    {t === "feed" ? "Live Feed" : "Quote Templates"}
                  </button>
                ))}
              </div>
            }
          >
            {activeTab === "feed" ? (
              <div className="space-y-0">
                {REPOST_FEED.map((entry, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-3 py-3 border-b border-phantom-border/30 last:border-0 hover:bg-phantom-panelHi/20 rounded px-1 transition-colors"
                  >
                    <span className="w-2 h-2 mt-1.5 rounded-full bg-orange-400 flex-shrink-0 animate-pulse" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-xs text-phantom-accent">{entry.account}</span>
                        <span className="text-xs text-phantom-ghost">reposted</span>
                        <span className="font-mono text-xs text-phantom-magenta">{entry.creator}</span>
                      </div>
                      <p className="text-xs text-phantom-ghost mt-0.5 truncate italic">
                        &ldquo;{entry.thread}&rdquo;
                      </p>
                    </div>
                    <span className="text-[11px] text-phantom-ghost tabular-nums flex-shrink-0">{entry.ts}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="columns-1 sm:columns-2 gap-4 space-y-4">
                {QUOTE_TEMPLATES.map((card) => {
                  const s = QUOTE_STYLES[card.tone];
                  return (
                    <div
                      key={card.id}
                      className="break-inside-avoid rounded-lg border border-phantom-border bg-phantom-panelHi p-4 space-y-3 hover:border-phantom-accent/30 transition-colors"
                    >
                      <p className="text-sm font-medium text-white leading-snug">{card.text}</p>
                      <div className="flex items-center justify-between gap-2">
                        <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-semibold border", s.bg, s.text, s.border)}>
                          {card.tone}
                        </span>
                        <div className="flex items-center gap-3 text-[11px] text-phantom-ghost">
                          <span>{card.accounts} accts</span>
                          <span className="text-phantom-accent tabular-nums">{card.reposts.toLocaleString()} reposts</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Hourly sparkline */}
          <Panel label="timing" title="Hourly Repost Distribution">
            <div className="flex items-end gap-0.5 h-24">
              {HOURLY_REPOSTS.map((val, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex-1 rounded-t transition-all",
                    i >= 18 && i <= 21
                      ? "bg-phantom-accent"
                      : "bg-phantom-accent/30 hover:bg-phantom-accent/60"
                  )}
                  style={{ height: `${(val / MAX_HOURLY) * 100}%` }}
                  title={`${i}:00 — ${val} reposts`}
                />
              ))}
            </div>
            <div className="flex justify-between text-[10px] text-phantom-ghost mt-2">
              <span>12am</span>
              <span className="text-phantom-accent">Peak 6–10pm</span>
              <span>11pm</span>
            </div>
          </Panel>

          {/* Top creators */}
          <Panel label="rankings" title="Top Creators by Performance">
            <div className="space-y-3">
              {TOP_CREATORS.map((c, i) => (
                <div key={i} className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[11px] text-phantom-ghost w-4 flex-shrink-0">#{i + 1}</span>
                    <span className="font-mono text-xs text-phantom-accent truncate">{c.creator}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-xs tabular-nums text-phantom-ghost">{c.reposts}</span>
                    <span className={cn("px-2 py-0.5 rounded-full border text-[10px] font-semibold", boostBadge(c.reachBoost))}>
                      {c.reachBoost}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
