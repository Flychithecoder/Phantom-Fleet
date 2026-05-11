"use client";

import { cn } from "@/lib/utils";

export type PlatformWindow = {
  platform: string;
  color: string;        // Tailwind bg color or hex
  slots: number[];      // which half-hour slots are active (0–47, where 0=midnight, 4=2am, etc.)
  label: string;
};

// 48 half-hour slots: slot 0 = 00:00–00:30, slot 4 = 02:00–02:30
const QUIET_SLOTS = Array.from({ length: 8 }, (_, i) => i + 4); // 2am–6am = slots 4..11

function formatHour(slot: number): string {
  const hour = Math.floor(slot / 2);
  const min = slot % 2 === 0 ? "00" : "30";
  const h = hour === 0 ? "12" : hour > 12 ? String(hour - 12) : String(hour);
  const ampm = hour < 12 ? "am" : "pm";
  if (min === "00") return `${h}${ampm}`;
  return "";
}

const HOUR_LABELS = Array.from({ length: 48 }, (_, i) => formatHour(i));

export function TimelineGrid({
  windows,
  currentSlot,
}: {
  windows: PlatformWindow[];
  currentSlot?: number; // current time as a slot index
}) {
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[900px]">
        {/* Hour labels */}
        <div className="flex mb-2 pl-[100px]">
          {HOUR_LABELS.map((label, i) => (
            <div
              key={i}
              className="flex-1 text-center text-[9px] text-phantom-ghost font-mono"
              style={{ minWidth: 0 }}
            >
              {label}
            </div>
          ))}
        </div>

        {/* Quiet hours shading layer — sits behind all rows */}
        <div className="relative">
          {/* Track area */}
          <div className="absolute inset-0 pl-[100px] flex pointer-events-none">
            {Array.from({ length: 48 }, (_, i) => (
              <div
                key={i}
                className={cn(
                  "flex-1 h-full",
                  QUIET_SLOTS.includes(i) && "bg-phantom-border/20"
                )}
              />
            ))}
          </div>

          {/* Platform rows */}
          <div className="relative space-y-1.5">
            {windows.map((win) => (
              <div key={win.platform} className="flex items-center h-7 gap-0">
                {/* Platform label */}
                <div className="w-[100px] shrink-0 text-[11px] text-phantom-ghost font-medium pr-3 text-right truncate">
                  {win.label}
                </div>

                {/* Slot cells */}
                <div className="flex-1 flex h-full gap-px">
                  {Array.from({ length: 48 }, (_, slotIdx) => {
                    const isActive = win.slots.includes(slotIdx);
                    const isQuiet = QUIET_SLOTS.includes(slotIdx);
                    const isCurrent = currentSlot === slotIdx;

                    return (
                      <div
                        key={slotIdx}
                        className={cn(
                          "flex-1 h-full rounded-[2px] transition-all",
                          isQuiet && !isActive && "bg-phantom-border/10",
                          !isQuiet && !isActive && "bg-phantom-panelHi/30",
                          isActive && `${win.color} opacity-80`,
                          isCurrent && "ring-1 ring-white/40"
                        )}
                      />
                    );
                  })}
                </div>
              </div>
            ))}

            {/* Current time cursor */}
            {currentSlot !== undefined && (
              <div
                className="absolute top-0 bottom-0 w-px bg-white/30 pointer-events-none"
                style={{
                  left: `calc(100px + ${(currentSlot / 48) * 100}% * (1 - 100px / 100%))`,
                }}
              />
            )}
          </div>
        </div>

        {/* Legend row */}
        <div className="flex items-center gap-4 mt-4 pl-[100px] flex-wrap">
          <div className="flex items-center gap-1.5 text-[10px] text-phantom-ghost">
            <div className="w-4 h-3 rounded-[2px] bg-phantom-border/20" />
            <span>Quiet hours (2am–6am)</span>
          </div>
          <div className="flex items-center gap-1.5 text-[10px] text-phantom-ghost">
            <div className="w-px h-3 bg-white/30" />
            <span>Current time</span>
          </div>
          {windows.slice(0, 5).map((w) => (
            <div key={w.platform} className="flex items-center gap-1.5 text-[10px] text-phantom-ghost">
              <div className={cn("w-4 h-3 rounded-[2px]", w.color)} />
              <span>{w.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
