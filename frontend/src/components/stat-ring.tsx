"use client";

import { cn } from "@/lib/utils";

/**
 * Radial progress ring — used for health scores, engagement percentages,
 * completion ratios. Animated draw on mount.
 */
export function StatRing({
  value,             // 0..1
  label,
  sub,
  size = 140,
  strokeWidth = 10,
  color = "phantom-accent",
}: {
  value: number;
  label: string;
  sub?: string;
  size?: number;
  strokeWidth?: number;
  color?: "phantom-accent" | "phantom-alive" | "phantom-magenta" | "phantom-amber" | "phantom-red";
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference * (1 - Math.max(0, Math.min(1, value)));

  const colorClass: Record<typeof color, string> = {
    "phantom-accent": "stroke-phantom-accent drop-shadow-[0_0_8px_hsl(162_100%_54%/0.6)]",
    "phantom-alive": "stroke-phantom-alive drop-shadow-[0_0_8px_hsl(142_71%_45%/0.6)]",
    "phantom-magenta": "stroke-phantom-magenta drop-shadow-[0_0_8px_hsl(292_91%_68%/0.6)]",
    "phantom-amber": "stroke-phantom-amber drop-shadow-[0_0_8px_hsl(38_92%_58%/0.6)]",
    "phantom-red": "stroke-phantom-red drop-shadow-[0_0_8px_hsl(0_91%_65%/0.6)]",
  };

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: size, height: size }}>
        <svg className="-rotate-90" width={size} height={size}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            strokeWidth={strokeWidth}
            fill="none"
            className="stroke-phantom-panelHi"
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            strokeWidth={strokeWidth}
            fill="none"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            className={cn("transition-all duration-700 ease-out", colorClass[color])}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="phantom-metric text-3xl tabular-nums">
            {Math.round(value * 100)}
            <span className="text-sm text-phantom-ghost ml-0.5">%</span>
          </span>
          {sub && <span className="text-[10px] text-phantom-ghost mt-0.5">{sub}</span>}
        </div>
      </div>
      <div className="text-[11px] text-phantom-ghost uppercase tracking-[0.15em] mt-3 font-medium">
        {label}
      </div>
    </div>
  );
}
