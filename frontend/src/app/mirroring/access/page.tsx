"use client";
/**
 * Mirroring → Device Access: which phones Phantom Fleet's screens (Fleet Mirror "ui" key) and its AI agents
 * ("agents" key) may control, and the device tools agents can use. The lists are set in Fleet Mirror
 * (More → Settings → Local API keys) — this page only shows them.
 */
import { useEffect, useState } from "react";
import { Bot, KeyRound, MonitorSmartphone } from "lucide-react";
import { Panel } from "@/components/panel";
import { cn } from "@/lib/utils";

type Role = { configured: boolean; phones?: number; may_control?: string[]; error?: string };
type Access = { ui?: Role; agents?: Role };

const TOOLS = [
  "device.list", "device.screenshot", "device.ui_dump", "device.screen_size", "device.tap", "device.swipe",
  "device.long_press", "device.key", "device.text", "device.clipboard_set", "device.clipboard_get", "device.shell",
  "device.apps", "device.app_install", "device.app_start", "device.app_stop", "device.file_push", "device.file_pull",
  "device.task_run", "device.task_status", "device.task_stop",
];

function RoleCard({ title, icon: Icon, role, note }: { title: string; icon: typeof Bot; role?: Role; note: string }) {
  const all = role?.may_control?.length && role.phones && role.may_control.length >= role.phones;
  return (
    <Panel
      label="Access"
      title={<span className="flex items-center gap-2"><Icon className="w-5 h-5 text-phantom-accent" strokeWidth={1.5} />{title}</span>}
      subtitle={note}
    >
      {!role ? (
        <div className="phantom-skeleton h-16" />
      ) : !role.configured ? (
        <div className="text-sm text-phantom-amber">Not configured (no key file set in backend/.env).</div>
      ) : role.error ? (
        <div className="text-sm text-phantom-red break-words">{role.error}</div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-baseline gap-2">
            <span className="phantom-metric text-4xl">{role.may_control?.length ?? 0}</span>
            <span className="text-sm text-phantom-ghost">of {role.phones} phones it may control{all ? " (all)" : ""}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(role.may_control ?? []).map((s) => (
              <span key={s} className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-mono tracking-wider border bg-phantom-accent/10 text-phantom-accent border-phantom-accent/30">
                {s}
              </span>
            ))}
            {!role.may_control?.length && <span className="text-xs text-phantom-ghost">none: every phone is view-only</span>}
          </div>
          <div className="text-[11px] text-phantom-ghost">Every other phone is view-only (live screen, screenshots, lists).</div>
        </div>
      )}
    </Panel>
  );
}

export default function DeviceAccessPage() {
  const [a, setA] = useState<Access>({});
  useEffect(() => {
    fetch("/api/fleet-mirror/access", { cache: "no-store" }).then((r) => (r.ok ? r.json() : {})).then(setA).catch(() => setA({}));
  }, []);
  return (
    <div className="space-y-6">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Mirroring</div>
        <h1 className="font-display text-3xl font-bold mt-1 tracking-tight flex items-center gap-3">
          <KeyRound className="w-8 h-8 text-phantom-accent" strokeWidth={1.5} />
          Device Access
        </h1>
        <div className="text-xs text-phantom-ghost mt-1 max-w-2xl">
          Which phones Phantom Fleet may control through Fleet Mirror. People (Phone Wall, Live screen) and AI agents have
          separate keys and separate lists. Change them in Fleet Mirror → More → Settings → Local API keys.
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <RoleCard title="People (Phone Wall, Live screen)" icon={MonitorSmartphone} role={a.ui}
          note="Fleet Mirror key “ui”: taps, keys, text, batch tools and tasks from Phantom Fleet's screens." />
        <RoleCard title="AI agents & automation" icon={Bot} role={a.agents}
          note="Fleet Mirror key “agents”: every device tool and every adb command Phantom Fleet's agents run." />
      </div>
      <Panel label="Agents" title="Device tools" subtitle="Registered by agents/device_tools.py. Add the ones an agent needs to its allowed_tools.">
        <div className="flex flex-wrap gap-1.5">
          {TOOLS.map((t) => (
            <span key={t} className={cn("inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-mono tracking-wider border",
              "bg-phantom-panelHi text-phantom-ghost border-phantom-border")}>{t}</span>
          ))}
        </div>
      </Panel>
    </div>
  );
}
