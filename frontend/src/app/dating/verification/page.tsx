"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type VerifyStatus = "waiting_sim" | "verifying" | "complete" | "failed";
type SimStatus    = "available" | "in_use" | "cooldown";

const VERIFY_STATUS_STYLES: Record<VerifyStatus, { bg: string; text: string; border: string; label: string }> = {
  waiting_sim: { bg: "bg-phantom-amber/10",  text: "text-phantom-amber",  border: "border-phantom-amber/20",  label: "WAITING SIM" },
  verifying:   { bg: "bg-phantom-accent/10", text: "text-phantom-accent", border: "border-phantom-accent/20", label: "VERIFYING"   },
  complete:    { bg: "bg-phantom-alive/10",  text: "text-phantom-alive",  border: "border-phantom-alive/20",  label: "COMPLETE"    },
  failed:      { bg: "bg-phantom-red/10",    text: "text-phantom-red",    border: "border-phantom-red/20",    label: "FAILED"      },
};

const SIM_STATUS_STYLES: Record<SimStatus, { bg: string; text: string; border: string; dot: string }> = {
  available: { bg: "bg-phantom-alive/10",  text: "text-phantom-alive",  border: "border-phantom-alive/20",  dot: "bg-phantom-alive"  },
  in_use:    { bg: "bg-phantom-accent/10", text: "text-phantom-accent", border: "border-phantom-accent/20", dot: "bg-phantom-accent animate-pulse" },
  cooldown:  { bg: "bg-phantom-amber/10",  text: "text-phantom-amber",  border: "border-phantom-amber/20",  dot: "bg-phantom-amber"  },
};

const VERIFY_QUEUE = [
  { id: "v1",  account: "TinderAcc_14",  platform: "Tinder",  status: "verifying"   as VerifyStatus, sim: "SIM-02", startedAt: "09:41", elapsed: "1m 24s", attempts: 1 },
  { id: "v2",  account: "BumbleAcc_07",  platform: "Bumble",  status: "verifying"   as VerifyStatus, sim: "SIM-05", startedAt: "09:42", elapsed: "0m 53s", attempts: 1 },
  { id: "v3",  account: "HingeAcc_21",   platform: "Hinge",   status: "waiting_sim" as VerifyStatus, sim: "—",      startedAt: "—",     elapsed: "—",      attempts: 0 },
  { id: "v4",  account: "GrindrAcc_09",  platform: "Grindr",  status: "waiting_sim" as VerifyStatus, sim: "—",      startedAt: "—",     elapsed: "—",      attempts: 0 },
  { id: "v5",  account: "TinderAcc_38",  platform: "Tinder",  status: "waiting_sim" as VerifyStatus, sim: "—",      startedAt: "—",     elapsed: "—",      attempts: 0 },
  { id: "v6",  account: "BumbleAcc_29",  platform: "Bumble",  status: "complete"    as VerifyStatus, sim: "SIM-01", startedAt: "09:34", elapsed: "2m 48s", attempts: 1 },
  { id: "v7",  account: "HingeAcc_06",   platform: "Hinge",   status: "complete"    as VerifyStatus, sim: "SIM-07", startedAt: "09:28", elapsed: "3m 12s", attempts: 1 },
  { id: "v8",  account: "TinderAcc_22",  platform: "Tinder",  status: "failed"      as VerifyStatus, sim: "SIM-04", startedAt: "09:19", elapsed: "5m 00s", attempts: 3 },
];

const SIM_POOL: {
  id: string; slot: number; carrier: string; number: string;
  status: SimStatus; lastUsed: string; totalUses: number;
}[] = [
  { id: "s1",  slot: 1,  carrier: "T-Mobile",  number: "+1 (646) ***-**14", status: "in_use",   lastUsed: "now",      totalUses: 214 },
  { id: "s2",  slot: 2,  carrier: "AT&T",       number: "+1 (212) ***-**87", status: "in_use",   lastUsed: "now",      totalUses: 189 },
  { id: "s3",  slot: 3,  carrier: "Verizon",    number: "+1 (917) ***-**31", status: "cooldown", lastUsed: "4m ago",   totalUses: 302 },
  { id: "s4",  slot: 4,  carrier: "T-Mobile",   number: "+1 (646) ***-**62", status: "cooldown", lastUsed: "8m ago",   totalUses: 156 },
  { id: "s5",  slot: 5,  carrier: "AT&T",       number: "+1 (415) ***-**09", status: "in_use",   lastUsed: "now",      totalUses: 241 },
  { id: "s6",  slot: 6,  carrier: "Verizon",    number: "+1 (310) ***-**55", status: "available",lastUsed: "12m ago",  totalUses: 98  },
  { id: "s7",  slot: 7,  carrier: "T-Mobile",   number: "+1 (773) ***-**40", status: "in_use",   lastUsed: "now",      totalUses: 178 },
  { id: "s8",  slot: 8,  carrier: "AT&T",       number: "+1 (404) ***-**73", status: "available",lastUsed: "18m ago",  totalUses: 67  },
  { id: "s9",  slot: 9,  carrier: "Verizon",    number: "+1 (512) ***-**28", status: "available",lastUsed: "25m ago",  totalUses: 44  },
  { id: "s10", slot: 10, carrier: "T-Mobile",   number: "+1 (702) ***-**16", status: "available",lastUsed: "31m ago",  totalUses: 33  },
  { id: "s11", slot: 11, carrier: "AT&T",       number: "+1 (818) ***-**94", status: "cooldown", lastUsed: "3m ago",   totalUses: 127 },
  { id: "s12", slot: 12, carrier: "Verizon",    number: "+1 (214) ***-**57", status: "cooldown", lastUsed: "6m ago",   totalUses: 88  },
];

type FailReason = "wrong_code" | "timeout" | "number_banned";
const FAIL_REASON_LABELS: Record<FailReason, string> = {
  wrong_code:    "Wrong code",
  timeout:       "Timeout",
  number_banned: "Number banned",
};

const FAILED_VERIFICATIONS = [
  { id: "f1", account: "TinderAcc_22",  platform: "Tinder",  reason: "wrong_code"    as FailReason, sim: "SIM-04", failedAt: "09:24" },
  { id: "f2", account: "GrindrAcc_04",  platform: "Grindr",  reason: "number_banned" as FailReason, sim: "SIM-03", failedAt: "08:57" },
  { id: "f3", account: "BumbleAcc_14",  platform: "Bumble",  reason: "timeout"       as FailReason, sim: "SIM-08", failedAt: "08:34" },
  { id: "f4", account: "HingeAcc_33",   platform: "Hinge",   reason: "wrong_code"    as FailReason, sim: "SIM-11", failedAt: "08:12" },
  { id: "f5", account: "TinderAcc_09",  platform: "Tinder",  reason: "timeout"       as FailReason, sim: "SIM-06", failedAt: "07:48" },
];

const REASON_COLORS: Record<FailReason, string> = {
  wrong_code:    "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/20",
  timeout:       "bg-phantom-ghost/10 text-phantom-ghost border-phantom-ghost/20",
  number_banned: "bg-phantom-red/10 text-phantom-red border-phantom-red/20",
};

const PLATFORM_TAGS: Record<string, string> = {
  Tinder: "bg-phantom-red/10 text-phantom-red border-phantom-red/20",
  Bumble: "bg-phantom-amber/10 text-phantom-amber border-phantom-amber/20",
  Hinge:  "bg-phantom-magenta/10 text-phantom-magenta border-phantom-magenta/20",
  Grindr: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function VerificationQueuePage() {
  const simsAvailable = SIM_POOL.filter((s) => s.status === "available").length;
  const simsInUse     = SIM_POOL.filter((s) => s.status === "in_use").length;
  const simsCooldown  = SIM_POOL.filter((s) => s.status === "cooldown").length;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Dating · verification
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <ShieldCheck className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Verification <span className="phantom-accent-text">Queue</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          SIM-based phone verification for new dating profiles across Tinder, Bumble, Hinge, and
          Grindr. 12-SIM pool with automatic rotation and cooldown management.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="SIMs Available"      value={`${simsAvailable}/12`}  sub={`${simsInUse} in use · ${simsCooldown} cooldown`} accent />
        <KPICard label="Pending Verifications" value="14"  sub="in queue"                                                               />
        <KPICard label="Completed Today"     value="6"    delta={0.2}                                                                  />
        <KPICard label="Avg Verify Time"     value="3.2 min" sub="per verification"                                                    />
      </div>

      {/* Verification Queue Table */}
      <Panel label="queue" title="Verification Queue" subtitle="Active and pending phone verification tasks">
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {["Account", "Platform", "Status", "SIM", "Started At", "Elapsed", "Attempts"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {VERIFY_QUEUE.map((row) => {
                const s = VERIFY_STATUS_STYLES[row.status];
                return (
                  <tr key={row.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors">
                    <td className="px-3 py-3 font-mono text-xs text-phantom-accent">{row.account}</td>
                    <td className="px-3 py-3">
                      <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", PLATFORM_TAGS[row.platform])}>
                        {row.platform}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", s.bg, s.text, s.border)}>
                        {s.label}
                      </span>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-phantom-ghost">{row.sim}</td>
                    <td className="px-3 py-3 tabular-nums text-xs text-phantom-ghost">{row.startedAt}</td>
                    <td className="px-3 py-3 tabular-nums text-xs font-medium">
                      {row.elapsed === "—" ? <span className="text-phantom-ghost">—</span> : row.elapsed}
                    </td>
                    <td className="px-3 py-3 tabular-nums text-xs">
                      <span className={cn(row.attempts >= 3 ? "text-phantom-red font-bold" : "text-phantom-ghost")}>
                        {row.attempts}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* SIM Pool + Failed Verifications */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* SIM Pool */}
        <div className="lg:col-span-2">
          <Panel label="hardware" title="SIM Pool" subtitle="12 SIM slots — live status, carrier, usage">
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
              {SIM_POOL.map((sim) => {
                const s = SIM_STATUS_STYLES[sim.status];
                return (
                  <div key={sim.id} className={cn("rounded-xl p-3 border space-y-2", s.bg, s.border)}>
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold text-phantom-ghost">SIM-{String(sim.slot).padStart(2, "0")}</span>
                      <span className={cn("w-2 h-2 rounded-full flex-shrink-0", s.dot)} />
                    </div>
                    <div className={cn("text-xs font-bold", s.text)}>
                      {sim.status === "in_use" ? "IN USE" : sim.status === "cooldown" ? "COOLDOWN" : "AVAILABLE"}
                    </div>
                    <div className="text-[10px] text-phantom-ghost">{sim.carrier}</div>
                    <div className="text-[10px] font-mono text-phantom-ghost">{sim.number}</div>
                    <div className="flex items-center justify-between pt-1 border-t border-phantom-border/30">
                      <span className="text-[10px] text-phantom-ghost">{sim.lastUsed}</span>
                      <span className="text-[10px] text-phantom-ghost tabular-nums">{sim.totalUses} uses</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>

        {/* Failed Verifications */}
        <div>
          <Panel label="failures" title="Recent Failures" subtitle="Last 5 failed verifications">
            <div className="space-y-3">
              {FAILED_VERIFICATIONS.map((f) => (
                <div key={f.id} className="p-3 rounded-lg bg-phantom-red/5 border border-phantom-red/20 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-phantom-accent">{f.account}</span>
                    <span className="text-[10px] text-phantom-ghost tabular-nums">{f.failedAt}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border", PLATFORM_TAGS[f.platform])}>
                      {f.platform}
                    </span>
                    <span className="text-[10px] text-phantom-ghost">{f.sim}</span>
                  </div>
                  <div className={cn("px-2 py-0.5 rounded-full text-[10px] font-bold border inline-block", REASON_COLORS[f.reason])}>
                    {FAIL_REASON_LABELS[f.reason]}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
