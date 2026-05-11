"use client";

import { Panel } from "@/components/panel";
import { DataTable, Column } from "@/components/data-table";
import { Target } from "lucide-react";
import { cn } from "@/lib/utils";

type Source = {
  id: string;
  username: string;
  followers: number;
  engagement: number;
  score: number;
  tier: "premium" | "approved" | "rejected";
  state: string;
  discovered: string;
  lastScraped: string;
};

const SOURCES: Source[] = [
  { id: "1", username: "emilyaxoxo", followers: 128_400, engagement: 0.094, score: 94, tier: "premium", state: "NYC", discovered: "3d ago", lastScraped: "2h ago" },
  { id: "2", username: "bellajanemuse", followers: 87_200, engagement: 0.081, score: 91, tier: "premium", state: "Brooklyn", discovered: "5d ago", lastScraped: "4h ago" },
  { id: "3", username: "siennaxobaby", followers: 64_800, engagement: 0.073, score: 88, tier: "premium", state: "Miami FL", discovered: "2d ago", lastScraped: "1h ago" },
  { id: "4", username: "avaherworld", followers: 42_300, engagement: 0.068, score: 82, tier: "approved", state: "Austin TX", discovered: "1w ago", lastScraped: "5h ago" },
  { id: "5", username: "chloekissxo", followers: 58_100, engagement: 0.061, score: 79, tier: "approved", state: "LA", discovered: "1w ago", lastScraped: "3h ago" },
  { id: "6", username: "luna.sweetie", followers: 31_900, engagement: 0.054, score: 74, tier: "approved", state: "Chicago IL", discovered: "4d ago", lastScraped: "6h ago" },
  { id: "7", username: "ivybellexx", followers: 19_200, engagement: 0.049, score: 68, tier: "approved", state: "Boston MA", discovered: "2d ago", lastScraped: "12h ago" },
];

const sourceColumns: Column<Source>[] = [
  {
    key: "username",
    header: "Source",
    render: (r) => (
      <div>
        <div className="font-mono text-white text-sm">@{r.username}</div>
        <div className="text-[10px] text-phantom-ghost">{r.state}</div>
      </div>
    ),
  },
  {
    key: "followers",
    header: "Followers",
    align: "right",
    render: (r) => (
      <span className="font-mono tabular-nums">{(r.followers / 1000).toFixed(1)}k</span>
    ),
  },
  {
    key: "engagement",
    header: "Engagement",
    align: "right",
    render: (r) => (
      <span className="font-mono tabular-nums text-phantom-accent">
        {(r.engagement * 100).toFixed(1)}%
      </span>
    ),
  },
  {
    key: "score",
    header: "Score",
    align: "right",
    render: (r) => (
      <div className="flex items-center justify-end gap-2">
        <div className="w-16 h-1.5 rounded-full bg-phantom-panelHi overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full",
              r.score >= 85 && "bg-phantom-accent shadow-[0_0_8px_hsl(162_100%_54%/0.6)]",
              r.score >= 65 && r.score < 85 && "bg-phantom-alive",
              r.score < 65 && "bg-phantom-amber",
            )}
            style={{ width: `${r.score}%` }}
          />
        </div>
        <span className="font-mono tabular-nums text-sm w-6">{r.score}</span>
      </div>
    ),
  },
  {
    key: "tier",
    header: "Tier",
    render: (r) => (
      <span
        className={cn(
          "inline-flex px-2 py-0.5 rounded-md text-[10px] font-mono tracking-wider border",
          r.tier === "premium" && "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/30",
          r.tier === "approved" && "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/30",
          r.tier === "rejected" && "bg-phantom-red/10 text-phantom-red border-phantom-red/30",
        )}
      >
        {r.tier.toUpperCase()}
      </span>
    ),
  },
  {
    key: "lastScraped",
    header: "Last pull",
    render: (r) => <span className="text-xs text-phantom-ghost">{r.lastScraped}</span>,
  },
];

// ─── Competitor Source Tracker ────────────────────────────────────────────────

type CompetitorSource = {
  id: string;
  username: string;
  followers: number;
  engagementRate: number;
  weeklyFollowerGrowth: number;
  postsPerWeek: number;
  lastScraped: string;
  tracking: "active" | "paused";
  // 4-week follower growth data points (weekly snapshot, in thousands)
  growthTrend: number[];
};

const COMPETITOR_SOURCES: CompetitorSource[] = [
  {
    id: "cs1",
    username: "fitbabe_us",
    followers: 412_800,
    engagementRate: 0.087,
    weeklyFollowerGrowth: +4_200,
    postsPerWeek: 14,
    lastScraped: "1h ago",
    tracking: "active",
    growthTrend: [398, 402, 407, 413],
  },
  {
    id: "cs2",
    username: "glam.tatiana",
    followers: 289_400,
    engagementRate: 0.112,
    weeklyFollowerGrowth: +3_100,
    postsPerWeek: 18,
    lastScraped: "2h ago",
    tracking: "active",
    growthTrend: [271, 277, 283, 289],
  },
  {
    id: "cs3",
    username: "xoxo_lifewith_k",
    followers: 187_200,
    engagementRate: 0.094,
    weeklyFollowerGrowth: +1_900,
    postsPerWeek: 11,
    lastScraped: "3h ago",
    tracking: "active",
    growthTrend: [179, 182, 185, 187],
  },
  {
    id: "cs4",
    username: "brooklyn_babe_official",
    followers: 155_600,
    engagementRate: 0.078,
    weeklyFollowerGrowth: +2_400,
    postsPerWeek: 9,
    lastScraped: "2h ago",
    tracking: "active",
    growthTrend: [140, 146, 150, 156],
  },
  {
    id: "cs5",
    username: "sunsets.with.sara",
    followers: 134_100,
    engagementRate: 0.121,
    weeklyFollowerGrowth: +1_200,
    postsPerWeek: 7,
    lastScraped: "4h ago",
    tracking: "active",
    growthTrend: [129, 131, 133, 134],
  },
  {
    id: "cs6",
    username: "thats_so_mia",
    followers: 98_700,
    engagementRate: 0.068,
    weeklyFollowerGrowth: -400,
    postsPerWeek: 5,
    lastScraped: "5h ago",
    tracking: "paused",
    growthTrend: [101, 100, 99, 99],
  },
  {
    id: "cs7",
    username: "lavidalucy",
    followers: 76_300,
    engagementRate: 0.083,
    weeklyFollowerGrowth: +870,
    postsPerWeek: 12,
    lastScraped: "6h ago",
    tracking: "active",
    growthTrend: [72, 73, 75, 76],
  },
  {
    id: "cs8",
    username: "neonrose.diary",
    followers: 61_500,
    engagementRate: 0.097,
    weeklyFollowerGrowth: +1_100,
    postsPerWeek: 8,
    lastScraped: "7h ago",
    tracking: "active",
    growthTrend: [57, 59, 61, 62],
  },
];

// ─── Inline SVG Sparkline (no recharts) ──────────────────────────────────────

function MiniSparkline({
  data,
  color = "hsl(162 100% 54%)",
  width = 80,
  height = 28,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 2;
  const usableW = width - pad * 2;
  const usableH = height - pad * 2;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * usableW;
    const y = pad + (1 - (v - min) / range) * usableH;
    return `${x},${y}`;
  });

  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* End dot */}
      {points.length > 0 && (() => {
        const last = points[points.length - 1].split(",");
        return (
          <circle
            cx={parseFloat(last[0])}
            cy={parseFloat(last[1])}
            r={2.5}
            fill={color}
          />
        );
      })()}
    </svg>
  );
}

// ─── Pool size data for div-based line ───────────────────────────────────────

const POOL_HISTORY = [
  { week: "Mar 17", size: 298 },
  { week: "Mar 24", size: 312 },
  { week: "Mar 31", size: 329 },
  { week: "Apr 7",  size: 341 },
  { week: "Apr 13", size: 347 },
];

const competitorColumns: Column<CompetitorSource>[] = [
  {
    key: "username",
    header: "Username",
    render: (r) => (
      <div>
        <div className="font-mono text-white text-sm">@{r.username}</div>
      </div>
    ),
  },
  {
    key: "followers",
    header: "Followers",
    align: "right",
    render: (r) => (
      <span className="font-mono tabular-nums text-xs">{(r.followers / 1000).toFixed(1)}k</span>
    ),
  },
  {
    key: "engagementRate",
    header: "Engagement",
    align: "right",
    render: (r) => (
      <span className="font-mono tabular-nums text-xs text-phantom-accent">
        {(r.engagementRate * 100).toFixed(1)}%
      </span>
    ),
  },
  {
    key: "weeklyFollowerGrowth",
    header: "Wkly Growth",
    align: "right",
    render: (r) => (
      <span
        className={cn(
          "font-mono tabular-nums text-xs",
          r.weeklyFollowerGrowth >= 0 ? "text-phantom-alive" : "text-phantom-red",
        )}
      >
        {r.weeklyFollowerGrowth >= 0 ? "+" : ""}
        {(r.weeklyFollowerGrowth / 1000).toFixed(1)}k
      </span>
    ),
  },
  {
    key: "postsPerWeek",
    header: "Posts/Wk",
    align: "right",
    render: (r) => (
      <span className="font-mono tabular-nums text-xs">{r.postsPerWeek}</span>
    ),
  },
  {
    key: "growthTrend",
    header: "4-Wk Trend",
    render: (r) => (
      <MiniSparkline
        data={r.growthTrend}
        color={r.weeklyFollowerGrowth >= 0 ? "hsl(162 100% 54%)" : "hsl(0 84% 60%)"}
      />
    ),
  },
  {
    key: "lastScraped",
    header: "Last Scraped",
    render: (r) => <span className="text-xs text-phantom-ghost">{r.lastScraped}</span>,
  },
  {
    key: "tracking",
    header: "Status",
    render: (r) => (
      <span
        className={cn(
          "inline-flex px-2 py-0.5 rounded text-[9px] font-mono tracking-wider border",
          r.tracking === "active" && "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/30",
          r.tracking === "paused" && "bg-phantom-ghost/10 text-phantom-ghost border-phantom-ghost/20",
        )}
      >
        {r.tracking.toUpperCase()}
      </span>
    ),
  },
];

export default function TargetsPage() {
  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Targeting pipeline
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Target className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Fresh <span className="phantom-accent-text">Targets</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          No static pool. Fresh daily scraping from auto-discovered female US sources.
          Male target filter applied post-scrape. 90-day fleet-wide dedup. Zero cross-persona overlap.
        </p>
      </div>

      {/* Top stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">Fresh today</div>
          <div className="phantom-metric-lg mt-3">4,280</div>
          <div className="text-xs text-phantom-ghost mt-1">After 90d dedup + male filter</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">Raw scraped</div>
          <div className="phantom-metric-lg mt-3">14,620</div>
          <div className="text-xs text-phantom-ghost mt-1">~29% pass all filters</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">Approved sources</div>
          <div className="phantom-metric-lg mt-3 text-phantom-accent">347</div>
          <div className="text-xs text-phantom-ghost mt-1">42 premium · 305 approved</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">Follow-back ratio</div>
          <div className="phantom-metric-lg mt-3">24.8%</div>
          <div className="text-xs text-phantom-ghost mt-1">Last 7 days</div>
        </div>
      </div>

      <Panel
        label="source pool"
        title="Auto-discovered female US creators"
        subtitle="SourceDiscoveryAgent continuously expands this pool via IG 'similar accounts', follower-chain walks, and keyword search. Sources scoring >65 enter the pool, >85 become premium."
      >
        <DataTable columns={sourceColumns} rows={SOURCES} />
      </Panel>

      {/* ─── Competitor Source Tracker ─────────────────────────────────────── */}

      <Panel
        label="competitor intelligence"
        title="Competitor Source Tracker"
        subtitle="Top competitor accounts monitored for follower growth velocity, engagement trends, and content frequency. Used to identify high-yield target pools and benchmark against our own growth."
        actions={
          <div className="flex items-center gap-2">
            <button className="px-3 py-1.5 rounded-lg bg-phantom-accent/10 border border-phantom-accent/30 text-phantom-accent text-xs font-medium hover:bg-phantom-accent/20 transition-colors">
              + Add Source
            </button>
            <button className="px-3 py-1.5 rounded-lg bg-phantom-panelHi border border-phantom-border text-xs hover:border-phantom-ghost/40 transition-colors text-phantom-ghost">
              Pause All
            </button>
          </div>
        }
      >
        <DataTable columns={competitorColumns} rows={COMPETITOR_SOURCES} />
      </Panel>

      {/* ─── Source Pool Health ─────────────────────────────────────────────── */}

      <Panel
        label="pool health"
        title="Source Pool Health"
        subtitle="Pool size trends, weekly churn rate, and top performers by metric."
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Pool size over time */}
          <div className="lg:col-span-2 space-y-4">
            <div className="text-xs font-medium text-white">Pool size over 5 weeks</div>
            <div className="space-y-2">
              {POOL_HISTORY.map((w, i) => {
                const maxSize = Math.max(...POOL_HISTORY.map((p) => p.size));
                const pct = (w.size / maxSize) * 100;
                return (
                  <div key={w.week} className="flex items-center gap-3">
                    <span className="font-mono text-[10px] text-phantom-ghost w-14 flex-shrink-0">{w.week}</span>
                    <div className="flex-1 h-6 bg-phantom-panelHi rounded overflow-hidden relative">
                      <div
                        className={cn(
                          "h-full rounded transition-all",
                          i === POOL_HISTORY.length - 1
                            ? "bg-phantom-accent/30 border-r-2 border-phantom-accent"
                            : "bg-phantom-accent/15",
                        )}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="font-mono text-xs text-white tabular-nums w-8 text-right">{w.size}</span>
                  </div>
                );
              })}
            </div>
            {/* Weekly adds/removes */}
            <div className="grid grid-cols-2 gap-3 mt-4">
              <div className="p-3 rounded-lg bg-phantom-alive/5 border border-phantom-alive/20">
                <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">Added this week</div>
                <div className="font-mono text-xl font-bold text-phantom-alive mt-1">+14</div>
                <div className="text-[10px] text-phantom-ghost mt-0.5">New sources cleared threshold</div>
              </div>
              <div className="p-3 rounded-lg bg-phantom-red/5 border border-phantom-red/20">
                <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">Removed this week</div>
                <div className="font-mono text-xl font-bold text-phantom-red mt-1">-8</div>
                <div className="text-[10px] text-phantom-ghost mt-0.5">Score dropped below threshold</div>
              </div>
            </div>
          </div>

          {/* Top performers */}
          <div className="space-y-3">
            <div className="text-xs font-medium text-white mb-3">Top performers</div>

            <div className="p-3 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">By follower count</div>
              <div className="font-mono text-sm text-phantom-accent">@fitbabe_us</div>
              <div className="text-[10px] text-phantom-ghost mt-0.5">412.8k followers</div>
            </div>

            <div className="p-3 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">By engagement rate</div>
              <div className="font-mono text-sm text-phantom-accent">@sunsets.with.sara</div>
              <div className="text-[10px] text-phantom-ghost mt-0.5">12.1% engagement rate</div>
            </div>

            <div className="p-3 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">By discovery rate</div>
              <div className="font-mono text-sm text-phantom-accent">@glam.tatiana</div>
              <div className="text-[10px] text-phantom-ghost mt-0.5">+3.1k followers/week</div>
            </div>

            <div className="p-3 rounded-lg bg-phantom-panelHi/40 border border-phantom-border/50">
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">Pool health score</div>
              <div className="font-mono text-xl font-bold text-phantom-alive mt-0.5">92/100</div>
              <div className="text-[10px] text-phantom-ghost mt-0.5">7 active · 1 paused · 0 stale</div>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}
