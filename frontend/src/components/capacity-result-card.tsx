"use client";

import { cn } from "@/lib/utils";
import type { Platform } from "@/components/platform-badge";
import { PlatformBadge } from "@/components/platform-badge";
import { AlertTriangle, Cpu, HardDrive } from "lucide-react";

export type CapacityResult = {
  platform: Platform;
  maxAccountsPerPhone: number;
  startAccounts: number;
  executionMode: "Background API" | "Foreground UI" | "Hybrid";
  storageMbPerAccount: number;
  ramMbPerAccount: number;
};

const EXECUTION_MODE_STYLES: Record<CapacityResult["executionMode"], string> = {
  "Background API": "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/25",
  "Foreground UI": "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/25",
  "Hybrid": "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/25",
};

export function CapacityResultCard({
  result,
  phoneCount,
}: {
  result: CapacityResult;
  phoneCount: number;
}) {
  const fleetTotal = result.startAccounts * phoneCount;
  const totalStorageMb = result.storageMbPerAccount * result.startAccounts;
  const totalRamMb = result.ramMbPerAccount * result.startAccounts;
  const storageGb = totalStorageMb / 1024;
  const ramGb = totalRamMb / 1024;

  return (
    <div className="phantom-panel p-5 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <PlatformBadge platform={result.platform} size="md" />
        <span
          className={cn(
            "text-[9px] font-mono tracking-wider px-2 py-0.5 rounded border",
            EXECUTION_MODE_STYLES[result.executionMode]
          )}
        >
          {result.executionMode.toUpperCase()}
        </span>
      </div>

      {/* Accounts */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">Per phone</div>
          <div className="font-display font-bold text-2xl tabular-nums mt-1 phantom-accent-text">
            {result.startAccounts}
          </div>
          <div className="text-[10px] text-phantom-ghost mt-0.5">start · max {result.maxAccountsPerPhone}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">Fleet total</div>
          <div className="font-display font-bold text-2xl tabular-nums mt-1">
            {fleetTotal.toLocaleString()}
          </div>
          <div className="text-[10px] text-phantom-ghost mt-0.5">across {phoneCount} phones</div>
        </div>
      </div>

      {/* Resource bars */}
      <div className="space-y-2.5">
        <ResourceBar
          icon={<HardDrive className="w-3 h-3" />}
          label="Storage"
          value={storageGb}
          max={32}
          unit="GB"
          color="hsl(162 100% 54%)"
        />
        <ResourceBar
          icon={<Cpu className="w-3 h-3" />}
          label="RAM"
          value={ramGb}
          max={8}
          unit="GB"
          color="hsl(292 91% 68%)"
        />
      </div>
    </div>
  );
}

function ResourceBar({
  icon,
  label,
  value,
  max,
  unit,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  max: number;
  unit: string;
  color: string;
}) {
  const pct = Math.min(value / max, 1);
  const isHigh = pct > 0.75;

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5 text-[10px] text-phantom-ghost">
          {icon}
          <span>{label}</span>
        </div>
        <div className="flex items-center gap-1">
          {isHigh && <AlertTriangle className="w-3 h-3 text-phantom-amber" />}
          <span
            className={cn(
              "text-[10px] font-mono tabular-nums",
              isHigh ? "text-phantom-amber" : "text-phantom-ghost"
            )}
          >
            {value.toFixed(1)}{unit}
          </span>
        </div>
      </div>
      <div className="h-1.5 rounded-full bg-phantom-panelHi overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${pct * 100}%`,
            background: isHigh ? "hsl(38 92% 58%)" : color,
            boxShadow: `0 0 8px ${isHigh ? "hsl(38 92% 58% / 0.4)" : `${color} / 0.4`}`,
          }}
        />
      </div>
    </div>
  );
}
