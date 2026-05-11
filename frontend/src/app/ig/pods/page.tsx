"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { KPICard } from "@/components/kpi-card";
import { Network } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const AVATAR_COLORS = [
  "bg-pink-500", "bg-purple-500", "bg-blue-500", "bg-teal-500",
  "bg-orange-500", "bg-amber-500", "bg-rose-500", "bg-indigo-500",
];

type Pod = {
  id: string;
  members: number;
  engagements: number;
  avatars: { initials: string; color: string }[];
  status: "Active" | "Resting";
};

const PODS: Pod[] = [
  { id: "POD-001", members: 14, engagements: 312, avatars: [{ initials: "LV", color: AVATAR_COLORS[0] }, { initials: "MA", color: AVATAR_COLORS[1] }, { initials: "SE", color: AVATAR_COLORS[2] }, { initials: "GF", color: AVATAR_COLORS[3] }], status: "Active" },
  { id: "POD-002", members: 11, engagements: 198, avatars: [{ initials: "NV", color: AVATAR_COLORS[4] }, { initials: "JK", color: AVATAR_COLORS[5] }, { initials: "AC", color: AVATAR_COLORS[6] }], status: "Active" },
  { id: "POD-003", members: 13, engagements: 0,   avatars: [{ initials: "RB", color: AVATAR_COLORS[7] }, { initials: "CM", color: AVATAR_COLORS[0] }, { initials: "TS", color: AVATAR_COLORS[1] }], status: "Resting" },
  { id: "POD-004", members: 15, engagements: 487, avatars: [{ initials: "EL", color: AVATAR_COLORS[2] }, { initials: "PW", color: AVATAR_COLORS[3] }, { initials: "DH", color: AVATAR_COLORS[4] }, { initials: "BK", color: AVATAR_COLORS[5] }], status: "Active" },
  { id: "POD-005", members: 10, engagements: 221, avatars: [{ initials: "ZM", color: AVATAR_COLORS[6] }, { initials: "VN", color: AVATAR_COLORS[7] }, { initials: "YT", color: AVATAR_COLORS[0] }], status: "Active" },
  { id: "POD-006", members: 12, engagements: 0,   avatars: [{ initials: "XR", color: AVATAR_COLORS[1] }, { initials: "WP", color: AVATAR_COLORS[2] }, { initials: "UA", color: AVATAR_COLORS[3] }], status: "Resting" },
  { id: "POD-007", members: 14, engagements: 543, avatars: [{ initials: "LM", color: AVATAR_COLORS[4] }, { initials: "KJ", color: AVATAR_COLORS[5] }, { initials: "IH", color: AVATAR_COLORS[6] }, { initials: "GE", color: AVATAR_COLORS[7] }], status: "Active" },
  { id: "POD-008", members: 11, engagements: 304, avatars: [{ initials: "FD", color: AVATAR_COLORS[0] }, { initials: "EC", color: AVATAR_COLORS[1] }, { initials: "DB", color: AVATAR_COLORS[2] }], status: "Active" },
  { id: "POD-009", members: 13, engagements: 178, avatars: [{ initials: "CA", color: AVATAR_COLORS[3] }, { initials: "BZ", color: AVATAR_COLORS[4] }, { initials: "AY", color: AVATAR_COLORS[5] }], status: "Active" },
  { id: "POD-010", members: 10, engagements: 0,   avatars: [{ initials: "ZX", color: AVATAR_COLORS[6] }, { initials: "YW", color: AVATAR_COLORS[7] }, { initials: "XV", color: AVATAR_COLORS[0] }], status: "Resting" },
  { id: "POD-011", members: 15, engagements: 612, avatars: [{ initials: "WT", color: AVATAR_COLORS[1] }, { initials: "VS", color: AVATAR_COLORS[2] }, { initials: "UR", color: AVATAR_COLORS[3] }, { initials: "TQ", color: AVATAR_COLORS[4] }], status: "Active" },
  { id: "POD-012", members: 12, engagements: 289, avatars: [{ initials: "SP", color: AVATAR_COLORS[5] }, { initials: "RO", color: AVATAR_COLORS[6] }, { initials: "QN", color: AVATAR_COLORS[7] }], status: "Active" },
];

const ACTIVITY_FEED = [
  { ts: "2min ago",  pod: "POD-007", actor: "@luna_aesthetic",   action: "reacted 🔥 to",  target: "@mia_vibes", boost: 12 },
  { ts: "4min ago",  pod: "POD-004", actor: "@swift_emma_42",    action: "commented on",   target: "@nova_daily", boost: 8 },
  { ts: "7min ago",  pod: "POD-011", actor: "@grace_fit_life",   action: "saved post from", target: "@aria_content", boost: 15 },
  { ts: "11min ago", pod: "POD-001", actor: "@jade_glowup",      action: "shared story of", target: "@luna_aesthetic", boost: 6 },
  { ts: "15min ago", pod: "POD-007", actor: "@stella_vibes",     action: "reacted ❤️ to",  target: "@swift_emma_42", boost: 12 },
  { ts: "19min ago", pod: "POD-009", actor: "@mia_vibes",        action: "commented on",   target: "@grace_fit_life", boost: 9 },
  { ts: "24min ago", pod: "POD-004", actor: "@nova_daily",       action: "reacted 🎯 to",  target: "@jade_glowup", boost: 11 },
  { ts: "31min ago", pod: "POD-012", actor: "@aria_content",     action: "saved post from", target: "@stella_vibes", boost: 7 },
  { ts: "38min ago", pod: "POD-011", actor: "@luna_aesthetic",   action: "shared story of", target: "@swift_emma_42", boost: 14 },
  { ts: "44min ago", pod: "POD-001", actor: "@jade_glowup",      action: "reacted 🔥 to",  target: "@mia_vibes", boost: 10 },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PodsPage() {
  const [statusFilter, setStatusFilter] = useState<"All" | "Active" | "Resting">("All");

  const filteredPods =
    statusFilter === "All" ? PODS : PODS.filter((p) => p.status === statusFilter);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Instagram · engagement pods
        </div>
        <div className="flex items-center gap-3 mt-2 flex-wrap">
          <Network className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <h1 className="font-display text-4xl font-bold tracking-tight">
            Engagement Pod <span className="phantom-accent-text">Network</span>
          </h1>
          <span className="px-3 py-1 rounded-full bg-phantom-accent/10 border border-phantom-accent/20 text-phantom-accent text-xs font-semibold">
            41 Active Pods
          </span>
          <span className="text-phantom-ghost text-sm">· 6,000 engagements/day</span>
        </div>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Coordinated pod engagement network pushing posts to Explore via mutual reactions, saves, and shares.
        </p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Active Pods" value="41" delta={0.025} />
        <KPICard label="Avg Pod Size" value="12.3" sub="members per pod" />
        <KPICard label="Engagements Today" value="5,847" delta={0.091} />
        <KPICard label="Posts Pushed to Explore" value="23" sub="est. from pod signals" accent />
      </div>

      {/* Pod grid */}
      <Panel
        label="pods"
        title="All Pods"
        actions={
          <div className="flex gap-1.5">
            {(["All", "Active", "Resting"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={`px-3 py-1 rounded text-xs font-medium transition-all border ${
                  statusFilter === f
                    ? "bg-phantom-accent/10 border-phantom-accent/30 text-phantom-accent"
                    : "border-phantom-border text-phantom-ghost hover:text-white hover:bg-phantom-panelHi"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        }
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {filteredPods.map((pod) => (
            <div
              key={pod.id}
              className="rounded-lg border border-phantom-border bg-phantom-panelHi p-4 space-y-3 hover:border-phantom-accent/30 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs font-bold text-phantom-accent">{pod.id}</span>
                {pod.status === "Active" ? (
                  <span className="px-2 py-0.5 rounded-full bg-phantom-alive/10 border border-phantom-alive/20 text-phantom-alive text-[10px] font-semibold">
                    Active
                  </span>
                ) : (
                  <span className="px-2 py-0.5 rounded-full bg-phantom-ghost/10 border border-phantom-border text-phantom-ghost text-[10px] font-semibold">
                    Resting
                  </span>
                )}
              </div>
              <div className="flex items-center gap-4 text-[11px] text-phantom-ghost">
                <span><span className="text-white font-semibold">{pod.members}</span> members</span>
                <span>
                  <span className={cn("font-semibold", pod.engagements > 0 ? "text-phantom-accent" : "text-phantom-ghost")}>
                    {pod.engagements.toLocaleString()}
                  </span> eng
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                {pod.avatars.map((av, i) => (
                  <div
                    key={i}
                    className={cn(
                      "w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0",
                      av.color
                    )}
                  >
                    {av.initials}
                  </div>
                ))}
                {pod.members > pod.avatars.length && (
                  <div className="w-7 h-7 rounded-full bg-phantom-border flex items-center justify-center text-[10px] text-phantom-ghost">
                    +{pod.members - pod.avatars.length}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* Activity feed */}
      <Panel label="live activity" title="Recent Pod Activity Feed">
        <div className="space-y-2">
          {ACTIVITY_FEED.map((entry, i) => (
            <div
              key={i}
              className="flex items-start gap-3 px-4 py-3 rounded-lg bg-phantom-panelHi border border-phantom-border hover:border-phantom-accent/20 transition-colors"
            >
              <span className="phantom-dot bg-phantom-accent animate-phantom-pulse mt-1.5 shrink-0" />
              <div className="flex-1 min-w-0 text-xs text-phantom-ghost">
                <span className="font-mono text-phantom-ghost/60 mr-2">[{entry.ts}]</span>
                <span className="text-phantom-accent font-semibold">{entry.pod}</span>
                {" · "}
                <span className="text-white">{entry.actor}</span>
                {" "}
                <span>{entry.action}</span>
                {" "}
                <span className="text-white">{entry.target}&apos;s post</span>
                {" · "}
                <span className="text-phantom-alive">+{entry.boost} pod engagements queued</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
