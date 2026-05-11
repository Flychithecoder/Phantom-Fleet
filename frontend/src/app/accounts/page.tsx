"use client";

import { useState } from "react";
import { Panel } from "@/components/panel";
import { PlatformBadge, type Platform } from "@/components/platform-badge";
import { StatusBadge } from "@/components/status-badge";
import { Activity, Plus, Download, Heart, Smartphone, X } from "lucide-react";
import { cn } from "@/lib/utils";

type AccountStatus = "warming" | "active" | "flagged" | "dead" | "paused" | "re_wake";

type Account = {
  id: string;
  username: string;
  platform: Platform;
  phone: string;
  warmupDay: number;
  status: AccountStatus;
  sessionHealth: number; // 0–100
  followersK: number;
  actions24h: number;
};

const DEMO_ACCOUNTS: Account[] = [
  { id: "1", username: "tatiannalifee", platform: "instagram", phone: "RF8N81XYX4J", warmupDay: 72, status: "active", sessionHealth: 98, followersK: 2.84, actions24h: 42 },
  { id: "2", username: "tatianamusee", platform: "instagram", phone: "RF8N81XYX4J", warmupDay: 72, status: "active", sessionHealth: 95, followersK: 2.71, actions24h: 39 },
  { id: "3", username: "tatianazenn", platform: "instagram", phone: "RF8N81XYX4J", warmupDay: 72, status: "active", sessionHealth: 97, followersK: 2.89, actions24h: 41 },
  { id: "4", username: "melodieeeprincesss", platform: "instagram", phone: "RF8N90FZ0LV", warmupDay: 65, status: "active", sessionHealth: 99, followersK: 3.12, actions24h: 45 },
  { id: "5", username: "melodieeedream", platform: "instagram", phone: "RF8N90FZ0LV", warmupDay: 3, status: "re_wake", sessionHealth: 55, followersK: 2.45, actions24h: 8 },
  { id: "6", username: "cutie.melodieee", platform: "instagram", phone: "RF8N71RBF2H", warmupDay: 14, status: "warming", sessionHealth: 72, followersK: 1.84, actions24h: 22 },
  { id: "7", username: "hackerhoneytatii", platform: "threads", phone: "RF8N50EM1WK", warmupDay: 50, status: "active", sessionHealth: 93, followersK: 2.68, actions24h: 43 },
  { id: "8", username: "gentlemelodieee", platform: "threads", phone: "RF8N11BB1MN", warmupDay: 0, status: "dead", sessionHealth: 0, followersK: 0, actions24h: 0 },
  { id: "9", username: "softiemelodieee", platform: "instagram", phone: "RF8N71RBF2H", warmupDay: 28, status: "paused", sessionHealth: 82, followersK: 2.1, actions24h: 0 },
  { id: "10", username: "tatiannalifee_rdt", platform: "reddit", phone: "RF8N81XYX4J", warmupDay: 30, status: "active", sessionHealth: 90, followersK: 0.32, actions24h: 18 },
  { id: "11", username: "melodie_vibes", platform: "reddit", phone: "RF8N90FZ0LV", warmupDay: 20, status: "warming", sessionHealth: 68, followersK: 0.12, actions24h: 12 },
  { id: "12", username: "tatiannalifee_tt", platform: "tiktok", phone: "RF8N61Z9FZB", warmupDay: 45, status: "active", sessionHealth: 96, followersK: 5.4, actions24h: 30 },
  { id: "13", username: "tatiannalifee_x", platform: "x", phone: "RF8N61Z9FZB", warmupDay: 35, status: "active", sessionHealth: 88, followersK: 1.2, actions24h: 25 },
  { id: "14", username: "melodie_bsky", platform: "bluesky", phone: "RF8N70R01XT", warmupDay: 10, status: "warming", sessionHealth: 60, followersK: 0.05, actions24h: 8 },
  { id: "15", username: "tatiannalifee_disc", platform: "discord", phone: "RF8N3075H7Y", warmupDay: 22, status: "flagged", sessionHealth: 30, followersK: 0, actions24h: 3 },
];

type PlatformFilter = "all" | Platform;
type StatusFilter = "all" | AccountStatus;

function SessionHealthBar({ value }: { value: number }) {
  const color =
    value >= 85
      ? "bg-phantom-alive"
      : value >= 60
      ? "bg-phantom-accent"
      : value >= 35
      ? "bg-phantom-amber"
      : "bg-phantom-red";

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-phantom-panelHi overflow-hidden" style={{ minWidth: 60 }}>
        <div
          className={cn("h-full rounded-full transition-all", color)}
          style={{ width: `${value}%` }}
        />
      </div>
      <span
        className={cn(
          "text-[10px] font-mono tabular-nums w-7 text-right",
          value >= 85
            ? "text-phantom-alive"
            : value >= 60
            ? "text-phantom-accent"
            : value >= 35
            ? "text-phantom-amber"
            : "text-phantom-red"
        )}
      >
        {value}
      </span>
    </div>
  );
}

function ProvisionModal({ onClose }: { onClose: () => void }) {
  const [credentials, setCredentials] = useState("");
  const [platform, setPlatform] = useState<Platform>("instagram");
  const [phone, setPhone] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const PLATFORMS: Platform[] = ["instagram", "threads", "reddit", "x", "tiktok", "telegram", "discord", "dating", "bluesky"];

  const handleSubmit = async () => {
    if (!credentials.trim()) return;
    setSubmitting(true);
    try {
      await fetch("http://localhost:8001/api/accounts/provision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform,
          phone,
          credentials: credentials.trim().split("\n").filter(Boolean),
        }),
      });
    } catch {
      // backend offline
    } finally {
      setTimeout(() => {
        setSubmitting(false);
        onClose();
      }, 1500);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="phantom-panel-accent w-full max-w-lg mx-4 p-6 rounded-2xl space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Account provisioning
            </div>
            <div className="text-lg font-display font-semibold mt-1">Provision accounts</div>
          </div>
          <button onClick={onClose} className="text-phantom-ghost hover:text-white transition-colors">
            <X className="w-5 h-5" strokeWidth={1.75} />
          </button>
        </div>

        {/* Platform selector */}
        <div>
          <label className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium block mb-2">
            Platform
          </label>
          <div className="flex flex-wrap gap-1.5">
            {PLATFORMS.map((p) => (
              <button
                key={p}
                onClick={() => setPlatform(p)}
                className={cn(
                  "transition-all",
                  platform === p && "ring-2 ring-phantom-accent/50 rounded-md"
                )}
              >
                <PlatformBadge platform={p} size="sm" />
              </button>
            ))}
          </div>
        </div>

        {/* Phone assignment */}
        <div>
          <label className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium block mb-2">
            Assign to phone serial (optional)
          </label>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="RF8N81XYX4J"
            className="w-full bg-phantom-bg border border-phantom-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50"
          />
        </div>

        {/* Credentials textarea */}
        <div>
          <label className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium block mb-2">
            Credentials (one per line · username:password or cookie JSON)
          </label>
          <textarea
            value={credentials}
            onChange={(e) => setCredentials(e.target.value)}
            rows={6}
            placeholder={"username1:password1\nusername2:password2\n..."}
            className="w-full bg-phantom-bg border border-phantom-border rounded-lg px-3 py-2 text-xs font-mono text-white placeholder:text-phantom-ghost/40 resize-none focus:outline-none focus:border-phantom-accent/50"
          />
          <div className="text-[10px] text-phantom-ghost mt-1">
            {credentials.trim().split("\n").filter(Boolean).length} credentials pasted
          </div>
        </div>

        <div className="flex items-center gap-3 justify-end pt-1">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-phantom-ghost hover:text-white border border-phantom-border hover:border-phantom-border/60 transition-all"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !credentials.trim()}
            className={cn(
              "flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold bg-phantom-accent text-phantom-bg transition-all",
              "hover:shadow-[0_0_20px_hsl(162_100%_54%/0.4)] hover:brightness-110",
              (submitting || !credentials.trim()) && "opacity-50 cursor-not-allowed"
            )}
          >
            {submitting ? (
              <span className="phantom-dot bg-phantom-bg animate-phantom-pulse" />
            ) : (
              <Plus className="w-4 h-4" strokeWidth={2} />
            )}
            {submitting ? "Provisioning..." : "Provision"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AccountsPage() {
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showProvision, setShowProvision] = useState(false);

  const PLATFORM_FILTERS: { label: string; value: PlatformFilter }[] = [
    { label: "All", value: "all" },
    { label: "Instagram", value: "instagram" },
    { label: "Threads", value: "threads" },
    { label: "Reddit", value: "reddit" },
    { label: "X", value: "x" },
    { label: "TikTok", value: "tiktok" },
  ];

  const STATUS_FILTERS: { label: string; value: StatusFilter }[] = [
    { label: "All", value: "all" },
    { label: "Warming", value: "warming" },
    { label: "Active", value: "active" },
    { label: "Flagged", value: "flagged" },
    { label: "Dead", value: "dead" },
  ];

  const filtered = DEMO_ACCOUNTS.filter((a) => {
    const matchPlatform = platformFilter === "all" || a.platform === platformFilter;
    const matchStatus = statusFilter === "all" || a.status === statusFilter;
    return matchPlatform && matchStatus;
  });

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((a) => a.id)));
    }
  };

  return (
    <div className="space-y-8">
      {showProvision && <ProvisionModal onClose={() => setShowProvision(false)} />}

      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Account ledger
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <Activity className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            <span className="phantom-accent-text">Accounts</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            Every account, every phone, every platform. Filter, select, and bulk-manage.
          </p>
        </div>
        <button
          onClick={() => setShowProvision(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-phantom-accent text-phantom-bg hover:brightness-110 hover:shadow-[0_0_20px_hsl(162_100%_54%/0.35)] transition-all"
        >
          <Plus className="w-4 h-4" strokeWidth={2} />
          Provision accounts
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        {/* Platform filter */}
        <div className="flex items-center gap-1 p-1 bg-phantom-panel border border-phantom-border rounded-lg">
          {PLATFORM_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setPlatformFilter(f.value)}
              className={cn(
                "px-3 py-1 rounded-md text-[11px] font-medium transition-all duration-150",
                platformFilter === f.value
                  ? "bg-phantom-accent/15 text-phantom-accent"
                  : "text-phantom-ghost hover:text-white"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Status filter */}
        <div className="flex items-center gap-1 p-1 bg-phantom-panel border border-phantom-border rounded-lg">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatusFilter(f.value)}
              className={cn(
                "px-3 py-1 rounded-md text-[11px] font-medium transition-all duration-150",
                statusFilter === f.value
                  ? "bg-phantom-accent/15 text-phantom-accent"
                  : "text-phantom-ghost hover:text-white"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Showing count */}
        <span className="text-xs text-phantom-ghost ml-1">
          {filtered.length} accounts
        </span>
      </div>

      {/* Bulk actions bar — visible when items selected */}
      {selected.size > 0 && (
        <div className="phantom-panel-accent p-3 flex items-center gap-4 flex-wrap">
          <span className="text-sm font-medium text-phantom-accent">
            {selected.size} selected
          </span>
          <div className="flex items-center gap-2">
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-phantom-border bg-phantom-panelHi hover:bg-phantom-border transition-colors text-white">
              <Smartphone className="w-3.5 h-3.5" strokeWidth={1.75} />
              Assign to phone
            </button>
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-phantom-border bg-phantom-panelHi hover:bg-phantom-border transition-colors text-white">
              <Heart className="w-3.5 h-3.5" strokeWidth={1.75} />
              Check health
            </button>
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-phantom-border bg-phantom-panelHi hover:bg-phantom-border transition-colors text-white">
              <Download className="w-3.5 h-3.5" strokeWidth={1.75} />
              Export
            </button>
          </div>
          <button
            onClick={() => setSelected(new Set())}
            className="ml-auto text-phantom-ghost hover:text-white transition-colors"
          >
            <X className="w-4 h-4" strokeWidth={1.75} />
          </button>
        </div>
      )}

      {/* Table */}
      <Panel label="account table" title={`${filtered.length} accounts`}>
        <div className="overflow-x-auto -mx-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-phantom-border">
                <th className="px-3 py-2.5 text-left w-8">
                  <input
                    type="checkbox"
                    checked={selected.size === filtered.length && filtered.length > 0}
                    onChange={selectAll}
                    className="accent-phantom-accent w-3.5 h-3.5 cursor-pointer"
                  />
                </th>
                {["Account", "Platform", "Phone", "Warmup Day", "Status", "Session Health", "Actions 24h"].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2.5 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((account) => (
                <tr
                  key={account.id}
                  className={cn(
                    "border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors cursor-pointer",
                    selected.has(account.id) && "bg-phantom-accent/5"
                  )}
                  onClick={() => toggleSelect(account.id)}
                >
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(account.id)}
                      onChange={() => toggleSelect(account.id)}
                      className="accent-phantom-accent w-3.5 h-3.5 cursor-pointer"
                    />
                  </td>
                  <td className="px-3 py-3">
                    <div className="font-mono text-sm text-white">@{account.username}</div>
                    <div className="text-[10px] text-phantom-ghost">
                      {account.followersK > 0 ? `${account.followersK.toFixed(2)}K followers` : "dead"}
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <PlatformBadge platform={account.platform} size="sm" />
                  </td>
                  <td className="px-3 py-3">
                    <span className="font-mono text-[11px] text-phantom-ghost">{account.phone}</span>
                  </td>
                  <td className="px-3 py-3">
                    <div className="font-mono text-sm tabular-nums">
                      {account.warmupDay > 0 ? `Day ${account.warmupDay}` : "—"}
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={account.status} />
                  </td>
                  <td className="px-3 py-3 min-w-[100px]">
                    <SessionHealthBar value={account.sessionHealth} />
                  </td>
                  <td className="px-3 py-3 text-right">
                    <span
                      className={cn(
                        "font-mono tabular-nums text-sm",
                        account.actions24h > 30 ? "text-phantom-accent" : "text-white"
                      )}
                    >
                      {account.actions24h}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
