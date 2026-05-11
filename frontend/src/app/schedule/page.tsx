"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { TimelineGrid, type PlatformWindow } from "@/components/timeline-grid";
import { Calendar, Zap, WifiOff, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

// Each platform gets peak activity windows as a set of half-hour slots.
// Slot 0 = 00:00–00:30, slot 2 = 01:00, slot 24 = 12:00, etc.
// Quiet hours: slots 4–11 (2am–6am)

const PLATFORM_WINDOWS: PlatformWindow[] = [
  {
    platform: "instagram",
    label: "Instagram",
    color: "bg-[#E1306C]",
    // Peak: 6am–10am and 6pm–11pm (slots 12–20 and 36–46)
    slots: [
      12, 13, 14, 15, 16, 17, 18, 19, 20,      // 6am–10am
      24, 25, 26, 27,                            // 12pm–2pm (moderate)
      36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, // 6pm–11pm
    ],
  },
  {
    platform: "threads",
    label: "Threads",
    color: "bg-white/60",
    // Peak: 7am–9am and 7pm–10pm
    slots: [
      14, 15, 16, 17, 18,                       // 7am–9am
      26, 27, 28, 29,                            // 1pm–2:30pm
      38, 39, 40, 41, 42, 43, 44, 45,           // 7pm–10:30pm
    ],
  },
  {
    platform: "reddit",
    label: "Reddit",
    color: "bg-[#FF4500]",
    // Peak: 8am–12pm and 8pm–midnight
    slots: [
      16, 17, 18, 19, 20, 21, 22, 23,           // 8am–12pm
      40, 41, 42, 43, 44, 45, 46, 47,           // 8pm–midnight
    ],
  },
  {
    platform: "x",
    label: "X / Twitter",
    color: "bg-white/40",
    // Peak: 8am–10am and 5pm–9pm
    slots: [
      16, 17, 18, 19, 20,                       // 8am–10am
      22, 23,                                    // 11am–12pm
      34, 35, 36, 37, 38, 39, 40, 41, 42,      // 5pm–9pm
    ],
  },
  {
    platform: "tiktok",
    label: "TikTok",
    color: "bg-[#69C9D0]",
    // Peak: morning 9–11 and evening 7pm–11pm
    slots: [
      18, 19, 20, 21, 22,                       // 9am–11am
      30, 31,                                    // 3pm–4pm
      38, 39, 40, 41, 42, 43, 44, 45, 46,      // 7pm–11pm
    ],
  },
  {
    platform: "telegram",
    label: "Telegram",
    color: "bg-[#229ED9]",
    // Spread throughout day, no strong peaks
    slots: [
      16, 17, 20, 21, 24, 25, 28, 29, 32, 33, 36, 37, 40, 41, 44, 45,
    ],
  },
  {
    platform: "discord",
    label: "Discord",
    color: "bg-[#5865F2]",
    // Peak: afternoon/evening
    slots: [
      24, 25, 26, 27, 28,                       // 12pm–2pm
      36, 37, 38, 39, 40, 41, 42, 43,          // 6pm–9:30pm
    ],
  },
  {
    platform: "bluesky",
    label: "Bluesky",
    color: "bg-[#0085FF]",
    // Similar to Twitter peaks
    slots: [
      16, 17, 18, 19,                           // 8am–9:30am
      34, 35, 36, 37, 38, 39, 40,              // 5pm–8pm
    ],
  },
  {
    platform: "infrastructure",
    label: "Infra",
    color: "bg-phantom-ghost/40",
    // Infrastructure runs 24h except quiet hours already handled by slot
    slots: Array.from({ length: 48 }, (_, i) => i).filter((i) => i < 4 || i >= 12),
  },
];

// Calculate current slot from local time
function getCurrentSlot(): number {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  return Math.floor(minutes / 30);
}

type DayPreset = "weekday" | "weekend" | "custom";

const DAY_PRESETS: { label: string; value: DayPreset; description: string }[] = [
  { label: "Weekday", value: "weekday", description: "Mon–Fri typical US active hours" },
  { label: "Weekend", value: "weekend", description: "Sat–Sun shifted peaks, longer evening" },
  { label: "Custom", value: "custom", description: "Generated from schedule API" },
];

export default function SchedulePage() {
  const [dayPreset, setDayPreset] = useState<DayPreset>("weekday");
  const [generating, setGenerating] = useState(false);
  const [backendDown, setBackendDown] = useState(false);

  const currentSlot = getCurrentSlot();

  // Platform counts by hour — for the summary
  const activeSlotsByHour = Array.from({ length: 24 }, (_, h) => {
    const slot1 = h * 2;
    const slot2 = h * 2 + 1;
    return PLATFORM_WINDOWS.filter(
      (w) => w.platform !== "infrastructure" && (w.slots.includes(slot1) || w.slots.includes(slot2))
    ).length;
  });

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await fetch("http://localhost:8001/api/schedule/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset: dayPreset }),
      });
    } catch {
      setBackendDown(true);
    } finally {
      setTimeout(() => setGenerating(false), 2500);
    }
  };

  // Build hourly activity heat bar
  const maxPlatforms = Math.max(...activeSlotsByHour);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Orchestration layer
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <Calendar className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            Daily <span className="phantom-accent-text">Schedule</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            24-hour platform activity windows. Quiet hours 2am–6am are greyed and suppressed fleet-wide.
            Each bar shows which platforms are active during each half-hour slot.
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {backendDown && (
            <span className="flex items-center gap-1.5 text-xs text-phantom-amber bg-phantom-amber/10 border border-phantom-amber/20 px-3 py-1.5 rounded-lg">
              <WifiOff className="w-3.5 h-3.5" />
              Connecting to fleet...
            </span>
          )}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold border transition-all",
              "bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25 hover:shadow-[0_0_16px_hsl(162_100%_54%/0.2)]",
              generating && "opacity-60 cursor-not-allowed"
            )}
          >
            {generating ? (
              <span className="phantom-dot phantom-dot-accent animate-phantom-pulse" />
            ) : (
              <Zap className="w-4 h-4" strokeWidth={1.75} />
            )}
            {generating ? "Generating..." : "Generate schedule"}
          </button>
        </div>
      </div>

      {/* Day preset selector */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-phantom-ghost">Day type:</span>
        {DAY_PRESETS.map((p) => (
          <button
            key={p.value}
            onClick={() => setDayPreset(p.value)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
              dayPreset === p.value
                ? "bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30"
                : "bg-phantom-panelHi text-phantom-ghost border-phantom-border hover:text-white"
            )}
            title={p.description}
          >
            {p.label}
          </button>
        ))}
        <span className="text-xs text-phantom-ghost ml-2 flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5" />
          Current slot: <span className="text-white font-mono">{Math.floor(currentSlot / 2).toString().padStart(2, "0")}:{currentSlot % 2 === 0 ? "00" : "30"}</span>
        </span>
      </div>

      {/* Hourly activity heatbar */}
      <Panel label="hourly platform density" title="Platforms active per hour (non-infra)">
        <div className="flex items-end gap-1 h-16 mt-2">
          {activeSlotsByHour.map((count, h) => {
            const isQuiet = h >= 2 && h < 6;
            const isCurrent = Math.floor(currentSlot / 2) === h;
            const heightPct = maxPlatforms > 0 ? (count / maxPlatforms) * 100 : 0;
            return (
              <div
                key={h}
                className="flex-1 flex flex-col items-center justify-end gap-1"
                title={`${h}:00 — ${count} platforms`}
              >
                <div
                  className={cn(
                    "w-full rounded-t transition-all",
                    isQuiet ? "bg-phantom-border/30" : isCurrent ? "bg-phantom-accent" : "bg-phantom-accent/40"
                  )}
                  style={{ height: `${Math.max(heightPct, 4)}%` }}
                />
                {(h % 4 === 0 || isCurrent) && (
                  <span className={cn("text-[8px] font-mono", isCurrent ? "text-phantom-accent" : "text-phantom-ghost/50")}>
                    {h}
                  </span>
                )}
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-4 mt-3 text-[10px] text-phantom-ghost">
          <span className="flex items-center gap-1.5">
            <div className="w-3 h-2 rounded-sm bg-phantom-border/30" />
            Quiet hours
          </span>
          <span className="flex items-center gap-1.5">
            <div className="w-3 h-2 rounded-sm bg-phantom-accent" />
            Current hour
          </span>
          <span className="flex items-center gap-1.5">
            <div className="w-3 h-2 rounded-sm bg-phantom-accent/40" />
            Active
          </span>
        </div>
      </Panel>

      {/* Main timeline grid */}
      <Panel
        label="platform timeline · 48 slots"
        title="Half-hour activity windows per platform"
        subtitle="Each colored segment = platform is active during that half-hour. Grey band = quiet hours (2am–6am)."
      >
        <TimelineGrid windows={PLATFORM_WINDOWS} currentSlot={currentSlot} />
      </Panel>

      {/* Schedule summary table */}
      <Panel label="schedule summary" title="Peak windows per platform">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {PLATFORM_WINDOWS.filter((w) => w.platform !== "infrastructure").map((win) => {
            const activeCount = win.slots.filter((s) => s >= 12 || s < 4).length; // exclude quiet
            const peakHours = win.slots
              .filter((s) => s >= 12)
              .map((s) => Math.floor(s / 2));
            const uniqueHours = [...new Set(peakHours)].sort((a, b) => a - b);
            const firstPeak = uniqueHours[0];
            const lastPeak = uniqueHours[uniqueHours.length - 1];

            return (
              <div
                key={win.platform}
                className="phantom-panel p-4 flex items-start gap-3"
              >
                <div
                  className={cn("w-1.5 self-stretch rounded-full shrink-0", win.color)}
                />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-white">{win.label}</div>
                  <div className="text-[10px] text-phantom-ghost mt-0.5">
                    Peak: {firstPeak !== undefined ? `${firstPeak}:00` : "—"}–{lastPeak !== undefined ? `${lastPeak}:30` : "—"}
                  </div>
                  <div className="text-[10px] text-phantom-ghost mt-0.5">
                    Active slots: <span className="text-phantom-accent font-mono">{activeCount}</span>/48
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
