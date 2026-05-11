"use client";

import { cn } from "@/lib/utils";

/**
 * Horizontal funnel visualization — shows conversion from reach → profile visit
 * → follow → DM → click → subscribe, each stage narrower than the last.
 */
export function FunnelViz({
  stages,
}: {
  stages: Array<{ label: string; count: number; color?: string }>;
}) {
  const max = Math.max(...stages.map((s) => s.count), 1);
  return (
    <div className="space-y-3">
      {stages.map((stage, i) => {
        const pct = stage.count / max;
        const retention = i === 0 ? 1 : stage.count / stages[0].count;
        return (
          <div key={stage.label} className="relative">
            <div className="flex items-baseline justify-between mb-1.5">
              <span className="text-xs text-phantom-ghost">{stage.label}</span>
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-sm tabular-nums text-white">
                  {stage.count.toLocaleString()}
                </span>
                <span className="font-mono text-[10px] text-phantom-accent tabular-nums">
                  {(retention * 100).toFixed(1)}%
                </span>
              </div>
            </div>
            <div className="h-6 rounded-md bg-phantom-panelHi/50 overflow-hidden relative">
              <div
                className={cn(
                  "h-full rounded-md transition-all duration-700",
                  stage.color || "bg-gradient-to-r from-phantom-accent to-phantom-magenta",
                )}
                style={{
                  width: `${pct * 100}%`,
                  boxShadow: `0 0 16px ${stage.color || "hsl(162 100% 54% / 0.3)"}`,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
