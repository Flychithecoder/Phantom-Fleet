"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types & mock data
// ---------------------------------------------------------------------------

type Tone = "Hot Take" | "Supportive" | "Witty" | "Curious" | "Relatable" | "Agree" | "Question";

const TONE_STYLES: Record<Tone, { bg: string; text: string; border: string }> = {
  "Hot Take":  { bg: "bg-red-500/10",    text: "text-red-400",    border: "border-red-500/20"    },
  "Supportive":{ bg: "bg-green-500/10",  text: "text-green-400",  border: "border-green-500/20"  },
  "Witty":     { bg: "bg-yellow-500/10", text: "text-yellow-400", border: "border-yellow-500/20" },
  "Curious":   { bg: "bg-blue-500/10",   text: "text-blue-400",   border: "border-blue-500/20"   },
  "Relatable": { bg: "bg-purple-500/10", text: "text-purple-400", border: "border-purple-500/20" },
  "Agree":     { bg: "bg-teal-500/10",   text: "text-teal-400",   border: "border-teal-500/20"   },
  "Question":  { bg: "bg-orange-500/10", text: "text-orange-400", border: "border-orange-500/20" },
};

const REPLY_TEMPLATES = [
  { id: 1,  text: "this is so real 😭",                                  tone: "Relatable"  as Tone, accounts: 91,  sent: 2_840 },
  { id: 2,  text: "not me saving this immediately 🙌",                   tone: "Agree"      as Tone, accounts: 84,  sent: 2_340 },
  { id: 3,  text: "lowkey needed to hear this today",                    tone: "Supportive" as Tone, accounts: 102, sent: 3_180 },
  { id: 4,  text: "okay but why did this hit different at 2am 😭",       tone: "Relatable"  as Tone, accounts: 78,  sent: 2_010 },
  { id: 5,  text: "the way i'm about to screenshot and send to 5 people", tone: "Witty"      as Tone, accounts: 95,  sent: 2_950 },
  { id: 6,  text: "this needs to be said louder fr",                     tone: "Hot Take"   as Tone, accounts: 88,  sent: 2_670 },
  { id: 7,  text: "wait is this about me 👀",                            tone: "Curious"    as Tone, accounts: 73,  sent: 1_890 },
  { id: 8,  text: "the right people will always find you 🤍",            tone: "Supportive" as Tone, accounts: 110, sent: 3_420 },
  { id: 9,  text: "literally every person ever needs to see this",       tone: "Agree"      as Tone, accounts: 66,  sent: 1_640 },
  { id: 10, text: "okay but how did you know exactly what I needed??",   tone: "Question"   as Tone, accounts: 83,  sent: 2_190 },
  { id: 11, text: "this > therapy fr fr 😭💀",                           tone: "Witty"      as Tone, accounts: 97,  sent: 3_070 },
  { id: 12, text: "nobody talks about this enough and it's a problem",   tone: "Hot Take"   as Tone, accounts: 81,  sent: 2_430 },
];

const TOP_TEMPLATES = [
  { text: "the right people will always find you 🤍",         engagementRate: 5.81 },
  { text: "lowkey needed to hear this today",                 engagementRate: 5.43 },
  { text: "this > therapy fr fr 😭💀",                        engagementRate: 5.12 },
  { text: "the way i'm about to screenshot and send to 5...", engagementRate: 4.97 },
  { text: "this is so real 😭",                               engagementRate: 4.68 },
];

const TONE_DIST: { tone: Tone; pct: number }[] = [
  { tone: "Relatable",  pct: 24 },
  { tone: "Supportive", pct: 20 },
  { tone: "Agree",      pct: 17 },
  { tone: "Witty",      pct: 14 },
  { tone: "Hot Take",   pct: 12 },
  { tone: "Question",   pct: 8  },
  { tone: "Curious",    pct: 5  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RepliesPage() {
  const [toneFilter, setToneFilter] = useState<Tone | "All">("All");

  const filtered =
    toneFilter === "All" ? REPLY_TEMPLATES : REPLY_TEMPLATES.filter((t) => t.tone === toneFilter);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Threads · reply engine
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <MessageSquare className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Reply <span className="phantom-accent-text">Engine</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-xs font-semibold">
            5,810 replies today
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          AI-powered reply templates deployed at fleet scale to drive profile visits, follows, and DM conversions.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Replies Sent Today"        value="5,810"  delta={0.087}             />
        <KPICard label="Profile Visits from Replies" value="2,340" delta={0.124}            />
        <KPICard label="New Follows from Replies"  value="847"    delta={0.063}             />
        <KPICard label="Avg Engagement Rate"       value="4.2%"   sub="vs 1.8% baseline"    />
      </div>

      {/* Main + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Template grid — 2/3 */}
        <div className="lg:col-span-2">
          <Panel
            label="templates"
            title="Reply Templates"
            actions={
              <select
                value={toneFilter}
                onChange={(e) => setToneFilter(e.target.value as Tone | "All")}
                className="bg-phantom-panelHi border border-phantom-border text-phantom-ghost text-xs rounded px-2 py-1 focus:outline-none"
              >
                <option value="All">All tones</option>
                {(Object.keys(TONE_STYLES) as Tone[]).map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            }
          >
            <div className="columns-1 sm:columns-2 gap-4 space-y-4">
              {filtered.map((card) => {
                const s = TONE_STYLES[card.tone];
                return (
                  <div
                    key={card.id}
                    className="break-inside-avoid rounded-lg border border-phantom-border bg-phantom-panelHi p-4 space-y-3 hover:border-phantom-accent/30 transition-colors"
                  >
                    <p className="text-sm font-medium text-white leading-snug">{card.text}</p>
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span
                        className={cn(
                          "px-2 py-0.5 rounded-full text-[10px] font-semibold border",
                          s.bg, s.text, s.border
                        )}
                      >
                        {card.tone}
                      </span>
                      <div className="flex items-center gap-3 text-[11px] text-phantom-ghost">
                        <span>{card.accounts} accts</span>
                        <span className="text-phantom-accent tabular-nums">
                          {card.sent.toLocaleString()} sent
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>

        {/* Sidebar — 1/3 */}
        <div className="space-y-6">
          {/* Top performers */}
          <Panel label="rankings" title="Top Performing Templates">
            <div className="space-y-4">
              {TOP_TEMPLATES.map((t, i) => (
                <div key={i} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] text-phantom-ghost">#{i + 1}</span>
                    <span className="text-xs font-semibold text-phantom-alive tabular-nums">
                      {t.engagementRate.toFixed(2)}%
                    </span>
                  </div>
                  <p className="text-xs text-white leading-snug line-clamp-2">{t.text}</p>
                  <div className="h-1.5 rounded-full bg-phantom-border overflow-hidden">
                    <div
                      className="h-full rounded-full bg-phantom-accent"
                      style={{ width: `${(t.engagementRate / 6.5) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          {/* Tone distribution */}
          <Panel label="composition" title="Tone Distribution">
            <div className="space-y-2.5">
              {TONE_DIST.map(({ tone, pct }) => {
                const s = TONE_STYLES[tone];
                return (
                  <div key={tone} className="space-y-1">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className={cn("font-medium", s.text)}>{tone}</span>
                      <span className="text-phantom-ghost tabular-nums">{pct}%</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-phantom-border overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", s.bg.replace("/10", "/60"))}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
