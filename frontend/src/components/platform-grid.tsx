"use client";

import { cn } from "@/lib/utils";

type Platform = {
  name: string;
  shortCode: string;
  accountsPerPhone: string;
  executionMode: "API" | "Accessibility" | "Hybrid" | "Phase 2";
  status: "live" | "beta" | "upcoming";
  color: string;
};

const PLATFORMS: Platform[] = [
  {
    name: "Instagram",
    shortCode: "IG",
    accountsPerPhone: "90+",
    executionMode: "Accessibility",
    status: "live",
    color: "hsl(292 91% 68%)",
  },
  {
    name: "Threads",
    shortCode: "TH",
    accountsPerPhone: "90+",
    executionMode: "Accessibility",
    status: "live",
    color: "hsl(0 0% 80%)",
  },
  {
    name: "Reddit",
    shortCode: "RD",
    accountsPerPhone: "60+",
    executionMode: "API",
    status: "live",
    color: "hsl(18 100% 55%)",
  },
  {
    name: "X / Twitter",
    shortCode: "X",
    accountsPerPhone: "80+",
    executionMode: "API",
    status: "live",
    color: "hsl(0 0% 90%)",
  },
  {
    name: "TikTok",
    shortCode: "TT",
    accountsPerPhone: "40+",
    executionMode: "Accessibility",
    status: "live",
    color: "hsl(180 100% 55%)",
  },
  {
    name: "Telegram",
    shortCode: "TG",
    accountsPerPhone: "100+",
    executionMode: "API",
    status: "live",
    color: "hsl(200 100% 56%)",
  },
  {
    name: "Discord",
    shortCode: "DC",
    accountsPerPhone: "50+",
    executionMode: "API",
    status: "beta",
    color: "hsl(235 86% 65%)",
  },
  {
    name: "BlueSky",
    shortCode: "BS",
    accountsPerPhone: "50+",
    executionMode: "API",
    status: "beta",
    color: "hsl(212 100% 58%)",
  },
  {
    name: "LinkedIn",
    shortCode: "LI",
    accountsPerPhone: "20+",
    executionMode: "Hybrid",
    status: "beta",
    color: "hsl(201 100% 38%)",
  },
  {
    name: "Dating Apps",
    shortCode: "DA",
    accountsPerPhone: "30+",
    executionMode: "Accessibility",
    status: "beta",
    color: "hsl(348 100% 60%)",
  },
];

const STATUS_LABEL: Record<Platform["status"], string> = {
  live: "Live",
  beta: "Beta",
  upcoming: "Soon",
};

const MODE_COLOR: Record<Platform["executionMode"], string> = {
  API: "text-phantom-accent border-phantom-accent/30 bg-phantom-accent/10",
  Accessibility: "text-phantom-magenta border-phantom-magenta/30 bg-phantom-magenta/10",
  Hybrid: "text-phantom-amber border-phantom-amber/30 bg-phantom-amber/10",
  "Phase 2": "text-phantom-ghost border-phantom-border bg-phantom-panelHi",
};

export function PlatformGrid({ className }: { className?: string }) {
  return (
    <div className={cn("grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4", className)}>
      {PLATFORMS.map((p) => (
        <div
          key={p.name}
          className="phantom-panel p-5 flex flex-col gap-3 group hover:border-phantom-accent/20 transition-all"
        >
          {/* Platform icon circle */}
          <div className="flex items-start justify-between">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center font-black text-sm text-white shrink-0"
              style={{ backgroundColor: `${p.color}20`, border: `1px solid ${p.color}40` }}
            >
              <span style={{ color: p.color }}>{p.shortCode}</span>
            </div>
            {/* Status badge */}
            <span
              className={cn(
                "text-[9px] uppercase tracking-[0.12em] font-mono px-2 py-0.5 rounded-full border",
                p.status === "live" &&
                  "text-phantom-alive border-phantom-alive/30 bg-phantom-alive/10",
                p.status === "beta" &&
                  "text-phantom-amber border-phantom-amber/30 bg-phantom-amber/10",
                p.status === "upcoming" &&
                  "text-phantom-ghost border-phantom-border bg-phantom-panelHi"
              )}
            >
              {STATUS_LABEL[p.status]}
            </span>
          </div>

          {/* Name */}
          <div className="font-display font-semibold text-sm">{p.name}</div>

          {/* Density */}
          <div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em] font-medium mb-1">
              Accounts / phone
            </div>
            <div className="phantom-metric text-2xl phantom-accent-text">{p.accountsPerPhone}</div>
          </div>

          {/* Mode badge */}
          <span
            className={cn(
              "self-start text-[9px] uppercase tracking-[0.12em] font-mono px-2 py-0.5 rounded-md border",
              MODE_COLOR[p.executionMode]
            )}
          >
            {p.executionMode}
          </span>
        </div>
      ))}
    </div>
  );
}
