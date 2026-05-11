"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { RotateCcw, CheckCircle2, PauseCircle } from "lucide-react";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const UNFOLLOW_QUEUE = [
  { username: "@luna_aesthetic", following: 5_842, queued: 120, status: "Active" },
  { username: "@mia_vibes_xo", following: 4_210, queued: 85, status: "Active" },
  { username: "@nova_daily", following: 6_103, queued: 200, status: "Paused" },
  { username: "@swift_emma_42", following: 3_950, queued: 60, status: "Active" },
  { username: "@grace_fit_life", following: 2_780, queued: 40, status: "Active" },
  { username: "@stella_vibes", following: 5_990, queued: 180, status: "Paused" },
  { username: "@aria_content", following: 1_860, queued: 30, status: "Active" },
  { username: "@jade_glowup", following: 4_440, queued: 95, status: "Active" },
];

const FOLLOW_BACK_CONVERTS = [
  { account: "@luna_aesthetic", followedBack: "Apr 10", daysSince: 1, dmInitiated: true },
  { account: "@mia_vibes_xo", followedBack: "Apr 9", daysSince: 2, dmInitiated: true },
  { account: "@nova_daily", followedBack: "Apr 8", daysSince: 3, dmInitiated: false },
  { account: "@swift_emma_42", followedBack: "Apr 7", daysSince: 4, dmInitiated: true },
  { account: "@grace_fit_life", followedBack: "Apr 6", daysSince: 5, dmInitiated: false },
  { account: "@stella_vibes", followedBack: "Apr 5", daysSince: 6, dmInitiated: true },
];

const DAILY_UNFOLLOWS = [
  { day: "Apr 5", count: 1204 },
  { day: "Apr 6", count: 2108 },
  { day: "Apr 7", count: 2847 },
  { day: "Apr 8", count: 1956 },
  { day: "Apr 9", count: 2340 },
  { day: "Apr 10", count: 2100 },
  { day: "Apr 11", count: 2847 },
];

const MAX_BAR = Math.max(...DAILY_UNFOLLOWS.map((d) => d.count));

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UnfollowPage() {
  const [statusFilter, setStatusFilter] = useState<"All" | "Active" | "Paused">("All");

  const filteredQueue =
    statusFilter === "All"
      ? UNFOLLOW_QUEUE
      : UNFOLLOW_QUEUE.filter((r) => r.status === statusFilter);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Instagram · unfollow engine
        </div>
        <div className="flex items-center gap-3 mt-2">
          <RotateCcw className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Unfollow <span className="phantom-accent-text">Engine</span>
          </h1>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Automated follow-back detection, follow-wall management, and safe unfollow scheduling across the IG fleet.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Unfollowed Today" value="2,847" delta={0.082} sub="vs yesterday" />
        <KPICard label="Protected (Follow-Back)" value="1,203" sub="safe from unfollow" />
        <KPICard label="Avg Following Count" value="2,841" sub="across fleet" />
        <KPICard
          label="Accounts Near Wall (>6k)"
          value="3"
          sub="needs immediate unfollow"
          accent
        />
      </div>

      {/* Two-column panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Unfollow Queue */}
        <Panel
          label="queue"
          title="Unfollow Queue"
          actions={
            <div className="flex gap-1.5">
              {(["All", "Active", "Paused"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={`px-3 py-1 rounded text-xs font-medium transition-all border ${
                    statusFilter === f
                      ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                      : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-phantom-border">
                  <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Account</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Following</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Queued</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-phantom-border/40">
                {filteredQueue.map((row) => (
                  <tr key={row.username} className="hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="py-3 font-mono text-xs text-phantom-accent">{row.username}</td>
                    <td className="py-3 text-right font-mono text-xs text-white tabular-nums">
                      {row.following.toLocaleString()}
                      {row.following > 5900 && (
                        <span className="ml-1.5 text-phantom-danger text-[10px]">⚠</span>
                      )}
                    </td>
                    <td className="py-3 text-right font-mono text-xs text-phantom-ghost tabular-nums">{row.queued}</td>
                    <td className="py-3 text-right">
                      {row.status === "Active" ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-[10px] font-semibold">
                          <CheckCircle2 className="w-3 h-3" strokeWidth={2.5} />
                          Active
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-phantom-ghost/10 border border-phantom-border text-phantom-ghost text-[10px] font-semibold">
                          <PauseCircle className="w-3 h-3" strokeWidth={2.5} />
                          Paused
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* Follow-Back Converts */}
        <Panel label="conversions" title="Follow-Back Converts">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-phantom-border">
                  <th className="text-left text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Account</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Followed Back</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">Days</th>
                  <th className="text-right text-[11px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 font-medium">DM</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-phantom-border/40">
                {FOLLOW_BACK_CONVERTS.map((row) => (
                  <tr key={row.account} className="hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="py-3 font-mono text-xs text-phantom-accent">{row.account}</td>
                    <td className="py-3 text-right text-xs text-phantom-ghost">{row.followedBack}</td>
                    <td className="py-3 text-right font-mono text-xs text-white tabular-nums">{row.daysSince}d</td>
                    <td className="py-3 text-right">
                      {row.dmInitiated ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-phantom-accent/10 border border-phantom-accent/20 text-phantom-accent text-[10px] font-semibold">
                          Sent
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-phantom-ghost/10 border border-phantom-border text-phantom-ghost text-[10px] font-semibold">
                          No
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* Daily Unfollow Volume bar chart */}
      <Panel label="7-day trend" title="Daily Unfollow Volume">
        <div className="flex items-end gap-3 h-40 pt-4">
          {DAILY_UNFOLLOWS.map((d) => {
            const heightPct = (d.count / MAX_BAR) * 100;
            return (
              <div key={d.day} className="flex-1 flex flex-col items-center gap-2 group">
                <span className="text-[10px] text-phantom-ghost tabular-nums opacity-0 group-hover:opacity-100 transition-opacity">
                  {d.count.toLocaleString()}
                </span>
                <div className="w-full relative flex items-end" style={{ height: "80px" }}>
                  <div
                    className="w-full rounded-t bg-phantom-accent/70 hover:bg-phantom-accent transition-colors"
                    style={{ height: `${heightPct}%` }}
                  />
                </div>
                <span className="text-[10px] text-phantom-ghost">{d.day}</span>
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex items-center justify-between text-[10px] text-phantom-ghost">
          <span>0</span>
          <span>{MAX_BAR.toLocaleString()} max</span>
        </div>
      </Panel>
    </div>
  );
}
