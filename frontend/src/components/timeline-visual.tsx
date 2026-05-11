"use client";

import { cn } from "@/lib/utils";

type PlatformSlot = {
  platform: string;
  shortCode: string;
  color: string;
  hours: number[]; // active hours (0-23)
  proxy?: string;
};

const PLATFORM_SLOTS: PlatformSlot[] = [
  {
    platform: "LinkedIn",
    shortCode: "LI",
    color: "hsl(201 100% 38%)",
    hours: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
    proxy: "DC Residential",
  },
  {
    platform: "Reddit",
    shortCode: "RD",
    color: "hsl(18 100% 55%)",
    hours: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21],
    proxy: "Mobile 4G",
  },
  {
    platform: "X / Twitter",
    shortCode: "X",
    color: "hsl(0 0% 85%)",
    hours: [7, 8, 9, 10, 11, 18, 19, 20, 21, 22],
    proxy: "Mobile 4G",
  },
  {
    platform: "Instagram",
    shortCode: "IG",
    color: "hsl(292 91% 68%)",
    hours: [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21],
    proxy: "Mobile 4G",
  },
  {
    platform: "Threads",
    shortCode: "TH",
    color: "hsl(0 0% 70%)",
    hours: [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
    proxy: "Mobile 4G",
  },
  {
    platform: "TikTok",
    shortCode: "TT",
    color: "hsl(180 100% 55%)",
    hours: [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
    proxy: "Mobile 4G",
  },
  {
    platform: "Discord",
    shortCode: "DC",
    color: "hsl(235 86% 65%)",
    hours: [15, 16, 17, 18, 19, 20, 21, 22, 23],
    proxy: "Residential",
  },
  {
    platform: "Telegram",
    shortCode: "TG",
    color: "hsl(200 100% 56%)",
    hours: [7, 8, 9, 17, 18, 19, 20, 21, 22, 23],
    proxy: "Mobile 4G",
  },
  {
    platform: "Dating Apps",
    shortCode: "DA",
    color: "hsl(348 100% 60%)",
    hours: [18, 19, 20, 21, 22, 23],
    proxy: "Mobile 4G",
  },
  {
    platform: "BlueSky",
    shortCode: "BS",
    color: "hsl(212 100% 58%)",
    hours: [10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
    proxy: "Residential",
  },
];

const QUIET_HOURS = [0, 1, 2, 3, 4, 5, 6];

const HOUR_LABELS = [
  "12a", "1a", "2a", "3a", "4a", "5a", "6a",
  "7a", "8a", "9a", "10a", "11a", "12p",
  "1p", "2p", "3p", "4p", "5p", "6p",
  "7p", "8p", "9p", "10p", "11p",
];

export function TimelineVisual({ className }: { className?: string }) {
  return (
    <div className={cn("phantom-panel p-6 overflow-x-auto", className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-mono mb-1">
            24-Hour Fleet Cycle
          </div>
          <div className="font-display font-semibold text-sm">
            Proxy multiplexing by platform and time of day
          </div>
        </div>
        <div className="flex items-center gap-4 text-[10px] font-mono text-phantom-ghost">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-sm bg-phantom-panelHi border border-phantom-border opacity-40" />
            Quiet (2a–6a)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-sm bg-phantom-accent/30 border border-phantom-accent/50" />
            Active window
          </span>
        </div>
      </div>

      {/* Timeline grid */}
      <div className="min-w-[640px]">
        {/* Hour labels */}
        <div className="flex mb-2" style={{ paddingLeft: "7rem" }}>
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={h}
              className={cn(
                "flex-1 text-center text-[9px] font-mono",
                QUIET_HOURS.includes(h) ? "text-phantom-ghost/30" : "text-phantom-ghost/60"
              )}
            >
              {h % 3 === 0 ? HOUR_LABELS[h] : ""}
            </div>
          ))}
        </div>

        {/* Platform rows */}
        <div className="space-y-1.5">
          {PLATFORM_SLOTS.map((p) => (
            <div key={p.platform} className="flex items-center gap-0">
              {/* Label */}
              <div className="w-28 shrink-0 pr-3 text-right">
                <div className="text-xs font-display font-medium" style={{ color: p.color }}>
                  {p.shortCode}
                </div>
                <div className="text-[9px] text-phantom-ghost/50 font-mono leading-tight">
                  {p.proxy}
                </div>
              </div>

              {/* Hour cells */}
              {Array.from({ length: 24 }, (_, h) => {
                const isActive = p.hours.includes(h);
                const isQuiet = QUIET_HOURS.includes(h);
                const isFirst = isActive && !p.hours.includes(h - 1);
                const isLast = isActive && !p.hours.includes(h + 1);
                return (
                  <div
                    key={h}
                    title={`${p.platform} — ${HOUR_LABELS[h]}`}
                    className={cn(
                      "flex-1 h-7 transition-colors",
                      isQuiet && !isActive && "bg-phantom-bg/40",
                      !isActive && !isQuiet && "bg-phantom-panelHi/30",
                      isActive && "opacity-80 hover:opacity-100",
                      isFirst && "rounded-l-md",
                      isLast && "rounded-r-md"
                    )}
                    style={
                      isActive
                        ? {
                            backgroundColor: `${p.color}28`,
                            borderTop: `1px solid ${p.color}50`,
                            borderBottom: `1px solid ${p.color}50`,
                            ...(isFirst
                              ? { borderLeft: `1px solid ${p.color}50` }
                              : {}),
                            ...(isLast
                              ? { borderRight: `1px solid ${p.color}50` }
                              : {}),
                          }
                        : undefined
                    }
                  />
                );
              })}
            </div>
          ))}
        </div>

        {/* Quiet zone annotation */}
        <div className="flex mt-3" style={{ paddingLeft: "7rem" }}>
          {Array.from({ length: 24 }, (_, h) => (
            <div key={h} className="flex-1">
              {h === 2 && (
                <div className="text-[9px] font-mono text-phantom-ghost/40 whitespace-nowrap">
                  quiet zone
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Peak windows annotation */}
        <div className="flex mt-1" style={{ paddingLeft: "7rem" }}>
          {Array.from({ length: 24 }, (_, h) => (
            <div key={h} className="flex-1">
              {h === 9 && (
                <div className="text-[9px] font-mono text-phantom-accent/60 whitespace-nowrap">
                  morning peak
                </div>
              )}
              {h === 18 && (
                <div className="text-[9px] font-mono text-phantom-accent/60 whitespace-nowrap">
                  evening peak
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Footer note */}
      <div className="mt-6 pt-4 border-t border-phantom-border text-[10px] text-phantom-ghost font-mono">
        Windows are defaults. Capacity Planner AI adjusts per proxy tier, timezone cohort, and
        platform activity curves. All hours local to account geography.
      </div>
    </div>
  );
}
