"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { use } from "react";
import {
  ChevronLeft, TrendingUp, Users, UserPlus, UserMinus,
  Heart, BookOpen, MessageCircle, Send, BarChart2,
} from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from "recharts";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

type DayStat = {
  date: string;      // "Apr 01"
  follows: number;
  unfollows: number;
  likes: number;
  stories: number;
  comments: number;
  dms: number;
  followers: number;
  following: number;
};

// ─── Demo data ────────────────────────────────────────────────────────────────

function generateDemo(): DayStat[] {
  const now = new Date();
  return Array.from({ length: 30 }, (_, i) => {
    const d = new Date(now);
    d.setDate(d.getDate() - (29 - i));
    const label = d.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
    const base = 10000 + i * 90 + Math.round(Math.sin(i * 0.5) * 200);
    return {
      date: label,
      follows:   Math.round(18 + Math.random() * 12),
      unfollows: Math.round(14 + Math.random() * 10),
      likes:     Math.round(55 + Math.random() * 40),
      stories:   Math.round(120 + Math.random() * 60),
      comments:  Math.round(Math.random() * 10),
      dms:       Math.round(Math.random() * 6),
      followers: base,
      following: Math.round(8000 + i * 15 + Math.random() * 30),
    };
  });
}

// ─── Custom tooltip ───────────────────────────────────────────────────────────

function PhantomTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-phantom-panel border border-phantom-border rounded-xl px-4 py-3 shadow-xl text-xs space-y-1.5 min-w-[130px]">
      <div className="text-phantom-ghost font-mono font-medium mb-2">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: p.color }} />
            <span className="text-phantom-ghost capitalize">{p.name}</span>
          </span>
          <span className="font-mono font-bold text-white tabular-nums">{p.value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Stat card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, icon, color }: {
  label: string; value: string | number; sub?: string;
  icon: React.ReactNode; color: string;
}) {
  return (
    <div className="phantom-panel px-5 py-4 flex items-start gap-4">
      <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center shrink-0", color)}>
        {icon}
      </div>
      <div>
        <div className="text-2xl font-display font-bold tabular-nums text-white">{typeof value === "number" ? value.toLocaleString() : value}</div>
        <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em] mt-0.5">{label}</div>
        {sub && <div className="text-[11px] text-phantom-ghost/50 mt-0.5">{sub}</div>}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AccountStatsPage({
  params,
}: {
  params: Promise<{ serial: string; account_id: string }>;
}) {
  const { serial, account_id } = use(params);
  const [data, setData] = useState<DayStat[]>(generateDemo());
  const [username, setUsername] = useState("tatiannalifee");
  const [range, setRange] = useState<7 | 14 | 30>(30);

  useEffect(() => {
    fetch(`http://localhost:8001/api/accounts/${account_id}/stats?days=30`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => {
        if (d?.days?.length) {
          setData(d.days);
          if (d.username) setUsername(d.username);
        }
      })
      .catch(() => {});
  }, [account_id]);

  const sliced = data.slice(-range);
  const latest = sliced[sliced.length - 1] ?? data[data.length - 1];
  const first  = sliced[0] ?? data[0];
  const followerGrowth = latest ? latest.followers - first.followers : 0;
  const totalFollows   = sliced.reduce((s, d) => s + d.follows, 0);
  const totalLikes     = sliced.reduce((s, d) => s + d.likes, 0);
  const totalStories   = sliced.reduce((s, d) => s + d.stories, 0);
  const followBackRate = totalFollows > 0
    ? Math.round((sliced.reduce((s, d) => s + d.unfollows, 0) / totalFollows) * 100)
    : 0;

  const ACCENT  = "hsl(162 100% 54%)";
  const MAGENTA = "hsl(292 91% 68%)";
  const AMBER   = "hsl(38 92% 58%)";
  const BLUE    = "hsl(213 94% 68%)";
  const GREEN   = "hsl(142 71% 45%)";
  const GHOST   = "hsl(240 5% 45%)";

  const chartStyle = {
    cartesianGrid: { stroke: "hsl(240 6% 18% / 0.5)", strokeDasharray: "4 4" },
    xAxis: { tick: { fill: "hsl(240 5% 45%)", fontSize: 10 }, axisLine: false, tickLine: false },
    yAxis: { tick: { fill: "hsl(240 5% 45%)", fontSize: 10 }, axisLine: false, tickLine: false },
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-phantom-ghost">
        <Link href="/fleet" className="hover:text-white transition-colors">Fleet</Link>
        <span>/</span>
        <Link href={`/fleet/${serial}`} className="hover:text-white transition-colors font-mono">{serial.slice(0, 10)}…</Link>
        <span>/</span>
        <Link href={`/fleet/${serial}/${account_id}/settings`} className="hover:text-white transition-colors">@{username}</Link>
        <span>/</span>
        <span className="text-white">Stats</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Account analytics</div>
          <h1 className="font-display text-3xl font-bold mt-1 tracking-tight flex items-center gap-3">
            <BarChart2 className="w-8 h-8 text-phantom-accent" strokeWidth={1.5} />
            @{username}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          {/* Range selector */}
          <div className="flex items-center border border-phantom-border rounded-lg overflow-hidden">
            {([7, 14, 30] as const).map((r) => (
              <button key={r} onClick={() => setRange(r)}
                className={cn("px-3 py-2 text-xs font-mono transition-colors",
                  range === r ? "bg-phantom-accent/15 text-phantom-accent" : "bg-phantom-panelHi text-phantom-ghost hover:text-white")}>
                {r}d
              </button>
            ))}
          </div>
          <Link href={`/fleet/${serial}/${account_id}/settings`}
            className="flex items-center gap-1.5 text-xs text-phantom-ghost hover:text-white transition-colors px-3 py-2">
            <ChevronLeft className="w-3.5 h-3.5" /> Settings
          </Link>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard label="Followers"      value={latest?.followers ?? 0}      sub={`+${followerGrowth.toLocaleString()} this period`}        icon={<Users      className="w-5 h-5 text-phantom-accent"  strokeWidth={1.5} />} color="bg-phantom-accent/10" />
        <StatCard label="Follows"        value={totalFollows}                 sub={`${range}d total`}  icon={<UserPlus   className="w-5 h-5 text-green-400"   strokeWidth={1.5} />} color="bg-green-400/10" />
        <StatCard label="Likes"          value={totalLikes}                   sub={`${range}d total`}  icon={<Heart      className="w-5 h-5 text-pink-400"    strokeWidth={1.5} />} color="bg-pink-400/10" />
        <StatCard label="Stories"        value={totalStories}                 sub={`${range}d total`}  icon={<BookOpen   className="w-5 h-5 text-phantom-amber"strokeWidth={1.5} />} color="bg-phantom-amber/10" />
        <StatCard label="Follow-back %"  value={`${followBackRate}%`}         sub="of follows returned" icon={<TrendingUp className="w-5 h-5 text-blue-400"   strokeWidth={1.5} />} color="bg-blue-400/10" />
        <StatCard label="Following"      value={latest?.following ?? 0}       icon={<UserMinus  className="w-5 h-5 text-phantom-ghost"strokeWidth={1.5} />} color="bg-phantom-panelHi" />
      </div>

      {/* Follower growth chart */}
      <div className="phantom-panel overflow-hidden">
        <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40">
          <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Follower growth · {range}d</span>
        </div>
        <div className="p-5">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={sliced} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid {...chartStyle.cartesianGrid} />
              <XAxis dataKey="date" {...chartStyle.xAxis} interval={Math.floor(sliced.length / 6)} />
              <YAxis {...chartStyle.yAxis} domain={["auto", "auto"]} />
              <Tooltip content={<PhantomTooltip />} />
              <Line type="monotone" dataKey="followers" name="followers" stroke={ACCENT}  strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="following" name="following" stroke={GHOST}   strokeWidth={1.5} dot={false} strokeDasharray="4 4" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Daily actions chart */}
      <div className="phantom-panel overflow-hidden">
        <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40">
          <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Daily actions · {range}d</span>
        </div>
        <div className="p-5">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={sliced} margin={{ top: 5, right: 10, bottom: 0, left: 0 }} barCategoryGap="30%">
              <CartesianGrid {...chartStyle.cartesianGrid} />
              <XAxis dataKey="date" {...chartStyle.xAxis} interval={Math.floor(sliced.length / 6)} />
              <YAxis {...chartStyle.yAxis} />
              <Tooltip content={<PhantomTooltip />} />
              <Legend wrapperStyle={{ fontSize: "11px", color: "hsl(240 5% 45%)", paddingTop: "12px" }} />
              <Bar dataKey="follows"   name="follows"   fill={ACCENT}  radius={[3,3,0,0]} maxBarSize={20} />
              <Bar dataKey="likes"     name="likes"     fill={MAGENTA} radius={[3,3,0,0]} maxBarSize={20} />
              <Bar dataKey="stories"   name="stories"   fill={AMBER}   radius={[3,3,0,0]} maxBarSize={20} />
              <Bar dataKey="comments"  name="comments"  fill={BLUE}    radius={[3,3,0,0]} maxBarSize={20} />
              <Bar dataKey="dms"       name="dms"       fill={GREEN}   radius={[3,3,0,0]} maxBarSize={20} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Follow / Unfollow balance */}
      <div className="phantom-panel overflow-hidden">
        <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40">
          <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Follow ↔ Unfollow balance · {range}d</span>
        </div>
        <div className="p-5">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={sliced} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid {...chartStyle.cartesianGrid} />
              <XAxis dataKey="date" {...chartStyle.xAxis} interval={Math.floor(sliced.length / 6)} />
              <YAxis {...chartStyle.yAxis} />
              <Tooltip content={<PhantomTooltip />} />
              <Legend wrapperStyle={{ fontSize: "11px", color: "hsl(240 5% 45%)", paddingTop: "12px" }} />
              <Line type="monotone" dataKey="follows"   name="follows"   stroke={ACCENT}  strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="unfollows" name="unfollows" stroke={MAGENTA} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Raw data table */}
      <div className="phantom-panel overflow-hidden">
        <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Raw data · last {range} days</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-phantom-border bg-phantom-panelHi/30">
                {["Date", "Followers", "Following", "Follows", "Unfollows", "Likes", "Stories", "Comments", "DMs"].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-[10px] uppercase tracking-[0.12em] text-phantom-ghost font-medium text-left whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...sliced].reverse().map((row, i) => (
                <tr key={i} className="border-b border-phantom-border/30 hover:bg-phantom-panelHi/20 transition-colors">
                  <td className="px-4 py-2 font-mono text-phantom-ghost">{row.date}</td>
                  <td className="px-4 py-2 font-mono text-white tabular-nums">{row.followers.toLocaleString()}</td>
                  <td className="px-4 py-2 font-mono text-white tabular-nums">{row.following.toLocaleString()}</td>
                  <td className="px-4 py-2 font-mono text-phantom-accent tabular-nums">{row.follows}</td>
                  <td className="px-4 py-2 font-mono text-phantom-magenta tabular-nums">{row.unfollows}</td>
                  <td className="px-4 py-2 font-mono text-pink-400 tabular-nums">{row.likes}</td>
                  <td className="px-4 py-2 font-mono text-phantom-amber tabular-nums">{row.stories}</td>
                  <td className="px-4 py-2 font-mono tabular-nums">{row.comments}</td>
                  <td className="px-4 py-2 font-mono tabular-nums">{row.dms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
