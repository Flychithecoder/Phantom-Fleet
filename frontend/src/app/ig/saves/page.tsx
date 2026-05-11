"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Bookmark } from "lucide-react";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const CREATOR_POSTS = [
  { creator: "@creator_luna",   caption: "Morning routine that changed my life completely 🌅",  age: "2h",  saves: 312, reachBoost: "+340%" },
  { creator: "@astro_mia",      caption: "The secret ingredient is always love + turmeric latte", age: "4h",  saves: 189, reachBoost: "+180%" },
  { creator: "@nova_content",   caption: "POV: you finally unbothered and living your best era",  age: "6h",  saves: 247, reachBoost: "+240%" },
  { creator: "@aesthetic_glow", caption: "Skincare routine that took me from dry to glass skin",   age: "8h",  saves: 94,  reachBoost: "+90%" },
  { creator: "@swift_create",   caption: "5 habits that changed my relationship with money 💸",    age: "10h", saves: 401, reachBoost: "+420%" },
  { creator: "@jade_vibes",     caption: "Outfit formula that works for literally any body type",  age: "12h", saves: 156, reachBoost: "+150%" },
  { creator: "@grace_daily",    caption: "How I meal prep for the whole week in under 2 hours",    age: "14h", saves: 223, reachBoost: "+210%" },
  { creator: "@luna_lifestyle", caption: "The mindset shift that made everything easier fr fr",    age: "16h", saves: 178, reachBoost: "+170%" },
];

const SAVE_FEED = [
  { ts: "just now",  account: "@swift_emma_42",   creator: "@creator_luna",   dwell: "8s"  },
  { ts: "14s ago",   account: "@mia_fleet_01",     creator: "@astro_mia",      dwell: "11s" },
  { ts: "31s ago",   account: "@jade_glowup",      creator: "@swift_create",   dwell: "6s"  },
  { ts: "48s ago",   account: "@nova_fleet_07",    creator: "@nova_content",   dwell: "9s"  },
  { ts: "1min ago",  account: "@luna_aesthetic",   creator: "@jade_vibes",     dwell: "7s"  },
  { ts: "2min ago",  account: "@grace_fleet_13",   creator: "@grace_daily",    dwell: "12s" },
  { ts: "3min ago",  account: "@aria_content_02",  creator: "@creator_luna",   dwell: "5s"  },
  { ts: "4min ago",  account: "@stella_vibes",     creator: "@aesthetic_glow", dwell: "8s"  },
];

// 24h save sparkline — natural curve heavy 10am-8pm (indices 0-23)
const HOURLY_SAVES = [
  4, 3, 2, 2, 3, 5, 12, 28, 52, 78, 94, 102, 108, 112, 109, 101, 95, 84, 67, 48, 32, 18, 10, 6,
];
const MAX_HOURLY = Math.max(...HOURLY_SAVES);

function boostColor(boost: string) {
  const val = parseInt(boost);
  if (val >= 300) return "bg-phantom-alive/10 border-phantom-alive/20 text-phantom-alive";
  if (val >= 150) return "bg-phantom-accent/10 border-phantom-accent/20 text-phantom-accent";
  return "bg-phantom-ghost/10 border-phantom-border text-phantom-ghost";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SavesPage() {
  const [sortBy, setSortBy] = useState<"saves" | "boost">("saves");

  const sortedPosts = [...CREATOR_POSTS].sort((a, b) =>
    sortBy === "saves"
      ? b.saves - a.saves
      : parseInt(b.reachBoost) - parseInt(a.reachBoost)
  );

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Instagram · save farming
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <Bookmark className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Save <span className="phantom-accent-text">Farming</span>
          </h1>
          <span className="text-phantom-ghost text-sm">· 5× algorithm weight vs. likes</span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Fleet saves creator posts with realistic dwell times, triggering IG&apos;s highest-weighted engagement signal for maximum organic reach boost.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Saves Today" value="1,547" delta={0.124} />
        <KPICard label="Creator Posts Saved" value="312" sub="unique posts" />
        <KPICard label="Avg Saves Per Post" value="4.9" sub="per fleet account" />
        <KPICard label="Algorithm Boost Events" value="18" sub="posts pushed to Explore" accent />
      </div>

      {/* Main + side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Creator posts table — 2 cols */}
        <div className="lg:col-span-2">
          <Panel
            label="targets"
            title="Creator Posts Being Saved"
            actions={
              <div className="flex gap-1.5">
                {(["saves", "boost"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setSortBy(s)}
                    className={`px-3 py-1 rounded text-xs font-medium transition-all border capitalize ${
                      sortBy === s
                        ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                        : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-phantom-border">
                    <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Creator</th>
                    <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Post</th>
                    <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Age</th>
                    <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Saves</th>
                    <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Reach Boost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-phantom-border/40">
                  {sortedPosts.map((row) => (
                    <tr key={row.creator} className="hover:bg-phantom-panelHi/30 transition-colors">
                      <td className="py-3 font-mono text-xs text-phantom-accent whitespace-nowrap">{row.creator}</td>
                      <td className="py-3 text-xs text-phantom-ghost max-w-[180px]">
                        <span className="line-clamp-1">{row.caption}</span>
                      </td>
                      <td className="py-3 text-right text-xs text-phantom-ghost tabular-nums whitespace-nowrap">{row.age}</td>
                      <td className="py-3 text-right font-mono text-xs text-white tabular-nums">{row.saves}</td>
                      <td className="py-3 text-right">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-bold ${boostColor(row.reachBoost)}`}>
                          {row.reachBoost}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        {/* Save farming activity feed — 1 col */}
        <Panel label="live" title="Save Farming Activity">
          <div className="space-y-2">
            {SAVE_FEED.map((entry, i) => (
              <div
                key={i}
                className="px-3 py-2.5 rounded-lg bg-phantom-bg border border-phantom-border text-xs space-y-0.5 hover:border-phantom-accent/20 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="phantom-dot bg-phantom-accent animate-phantom-pulse shrink-0" />
                  <span className="text-phantom-ghost/60 font-mono">[{entry.ts}]</span>
                </div>
                <div className="text-phantom-ghost pl-4">
                  <span className="text-phantom-accent">{entry.account}</span>
                  {" saved post from "}
                  <span className="text-white">{entry.creator}</span>
                  {" · "}
                  <span className="text-phantom-alive">{entry.dwell} dwell time</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {/* Saves by hour sparkline */}
      <Panel label="distribution" title="Saves by Hour (24h)">
        <div className="space-y-2">
          <div className="flex items-end gap-1 h-24">
            {HOURLY_SAVES.map((val, hour) => {
              const heightPct = (val / MAX_HOURLY) * 100;
              return (
                <div key={hour} className="flex-1 flex flex-col items-center gap-1 group">
                  <div className="w-full flex items-end" style={{ height: "80px" }}>
                    <div
                      className="w-full rounded-t bg-phantom-accent/50 hover:bg-phantom-accent transition-colors"
                      style={{ height: `${heightPct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex justify-between text-[10px] text-phantom-ghost">
            <span>12am</span>
            <span>6am</span>
            <span>12pm</span>
            <span>6pm</span>
            <span>11pm</span>
          </div>
          <div className="text-[11px] text-phantom-ghost">
            Peak window: <span className="text-phantom-alive font-semibold">10am – 8pm</span> · natural activity curve
          </div>
        </div>
      </Panel>
    </div>
  );
}
