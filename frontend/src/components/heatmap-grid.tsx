"use client";

import { cn } from "@/lib/utils";

/**
 * Cohort × metric heatmap — used on the Analytics page to show cohort-wise
 * survival rates, conversion rates, or action density.
 */
export function HeatmapGrid({
  xLabels,
  yLabels,
  data,         // data[y][x] = 0..1
  cellSize = 28,
}: {
  xLabels: string[];
  yLabels: string[];
  data: number[][];
  cellSize?: number;
}) {
  const colorFor = (v: number) => {
    if (v >= 0.8) return "bg-phantom-alive shadow-[0_0_10px_hsl(142_71%_45%/0.5)]";
    if (v >= 0.6) return "bg-phantom-accent shadow-[0_0_10px_hsl(162_100%_54%/0.5)]";
    if (v >= 0.4) return "bg-phantom-amber shadow-[0_0_10px_hsl(38_92%_58%/0.5)]";
    if (v >= 0.2) return "bg-phantom-red/60";
    return "bg-phantom-panelHi";
  };
  return (
    <div className="overflow-x-auto">
      <table>
        <thead>
          <tr>
            <th />
            {xLabels.map((x) => (
              <th key={x} className="text-[9px] text-phantom-ghost font-medium px-1 pb-2">
                {x}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {yLabels.map((y, yi) => (
            <tr key={y}>
              <td className="text-[11px] text-phantom-ghost pr-3 text-right whitespace-nowrap">{y}</td>
              {xLabels.map((_, xi) => {
                const v = data[yi]?.[xi] ?? 0;
                return (
                  <td key={xi} className="p-0.5">
                    <div
                      className={cn("rounded-sm transition-all hover:scale-110 cursor-pointer", colorFor(v))}
                      style={{ width: cellSize, height: cellSize, opacity: 0.3 + v * 0.7 }}
                      title={`${(v * 100).toFixed(0)}%`}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
