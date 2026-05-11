import Link from "next/link";
import {
  ArrowRight,
  Bot,
  Clock,
  Shield,
  Smartphone,
  BarChart3,
  MessageSquare,
  Camera,
  Server,
  Check,
} from "lucide-react";
import { AgentHierarchyVisual } from "@/components/agent-hierarchy-visual";
import { TimelineVisual } from "@/components/timeline-visual";
import { PlatformGrid } from "@/components/platform-grid";

const CHAT_TIERS = [
  { tier: "Professional", platforms: ["LinkedIn", "Twitter / X (B2B)"], tone: "Formal, value-driven, brand-safe", example: "I noticed your team is scaling outreach — happy to connect on how we approached a similar challenge." },
  { tier: "Casual / Community", platforms: ["Reddit", "Discord", "BlueSky", "Telegram"], tone: "Conversational, community-aware, no sales pressure", example: "This subreddit is great for this — have you tried the newer approach? Happy to share what worked." },
  { tier: "Creator Friendly", platforms: ["Instagram", "Threads", "TikTok"], tone: "Warm, relatable, engagement-first", example: "Love this content — your editing style is next level. Following for more." },
  { tier: "Intimate / NSFW", platforms: ["Dating Apps", "Private Messaging"], tone: "Persona-matched, context-aware, age-gated", example: "Available on appropriate platforms only. Context-matched to persona profile." },
];

const VERIFICATION_STEPS = [
  { step: "01", title: "Account flagged for verification", body: "Platform requests photo ID. Agent intercepts the prompt before it surfaces as a ban." },
  { step: "02", title: "Photo Verification AI activates", body: "Selects the correct persona-matched photo from the vault. Applies lighting, angle, and metadata normalization." },
  { step: "03", title: "Document context generation", body: "Ensures EXIF, resolution, and device metadata match the account's declared device profile." },
  { step: "04", title: "Submission and confirmation", body: "Automated submission with retry logic. Account restored within the platform's typical review window." },
];

export default function FeaturesPage() {
  return (
    <>
      {/* ═══════════════════ HERO ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pt-20 pb-24 text-center">
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          The product
        </div>
        <h1 className="font-display text-5xl md:text-6xl font-bold mt-4 tracking-tight">
          Every capability. <span className="phantom-accent-text">Every platform.</span>
        </h1>
        <p className="mt-6 text-lg text-phantom-ghost max-w-2xl mx-auto leading-relaxed">
          Phantom Fleet is the only fleet automation system built from the ground up for
          agencies, brands, and growth teams who operate across multiple platforms simultaneously.
        </p>
      </section>

      {/* ═══════════════════ 1. AI AGENT MANAGERS ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-start">
          <div>
            <div className="inline-flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center">
                <Bot className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
              </div>
              <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                AI Agent Managers
              </span>
            </div>
            <h2 className="font-display text-4xl font-bold tracking-tight mb-6">
              Build a gameplan for platforms you&apos;ve never run before.
            </h2>
            <p className="text-phantom-ghost leading-relaxed mb-6">
              The Chief Agent owns the full cross-platform gameplan. It delegates to Platform
              Managers — each one an expert in a specific network&apos;s norms, timing, and
              growth mechanics. Specialists execute below them: warming, targeting, content,
              fingerprint monitoring, proxy cycling, recovery, and conversion attribution.
            </p>
            <ul className="space-y-3">
              {[
                "Chief Agent sets weekly KPI targets and allocates resources across platforms",
                "Platform Managers handle every network-specific decision autonomously",
                "Specialist agents run warming, targeting, content, proxies, and recovery",
                "Every agent action logged before execution — full audit trail",
                "Tool allowlists and cost caps enforced at code level, not prompt level",
              ].map((item) => (
                <li key={item} className="flex items-start gap-3 text-sm">
                  <Check className="w-4 h-4 text-phantom-accent shrink-0 mt-0.5" strokeWidth={2.5} />
                  <span className="text-phantom-ghost">{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <AgentHierarchyVisual />
          </div>
        </div>
      </section>

      {/* ═══════════════════ 2. 24-HOUR FLEET CYCLING ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="mb-12">
          <div className="inline-flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center">
              <Clock className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
            </div>
            <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              24-Hour Fleet Cycling
            </span>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-end mb-8">
            <h2 className="font-display text-4xl font-bold tracking-tight">
              One proxy farm. Ten platforms. Zero idle hardware.
            </h2>
            <p className="text-phantom-ghost leading-relaxed">
              Phantom Fleet multiplexes your phone farm and proxy infrastructure across platforms
              by time of day. LinkedIn gets peak business hours. Dating apps get evenings. Reddit
              runs through the afternoon. Every account runs in its platform&apos;s optimal window
              — automatically.
            </p>
          </div>
        </div>
        <TimelineVisual />
        <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            {
              label: "Proxy Multiplexing",
              body: "Same 4G proxy pool serves multiple platforms in rotating windows. Cost-per-account drops as platform count rises.",
            },
            {
              label: "Timezone-Aware Scheduling",
              body: "Each account runs in its own declared timezone. No impossible activity spikes at 3am UTC.",
            },
            {
              label: "Platform-Optimal Windows",
              body: "Capacity Planner AI calibrates per-platform active windows against real engagement curve data.",
            },
          ].map((c) => (
            <div key={c.label} className="phantom-panel p-5">
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-accent font-mono mb-2">
                {c.label}
              </div>
              <div className="text-sm text-phantom-ghost leading-relaxed">{c.body}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ═══════════════════ 3. 10 PLATFORMS ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center">
              <Server className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
            </div>
            <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Platform Coverage
            </span>
          </div>
          <h2 className="font-display text-4xl font-bold tracking-tight mt-1">
            10 platforms. <span className="phantom-accent-text">One dashboard.</span>
          </h2>
          <p className="mt-4 text-phantom-ghost max-w-xl mx-auto">
            Account density numbers are production-validated figures, not theoretical maximums.
            Execution mode shows how Phantom Fleet interacts with each platform&apos;s API layer.
          </p>
        </div>
        <PlatformGrid />
      </section>

      {/* ═══════════════════ 4. REAL DEVICE FINGERPRINTING ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
          <div>
            <div className="inline-flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center">
                <Shield className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
              </div>
              <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                Real Device Fingerprinting
              </span>
            </div>
            <h2 className="font-display text-4xl font-bold tracking-tight mb-6">
              VPS bots get caught. Real devices don&apos;t.
            </h2>
            <p className="text-phantom-ghost leading-relaxed mb-8">
              Every Phantom Fleet account is anchored to a physical Android device. Genuine hardware
              telemetry — accelerometer drift, touch biometrics, battery curves, TLS fingerprints —
              cannot be faked by a VPS. Our 20-dimension cluster monitor runs continuously to ensure
              no statistical pattern emerges across your fleet.
            </p>
          </div>

          {/* Comparison cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="phantom-panel p-5 border-phantom-red/30 bg-phantom-red/5">
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-red font-mono mb-3">
                VPS-based bots
              </div>
              <ul className="space-y-2">
                {[
                  "Datacenter IP range — instant flag",
                  "No hardware entropy source",
                  "Uniform TLS fingerprints across fleet",
                  "No real touch events or biometrics",
                  "Identical OS environment per VM",
                  "Cluster detectable in one SQL query",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2 text-xs text-phantom-ghost">
                    <span className="text-phantom-red mt-0.5">—</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <div className="phantom-panel-accent p-5">
              <div className="text-[10px] uppercase tracking-[0.12em] text-phantom-accent font-mono mb-3">
                Phantom Fleet
              </div>
              <ul className="space-y-2">
                {[
                  "Real 4G / residential mobile IP",
                  "Hardware-sourced entropy on every call",
                  "Per-device TLS profile from real handshake",
                  "Native Kotlin accessibility — real touch events",
                  "Device distribution matches real-world installs",
                  "20-dim cluster audit on every commit",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2 text-xs">
                    <Check className="w-3 h-3 text-phantom-accent shrink-0 mt-0.5" strokeWidth={2.5} />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ═══════════════════ 5. CAPACITY PLANNER ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-start">
          <div>
            <div className="inline-flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center">
                <BarChart3 className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
              </div>
              <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                Capacity Planner AI
              </span>
            </div>
            <h2 className="font-display text-4xl font-bold tracking-tight mb-6">
              Know exactly how many accounts your farm can sustain.
            </h2>
            <p className="text-phantom-ghost leading-relaxed mb-6">
              Input your device count, proxy tier, target platforms, and warming stage. Capacity
              Planner outputs a precise account ceiling per platform — factoring in proxy rotation
              windows, warming curve durations, and per-platform density limits.
            </p>
            <p className="text-phantom-ghost leading-relaxed">
              Stop over-provisioning and getting accounts terminated. Stop under-provisioning and
              leaving performance on the table. Capacity Planner eliminates guesswork at every
              farm size.
            </p>
          </div>

          {/* Mockup terminal card */}
          <div className="phantom-panel overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-phantom-border bg-phantom-panelHi/50">
              <div className="flex gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-phantom-red/60" />
                <span className="w-2.5 h-2.5 rounded-full bg-phantom-amber/60" />
                <span className="w-2.5 h-2.5 rounded-full bg-phantom-alive/60" />
              </div>
              <span className="text-[10px] font-mono text-phantom-ghost ml-2">
                capacity_planner — output
              </span>
            </div>
            <div className="p-5 font-mono text-sm space-y-1">
              <div className="text-phantom-ghost/50">$ phantom capacity --devices 12 --proxies 4g-48 --platforms ig,reddit,x</div>
              <div className="text-phantom-ghost mt-3">Analyzing farm configuration...</div>
              <div className="text-phantom-ghost">Proxy rotation window: 45 min</div>
              <div className="text-phantom-ghost">Warming stage: mixed (d3–d28)</div>
              <div className="mt-3 space-y-1">
                <div className="flex justify-between">
                  <span className="text-phantom-ghost">Instagram</span>
                  <span className="text-phantom-accent">94 accounts</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-phantom-ghost">Reddit</span>
                  <span className="text-phantom-accent">68 accounts</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-phantom-ghost">X / Twitter</span>
                  <span className="text-phantom-accent">82 accounts</span>
                </div>
              </div>
              <div className="mt-3 pt-3 border-t border-phantom-border">
                <div className="flex justify-between">
                  <span className="text-phantom-ghost">Total fleet capacity</span>
                  <span className="phantom-accent-text font-bold">244 accounts</span>
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-phantom-ghost">Proxy headroom</span>
                  <span className="text-phantom-alive">18% spare</span>
                </div>
              </div>
              <div className="mt-3 text-[10px] text-phantom-ghost/50">
                Recommendation: add 6 proxies to unlock 31 additional IG accounts.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ═══════════════════ 6. CHAT AI TIERS ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center">
              <MessageSquare className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
            </div>
            <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Context-Aware Chat Tiers
            </span>
          </div>
          <h2 className="font-display text-4xl font-bold tracking-tight mt-1">
            Professional on LinkedIn. <span className="phantom-accent-text">NSFW on dating apps.</span>
          </h2>
          <p className="mt-4 text-phantom-ghost max-w-xl mx-auto">
            One chat system, every context. Phantom Fleet automatically selects the correct
            communication register for each platform — no manual configuration per account.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {CHAT_TIERS.map((t) => (
            <div key={t.tier} className="phantom-panel p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="font-display font-semibold text-base">{t.tier}</div>
              </div>
              <div className="flex flex-wrap gap-1.5 mb-4">
                {t.platforms.map((p) => (
                  <span
                    key={p}
                    className="text-[9px] uppercase tracking-[0.12em] font-mono px-2 py-0.5 rounded-md border border-phantom-border text-phantom-ghost bg-phantom-panelHi"
                  >
                    {p}
                  </span>
                ))}
              </div>
              <div className="text-xs text-phantom-ghost mb-3">
                <span className="text-phantom-accent font-mono">Tone: </span>
                {t.tone}
              </div>
              <div className="bg-phantom-panelHi rounded-lg p-3 text-xs text-phantom-ghost italic border border-phantom-border">
                &ldquo;{t.example}&rdquo;
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ═══════════════════ 7. PHOTO VERIFICATION AI ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-32">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-start">
          <div>
            <div className="inline-flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center">
                <Camera className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
              </div>
              <span className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                Photo Verification AI
              </span>
            </div>
            <h2 className="font-display text-4xl font-bold tracking-tight mb-6">
              Survive dating app verification without human intervention.
            </h2>
            <p className="text-phantom-ghost leading-relaxed mb-6">
              Dating platforms increasingly require photo verification before engagement can
              continue. Photo Verification AI intercepts these requests, selects the correct
              persona-matched image, and handles submission — fully autonomously.
            </p>
            <p className="text-phantom-ghost leading-relaxed">
              Images are stored in a persona-linked vault with EXIF and metadata normalization.
              The AI matches lighting conditions, angle, and device metadata to the account&apos;s
              declared profile before submission.
            </p>
          </div>

          {/* Verification flow */}
          <div className="space-y-3">
            {VERIFICATION_STEPS.map((s, i) => (
              <div key={s.step} className="flex gap-4">
                <div className="flex flex-col items-center">
                  <div className="w-8 h-8 rounded-full border border-phantom-accent/40 bg-phantom-accent/10 flex items-center justify-center text-[10px] font-mono text-phantom-accent font-bold shrink-0">
                    {s.step}
                  </div>
                  {i < VERIFICATION_STEPS.length - 1 && (
                    <div className="w-px flex-1 bg-phantom-border mt-2" />
                  )}
                </div>
                <div className="pb-6">
                  <div className="font-display font-semibold text-sm mb-1">{s.title}</div>
                  <div className="text-xs text-phantom-ghost leading-relaxed">{s.body}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════ CTA ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pb-24">
        <div className="phantom-panel-accent p-10 relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-phantom-accent/5 via-transparent to-transparent pointer-events-none" />
          <div className="relative flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
            <div>
              <div className="font-display text-2xl font-bold mb-2">
                Ready to deploy your fleet?
              </div>
              <p className="text-phantom-ghost max-w-lg text-sm leading-relaxed">
                Starter trial includes all platforms, all agent tiers, and the full Capacity
                Planner. No contracts. Cancel anytime.
              </p>
            </div>
            <div className="flex gap-3 shrink-0">
              <Link
                href="/pricing"
                className="group px-6 flex items-center gap-2 rounded-lg bg-phantom-accent text-phantom-bg font-semibold text-sm shadow-[0_0_48px_hsl(162_100%_54%/0.4)] hover:shadow-[0_0_64px_hsl(162_100%_54%/0.6)] transition-shadow"
                style={{ height: "2.75rem" }}
              >
                See Pricing
                <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
              </Link>
              <Link
                href="/comparison"
                className="px-6 flex items-center rounded-lg border border-phantom-border text-sm font-medium hover:bg-phantom-panelHi/50 transition-colors"
                style={{ height: "2.75rem" }}
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
