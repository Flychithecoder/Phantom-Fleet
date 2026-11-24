"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Globe, Plus, Trash2, CheckCircle2, AlertCircle, Loader2, Shield, Server,
} from "lucide-react";
import { cn } from "@/lib/utils";

type ProxyRow = {
  index: number;
  host: string;
  port: number;
  username: string;
  has_password: boolean;
};

type PoolList = {
  pool_size: number;
  mutable: boolean;
  accounts_per_ip: number;
  groups_per_phone: number;
  proxies: ProxyRow[];
};

type VerifyRow = {
  index: number;
  host: string;
  port: number;
  ok: boolean;
  external_ip: string | null;
  error: string | null;
};

type VerifyResult = {
  pool_size: number;
  ok_count: number;
  results: VerifyRow[];
};

export default function ProxyPoolPage() {
  const [pool, setPool] = useState<PoolList | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string[] | null>(null);
  const [addInput, setAddInput] = useState("");
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [verifying, setVerifying] = useState(false);

  const load = useCallback(() => {
    fetch("/api/proxy/pool")
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d: PoolList) => setPool(d))
      .catch(() => setPool(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const add = async () => {
    setAdding(true);
    setAddError(null);
    const lines = addInput.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
    try {
      const r = await fetch("/api/proxy/pool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lines }),
      });
      const d = await r.json();
      if (!r.ok) setAddError([typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail)]);
      else if (d.errors?.length) setAddError(d.errors);
      if (r.ok) setAddInput("");
      load();
    } catch (e) {
      setAddError([String(e)]);
    } finally {
      setAdding(false);
    }
  };

  const remove = async (idx: number) => {
    await fetch(`/api/proxy/pool/${idx}`, { method: "DELETE" });
    load();
  };

  const runVerify = async () => {
    setVerifying(true);
    try {
      const r = await fetch("/api/proxy/pool/verify", { method: "POST" });
      setVerify(await r.json());
    } finally {
      setVerifying(false);
    }
  };

  const vlookup = (idx: number): VerifyRow | undefined =>
    verify?.results.find((r) => r.index === idx);

  return (
    <div className="space-y-6">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Infrastructure · Proxies
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Globe className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          Proxy <span className="phantom-accent-text">pool</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-2xl">
          Provider-agnostic. Paste any proxy from any vendor — IPRoyal, Smartproxy,
          TrumpProxies, BrightData, Oxylabs, custom. Lines of
          <code className="mx-1 text-phantom-accent">host:port:user:pass</code>
          or <code className="mx-1 text-phantom-accent">scheme://user:pass@host:port</code>.
        </p>
      </div>

      {/* Summary tiles */}
      {pool && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile label="Pool size" value={pool.pool_size.toString()} />
          <Tile label="Accounts / IP" value={pool.accounts_per_ip.toString()} />
          <Tile label="Groups / phone" value={pool.groups_per_phone.toString()} />
          <Tile
            label="Pool state"
            value={pool.mutable ? "editable" : "read-only"}
            tone={pool.mutable ? "accent" : "amber"}
          />
        </div>
      )}

      {/* Add card */}
      {pool?.mutable && (
        <div className="phantom-panel p-5">
          <div className="flex items-center gap-2 mb-3">
            <Plus className="w-4 h-4 text-phantom-accent" />
            <h2 className="text-sm font-semibold">Add proxies</h2>
          </div>
          <textarea
            value={addInput}
            onChange={(e) => setAddInput(e.target.value)}
            placeholder={"host:port:user:pass\nhost:port:user:pass\nhttp://user:pass@host:port"}
            className="w-full h-28 px-3 py-2 rounded-md bg-phantom-panelHi border border-phantom-border text-xs font-mono focus:outline-none focus:border-phantom-accent/50"
          />
          <div className="flex items-center justify-between mt-3">
            <span className="text-[10px] text-phantom-ghost">
              One proxy per line. Comments with <code>#</code> allowed. No vendor-specific parsing.
            </span>
            <button
              onClick={add}
              disabled={adding || !addInput.trim()}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold border",
                adding || !addInput.trim()
                  ? "bg-phantom-panelHi text-phantom-ghost border-phantom-border cursor-not-allowed"
                  : "bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25",
              )}
            >
              {adding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              {adding ? "Adding…" : "Add to pool"}
            </button>
          </div>
          {addError && addError.length > 0 && (
            <div className="mt-3 text-[11px] font-mono text-red-400 space-y-1">
              {addError.map((e, i) => <div key={i}>• {e}</div>)}
            </div>
          )}
        </div>
      )}

      {!pool?.mutable && pool && (
        <div className="phantom-panel p-4 flex items-start gap-3 border border-phantom-amber/30 bg-phantom-amber/5">
          <Shield className="w-5 h-5 text-phantom-amber shrink-0" />
          <div>
            <div className="text-sm font-semibold text-phantom-amber">Read-only pool</div>
            <div className="text-xs text-phantom-ghost mt-1">
              Active pool is vendor-specific (loaded from legacy env vars). To edit at runtime,
              set <code>PHANTOM_PROXY_POOL</code> in the backend <code>.env</code>
              and restart — the pool then becomes editable from this page.
            </div>
          </div>
        </div>
      )}

      {/* Verify */}
      {pool && pool.pool_size > 0 && (
        <div className="flex items-center justify-between phantom-panel p-4">
          <div className="text-sm text-phantom-ghost">
            {verify
              ? <>Last verify: <span className="text-white font-semibold">{verify.ok_count}</span> / {verify.pool_size} reachable</>
              : "No verify run yet."}
          </div>
          <button
            onClick={runVerify}
            disabled={verifying}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold border bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panel"
          >
            {verifying ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
            {verifying ? "Verifying…" : "Verify pool"}
          </button>
        </div>
      )}

      {/* Pool list */}
      {loading && !pool && (
        <div className="phantom-panel p-5 flex items-center gap-3 text-phantom-ghost text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading pool…
        </div>
      )}
      {pool && (
        <div className="phantom-panel overflow-hidden">
          <div className="px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
              Proxies ({pool.pool_size})
            </span>
          </div>
          {pool.pool_size === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-phantom-ghost">
              Pool is empty. Add proxies above to unblock Phase 1 launch.
            </div>
          ) : (
            <div className="divide-y divide-phantom-border/30">
              {pool.proxies.map((p) => {
                const v = vlookup(p.index);
                return (
                  <div key={p.index} className="px-5 py-3 flex items-center gap-3">
                    <Server className="w-4 h-4 text-phantom-ghost shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-mono text-white">{p.host}:{p.port}</span>
                        {p.username && (
                          <span className="text-[10px] font-mono text-phantom-ghost">
                            user={p.username}{p.has_password ? " +pass" : ""}
                          </span>
                        )}
                        {v && (
                          <span className={cn(
                            "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded flex items-center gap-1",
                            v.ok
                              ? "text-green-400 bg-green-500/10"
                              : "text-red-400 bg-red-500/10",
                          )}>
                            {v.ok ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                            {v.ok ? (v.external_ip ?? "OK") : "FAIL"}
                          </span>
                        )}
                      </div>
                      {v?.error && (
                        <div className="text-[10px] text-red-400/70 mt-1 font-mono truncate">
                          {v.error}
                        </div>
                      )}
                    </div>
                    {pool.mutable && (
                      <button
                        onClick={() => remove(p.index)}
                        className="p-2 rounded-md text-phantom-ghost hover:text-red-400 hover:bg-red-500/10"
                        title="Remove proxy"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Tile({
  label, value, tone = "accent",
}: { label: string; value: string; tone?: "accent" | "amber" }) {
  return (
    <div className="phantom-panel p-4">
      <div className={cn(
        "text-2xl font-display font-bold tabular-nums",
        tone === "amber" ? "text-phantom-amber" : "text-phantom-accent",
      )}>{value}</div>
      <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em] mt-0.5">
        {label}
      </div>
    </div>
  );
}
