import React from "react";
import Link from "next/link";
import { ArrowRight, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

type CellValue = true | false | string;

type CompRow = {
  category: string;
  feature: string;
  phantom: CellValue;
  onimator: CellValue;
  manual: CellValue;
  note?: string;
};

const ROWS: CompRow[] = [
  // Platforms
  {
    category: "Platform Coverage",
    feature: "Platforms supported",
    phantom: "10 (IG, Threads, Reddit, X, TikTok, Telegram, Discord, BlueSky, LinkedIn, Dating)",
    onimator: "6 (IG, TikTok, Threads, Reddit, X, Snapchat)",
    manual: "1–2 (operator-dependent)",
  },
  {
    category: "Platform Coverage",
    feature: "Accounts per phone",
    phantom: "90+",
    onimator: "20",
    manual: "1–5",
    note: "Phantom Fleet 4.5x the density of Onimator",
  },
  {
    category: "Platform Coverage",
    feature: "Simultaneous multi-platform operation",
    phantom: true,
    onimator: false,
    manual: false,
  },

  // AI + Agents
  {
    category: "AI Agents",
    feature: "AI Agent Managers",
    phantom: "Chief + Platform + 13 Specialists",
    onimator: "Basic chat bot only",
    manual: false,
  },
  {
    category: "AI Agents",
    feature: "AI-generated growth gameplan",
    phantom: true,
    onimator: false,
    manual: false,
  },
  {
    category: "AI Agents",
    feature: "Autonomous platform strategy for unknown networks",
    phantom: true,
    onimator: false,
    manual: false,
  },
  {
    category: "AI Agents",
    feature: "Warming agent",
    phantom: true,
    onimator: "Manual config",
    manual: "Fully manual",
  },
  {
    category: "AI Agents",
    feature: "Recovery + replacement agents",
    phantom: true,
    onimator: false,
    manual: "Fully manual",
  },
  {
    category: "AI Agents",
    feature: "Funnel conversion attribution",
    phantom: true,
    onimator: false,
    manual: false,
  },

  // Infrastructure
  {
    category: "Infrastructure",
    feature: "24-hour intelligent cycling",
    phantom: "Platform rotation by time of day",
    onimator: false,
    manual: false,
  },
  {
    category: "Infrastructure",
    feature: "Proxy multiplexing across platforms",
    phantom: true,
    onimator: false,
    manual: false,
  },
  {
    category: "Infrastructure",
    feature: "Capacity Planner AI",
    phantom: true,
    onimator: false,
    manual: false,
    note: "Tells you exactly how many accounts your farm can sustain",
  },
  {
    category: "Infrastructure",
    feature: "Background API workers (no phone on-screen)",
    phantom: true,
    onimator: false,
    manual: false,
  },
  {
    category: "Infrastructure",
    feature: "Real device fingerprint anchoring",
    phantom: true,
    onimator: "Partial (uiautomator2)",
    manual: "N/A",
  },

  // Anti-detection
  {
    category: "Anti-Detection",
    feature: "Real-device execution (not VPS)",
    phantom: true,
    onimator: true,
    manual: "N/A",
  },
  {
    category: "Anti-Detection",
    feature: "Fleet-level cluster monitoring",
    phantom: "20-dimension continuous audit",
    onimator: false,
    manual: false,
    note: "Critical at 50+ accounts",
  },
  {
    category: "Anti-Detection",
    feature: "LogNormal distribution sampling",
    phantom: true,
    onimator: false,
    manual: false,
  },
  {
    category: "Anti-Detection",
    feature: "Cross-field fingerprint contradiction detection",
    phantom: true,
    onimator: false,
    manual: false,
  },
  {
    category: "Anti-Detection",
    feature: "Monte Carlo CI gate (10K persona test)",
    phantom: true,
    onimator: false,
    manual: false,
  },
  {
    category: "Anti-Detection",
    feature: "30-day account survival rate",
    phantom: "99.4%",
    onimator: "~85% (community-reported)",
    manual: "~70% (varies)",
  },

  // Chat
  {
    category: "Chat System",
    feature: "Context-aware chat tiers",
    phantom: "Professional / Casual / Creator / NSFW",
    onimator: "Single mode",
    manual: "Manual",
  },
  {
    category: "Chat System",
    feature: "LLM-tell filter (removes AI tells from output)",
    phantom: true,
    onimator: false,
    manual: false,
  },
  {
    category: "Chat System",
    feature: "Photo Verification AI (dating apps)",
    phantom: true,
    onimator: false,
    manual: "Manual",
  },

  // Operations
  {
    category: "Operations",
    feature: "Event-sourced audit log",
    phantom: "Full pre-execution logging",
    onimator: false,
    manual: false,
  },
  {
    category: "Operations",
    feature: "Team seats",
    phantom: "1–Unlimited",
    onimator: "1",
    manual: "N/A",
  },
  {
    category: "Operations",
    feature: "API access",
    phantom: "Fleet plan",
    onimator: false,
    manual: false,
  },
  {
    category: "Operations",
    feature: "Starting price",
    phantom: "$299/mo",
    onimator: "~$149/mo (est.)",
    manual: "$0 (time cost: high)",
  },
];

function Cell({ value, highlight }: { value: CellValue; highlight?: boolean }) {
  if (value === true) {
    return (
      <div className="flex justify-center">
        <Check
          className={cn("w-4 h-4", highlight ? "text-phantom-accent" : "text-phantom-alive")}
          strokeWidth={2.5}
        />
      </div>
    );
  }
  if (value === false) {
    return (
      <div className="flex justify-center">
        <X className="w-3.5 h-3.5 text-phantom-red/50" strokeWidth={2} />
      </div>
    );
  }
  return (
    <div
      className={cn(
        "text-xs leading-snug text-center",
        highlight ? "text-white" : "text-phantom-ghost"
      )}
    >
      {value}
    </div>
  );
}

export default function ComparisonPage() {
  let currentCategory = "";
  return (
    <>
      {/* ═══════════════════ HERO ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pt-20 pb-16 text-center">
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Competitive comparison
        </div>
        <h1 className="font-display text-5xl md:text-6xl font-bold mt-4 tracking-tight">
          Phantom Fleet vs <span className="text-phantom-ghost">the alternatives.</span>
        </h1>
        <p className="mt-6 text-lg text-phantom-ghost max-w-2xl mx-auto leading-relaxed">
          A direct comparison against Onimator — the previous generation market leader — and
          manual operation. Metrics are specific and verifiable.
        </p>
      </section>

      {/* ═══════════════════ SUMMARY CARDS ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            {
              name: "Manual Operation",
              verdict: "Highest risk",
              color: "text-phantom-red",
              borderColor: "border-phantom-red/20",
              points: [
                "Hours per day of manual work",
                "No clustering protection",
                "No scale beyond ~10 accounts",
                "0% automation",
              ],
            },
            {
              name: "Onimator",
              verdict: "Previous generation",
              color: "text-phantom-amber",
              borderColor: "border-phantom-amber/20",
              points: [
                "Real device execution (good)",
                "20 accounts per phone ceiling",
                "No fleet-level cluster detection",
                "No AI agent managers",
                "6 platforms max",
              ],
            },
            {
              name: "Phantom Fleet",
              verdict: "Current generation",
              color: "text-phantom-accent",
              borderColor: "border-phantom-accent/30",
              points: [
                "90+ accounts per phone",
                "10 platforms, one dashboard",
                "24h autonomous cycling",
                "15-agent mesh, zero manual work",
                "Fleet-scale cluster monitoring",
              ],
            },
          ].map((c) => (
            <div
              key={c.name}
              className={cn("phantom-panel p-6 border", c.borderColor)}
            >
              <div className="text-[10px] uppercase tracking-[0.12em] font-mono text-phantom-ghost mb-2">
                {c.name}
              </div>
              <div className={cn("font-display font-bold text-lg mb-4", c.color)}>
                {c.verdict}
              </div>
              <ul className="space-y-2">
                {c.points.map((p) => (
                  <li key={p} className="text-xs text-phantom-ghost leading-snug">
                    — {p}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* ═══════════════════ FULL TABLE ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-24">
        <div className="phantom-panel overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                <th className="px-6 py-5 text-left text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                  Feature
                </th>
                <th className="px-5 py-5 text-center text-[10px] uppercase tracking-[0.15em] font-medium w-[220px] bg-phantom-accent/5">
                  <span className="phantom-accent-text">Phantom Fleet</span>
                </th>
                <th className="px-5 py-5 text-center text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium w-[200px]">
                  Onimator
                </th>
                <th className="px-5 py-5 text-center text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium w-[160px]">
                  Manual
                </th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row, i) => {
                const showCategory = row.category !== currentCategory;
                currentCategory = row.category;
                return (
                  <React.Fragment key={i}>
                    {showCategory && (
                      <tr>
                        <td colSpan={4} className="px-6 pt-6 pb-2">
                          <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost/60 font-medium">
                            {row.category}
                          </div>
                        </td>
                      </tr>
                    )}
                    <tr
                      className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/20"
                    >
                      <td className="px-6 py-3">
                        <div className="text-sm">{row.feature}</div>
                        {row.note && (
                          <div className="text-[10px] text-phantom-ghost/50 font-mono mt-0.5">
                            {row.note}
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3 bg-phantom-accent/[0.03]">
                        <Cell value={row.phantom} highlight />
                      </td>
                      <td className="px-5 py-3">
                        <Cell value={row.onimator} />
                      </td>
                      <td className="px-5 py-3">
                        <Cell value={row.manual} />
                      </td>
                    </tr>
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-4 text-[10px] text-phantom-ghost/50 font-mono text-center">
          Onimator figures based on public documentation and community benchmarks as of Q1 2026.
          Manual figures are illustrative. All Phantom Fleet figures are production-validated.
        </div>
      </section>

      {/* ═══════════════════ KEY DIFFERENTIATOR CALLOUTS ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-24">
        <div className="text-center mb-10">
          <h2 className="font-display text-3xl font-bold tracking-tight">
            The gaps that matter at scale.
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            {
              metric: "4.5x",
              label: "More accounts per phone",
              detail:
                "90+ vs Onimator's 20. Same hardware. Same proxies. The density gap compounds directly into revenue.",
            },
            {
              metric: "10",
              label: "Platforms vs 6",
              detail:
                "LinkedIn, BlueSky, Discord, and dating apps are unavailable in Onimator. Phantom Fleet covers them all from day one.",
            },
            {
              metric: "0",
              label: "Manual daily tasks required",
              detail:
                "15 autonomous agents handle every routine operation. Onimator still requires manual warming configuration, target lists, and recovery.",
            },
            {
              metric: "20",
              label: "Fingerprint dimensions monitored",
              detail:
                "Continuous fleet-level cluster audit. Onimator has no cluster detection. One statistical anomaly costs you a hundred accounts.",
            },
            {
              metric: "24h",
              label: "Autonomous cycling",
              detail:
                "Phantom Fleet decides which platform runs when based on proxy windows, platform peaks, and account health. Onimator runs one platform at a time.",
            },
            {
              metric: "99.4%",
              label: "30-day account survival",
              detail:
                "Production benchmark across the beta fleet. Onimator community benchmarks average ~85% with manual warming. The gap is the cluster detection layer.",
            },
          ].map((d) => (
            <div key={d.label} className="phantom-panel p-6">
              <div className="phantom-metric text-5xl phantom-accent-text mb-2">{d.metric}</div>
              <div className="font-display font-semibold text-sm mb-2">{d.label}</div>
              <div className="text-xs text-phantom-ghost leading-relaxed">{d.detail}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ═══════════════════ CTA ═══════════════════ */}
      <section className="max-w-4xl mx-auto px-6 pb-28 text-center">
        <div className="phantom-panel-accent p-12 relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-phantom-accent/5 via-transparent to-transparent pointer-events-none" />
          <div className="relative">
            <h2 className="font-display text-3xl md:text-4xl font-bold tracking-tight mb-4">
              Stop operating the 2023 playbook.
            </h2>
            <p className="text-phantom-ghost max-w-lg mx-auto mb-8 leading-relaxed">
              Phantom Fleet is the platform built for how social media automation actually works
              in 2026 — cross-platform, agent-driven, and statistically indistinguishable from
              real users at scale.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-4">
              <Link
                href="/pricing"
                className="group px-7 flex items-center gap-2 rounded-lg bg-phantom-accent text-phantom-bg font-semibold text-sm shadow-[0_0_48px_hsl(162_100%_54%/0.4)] hover:shadow-[0_0_72px_hsl(162_100%_54%/0.6)] transition-shadow"
                style={{ height: "3.25rem" }}
              >
                Start Free Trial
                <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
              </Link>
              <Link
                href="/features"
                className="px-7 flex items-center rounded-lg border border-phantom-border text-sm font-medium hover:bg-phantom-panelHi/50 transition-colors"
                style={{ height: "3.25rem" }}
              >
                See All Features
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
