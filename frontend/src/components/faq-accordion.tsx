"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

const FAQ_ITEMS = [
  {
    q: "Who is Phantom Fleet for?",
    a: "Anyone who needs to run multi-account social media automation at scale: growth agencies, solo creators, DTC brands running organic social, dropshippers, lead-gen operators, influencer marketing teams, brand protection services, and OFM agencies. If you're running more than 5 accounts across any combination of platforms, Phantom Fleet is built for you. The tool is industry-neutral — what you do with it is up to you.",
  },
  {
    q: "How is Phantom Fleet different from Onimator?",
    a: "Onimator is a Python 3.9 monolith running flat randomization with zero cluster monitoring. Phantom Fleet is a Python 3.12 + Next.js + Kotlin system with 15 autonomous agents, live 20-dimension fleet-scale cluster detection, a unified cross-platform persona primitive, and a 10,000-persona Monte Carlo CI gate that fails the build if any fingerprint dimension clusters. Onimator users report 30-60 day average account lifespans; Phantom Fleet is built for 6+ month lifespans.",
  },
  {
    q: "What's the 'fleet-scale cluster detection' you keep mentioning?",
    a: "20 fingerprint dimensions watched continuously across every account in the fleet. Device model distribution, locale/timezone cross-fields, JA3/JA4 TLS, tap-dwell distribution, diurnal timing, content pool diversity, follow-back ratio, scroll velocity, and more. The Fingerprint Monitor Agent runs cluster detection every 5 minutes. The moment any dimension tightens toward a cluster signature, the affected cohort is auto-paused — BEFORE any platform's classifier notices. Nothing else on the market does this.",
  },
  {
    q: "Why 'persona' instead of 'account'?",
    a: "A persona is a human character that exists above any specific account. One persona → N accounts across N platforms → N phones. When an account dies, Phantom Fleet auto-provisions a replacement account under the same persona with the same biometrics, same targeting config, same content style. Accounts come and go. Personas never do. This is what makes cross-platform growth (IG + TikTok + Threads + Reddit + X) possible with a single identity.",
  },
  {
    q: "What hardware do I need?",
    a: "Any rooted or non-rooted Android phones from Android 10+. Phantom Fleet is tested on Samsung Galaxy S10 Lite, A-series, and Pixel 6+. One Windows or Linux PC per farm with ADB. The Phantom Fleet Companion APK (Kotlin) runs on every phone and replaces uiautomator2 with a 5-10x faster Accessibility Service driver.",
  },
  {
    q: "Do I need proxies?",
    a: "Yes. Phantom Fleet uses IPRoyal Royal Residential Unlimited at ~$80/mo for Phase 0, with per-session unique US residential IPs pinned to each persona's home region. The Proxy Orchestrator Agent handles rotation, sticky sessions, and block-signal recovery. Proxies are the only recurring operational cost beyond LLM API calls.",
  },
  {
    q: "Is this legal?",
    a: "Phantom Fleet is a tool. What you run on it and how you comply with platform TOS is your call. The product itself is an orchestration layer — the Fingerprint Monitor Agent explicitly pauses cohorts to reduce detection, not to evade consequences. Consult a lawyer for your specific use case.",
  },
  {
    q: "Which platforms are supported?",
    a: "Phase 1 is Instagram-only so we can prove the architecture on one platform. Phase 2 adds TikTok, Threads, and Reddit. Phase 3 adds Snapchat and dating apps. Phase 4+ adds X/Twitter, Facebook, YouTube, LinkedIn, Spotify, Pinterest, Discord, Telegram. Adding a platform is a 2-week plugin once the persona primitive is in place.",
  },
  {
    q: "What does 'autonomous' actually mean?",
    a: "15 AI agents handle every operation: warming new accounts, scraping fresh targets daily, discovering new source accounts, rotating proxies on block signals, generating captions, running DM conversations, recovering from phone crashes, replacing dead accounts, tracking conversion attribution, reviewing weekly KPIs, and gating deploys through a cluster audit harness. You set up once, approve the Phase 0 launch, and the fleet operates itself.",
  },
  {
    q: "Do you host my data?",
    a: "No. Phantom Fleet is self-hosted. Runs entirely on your farm PC + Postgres + Redis. Nothing leaves your hardware except the LLM API calls the agents make (OpenRouter / Anthropic / OpenAI) and the residential proxy traffic. You own all your data and all your credentials.",
  },
  {
    q: "How much does it cost to run at scale?",
    a: "Phase 0 (17 phones, 219 accounts) runs around $80/mo for residential proxies and $150-300/mo for LLM API costs depending on agent activity. No per-action fees. No hidden charges. Aged-account replenishment is on you — you buy your own account inventory from your preferred marketplace.",
  },
];

export function FaqAccordion() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <div className="space-y-3">
      {FAQ_ITEMS.map((item, i) => (
        <div
          key={i}
          className={cn(
            "phantom-panel overflow-hidden transition-all",
            open === i && "phantom-panel-accent"
          )}
        >
          <button
            onClick={() => setOpen(open === i ? null : i)}
            className="w-full flex items-center justify-between p-5 text-left group"
          >
            <span className="font-display font-semibold text-base pr-6">{item.q}</span>
            <ChevronDown
              className={cn(
                "w-4 h-4 text-phantom-ghost transition-transform shrink-0",
                open === i && "rotate-180 text-phantom-accent"
              )}
            />
          </button>
          {open === i && (
            <div className="px-5 pb-5 text-sm text-phantom-ghost leading-relaxed">{item.a}</div>
          )}
        </div>
      ))}
    </div>
  );
}
