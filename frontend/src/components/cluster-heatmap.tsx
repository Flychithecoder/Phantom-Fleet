"use client";

import { cn } from "@/lib/utils";
import { ShieldCheck } from "lucide-react";

/**
 * Live fingerprint cluster heatmap — 20 fingerprint dimensions, each
 * scored 0-1 where 0 = fully diverse (safe) and 1 = fully clustered (critical).
 * This is Phantom Fleet's moat. Onimator has zero of this.
 */

const DIMENSIONS = [
  { name: "Device model",       score: 0.18 },
  { name: "Android version",    score: 0.22 },
  { name: "Locale",             score: 0.08 },
  { name: "Timezone",           score: 0.11 },
  { name: "Tap dwell",          score: 0.14 },
  { name: "Keystroke cadence",  score: 0.16 },
  { name: "Scroll velocity",    score: 0.12 },
  { name: "Session length",     score: 0.09 },
  { name: "Inter-session gap",  score: 0.15 },
  { name: "Diurnal curve",      score: 0.07 },
  { name: "Action type mix",    score: 0.13 },
  { name: "Follow-back ratio",  score: 0.31 }, // slightly elevated
  { name: "Content pool",       score: 0.10 },
  { name: "Caption voice",      score: 0.06 },
  { name: "Target source mix",  score: 0.19 },
  { name: "Proxy geo spread",   score: 0.17 },
  { name: "JA3/JA4 TLS",        score: 0.24 },
  { name: "Battery curve",      score: 0.20 },
  { name: "Installed apps",     score: 0.13 },
  { name: "Sensor jitter",      score: 0.11 },
];

function scoreColor(s: number) {
  // 0 → phantom-alive, 0.5 → amber, 1 → red
  if (s < 0.25) return "bg-phantom-alive/80 shadow-[0_0_12px_hsl(142_71%_45%/0.4)]";
  if (s < 0.5) return "bg-phantom-accent/80 shadow-[0_0_12px_hsl(162_100%_54%/0.4)]";
  if (s < 0.75) return "bg-phantom-amber/80 shadow-[0_0_12px_hsl(38_92%_58%/0.4)]";
  return "bg-phantom-red/80 shadow-[0_0_12px_hsl(0_91%_65%/0.4)]";
}

export function ClusterHeatmap() {
  const maxScore = Math.max(...DIMENSIONS.map((d) => d.score));
  return (
    <div className="phantom-panel p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Cluster monitor · live
          </div>
          <div className="text-lg font-display font-semibold mt-1 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-phantom-alive" strokeWidth={1.75} />
            Fleet fingerprint health
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] text-phantom-ghost">Max dim score</div>
          <div className={cn(
            "font-display font-bold text-2xl tabular-nums",
            maxScore < 0.25 && "text-phantom-alive",
            maxScore >= 0.25 && maxScore < 0.5 && "text-phantom-accent",
            maxScore >= 0.5 && maxScore < 0.75 && "text-phantom-amber",
            maxScore >= 0.75 && "text-phantom-red",
          )}>
            {maxScore.toFixed(2)}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {DIMENSIONS.map((d) => (
          <div key={d.name} className="group">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] text-phantom-ghost">{d.name}</span>
              <span className="text-[11px] font-mono tabular-nums text-phantom-ghost">
                {d.score.toFixed(2)}
              </span>
            </div>
            <div className="h-2 rounded-full bg-phantom-panelHi overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", scoreColor(d.score))}
                style={{ width: `${d.score * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-6 pt-5 border-t border-phantom-border flex items-center justify-between text-xs text-phantom-ghost">
        <span>10,000-persona Monte Carlo runs nightly · last pass: 2h ago ✓</span>
        <span>Next scan: 4m 12s</span>
      </div>
    </div>
  );
}
