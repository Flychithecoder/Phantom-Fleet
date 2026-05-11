"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { FlaskConical, Plus, Trophy, TrendingUp, Clock, Users } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type TestType = "dm_opener" | "note" | "bio" | "cta" | "caption";
type TestStatus = "active" | "completed" | "paused";

type ABTest = {
  id: string;
  name: string;
  type: TestType;
  variantA: string;
  variantB: string;
  accountsPerVariant: number;
  startedDate: string;
  currentWinner: "A" | "B" | "tie" | null;
  confidence: number | null;
  status: TestStatus;
  metricsA: { sent: number; replied: number; converted: number; revenue: number };
  metricsB: { sent: number; replied: number; converted: number; revenue: number };
  lift?: number;
};

const TESTS: ABTest[] = [
  {
    id: "t1",
    name: "DM Opener — Hey vs Hey Girl",
    type: "dm_opener",
    variantA: '"hey 👋"',
    variantB: '"hey girl 💕"',
    accountsPerVariant: 214,
    startedDate: "Apr 8",
    currentWinner: "B",
    confidence: 94.2,
    status: "active",
    metricsA: { sent: 4284, replied: 642,  converted: 71,  revenue: 1065 },
    metricsB: { sent: 4301, replied: 817,  converted: 104, revenue: 1560 },
  },
  {
    id: "t2",
    name: "Note Mood — Curious vs Playful",
    type: "note",
    variantA: "Curious tone (question-led)",
    variantB: "Playful tone (emoji-heavy)",
    accountsPerVariant: 183,
    startedDate: "Apr 9",
    currentWinner: "A",
    confidence: 81.7,
    status: "active",
    metricsA: { sent: 3660, replied: 549, converted: 62, revenue: 930 },
    metricsB: { sent: 3660, replied: 476, converted: 51, revenue: 765 },
  },
  {
    id: "t3",
    name: "Bio Link Placement — Top vs Bottom",
    type: "bio",
    variantA: "Link in first line",
    variantB: "Link at bottom after CTA",
    accountsPerVariant: 210,
    startedDate: "Apr 6",
    currentWinner: "B",
    confidence: 97.1,
    status: "active",
    metricsA: { sent: 4200, replied: 504, converted: 55, revenue: 825  },
    metricsB: { sent: 4200, replied: 630, converted: 84, revenue: 1260 },
  },
  {
    id: "t4",
    name: "CTA Urgency — Now vs Today Only",
    type: "cta",
    variantA: '"check it out now"',
    variantB: '"today only 🔥"',
    accountsPerVariant: 120,
    startedDate: "Apr 10",
    currentWinner: null,
    confidence: 48.3,
    status: "active",
    metricsA: { sent: 2400, replied: 312, converted: 32, revenue: 480 },
    metricsB: { sent: 2400, replied: 336, converted: 37, revenue: 555 },
  },
  {
    id: "t5",
    name: "Caption Length — Short vs Long",
    type: "caption",
    variantA: "Short caption (< 50 chars)",
    variantB: "Long caption (150–200 chars)",
    accountsPerVariant: 195,
    startedDate: "Mar 31",
    currentWinner: "A",
    confidence: 99.1,
    status: "completed",
    metricsA: { sent: 5850, replied: 878, converted: 97,  revenue: 1455 },
    metricsB: { sent: 5850, replied: 643, converted: 68,  revenue: 1020 },
    lift: 42.6,
  },
  {
    id: "t6",
    name: "DM Opener — Name Drop vs Generic",
    type: "dm_opener",
    variantA: "Personalized with username",
    variantB: "Generic opener only",
    accountsPerVariant: 240,
    startedDate: "Apr 2",
    currentWinner: "A",
    confidence: 99.8,
    status: "completed",
    metricsA: { sent: 7200, replied: 1296, converted: 162, revenue: 2430 },
    metricsB: { sent: 7200, replied: 864,  converted: 104, revenue: 1560 },
    lift: 55.8,
  },
  {
    id: "t7",
    name: "Note Timing — AM vs PM",
    type: "note",
    variantA: "Post between 8–10am local",
    variantB: "Post between 7–9pm local",
    accountsPerVariant: 200,
    startedDate: "Mar 28",
    currentWinner: "B",
    confidence: 96.4,
    status: "completed",
    metricsA: { sent: 6000, replied: 780,  converted: 88,  revenue: 1320 },
    metricsB: { sent: 6000, replied: 1020, converted: 122, revenue: 1830 },
    lift: 38.6,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function TypeBadge({ type }: { type: TestType }) {
  const map: Record<TestType, { label: string; cls: string }> = {
    dm_opener: { label: "DM Opener", cls: "bg-phantom-magenta/10 border-phantom-magenta/20 text-phantom-magenta" },
    note:      { label: "Note",      cls: "bg-phantom-accent/10 border-phantom-accent/20 text-phantom-accent"   },
    bio:       { label: "Bio",       cls: "bg-phantom-amber/10 border-phantom-amber/20 text-phantom-amber"      },
    cta:       { label: "CTA",       cls: "bg-phantom-alive/10 border-phantom-alive/20 text-phantom-alive"      },
    caption:   { label: "Caption",   cls: "bg-blue-400/10 border-blue-400/20 text-blue-400"                    },
  };
  const { label, cls } = map[type];
  return (
    <span className={cn("px-2 py-0.5 rounded-full border text-[10px] font-semibold whitespace-nowrap", cls)}>
      {label}
    </span>
  );
}

function WinnerBadge({
  winner,
  confidence,
}: {
  winner: ABTest["currentWinner"];
  confidence: ABTest["confidence"];
}) {
  if (!winner || winner === "tie") {
    return <span className="text-[10px] text-phantom-ghost">No winner yet</span>;
  }
  const cls =
    winner === "A"
      ? "bg-phantom-accent/10 border-phantom-accent/20 text-phantom-accent"
      : "bg-phantom-magenta/10 border-phantom-magenta/20 text-phantom-magenta";
  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold", cls)}>
      <Trophy className="w-3 h-3" />
      Variant {winner}
      {confidence !== null && <span className="opacity-60">({confidence}%)</span>}
    </span>
  );
}

function MetricBar({
  labelA,
  valA,
  labelB,
  valB,
  maxVal,
}: {
  labelA: string;
  valA: number;
  labelB: string;
  valB: number;
  maxVal: number;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-phantom-ghost w-6 shrink-0">A</span>
        <div className="flex-1 h-5 bg-phantom-border/30 rounded overflow-hidden relative">
          <div
            className="h-full rounded bg-phantom-accent/60"
            style={{ width: `${(valA / maxVal) * 100}%` }}
          />
          <span className="absolute inset-0 flex items-center pl-2 text-[10px] font-mono text-white/80">
            {labelA}
          </span>
        </div>
        <span className="text-[10px] tabular-nums font-mono text-phantom-accent w-14 text-right shrink-0">
          {valA.toLocaleString()}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-phantom-ghost w-6 shrink-0">B</span>
        <div className="flex-1 h-5 bg-phantom-border/30 rounded overflow-hidden relative">
          <div
            className="h-full rounded bg-phantom-magenta/50"
            style={{ width: `${(valB / maxVal) * 100}%` }}
          />
          <span className="absolute inset-0 flex items-center pl-2 text-[10px] font-mono text-white/80">
            {labelB}
          </span>
        </div>
        <span className="text-[10px] tabular-nums font-mono text-phantom-magenta w-14 text-right shrink-0">
          {valB.toLocaleString()}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ABTestPage() {
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "completed">("all");

  const activeTests    = TESTS.filter((t) => t.status === "active");
  const completedTests = TESTS.filter((t) => t.status === "completed");
  const completedWithLift = completedTests.filter((t) => t.lift !== undefined);
  const avgLift =
    completedWithLift.reduce((s, t) => s + (t.lift ?? 0), 0) / completedWithLift.length;

  const topTest = TESTS.find((t) => t.id === "t1")!;

  const filteredTests =
    statusFilter === "all"
      ? TESTS
      : TESTS.filter((t) => t.status === statusFilter);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Instagram · conversion optimization
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <FlaskConical className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            A/B <span className="phantom-accent-text">Testing</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-accent/10 border border-phantom-accent/20 text-phantom-accent text-xs font-semibold">
            {activeTests.length} active tests
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Split-test DM openers, note tones, bio layouts, and CTA copy across account cohorts to find the highest-converting variants before fleet-wide rollout.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Active Tests"
          value={String(activeTests.length)}
          sub="running now"
          accent
        />
        <KPICard
          label="Completed Tests"
          value={String(completedTests.length)}
          sub="with winner declared"
        />
        <KPICard
          label="Avg Lift (Winning)"
          value={`${avgLift.toFixed(1)}%`}
          sub="reply rate vs control"
          delta={0.45}
        />
        <KPICard
          label="Tests Run This Month"
          value="7"
          sub="Apr 2026"
          delta={0.167}
        />
      </div>

      {/* Featured test — top result detail */}
      <Panel
        label="featured test"
        title={
          <>
            Top Active Test: <span className="phantom-accent-text">DM Opener</span>
          </>
        }
        subtitle={`${topTest.name} · ${topTest.accountsPerVariant * 2} total accounts · started ${topTest.startedDate}`}
        accent
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Variant descriptions + confidence */}
          <div className="space-y-4">
            <div className="rounded-lg border border-phantom-border bg-phantom-bg p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost font-medium">
                  Variant A (Control)
                </span>
                <span className="text-[10px] text-phantom-ghost font-mono">
                  {topTest.accountsPerVariant} accounts
                </span>
              </div>
              <div className="text-lg font-bold text-white font-mono">{topTest.variantA}</div>
              <div className="text-[11px] text-phantom-ghost">Simple greeting, no gender assumption</div>
            </div>

            <div className="rounded-lg border border-phantom-magenta/20 bg-phantom-magenta/5 p-4 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost font-medium">
                    Variant B
                  </span>
                  <Trophy className="w-3.5 h-3.5 text-phantom-amber" />
                </div>
                <span className="text-[10px] text-phantom-ghost font-mono">
                  {topTest.accountsPerVariant} accounts
                </span>
              </div>
              <div className="text-lg font-bold text-phantom-magenta font-mono">{topTest.variantB}</div>
              <div className="text-[11px] text-phantom-ghost">Warmer, persona-matched feminine tone</div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-phantom-ghost">Statistical confidence</span>
                <span className="text-phantom-alive font-bold tabular-nums">{topTest.confidence}%</span>
              </div>
              <div className="h-2 bg-phantom-border/30 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-phantom-amber via-phantom-accent to-phantom-alive transition-all"
                  style={{ width: `${topTest.confidence}%` }}
                />
              </div>
              <div className="flex justify-between text-[9px] text-phantom-ghost/60">
                <span>0%</span>
                <span className="text-phantom-ghost">80% threshold</span>
                <span>100%</span>
              </div>
            </div>
          </div>

          {/* Metric bar comparisons */}
          <div className="space-y-5">
            <div>
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-2 font-medium">
                Send Count
              </div>
              <MetricBar
                labelA="A sends"
                valA={topTest.metricsA.sent}
                labelB="B sends"
                valB={topTest.metricsB.sent}
                maxVal={Math.max(topTest.metricsA.sent, topTest.metricsB.sent)}
              />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost font-medium">Reply Rate</span>
                <span className="text-[10px] text-phantom-alive">
                  A: {((topTest.metricsA.replied / topTest.metricsA.sent) * 100).toFixed(1)}%
                  &nbsp;·&nbsp;
                  B: {((topTest.metricsB.replied / topTest.metricsB.sent) * 100).toFixed(1)}%
                </span>
              </div>
              <MetricBar
                labelA="A replies"
                valA={topTest.metricsA.replied}
                labelB="B replies"
                valB={topTest.metricsB.replied}
                maxVal={Math.max(topTest.metricsA.replied, topTest.metricsB.replied)}
              />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost font-medium">
                  Conversion Rate
                </span>
                <span className="text-[10px] text-phantom-alive">
                  A: {((topTest.metricsA.converted / topTest.metricsA.sent) * 100).toFixed(2)}%
                  &nbsp;·&nbsp;
                  B: {((topTest.metricsB.converted / topTest.metricsB.sent) * 100).toFixed(2)}%
                </span>
              </div>
              <MetricBar
                labelA="A converts"
                valA={topTest.metricsA.converted}
                labelB="B converts"
                valB={topTest.metricsB.converted}
                maxVal={Math.max(topTest.metricsA.converted, topTest.metricsB.converted)}
              />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-2 font-medium">
                Revenue Attribution
              </div>
              <MetricBar
                labelA={`$${topTest.metricsA.revenue.toLocaleString()}`}
                valA={topTest.metricsA.revenue}
                labelB={`$${topTest.metricsB.revenue.toLocaleString()}`}
                valB={topTest.metricsB.revenue}
                maxVal={Math.max(topTest.metricsA.revenue, topTest.metricsB.revenue)}
              />
            </div>

            {/* Projected lift callout */}
            <div className="rounded-lg bg-phantom-alive/5 border border-phantom-alive/20 px-4 py-3">
              <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em] font-medium mb-1">
                Monthly revenue delta if B deployed fleet-wide
              </div>
              <div className="text-2xl font-bold text-phantom-alive tabular-nums">
                +$
                {Math.round(
                  ((topTest.metricsB.revenue - topTest.metricsA.revenue) /
                    topTest.accountsPerVariant) *
                    847 *
                    30
                ).toLocaleString()}
              </div>
              <div className="text-[10px] text-phantom-ghost mt-1">
                Extrapolated across 847 accounts · 30 days
              </div>
            </div>
          </div>
        </div>
      </Panel>

      {/* All tests table */}
      <Panel
        label="all tests"
        title="Test Registry"
        actions={
          <div className="flex items-center gap-2">
            <div className="flex gap-1.5">
              {(["all", "active", "completed"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={cn(
                    "px-3 py-1 rounded text-xs font-medium transition-all border",
                    statusFilter === f
                      ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                      : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                  )}
                >
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
            </div>
            <button
              disabled
              title="New test creation coming soon"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-phantom-border text-phantom-ghost cursor-not-allowed opacity-40"
            >
              <Plus className="w-3.5 h-3.5" />
              New Test
            </button>
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                {[
                  "Test Name",
                  "Type",
                  "Variants",
                  "Accts / Side",
                  "Started",
                  "Winner",
                  "Confidence",
                  "Status",
                ].map((h) => (
                  <th
                    key={h}
                    className="text-left text-[10px] uppercase tracking-[0.12em] text-phantom-ghost pb-3 pr-4 font-medium whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-phantom-border/40">
              {filteredTests.map((test) => (
                <tr
                  key={test.id}
                  className={cn(
                    "hover:bg-phantom-panelHi/30 transition-colors",
                    test.status === "completed" && "opacity-80"
                  )}
                >
                  <td className="py-3 pr-4 text-xs font-semibold text-white whitespace-nowrap max-w-[200px] truncate">
                    {test.name}
                  </td>
                  <td className="py-3 pr-4">
                    <TypeBadge type={test.type} />
                  </td>
                  <td className="py-3 pr-4">
                    <div className="text-[10px] space-y-0.5">
                      <div className="text-phantom-accent font-mono truncate max-w-[130px]">
                        A: {test.variantA}
                      </div>
                      <div className="text-phantom-magenta font-mono truncate max-w-[130px]">
                        B: {test.variantB}
                      </div>
                    </div>
                  </td>
                  <td className="py-3 pr-4 text-xs tabular-nums font-mono text-phantom-ghost">
                    <div className="flex items-center gap-1">
                      <Users className="w-3 h-3" />
                      {test.accountsPerVariant}
                    </div>
                  </td>
                  <td className="py-3 pr-4 text-xs text-phantom-ghost whitespace-nowrap">
                    <div className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {test.startedDate}
                    </div>
                  </td>
                  <td className="py-3 pr-4">
                    <WinnerBadge winner={test.currentWinner} confidence={test.confidence} />
                  </td>
                  <td className="py-3 pr-4">
                    {test.confidence !== null ? (
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-phantom-border/30 rounded-full overflow-hidden">
                          <div
                            className={cn(
                              "h-full rounded-full",
                              test.confidence >= 95
                                ? "bg-phantom-alive"
                                : test.confidence >= 80
                                ? "bg-phantom-amber"
                                : "bg-phantom-ghost/40"
                            )}
                            style={{ width: `${test.confidence}%` }}
                          />
                        </div>
                        <span className="text-[10px] tabular-nums text-phantom-ghost">
                          {test.confidence}%
                        </span>
                      </div>
                    ) : (
                      <span className="text-[10px] text-phantom-ghost">—</span>
                    )}
                  </td>
                  <td className="py-3">
                    {test.status === "active" ? (
                      <span className="px-2 py-0.5 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-[10px] font-semibold">
                        Active
                      </span>
                    ) : test.status === "completed" ? (
                      <div className="space-y-0.5">
                        <span className="px-2 py-0.5 rounded-full bg-phantom-ghost/10 border border-phantom-border text-phantom-ghost text-[10px] font-semibold">
                          Completed
                        </span>
                        {test.lift !== undefined && (
                          <div className="flex items-center gap-1 text-[10px] text-phantom-alive font-semibold">
                            <TrendingUp className="w-3 h-3" />+{test.lift}% lift
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full bg-phantom-amber/10 border border-phantom-amber/20 text-phantom-amber text-[10px] font-semibold">
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

      {/* Completed tests results */}
      <Panel
        label="completed tests"
        title="Completed Test Results"
        subtitle="Finalized tests with declared winners and measured reply-rate lift"
      >
        <div className="space-y-4">
          {completedTests.map((test) => {
            const replyRateA = ((test.metricsA.replied / test.metricsA.sent) * 100).toFixed(1);
            const replyRateB = ((test.metricsB.replied / test.metricsB.sent) * 100).toFixed(1);
            const convRateA  = ((test.metricsA.converted / test.metricsA.sent) * 100).toFixed(2);
            const convRateB  = ((test.metricsB.converted / test.metricsB.sent) * 100).toFixed(2);
            const winner     = test.currentWinner;
            return (
              <div
                key={test.id}
                className="rounded-lg border border-phantom-border bg-phantom-bg p-5 hover:border-phantom-accent/20 transition-colors"
              >
                <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
                  <div>
                    <div className="text-sm font-semibold text-white">{test.name}</div>
                    <div className="flex items-center gap-2 mt-1">
                      <TypeBadge type={test.type} />
                      <span className="text-[10px] text-phantom-ghost font-mono">
                        {test.startedDate} · {test.accountsPerVariant * 2} accounts total
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {test.lift !== undefined && (
                      <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-phantom-alive/10 border border-phantom-alive/20">
                        <TrendingUp className="w-3.5 h-3.5 text-phantom-alive" />
                        <span className="text-phantom-alive text-xs font-bold tabular-nums">
                          +{test.lift}% lift
                        </span>
                      </div>
                    )}
                    <WinnerBadge winner={winner} confidence={test.confidence} />
                  </div>
                </div>

                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {[
                    { label: "Reply Rate A", val: `${replyRateA}%`, hilite: winner === "A" },
                    { label: "Reply Rate B", val: `${replyRateB}%`, hilite: winner === "B" },
                    { label: "Conv. Rate A", val: `${convRateA}%`,  hilite: winner === "A" },
                    { label: "Conv. Rate B", val: `${convRateB}%`,  hilite: winner === "B" },
                  ].map(({ label, val, hilite }) => (
                    <div
                      key={label}
                      className={cn(
                        "rounded-lg border p-3 text-center",
                        hilite
                          ? "border-phantom-alive/30 bg-phantom-alive/5"
                          : "border-phantom-border bg-phantom-panelHi"
                      )}
                    >
                      <div className="text-[9px] uppercase tracking-[0.12em] text-phantom-ghost mb-1">
                        {label}
                      </div>
                      <div
                        className={cn(
                          "text-base font-bold tabular-nums",
                          hilite ? "text-phantom-alive" : "text-phantom-ghost"
                        )}
                      >
                        {val}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Revenue bar comparison inline */}
                <div className="mt-4 pt-3 border-t border-phantom-border/50">
                  <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost mb-2 font-medium">
                    Revenue Attribution
                  </div>
                  <MetricBar
                    labelA={`$${test.metricsA.revenue.toLocaleString()}`}
                    valA={test.metricsA.revenue}
                    labelB={`$${test.metricsB.revenue.toLocaleString()}`}
                    valB={test.metricsB.revenue}
                    maxVal={Math.max(test.metricsA.revenue, test.metricsB.revenue)}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
