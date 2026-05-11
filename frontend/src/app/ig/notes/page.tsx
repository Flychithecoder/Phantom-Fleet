"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types & mock data
// ---------------------------------------------------------------------------

type Mood = "flirty" | "funny" | "relatable" | "mystery" | "motivational" | "aesthetic" | "nostalgic" | "spicy";

const MOOD_STYLES: Record<Mood, { label: string; bg: string; text: string }> = {
  flirty:       { label: "Flirty",       bg: "bg-pink-500/10",    text: "text-pink-400"   },
  funny:        { label: "Funny",        bg: "bg-yellow-500/10",  text: "text-yellow-400" },
  relatable:    { label: "Relatable",    bg: "bg-blue-500/10",    text: "text-blue-400"   },
  mystery:      { label: "Mystery",      bg: "bg-purple-500/10",  text: "text-purple-400" },
  motivational: { label: "Motivational", bg: "bg-orange-500/10",  text: "text-orange-400" },
  aesthetic:    { label: "Aesthetic",    bg: "bg-teal-500/10",    text: "text-teal-400"   },
  nostalgic:    { label: "Nostalgic",    bg: "bg-amber-500/10",   text: "text-amber-400"  },
  spicy:        { label: "Spicy",        bg: "bg-red-500/10",     text: "text-red-400"    },
};

const NOTE_CARDS = [
  { id: 1, text: "not me falling for someone who doesn't even know i exist 🙈",        mood: "flirty"       as Mood, accounts: 84, replies: 312 },
  { id: 2, text: "my love language is sending memes at 2am and hoping you get it",      mood: "funny"        as Mood, accounts: 91, replies: 427 },
  { id: 3, text: "it's okay to outgrow people. growth is not betrayal.",                mood: "relatable"    as Mood, accounts: 76, replies: 289 },
  { id: 4, text: "some chapters end so the right story can begin… 🌙",                  mood: "mystery"      as Mood, accounts: 68, replies: 198 },
  { id: 5, text: "the version of you 3 years ago would be proud of where you are",       mood: "motivational" as Mood, accounts: 102, replies: 501 },
  { id: 6, text: "soft life is the only life worth living fr 🌸",                        mood: "aesthetic"    as Mood, accounts: 59, replies: 143 },
  { id: 7, text: "remember when we stayed up till 4am talking about everything? miss that", mood: "nostalgic" as Mood, accounts: 73, replies: 267 },
  { id: 8, text: "your vibe is literally a magnet. protect it 🔥",                       mood: "spicy"        as Mood, accounts: 88, replies: 384 },
  { id: 9, text: "the right person won't need convincing 💌",                            mood: "flirty"       as Mood, accounts: 95, replies: 456 },
  { id: 10, text: "me explaining my trauma to my situationship at midnight 😭",          mood: "funny"        as Mood, accounts: 110, replies: 612 },
  { id: 11, text: "healing isn't linear and that's okay. keep going 🤍",                 mood: "relatable"    as Mood, accounts: 82, replies: 334 },
  { id: 12, text: "something is shifting. can you feel it? ✨",                           mood: "mystery"      as Mood, accounts: 64, replies: 172 },
];

const TOP_NOTES = [
  { text: "me explaining my trauma to my situationship at midnight 😭", replyRate: 5.56 },
  { text: "the right person won't need convincing 💌",                  replyRate: 4.80 },
  { text: "the version of you 3 years ago would be proud",              replyRate: 4.91 },
  { text: "your vibe is literally a magnet. protect it 🔥",             replyRate: 4.36 },
  { text: "my love language is sending memes at 2am",                   replyRate: 4.69 },
];

const MOOD_DISTRIBUTION: { mood: Mood; pct: number }[] = [
  { mood: "relatable",    pct: 22 },
  { mood: "flirty",       pct: 19 },
  { mood: "funny",        pct: 17 },
  { mood: "motivational", pct: 14 },
  { mood: "mystery",      pct: 11 },
  { mood: "spicy",        pct: 8  },
  { mood: "aesthetic",    pct: 5  },
  { mood: "nostalgic",    pct: 4  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function NotesPage() {
  const [moodFilter, setMoodFilter] = useState<Mood | "All">("All");

  const filteredCards =
    moodFilter === "All" ? NOTE_CARDS : NOTE_CARDS.filter((c) => c.mood === moodFilter);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Instagram · notes engine
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <MessageSquare className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            IG Notes <span className="phantom-accent-text">Engine</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-xs font-semibold">
            1.5M daily impressions
          </span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Mood-targeted IG Notes published across the fleet to drive DM replies and profile visits.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Notes Posted Today" value="487" delta={0.063} />
        <KPICard label="DM Replies Triggered" value="1,247" delta={0.114} />
        <KPICard label="Avg Reply Rate" value="0.83%" sub="vs 0.31% industry" />
        <KPICard label="Active Templates" value="120" sub="8 mood categories" />
      </div>

      {/* Main + side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Notes feed — 2 cols */}
        <div className="lg:col-span-2">
          <Panel
            label="live feed"
            title="Today's Notes Feed"
            actions={
              <select
                value={moodFilter}
                onChange={(e) => setMoodFilter(e.target.value as Mood | "All")}
                className="bg-phantom-panelHi border border-phantom-border text-phantom-ghost text-xs rounded px-2 py-1 focus:outline-none"
              >
                <option value="All">All moods</option>
                {Object.entries(MOOD_STYLES).map(([key, val]) => (
                  <option key={key} value={key}>{val.label}</option>
                ))}
              </select>
            }
          >
            <div className="columns-1 sm:columns-2 xl:columns-3 gap-4 space-y-4">
              {filteredCards.map((card) => {
                const mood = MOOD_STYLES[card.mood];
                return (
                  <div
                    key={card.id}
                    className="break-inside-avoid rounded-lg border border-phantom-border bg-phantom-panelHi p-4 space-y-3 hover:border-phantom-accent/30 transition-colors"
                  >
                    <p className="text-base font-medium text-white leading-snug">{card.text}</p>
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span
                        className={cn(
                          "px-2 py-0.5 rounded-full text-[10px] font-semibold border",
                          mood.bg,
                          mood.text,
                          "border-white/10"
                        )}
                      >
                        {mood.label}
                      </span>
                      <div className="flex items-center gap-3 text-[11px] text-phantom-ghost">
                        <span>{card.accounts} accts</span>
                        <span className="text-phantom-accent">{card.replies} replies</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>

        {/* Top Performers — 1 col */}
        <div className="space-y-6">
          <Panel label="rankings" title="Top Performing Notes">
            <div className="space-y-4">
              {TOP_NOTES.map((note, i) => (
                <div key={i} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] text-phantom-ghost">#{i + 1}</span>
                    <span className="text-xs font-semibold text-phantom-alive tabular-nums">
                      {note.replyRate.toFixed(2)}%
                    </span>
                  </div>
                  <p className="text-xs text-white leading-snug line-clamp-2">{note.text}</p>
                  <div className="h-1.5 rounded-full bg-phantom-border overflow-hidden">
                    <div
                      className="h-full rounded-full bg-phantom-accent"
                      style={{ width: `${(note.replyRate / 6) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          {/* Mood distribution */}
          <Panel label="composition" title="Mood Distribution">
            <div className="space-y-2.5">
              {MOOD_DISTRIBUTION.map(({ mood, pct }) => {
                const m = MOOD_STYLES[mood];
                return (
                  <div key={mood} className="space-y-1">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className={cn("font-medium", m.text)}>{m.label}</span>
                      <span className="text-phantom-ghost tabular-nums">{pct}%</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-phantom-border overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", m.bg.replace("/10", "/60"))}
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
