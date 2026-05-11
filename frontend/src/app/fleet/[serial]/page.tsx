// @refresh reset
"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { use } from "react";
import {
  Smartphone, ChevronLeft, WifiOff, Plus, Settings,
  BarChart2, Trash2, Play, Square, ShieldCheck, Wifi, RefreshCw, Copy, X,
  Eye, EyeOff, Key, CheckSquare, Download, Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

type AccountState = "RUNNING" | "PAUSED" | "BLOCKED" | "OFFLINE" | "WARMUP";

type AccountRow = {
  id: string;
  username: string;
  platform: string;
  clonePackage: string;
  startHour: number;
  endHour: number;
  state: AccountState;
  followers: number;
  following: number;
  toggling?: boolean;
  today: { follows: number; unfollows: number; likes: number; stories: number; comments: number; dms: number; };
  followEnabled: boolean;
  likeEnabled: boolean;
  storyEnabled: boolean;
};

// ─── Demo data ────────────────────────────────────────────────────────────────

const DEMO_ACCOUNTS: AccountRow[] = [
  { id: "acc_01", username: "tatiannalifee",    platform: "instagram", clonePackage: "com.instagram.android",   startHour: 8,  endHour: 22, state: "RUNNING", followers: 12480, following: 8234,  followEnabled: true,  likeEnabled: true,  storyEnabled: true,  today: { follows: 127, unfollows: 84,  likes: 540, stories: 310, comments: 12, dms: 8  } },
  { id: "acc_02", username: "tatiannalifee2",   platform: "instagram", clonePackage: "com.instagram.android_2", startHour: 9,  endHour: 21, state: "RUNNING", followers: 9820,  following: 6500,  followEnabled: true,  likeEnabled: true,  storyEnabled: true,  today: { follows: 98,  unfollows: 65,  likes: 430, stories: 201, comments: 0,  dms: 15 } },
  { id: "acc_03", username: "tatiannalifee3",   platform: "instagram", clonePackage: "com.instagram.android_3", startHour: 10, endHour: 20, state: "WARMUP",  followers: 340,   following: 980,   followEnabled: true,  likeEnabled: true,  storyEnabled: true,  today: { follows: 18,  unfollows: 0,   likes: 80,  stories: 44,  comments: 0,  dms: 0  } },
  { id: "acc_04", username: "melodieofficial",  platform: "instagram", clonePackage: "com.instagram.android_4", startHour: 7,  endHour: 23, state: "BLOCKED", followers: 18200, following: 14000, followEnabled: false, likeEnabled: false, storyEnabled: false, today: { follows: 0,   unfollows: 0,   likes: 0,   stories: 0,   comments: 0,  dms: 0  } },
  { id: "acc_05", username: "melodieofficial2", platform: "instagram", clonePackage: "com.instagram.android_5", startHour: 8,  endHour: 22, state: "RUNNING", followers: 31500, following: 22800, followEnabled: true,  likeEnabled: true,  storyEnabled: true,  today: { follows: 210, unfollows: 140, likes: 820, stories: 490, comments: 24, dms: 11 } },
  { id: "acc_06", username: "melodieofficial3", platform: "instagram", clonePackage: "com.instagram.android_6", startHour: 9,  endHour: 21, state: "PAUSED",  followers: 7640,  following: 5210,  followEnabled: true,  likeEnabled: true,  storyEnabled: true,  today: { follows: 44,  unfollows: 20,  likes: 200, stories: 110, comments: 5,  dms: 2  } },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

const STATE_BADGE: Record<AccountState, string> = {
  RUNNING: "text-green-400 border-green-400/25 bg-green-400/10",
  PAUSED:  "text-yellow-400 border-yellow-400/25 bg-yellow-400/10",
  BLOCKED: "text-red-400 border-red-400/25 bg-red-400/10",
  OFFLINE: "text-phantom-ghost border-phantom-border bg-phantom-panelHi",
  WARMUP:  "text-phantom-accent border-phantom-accent/25 bg-phantom-accent/10",
};

const STATE_LABEL: Record<AccountState, string> = {
  RUNNING: "Running",
  PAUSED:  "Paused",
  BLOCKED: "Blocked",
  OFFLINE: "Offline",
  WARMUP:  "Warm-up",
};

function pad(n: number) { return String(n).padStart(2, "0"); }

function fmt(n: number) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function StatDot({ val, enabled }: { val: number; enabled: boolean }) {
  const color = !enabled ? "bg-phantom-ghost/20" : val > 0 ? "bg-green-400" : "bg-green-400/25";
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn("w-2 h-2 rounded-full shrink-0", color)} />
      <span className={cn("font-mono text-xs tabular-nums", enabled ? "text-white" : "text-phantom-ghost/30")}>{val}</span>
    </div>
  );
}

// ─── Add Account modal ────────────────────────────────────────────────────────

type AddAccountForm = {
  username: string; password: string; twoFaKey: string;
  clonePackage: string; startHour: number; endHour: number;
};

function AddAccountModal({
  serial,
  onClose,
  onAdded,
}: {
  serial: string;
  onClose: () => void;
  onAdded: (acc: AccountRow) => void;
}) {
  const [form, setForm] = useState<AddAccountForm>({
    username: "", password: "", twoFaKey: "",
    clonePackage: "com.instagram.android", startHour: 8, endHour: 22,
  });
  const [showPw, setShowPw] = useState(false);
  const [show2fa, setShow2fa] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (patch: Partial<AddAccountForm>) => setForm((p) => ({ ...p, ...patch }));

  const handleSubmit = async () => {
    if (!form.username.trim() || !form.password.trim()) {
      setError("Username and password are required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`http://localhost:8001/api/accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone_serial:  serial,
          username:      form.username.trim(),
          password:      form.password,
          totp_secret:   form.twoFaKey || null,
          clone_package: form.clonePackage.trim() || "com.instagram.android",
          start_hour:    form.startHour,
          end_hour:      form.endHour,
          platform:      "instagram",
          status:        "paused",
        }),
      });
      const data = await res.json();
      const newAcc: AccountRow = {
        id: String(data.id ?? `acc_new_${Date.now()}`),
        username: form.username.trim(),
        platform: "instagram",
        clonePackage: form.clonePackage.trim(),
        startHour: form.startHour,
        endHour: form.endHour,
        state: "PAUSED",
        followers: 0,
        following: 0,
        followEnabled: true,
        likeEnabled: true,
        storyEnabled: true,
        today: { follows: 0, unfollows: 0, likes: 0, stories: 0, comments: 0, dms: 0 },
      };
      onAdded(newAcc);
      onClose();
    } catch {
      // backend offline — add locally
      const newAcc: AccountRow = {
        id: `acc_new_${Date.now()}`,
        username: form.username.trim(),
        platform: "instagram",
        clonePackage: form.clonePackage.trim() || "com.instagram.android",
        startHour: form.startHour,
        endHour: form.endHour,
        state: "PAUSED",
        followers: 0,
        following: 0,
        followEnabled: true,
        likeEnabled: true,
        storyEnabled: true,
        today: { follows: 0, unfollows: 0, likes: 0, stories: 0, comments: 0, dms: 0 },
      };
      onAdded(newAcc);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  // Close on backdrop click
  const handleBackdrop = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  const inputCls = "w-full px-3 py-2 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 transition-colors font-mono";
  const labelCls = "block text-[10px] uppercase tracking-wider text-phantom-ghost mb-1.5";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={handleBackdrop}
    >
      <div className="w-full max-w-lg bg-phantom-panel border border-phantom-border rounded-2xl overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-phantom-border">
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Device · {serial.slice(0, 12)}</div>
            <div className="text-white font-semibold mt-0.5">Add account</div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-phantom-ghost hover:text-white hover:bg-phantom-panelHi transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {/* Username */}
          <div>
            <label className={labelCls}>Instagram username</label>
            <input value={form.username} onChange={(e) => set({ username: e.target.value })}
              placeholder="tatiannalifee" className={inputCls} autoFocus />
          </div>

          {/* Password */}
          <div>
            <label className={labelCls}>Password</label>
            <div className="relative">
              <input value={form.password} onChange={(e) => set({ password: e.target.value })}
                type={showPw ? "text" : "password"} placeholder="••••••••••" className={cn(inputCls, "pr-10")} />
              <button onClick={() => setShowPw((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-phantom-ghost/40 hover:text-phantom-ghost transition-colors">
                {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* 2FA */}
          <div>
            <label className={cn(labelCls, "flex items-center gap-1.5")}>
              <Key className="w-3 h-3" /> 2FA secret key (TOTP) — optional
            </label>
            <div className="relative">
              <input value={form.twoFaKey} onChange={(e) => set({ twoFaKey: e.target.value })}
                type={show2fa ? "text" : "password"}
                placeholder="JBSWY3DPEHPK3PXP (base32 — leave blank if no 2FA)"
                className={cn(inputCls, "pr-10")} />
              <button onClick={() => setShow2fa((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-phantom-ghost/40 hover:text-phantom-ghost transition-colors">
                {show2fa ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Clone package */}
          <div>
            <label className={labelCls}>Clone package (APP ID)</label>
            <input value={form.clonePackage} onChange={(e) => set({ clonePackage: e.target.value })}
              placeholder="com.instagram.android" className={inputCls} />
            <p className="mt-1 text-[11px] text-phantom-ghost/40">Leave as default if using the original app. Change if using a clone app.</p>
          </div>

          {/* Schedule */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Start hour</label>
              <select value={form.startHour} onChange={(e) => set({ startHour: Number(e.target.value) })}
                className="w-full px-3 py-2 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white font-mono focus:outline-none focus:border-phantom-accent/50 transition-colors">
                {Array.from({ length: 24 }, (_, i) => i).map((h) => (
                  <option key={h} value={h}>{pad(h)}:00</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>End hour</label>
              <select value={form.endHour} onChange={(e) => set({ endHour: Number(e.target.value) })}
                className="w-full px-3 py-2 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white font-mono focus:outline-none focus:border-phantom-accent/50 transition-colors">
                {Array.from({ length: 24 }, (_, i) => i).map((h) => (
                  <option key={h} value={h}>{pad(h)}:00</option>
                ))}
              </select>
            </div>
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 px-3 py-2 rounded-lg">{error}</div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-phantom-border bg-phantom-panelHi/30">
          <button onClick={onClose} className="px-5 py-2 rounded-lg text-sm text-phantom-ghost border border-phantom-border bg-phantom-panelHi hover:text-white hover:bg-phantom-panelHi/80 transition-colors">
            Cancel
          </button>
          <button onClick={handleSubmit} disabled={saving}
            className="px-6 py-2 rounded-lg text-sm font-semibold bg-phantom-accent text-phantom-bg hover:bg-phantom-accent/90 disabled:opacity-60 transition-colors">
            {saving ? "Adding…" : "Add Account"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DeviceManagePage({
  params,
}: {
  params: Promise<{ serial: string }>;
}) {
  const { serial } = use(params);
  const [accounts, setAccounts]     = useState<AccountRow[]>(DEMO_ACCOUNTS);
  const [backendDown, setBackendDown] = useState(false);
  const [verifying, setVerifying]   = useState(false);
  const [syncing, setSyncing]       = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [importError, setImportError] = useState("");
  const deviceName = "Phone 1 - F2 - Tatiana";

  const toState = (s: string): AccountState => {
    if (s === "active") return "RUNNING";
    if (s === "paused") return "PAUSED";
    if (s === "banned") return "BLOCKED";
    if (s === "warmup") return "WARMUP";
    return "OFFLINE";
  };

  const fetchAccounts = (showLoader = false) => {
    if (showLoader) setSyncing(true);
    fetch(`http://localhost:8001/api/fleet/${serial}/accounts`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => {
        if (d?.accounts?.length) {
          setAccounts(d.accounts.map((a: Record<string, unknown>) => {
            const tc = (a.today_counts as Record<string, number>) ?? {};
            return {
              id: String(a.id), username: String(a.username),
              platform: String(a.platform ?? "instagram"),
              clonePackage: String(a.clone_package ?? ""),
              startHour: Number(a.start_hour ?? 8), endHour: Number(a.end_hour ?? 22),
              state: toState(String(a.status ?? "")),
              followers: Number(a.follower_count ?? 0),
              following: Number(a.following_count ?? 0),
              followEnabled: Boolean(a.follow_enabled),
              likeEnabled: Boolean(a.like_enabled),
              storyEnabled: Boolean(a.story_enabled),
              today: {
                follows: tc.follow ?? 0, unfollows: tc.unfollow ?? 0,
                likes: tc.like ?? 0, stories: tc.story ?? 0,
                comments: tc.comment ?? 0, dms: tc.dm ?? 0,
              },
            };
          }));
        }
        setBackendDown(false);
      })
      .catch(() => setBackendDown(true))
      .finally(() => { if (showLoader) setSyncing(false); });
  };

  useEffect(() => { fetchAccounts(); }, [serial]);

  const safeAccounts = accounts.map((a) => ({
    ...a,
    today: a && typeof a === "object" && a.today && typeof a.today === "object"
      ? a.today
      : { follows: 0, unfollows: 0, likes: 0, stories: 0, comments: 0, dms: 0 },
  }));

  const counts = {
    total:   safeAccounts.length,
    running: safeAccounts.filter((a) => a.state === "RUNNING").length,
    blocked: safeAccounts.filter((a) => a.state === "BLOCKED").length,
    follows: safeAccounts.reduce((s, a) => s + (Number(a.today.follows) || 0), 0),
  };

  // ── Toggle with backend PATCH ──────────────────────────────────────────────
  const toggleState = async (id: string) => {
    const acc = safeAccounts.find((a) => a.id === id);
    if (!acc || acc.toggling) return;
    const newState = acc.state === "RUNNING" ? "PAUSED" : "RUNNING";
    const apiStatus = newState === "RUNNING" ? "active" : "paused";
    // Optimistic update
    setAccounts((p) => p.map((a) => a.id === id ? { ...a, state: newState, toggling: true } : a));
    await fetch(`http://localhost:8001/api/accounts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: apiStatus }),
    }).catch(() => {});
    setAccounts((p) => p.map((a) => a.id === id ? { ...a, toggling: false } : a));
  };

  // ── Start/Pause all with backend ───────────────────────────────────────────
  const setAllState = async (newState: "RUNNING" | "PAUSED") => {
    const apiStatus = newState === "RUNNING" ? "active" : "paused";
    setAccounts((p) => p.map((a) => ({ ...a, state: newState, toggling: true })));
    await Promise.allSettled(
      safeAccounts.map((a) =>
        fetch(`http://localhost:8001/api/accounts/${a.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: apiStatus }),
        })
      )
    );
    setAccounts((p) => p.map((a) => ({ ...a, toggling: false })));
  };

  const handleDelete = (id: string) => {
    if (!confirm("Remove this account from the device?")) return;
    setAccounts((p) => p.filter((a) => a.id !== id));
    fetch(`http://localhost:8001/api/accounts/${id}`, { method: "DELETE" }).catch(() => {});
  };

  // ── Bulk selection ──────────────────────────────────────────────────────────
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };
  const allSelected = safeAccounts.length > 0 && selectedIds.size === safeAccounts.length;
  const toggleSelectAll = () => setSelectedIds(allSelected ? new Set() : new Set(safeAccounts.map((a) => a.id)));

  const bulkSetState = async (newState: "RUNNING" | "PAUSED") => {
    const ids = Array.from(selectedIds);
    const apiStatus = newState === "RUNNING" ? "active" : "paused";
    setAccounts((p) => p.map((a) => selectedIds.has(a.id) ? { ...a, state: newState } : a));
    await Promise.allSettled(ids.map((id) =>
      fetch(`http://localhost:8001/api/accounts/${id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: apiStatus }),
      })
    ));
    setSelectedIds(new Set());
  };

  const bulkDelete = () => {
    if (!confirm(`Remove ${selectedIds.size} selected accounts?`)) return;
    const ids = Array.from(selectedIds);
    setAccounts((p) => p.filter((a) => !selectedIds.has(a.id)));
    ids.forEach((id) => fetch(`http://localhost:8001/api/accounts/${id}`, { method: "DELETE" }).catch(() => {}));
    setSelectedIds(new Set());
  };

  // ── Export CSV ───────────────────────────────────────────────────────────────
  const exportCSV = () => {
    const header = "username,platform,clone_package,start_hour,end_hour,state,followers,following";
    const rows = safeAccounts.map((a) =>
      [a.username, a.platform, a.clonePackage, a.startHour, a.endHour, a.state, a.followers, a.following].join(",")
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `accounts_${serial}_${new Date().toISOString().slice(0,10)}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  // ── Import CSV ───────────────────────────────────────────────────────────────
  const importCSV = (e: React.ChangeEvent<HTMLInputElement>) => {
    setImportError("");
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const lines = (ev.target?.result as string).split("\n").filter(Boolean);
        const data = lines.slice(1).map((line) => {
          const [username, , clonePackage, startHour, endHour] = line.split(",");
          if (!username?.trim()) throw new Error("Invalid CSV");
          const newAcc: AccountRow = {
            id: `acc_import_${Date.now()}_${Math.random().toString(36).slice(2)}`,
            username: username.trim(), platform: "instagram",
            clonePackage: clonePackage?.trim() || "com.instagram.android",
            startHour: Number(startHour) || 8, endHour: Number(endHour) || 22,
            state: "PAUSED", followers: 0, following: 0,
            followEnabled: true, likeEnabled: true, storyEnabled: true,
            today: { follows: 0, unfollows: 0, likes: 0, stories: 0, comments: 0, dms: 0 },
          };
          return newAcc;
        });
        setAccounts((p) => [...p, ...data]);
      } catch {
        setImportError("Invalid CSV format. Expected: username,platform,clone_package,start_hour,end_hour");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const handleClone = (id: string) => {
    const source = safeAccounts.find((a) => a.id === id);
    if (!source) return;
    const cloned: AccountRow = {
      ...source,
      id: `acc_clone_${Date.now()}`,
      username: `${source.username}_clone`,
      state: "PAUSED",
      followers: 0,
      following: 0,
      today: { follows: 0, unfollows: 0, likes: 0, stories: 0, comments: 0, dms: 0 },
    };
    setAccounts((p) => [...p, cloned]);
    fetch(`http://localhost:8001/api/accounts/${id}/clone`, { method: "POST" }).catch(() => {});
  };

  return (
    <>
      {/* Add Account modal */}
      {showAddModal && (
        <AddAccountModal
          serial={serial}
          onClose={() => setShowAddModal(false)}
          onAdded={(acc) => setAccounts((p) => [...p, acc])}
        />
      )}

      <div className="space-y-6">
        {/* Breadcrumb */}
        <Link href="/fleet" className="inline-flex items-center gap-1.5 text-xs text-phantom-ghost hover:text-white transition-colors">
          <ChevronLeft className="w-3.5 h-3.5" />
          Back to Fleet
        </Link>

        {/* Header */}
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Device · Manage accounts</div>
            <h1 className="font-display text-3xl font-bold mt-1 tracking-tight flex items-center gap-3">
              <Smartphone className="w-8 h-8 text-phantom-accent" strokeWidth={1.5} />
              {deviceName}
              <span className="text-sm font-mono bg-phantom-panelHi border border-phantom-border px-2 py-0.5 rounded-md text-phantom-ghost">
                {accounts.length}
              </span>
            </h1>
            <div className="flex items-center gap-2.5 mt-1.5 text-xs text-phantom-ghost">
              <span className="font-mono">{serial}</span>
              <span>·</span>
              <span>Samsung Galaxy S10 Lite</span>
              <span>·</span>
              <span className="flex items-center gap-1 text-green-400">
                <Wifi className="w-3 h-3" /> Connected
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {backendDown && (
              <span className="flex items-center gap-1.5 text-xs text-phantom-amber bg-phantom-amber/10 border border-phantom-amber/20 px-3 py-1.5 rounded-lg">
                <WifiOff className="w-3.5 h-3.5" /> Connecting…
              </span>
            )}
            <button onClick={() => setAllState("RUNNING")}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-green-500/15 text-green-400 border-green-500/25 hover:bg-green-500/25 transition-colors">
              <Play className="w-4 h-4 fill-current" strokeWidth={0} />
              Start All
            </button>
            <button onClick={() => setAllState("PAUSED")}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-yellow-500/10 text-yellow-400 border-yellow-500/25 hover:bg-yellow-500/20 transition-colors">
              <Square className="w-4 h-4 fill-current" strokeWidth={0} />
              Pause All
            </button>
            <button
              onClick={() => { setVerifying(true); fetch(`http://localhost:8001/api/fleet/${serial}/verify-proxy`, { method: "POST" }).catch(() => {}); setTimeout(() => setVerifying(false), 2000); }}
              disabled={verifying}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-60 transition-colors">
              <ShieldCheck className="w-4 h-4" strokeWidth={1.75} />
              {verifying ? "Checking…" : "Verify proxy"}
            </button>
            <button onClick={() => fetchAccounts(true)} disabled={syncing}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panelHi/80 disabled:opacity-60 transition-colors">
              <RefreshCw className={cn("w-4 h-4", syncing && "animate-spin")} strokeWidth={1.75} />
              {syncing ? "Syncing…" : "Sync Accounts"}
            </button>
            <button onClick={() => setShowAddModal(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panelHi/80 transition-colors">
              <Plus className="w-4 h-4" strokeWidth={1.75} />
              Add Account
            </button>
            <button onClick={exportCSV}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-panelHi text-phantom-ghost border-phantom-border hover:text-white hover:bg-phantom-panelHi/80 transition-colors">
              <Download className="w-4 h-4" strokeWidth={1.75} />
              Export CSV
            </button>
            <label className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-panelHi text-phantom-ghost border-phantom-border hover:text-white hover:bg-phantom-panelHi/80 transition-colors cursor-pointer">
              <Upload className="w-4 h-4" strokeWidth={1.75} />
              Import CSV
              <input type="file" accept=".csv" onChange={importCSV} className="hidden" />
            </label>
          </div>
        </div>

        {/* Import error */}
        {importError && (
          <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 px-3 py-2 rounded-lg flex items-center justify-between">
            {importError}
            <button onClick={() => setImportError("")} className="text-red-400/60 hover:text-red-400"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}

        {/* Bulk action bar */}
        {selectedIds.size > 0 && (
          <div className="flex items-center gap-3 px-4 py-2.5 rounded-lg bg-phantom-accent/10 border border-phantom-accent/30">
            <CheckSquare className="w-4 h-4 text-phantom-accent" />
            <span className="text-sm text-phantom-accent font-medium">{selectedIds.size} selected</span>
            <div className="flex items-center gap-2 ml-2">
              <button onClick={() => bulkSetState("RUNNING")}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/25 hover:bg-green-500/25 transition-colors">
                <Play className="w-3 h-3 fill-current" strokeWidth={0} /> Start All
              </button>
              <button onClick={() => bulkSetState("PAUSED")}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-yellow-500/10 text-yellow-400 border border-yellow-500/25 hover:bg-yellow-500/20 transition-colors">
                <Square className="w-3 h-3 fill-current" strokeWidth={0} /> Pause All
              </button>
              <button onClick={bulkDelete}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/10 text-red-400 border border-red-500/25 hover:bg-red-500/20 transition-colors">
                <Trash2 className="w-3 h-3" strokeWidth={1.75} /> Delete
              </button>
            </div>
            <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-phantom-ghost hover:text-white transition-colors">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Summary strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Accounts",      value: counts.total,   color: "text-white"         },
            { label: "Running",       value: counts.running, color: "text-green-400"      },
            { label: "Blocked",       value: counts.blocked, color: "text-red-400"        },
            { label: "Follows today", value: counts.follows, color: "text-phantom-accent" },
          ].map((s) => (
            <div key={s.label} className="phantom-panel px-5 py-4">
              <div className={cn("text-2xl font-display font-bold tabular-nums", s.color)}>{s.value}</div>
              <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em] mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Account table */}
        <div className="phantom-panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-phantom-border bg-phantom-panelHi/50">
                  <th className="px-4 py-3 w-8">
                    <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                      className="w-3.5 h-3.5 accent-[hsl(162_100%_54%)] cursor-pointer" />
                  </th>
                  {["Account", "Schedule", "Followers", "Following", "Follows", "Unfollows", "Likes", "Stories", "Comments", "DMs", "State", "Actions"].map((h) => (
                    <th key={h} className="px-4 py-3 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {safeAccounts.map((acc) => (
                  <tr key={acc.id} className={cn("border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors", selectedIds.has(acc.id) && "bg-phantom-accent/5")}>
                    {/* Checkbox */}
                    <td className="px-4 py-3 w-8">
                      <input type="checkbox" checked={selectedIds.has(acc.id)} onChange={() => toggleSelect(acc.id)}
                        className="w-3.5 h-3.5 accent-[hsl(162_100%_54%)] cursor-pointer" />
                    </td>

                    {/* Account */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className={cn("w-2 h-2 rounded-full shrink-0",
                          acc.state === "RUNNING" ? "bg-green-400" :
                          acc.state === "PAUSED"  ? "bg-yellow-400" :
                          acc.state === "BLOCKED" ? "bg-red-500" :
                          acc.state === "WARMUP"  ? "bg-phantom-accent" : "bg-phantom-ghost/30")} />
                        <div>
                          <Link href={`/fleet/${serial}/${acc.id}/settings`}
                            className="font-medium text-white hover:text-phantom-accent transition-colors">
                            @{acc.username}
                          </Link>
                          <div className="text-[11px] text-phantom-ghost/50 font-mono mt-0.5 truncate max-w-[140px]">
                            {acc.clonePackage || "—"}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Schedule */}
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-white whitespace-nowrap">{pad(acc.startHour)}:00–{pad(acc.endHour)}:00</span>
                    </td>

                    {/* Followers / Following */}
                    <td className="px-4 py-3"><span className="font-mono text-xs text-white tabular-nums">{fmt(acc.followers)}</span></td>
                    <td className="px-4 py-3"><span className="font-mono text-xs text-white tabular-nums">{fmt(acc.following)}</span></td>

                    {/* Stat dots */}
                    <td className="px-4 py-2"><StatDot val={Number(acc.today.follows)   || 0} enabled={acc.followEnabled && acc.state !== "BLOCKED"} /></td>
                    <td className="px-4 py-2"><StatDot val={Number(acc.today.unfollows) || 0} enabled={acc.followEnabled && acc.state !== "BLOCKED"} /></td>
                    <td className="px-4 py-2"><StatDot val={Number(acc.today.likes)     || 0} enabled={acc.likeEnabled   && acc.state !== "BLOCKED"} /></td>
                    <td className="px-4 py-2"><StatDot val={Number(acc.today.stories)   || 0} enabled={acc.storyEnabled  && acc.state !== "BLOCKED"} /></td>
                    <td className="px-4 py-2"><StatDot val={Number(acc.today.comments)  || 0} enabled={acc.state !== "BLOCKED"} /></td>
                    <td className="px-4 py-2"><StatDot val={Number(acc.today.dms)       || 0} enabled={acc.state !== "BLOCKED"} /></td>

                    {/* State */}
                    <td className="px-4 py-3">
                      <span className={cn("text-[10px] font-mono tracking-wider px-2 py-0.5 rounded border whitespace-nowrap", STATE_BADGE[acc.state])}>
                        {STATE_LABEL[acc.state]}
                      </span>
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => toggleState(acc.id)}
                          disabled={acc.toggling}
                          title={acc.state === "RUNNING" ? "Pause" : "Start"}
                          className={cn("flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50",
                            acc.state === "RUNNING"
                              ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/25 hover:bg-yellow-500/20"
                              : "bg-green-500/15 text-green-400 border-green-500/25 hover:bg-green-500/25")}>
                          {acc.toggling
                            ? <RefreshCw className="w-2.5 h-2.5 animate-spin" />
                            : acc.state === "RUNNING"
                              ? <><Square className="w-2.5 h-2.5 fill-current" strokeWidth={0} /> Pause</>
                              : <><Play   className="w-2.5 h-2.5 fill-current" strokeWidth={0} /> Start</>}
                        </button>
                        <Link href={`/fleet/${serial}/${acc.id}/settings`}
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-phantom-panelHi text-white border border-phantom-border hover:bg-phantom-panelHi/80 transition-colors">
                          <Settings className="w-3 h-3" strokeWidth={1.75} />
                          Manage
                        </Link>
                        <button onClick={() => handleClone(acc.id)} title="Clone settings"
                          className="p-1.5 rounded-lg text-phantom-ghost hover:text-phantom-accent hover:bg-phantom-accent/10 border border-transparent hover:border-phantom-accent/20 transition-colors">
                          <Copy className="w-3.5 h-3.5" strokeWidth={1.75} />
                        </button>
                        <Link href={`/fleet/${serial}/${acc.id}/stats`} title="View stats"
                          className="p-1.5 rounded-lg text-phantom-ghost hover:text-phantom-accent hover:bg-phantom-accent/10 border border-transparent hover:border-phantom-accent/20 transition-colors">
                          <BarChart2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                        </Link>
                        <button onClick={() => handleDelete(acc.id)} title="Remove account"
                          className="p-1.5 rounded-lg text-phantom-ghost hover:text-red-400 hover:bg-red-400/10 border border-transparent hover:border-red-400/20 transition-colors">
                          <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </>
  );
}
