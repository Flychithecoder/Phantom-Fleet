"use client";

import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import {
  Server,
  Wifi,
  Battery,
  Clock,
  CheckCircle2,
  AlertCircle,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

type InterestCategory = "fitness" | "sports" | "lifestyle" | "cars_tech";

const INTEREST_COLORS: Record<InterestCategory, string> = {
  fitness:   "bg-green-500/20 text-green-400 border-green-500/30",
  sports:    "bg-blue-500/20 text-blue-400 border-blue-500/30",
  lifestyle: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  cars_tech: "bg-orange-500/20 text-orange-400 border-orange-500/30",
};

const INTEREST_LABELS: Record<InterestCategory, string> = {
  fitness:   "Fitness",
  sports:    "Sports",
  lifestyle: "Lifestyle",
  cars_tech: "Cars / Tech",
};

type AccountRow = {
  id: string;
  username: string;
  personaName: string;
  category: InterestCategory;
  likes: number;
  comments: number;
  status: "active" | "idle" | "capped";
};

// 48 mock accounts representing the male pod box
const ACCOUNTS: AccountRow[] = [
  { id: "m001", username: "liam_smit_94",    personaName: "Liam Smith",       category: "fitness",   likes: 14, comments: 3, status: "capped"  },
  { id: "m002", username: "hoops_noah",       personaName: "Noah Williams",    category: "sports",    likes: 11, comments: 2, status: "active"  },
  { id: "m003", username: "mason_nyc",        personaName: "Mason Brown",      category: "lifestyle", likes: 8,  comments: 1, status: "active"  },
  { id: "m004", username: "real_ethan",       personaName: "Ethan Garcia",     category: "cars_tech", likes: 15, comments: 3, status: "capped"  },
  { id: "m005", username: "lucas_johns_97",   personaName: "Lucas Johnson",    category: "fitness",   likes: 12, comments: 2, status: "active"  },
  { id: "m006", username: "footy_aiden",      personaName: "Aiden Davis",      category: "sports",    likes: 10, comments: 1, status: "active"  },
  { id: "m007", username: "james_la",         personaName: "James Wilson",     category: "lifestyle", likes: 7,  comments: 0, status: "idle"    },
  { id: "m008", username: "og_logan",         personaName: "Logan Moore",      category: "cars_tech", likes: 9,  comments: 2, status: "active"  },
  { id: "m009", username: "jackson_taylo_03", personaName: "Jackson Taylor",   category: "fitness",   likes: 15, comments: 3, status: "capped"  },
  { id: "m010", username: "ballin_sebastian", personaName: "Sebastian Anderson",category: "sports",   likes: 13, comments: 2, status: "active"  },
  { id: "m011", username: "mateo_chicago",    personaName: "Mateo Thomas",     category: "lifestyle", likes: 6,  comments: 1, status: "active"  },
  { id: "m012", username: "fast_henry",       personaName: "Henry Jackson",    category: "cars_tech", likes: 11, comments: 0, status: "active"  },
  { id: "m013", username: "owen_white_01",    personaName: "Owen White",       category: "fitness",   likes: 14, comments: 3, status: "capped"  },
  { id: "m014", username: "striker_alex",     personaName: "Alexander Harris", category: "sports",    likes: 8,  comments: 2, status: "active"  },
  { id: "m015", username: "daniel_dc",        personaName: "Daniel Martin",    category: "lifestyle", likes: 10, comments: 1, status: "active"  },
  { id: "m016", username: "big_elijah",       personaName: "Elijah Thompson",  category: "cars_tech", likes: 12, comments: 2, status: "active"  },
  { id: "m017", username: "ben_jones_99",     personaName: "Benjamin Young",   category: "fitness",   likes: 15, comments: 3, status: "capped"  },
  { id: "m018", username: "courtside_carter", personaName: "Carter Allen",     category: "sports",    likes: 9,  comments: 1, status: "active"  },
  { id: "m019", username: "dylan_miami",      personaName: "Dylan King",       category: "lifestyle", likes: 7,  comments: 0, status: "idle"    },
  { id: "m020", username: "raw_ryan",         personaName: "Ryan Wright",      category: "cars_tech", likes: 11, comments: 2, status: "active"  },
  { id: "m021", username: "nathan_scott_00",  personaName: "Nathan Scott",     category: "fitness",   likes: 13, comments: 2, status: "active"  },
  { id: "m022", username: "baller_caleb",     personaName: "Caleb Green",      category: "sports",    likes: 10, comments: 3, status: "active"  },
  { id: "m023", username: "jayden_austin",    personaName: "Jayden Baker",     category: "lifestyle", likes: 8,  comments: 1, status: "active"  },
  { id: "m024", username: "goat_hunter",      personaName: "Hunter Adams",     category: "cars_tech", likes: 14, comments: 0, status: "active"  },
  { id: "m025", username: "christian_nyc",    personaName: "Christian Nelson", category: "fitness",   likes: 15, comments: 3, status: "capped"  },
  { id: "m026", username: "netter_isaiah",    personaName: "Isaiah Hill",      category: "sports",    likes: 7,  comments: 1, status: "active"  },
  { id: "m027", username: "connor_seattl_98", personaName: "Connor Ramirez",   category: "lifestyle", likes: 9,  comments: 2, status: "active"  },
  { id: "m028", username: "true_evan",        personaName: "Evan Campbell",    category: "cars_tech", likes: 12, comments: 1, status: "active"  },
  { id: "m029", username: "tyler_mitch_96",   personaName: "Tyler Mitchell",   category: "fitness",   likes: 11, comments: 2, status: "active"  },
  { id: "m030", username: "gridiron_zach",    personaName: "Zachary Roberts",  category: "sports",    likes: 8,  comments: 0, status: "idle"    },
  { id: "m031", username: "jordan_carter_02", personaName: "Jordan Carter",    category: "lifestyle", likes: 10, comments: 1, status: "active"  },
  { id: "m032", username: "sly_austin",       personaName: "Austin Phillips",  category: "cars_tech", likes: 13, comments: 3, status: "active"  },
  { id: "m033", username: "brandon_denver",   personaName: "Brandon Evans",    category: "fitness",   likes: 15, comments: 3, status: "capped"  },
  { id: "m034", username: "pitchside_chase",  personaName: "Chase Turner",     category: "sports",    likes: 6,  comments: 1, status: "active"  },
  { id: "m035", username: "cody_torres_01",   personaName: "Cody Torres",      category: "lifestyle", likes: 9,  comments: 0, status: "idle"    },
  { id: "m036", username: "young_derek",      personaName: "Derek Parker",     category: "cars_tech", likes: 12, comments: 2, status: "active"  },
  { id: "m037", username: "dom_boston",       personaName: "Dominic Collins",  category: "fitness",   likes: 14, comments: 2, status: "active"  },
  { id: "m038", username: "hoops_eric",       personaName: "Eric Edwards",     category: "sports",    likes: 11, comments: 1, status: "active"  },
  { id: "m039", username: "finn_philly",      personaName: "Finn Stewart",     category: "lifestyle", likes: 8,  comments: 1, status: "active"  },
  { id: "m040", username: "pure_gage",        personaName: "Gage Flores",      category: "cars_tech", likes: 10, comments: 0, status: "idle"    },
  { id: "m041", username: "garrett_la",       personaName: "Garrett Morris",   category: "fitness",   likes: 15, comments: 3, status: "capped"  },
  { id: "m042", username: "footy_gavin",      personaName: "Gavin Nguyen",     category: "sports",    likes: 9,  comments: 2, status: "active"  },
  { id: "m043", username: "grant_seattl_99",  personaName: "Grant Murphy",     category: "lifestyle", likes: 7,  comments: 1, status: "active"  },
  { id: "m044", username: "big_griffin",      personaName: "Griffin Rivera",   category: "cars_tech", likes: 13, comments: 2, status: "active"  },
  { id: "m045", username: "hayden_cook_97",   personaName: "Hayden Cook",      category: "fitness",   likes: 12, comments: 1, status: "active"  },
  { id: "m046", username: "ballin_ian",       personaName: "Ian Rogers",       category: "sports",    likes: 10, comments: 2, status: "active"  },
  { id: "m047", username: "jake_houston",     personaName: "Jake Morgan",      category: "lifestyle", likes: 8,  comments: 0, status: "idle"    },
  { id: "m048", username: "og_jason",         personaName: "Jason Peterson",   category: "cars_tech", likes: 14, comments: 3, status: "active"  },
];

type PendingPost = {
  id: string;
  creatorAccount: string;
  postTime: string;
  minutesRemaining: number;
  engaged: number;
  total: number;
};

const PENDING_POSTS: PendingPost[] = [
  { id: "p1", creatorAccount: "@creator_luna",   postTime: "12 min ago", minutesRemaining: 78, engaged: 48, total: 48 },
  { id: "p2", creatorAccount: "@model_sophia",   postTime: "34 min ago", minutesRemaining: 56, engaged: 43, total: 48 },
  { id: "p3", creatorAccount: "@ella_official",  postTime: "51 min ago", minutesRemaining: 39, engaged: 22, total: 48 },
  { id: "p4", creatorAccount: "@creator_nova",   postTime: "1h 3m ago",  minutesRemaining: 27, engaged: 11, total: 48 },
  { id: "p5", creatorAccount: "@mia_content",    postTime: "1h 21m ago", minutesRemaining: 9,  engaged: 3,  total: 48 },
];

type ActivityEntry = {
  ago: string;
  username: string;
  action: string;
  target: string;
  delay: string;
};

const ACTIVITY_FEED: ActivityEntry[] = [
  { ago: "23s ago",  username: "liam_smit_94",    action: "liked",            target: "@creator_luna",   delay: "3.1s delay"  },
  { ago: "41s ago",  username: "hoops_noah",       action: "liked",            target: "@creator_luna",   delay: "5.7s delay"  },
  { ago: "58s ago",  username: "mason_nyc",        action: "commented",        target: "@creator_luna",   delay: "4.2s delay"  },
  { ago: "1m ago",   username: "real_ethan",       action: "liked",            target: "@creator_luna",   delay: "6.8s delay"  },
  { ago: "2m ago",   username: "jackson_taylo_03", action: "liked + commented",target: "@creator_luna",   delay: "3.9s delay"  },
  { ago: "4m ago",   username: "liam_smit_94",     action: "liked",            target: "@model_sophia",   delay: "7.2s delay"  },
  { ago: "6m ago",   username: "christian_nyc",    action: "liked + commented",target: "@model_sophia",   delay: "4.5s delay"  },
  { ago: "8m ago",   username: "hoops_eric",       action: "liked",            target: "@model_sophia",   delay: "5.1s delay"  },
  { ago: "11m ago",  username: "og_jason",         action: "liked",            target: "@ella_official",  delay: "3.8s delay"  },
  { ago: "14m ago",  username: "dom_boston",       action: "liked + commented",target: "@ella_official",  delay: "6.3s delay"  },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: AccountRow["status"] }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full border",
        status === "active" && "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/30",
        status === "idle"   && "bg-phantom-ghost/10 text-phantom-ghost border-phantom-ghost/20",
        status === "capped" && "bg-amber-500/10 text-amber-400 border-amber-500/30",
      )}
    >
      {status === "active" && <span className="w-1.5 h-1.5 rounded-full bg-phantom-accent animate-pulse" />}
      {status === "idle"   && <span className="w-1.5 h-1.5 rounded-full bg-phantom-ghost/60" />}
      {status === "capped" && <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />}
      {status === "active" ? "Active" : status === "idle" ? "Idle" : "Capped"}
    </span>
  );
}

function InterestBadge({ category }: { category: InterestCategory }) {
  return (
    <span
      className={cn(
        "inline-block text-[10px] font-medium px-2 py-0.5 rounded-full border",
        INTEREST_COLORS[category],
      )}
    >
      {INTEREST_LABELS[category]}
    </span>
  );
}

function EngagementBar({ value, max }: { value: number; max: number }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 rounded-full bg-phantom-border overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            pct === 100 ? "bg-phantom-accent" : pct > 60 ? "bg-blue-500" : "bg-amber-500",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-phantom-ghost tabular-nums">
        {value} / {max}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function S10BoxPage() {
  const activeCount   = ACCOUNTS.filter(a => a.status === "active").length;
  const cappedCount   = ACCOUNTS.filter(a => a.status === "capped").length;
  const totalLikes    = ACCOUNTS.reduce((s, a) => s + a.likes, 0);
  const totalComments = ACCOUNTS.reduce((s, a) => s + a.comments, 0);
  const totalActions  = totalLikes + totalComments;

  return (
    <main className="flex-1 p-6 space-y-6 overflow-y-auto">

      {/* ── Page header ── */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-display font-bold">S10 Male Pod Box</h1>
            <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-full bg-phantom-accent/10 text-phantom-accent border border-phantom-accent/30">
              <Zap className="w-3 h-3" />
              Dedicated Hardware
            </span>
          </div>
          <p className="text-sm text-phantom-ghost">
            48 Male Accounts · Pod Engine Only · Direct IG Mobile API · No Accessibility Service
          </p>
        </div>
      </div>

      {/* ── KPI strip ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Active Accounts"
          value={`${activeCount + cappedCount}`}
          sub={`${cappedCount} daily-capped`}
        />
        <KPICard
          label="Pod Actions Today"
          value={totalActions.toLocaleString()}
          sub={`${totalLikes} likes · ${totalComments} comments`}
        />
        <KPICard
          label="Avg Response Time"
          value="4.2 min"
          sub="median across all pods"
        />
        <KPICard
          label="Posts Pushed to Explore"
          value="23"
          sub="estimated Explore boosts today"
        />
      </div>

      {/* ── S10 Box Status ── */}
      <Panel label="Hardware" title="S10 Box Status">
        {/* Phone card */}
        <div className="flex items-center gap-4 p-4 rounded-xl border border-phantom-border bg-phantom-panelHi/40 mb-6">
          <div className="w-10 h-10 rounded-lg bg-phantom-accent/10 border border-phantom-accent/20 flex items-center justify-center shrink-0">
            <Server className="w-5 h-5 text-phantom-accent" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="font-semibold text-sm">Samsung Galaxy S10</span>
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-phantom-accent/10 text-phantom-accent border border-phantom-accent/20">
                Pod Engine Only
              </span>
            </div>
            <div className="text-xs text-phantom-ghost font-mono">
              Serial: R38M30WXPAS · 8 GB RAM · 128 GB
            </div>
          </div>
          <div className="flex items-center gap-4 text-xs text-phantom-ghost shrink-0">
            <div className="flex items-center gap-1.5">
              <Wifi className="w-3.5 h-3.5 text-phantom-accent" />
              <span className="text-phantom-accent font-medium">Connected</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Battery className="w-3.5 h-3.5 text-green-400" />
              <span className="text-green-400 font-medium">87%</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-medium">48 clones active</span>
            </div>
          </div>
        </div>

        {/* Accounts table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border text-left">
                <th className="pb-2 pr-4 text-[11px] uppercase tracking-widest text-phantom-ghost font-medium">Username</th>
                <th className="pb-2 pr-4 text-[11px] uppercase tracking-widest text-phantom-ghost font-medium">Persona</th>
                <th className="pb-2 pr-4 text-[11px] uppercase tracking-widest text-phantom-ghost font-medium">Interest</th>
                <th className="pb-2 pr-4 text-[11px] uppercase tracking-widest text-phantom-ghost font-medium text-right">Likes</th>
                <th className="pb-2 pr-4 text-[11px] uppercase tracking-widest text-phantom-ghost font-medium text-right">Comments</th>
                <th className="pb-2 text-[11px] uppercase tracking-widest text-phantom-ghost font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-phantom-border/50">
              {ACCOUNTS.map((account) => (
                <tr key={account.id} className="group hover:bg-phantom-panelHi/30 transition-colors">
                  <td className="py-2 pr-4">
                    <span className="font-mono text-xs text-phantom-text">@{account.username}</span>
                  </td>
                  <td className="py-2 pr-4">
                    <span className="text-xs text-phantom-ghost">{account.personaName}</span>
                  </td>
                  <td className="py-2 pr-4">
                    <InterestBadge category={account.category} />
                  </td>
                  <td className="py-2 pr-4 text-right">
                    <span className={cn(
                      "text-xs font-mono tabular-nums",
                      account.likes >= 15 ? "text-amber-400" : "text-phantom-text"
                    )}>
                      {account.likes}
                      <span className="text-phantom-ghost/60">/15</span>
                    </span>
                  </td>
                  <td className="py-2 pr-4 text-right">
                    <span className={cn(
                      "text-xs font-mono tabular-nums",
                      account.comments >= 3 ? "text-amber-400" : "text-phantom-text"
                    )}>
                      {account.comments}
                      <span className="text-phantom-ghost/60">/3</span>
                    </span>
                  </td>
                  <td className="py-2">
                    <StatusBadge status={account.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ── Pending Pod Queue ── */}
      <Panel label="Engagement Queue" title="Pending Pod Queue">
        <div className="space-y-3">
          {PENDING_POSTS.map((post) => (
            <div
              key={post.id}
              className="flex items-center gap-4 p-3 rounded-lg border border-phantom-border bg-phantom-panelHi/20 hover:bg-phantom-panelHi/40 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-sm font-medium">{post.creatorAccount}</span>
                  <span className="text-xs text-phantom-ghost">{post.postTime}</span>
                  <span className={cn(
                    "text-[10px] font-medium px-1.5 py-0.5 rounded border",
                    post.minutesRemaining <= 15
                      ? "bg-red-500/10 text-red-400 border-red-500/30"
                      : post.minutesRemaining <= 40
                      ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                      : "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/30"
                  )}>
                    <Clock className="w-2.5 h-2.5 inline mr-0.5" />
                    {post.minutesRemaining}m left
                  </span>
                </div>
                <EngagementBar value={post.engaged} max={post.total} />
              </div>
              <div className="shrink-0">
                {post.engaged === post.total ? (
                  <CheckCircle2 className="w-5 h-5 text-phantom-accent" />
                ) : (
                  <AlertCircle className="w-5 h-5 text-amber-400 animate-pulse" />
                )}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* ── Activity Feed ── */}
      <Panel label="Live Log" title="Today's Activity Feed">
        <div className="space-y-2">
          {ACTIVITY_FEED.map((entry, i) => (
            <div
              key={i}
              className="flex items-center gap-3 py-2 border-b border-phantom-border/40 last:border-0"
            >
              <span className="text-[10px] text-phantom-ghost/60 font-mono w-16 shrink-0">
                {entry.ago}
              </span>
              <span className="text-xs font-mono text-phantom-accent">
                @{entry.username}
              </span>
              <span className="text-xs text-phantom-ghost">
                {entry.action}
              </span>
              <span className="text-xs font-medium">
                {entry.target}
              </span>
              <span className="text-[10px] text-phantom-ghost/50 ml-auto font-mono">
                pod duty · {entry.delay}
              </span>
            </div>
          ))}
        </div>
      </Panel>

    </main>
  );
}
