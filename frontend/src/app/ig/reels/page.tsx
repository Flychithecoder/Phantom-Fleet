"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Film, Play } from "lucide-react";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const REEL_COLORS = [
  "from-pink-500/30 to-purple-500/30",
  "from-blue-500/30 to-teal-500/30",
  "from-orange-500/30 to-amber-500/30",
  "from-rose-500/30 to-pink-500/30",
  "from-indigo-500/30 to-blue-500/30",
  "from-teal-500/30 to-green-500/30",
];

const TRACKED_REELS = [
  { creator: "@creator_luna",   posted: "2h ago",  views: 8_240, watchThrough: 84.2, shares: 612, reach: "142K", gradient: REEL_COLORS[0] },
  { creator: "@astro_mia",      posted: "4h ago",  views: 6_180, watchThrough: 79.8, shares: 487, reach: "98K",  gradient: REEL_COLORS[1] },
  { creator: "@nova_content",   posted: "6h ago",  views: 9_440, watchThrough: 82.1, shares: 701, reach: "168K", gradient: REEL_COLORS[2] },
  { creator: "@aesthetic_glow", posted: "9h ago",  views: 5_320, watchThrough: 76.4, shares: 398, reach: "84K",  gradient: REEL_COLORS[3] },
  { creator: "@swift_create",   posted: "11h ago", views: 11_200, watchThrough: 88.7, shares: 934, reach: "210K", gradient: REEL_COLORS[4] },
  { creator: "@jade_vibes",     posted: "14h ago", views: 7_820, watchThrough: 81.0, shares: 543, reach: "126K", gradient: REEL_COLORS[5] },
];

// Bell-curve watch-through distribution centered around 80%
// Buckets: 0-10, 10-20, ..., 90-100
const WATCH_BUCKETS = [
  { label: "0–10%",   pct: 1.2 },
  { label: "10–20%",  pct: 2.8 },
  { label: "20–30%",  pct: 5.1 },
  { label: "30–40%",  pct: 8.4 },
  { label: "40–50%",  pct: 11.6 },
  { label: "50–60%",  pct: 14.9 },
  { label: "60–70%",  pct: 17.2 },
  { label: "70–80%",  pct: 18.8 },
  { label: "80–90%",  pct: 13.4 },
  { label: "90–100%", pct: 6.6  },
];
const MAX_BUCKET = Math.max(...WATCH_BUCKETS.map((b) => b.pct));

const FLEET_FEED = [
  { ts: "3min ago",  accounts: 847,  creator: "@creator_luna",   watchThrough: 82.1, rewatches: 169, shares: 68  },
  { ts: "8min ago",  accounts: 1_203, creator: "@swift_create",   watchThrough: 88.7, rewatches: 241, shares: 112 },
  { ts: "14min ago", accounts: 612,  creator: "@nova_content",   watchThrough: 80.4, rewatches: 127, shares: 54  },
  { ts: "22min ago", accounts: 934,  creator: "@astro_mia",      watchThrough: 79.8, rewatches: 198, shares: 87  },
  { ts: "35min ago", accounts: 728,  creator: "@jade_vibes",     watchThrough: 81.0, rewatches: 153, shares: 61  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ReelsPage() {
  const [sortBy, setSortBy] = useState<"views" | "watchThrough" | "shares">("views");

  const sortedReels = [...TRACKED_REELS].sort((a, b) => {
    if (sortBy === "views") return b.views - a.views;
    if (sortBy === "watchThrough") return b.watchThrough - a.watchThrough;
    return b.shares - a.shares;
  });

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Instagram · reel farming
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <Film className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Reel View <span className="phantom-accent-text">Farming</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-accent/10 border border-phantom-accent/20 text-phantom-accent text-xs font-semibold">
            2–3× organic reach multiplier
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Fleet accounts watch creator Reels with realistic watch-through patterns, rewatches, and story shares to trigger IG&apos;s Reel distribution algorithm.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Reel Views Today" value="48,200" delta={0.187} />
        <KPICard label="Avg Watch-Through" value="81.4%" sub="target: >75%" accent />
        <KPICard label="Rewatches (×2)" value="9,640" delta={0.143} />
        <KPICard label="Story Shares" value="3,856" delta={0.092} />
      </div>

      {/* Tracked reels table */}
      <Panel
        label="tracked reels"
        title="Tracked Creator Reels"
        actions={
          <div className="flex gap-1.5">
            {(["views", "watchThrough", "shares"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSortBy(s)}
                className={`px-3 py-1 rounded text-xs font-medium transition-all border ${
                  sortBy === s
                    ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                    : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                }`}
              >
                {s === "watchThrough" ? "watch%" : s}
              </button>
            ))}
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Preview</th>
                <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Creator</th>
                <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Posted</th>
                <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Views</th>
                <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Watch%</th>
                <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Story Shares</th>
                <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Reach Est.</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-phantom-border/40">
              {sortedReels.map((row) => (
                <tr key={row.creator} className="hover:bg-phantom-panelHi/30 transition-colors">
                  <td className="py-3">
                    <div className={`w-10 h-14 rounded-md bg-gradient-to-br ${row.gradient} border border-phantom-border flex items-center justify-center`}>
                      <Play className="w-4 h-4 text-white/70" strokeWidth={1.5} />
                    </div>
                  </td>
                  <td className="py-3 font-mono text-xs text-phantom-accent">{row.creator}</td>
                  <td className="py-3 text-right text-xs text-phantom-ghost tabular-nums whitespace-nowrap">{row.posted}</td>
                  <td className="py-3 text-right font-mono text-xs text-white tabular-nums">{row.views.toLocaleString()}</td>
                  <td className="py-3 text-right">
                    <span className={`font-mono text-xs tabular-nums font-semibold ${row.watchThrough >= 80 ? "text-phantom-alive" : "text-phantom-accent"}`}>
                      {row.watchThrough}%
                    </span>
                  </td>
                  <td className="py-3 text-right font-mono text-xs text-phantom-ghost tabular-nums">{row.shares.toLocaleString()}</td>
                  <td className="py-3 text-right font-mono text-xs text-phantom-accent tabular-nums">{row.reach}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Two columns: histogram + fleet feed */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Watch-through distribution */}
        <Panel label="distribution" title="Watch-Through Distribution">
          <p className="text-[11px] text-phantom-ghost mb-4">
            % of views at each 10% completion bucket — bell curve centered ~80%
          </p>
          <div className="space-y-2">
            {WATCH_BUCKETS.map((bucket) => (
              <div key={bucket.label} className="flex items-center gap-3">
                <span className="text-[11px] text-phantom-ghost font-mono w-16 shrink-0">{bucket.label}</span>
                <div className="flex-1 h-5 bg-phantom-border/40 rounded overflow-hidden relative">
                  <div
                    className="h-full rounded bg-phantom-accent/70"
                    style={{ width: `${(bucket.pct / MAX_BUCKET) * 100}%` }}
                  />
                </div>
                <span className="text-[11px] text-phantom-ghost tabular-nums w-10 text-right shrink-0">{bucket.pct}%</span>
              </div>
            ))}
          </div>
          <div className="mt-4 text-[11px] text-phantom-ghost">
            Natural bell curve · peak at <span className="text-phantom-alive font-semibold">70–80%</span> bucket
          </div>
        </Panel>

        {/* Fleet activity feed */}
        <Panel label="live fleet" title="Fleet Activity">
          <div className="space-y-3">
            {FLEET_FEED.map((entry, i) => (
              <div
                key={i}
                className="p-4 rounded-lg bg-phantom-bg border border-phantom-border hover:border-phantom-accent/20 transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="phantom-dot bg-phantom-accent animate-phantom-pulse" />
                  <span className="text-[10px] text-phantom-ghost/60 font-mono">[{entry.ts}]</span>
                </div>
                <p className="text-xs text-phantom-ghost leading-relaxed">
                  <span className="text-phantom-alive font-semibold">{entry.accounts.toLocaleString()} accounts</span>
                  {" watched "}
                  <span className="text-phantom-accent">{entry.creator}</span>
                  {" Reel · "}
                  <span className="text-white">{entry.watchThrough}% avg watch-through</span>
                  {" · "}
                  <span className="text-phantom-ghost">{entry.rewatches} rewatches</span>
                  {" · "}
                  <span className="text-phantom-ghost">{entry.shares} story shares queued</span>
                </p>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
