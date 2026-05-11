import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * 24-hour timeline strip showing which hours a platform is active.
 * Pass an array of active hour numbers (0-23).
 */
export function TimeSlotStrip({
  activeHours,
  currentHour,
  label = "Schedule today",
}: {
  activeHours: number[];
  currentHour?: number;
  label?: string;
}) {
  // Use state so the current-hour marker is only set client-side (avoids SSR mismatch).
  const [clientHour, setClientHour] = useState<number | null>(null);
  useEffect(() => { setClientHour(currentHour ?? new Date().getHours()); }, [currentHour]);
  const now = clientHour ?? currentHour ?? 0;
  const activeSet = new Set(activeHours);

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          {label}
        </span>
        <span className="text-[10px] font-mono text-phantom-ghost">
          {activeHours.length}h active / 24h
        </span>
      </div>
      <div className="flex gap-0.5">
        {Array.from({ length: 24 }, (_, h) => {
          const isActive = activeSet.has(h);
          const isCurrent = h === now;
          return (
            <div
              key={h}
              title={`${String(h).padStart(2, "0")}:00 — ${isActive ? "Active" : "Inactive"}`}
              className={cn(
                "flex-1 h-5 rounded-sm transition-all relative",
                isActive
                  ? "bg-phantom-accent"
                  : "bg-phantom-panelHi",
                isCurrent && "ring-1 ring-white ring-offset-1 ring-offset-phantom-bg"
              )}
              style={
                isActive
                  ? { boxShadow: "0 0 6px hsl(162 100% 54% / 0.4)" }
                  : undefined
              }
            />
          );
        })}
      </div>
      {/* Hour labels — every 6 hours */}
      <div className="flex justify-between mt-1 text-[9px] font-mono text-phantom-ghost">
        <span>00</span>
        <span>06</span>
        <span>12</span>
        <span>18</span>
        <span>23</span>
      </div>
      {/* Legend */}
      <div className="flex items-center gap-3 mt-2 text-[9px] text-phantom-ghost">
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-sm bg-phantom-accent inline-block" />
          Active
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-sm bg-phantom-panelHi inline-block" />
          Inactive
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-sm ring-1 ring-white inline-block" />
          Now ({String(now).padStart(2, "0")}:xx)
        </span>
      </div>
    </div>
  );
}
