import Link from "next/link";
import { Check, ArrowRight, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

type Tier = {
  name: string;
  price: string;
  annualPrice: string;
  period: string;
  description: string;
  highlight?: string;
  features: string[];
  cta: string;
  ctaHref: string;
  accent: boolean;
};

const TIERS: Tier[] = [
  {
    name: "Starter",
    price: "$299",
    annualPrice: "$239",
    period: "/mo",
    description: "Get your first phones running. Perfect for solo operators and small teams testing fleet automation.",
    features: [
      "Up to 5 phones",
      "3 platforms included",
      "90+ accounts per phone",
      "Core agent mesh (Warming, Targeting, Fingerprint)",
      "24-hour fleet cycling",
      "Capacity Planner AI",
      "Community support",
      "Full dashboard access",
    ],
    cta: "Start Free Trial",
    ctaHref: "/",
    accent: false,
  },
  {
    name: "Growth",
    price: "$799",
    annualPrice: "$639",
    period: "/mo",
    description: "For agencies and growth teams scaling across multiple platforms with AI gameplans.",
    highlight: "Most popular",
    features: [
      "Up to 20 phones",
      "All 10 platforms",
      "90+ accounts per phone",
      "Full 15-agent mesh",
      "AI Gameplans (Chief Agent)",
      "Context-aware Chat Tiers",
      "Photo Verification AI",
      "Priority support",
      "5 team seats",
    ],
    cta: "Start Free Trial",
    ctaHref: "/",
    accent: true,
  },
  {
    name: "Fleet",
    price: "$1,999",
    annualPrice: "$1,599",
    period: "/mo",
    description: "Unlimited scale. For established agencies and operators running enterprise-level farms.",
    features: [
      "Unlimited phones",
      "All 10 platforms",
      "90+ accounts per phone",
      "Full 15-agent mesh",
      "Dedicated onboarding session",
      "White-glove support + SLA",
      "Custom integrations",
      "API access",
      "Unlimited team seats",
    ],
    cta: "Contact Sales",
    ctaHref: "/",
    accent: false,
  },
];

const ALL_FEATURES = [
  { label: "Phones included", starter: "5", growth: "20", fleet: "Unlimited" },
  { label: "Platforms", starter: "3", growth: "All 10", fleet: "All 10" },
  { label: "Accounts per phone", starter: "90+", growth: "90+", fleet: "90+" },
  { label: "AI Agent Managers", starter: true, growth: true, fleet: true },
  { label: "24-hour fleet cycling", starter: true, growth: true, fleet: true },
  { label: "Capacity Planner AI", starter: true, growth: true, fleet: true },
  { label: "Real device fingerprinting", starter: true, growth: true, fleet: true },
  { label: "Chief Agent gameplans", starter: false, growth: true, fleet: true },
  { label: "Context-aware Chat Tiers", starter: false, growth: true, fleet: true },
  { label: "Photo Verification AI", starter: false, growth: true, fleet: true },
  { label: "Dedicated onboarding", starter: false, growth: false, fleet: true },
  { label: "White-glove support", starter: false, growth: false, fleet: true },
  { label: "Custom integrations", starter: false, growth: false, fleet: true },
  { label: "API access", starter: false, growth: false, fleet: true },
  { label: "Support tier", starter: "Community", growth: "Priority", fleet: "SLA + dedicated" },
  { label: "Team seats", starter: "1", growth: "5", fleet: "Unlimited" },
];

function FeatureCell({ value }: { value: string | boolean }) {
  if (value === true) {
    return (
      <div className="flex justify-center">
        <Check className="w-4 h-4 text-phantom-accent" strokeWidth={2.5} />
      </div>
    );
  }
  if (value === false) {
    return (
      <div className="flex justify-center">
        <Minus className="w-4 h-4 text-phantom-ghost/30" strokeWidth={1.5} />
      </div>
    );
  }
  return (
    <div className="text-center text-sm text-phantom-ghost">{value}</div>
  );
}

export default function PricingPage() {
  return (
    <>
      {/* ═══════════════════ HERO ═══════════════════ */}
      <section className="max-w-7xl mx-auto px-6 pt-20 pb-16 text-center">
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Pricing
        </div>
        <h1 className="font-display text-5xl md:text-6xl font-bold mt-4 tracking-tight">
          Priced for <span className="phantom-accent-text">serious operators.</span>
        </h1>
        <p className="mt-6 text-lg text-phantom-ghost max-w-xl mx-auto leading-relaxed">
          No contracts. Cancel any time. Every plan includes the full 15-agent mesh and
          real-device fingerprint architecture.
        </p>

        {/* Annual toggle label */}
        <div className="mt-8 inline-flex items-center gap-2 px-4 py-2 rounded-full border border-phantom-accent/30 bg-phantom-accent/10 text-sm text-phantom-accent font-medium">
          20% off with annual billing
        </div>
      </section>

      {/* ═══════════════════ TIER CARDS ═══════════════════ */}
      <section className="max-w-6xl mx-auto px-6 pb-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              className={cn(
                "p-7 flex flex-col relative",
                tier.accent
                  ? "phantom-panel-accent scale-[1.02] shadow-[0_0_64px_hsl(162_100%_54%/0.1)]"
                  : "phantom-panel"
              )}
            >
              {/* Most popular badge */}
              {tier.highlight && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full bg-phantom-accent text-phantom-bg text-[10px] font-bold uppercase tracking-[0.1em] shadow-[0_0_24px_hsl(162_100%_54%/0.5)]">
                  {tier.highlight}
                </div>
              )}

              {/* Tier name */}
              <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-3">
                {tier.name}
              </div>

              {/* Price */}
              <div className="flex items-baseline gap-1 mb-1">
                <span
                  className={cn(
                    "phantom-metric text-5xl",
                    tier.accent ? "phantom-accent-text" : "text-white"
                  )}
                >
                  {tier.price}
                </span>
                <span className="text-phantom-ghost text-sm">{tier.period}</span>
              </div>
              <div className="text-xs text-phantom-ghost mb-1">
                <span className="text-phantom-accent font-mono">{tier.annualPrice}/mo</span>
                {" "}billed annually
              </div>

              <div className="text-xs text-phantom-ghost leading-relaxed mt-3 mb-6">
                {tier.description}
              </div>

              {/* Features */}
              <ul className="space-y-2.5 flex-1 mb-8">
                {tier.features.map((f) => (
                  <li key={f} className="flex items-start gap-2.5 text-sm">
                    <Check
                      className="w-3.5 h-3.5 text-phantom-accent shrink-0 mt-0.5"
                      strokeWidth={2.5}
                    />
                    <span className="text-phantom-ghost">{f}</span>
                  </li>
                ))}
              </ul>

              {/* CTA */}
              <Link
                href={tier.ctaHref}
                className={cn(
                  "h-11 rounded-lg font-semibold text-sm flex items-center justify-center gap-1.5 transition-all",
                  tier.accent
                    ? "bg-phantom-accent text-phantom-bg shadow-[0_0_32px_hsl(162_100%_54%/0.3)] hover:shadow-[0_0_48px_hsl(162_100%_54%/0.5)]"
                    : "border border-phantom-border hover:bg-phantom-panelHi/60"
                )}
              >
                {tier.cta}
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          ))}
        </div>

        <div className="mt-6 text-center text-xs text-phantom-ghost">
          All plans: no contracts · cancel any time · 14-day free trial on Starter and Growth
        </div>
      </section>

      {/* ═══════════════════ FULL FEATURE TABLE ═══════════════════ */}
      <section className="max-w-5xl mx-auto px-6 pb-24">
        <div className="text-center mb-10">
          <h2 className="font-display text-2xl font-bold tracking-tight">
            Full plan comparison
          </h2>
        </div>

        <div className="phantom-panel overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                <th className="px-6 py-4 text-left text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
                  Feature
                </th>
                <th className="px-4 py-4 text-center text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium w-32">
                  Starter
                </th>
                <th className="px-4 py-4 text-center text-[10px] uppercase tracking-[0.15em] font-medium w-32 bg-phantom-accent/5">
                  <span className="phantom-accent-text">Growth</span>
                </th>
                <th className="px-4 py-4 text-center text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium w-32">
                  Fleet
                </th>
              </tr>
            </thead>
            <tbody>
              {ALL_FEATURES.map((row) => (
                <tr key={row.label} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/20">
                  <td className="px-6 py-3 text-sm text-phantom-ghost">{row.label}</td>
                  <td className="px-4 py-3">
                    <FeatureCell value={row.starter} />
                  </td>
                  <td className="px-4 py-3 bg-phantom-accent/5">
                    <FeatureCell value={row.growth} />
                  </td>
                  <td className="px-4 py-3">
                    <FeatureCell value={row.fleet} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ═══════════════════ OFM AGENCY NOTE ═══════════════════ */}
      <section className="max-w-3xl mx-auto px-6 pb-24">
        <div className="phantom-panel p-8 border border-phantom-border relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-phantom-magenta/5 via-transparent to-transparent pointer-events-none" />
          <div className="relative">
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-mono mb-3">
              Agency-Specific Pricing
            </div>
            <div className="font-display font-semibold text-lg mb-3">
              OFM agencies — contact us for custom rates.
            </div>
            <p className="text-sm text-phantom-ghost leading-relaxed mb-5">
              Revenue-share pricing structures are available for OFM agencies managing creator
              portfolios. Custom integrations with your existing CRM and content workflows are
              included.
            </p>
            <Link
              href="/"
              className="inline-flex items-center gap-2 text-sm font-semibold text-phantom-accent hover:text-phantom-accentHi transition-colors"
            >
              Contact us about agency pricing
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </section>

      {/* ═══════════════════ FAQ STRIP ═══════════════════ */}
      <section className="max-w-4xl mx-auto px-6 pb-28">
        <div className="text-center mb-10">
          <h2 className="font-display text-2xl font-bold tracking-tight">
            Common questions
          </h2>
        </div>
        <div className="space-y-3">
          {[
            {
              q: "Do I need my own hardware?",
              a: "Yes — Phantom Fleet runs on physical Android devices you own. This is by design: real hardware telemetry is what keeps your accounts alive. We guide you through the setup during onboarding.",
            },
            {
              q: "What proxies do I need?",
              a: "We recommend 4G mobile proxies for Instagram, TikTok, Threads, and dating apps. Residential proxies work well for Reddit, Discord, LinkedIn, and BlueSky. Capacity Planner AI will tell you exactly how many proxies you need for your device count.",
            },
            {
              q: "How does the free trial work?",
              a: "14-day free trial on Starter and Growth plans. No credit card required. Full feature access — including the agent mesh and Capacity Planner. Cancel before day 14 and pay nothing.",
            },
            {
              q: "Can I upgrade or downgrade mid-cycle?",
              a: "Yes. Plan changes take effect immediately. Upgrades are prorated. Downgrades apply at the next billing cycle.",
            },
            {
              q: "Is Phantom Fleet self-hosted?",
              a: "The control dashboard is cloud-hosted. The device agents run on your local hardware. Your account data never leaves your devices — only telemetry and action logs sync to the dashboard.",
            },
          ].map((item) => (
            <div key={item.q} className="phantom-panel p-5">
              <div className="font-display font-semibold text-sm mb-2">{item.q}</div>
              <div className="text-sm text-phantom-ghost leading-relaxed">{item.a}</div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
