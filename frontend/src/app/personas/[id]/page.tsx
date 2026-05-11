"use client";

import { use } from "react";
import { Panel } from "@/components/panel";
import { StatRing } from "@/components/stat-ring";
import { Sparkline } from "@/components/sparkline";
import { Users, Cpu, Target, TrendingUp } from "lucide-react";

const PERSONAS: Record<string, any> = {
  tatiana: {
    name: "Tatiana",
    gender: "Female, 22, NYC",
    bio: "Computer science dropout, neon-cyan aesthetic, posts every morning and evening. Loves streetwear and electronic music. Claims NY location, en-US locale, America/New_York timezone, Samsung SM-G770F device model.",
    accounts: 97,
    phones: 9,
    aggressiveness: 1.08,
    survival30d: 0.994,
    engagement: 0.067,
    conversion: 0.032,
    ofRevenue: 2_340,
    peak_hour: 21,
    active_window: "9am - 11pm ET",
    biometrics: {
      tapDwell: "124 ms",
      keyStroke: "186 ms",
      typoRate: "2.8%",
      scrollVel: "2,450 px/s",
      sessionLen: "12.4 min",
    },
    sparkline: [22, 28, 31, 25, 29, 34, 38, 41, 37, 42, 44, 39, 45, 48, 52],
  },
  melodie: {
    name: "Melodie",
    gender: "Female, 21, Brooklyn",
    bio: "Digital creator, pastel aesthetic, morning person. Posts brunch photos and acoustic covers. Claims Brooklyn location, en-US locale, America/New_York timezone.",
    accounts: 122,
    phones: 10,
    aggressiveness: 0.96,
    survival30d: 0.992,
    engagement: 0.081,
    conversion: 0.045,
    ofRevenue: 3_120,
    peak_hour: 10,
    active_window: "7am - 10pm ET",
    biometrics: {
      tapDwell: "118 ms",
      keyStroke: "192 ms",
      typoRate: "3.1%",
      scrollVel: "2,210 px/s",
      sessionLen: "11.8 min",
    },
    sparkline: [18, 24, 27, 30, 33, 31, 36, 40, 42, 45, 43, 48, 51, 49, 54],
  },
};

export default function PersonaDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const p = PERSONAS[id] || PERSONAS.tatiana;

  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Persona detail · locked biometrics
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Users className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <span className="phantom-accent-text">{p.name}</span>
          <span className="text-sm font-normal text-phantom-ghost ml-2">{p.gender}</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-2xl">{p.bio}</p>
      </div>

      {/* KPI rings */}
      <div className="phantom-panel p-8">
        <div className="grid grid-cols-3 gap-8 place-items-center">
          <StatRing value={p.survival30d} label="30-day survival" sub={`${p.accounts} alive`} color="phantom-alive" />
          <StatRing value={p.engagement} label="engagement rate" color="phantom-accent" />
          <StatRing value={p.conversion} label="funnel conversion" color="phantom-magenta" />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Biometrics */}
        <Panel label="locked biometrics" title={
          <span className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
            Behavioral profile
          </span>
        } subtitle="Sampled once at persona creation. Immutable for life.">
          <div className="space-y-3 text-sm">
            {Object.entries(p.biometrics).map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-phantom-border/30 pb-2">
                <span className="text-phantom-ghost capitalize">{k.replace(/([A-Z])/g, " $1")}</span>
                <span className="font-mono tabular-nums text-white">{v as string}</span>
              </div>
            ))}
          </div>
        </Panel>

        {/* Targeting */}
        <Panel label="targeting" title={
          <span className="flex items-center gap-2">
            <Target className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
            Source pool
          </span>
        }>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between"><span className="text-phantom-ghost">Approved sources</span><span className="font-mono">173</span></div>
            <div className="flex justify-between"><span className="text-phantom-ghost">Premium sources</span><span className="font-mono text-phantom-accent">21</span></div>
            <div className="flex justify-between"><span className="text-phantom-ghost">Fresh targets today</span><span className="font-mono">2,140</span></div>
            <div className="flex justify-between"><span className="text-phantom-ghost">FBR (7d avg)</span><span className="font-mono text-phantom-alive">26.4%</span></div>
            <div className="flex justify-between"><span className="text-phantom-ghost">Peak hour local</span><span className="font-mono">{p.peak_hour}:00</span></div>
            <div className="flex justify-between"><span className="text-phantom-ghost">Active window</span><span className="font-mono text-xs">{p.active_window}</span></div>
          </div>
        </Panel>

        {/* Revenue */}
        <Panel label="revenue" title={
          <span className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
            Funnel ROI
          </span>
        }>
          <div className="space-y-4">
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">OF revenue (30d)</div>
              <div className="phantom-metric text-4xl mt-1 text-phantom-accent tabular-nums">
                ${p.ofRevenue.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost mb-1">Follower growth · 15d</div>
              <Sparkline data={p.sparkline} label="followers/day" />
            </div>
            <div className="pt-2 border-t border-phantom-border">
              <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Aggressiveness</div>
              <div className="text-sm font-mono mt-1">{p.aggressiveness.toFixed(2)}× base</div>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
