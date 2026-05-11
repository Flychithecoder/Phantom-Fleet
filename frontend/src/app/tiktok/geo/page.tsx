"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Globe } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type RegionHealth = "HEALTHY" | "DEGRADED" | "CRITICAL";

const HEALTH_STYLES: Record<RegionHealth, { bg: string; text: string; border: string }> = {
  HEALTHY:  { bg: "bg-phantom-alive/10",  text: "text-phantom-alive",  border: "border-phantom-alive/20"  },
  DEGRADED: { bg: "bg-phantom-amber/10",  text: "text-phantom-amber",  border: "border-phantom-amber/20"  },
  CRITICAL: { bg: "bg-phantom-red/10",    text: "text-phantom-red",    border: "border-phantom-red/20"    },
};

const REGION_BREAKDOWN = [
  { id: "us", region: "United States", code: "US", accounts: 193, avgFBR: "4.8%", avgViews: "9.2K", proxyPool: 48, health: "HEALTHY"  as RegionHealth },
  { id: "uk", region: "United Kingdom",code: "UK", accounts: 56,  avgFBR: "3.9%", avgViews: "7.1K", proxyPool: 14, health: "HEALTHY"  as RegionHealth },
  { id: "ca", region: "Canada",        code: "CA", accounts: 34,  avgFBR: "4.2%", avgViews: "6.8K", proxyPool: 9,  health: "DEGRADED" as RegionHealth },
  { id: "au", region: "Australia",     code: "AU", accounts: 29,  avgFBR: "3.6%", avgViews: "5.9K", proxyPool: 8,  health: "HEALTHY"  as RegionHealth },
];

const PROXY_POOLS = [
  { id: "p1", region: "US", provider: "Bright Data 4G", total: 48, active: 44, lastRotation: "3m ago",   successRate: 98.2, flaggedIPs: 2  },
  { id: "p2", region: "UK", provider: "Proxy-Cheap 4G", total: 14, active: 13, lastRotation: "7m ago",   successRate: 96.8, flaggedIPs: 0  },
  { id: "p3", region: "CA", provider: "Bright Data 4G", total: 9,  active: 7,  lastRotation: "18m ago",  successRate: 88.4, flaggedIPs: 3  },
  { id: "p4", region: "AU", provider: "Proxy-Cheap 4G", total: 8,  active: 8,  lastRotation: "2m ago",   successRate: 97.5, flaggedIPs: 0  },
];

// Target vs actual distribution
const DISTRIBUTION = [
  { region: "US", target: 62, actual: 61.9, count: 193 },
  { region: "UK", target: 18, actual: 17.9, count: 56  },
  { region: "CA", target: 11, actual: 10.9, count: 34  },
  { region: "AU", target:  9, actual:  9.3, count: 29  },
];

const REGION_FLAG: Record<string, string> = { US: "🇺🇸", UK: "🇬🇧", CA: "🇨🇦", AU: "🇦🇺" };

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function TikTokGeoPage() {
  const totalAccounts = REGION_BREAKDOWN.reduce((sum, r) => sum + r.accounts, 0);
  const euAccounts = REGION_BREAKDOWN.filter((r) => r.code === "UK").reduce((sum, r) => sum + r.accounts, 0);
  const apacAccounts = REGION_BREAKDOWN.filter((r) => r.code === "AU").reduce((sum, r) => sum + r.accounts, 0);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          TikTok · geo distribution
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <Globe className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Geo <span className="phantom-accent-text">Distribution</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-xs font-semibold">
            4 active regions
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Geographic account distribution, regional proxy health, and target-vs-actual rebalancing across the TikTok fleet.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Active Regions"  value="4"                   sub="US · UK · CA · AU"        />
        <KPICard label="US Accounts"     value={String(193)}         delta={0.031} sub="of 312 fleet"  />
        <KPICard label="EU Accounts"     value={String(euAccounts)}  sub="UK fleet"                 />
        <KPICard label="APAC Accounts"   value={String(apacAccounts)} sub="AU fleet"    accent       />
      </div>

      {/* Per-region breakdown table */}
      <Panel label="regional breakdown" title="Per-Region Account Health">
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Region", "Accounts", "Avg FBR", "Avg Views / Post", "Proxy Pool", "Health"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {REGION_BREAKDOWN.map((row) => {
                const s = HEALTH_STYLES[row.health];
                const share = ((row.accounts / totalAccounts) * 100).toFixed(1);
                return (
                  <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{REGION_FLAG[row.code]}</span>
                        <div>
                          <div className="text-xs text-white font-semibold">{row.region}</div>
                          <div className="text-[10px] text-phantom-ghost">{row.code} · {share}% of fleet</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-xs font-bold tabular-nums text-white">{row.accounts}</td>
                    <td className="px-3 py-3 text-xs font-semibold tabular-nums phantom-accent-text">{row.avgFBR}</td>
                    <td className="px-3 py-3 text-xs tabular-nums text-white">{row.avgViews}</td>
                    <td className="px-3 py-3 text-xs tabular-nums text-phantom-ghost">{row.proxyPool} proxies</td>
                    <td className="px-3 py-3">
                      <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", s.bg, s.text, s.border)}>
                        {row.health}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Proxy pools */}
      <Panel label="proxy infrastructure" title="IP / Proxy Pool Status">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {PROXY_POOLS.map((p) => (
            <div key={p.id} className="rounded-lg bg-phantom-panelHi border border-phantom-border p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span>{REGION_FLAG[p.region]}</span>
                  <span className="text-sm font-bold text-white">{p.region}</span>
                </div>
                {p.flaggedIPs > 0 && (
                  <span className="px-1.5 py-0.5 rounded bg-phantom-red/10 border border-phantom-red/20 text-phantom-red text-[10px] font-bold">
                    {p.flaggedIPs} flagged
                  </span>
                )}
              </div>
              <div className="text-[11px] text-phantom-ghost">{p.provider}</div>
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="text-phantom-ghost">Active</span>
                  <span className="tabular-nums text-white font-semibold">{p.active}/{p.total}</span>
                </div>
                <div className="h-1.5 rounded-full bg-phantom-border overflow-hidden">
                  <div
                    className={cn("h-full rounded-full", p.active / p.total >= 0.9 ? "bg-phantom-alive" : "bg-phantom-amber")}
                    style={{ width: `${(p.active / p.total) * 100}%` }}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div>
                  <div className="text-phantom-ghost">Success Rate</div>
                  <div className={cn("font-bold tabular-nums", p.successRate >= 95 ? "text-phantom-alive" : "text-phantom-amber")}>
                    {p.successRate}%
                  </div>
                </div>
                <div>
                  <div className="text-phantom-ghost">Last Rotation</div>
                  <div className="text-white">{p.lastRotation}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* Rebalancing panel */}
      <Panel label="rebalancing" title="Target vs Actual Distribution" accent>
        <div className="space-y-5">
          {DISTRIBUTION.map((d) => {
            const delta = Math.abs(d.target - d.actual);
            const onTarget = delta < 1;
            return (
              <div key={d.region} className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span>{REGION_FLAG[d.region]}</span>
                    <span className="text-sm font-semibold text-white">{d.region}</span>
                    <span className="text-xs text-phantom-ghost">{d.count} accounts</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-phantom-ghost">Target: <span className="text-white font-semibold">{d.target}%</span></span>
                    <span className="text-phantom-ghost">Actual: <span className={cn("font-semibold", onTarget ? "text-phantom-alive" : "text-phantom-amber")}>{d.actual}%</span></span>
                    <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", onTarget
                      ? "bg-phantom-alive/10 border-phantom-alive/20 text-phantom-alive"
                      : "bg-phantom-amber/10 border-phantom-amber/20 text-phantom-amber")}>
                      {onTarget ? "ON TARGET" : `DRIFT +${delta.toFixed(1)}%`}
                    </span>
                  </div>
                </div>
                <div className="relative h-3 rounded-full bg-phantom-border overflow-hidden">
                  {/* Target marker */}
                  <div
                    className="absolute top-0 bottom-0 w-0.5 bg-phantom-ghost/50 z-10"
                    style={{ left: `${d.target}%` }}
                  />
                  {/* Actual fill */}
                  <div
                    className={cn("h-full rounded-full", onTarget ? "bg-phantom-alive/70" : "bg-phantom-amber/70")}
                    style={{ width: `${d.actual}%` }}
                  />
                </div>
              </div>
            );
          })}
          <div className="text-[11px] text-phantom-ghost pt-2 border-t border-phantom-border/40">
            Target distribution is based on US platform audience data · rebalance automatically triggers when drift exceeds 2%
          </div>
        </div>
      </Panel>
    </div>
  );
}
