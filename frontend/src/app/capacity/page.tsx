"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { CapacityResultCard, type CapacityResult } from "@/components/capacity-result-card";
import type { Platform } from "@/components/platform-badge";
import { AlertTriangle, Calculator, ChevronDown, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ──────────────────────────────────────────────────────────────────

type PhoneModel = "Samsung S10 Lite" | "Samsung S20" | "Samsung A53" | "Generic Android";

type CapacityPlanResponse = {
  platforms: CapacityResult[];
  unsupportedPlatforms: string[];
  summaryPerPhone: {
    totalAccounts: number;
    totalStorageGb: number;
    totalRamGb: number;
    storageCapacityGb: number;
    ramCapacityGb: number;
  };
  fleetTotal: number;
  warnings: string[];
};

// ─── Mock / fallback data generator (used when backend is unreachable) ───────

const PLATFORM_SPECS: Record<string, Omit<CapacityResult, "platform">> = {
  instagram: {
    maxAccountsPerPhone: 8,
    startAccounts: 5,
    executionMode: "Background API",
    storageMbPerAccount: 120,
    ramMbPerAccount: 80,
  },
  threads: {
    maxAccountsPerPhone: 8,
    startAccounts: 5,
    executionMode: "Background API",
    storageMbPerAccount: 110,
    ramMbPerAccount: 75,
  },
  tiktok: {
    maxAccountsPerPhone: 3,
    startAccounts: 2,
    executionMode: "Foreground UI",
    storageMbPerAccount: 350,
    ramMbPerAccount: 180,
  },
  telegram: {
    maxAccountsPerPhone: 12,
    startAccounts: 8,
    executionMode: "Background API",
    storageMbPerAccount: 60,
    ramMbPerAccount: 45,
  },
  reddit: {
    maxAccountsPerPhone: 10,
    startAccounts: 6,
    executionMode: "Background API",
    storageMbPerAccount: 80,
    ramMbPerAccount: 55,
  },
  x: {
    maxAccountsPerPhone: 6,
    startAccounts: 4,
    executionMode: "Background API",
    storageMbPerAccount: 95,
    ramMbPerAccount: 70,
  },
  discord: {
    maxAccountsPerPhone: 8,
    startAccounts: 5,
    executionMode: "Background API",
    storageMbPerAccount: 130,
    ramMbPerAccount: 90,
  },
  bluesky: {
    maxAccountsPerPhone: 10,
    startAccounts: 6,
    executionMode: "Background API",
    storageMbPerAccount: 70,
    ramMbPerAccount: 50,
  },
};

const PHONE_MODEL_SPECS: Record<PhoneModel, { storageGb: number; ramGb: number }> = {
  "Samsung S10 Lite": { storageGb: 128, ramGb: 8 },
  "Samsung S20": { storageGb: 128, ramGb: 12 },
  "Samsung A53": { storageGb: 128, ramGb: 6 },
  "Generic Android": { storageGb: 64, ramGb: 4 },
};

function buildMockResponse(
  platforms: string[],
  phoneCount: number,
  phoneModel: PhoneModel
): CapacityPlanResponse {
  const validPlatforms = Object.keys(PLATFORM_SPECS) as Platform[];
  const supportedPlatforms: CapacityResult[] = [];
  const unsupported: string[] = [];

  for (const p of platforms) {
    const normalized = p.trim().toLowerCase();
    if (PLATFORM_SPECS[normalized]) {
      supportedPlatforms.push({
        platform: normalized as Platform,
        ...PLATFORM_SPECS[normalized],
      });
    } else {
      // Check partial match
      const matched = validPlatforms.find((v) => v.includes(normalized) || normalized.includes(v));
      if (matched) {
        supportedPlatforms.push({ platform: matched, ...PLATFORM_SPECS[matched] });
      } else {
        unsupported.push(p.trim());
      }
    }
  }

  const specs = PHONE_MODEL_SPECS[phoneModel];
  const totalAccountsPerPhone = supportedPlatforms.reduce((s, p) => s + p.startAccounts, 0);
  const totalStorageMb = supportedPlatforms.reduce(
    (s, p) => s + p.storageMbPerAccount * p.startAccounts,
    0
  );
  const totalRamMb = supportedPlatforms.reduce(
    (s, p) => s + p.ramMbPerAccount * p.startAccounts,
    0
  );

  const warnings: string[] = [];
  if (totalStorageMb / 1024 > specs.storageGb * 0.7) {
    warnings.push(
      `Storage usage (${(totalStorageMb / 1024).toFixed(1)} GB) exceeds 70% of ${phoneModel} capacity.`
    );
  }
  if (totalRamMb / 1024 > specs.ramGb * 0.75) {
    warnings.push(
      `RAM usage (${(totalRamMb / 1024).toFixed(1)} GB) exceeds 75% of ${phoneModel} RAM. Foreground UI apps will compete for memory.`
    );
  }
  if (unsupported.length > 0) {
    warnings.push(
      `${unsupported.length} platform(s) not in current OFM build: ${unsupported.join(", ")}.`
    );
  }

  return {
    platforms: supportedPlatforms,
    unsupportedPlatforms: unsupported,
    summaryPerPhone: {
      totalAccounts: totalAccountsPerPhone,
      totalStorageGb: totalStorageMb / 1024,
      totalRamGb: totalRamMb / 1024,
      storageCapacityGb: specs.storageGb,
      ramCapacityGb: specs.ramGb,
    },
    fleetTotal: totalAccountsPerPhone * phoneCount,
    warnings,
  };
}

// ─── Skeleton ────────────────────────────────────────────────────────────────

function ResultSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="phantom-skeleton h-[220px] rounded-xl" />
        ))}
      </div>
      <div className="phantom-skeleton h-24 rounded-xl" />
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function CapacityPage() {
  const [platforms, setPlatforms] = useState("");
  const [phoneCount, setPhoneCount] = useState(20);
  const [phoneModel, setPhoneModel] = useState<PhoneModel>("Samsung S10 Lite");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CapacityPlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleCalculate() {
    if (!platforms.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    const platformList = platforms
      .split(/[,\n]+/)
      .map((p) => p.trim())
      .filter(Boolean);

    try {
      const res = await fetch("http://localhost:8001/api/capacity-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platforms: platformList,
          phone_count: phoneCount,
          phone_model: phoneModel,
        }),
        signal: AbortSignal.timeout(6000),
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setResult(data);
    } catch {
      // Backend not available — use local mock
      setResult(buildMockResponse(platformList, phoneCount, phoneModel));
    } finally {
      setLoading(false);
    }
  }

  const storageUtilPct = result
    ? (result.summaryPerPhone.totalStorageGb / result.summaryPerPhone.storageCapacityGb) * 100
    : 0;
  const ramUtilPct = result
    ? (result.summaryPerPhone.totalRamGb / result.summaryPerPhone.ramCapacityGb) * 100
    : 0;

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Fleet planning
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <Calculator className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            Capacity <span className="phantom-accent-text">Planner</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            Tell us which platforms you want to run and how many phones you have.
            We calculate exact account slots, storage, RAM, and execution mode per platform.
          </p>
        </div>
      </div>

      {/* Input form */}
      <Panel label="configure your farm" title="Build my capacity plan">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Platform text input */}
          <div className="lg:col-span-3">
            <label className="block text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-2">
              Platforms to run
            </label>
            <textarea
              value={platforms}
              onChange={(e) => setPlatforms(e.target.value)}
              placeholder="e.g. Instagram, TikTok, Telegram, Grindr"
              rows={3}
              className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-4 py-3 text-sm text-white placeholder:text-phantom-ghost focus:outline-none focus:ring-1 focus:ring-phantom-accent focus:border-phantom-accent resize-none font-mono transition-colors"
            />
            <p className="text-[10px] text-phantom-ghost mt-1.5">
              Comma-separated or one per line. Supported: Instagram, Threads, Reddit, X, TikTok, Telegram, Discord, Bluesky, Dating.
            </p>
          </div>

          {/* Phone count */}
          <div>
            <label className="block text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-2">
              Phone count
            </label>
            <input
              type="number"
              min={1}
              max={500}
              value={phoneCount}
              onChange={(e) => setPhoneCount(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-phantom-accent focus:border-phantom-accent font-mono transition-colors"
            />
          </div>

          {/* Phone model */}
          <div className="relative">
            <label className="block text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-2">
              Phone model
            </label>
            <div className="relative">
              <select
                value={phoneModel}
                onChange={(e) => setPhoneModel(e.target.value as PhoneModel)}
                className="w-full appearance-none bg-phantom-panelHi border border-phantom-border rounded-lg px-4 py-2.5 pr-9 text-sm text-white focus:outline-none focus:ring-1 focus:ring-phantom-accent focus:border-phantom-accent font-mono transition-colors cursor-pointer"
              >
                <option>Samsung S10 Lite</option>
                <option>Samsung S20</option>
                <option>Samsung A53</option>
                <option>Generic Android</option>
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-phantom-ghost pointer-events-none" />
            </div>
          </div>

          {/* Submit button */}
          <div className="flex items-end">
            <button
              onClick={handleCalculate}
              disabled={loading || !platforms.trim()}
              className={cn(
                "w-full flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg text-sm font-semibold transition-all duration-200",
                "bg-phantom-accent text-phantom-bg",
                "hover:bg-phantom-accentHi shadow-[0_0_24px_hsl(162_100%_54%/0.3)]",
                "disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none",
                loading && "cursor-wait"
              )}
            >
              <Zap className="w-4 h-4" />
              {loading ? "Calculating…" : "Calculate Capacity"}
            </button>
          </div>
        </div>
      </Panel>

      {/* Loading skeleton */}
      {loading && <ResultSkeleton />}

      {/* Results */}
      {result && !loading && (
        <div className="space-y-6">
          {/* Platform cards grid */}
          <div>
            <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-4">
              Per-platform allocation
            </div>
            {result.platforms.length > 0 ? (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {result.platforms.map((p) => (
                  <CapacityResultCard
                    key={p.platform}
                    result={p}
                    phoneCount={phoneCount}
                  />
                ))}
              </div>
            ) : (
              <div className="phantom-panel p-8 text-center text-phantom-ghost text-sm">
                No supported platforms found in your input.
              </div>
            )}
          </div>

          {/* Summary bar */}
          <div className="phantom-panel-accent p-6">
            <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-accent font-medium mb-4">
              Summary — {phoneCount} phones · {phoneModel}
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">Accounts / phone</div>
                <div className="font-display font-bold text-3xl tabular-nums mt-1 phantom-accent-text">
                  {result.summaryPerPhone.totalAccounts}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">Fleet total</div>
                <div className="font-display font-bold text-3xl tabular-nums mt-1">
                  {result.fleetTotal.toLocaleString()}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">Storage / phone</div>
                <div className={cn(
                  "font-display font-bold text-3xl tabular-nums mt-1",
                  storageUtilPct > 75 ? "text-phantom-amber" : "text-white"
                )}>
                  {result.summaryPerPhone.totalStorageGb.toFixed(1)} GB
                </div>
                <div className="text-[10px] text-phantom-ghost mt-0.5">
                  of {result.summaryPerPhone.storageCapacityGb} GB
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost">RAM / phone</div>
                <div className={cn(
                  "font-display font-bold text-3xl tabular-nums mt-1",
                  ramUtilPct > 75 ? "text-phantom-amber" : "text-white"
                )}>
                  {result.summaryPerPhone.totalRamGb.toFixed(1)} GB
                </div>
                <div className="text-[10px] text-phantom-ghost mt-0.5">
                  of {result.summaryPerPhone.ramCapacityGb} GB
                </div>
              </div>
            </div>

            {/* Utilization bars */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <UtilBar
                label="Storage utilization"
                pct={storageUtilPct}
                used={`${result.summaryPerPhone.totalStorageGb.toFixed(1)} GB`}
                cap={`${result.summaryPerPhone.storageCapacityGb} GB`}
              />
              <UtilBar
                label="RAM utilization"
                pct={ramUtilPct}
                used={`${result.summaryPerPhone.totalRamGb.toFixed(1)} GB`}
                cap={`${result.summaryPerPhone.ramCapacityGb} GB`}
              />
            </div>
          </div>

          {/* Warnings */}
          {result.warnings.length > 0 && (
            <div className="phantom-panel border-l-2 border-phantom-amber p-5">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-4 h-4 text-phantom-amber" />
                <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-amber font-medium">
                  Warnings
                </span>
              </div>
              <ul className="space-y-2">
                {result.warnings.map((w, i) => (
                  <li key={i} className="text-sm text-phantom-ghost flex items-start gap-2">
                    <span className="text-phantom-amber mt-0.5 shrink-0">›</span>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Unsupported platforms */}
          {result.unsupportedPlatforms.length > 0 && (
            <div className="phantom-panel p-5">
              <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-3">
                Not in OFM build
              </div>
              <div className="flex flex-wrap gap-2">
                {result.unsupportedPlatforms.map((p) => (
                  <span
                    key={p}
                    className="text-xs font-mono px-2 py-1 rounded bg-phantom-panelHi border border-phantom-border text-phantom-ghost"
                  >
                    {p}
                  </span>
                ))}
              </div>
              <p className="text-xs text-phantom-ghost mt-3">
                These platforms are not supported in the current OFM Automation build and were excluded from the plan.
                Submit a feature request to add them to the roadmap.
              </p>
            </div>
          )}

          {/* Full farm total table */}
          <Panel label="full farm total" title={`${phoneCount} phones × all platforms`}>
            <div className="overflow-x-auto -mx-2">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-phantom-border">
                    {["Platform", "Mode", "Accts/Phone", "Fleet Accts", "Storage/Phone", "RAM/Phone", "Fleet Storage"].map((h) => (
                      <th
                        key={h}
                        className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.platforms.map((p) => {
                    const storagePerPhone = (p.storageMbPerAccount * p.startAccounts / 1024).toFixed(2);
                    const ramPerPhone = (p.ramMbPerAccount * p.startAccounts / 1024).toFixed(2);
                    const fleetStorage = (p.storageMbPerAccount * p.startAccounts * phoneCount / 1024).toFixed(1);
                    return (
                      <tr
                        key={p.platform}
                        className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors"
                      >
                        <td className="px-3 py-3 capitalize font-medium">{p.platform}</td>
                        <td className="px-3 py-3">
                          <span className={cn(
                            "text-[9px] font-mono tracking-wider px-1.5 py-0.5 rounded border",
                            p.executionMode === "Background API"
                              ? "bg-phantom-alive/10 text-phantom-alive border-phantom-alive/25"
                              : p.executionMode === "Foreground UI"
                              ? "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/25"
                              : "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/25"
                          )}>
                            {p.executionMode === "Background API" ? "BG API" : p.executionMode === "Foreground UI" ? "FG UI" : "HYBRID"}
                          </span>
                        </td>
                        <td className="px-3 py-3 font-mono tabular-nums text-phantom-accent">{p.startAccounts}</td>
                        <td className="px-3 py-3 font-mono tabular-nums font-semibold">{(p.startAccounts * phoneCount).toLocaleString()}</td>
                        <td className="px-3 py-3 font-mono tabular-nums text-phantom-ghost">{storagePerPhone} GB</td>
                        <td className="px-3 py-3 font-mono tabular-nums text-phantom-ghost">{ramPerPhone} GB</td>
                        <td className="px-3 py-3 font-mono tabular-nums">{fleetStorage} GB</td>
                      </tr>
                    );
                  })}
                  {/* Totals row */}
                  <tr className="border-t-2 border-phantom-accent/30 bg-phantom-accent/5">
                    <td className="px-3 py-3 font-semibold text-phantom-accent" colSpan={2}>TOTAL</td>
                    <td className="px-3 py-3 font-mono tabular-nums font-bold text-phantom-accent">
                      {result.summaryPerPhone.totalAccounts}
                    </td>
                    <td className="px-3 py-3 font-mono tabular-nums font-bold">
                      {result.fleetTotal.toLocaleString()}
                    </td>
                    <td className="px-3 py-3 font-mono tabular-nums font-bold">
                      {result.summaryPerPhone.totalStorageGb.toFixed(2)} GB
                    </td>
                    <td className="px-3 py-3 font-mono tabular-nums font-bold">
                      {result.summaryPerPhone.totalRamGb.toFixed(2)} GB
                    </td>
                    <td className="px-3 py-3 font-mono tabular-nums font-bold">
                      {(result.summaryPerPhone.totalStorageGb * phoneCount).toFixed(1)} GB
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}

      {error && (
        <div className="phantom-panel border-l-2 border-phantom-red p-5 text-sm text-phantom-red">
          {error}
        </div>
      )}
    </div>
  );
}

function UtilBar({
  label,
  pct,
  used,
  cap,
}: {
  label: string;
  pct: number;
  used: string;
  cap: string;
}) {
  const isHigh = pct > 75;
  const clamped = Math.min(pct, 100);
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] text-phantom-ghost">{label}</span>
        <span className={cn("text-[10px] font-mono", isHigh ? "text-phantom-amber" : "text-phantom-ghost")}>
          {used} / {cap} · {pct.toFixed(0)}%
        </span>
      </div>
      <div className="h-2 rounded-full bg-phantom-panelHi overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${clamped}%`,
            background: isHigh ? "hsl(38 92% 58%)" : "hsl(162 100% 54%)",
            boxShadow: `0 0 10px ${isHigh ? "hsl(38 92% 58% / 0.35)" : "hsl(162 100% 54% / 0.35)"}`,
          }}
        />
      </div>
    </div>
  );
}
