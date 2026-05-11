"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Smartphone, Scan, ShieldCheck, Plus, Play, Settings, Trash2, WifiOff, LayoutGrid, List } from "lucide-react";
import { cn } from "@/lib/utils";

type PhoneState = "PROXY_READY" | "ONLINE" | "BUSY" | "OFFLINE";

type PhoneRow = {
  serial: string;
  name: string;
  state: PhoneState;
  accountCount: number;
  model: string;
  wifi_ip?: string;
};

const DEMO_PHONES: PhoneRow[] = [
  { serial: "RF8N61Z9FZB", name: "Phone 1 - F2 - Tatiana",  state: "PROXY_READY", accountCount: 16, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N50EM1WK", name: "Phone 2 - F2 - Tatiana",  state: "PROXY_READY", accountCount: 14, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N70R01XT", name: "Phone 3 - F2 - Tatiana",  state: "PROXY_READY", accountCount: 12, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N90FZ0LV", name: "Phone 4 - F2 - Melodie",  state: "BUSY",        accountCount: 39, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N71RBF2H", name: "Phone 5 - F2 - Melodie",  state: "PROXY_READY", accountCount: 16, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N30B5FAD", name: "Phone 6 - F2 - Melodie",  state: "PROXY_READY", accountCount: 12, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N10B574B", name: "Phone 7 - F2 - Melodie",  state: "BUSY",        accountCount: 18, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N20VWNHM", name: "Phone 8 - F2 - Melodie",  state: "ONLINE",      accountCount: 14, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N81XYX4J", name: "Phone 9 - F2 - Tatiana",  state: "PROXY_READY", accountCount: 23, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N81VR6DT", name: "Phone 10 - F2 - Melodie", state: "OFFLINE",     accountCount: 4,  model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N501E82B", name: "Phone 11 - F2 - Melodie", state: "ONLINE",      accountCount: 8,  model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N4057ELK", name: "Phone 12 - F2 - Melodie", state: "PROXY_READY", accountCount: 9,  model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N3075H7Y", name: "Phone 13 - F2 - Melodie", state: "PROXY_READY", accountCount: 10, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N21A0X5Y", name: "Phone 14 - F2 - Melodie", state: "PROXY_READY", accountCount: 10, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N10J57DA", name: "Phone 15 - F2 - Tatiana", state: "PROXY_READY", accountCount: 9,  model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N11BB1MN", name: "Phone 16 - F2 - Melodie", state: "OFFLINE",     accountCount: 10, model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N406NLWK", name: "Phone 17 - F2 - Tatiana", state: "PROXY_READY", accountCount: 9,  model: "Samsung Galaxy S10 Lite" },
  { serial: "RF8N10J56NB", name: "Phone 18 - F2 - Tatiana", state: "OFFLINE",     accountCount: 4,  model: "Samsung Galaxy S10 Lite" },
  { serial: "53c8e3ad1b3f7ece", name: "Phone 19 - F2 - Tatiana", state: "ONLINE", accountCount: 3,  model: "Samsung Galaxy S10 Lite" },
];

const STATE_DOT: Record<PhoneState, string> = {
  PROXY_READY: "bg-green-400",
  ONLINE:      "bg-yellow-400",
  BUSY:        "bg-blue-400",
  OFFLINE:     "bg-red-500",
};

const STATE_LABEL: Record<PhoneState, string> = {
  PROXY_READY: "Ready",
  ONLINE:      "Online",
  BUSY:        "Busy",
  OFFLINE:     "Offline",
};

export default function FleetPage() {
  const [phones, setPhones]       = useState<PhoneRow[]>(DEMO_PHONES);
  const [view, setView]           = useState<"table" | "grid">("table");
  const [scanning, setScanning]   = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    fetch("http://localhost:8001/api/fleet/phones")
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => { if (Array.isArray(d) && d.length > 0) setPhones(d); })
      .catch(() => setBackendDown(true));
  }, []);

  const handleScan = async () => {
    setScanning(true);
    try { await fetch("http://localhost:8001/api/fleet/scan", { method: "POST" }); } catch {}
    setTimeout(() => setScanning(false), 2000);
  };

  const handleVerifyAll = async () => {
    setVerifying(true);
    try { await fetch("http://localhost:8001/api/fleet/verify-all", { method: "POST" }); } catch {}
    setTimeout(() => setVerifying(false), 3000);
  };

  const handleDelete = async (serial: string) => {
    if (!confirm(`Remove ${serial} from the fleet?`)) return;
    setPhones((prev) => prev.filter((p) => p.serial !== serial));
    try { await fetch(`http://localhost:8001/api/fleet/phones/${serial}`, { method: "DELETE" }); } catch {}
  };

  const counts = {
    total:  phones.length,
    ready:  phones.filter((p) => p.state === "PROXY_READY").length,
    busy:   phones.filter((p) => p.state === "BUSY" || p.state === "ONLINE").length,
    offline: phones.filter((p) => p.state === "OFFLINE").length,
    accounts: phones.reduce((s, p) => s + p.accountCount, 0),
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Hardware layer</div>
          <h1 className="font-display text-3xl font-bold mt-1 tracking-tight flex items-center gap-3">
            <Smartphone className="w-8 h-8 text-phantom-accent" strokeWidth={1.5} />
            Devices <span className="ml-1 text-sm font-mono bg-phantom-panelHi border border-phantom-border px-2 py-0.5 rounded-md text-phantom-ghost">{phones.length}</span>
          </h1>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {backendDown && (
            <span className="flex items-center gap-1.5 text-xs text-phantom-amber bg-phantom-amber/10 border border-phantom-amber/20 px-3 py-1.5 rounded-lg">
              <WifiOff className="w-3.5 h-3.5" /> Connecting…
            </span>
          )}
          {/* View toggle */}
          <div className="flex items-center border border-phantom-border rounded-lg overflow-hidden">
            <button
              onClick={() => setView("table")}
              className={cn("px-3 py-2 text-sm transition-colors", view === "table" ? "bg-phantom-accent/15 text-phantom-accent" : "text-phantom-ghost hover:text-white bg-phantom-panelHi")}
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => setView("grid")}
              className={cn("px-3 py-2 text-sm transition-colors", view === "grid" ? "bg-phantom-accent/15 text-phantom-accent" : "text-phantom-ghost hover:text-white bg-phantom-panelHi")}
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
          </div>
          <button
            onClick={handleScan}
            disabled={scanning}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panelHi/80 disabled:opacity-60"
          >
            <Scan className="w-4 h-4" strokeWidth={1.75} />
            {scanning ? "Scanning…" : "Scan for devices"}
          </button>
          <button
            onClick={handleVerifyAll}
            disabled={verifying}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-60"
          >
            <ShieldCheck className="w-4 h-4" strokeWidth={1.75} />
            {verifying ? "Verifying…" : "Verify all proxies"}
          </button>
          <button className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panelHi/80">
            <Plus className="w-4 h-4" strokeWidth={1.75} />
            Add Device
          </button>
        </div>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total devices",   value: counts.total,    color: "text-white" },
          { label: "Proxy ready",     value: counts.ready,    color: "text-green-400" },
          { label: "Online / Busy",   value: counts.busy,     color: "text-yellow-400" },
          { label: "Total accounts",  value: counts.accounts, color: "text-phantom-accent" },
        ].map((s) => (
          <div key={s.label} className="phantom-panel px-5 py-4">
            <div className={cn("text-2xl font-display font-bold tabular-nums", s.color)}>{s.value}</div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em] mt-0.5">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Table view */}
      {view === "table" && (
        <div className="phantom-panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-phantom-border bg-phantom-panelHi/50">
                  {["Device ID", "Device Name", "Accounts", "State", "Action"].map((h) => (
                    <th key={h} className="px-4 py-3 text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium text-left whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {phones.map((phone) => (
                  <tr
                    key={phone.serial}
                    className="border-b border-phantom-border/40 hover:bg-phantom-panelHi/30 transition-colors"
                  >
                    {/* Device ID */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className={cn("w-2 h-2 rounded-full shrink-0", STATE_DOT[phone.state])} />
                        <span className="font-mono text-xs text-phantom-ghost">{phone.serial}</span>
                      </div>
                    </td>

                    {/* Device Name */}
                    <td className="px-4 py-3">
                      <span className="text-white font-medium">{phone.name}</span>
                      <div className="text-[11px] text-phantom-ghost/60 mt-0.5">{phone.model}</div>
                    </td>

                    {/* Account count */}
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center justify-center w-10 h-6 rounded-md bg-phantom-panelHi border border-phantom-border font-mono text-xs font-bold text-white">
                        {phone.accountCount}
                      </span>
                    </td>

                    {/* State */}
                    <td className="px-4 py-3">
                      <span className={cn(
                        "text-[10px] font-mono tracking-wider px-2 py-0.5 rounded border",
                        phone.state === "PROXY_READY" ? "text-green-400 border-green-400/25 bg-green-400/10" :
                        phone.state === "ONLINE"      ? "text-yellow-400 border-yellow-400/25 bg-yellow-400/10" :
                        phone.state === "BUSY"        ? "text-blue-400 border-blue-400/25 bg-blue-400/10" :
                        "text-red-400 border-red-400/25 bg-red-400/10"
                      )}>
                        {STATE_LABEL[phone.state]}
                      </span>
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          title="Start automation"
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/25 hover:bg-green-500/25 transition-colors"
                        >
                          <Play className="w-3 h-3 fill-current" />
                          Start
                        </button>
                        <button
                          title="Add account"
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-phantom-accent/10 text-phantom-accent border border-phantom-accent/25 hover:bg-phantom-accent/20 transition-colors"
                        >
                          <Plus className="w-3 h-3" strokeWidth={2} />
                          Add Account
                        </button>
                        <Link
                          href={`/fleet/${phone.serial}`}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-phantom-panelHi text-white border border-phantom-border hover:bg-phantom-panelHi/80 transition-colors"
                        >
                          <Settings className="w-3 h-3" strokeWidth={1.75} />
                          Manage
                        </Link>
                        <button
                          onClick={() => handleDelete(phone.serial)}
                          title="Remove device"
                          className="p-1.5 rounded-lg text-phantom-ghost hover:text-red-400 hover:bg-red-400/10 border border-transparent hover:border-red-400/20 transition-colors"
                        >
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
      )}

      {/* Grid view */}
      {view === "grid" && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {phones.map((phone) => (
            <Link
              key={phone.serial}
              href={`/fleet/${phone.serial}`}
              className="phantom-panel p-4 hover:border-phantom-accent/30 transition-colors cursor-pointer group"
            >
              <div className="flex items-center gap-2 mb-3">
                <span className={cn("w-2 h-2 rounded-full", STATE_DOT[phone.state])} />
                <span className="font-mono text-[10px] text-phantom-ghost truncate">{phone.serial.slice(0, 10)}</span>
              </div>
              <div className="text-xs text-white font-medium truncate">{phone.name}</div>
              <div className="text-[11px] text-phantom-ghost mt-1">{phone.accountCount} accounts</div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
