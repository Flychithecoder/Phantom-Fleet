import Link from "next/link";
import { ArrowRight, Zap, Shield, Bot, BarChart3, Clock, Smartphone } from "lucide-react";
import { AnimatedHeroBg } from "@/components/animated-hero-bg";
import { PlatformGrid } from "@/components/platform-grid";

const STATS = [
  { value: "10", label: "Platforms", sub: "one unified dashboard" },
  { value: "90+", label: "Accounts / Phone", sub: "industry record density" },
  { value: "24h", label: "Autonomous", sub: "intelligent cycling" },
  { value: "151", label: "Tests Passing", sub: "engineering integrity" },
];

const PILLARS = [
  {
    icon: Bot,
    title: "AI Agent Managers",
    body: "Hierarchical agent mesh — Chief Agent, Platform Managers, Specialists. Build your growth gameplan on any platform without needing to know it.",
  },
  {
    icon: Clock,
    title: "24-Hour Fleet Cycling",
    body: "Multiplexes your proxy infrastructure across platforms by time of day. Reddit at 2pm, LinkedIn at 9am, dating at 8pm. Zero idle hardware.",
  },
  {
    icon: Shield,
    title: "Real Device Fingerprinting",
    body: "Every account is anchored to a real physical device — not a VPS. Platform ML sees genuine hardware signals, not a datacenter.",
  },
  {
    icon: Smartphone,
    title: "90+ Accounts Per Phone",
    body: "Competitors cap at 20. Phantom Fleet's density tech runs 90+ production accounts per device with full isolation and zero cross-account bleed.",
  },
  {
    icon: BarChart3,
    title: "Capacity Planner AI",
    body: "Tell it your farm size. It tells you exactly how many accounts you can sustain, per platform, per proxy tier, per warming stage.",
  },
  {
    icon: Zap,
    title: "Context-Aware Chat Tiers",
    body: "Professional mode for LinkedIn. Casual for Reddit. NSFW for dating apps. One system, every context — automatically routed by platform.",
  },
];

const PLATFORMS = [
  "Instagram", "Threads", "Reddit", "X / Twitter", "TikTok",
  "Telegram", "Discord", "BlueSky", "LinkedIn", "Dating Apps",
];

export default function MarketingHomePage() {
  return (
    <>
      {/* ═══════════════════════════════════════ HERO ═══════════════════════════════════════ */}
      <section className="relative overflow-hidden">
        <AnimatedHeroBg />

        {/* Radial glow behind headline */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse 60% 40% at 50% 30%, hsl(162 100% 54% / 0.07), transparent)",
          }}
        />

        <div className="relative max-w-7xl mx-auto px-6 pt-28 pb-36 text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-phantom-border bg-phantom-panelHi/60 text-xs text-phantom-ghost mb-8 backdrop-blur">
            <span className="phantom-dot phantom-dot-accent animate-phantom-pulse" />
            Now in private beta — agencies, brands, and growth teams
          </div>

          {/* Headline */}
          <h1 className="font-display font-black tracking-tight">
            <span className="block text-5xl md:text-7xl lg:text-[5.5rem] leading-[0.93] text-white">
              Your Fleet.
            </span>
            <span className="block text-5xl md:text-7xl lg:text-[5.5rem] leading-[0.93] text-white mt-2">
              Every Platform.
            </span>
            <span className="block text-5xl md:text-7xl lg:text-[5.5rem] leading-[0.93] mt-2 phantom-accent-text">
              Zero Guesswork.
            </span>
          </h1>

          {/* Subheading */}
          <p className="mt-10 text-lg md:text-xl text-phantom-ghost max-w-2xl mx-auto leading-relaxed">
            AI Agent Managers that build your growth gameplan, run your farm 24/7, and adapt in
            real time — across 10 platforms from a single command dashboard.
          </p>

          {/* CTAs */}
          <div className="mt-12 flex flex-wrap items-center justify-center gap-4">
            <Link
              href="/pricing"
              className="group px-7 flex items-center gap-2 rounded-lg bg-phantom-accent text-phantom-bg font-semibold text-sm shadow-[0_0_48px_hsl(162_100%_54%/0.4)] hover:shadow-[0_0_72px_hsl(162_100%_54%/0.65)] transition-shadow"
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
              See How It Works
            </Link>
          </div>

          {/* Stats strip */}
          <div className="mt-24 grid grid-cols-2 md:grid-cols-4 gap-px bg-phantom-border/30 rounded-xl overflow-hidden max-w-4xl mx-auto border border-phantom-border/60">
            {STATS.map((s) => (
              <div key={s.label} className="bg-phantom-bg/80 backdrop-blur px-5 py-6 text-left">
                <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                  {s.label}
                </div>
                <div className="phantom-metric text-3xl mt-2 phantom-accent-text">{s.value}</div>
                <div className="text-[10px] text-phantom-ghost/70 mt-1 font-mono">{s.sub}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════ PLATFORM LOGOS STRIP ═══════════════════════════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-20">
        <div className="text-center mb-10">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Supported platforms
          </div>
          <p className="text-sm text-phantom-ghost/60 mt-2">
            One dashboard. Every network your audience lives on.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-3">
          {PLATFORMS.map((p) => (
            <div
              key={p}
              className="px-4 py-2 rounded-lg border border-phantom-border bg-phantom-panel text-xs font-mono text-phantom-ghost tracking-wider hover:border-phantom-accent/40 hover:text-phantom-accent transition-all"
            >
              {p.toUpperCase()}
            </div>
          ))}
        </div>
      </section>

      {/* ═══════════════════════════════════════ 6-PILLAR FEATURES ═══════════════════════════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="text-center mb-14">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Why Phantom Fleet
          </div>
          <h2 className="font-display text-4xl md:text-5xl font-bold mt-3 tracking-tight">
            Six moats <span className="phantom-accent-text">competitors don&apos;t have.</span>
          </h2>
          <p className="mt-5 text-phantom-ghost max-w-xl mx-auto text-sm leading-relaxed">
            Built from first principles for agencies, brands, and growth teams who can&apos;t
            afford account losses or manual babysitting.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {PILLARS.map((p) => (
            <div
              key={p.title}
              className="phantom-panel p-6 group hover:border-phantom-accent/30 hover:shadow-[0_0_32px_hsl(162_100%_54%/0.06)] transition-all"
            >
              <div className="w-11 h-11 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center mb-5 group-hover:scale-105 transition-transform">
                <p.icon className="w-5 h-5 text-phantom-accent" strokeWidth={1.75} />
              </div>
              <div className="font-display font-semibold text-base mb-2">{p.title}</div>
              <div className="text-sm text-phantom-ghost leading-relaxed">{p.body}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ═══════════════════════════════════════ PLATFORM GRID ═══════════════════════════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="text-center mb-14">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Platform coverage
          </div>
          <h2 className="font-display text-4xl md:text-5xl font-bold mt-3 tracking-tight">
            Ten platforms. <span className="phantom-accent-text">One command center.</span>
          </h2>
          <p className="mt-5 text-phantom-ghost max-w-xl mx-auto text-sm leading-relaxed">
            Account density numbers are production-validated. Mode badges reflect execution
            strategy per platform.
          </p>
        </div>
        <PlatformGrid />
      </section>

      {/* ═══════════════════════════════════════ WHO IT'S FOR ═══════════════════════════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="text-center mb-14">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Built for every growth team
          </div>
          <h2 className="font-display text-4xl md:text-5xl font-bold mt-3 tracking-tight">
            Whatever your <span className="phantom-accent-text">vertical.</span>
          </h2>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            {
              title: "Growth Agencies",
              body: "Scale client accounts across every platform with a single persona primitive and unified reporting.",
            },
            {
              title: "DTC Brands",
              body: "Organic growth for your store. Real-device trust signals that VPS-based tools never achieve.",
            },
            {
              title: "Creators",
              body: "Run your cross-platform growth ops while you create. 15 autonomous agents replace manual work.",
            },
            {
              title: "Community Managers",
              body: "Engage, moderate, and grow communities across Discord, Reddit, and Telegram simultaneously.",
            },
            {
              title: "Lead Gen Teams",
              body: "Cold outreach at scale with context-aware messaging and human-grade timing distributions.",
            },
            {
              title: "Brand Managers",
              body: "Monitor, engage, and defend your brand presence across every major social network from one view.",
            },
          ].map((u) => (
            <div
              key={u.title}
              className="phantom-panel p-5 hover:border-phantom-accent/20 transition-all"
            >
              <div className="font-display font-semibold text-sm mb-2">{u.title}</div>
              <div className="text-xs text-phantom-ghost leading-relaxed">{u.body}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ═══════════════════════════════════════ PROOF STRIP ═══════════════════════════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="phantom-panel-accent p-8 relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-phantom-accent/5 via-transparent to-transparent pointer-events-none" />
          <div className="relative grid grid-cols-1 md:grid-cols-3 gap-8 text-center">
            {[
              { metric: "99.4%", label: "30-day account survival rate" },
              { metric: "151", label: "CI tests passing on every deploy" },
              { metric: "<2ms", label: "Fingerprint audit latency per account" },
            ].map((s) => (
              <div key={s.label}>
                <div className="phantom-metric text-5xl phantom-accent-text">{s.metric}</div>
                <div className="text-sm text-phantom-ghost mt-2">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════ FINAL CTA ═══════════════════════════════════════ */}
      <section className="max-w-4xl mx-auto px-6 pb-28 text-center">
        <div className="phantom-panel p-14 relative overflow-hidden border border-phantom-border">
          <div className="absolute inset-0 bg-gradient-to-b from-phantom-accent/4 via-transparent to-transparent pointer-events-none" />
          <div className="relative">
            <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-5">
              Ready to deploy
            </div>
            <h2 className="font-display text-4xl md:text-5xl font-bold tracking-tight mb-4">
              Your fleet is waiting.
            </h2>
            <p className="text-phantom-ghost max-w-lg mx-auto mb-10 leading-relaxed">
              Spin up in under 30 minutes. Connect your devices, configure your platforms, and let
              Phantom Fleet&apos;s agent mesh do the rest.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-4">
              <Link
                href="/pricing"
                className="group px-7 flex items-center gap-2 rounded-lg bg-phantom-accent text-phantom-bg font-semibold text-sm shadow-[0_0_48px_hsl(162_100%_54%/0.35)] hover:shadow-[0_0_72px_hsl(162_100%_54%/0.6)] transition-shadow"
                style={{ height: "3.25rem" }}
              >
                Start Free Trial
                <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
              </Link>
              <Link
                href="/comparison"
                className="px-7 flex items-center rounded-lg border border-phantom-border text-sm font-medium hover:bg-phantom-panelHi/50 transition-colors"
                style={{ height: "3.25rem" }}
              >
                Compare vs Competitors
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
