import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown } from "lucide-react";

export function KPICard({
  label,
  value,
  delta,
  sub,
  accent = false,
}: {
  label: string;
  value: string;
  delta?: number; // +0.12 = +12%
  sub?: string;
  accent?: boolean;
}) {
  const positive = (delta ?? 0) >= 0;
  return (
    <div className={cn("phantom-panel p-6 flex flex-col justify-between", accent && "phantom-panel-accent")}>
      <div className="flex items-start justify-between">
        <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          {label}
        </span>
        {delta !== undefined && (
          <span
            className={cn(
              "text-xs font-medium flex items-center gap-1 tabular-nums",
              positive ? "text-phantom-alive" : "text-phantom-red"
            )}
          >
            {positive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
            {positive ? "+" : ""}
            {(delta * 100).toFixed(1)}%
          </span>
        )}
      </div>
      <div className="mt-6">
        <div className={cn("phantom-metric-lg", accent && "phantom-accent-text")}>{value}</div>
        {sub && <div className="text-xs text-phantom-ghost mt-2">{sub}</div>}
      </div>
    </div>
  );
}
