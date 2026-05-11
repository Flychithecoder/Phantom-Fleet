import Link from "next/link";
import { Book, Zap, Shield, Database, Bot, Cpu } from "lucide-react";

const DOC_SECTIONS = [
  {
    icon: Zap,
    title: "Quickstart",
    items: [
      "Installing Phantom Fleet on your first farm",
      "Importing existing accounts from Onimator",
      "Running the login-survival diagnostic",
      "Launching Phase 0 full-box parallel",
    ],
  },
  {
    icon: Shield,
    title: "Anti-detection",
    items: [
      "The 10-check cluster audit rule",
      "Distribution discipline (no flat randoms)",
      "Fingerprint dimensions we monitor",
      "LLM detection-tell filter",
    ],
  },
  {
    icon: Bot,
    title: "AI agent mesh",
    items: [
      "All 14 agents and their tool allowlists",
      "Writing a custom agent",
      "Cost caps + confirmation gates",
      "Event-sourced audit log",
    ],
  },
  {
    icon: Database,
    title: "Data model",
    items: [
      "Persona → Account → Phone schema",
      "Fresh target daily pipeline",
      "Target history 90-day cooldown",
      "Funnel conversion attribution",
    ],
  },
  {
    icon: Cpu,
    title: "Hardware",
    items: [
      "Supported phone models",
      "Companion APK install guide",
      "Wi-Fi ADB setup",
      "Phone recovery procedures",
    ],
  },
  {
    icon: Book,
    title: "Operations",
    items: [
      "Proxy selection & configuration",
      "Persona biometric lock-in",
      "Mother/slave amplification setup",
      "Scaling to Phase 2+",
    ],
  },
];

export default function DocsPage() {
  return (
    <section className="max-w-6xl mx-auto px-6 py-20">
      <div className="text-center mb-16">
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Documentation
        </div>
        <h1 className="font-display text-5xl md:text-6xl font-bold mt-3 tracking-tight">
          Everything <span className="phantom-accent-text">documented.</span>
        </h1>
        <p className="mt-6 text-lg text-phantom-ghost max-w-xl mx-auto">
          Full docs, architecture decisions, and operational runbooks.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {DOC_SECTIONS.map((section) => (
          <div key={section.title} className="phantom-panel p-6">
            <div className="w-10 h-10 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center mb-4">
              <section.icon className="w-5 h-5 text-phantom-accent" strokeWidth={1.75} />
            </div>
            <div className="font-display font-semibold text-lg mb-4">{section.title}</div>
            <ul className="space-y-2">
              {section.items.map((item) => (
                <li key={item}>
                  <Link
                    href="#"
                    className="text-sm text-phantom-ghost hover:text-phantom-accent transition-colors block py-0.5"
                  >
                    → {item}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
