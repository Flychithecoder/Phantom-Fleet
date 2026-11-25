"use client";

import { useCallback, useEffect, useState } from "react";
import { Panel } from "@/components/panel";
import { ShieldCheck, Check, X, RefreshCw, Target, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

type PendingTargetRaw = {
  id: number;
  farm_id: string | null;
  kind: string;
  handle: string;
  media_code: string | null;
  tags_json: string | null;
  locale: string | null;
  source: string;
  imported_ms: number;
};

type PendingTarget = Omit<PendingTargetRaw, "tags_json"> & { tags: string[] };

function parseTags(s: string | null): string[] {
  if (!s) return [];
  try {
    const v = JSON.parse(s);
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

type PendingComment = {
  id: number;
  text: string;
  niche: string;
  source: string;
  imported_ms: number;
};

type Counts = {
  pending_target_approvals: number;
  pending_comment_approvals: number;
};

function fmtAge(ms: number): string {
  const sec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export default function ApprovalsPage() {
  const [approver, setApprover] = useState("owner");
  const [targets, setTargets] = useState<PendingTarget[]>([]);
  const [comments, setComments] = useState<PendingComment[]>([]);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [farmFilter, setFarmFilter] = useState("");
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [err, setErr] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<number>(0);

  const refresh = useCallback(async () => {
    try {
      const qs = farmFilter ? `?farm_id=${encodeURIComponent(farmFilter)}` : "";
      const [t, c, pc] = await Promise.all([
        fetch(`/api/targets/pending${qs}`).then((r) => r.json()),
        fetch("/api/targets/comments/pending").then((r) => r.json()),
        fetch("/api/targets/pending_counts").then((r) => r.json()),
      ]);
      const rawTargets: PendingTargetRaw[] = t?.rows ?? [];
      setTargets(rawTargets.map((r) => {
        const { tags_json, ...rest } = r;
        return { ...rest, tags: parseTags(tags_json) };
      }));
      setComments(c?.rows ?? []);
      setCounts(pc ?? null);
      setErr(null);
      setLastRefresh(Date.now());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [farmFilter]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10_000);
    return () => clearInterval(id);
  }, [refresh]);

  const act = async (
    kind: "target" | "comment",
    id: number,
    decision: "approve" | "reject",
  ) => {
    const key = `${kind}:${id}:${decision}`;
    if (!approver.trim()) {
      setErr("Approver name required");
      return;
    }
    let reason = "";
    if (decision === "reject") {
      reason = window.prompt("Reason for rejection?") ?? "";
      if (!reason.trim()) return;
    }
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      const base = kind === "target"
        ? `/api/targets/${id}`
        : `/api/targets/comments/${id}`;
      const body = decision === "approve"
        ? { approver }
        : { approver, reason };
      const r = await fetch(`${base}/${decision}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(`${r.status}: ${t.slice(0, 200)}`);
      }
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy((b) => {
        const { [key]: _drop, ...rest } = b;
        return rest;
      });
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Owner gate
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <ShieldCheck className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <span className="phantom-accent-text">Approvals</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-2xl">
          Research agents (ig_target_scout + sibling specialists) deliver candidates to
          Phantom Fleet as <code className="font-mono text-[11px]">needs_approval</code>.
          Nothing is picked or dispatched until you approve it here. Comments go through
          the same gate before any clone will post them.
        </p>
      </div>

      {/* Top stats + controls */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
            Pending targets
          </div>
          <div className="phantom-metric-lg mt-3 text-phantom-amber">
            {counts?.pending_target_approvals ?? "—"}
          </div>
          <div className="text-xs text-phantom-ghost mt-1">All farms</div>
        </div>
        <div className="phantom-panel p-5">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
            Pending comments
          </div>
          <div className="phantom-metric-lg mt-3 text-phantom-amber">
            {counts?.pending_comment_approvals ?? "—"}
          </div>
          <div className="text-xs text-phantom-ghost mt-1">All niches</div>
        </div>
        <div className="phantom-panel p-5 lg:col-span-2">
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost">
            Approver + farm filter
          </div>
          <div className="mt-3 flex items-center gap-2">
            <input
              value={approver}
              onChange={(e) => setApprover(e.target.value)}
              placeholder="owner handle"
              className="flex-1 bg-phantom-panelHi border border-phantom-border rounded-md px-3 py-1.5 text-sm font-mono text-white focus:outline-none focus:border-phantom-accent/60"
            />
            <input
              value={farmFilter}
              onChange={(e) => setFarmFilter(e.target.value)}
              placeholder="farm_id (optional)"
              className="w-48 bg-phantom-panelHi border border-phantom-border rounded-md px-3 py-1.5 text-sm font-mono text-phantom-ghost focus:outline-none focus:border-phantom-accent/60"
            />
            <button
              onClick={refresh}
              className="px-3 py-1.5 rounded-md bg-phantom-accent/10 border border-phantom-accent/30 text-phantom-accent text-xs font-medium hover:bg-phantom-accent/20 transition-colors flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" strokeWidth={2} />
              Refresh
            </button>
          </div>
          <div className="text-[10px] text-phantom-ghost mt-2 font-mono">
            {err
              ? <span className="text-phantom-red">err: {err}</span>
              : lastRefresh
                ? `refreshed ${fmtAge(lastRefresh)}`
                : "fetching…"}
          </div>
        </div>
      </div>

      {/* Targets panel */}
      <Panel
        label="research → fleet"
        title="Pending targets"
        subtitle="Delivered by Treg research agents through Staffroom. Approve to let the picker consider the row; reject to drop it. Approvals and rejections are stamped with your handle."
      >
        {targets.length === 0 ? (
          <div className="text-phantom-ghost text-sm py-12 text-center">
            <Target className="w-8 h-8 mx-auto mb-3 text-phantom-ghost/40" strokeWidth={1.5} />
            Nothing waiting. When a scout run lands candidates, they appear here.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-[0.12em] text-phantom-ghost border-b border-phantom-border">
                <tr>
                  <th className="text-left font-medium py-2 px-2">Handle</th>
                  <th className="text-left font-medium py-2 px-2">Kind</th>
                  <th className="text-left font-medium py-2 px-2">Farm</th>
                  <th className="text-left font-medium py-2 px-2">Tags</th>
                  <th className="text-left font-medium py-2 px-2">Source</th>
                  <th className="text-left font-medium py-2 px-2">Age</th>
                  <th className="text-right font-medium py-2 px-2">Decide</th>
                </tr>
              </thead>
              <tbody>
                {targets.map((t) => {
                  const bk = `target:${t.id}:approve`;
                  const rk = `target:${t.id}:reject`;
                  return (
                    <tr key={t.id} className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30">
                      <td className="py-2 px-2 font-mono text-white">
                        @{t.handle}
                        {t.media_code && (
                          <span className="text-phantom-ghost text-[10px] ml-2">
                            /p/{t.media_code}
                          </span>
                        )}
                      </td>
                      <td className="py-2 px-2">
                        <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-mono border bg-phantom-panelHi/60 border-phantom-border text-phantom-ghost">
                          {t.kind}
                        </span>
                      </td>
                      <td className="py-2 px-2 font-mono text-xs text-phantom-ghost">
                        {t.farm_id ?? "—"}
                      </td>
                      <td className="py-2 px-2">
                        <div className="flex flex-wrap gap-1">
                          {(t.tags ?? []).slice(0, 4).map((tag) => (
                            <span key={tag} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-phantom-accent/10 text-phantom-accent">
                              {tag}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-2 px-2 font-mono text-[11px] text-phantom-ghost">
                        {t.source}
                      </td>
                      <td className="py-2 px-2 text-[11px] text-phantom-ghost">
                        {fmtAge(t.imported_ms)}
                      </td>
                      <td className="py-2 px-2 text-right">
                        <div className="inline-flex gap-1">
                          <button
                            disabled={!!busy[bk]}
                            onClick={() => act("target", t.id, "approve")}
                            className={cn(
                              "px-2 py-1 rounded border text-[11px] font-medium inline-flex items-center gap-1",
                              "bg-phantom-alive/10 border-phantom-alive/30 text-phantom-alive",
                              "hover:bg-phantom-alive/20 disabled:opacity-40",
                            )}
                          >
                            <Check className="w-3 h-3" strokeWidth={2.5} />
                            Approve
                          </button>
                          <button
                            disabled={!!busy[rk]}
                            onClick={() => act("target", t.id, "reject")}
                            className={cn(
                              "px-2 py-1 rounded border text-[11px] font-medium inline-flex items-center gap-1",
                              "bg-phantom-red/10 border-phantom-red/30 text-phantom-red",
                              "hover:bg-phantom-red/20 disabled:opacity-40",
                            )}
                          >
                            <X className="w-3 h-3" strokeWidth={2.5} />
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* Comments panel */}
      <Panel
        label="comment pool"
        title="Pending comments"
        subtitle="Generator output lands here. Nothing is said on a clone until you approve the exact text — the picker reads the active pool only."
      >
        {comments.length === 0 ? (
          <div className="text-phantom-ghost text-sm py-12 text-center">
            <MessageSquare className="w-8 h-8 mx-auto mb-3 text-phantom-ghost/40" strokeWidth={1.5} />
            Nothing waiting.
          </div>
        ) : (
          <div className="space-y-2">
            {comments.map((c) => {
              const bk = `comment:${c.id}:approve`;
              const rk = `comment:${c.id}:reject`;
              return (
                <div
                  key={c.id}
                  className="flex items-start gap-3 p-3 rounded-lg bg-phantom-panelHi/30 border border-phantom-border/40"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white font-mono break-words">
                      {c.text}
                    </div>
                    <div className="flex items-center gap-3 mt-1.5 text-[10px] font-mono text-phantom-ghost">
                      <span className="px-1.5 py-0.5 rounded bg-phantom-accent/10 text-phantom-accent">
                        {c.niche}
                      </span>
                      <span>{c.source}</span>
                      <span>{fmtAge(c.imported_ms)}</span>
                    </div>
                  </div>
                  <div className="flex gap-1 flex-shrink-0">
                    <button
                      disabled={!!busy[bk]}
                      onClick={() => act("comment", c.id, "approve")}
                      className={cn(
                        "px-2 py-1 rounded border text-[11px] font-medium inline-flex items-center gap-1",
                        "bg-phantom-alive/10 border-phantom-alive/30 text-phantom-alive",
                        "hover:bg-phantom-alive/20 disabled:opacity-40",
                      )}
                    >
                      <Check className="w-3 h-3" strokeWidth={2.5} />
                      Approve
                    </button>
                    <button
                      disabled={!!busy[rk]}
                      onClick={() => act("comment", c.id, "reject")}
                      className={cn(
                        "px-2 py-1 rounded border text-[11px] font-medium inline-flex items-center gap-1",
                        "bg-phantom-red/10 border-phantom-red/30 text-phantom-red",
                        "hover:bg-phantom-red/20 disabled:opacity-40",
                      )}
                    >
                      <X className="w-3 h-3" strokeWidth={2.5} />
                      Reject
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
