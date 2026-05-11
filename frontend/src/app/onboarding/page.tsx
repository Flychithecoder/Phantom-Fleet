"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  Usb,
  Smartphone,
  ShieldCheck,
  Users,
  Flame,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronRight,
  ArrowRight,
  Wifi,
  WifiOff,
  Clock,
  AlertTriangle,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type StepId = 1 | 2 | 3 | 4 | 5;

type DeviceEntry = {
  serial: string;
  state: string;
  apkInstalled: boolean;
  apkHealthy: boolean;
  installing: boolean;
  testing: boolean;
};

type PhoneState = "OFFLINE" | "ONLINE" | "PROXY_READY" | "BUSY" | "ERROR";

type ProxyPhoneResult = {
  serial: string;
  state: PhoneState;
  verified: boolean;
};

type AccountResult = {
  username: string;
  status: "provisioned" | "failed" | "needs_2fa";
  account_id: string | null;
  error: string | null;
};

const API = "http://localhost:8001";

// ---------------------------------------------------------------------------
// Step config
// ---------------------------------------------------------------------------

const STEPS = [
  { id: 1 as StepId, label: "Connect Phone",    icon: Usb },
  { id: 2 as StepId, label: "Install APK",       icon: Smartphone },
  { id: 3 as StepId, label: "Configure Proxy",   icon: ShieldCheck },
  { id: 4 as StepId, label: "Add Accounts",      icon: Users },
  { id: 5 as StepId, label: "Launch Warming",    icon: Flame },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StepIndicator({ current }: { current: StepId }) {
  return (
    <div className="flex items-center justify-center gap-0 mb-10">
      {STEPS.map((step, idx) => {
        const Icon = step.icon;
        const done = step.id < current;
        const active = step.id === current;
        return (
          <div key={step.id} className="flex items-center">
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={cn(
                  "w-9 h-9 rounded-full flex items-center justify-center border transition-all duration-300",
                  done
                    ? "bg-phantom-accent/20 border-phantom-accent text-phantom-accent"
                    : active
                    ? "bg-phantom-accent/10 border-phantom-accent text-phantom-accent shadow-[0_0_20px_hsl(162_100%_54%/0.3)]"
                    : "bg-phantom-panelHi/30 border-phantom-border text-phantom-ghost"
                )}
              >
                {done ? (
                  <CheckCircle2 className="w-4 h-4" strokeWidth={2} />
                ) : (
                  <Icon className="w-4 h-4" strokeWidth={1.75} />
                )}
              </div>
              <span
                className={cn(
                  "text-[10px] font-medium tracking-wide whitespace-nowrap",
                  active ? "text-phantom-accent" : done ? "text-white/60" : "text-phantom-ghost"
                )}
              >
                {step.label}
              </span>
            </div>
            {idx < STEPS.length - 1 && (
              <div
                className={cn(
                  "w-12 h-px mx-2 mb-5 transition-all duration-300",
                  done ? "bg-phantom-accent/40" : "bg-phantom-border"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  const map: Record<string, string> = {
    OFFLINE:     "bg-phantom-red/10 text-phantom-red border-phantom-red/20",
    ONLINE:      "bg-yellow-400/10 text-yellow-400 border-yellow-400/20",
    PROXY_READY: "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/20",
    BUSY:        "bg-blue-400/10 text-blue-400 border-blue-400/20",
    ERROR:       "bg-orange-400/10 text-orange-400 border-orange-400/20",
  };
  return (
    <span
      className={cn(
        "px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider border",
        map[state] ?? "bg-phantom-panelHi text-phantom-ghost border-phantom-border"
      )}
    >
      {state}
    </span>
  );
}

function PrimaryButton({
  label,
  onClick,
  loading,
  disabled,
  icon,
}: {
  label: string;
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading || disabled}
      className={cn(
        "flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all duration-200 border",
        "bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30",
        "hover:bg-phantom-accent/25 hover:shadow-[0_0_20px_hsl(162_100%_54%/0.25)]",
        (loading || disabled) && "opacity-50 cursor-not-allowed"
      )}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : icon}
      {label}
    </button>
  );
}

function GhostButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 border",
        "bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panelHi/80",
        disabled && "opacity-40 cursor-not-allowed"
      )}
    >
      {label}
      <ChevronRight className="w-4 h-4" />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — Connect Phone
// ---------------------------------------------------------------------------

function Step1({
  devices,
  scanning,
  onScan,
}: {
  devices: DeviceEntry[];
  scanning: boolean;
  onScan: () => void;
}) {
  return (
    <div className="space-y-6">
      <div className="text-center space-y-3">
        {/* Pulsing USB icon */}
        <div className="relative mx-auto w-20 h-20 flex items-center justify-center">
          <div className="absolute inset-0 rounded-full bg-phantom-accent/10 animate-ping" />
          <div className="absolute inset-2 rounded-full bg-phantom-accent/5" />
          <Usb className="relative w-10 h-10 text-phantom-accent" strokeWidth={1.5} />
        </div>
        <h2 className="text-xl font-display font-bold">Plug your Android phone into USB</h2>
        <p className="text-phantom-ghost text-sm max-w-sm mx-auto">
          Make sure USB debugging is enabled on the phone, then click Scan for Devices.
        </p>
      </div>

      <div className="flex justify-center">
        <PrimaryButton
          label={scanning ? "Scanning..." : "Scan for Devices"}
          onClick={onScan}
          loading={scanning}
          icon={<Smartphone className="w-4 h-4" strokeWidth={1.75} />}
        />
      </div>

      {devices.length > 0 ? (
        <div className="space-y-2">
          <div className="text-xs text-phantom-ghost uppercase tracking-wider font-medium">
            Detected devices
          </div>
          {devices.map((d) => (
            <div
              key={d.serial}
              className="phantom-panel p-3 flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <Smartphone className="w-5 h-5 text-phantom-accent" strokeWidth={1.5} />
                <span className="font-mono text-sm text-white">{d.serial}</span>
              </div>
              <StateBadge state={d.state} />
            </div>
          ))}
        </div>
      ) : (
        !scanning && (
          <div className="phantom-panel p-5 space-y-3">
            <div className="flex items-center gap-2 text-phantom-amber text-sm font-medium">
              <AlertTriangle className="w-4 h-4" />
              Troubleshooting tips
            </div>
            <ul className="text-phantom-ghost text-xs space-y-1.5 list-disc list-inside">
              <li>Go to Settings → Developer Options → USB Debugging → ON</li>
              <li>Accept the "Allow USB debugging?" dialog on the phone</li>
              <li>Install ADB drivers (Windows: Samsung/Google device drivers)</li>
              <li>Try a different USB cable (some cables are charge-only)</li>
              <li>Run <code className="text-phantom-accent bg-phantom-panelHi px-1 rounded">adb devices</code> in a terminal to confirm ADB sees the device</li>
            </ul>
          </div>
        )
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Install APK
// ---------------------------------------------------------------------------

function Step2({
  devices,
  onInstall,
  onTestConnection,
}: {
  devices: DeviceEntry[];
  onInstall: (serial: string) => void;
  onTestConnection: (serial: string) => void;
}) {
  return (
    <div className="space-y-5">
      <div className="text-center space-y-2">
        <h2 className="text-xl font-display font-bold">Install Companion APK</h2>
        <p className="text-phantom-ghost text-sm max-w-sm mx-auto">
          Install the Phantom Fleet companion app that bridges ADB commands to the phone.
        </p>
      </div>

      {devices.length === 0 ? (
        <div className="phantom-panel p-6 text-center text-phantom-ghost text-sm">
          No devices detected. Go back and scan for devices first.
        </div>
      ) : (
        <div className="space-y-3">
          {devices.map((d) => (
            <div key={d.serial} className="phantom-panel p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Smartphone className="w-5 h-5 text-phantom-accent" strokeWidth={1.5} />
                  <span className="font-mono text-sm">{d.serial}</span>
                </div>
                <div className="flex items-center gap-2">
                  {d.apkInstalled && (
                    <span className="text-[10px] text-phantom-accent border border-phantom-accent/20 bg-phantom-accent/10 px-2 py-0.5 rounded-md font-semibold uppercase">
                      Installed
                    </span>
                  )}
                  {d.apkHealthy && (
                    <span className="text-[10px] text-emerald-400 border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 rounded-md font-semibold uppercase flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> APK Live
                    </span>
                  )}
                </div>
              </div>

              {/* Progress bar during install */}
              {d.installing && (
                <div className="w-full h-1.5 bg-phantom-bg rounded-full overflow-hidden">
                  <div className="h-full bg-phantom-accent rounded-full animate-[progressPulse_1.5s_ease-in-out_infinite]" style={{ width: "60%" }} />
                </div>
              )}

              <div className="flex items-center gap-2">
                <button
                  onClick={() => onInstall(d.serial)}
                  disabled={d.installing || d.testing}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200",
                    "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/20",
                    "hover:bg-phantom-accent/20",
                    (d.installing || d.testing) && "opacity-50 cursor-not-allowed"
                  )}
                >
                  {d.installing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Smartphone className="w-3 h-3" />}
                  {d.installing ? "Installing..." : "Install APK"}
                </button>

                <button
                  onClick={() => onTestConnection(d.serial)}
                  disabled={d.testing || d.installing}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200",
                    "bg-phantom-panelHi text-white border-phantom-border",
                    "hover:bg-phantom-panelHi/80",
                    (d.testing || d.installing) && "opacity-50 cursor-not-allowed"
                  )}
                >
                  {d.testing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Wifi className="w-3 h-3" />}
                  {d.testing ? "Testing..." : "Test Connection"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Configure Proxy
// ---------------------------------------------------------------------------

function Step3({
  proxyUsername,
  proxyPassword,
  proxyHost,
  proxyPort,
  proxyMode,
  phoneResults,
  verifying,
  onChangeField,
  onVerify,
}: {
  proxyUsername: string;
  proxyPassword: string;
  proxyHost: string;
  proxyPort: string;
  proxyMode: "iproyal" | "custom";
  phoneResults: ProxyPhoneResult[];
  verifying: boolean;
  onChangeField: (k: string, v: string) => void;
  onVerify: () => void;
}) {
  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <h2 className="text-xl font-display font-bold">Configure Proxy</h2>
        <p className="text-phantom-ghost text-sm max-w-sm mx-auto">
          Every phone must route through a dedicated proxy before actions are allowed.
        </p>
      </div>

      {/* Mode toggle */}
      <div className="flex items-center gap-1 p-1 bg-phantom-bg rounded-lg border border-phantom-border w-fit mx-auto">
        {(["iproyal", "custom"] as const).map((m) => (
          <button
            key={m}
            onClick={() => onChangeField("proxyMode", m)}
            className={cn(
              "px-4 py-1.5 rounded-md text-xs font-medium transition-all duration-150",
              proxyMode === m
                ? "bg-phantom-accent/15 text-phantom-accent"
                : "text-phantom-ghost hover:text-white"
            )}
          >
            {m === "iproyal" ? "IPRoyal" : "Custom SOCKS5"}
          </button>
        ))}
      </div>

      <div className="space-y-3 max-w-sm mx-auto">
        {proxyMode === "iproyal" ? (
          <>
            <div className="space-y-1">
              <label className="text-xs text-phantom-ghost font-medium uppercase tracking-wider">
                IPRoyal Username
              </label>
              <input
                type="text"
                value={proxyUsername}
                onChange={(e) => onChangeField("proxyUsername", e.target.value)}
                placeholder="user@domain.com"
                className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-phantom-ghost/50 focus:outline-none focus:border-phantom-accent/50 transition-colors"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-phantom-ghost font-medium uppercase tracking-wider">
                IPRoyal Password
              </label>
              <input
                type="password"
                value={proxyPassword}
                onChange={(e) => onChangeField("proxyPassword", e.target.value)}
                placeholder="••••••••"
                className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-phantom-ghost/50 focus:outline-none focus:border-phantom-accent/50 transition-colors"
              />
            </div>
          </>
        ) : (
          <>
            <div className="space-y-1">
              <label className="text-xs text-phantom-ghost font-medium uppercase tracking-wider">
                SOCKS5 Host
              </label>
              <input
                type="text"
                value={proxyHost}
                onChange={(e) => onChangeField("proxyHost", e.target.value)}
                placeholder="proxy.example.com"
                className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-phantom-ghost/50 focus:outline-none focus:border-phantom-accent/50 transition-colors"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-phantom-ghost font-medium uppercase tracking-wider">
                Port
              </label>
              <input
                type="text"
                value={proxyPort}
                onChange={(e) => onChangeField("proxyPort", e.target.value)}
                placeholder="1080"
                className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-phantom-ghost/50 focus:outline-none focus:border-phantom-accent/50 transition-colors"
              />
            </div>
          </>
        )}
      </div>

      <div className="flex justify-center">
        <PrimaryButton
          label={verifying ? "Verifying proxies..." : "Verify Proxy on All Phones"}
          onClick={onVerify}
          loading={verifying}
          icon={<ShieldCheck className="w-4 h-4" strokeWidth={1.75} />}
        />
      </div>

      {phoneResults.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs text-phantom-ghost uppercase tracking-wider font-medium">
            Proxy verification results
          </div>
          {phoneResults.map((r) => (
            <div key={r.serial} className="phantom-panel p-3 flex items-center justify-between">
              <span className="font-mono text-xs text-white">{r.serial}</span>
              <div className="flex items-center gap-2">
                {r.verified ? (
                  <span className="text-[10px] text-phantom-accent border border-phantom-accent/20 bg-phantom-accent/10 px-2 py-0.5 rounded-md font-semibold uppercase flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> PROXY_READY
                  </span>
                ) : (
                  <span className="text-[10px] text-phantom-red border border-phantom-red/20 bg-phantom-red/10 px-2 py-0.5 rounded-md font-semibold uppercase flex items-center gap-1">
                    <XCircle className="w-3 h-3" /> Failed
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4 — Add Accounts
// ---------------------------------------------------------------------------

function Step4({
  credentialText,
  assignedSerial,
  proxyReadySerials,
  provisioning,
  accountResults,
  onChangeCredentials,
  onChangeSerial,
  onProvision,
}: {
  credentialText: string;
  assignedSerial: string;
  proxyReadySerials: string[];
  provisioning: boolean;
  accountResults: AccountResult[];
  onChangeCredentials: (v: string) => void;
  onChangeSerial: (v: string) => void;
  onProvision: () => void;
}) {
  const statusIcon = (status: AccountResult["status"]) => {
    if (status === "provisioned") return <CheckCircle2 className="w-4 h-4 text-phantom-accent" />;
    if (status === "needs_2fa") return <Clock className="w-4 h-4 text-yellow-400" />;
    return <XCircle className="w-4 h-4 text-phantom-red" />;
  };

  return (
    <div className="space-y-5">
      <div className="text-center space-y-2">
        <h2 className="text-xl font-display font-bold">Add Instagram Accounts</h2>
        <p className="text-phantom-ghost text-sm max-w-sm mx-auto">
          Paste credentials below — one per line. 2FA secret is optional.
        </p>
      </div>

      <div className="space-y-3 max-w-lg mx-auto">
        <div className="space-y-1">
          <label className="text-xs text-phantom-ghost font-medium uppercase tracking-wider">
            Credentials
          </label>
          <textarea
            value={credentialText}
            onChange={(e) => onChangeCredentials(e.target.value)}
            rows={6}
            placeholder={"username:password\nusername2:password2:TOTP_SECRET\nusername3:password3"}
            className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 transition-colors font-mono resize-y"
          />
          <p className="text-[11px] text-phantom-ghost">
            Format: <code className="text-phantom-accent">username:password</code> or{" "}
            <code className="text-phantom-accent">username:password:2fa_secret</code>
          </p>
        </div>

        <div className="space-y-1">
          <label className="text-xs text-phantom-ghost font-medium uppercase tracking-wider">
            Assign to Phone
          </label>
          {proxyReadySerials.length === 0 ? (
            <div className="flex items-center gap-2 text-phantom-amber text-xs">
              <WifiOff className="w-3.5 h-3.5" />
              No PROXY_READY phones. Complete proxy setup first.
            </div>
          ) : (
            <select
              value={assignedSerial}
              onChange={(e) => onChangeSerial(e.target.value)}
              className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-phantom-accent/50 transition-colors"
            >
              {proxyReadySerials.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          )}
        </div>

        <PrimaryButton
          label={provisioning ? "Provisioning..." : "Provision Accounts"}
          onClick={onProvision}
          loading={provisioning}
          disabled={proxyReadySerials.length === 0 || !credentialText.trim()}
          icon={<Users className="w-4 h-4" strokeWidth={1.75} />}
        />
      </div>

      {accountResults.length > 0 && (
        <div className="space-y-2 max-w-lg mx-auto">
          <div className="text-xs text-phantom-ghost uppercase tracking-wider font-medium">
            Provisioning results
          </div>
          {accountResults.map((r, idx) => (
            <div key={idx} className="phantom-panel p-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                {statusIcon(r.status)}
                <span className="text-sm font-medium">{r.username}</span>
                {r.error && (
                  <span className="text-[10px] text-phantom-red truncate max-w-[200px]">
                    {r.error}
                  </span>
                )}
              </div>
              <span
                className={cn(
                  "text-[10px] font-semibold uppercase px-2 py-0.5 rounded-md border",
                  r.status === "provisioned"
                    ? "text-phantom-accent border-phantom-accent/20 bg-phantom-accent/10"
                    : r.status === "needs_2fa"
                    ? "text-yellow-400 border-yellow-400/20 bg-yellow-400/10"
                    : "text-phantom-red border-phantom-red/20 bg-phantom-red/10"
                )}
              >
                {r.status === "provisioned"
                  ? "LOGGED IN"
                  : r.status === "needs_2fa"
                  ? "NEEDS 2FA"
                  : "FAILED"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 5 — Launch Warming
// ---------------------------------------------------------------------------

const WARMING_CURVE_LABELS = [
  "Day 1: Profile exploration, 10 story views",
  "Day 2: 5 follows, 15 story views",
  "Day 3: 10 follows, 20 story views, 5 likes",
  "Day 4: 15 follows, 25 story views, 10 likes",
  "Day 5: 20 follows, 30 story views, 15 likes",
  "Day 6: 25 follows, 35 story views, 20 likes, 2 DMs",
  "Day 7: Full speed — steady state reached",
];

function Step5({
  phoneCount,
  accountCount,
  warming,
  warmed,
  onStartWarming,
  onGoToDashboard,
}: {
  phoneCount: number;
  accountCount: number;
  warming: boolean;
  warmed: boolean;
  onStartWarming: () => void;
  onGoToDashboard: () => void;
}) {
  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <h2 className="text-xl font-display font-bold">Launch Warming</h2>
        <p className="text-phantom-ghost text-sm max-w-sm mx-auto">
          Your fleet is ready. Warming gradually ramps up activity to build trust with Instagram.
        </p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 gap-3 max-w-sm mx-auto">
        <div className="phantom-panel p-4 text-center space-y-1">
          <div className="text-3xl font-display font-bold text-phantom-accent">{phoneCount}</div>
          <div className="text-[10px] text-phantom-ghost uppercase tracking-wider">Phones Ready</div>
        </div>
        <div className="phantom-panel p-4 text-center space-y-1">
          <div className="text-3xl font-display font-bold text-phantom-accent">{accountCount}</div>
          <div className="text-[10px] text-phantom-ghost uppercase tracking-wider">Accounts</div>
        </div>
      </div>

      {/* 7-day curve */}
      <div className="phantom-panel p-4 space-y-3 max-w-lg mx-auto">
        <div className="text-xs text-phantom-ghost uppercase tracking-wider font-medium">
          7-Day Warming Curve
        </div>
        <div className="space-y-1.5">
          {WARMING_CURVE_LABELS.map((label, idx) => (
            <div key={idx} className="flex items-center gap-3">
              <div
                className={cn(
                  "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0",
                  idx === 6
                    ? "bg-phantom-accent/20 text-phantom-accent"
                    : "bg-phantom-panelHi text-phantom-ghost"
                )}
              >
                {idx + 1}
              </div>
              <span
                className={cn(
                  "text-xs",
                  idx === 6 ? "text-phantom-accent font-medium" : "text-phantom-ghost"
                )}
              >
                {label}
              </span>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2 text-phantom-ghost text-xs border-t border-phantom-border pt-3">
          <Clock className="w-3.5 h-3.5" />
          Estimated time to steady state: <strong className="text-white">7 days</strong>
        </div>
      </div>

      {warmed ? (
        <div className="space-y-4">
          <div className="flex items-center justify-center gap-2 text-phantom-accent font-medium">
            <CheckCircle2 className="w-5 h-5" />
            Warming cycle started successfully!
          </div>
          <div className="flex justify-center">
            <button
              onClick={onGoToDashboard}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-semibold bg-phantom-accent text-phantom-bg hover:bg-phantom-accent/90 transition-all duration-200 shadow-[0_0_24px_hsl(162_100%_54%/0.4)]"
            >
              Go to Dashboard
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      ) : (
        <div className="flex justify-center">
          <PrimaryButton
            label={warming ? "Starting..." : "Start Warming"}
            onClick={onStartWarming}
            loading={warming}
            disabled={accountCount === 0}
            icon={<Flame className="w-4 h-4" strokeWidth={1.75} />}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main wizard
// ---------------------------------------------------------------------------

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState<StepId>(1);

  // Step 1
  const [devices, setDevices] = useState<DeviceEntry[]>([]);
  const [scanning, setScanning] = useState(false);

  // Step 3
  const [proxyMode, setProxyMode] = useState<"iproyal" | "custom">("iproyal");
  const [proxyUsername, setProxyUsername] = useState("");
  const [proxyPassword, setProxyPassword] = useState("");
  const [proxyHost, setProxyHost] = useState("");
  const [proxyPort, setProxyPort] = useState("1080");
  const [verifying, setVerifying] = useState(false);
  const [phoneResults, setPhoneResults] = useState<ProxyPhoneResult[]>([]);

  // Step 4
  const [credentialText, setCredentialText] = useState("");
  const [assignedSerial, setAssignedSerial] = useState("");
  const [provisioning, setProvisioning] = useState(false);
  const [accountResults, setAccountResults] = useState<AccountResult[]>([]);

  // Step 5
  const [warming, setWarming] = useState(false);
  const [warmed, setWarmed] = useState(false);

  const proxyReadySerials = phoneResults.filter((r) => r.verified).map((r) => r.serial);

  // Auto-select first proxy-ready phone for step 4
  useEffect(() => {
    if (proxyReadySerials.length > 0 && !assignedSerial) {
      setAssignedSerial(proxyReadySerials[0]);
    }
  }, [proxyReadySerials]);

  // ---- Handlers ----

  const handleScan = async () => {
    setScanning(true);
    try {
      const res = await fetch(`${API}/api/fleet/scan`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const mapped: DeviceEntry[] = (data.phones || []).map((p: { serial: string; state: string }) => ({
          serial: p.serial,
          state: p.state.toUpperCase(),
          apkInstalled: false,
          apkHealthy: false,
          installing: false,
          testing: false,
        }));
        setDevices(mapped);
      }
    } catch {
      // Backend offline — no-op for demo
    } finally {
      setScanning(false);
    }
  };

  const handleInstallAPK = async (serial: string) => {
    setDevices((prev) =>
      prev.map((d) => (d.serial === serial ? { ...d, installing: true } : d))
    );
    try {
      const res = await fetch(`${API}/api/fleet/${encodeURIComponent(serial)}/install-apk`, {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        setDevices((prev) =>
          prev.map((d) =>
            d.serial === serial ? { ...d, installing: false, apkInstalled: data.installed } : d
          )
        );
      } else {
        setDevices((prev) =>
          prev.map((d) => (d.serial === serial ? { ...d, installing: false } : d))
        );
      }
    } catch {
      setDevices((prev) =>
        prev.map((d) => (d.serial === serial ? { ...d, installing: false } : d))
      );
    }
  };

  const handleTestConnection = async (serial: string) => {
    setDevices((prev) =>
      prev.map((d) => (d.serial === serial ? { ...d, testing: true } : d))
    );
    try {
      const res = await fetch(
        `${API}/api/fleet/${encodeURIComponent(serial)}/apk-health`
      );
      if (res.ok) {
        const data = await res.json();
        setDevices((prev) =>
          prev.map((d) =>
            d.serial === serial ? { ...d, testing: false, apkHealthy: data.alive } : d
          )
        );
      } else {
        setDevices((prev) =>
          prev.map((d) => (d.serial === serial ? { ...d, testing: false } : d))
        );
      }
    } catch {
      setDevices((prev) =>
        prev.map((d) => (d.serial === serial ? { ...d, testing: false } : d))
      );
    }
  };

  const handleProxyFieldChange = (k: string, v: string) => {
    if (k === "proxyMode") setProxyMode(v as "iproyal" | "custom");
    else if (k === "proxyUsername") setProxyUsername(v);
    else if (k === "proxyPassword") setProxyPassword(v);
    else if (k === "proxyHost") setProxyHost(v);
    else if (k === "proxyPort") setProxyPort(v);
  };

  const handleVerifyAll = async () => {
    setVerifying(true);
    try {
      const res = await fetch(`${API}/api/fleet/verify-all`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const results: ProxyPhoneResult[] = Object.entries(
          (data.results ?? {}) as Record<string, boolean>
        ).map(([serial, verified]) => ({
          serial,
          state: (verified ? "PROXY_READY" : "ONLINE") as PhoneState,
          verified,
        }));
        setPhoneResults(results);
      }
    } catch {
      // Backend offline
    } finally {
      setVerifying(false);
    }
  };

  const handleProvision = async () => {
    setProvisioning(true);
    const lines = credentialText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);

    const credentials = lines.map((line) => {
      const parts = line.split(":");
      return {
        username: parts[0] ?? "",
        password: parts[1] ?? "",
        totp_secret: parts[2] ?? undefined,
        platform: "instagram",
        phone_serial: assignedSerial || undefined,
      };
    });

    try {
      const res = await fetch(`${API}/api/accounts/provision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credentials }),
      });
      if (res.ok) {
        const data = await res.json();
        const results: AccountResult[] = (data.results || []).map(
          (r: {
            username: string;
            status: string;
            account_id: string | null;
            error: string | null;
          }) => ({
            username: r.username,
            status:
              r.status === "provisioned"
                ? "provisioned"
                : r.error?.includes("2fa")
                ? "needs_2fa"
                : "failed",
            account_id: r.account_id,
            error: r.error,
          })
        );
        setAccountResults(results);
      }
    } catch {
      // Backend offline
    } finally {
      setProvisioning(false);
    }
  };

  const handleStartWarming = async () => {
    setWarming(true);
    try {
      const res = await fetch(`${API}/api/fleet/start-warming`, { method: "POST" });
      if (res.ok) {
        setWarmed(true);
      }
    } catch {
      // Backend offline — optimistic success for demo
      setWarmed(true);
    } finally {
      setWarming(false);
    }
  };

  const canAdvance = (): boolean => {
    if (step === 1) return devices.length > 0;
    if (step === 2) return devices.some((d) => d.apkInstalled);
    if (step === 3) return proxyReadySerials.length > 0;
    if (step === 4) return accountResults.some((r) => r.status === "provisioned");
    return false;
  };

  const provisionedCount = accountResults.filter((r) => r.status === "provisioned").length;

  return (
    <div className="min-h-[calc(100vh-8rem)] flex flex-col items-center justify-start py-10">
      {/* Page header */}
      <div className="text-center mb-8">
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium mb-2">
          Setup Wizard
        </div>
        <h1 className="font-display text-3xl font-bold tracking-tight">
          Phone Farm <span className="phantom-accent-text">Onboarding</span>
        </h1>
        <p className="text-phantom-ghost text-sm mt-2">
          Get your first phone fleet live in 5 steps.
        </p>
      </div>

      {/* Step indicator */}
      <StepIndicator current={step} />

      {/* Step card */}
      <div className="w-full max-w-xl phantom-panel p-8 space-y-8">
        {step === 1 && (
          <Step1 devices={devices} scanning={scanning} onScan={handleScan} />
        )}
        {step === 2 && (
          <Step2
            devices={devices}
            onInstall={handleInstallAPK}
            onTestConnection={handleTestConnection}
          />
        )}
        {step === 3 && (
          <Step3
            proxyUsername={proxyUsername}
            proxyPassword={proxyPassword}
            proxyHost={proxyHost}
            proxyPort={proxyPort}
            proxyMode={proxyMode}
            phoneResults={phoneResults}
            verifying={verifying}
            onChangeField={handleProxyFieldChange}
            onVerify={handleVerifyAll}
          />
        )}
        {step === 4 && (
          <Step4
            credentialText={credentialText}
            assignedSerial={assignedSerial}
            proxyReadySerials={proxyReadySerials}
            provisioning={provisioning}
            accountResults={accountResults}
            onChangeCredentials={setCredentialText}
            onChangeSerial={setAssignedSerial}
            onProvision={handleProvision}
          />
        )}
        {step === 5 && (
          <Step5
            phoneCount={proxyReadySerials.length || devices.length}
            accountCount={provisionedCount}
            warming={warming}
            warmed={warmed}
            onStartWarming={handleStartWarming}
            onGoToDashboard={() => router.push("/")}
          />
        )}

        {/* Navigation footer */}
        {step < 5 && (
          <div className="flex items-center justify-between pt-4 border-t border-phantom-border">
            <button
              onClick={() => setStep((s) => Math.max(1, s - 1) as StepId)}
              disabled={step === 1}
              className={cn(
                "px-4 py-2 rounded-lg text-sm font-medium border transition-all duration-200",
                "bg-phantom-panelHi text-phantom-ghost border-phantom-border hover:text-white",
                step === 1 && "opacity-30 cursor-not-allowed"
              )}
            >
              Back
            </button>
            <GhostButton
              label="Next Step"
              onClick={() => setStep((s) => Math.min(5, s + 1) as StepId)}
              disabled={!canAdvance()}
            />
          </div>
        )}
      </div>
    </div>
  );
}
