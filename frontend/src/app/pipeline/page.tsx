"use client";

/**
 * Gmail → Reddit Pipeline dashboard.
 *
 * Shows the current state of the Gmail account pool and Reddit registration
 * pipeline, and provides controls to trigger creation and registration.
 *
 * Architecture:
 *   GmailCreationAgent (ADB phone farm)
 *     ↓  POST /api/pipeline/gmail/create
 *   GmailAccountPool (encrypted JSON)
 *     ↓  POST /api/pipeline/reddit/register
 *   RedditRegistrationAgent
 *     ↓  GET  /api/pipeline/reddit/accounts
 *   Reddit Panel aging pipeline
 */

import { useEffect, useState, useCallback } from "react";
import { Panel } from "@/components/panel";
import {
  Mail,
  RefreshCw,
  Download,
  Plus,
  UserPlus,
  CheckCircle,
  Clock,
  AlertCircle,
  Loader2,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PipelineStats {
  total_gmails: number;
  unregistered: number;
  registered: number;
  verified_reddit: number;
}

interface AccountEntry {
  email: string;
  reddit_username: string | null;
  status: "unregistered" | "registered" | "verified" | "aged";
  created_at: string;
  proxy_used: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE = "http://localhost:8001";

const PHONE_SERIALS = [
  "emulator-5554",
  "R5CT1012ABC",
  "R5CT1012DEF",
  "192.168.1.101:5555",
  "192.168.1.102:5555",
];

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; icon: React.ElementType }
> = {
  unregistered: {
    label: "Unregistered",
    color: "text-phantom-ghost",
    icon: Clock,
  },
  registered: {
    label: "Registered",
    color: "text-blue-400",
    icon: CheckCircle,
  },
  verified: {
    label: "Verified",
    color: "text-phantom-accent",
    icon: CheckCircle,
  },
  aged: {
    label: "Aged",
    color: "text-emerald-400",
    icon: CheckCircle,
  },
};

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border px-5 py-4 flex flex-col gap-1 ${
        accent
          ? "border-phantom-accent/30 bg-phantom-accent/5"
          : "border-phantom-border bg-phantom-panel/60"
      }`}
    >
      <div
        className={`text-2xl font-display font-bold ${
          accent ? "text-phantom-accent" : "text-white"
        }`}
      >
        {value}
      </div>
      <div className="text-[11px] uppercase tracking-[0.12em] text-phantom-ghost font-medium">
        {label}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.unregistered;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${cfg.color}`}>
      <Icon className="w-3.5 h-3.5" />
      {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PipelinePage() {
  const [stats, setStats] = useState<PipelineStats>({
    total_gmails: 0,
    unregistered: 0,
    registered: 0,
    verified_reddit: 0,
  });
  const [accounts, setAccounts] = useState<AccountEntry[]>([]);
  const [loadingStats, setLoadingStats] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(false);

  // Gmail creation form state
  const [selectedPhone, setSelectedPhone] = useState(PHONE_SERIALS[0]);
  const [gmailCount, setGmailCount] = useState(1);
  const [creatingGmail, setCreatingGmail] = useState(false);
  const [gmailMsg, setGmailMsg] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // Reddit registration form state
  const [redditCount, setRedditCount] = useState(5);
  const [proxyUrl, setProxyUrl] = useState("");
  const [registeringReddit, setRegisteringReddit] = useState(false);
  const [redditMsg, setRedditMsg] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // ---------------------------------------------------------------------------
  // Fetch helpers
  // ---------------------------------------------------------------------------

  const fetchStats = useCallback(async () => {
    setLoadingStats(true);
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/gmail/stats`);
      if (res.ok) setStats(await res.json());
    } catch {
      // silently ignore — backend may not be running
    } finally {
      setLoadingStats(false);
    }
  }, []);

  const fetchAccounts = useCallback(async () => {
    setLoadingAccounts(true);
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/reddit/accounts`);
      if (res.ok) {
        const data = await res.json();
        setAccounts(data.accounts ?? []);
      }
    } catch {
      // silently ignore
    } finally {
      setLoadingAccounts(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await Promise.all([fetchStats(), fetchAccounts()]);
  }, [fetchStats, fetchAccounts]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30_000);
    return () => clearInterval(interval);
  }, [refresh]);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  async function handleCreateGmail() {
    setCreatingGmail(true);
    setGmailMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/gmail/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone_serial: selectedPhone,
          count: gmailCount,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setGmailMsg({
          type: "success",
          text: data.message ?? `Queued ${gmailCount} creation(s) on ${selectedPhone}`,
        });
        setTimeout(refresh, 3000);
      } else {
        setGmailMsg({ type: "error", text: data.detail ?? "Creation request failed" });
      }
    } catch (err) {
      setGmailMsg({ type: "error", text: `Network error: ${String(err)}` });
    } finally {
      setCreatingGmail(false);
    }
  }

  async function handleRegisterReddit() {
    if (!proxyUrl.trim()) {
      setRedditMsg({ type: "error", text: "Proxy URL is required" });
      return;
    }
    setRegisteringReddit(true);
    setRedditMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/reddit/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: redditCount, proxy_url: proxyUrl }),
      });
      const data = await res.json();
      if (res.ok) {
        setRedditMsg({
          type: "success",
          text: data.message ?? `Queued ${redditCount} registration(s)`,
        });
        setTimeout(refresh, 3000);
      } else {
        setRedditMsg({ type: "error", text: data.detail ?? "Registration request failed" });
      }
    } catch (err) {
      setRedditMsg({ type: "error", text: `Network error: ${String(err)}` });
    } finally {
      setRegisteringReddit(false);
    }
  }

  async function handleExportCSV() {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/reddit/export`, {
        method: "POST",
      });
      if (!res.ok) {
        alert("Export failed");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "_");
      a.download = `reddit_accounts_${ts}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Export request failed");
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-1">
            Infrastructure
          </div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-3">
            <Mail className="w-6 h-6 text-phantom-accent" />
            Gmail → Reddit Pipeline
          </h1>
          <p className="text-sm text-phantom-ghost mt-1 max-w-xl">
            Create Gmail accounts via ADB phone farm, register Reddit accounts,
            and export credentials for the aging pipeline.
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={loadingStats}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-phantom-border text-phantom-ghost hover:text-white hover:border-phantom-accent/50 transition-all text-sm"
        >
          <RefreshCw
            className={`w-4 h-4 ${loadingStats ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Gmails" value={stats.total_gmails} />
        <StatCard label="Unregistered" value={stats.unregistered} />
        <StatCard label="Reddit Created" value={stats.registered} />
        <StatCard
          label="Verified Reddit"
          value={stats.verified_reddit}
          accent
        />
      </div>

      {/* Action panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Create Gmail */}
        <Panel
          label="Step 1"
          title="Create Gmail Accounts"
          subtitle="Launches Android account setup on the selected phone via ADB. Max 2 accounts per phone per day."
        >
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-phantom-ghost mb-1.5 font-medium">
                Phone Serial
              </label>
              <select
                value={selectedPhone}
                onChange={(e) => setSelectedPhone(e.target.value)}
                className="w-full bg-phantom-bg border border-phantom-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-phantom-accent/60 transition-colors"
              >
                {PHONE_SERIALS.map((serial) => (
                  <option key={serial} value={serial}>
                    {serial}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs text-phantom-ghost mb-1.5 font-medium">
                Count (1–5)
              </label>
              <input
                type="number"
                min={1}
                max={5}
                value={gmailCount}
                onChange={(e) =>
                  setGmailCount(
                    Math.max(1, Math.min(5, parseInt(e.target.value) || 1))
                  )
                }
                className="w-full bg-phantom-bg border border-phantom-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-phantom-accent/60 transition-colors"
              />
            </div>

            {gmailMsg && (
              <div
                className={`flex items-start gap-2 text-xs rounded-lg px-3 py-2 ${
                  gmailMsg.type === "success"
                    ? "bg-phantom-accent/10 border border-phantom-accent/20 text-phantom-accent"
                    : "bg-red-900/20 border border-red-500/30 text-red-400"
                }`}
              >
                {gmailMsg.type === "success" ? (
                  <CheckCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                )}
                {gmailMsg.text}
              </div>
            )}

            <button
              onClick={handleCreateGmail}
              disabled={creatingGmail}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-phantom-accent text-phantom-bg font-semibold text-sm hover:bg-phantom-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            >
              {creatingGmail ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Plus className="w-4 h-4" />
              )}
              {creatingGmail ? "Queuing…" : "Create Gmail Accounts"}
            </button>
          </div>
        </Panel>

        {/* Register Reddit */}
        <Panel
          label="Step 2"
          title="Register Reddit Accounts"
          subtitle="Takes unregistered Gmails from the pool and registers Reddit accounts. Requires a proxy URL."
        >
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-phantom-ghost mb-1.5 font-medium">
                Count
              </label>
              <input
                type="number"
                min={1}
                max={20}
                value={redditCount}
                onChange={(e) =>
                  setRedditCount(
                    Math.max(1, Math.min(20, parseInt(e.target.value) || 1))
                  )
                }
                className="w-full bg-phantom-bg border border-phantom-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-phantom-accent/60 transition-colors"
              />
              <p className="text-[11px] text-phantom-ghost mt-1">
                {stats.unregistered} Gmail(s) available in pool
              </p>
            </div>

            <div>
              <label className="block text-xs text-phantom-ghost mb-1.5 font-medium">
                Proxy URL
              </label>
              <input
                type="text"
                placeholder="http://user:pass@host:port"
                value={proxyUrl}
                onChange={(e) => setProxyUrl(e.target.value)}
                className="w-full bg-phantom-bg border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/60 transition-colors font-mono"
              />
            </div>

            {redditMsg && (
              <div
                className={`flex items-start gap-2 text-xs rounded-lg px-3 py-2 ${
                  redditMsg.type === "success"
                    ? "bg-phantom-accent/10 border border-phantom-accent/20 text-phantom-accent"
                    : "bg-red-900/20 border border-red-500/30 text-red-400"
                }`}
              >
                {redditMsg.type === "success" ? (
                  <CheckCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                )}
                {redditMsg.text}
              </div>
            )}

            <button
              onClick={handleRegisterReddit}
              disabled={registeringReddit || stats.unregistered === 0}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-phantom-accent text-phantom-bg font-semibold text-sm hover:bg-phantom-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            >
              {registeringReddit ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <UserPlus className="w-4 h-4" />
              )}
              {registeringReddit ? "Queuing…" : "Register Reddit Accounts"}
            </button>
          </div>
        </Panel>
      </div>

      {/* Account table */}
      <Panel
        label="Inventory"
        title="Account Pipeline"
        subtitle="All Gmail accounts and their Reddit registration status."
        actions={
          <button
            onClick={handleExportCSV}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-phantom-border text-phantom-ghost hover:text-white hover:border-phantom-accent/50 transition-all text-xs"
          >
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        }
      >
        {loadingAccounts && accounts.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-phantom-ghost">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading accounts…
          </div>
        ) : accounts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-phantom-ghost gap-2">
            <Mail className="w-8 h-8 opacity-30" />
            <p className="text-sm">No accounts in pipeline yet.</p>
            <p className="text-xs opacity-60">
              Create Gmail accounts above to get started.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-phantom-border">
                  <th className="text-left py-2.5 px-3 text-[11px] uppercase tracking-[0.1em] text-phantom-ghost font-medium">
                    Email
                  </th>
                  <th className="text-left py-2.5 px-3 text-[11px] uppercase tracking-[0.1em] text-phantom-ghost font-medium">
                    Reddit Username
                  </th>
                  <th className="text-left py-2.5 px-3 text-[11px] uppercase tracking-[0.1em] text-phantom-ghost font-medium">
                    Status
                  </th>
                  <th className="text-left py-2.5 px-3 text-[11px] uppercase tracking-[0.1em] text-phantom-ghost font-medium">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((acct, i) => (
                  <tr
                    key={acct.email}
                    className={`border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors ${
                      i % 2 === 0 ? "" : "bg-phantom-panel/20"
                    }`}
                  >
                    <td className="py-2.5 px-3 font-mono text-xs text-white/80">
                      {acct.email}
                    </td>
                    <td className="py-2.5 px-3 font-mono text-xs">
                      {acct.reddit_username ? (
                        <span className="text-phantom-accent">
                          u/{acct.reddit_username}
                        </span>
                      ) : (
                        <span className="text-phantom-ghost/40">—</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3">
                      <StatusBadge status={acct.status} />
                    </td>
                    <td className="py-2.5 px-3 text-xs text-phantom-ghost">
                      {acct.created_at
                        ? new Date(acct.created_at).toLocaleDateString("en-US", {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
