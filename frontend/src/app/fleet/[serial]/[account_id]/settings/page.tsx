"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { use } from "react";
import {
  ChevronLeft, Smartphone, LogIn, LogOut, Cpu, Scan, LayoutList,
  Shield, Clock, Heart, MessageCircle, UserPlus, UserMinus,
  BookOpen, Send, Film, Share2, TrendingUp, Users, Zap,
  ChevronDown, ChevronUp, RefreshCw, Target, Bot, Plus, Trash2,
  Key, Crosshair,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

type Tab =
  | "overview" | "timer" | "targets" | "follow" | "unfollow" | "like"
  | "comment" | "story" | "dm" | "post" | "reels" | "share" | "threads";

type AccountSettings = {
  id: string;
  username: string;
  password: string;
  clonePackage: string;
  loggedIn: boolean;
  followers: number;
  following: number;
  jobOrders: { follow: boolean; like: boolean; comment: boolean };
  tags: string;
  enable2fa: boolean;
  twoFaKey: string;
  enableEmail: boolean;
  startHour: number;
  endHour: number;
  // Timer
  timerMinActionsPerCycle: number;
  timerMaxActionsPerCycle: number;
  timerCycleMinDelay: number;
  timerCycleMaxDelay: number;
  // Follow
  followEnabled: boolean;      followDailyMax: number;      followMinDelay: number;      followMaxDelay: number;
  followMethodFollowers: boolean; followMethodLikers: boolean; followMethodHashtag: boolean;
  followMethodSpecific: boolean;  followMethodOwn: boolean;
  followSource: string;
  followScrollProfile: boolean;  followLikeRandomPosts: boolean;
  followMinPerOp: number;        followMaxPerOp: number;
  followAutoIncrement: boolean;  followAutoIncrStart: number; followAutoIncrStep: number; followAutoIncrMax: number;
  followMinFollowers: number;    followMaxFollowers: number;
  followSkipPrivate: boolean;    followSkipVerified: boolean;
  // Unfollow
  unfollowEnabled: boolean;    unfollowDailyMax: number;    unfollowMinDelay: number;    unfollowMaxDelay: number;
  unfollowMethod: "non_followers" | "everyone" | "whitelist";
  unfollowMinAgeDays: number;  unfollowMinPerOp: number;    unfollowMaxPerOp: number;
  // Like
  likeEnabled: boolean;        likeDailyMax: number;        likeMinDelay: number;        likeMaxDelay: number;
  likeSource: "hashtag" | "feed" | "profile";
  likeSourceTarget: string;    likeMinPerOp: number;        likeMaxPerOp: number;
  likeMinPostLikes: number;    likeMaxPostLikes: number;    likeMinPosterFollowers: number;
  likeSkipVideos: boolean;
  // Story
  storyEnabled: boolean;       storyDailyMax: number;
  storySource: "following" | "explore" | "hashtag";
  storyMinPerOp: number;       storyMaxPerOp: number;
  storyReact: boolean;         storyReply: boolean;         storyLikeAfter: boolean;
  // Comment
  commentEnabled: boolean;     commentDailyMax: number;
  commentSource: "hashtag" | "feed";
  commentSourceTarget: string;
  commentTemplates: string;
  commentAI: boolean;          commentMinPerOp: number;     commentMaxPerOp: number;
  commentMinDelay: number;     commentMaxDelay: number;
  // DM
  dmEnabled: boolean;          dmDailyMax: number;
  dmSource: "recent_followers" | "following" | "tags";
  dmTemplates: string;         dmMinPerOp: number;          dmMaxPerOp: number;
  dmMinDelay: number;          dmMaxDelay: number;          dmTrackReplies: boolean;
  // Post
  postEnabled: boolean;
  postSource: "content_vault" | "upload_folder" | "url";
  postSourcePath: string;
  postCaptions: string;
  postHashtags: string;
  postPerDay: number;
  postHours: string;
  postType: "image" | "carousel" | "video";
  postAICaptions: boolean;
  postWatermark: boolean;
  postMinDelay: number;
  postMaxDelay: number;
  // Reels
  reelsWatchEnabled: boolean;
  reelsWatchSource: "explore" | "following" | "hashtag";
  reelsWatchTarget: string;
  reelsWatchMinPerOp: number;  reelsWatchMaxPerOp: number;  reelsWatchDailyMax: number;
  reelsLikeWhileWatching: boolean;
  reelsCommentWhileWatching: boolean;
  reelsSave: boolean;
  reelsPostEnabled: boolean;
  reelsPostSource: "content_vault" | "upload_folder";
  reelsPostSourcePath: string;
  reelsPostCaptions: string;
  reelsPostPerDay: number;
  reelsPostAICaptions: boolean;
};

// ─── Demo data ────────────────────────────────────────────────────────────────

function buildDemo(accountId: string): AccountSettings {
  return {
    id: accountId, username: "tatiannalifee", password: "••••••••••",
    clonePackage: "com.instagram.android", loggedIn: true,
    followers: 12480, following: 8234,
    jobOrders: { follow: true, like: true, comment: false },
    tags: "#fitness #lifestyle #motivation",
    enable2fa: false, twoFaKey: "", enableEmail: false,
    startHour: 8, endHour: 22,
    timerMinActionsPerCycle: 3, timerMaxActionsPerCycle: 8,
    timerCycleMinDelay: 300, timerCycleMaxDelay: 900,
    followEnabled: true,     followDailyMax: 25,  followMinDelay: 90,  followMaxDelay: 300,
    followMethodFollowers: true, followMethodLikers: false, followMethodHashtag: false,
    followMethodSpecific: false, followMethodOwn: false,
    followSource: "@fitnessmotivation\n@gymlife_official\n@calisthenics_pros\n@mensphysique_ig\n@alphamindset",
    followScrollProfile: true, followLikeRandomPosts: true,
    followMinPerOp: 3, followMaxPerOp: 8,
    followAutoIncrement: false, followAutoIncrStart: 5, followAutoIncrStep: 2, followAutoIncrMax: 30,
    followMinFollowers: 100, followMaxFollowers: 50000,
    followSkipPrivate: false, followSkipVerified: true,
    unfollowEnabled: true,   unfollowDailyMax: 25, unfollowMinDelay: 90, unfollowMaxDelay: 300,
    unfollowMethod: "non_followers", unfollowMinAgeDays: 3, unfollowMinPerOp: 3, unfollowMaxPerOp: 8,
    likeEnabled: true,       likeDailyMax: 75, likeMinDelay: 30, likeMaxDelay: 90,
    likeSource: "hashtag", likeSourceTarget: "#fitness",
    likeMinPerOp: 5, likeMaxPerOp: 15,
    likeMinPostLikes: 10, likeMaxPostLikes: 50000, likeMinPosterFollowers: 500,
    likeSkipVideos: false,
    storyEnabled: true, storyDailyMax: 150, storySource: "following",
    storyMinPerOp: 10, storyMaxPerOp: 30, storyReact: false, storyReply: false, storyLikeAfter: false,
    commentEnabled: false, commentDailyMax: 8, commentSource: "hashtag",
    commentSourceTarget: "#fitness",
    commentTemplates: "Love this! 🔥\nAmazing content!\nKeep grinding! 💪\nThis is so inspiring!\nGreat post 🙌",
    commentAI: false, commentMinPerOp: 1, commentMaxPerOp: 3, commentMinDelay: 60, commentMaxDelay: 180,
    dmEnabled: false, dmDailyMax: 5, dmSource: "recent_followers",
    dmTemplates: "Hey {username}! Thanks for connecting 🙌\nHi {username}, love your content!",
    dmMinPerOp: 1, dmMaxPerOp: 2, dmMinDelay: 60, dmMaxDelay: 180, dmTrackReplies: true,
    postEnabled: false, postSource: "content_vault", postSourcePath: "/content/tatiannalifee",
    postCaptions: "Living my best life ✨\nNew content dropping soon 🔥\nFollow for exclusive content 💋",
    postHashtags: "#fitness #lifestyle #motivation #onlyfans #content",
    postPerDay: 2, postHours: "09:00, 18:00", postType: "image",
    postAICaptions: false, postWatermark: false, postMinDelay: 3600, postMaxDelay: 7200,
    reelsWatchEnabled: false, reelsWatchSource: "explore", reelsWatchTarget: "",
    reelsWatchMinPerOp: 5, reelsWatchMaxPerOp: 20, reelsWatchDailyMax: 100,
    reelsLikeWhileWatching: true, reelsCommentWhileWatching: false, reelsSave: false,
    reelsPostEnabled: false, reelsPostSource: "content_vault", reelsPostSourcePath: "/reels/tatiannalifee",
    reelsPostCaptions: "Watch till the end 🔥\nNew content every day 💫",
    reelsPostPerDay: 1, reelsPostAICaptions: false,
  };
}

// ─── Tab config ───────────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "overview", label: "Overview",  icon: <Smartphone className="w-3.5 h-3.5" /> },
  { id: "timer",    label: "Timer",     icon: <Clock className="w-3.5 h-3.5" /> },
  { id: "targets",  label: "Targets",   icon: <Crosshair className="w-3.5 h-3.5" /> },
  { id: "follow",   label: "Follow",    icon: <UserPlus className="w-3.5 h-3.5" /> },
  { id: "unfollow", label: "Unfollow",  icon: <UserMinus className="w-3.5 h-3.5" /> },
  { id: "like",     label: "Like",      icon: <Heart className="w-3.5 h-3.5" /> },
  { id: "comment",  label: "Comment",   icon: <MessageCircle className="w-3.5 h-3.5" /> },
  { id: "story",    label: "Story",     icon: <BookOpen className="w-3.5 h-3.5" /> },
  { id: "dm",       label: "DM",        icon: <Send className="w-3.5 h-3.5" /> },
  { id: "post",     label: "Post",      icon: <LayoutList className="w-3.5 h-3.5" /> },
  { id: "reels",    label: "Reels",     icon: <Film className="w-3.5 h-3.5" /> },
  { id: "share",    label: "Share",     icon: <Share2 className="w-3.5 h-3.5" /> },
  { id: "threads",  label: "Threads",   icon: <MessageCircle className="w-3.5 h-3.5 text-phantom-magenta" /> },
];

// ─── Shared sub-components ────────────────────────────────────────────────────

function SectionCard({ title, children, collapsible }: { title: string; children: React.ReactNode; collapsible?: boolean }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="phantom-panel overflow-hidden">
      <div
        className={cn("px-5 py-3 border-b border-phantom-border bg-phantom-panelHi/40 flex items-center justify-between", collapsible && "cursor-pointer")}
        onClick={() => collapsible && setOpen((o) => !o)}
      >
        <span className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">{title}</span>
        {collapsible && (open ? <ChevronUp className="w-3.5 h-3.5 text-phantom-ghost" /> : <ChevronDown className="w-3.5 h-3.5 text-phantom-ghost" />)}
      </div>
      {open && <div className="p-5">{children}</div>}
    </div>
  );
}

function FieldRow({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="flex items-start gap-4 py-2">
      <div className="w-36 shrink-0 pt-2">
        <label className="text-xs text-phantom-ghost">{label}</label>
        {hint && <div className="text-[10px] text-phantom-ghost/40 mt-0.5 leading-tight">{hint}</div>}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function TextInput({ value, onChange, type = "text", placeholder, readOnly }: {
  value: string; onChange?: (v: string) => void; type?: string; placeholder?: string; readOnly?: boolean;
}) {
  return (
    <input type={type} value={value} placeholder={placeholder} readOnly={readOnly}
      onChange={(e) => onChange?.(e.target.value)}
      className={cn("w-full px-3 py-2 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 transition-colors font-mono", readOnly && "opacity-60 cursor-default")} />
  );
}

function TextareaInput({ value, onChange, placeholder, rows = 5 }: {
  value: string; onChange: (v: string) => void; placeholder?: string; rows?: number;
}) {
  return (
    <textarea value={value} rows={rows} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
      className="w-full px-3 py-2 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 transition-colors font-mono resize-none" />
  );
}

function Toggle({ checked, onChange, label, sublabel }: { checked: boolean; onChange: (v: boolean) => void; label: string; sublabel?: string }) {
  return (
    <label className="flex items-start gap-3 cursor-pointer select-none">
      <div onClick={() => onChange(!checked)} className={cn("w-9 h-5 rounded-full transition-colors relative shrink-0 mt-0.5", checked ? "bg-phantom-accent" : "bg-phantom-border")}>
        <span className={cn("absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform", checked ? "translate-x-4" : "translate-x-0")} />
      </div>
      <div>
        <span className="text-sm text-white">{label}</span>
        {sublabel && <div className="text-[11px] text-phantom-ghost/50 mt-0.5">{sublabel}</div>}
      </div>
    </label>
  );
}

function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center gap-2.5 cursor-pointer select-none">
      <div onClick={() => onChange(!checked)} className={cn("w-4 h-4 rounded border transition-colors flex items-center justify-center shrink-0", checked ? "bg-phantom-accent border-phantom-accent" : "bg-transparent border-phantom-border")}>
        {checked && <svg className="w-2.5 h-2.5 text-phantom-bg" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><polyline points="20 6 9 17 4 12" /></svg>}
      </div>
      <span className="text-sm text-white">{label}</span>
    </label>
  );
}

function RadioGroup<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void;
  options: { value: T; label: string; description?: string }[];
}) {
  return (
    <div className="space-y-2">
      {options.map((opt) => (
        <label key={opt.value} className="flex items-start gap-2.5 cursor-pointer select-none">
          <div onClick={() => onChange(opt.value)} className={cn("w-4 h-4 rounded-full border transition-colors flex items-center justify-center mt-0.5 shrink-0", value === opt.value ? "border-phantom-accent" : "border-phantom-border")}>
            {value === opt.value && <span className="w-2 h-2 rounded-full bg-phantom-accent" />}
          </div>
          <div>
            <span className="text-sm text-white">{opt.label}</span>
            {opt.description && <div className="text-[11px] text-phantom-ghost/50">{opt.description}</div>}
          </div>
        </label>
      ))}
    </div>
  );
}

function NumInput({ value, onChange, label, unit, min = 0, max }: {
  value: number; onChange: (v: number) => void; label?: string; unit?: string; min?: number; max?: number;
}) {
  return (
    <div>
      {label && <label className="block text-[10px] uppercase tracking-wider text-phantom-ghost mb-1.5">{label}</label>}
      <div className="flex items-center gap-1.5">
        <input type="number" min={min} max={max} value={value}
          onChange={(e) => onChange(Math.max(min, max !== undefined ? Math.min(max, Number(e.target.value)) : Number(e.target.value)))}
          className="w-24 px-3 py-2 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white font-mono focus:outline-none focus:border-phantom-accent/50 transition-colors" />
        {unit && <span className="text-xs text-phantom-ghost">{unit}</span>}
      </div>
    </div>
  );
}

function HourSelect({ value, onChange, label }: { value: number; onChange: (v: number) => void; label: string }) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wider text-phantom-ghost mb-1.5">{label}</label>
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}
        className="px-3 py-2 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white font-mono focus:outline-none focus:border-phantom-accent/50 transition-colors">
        {Array.from({ length: 24 }, (_, i) => i).map((h) => (
          <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>
        ))}
      </select>
    </div>
  );
}

function SaveBar({ onSave, saving, label }: { onSave: () => void; saving: boolean; label: string }) {
  return (
    <div className="flex justify-end pt-2">
      <button onClick={onSave} disabled={saving}
        className="px-6 py-2.5 rounded-lg text-sm font-semibold bg-phantom-accent text-phantom-bg hover:bg-phantom-accent/90 disabled:opacity-60 transition-colors">
        {saving ? "Saving…" : label}
      </button>
    </div>
  );
}

// ─── Overview tab ─────────────────────────────────────────────────────────────

function OverviewTab({ settings, serial, onSave }: { settings: AccountSettings; serial: string; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [detecting, setDetecting] = useState(false);
  const [detectMsg, setDetectMsg] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [saving, setSaving] = useState(false);

  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));
  const setJO = (patch: Partial<AccountSettings["jobOrders"]>) =>
    setLocal((p) => ({ ...p, jobOrders: { ...p.jobOrders, ...patch } }));

  const handleDetect = async () => {
    setDetecting(true); setDetectMsg("");
    try {
      const res = await fetch(`http://localhost:8001/api/accounts/${local.id}/detect-clone`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_serial: serial }),
      });
      const data = await res.json();
      if (data.clone_package) { set({ clonePackage: data.clone_package }); setDetectMsg(`Detected: ${data.clone_package}`); }
      else setDetectMsg(data.error ?? "No package detected — open the clone app first");
    } catch { setDetectMsg("Backend offline — open clone app on phone and retry"); }
    finally { setDetecting(false); }
  };

  const handleLogin = async () => {
    setLoggingIn(true);
    try { await fetch(`http://localhost:8001/api/accounts/${local.id}/login`, { method: "POST" }); set({ loggedIn: true }); }
    catch { } finally { setLoggingIn(false); }
  };

  const handleLogout = async () => {
    try { await fetch(`http://localhost:8001/api/accounts/${local.id}/logout`, { method: "POST" }); set({ loggedIn: false }); }
    catch { }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clone_package: local.clonePackage, tags: local.tags }),
      });
      onSave(local);
    } catch { } finally { setSaving(false); }
  };

  return (
    <div className="space-y-5">
      {/* Stats strip */}
      <div className="grid grid-cols-2 gap-3">
        <div className="phantom-panel px-5 py-4 flex items-center gap-3">
          <Users className="w-5 h-5 text-phantom-ghost/40" strokeWidth={1.5} />
          <div>
            <div className="text-xl font-display font-bold tabular-nums text-white">{local.followers.toLocaleString()}</div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Followers</div>
          </div>
        </div>
        <div className="phantom-panel px-5 py-4 flex items-center gap-3">
          <TrendingUp className="w-5 h-5 text-phantom-ghost/40" strokeWidth={1.5} />
          <div>
            <div className="text-xl font-display font-bold tabular-nums text-white">{local.following.toLocaleString()}</div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-[0.12em]">Following</div>
          </div>
        </div>
      </div>

      {/* Login Credentials */}
      <SectionCard title="Login credentials">
        <div className="divide-y divide-phantom-border/30">
          <FieldRow label="Username"><TextInput value={local.username} onChange={(v) => set({ username: v })} placeholder="instagram_username" /></FieldRow>
          <FieldRow label="Password"><TextInput value={local.password} onChange={(v) => set({ password: v })} type="password" placeholder="••••••••••" /></FieldRow>
        </div>
        <div className="flex items-center gap-3 mt-4 pt-3 border-t border-phantom-border/30">
          <div className={cn("flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border",
            local.loggedIn ? "text-green-400 bg-green-400/10 border-green-400/25" : "text-phantom-ghost bg-phantom-panelHi border-phantom-border")}>
            <span className={cn("w-1.5 h-1.5 rounded-full", local.loggedIn ? "bg-green-400" : "bg-phantom-ghost/40")} />
            {local.loggedIn ? "Session active" : "Not logged in"}
          </div>
          <button onClick={handleLogin} disabled={loggingIn}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-60 transition-colors">
            <LogIn className="w-4 h-4" strokeWidth={1.75} />
            {loggingIn ? "Logging in…" : "Login"}
          </button>
          <button onClick={handleLogout}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-phantom-panelHi text-phantom-ghost border border-phantom-border hover:text-white hover:bg-phantom-panelHi/80 transition-colors">
            <LogOut className="w-4 h-4" strokeWidth={1.75} />
            Logout
          </button>
        </div>
      </SectionCard>

      {/* App Cloner */}
      <SectionCard title="App cloner · NomixCloner">
        <div className="divide-y divide-phantom-border/30">
          <FieldRow label="APP ID"><TextInput value={local.clonePackage} onChange={(v) => set({ clonePackage: v })} placeholder="com.instagram.android_clone1" /></FieldRow>
        </div>
        <div className="flex items-center gap-3 mt-4 pt-3 border-t border-phantom-border/30">
          <button onClick={handleDetect} disabled={detecting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-60 transition-colors">
            <Scan className="w-4 h-4" strokeWidth={1.75} />
            {detecting ? "Detecting…" : "Detect APP ID"}
          </button>
          <button className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-phantom-panelHi text-phantom-ghost border border-phantom-border hover:text-white hover:bg-phantom-panelHi/80 transition-colors">
            <Cpu className="w-4 h-4" strokeWidth={1.75} />
            Load APP IDs
          </button>
          {detectMsg && (
            <span className={cn("text-xs px-3 py-1.5 rounded-lg border",
              detectMsg.startsWith("Detected") ? "text-green-400 bg-green-400/10 border-green-400/25" : "text-phantom-amber bg-phantom-amber/10 border-phantom-amber/25")}>
              {detectMsg}
            </span>
          )}
        </div>
        <p className="mt-3 text-[11px] text-phantom-ghost/50 leading-relaxed">
          Open the Instagram clone on the phone, then click <strong className="text-phantom-ghost">Detect APP ID</strong> to automatically sync the package name.
        </p>
      </SectionCard>

      {/* Job Orders */}
      <SectionCard title="Participate in job orders">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Toggle checked={local.jobOrders.follow} onChange={(v) => setJO({ follow: v })} label="Follow jobs" />
          <Toggle checked={local.jobOrders.like}   onChange={(v) => setJO({ like: v })}   label="Like jobs" />
          <Toggle checked={local.jobOrders.comment} onChange={(v) => setJO({ comment: v })} label="Comment jobs" />
        </div>
      </SectionCard>

      {/* Tags */}
      <SectionCard title="Tags · targeting">
        <FieldRow label="Tags" hint="Hashtags or @usernames">
          <TextInput value={local.tags} onChange={(v) => set({ tags: v })} placeholder="#fitness #lifestyle #motivation" />
        </FieldRow>
      </SectionCard>

      {/* Options */}
      <SectionCard title="Options">
        <div className="space-y-5">
          <div>
            <Toggle checked={local.enable2fa} onChange={(v) => set({ enable2fa: v })} label="Enable 2FA login" sublabel="Auto-generate TOTP codes during login" />
            {local.enable2fa && (
              <div className="mt-3 ml-12 space-y-2">
                <label className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-phantom-ghost">
                  <Key className="w-3 h-3" /> 2FA Secret Key (TOTP)
                </label>
                <TextInput
                  value={local.twoFaKey}
                  onChange={(v) => set({ twoFaKey: v })}
                  placeholder="JBSWY3DPEHPK3PXP  (base32 secret from authenticator app)"
                />
                <p className="text-[11px] text-phantom-ghost/50 leading-relaxed">
                  Paste the base32 secret from your authenticator app (Google Auth / Authy). The bot auto-generates the 6-digit code at login time — no manual entry needed.
                </p>
              </div>
            )}
          </div>
          <Toggle checked={local.enableEmail} onChange={(v) => set({ enableEmail: v })} label="Enable dashboard email alerts" />
        </div>
      </SectionCard>

      <div className="flex justify-end gap-3">
        <Link href={`/fleet/${serial}`} className="px-5 py-2.5 rounded-lg text-sm font-medium bg-phantom-panelHi text-phantom-ghost border border-phantom-border hover:text-white hover:bg-phantom-panelHi/80 transition-colors">
          Cancel
        </Link>
        <button onClick={handleSave} disabled={saving}
          className="px-6 py-2.5 rounded-lg text-sm font-semibold bg-phantom-accent text-phantom-bg hover:bg-phantom-accent/90 disabled:opacity-60 transition-colors">
          {saving ? "Saving…" : "Save settings"}
        </button>
      </div>
    </div>
  );
}

// ─── Timer tab ────────────────────────────────────────────────────────────────

function TimerTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);
  const hours = local.endHour - local.startHour;

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start_hour: local.startHour, end_hour: local.endHour,
        timer_min_actions_per_cycle: local.timerMinActionsPerCycle,
        timer_max_actions_per_cycle: local.timerMaxActionsPerCycle,
        timer_cycle_min_delay: local.timerCycleMinDelay,
        timer_cycle_max_delay: local.timerCycleMaxDelay,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <SectionCard title="Active window">
        <div className="flex items-end gap-8 flex-wrap">
          <HourSelect value={local.startHour} onChange={(v) => setLocal((p) => ({ ...p, startHour: v }))} label="Start hour" />
          <HourSelect value={local.endHour}   onChange={(v) => setLocal((p) => ({ ...p, endHour: v }))}   label="End hour" />
          <div className="text-sm text-phantom-ghost pb-2">
            Active window: <span className="text-white font-mono">{hours > 0 ? hours : 24 + hours}h</span>
          </div>
        </div>
        {/* Timeline */}
        <div className="mt-4 relative h-8 bg-phantom-bg rounded-full overflow-hidden border border-phantom-border">
          <div className="absolute top-0 bottom-0 bg-phantom-accent/30 border-l border-r border-phantom-accent/50"
            style={{ left: `${(local.startHour / 24) * 100}%`, width: `${((local.endHour - local.startHour) / 24) * 100}%` }} />
          {[0, 6, 12, 18].map((h) => (
            <div key={h} className="absolute top-0 bottom-0 w-px bg-phantom-border/30" style={{ left: `${(h / 24) * 100}%` }} />
          ))}
        </div>
        <div className="flex justify-between text-[10px] text-phantom-ghost/40 mt-1 font-mono">
          <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span>
        </div>
        <p className="mt-3 text-[11px] text-phantom-ghost/50">
          All actions are constrained to this time window (phone&apos;s local timezone).
        </p>
      </SectionCard>

      <SectionCard title="Random action cycle">
        <p className="text-xs text-phantom-ghost/60 mb-5">
          Each cycle picks a random number of actions between Min and Max, then waits a random delay before the next cycle.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          <NumInput value={local.timerMinActionsPerCycle} onChange={(v) => setLocal((p) => ({ ...p, timerMinActionsPerCycle: v }))} label="Min actions/cycle" unit="actions" min={1} />
          <NumInput value={local.timerMaxActionsPerCycle} onChange={(v) => setLocal((p) => ({ ...p, timerMaxActionsPerCycle: v }))} label="Max actions/cycle" unit="actions" min={1} />
          <NumInput value={local.timerCycleMinDelay}      onChange={(v) => setLocal((p) => ({ ...p, timerCycleMinDelay: v }))}      label="Min cycle delay"  unit="sec" min={0} />
          <NumInput value={local.timerCycleMaxDelay}      onChange={(v) => setLocal((p) => ({ ...p, timerCycleMaxDelay: v }))}      label="Max cycle delay"  unit="sec" min={0} />
        </div>
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save timer" />
    </div>
  );
}

// ─── Follow tab ───────────────────────────────────────────────────────────────

function FollowTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [scraping, setScraping] = useState(false);
  const [scrapeMsg, setScrapeMsg] = useState("");
  const [saving, setSaving] = useState(false);

  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  const handleScrape = async () => {
    setScraping(true); setScrapeMsg("");
    try {
      const res = await fetch(`http://localhost:8001/api/accounts/${local.id}/scrape-follow-source`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: local.followSource }),
      });
      const d = await res.json();
      setScrapeMsg(d.message ?? `Scraped ${d.count ?? "?"} users`);
    } catch { setScrapeMsg("Backend offline"); }
    finally { setScraping(false); }
  };

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        follow_enabled: local.followEnabled, follow_daily_max: local.followDailyMax,
        follow_min_delay: local.followMinDelay, follow_max_delay: local.followMaxDelay,
        follow_source: local.followSource,
        follow_scroll_profile: local.followScrollProfile,
        follow_like_random_posts: local.followLikeRandomPosts,
        follow_min_per_op: local.followMinPerOp, follow_max_per_op: local.followMaxPerOp,
        follow_auto_increment: local.followAutoIncrement,
        follow_auto_incr_start: local.followAutoIncrStart,
        follow_auto_incr_step: local.followAutoIncrStep,
        follow_auto_incr_max: local.followAutoIncrMax,
        follow_min_followers: local.followMinFollowers,
        follow_max_followers: local.followMaxFollowers,
        follow_skip_private: local.followSkipPrivate,
        follow_skip_verified: local.followSkipVerified,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <SectionCard title="Follow settings">
        <Toggle checked={local.followEnabled} onChange={(v) => set({ followEnabled: v })}
          label="Enable follow" sublabel="Run follow actions during active window" />
      </SectionCard>

      <SectionCard title="Follow method">
        <p className="text-xs text-phantom-ghost/60 mb-4">Select which source to follow users from.</p>
        <div className="space-y-3">
          <Checkbox checked={local.followMethodFollowers} onChange={(v) => set({ followMethodFollowers: v })} label="Follow Followers — target a user's followers list" />
          <Checkbox checked={local.followMethodLikers}    onChange={(v) => set({ followMethodLikers: v })}    label="Follow Likers — target users who liked a specific post" />
          <Checkbox checked={local.followMethodHashtag}   onChange={(v) => set({ followMethodHashtag: v })}   label="Follow Hashtag — target users posting under a hashtag" />
          <Checkbox checked={local.followMethodSpecific}  onChange={(v) => set({ followMethodSpecific: v })}  label="Specific Users — follow from a custom list" />
          <Checkbox checked={local.followMethodOwn}       onChange={(v) => set({ followMethodOwn: v })}       label="Own Followers' Followers — compound source" />
        </div>
        <div className="mt-5 pt-4 border-t border-phantom-border/30 space-y-3">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] uppercase tracking-wider text-phantom-ghost">
                Target sources — one per line (@username, #hashtag, or post URL)
              </label>
              <span className="text-[10px] text-phantom-ghost/40 font-mono">
                {local.followSource.split("\n").filter(Boolean).length} sources
              </span>
            </div>
            <textarea
              value={local.followSource}
              onChange={(e) => set({ followSource: e.target.value })}
              rows={12}
              placeholder={"@fitnessmotivation\n@gymlife_official\n@mensphysique_ig\n#fitness\n#bodybuilding\n(add 1000s of targets — one per line)"}
              className="w-full px-3 py-2.5 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/30 focus:outline-none focus:border-phantom-accent/50 transition-colors font-mono resize-y min-h-[160px]"
            />
            <p className="mt-1.5 text-[11px] text-phantom-ghost/50">
              The bot cycles through this list in order, scraping followers/likers from each source. Supports thousands of entries.
            </p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <button onClick={handleScrape} disabled={scraping}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-phantom-accent/15 text-phantom-accent border border-phantom-accent/30 hover:bg-phantom-accent/25 disabled:opacity-60 transition-colors">
              <RefreshCw className={cn("w-4 h-4", scraping && "animate-spin")} strokeWidth={1.75} />
              {scraping ? "Scraping…" : "Scrape Source Followers"}
            </button>
            <button className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-phantom-panelHi text-phantom-ghost border border-phantom-border hover:text-white hover:bg-phantom-panelHi/80 transition-colors">
              <Shield className="w-4 h-4" strokeWidth={1.75} />
              Check Follow Back Ratio
            </button>
            {scrapeMsg && (
              <span className="text-xs px-3 py-1.5 rounded-lg border text-phantom-accent bg-phantom-accent/10 border-phantom-accent/25">{scrapeMsg}</span>
            )}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Sub-options">
        <div className="space-y-3">
          <Checkbox checked={local.followScrollProfile}    onChange={(v) => set({ followScrollProfile: v })}    label="Scroll Profile — browse target's profile before following" />
          <Checkbox checked={local.followLikeRandomPosts}  onChange={(v) => set({ followLikeRandomPosts: v })}  label="Like 1-3 Random Posts — engage before following to appear human" />
        </div>
      </SectionCard>

      <SectionCard title="Limits">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          <NumInput value={local.followMinPerOp}  onChange={(v) => set({ followMinPerOp: v })}  label="Min / operation" unit="follows" min={1} />
          <NumInput value={local.followMaxPerOp}  onChange={(v) => set({ followMaxPerOp: v })}  label="Max / operation" unit="follows" min={1} />
          <NumInput value={local.followDailyMax}  onChange={(v) => set({ followDailyMax: v })}  label="Daily max"       unit="follows" min={0} />
          <div />
          <NumInput value={local.followMinDelay}  onChange={(v) => set({ followMinDelay: v })}  label="Min delay"      unit="sec" min={0} />
          <NumInput value={local.followMaxDelay}  onChange={(v) => set({ followMaxDelay: v })}  label="Max delay"      unit="sec" min={0} />
        </div>
      </SectionCard>

      <SectionCard title="Auto increment follow limit" collapsible>
        <p className="text-xs text-phantom-ghost/60 mb-4">
          Warm-up ramp: starts at a low daily max and increments each day until reaching the max. Mimics a natural new account growth pattern.
        </p>
        <div className="mb-4">
          <Toggle checked={local.followAutoIncrement} onChange={(v) => set({ followAutoIncrement: v })}
            label="Enable auto increment" sublabel="Override daily max with ramp schedule" />
        </div>
        <div className={cn("grid grid-cols-2 sm:grid-cols-3 gap-5 transition-opacity", !local.followAutoIncrement && "opacity-40 pointer-events-none")}>
          <NumInput value={local.followAutoIncrStart} onChange={(v) => set({ followAutoIncrStart: v })} label="Start"         unit="follows/day" min={1} />
          <NumInput value={local.followAutoIncrStep}  onChange={(v) => set({ followAutoIncrStep: v })}  label="Increment"     unit="+/day" min={1} />
          <NumInput value={local.followAutoIncrMax}   onChange={(v) => set({ followAutoIncrMax: v })}   label="Max (ceiling)" unit="follows/day" min={1} />
        </div>
      </SectionCard>

      <SectionCard title="Filters" collapsible>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5 mb-4">
          <NumInput value={local.followMinFollowers} onChange={(v) => set({ followMinFollowers: v })} label="Min followers" min={0} />
          <NumInput value={local.followMaxFollowers} onChange={(v) => set({ followMaxFollowers: v })} label="Max followers" min={0} />
        </div>
        <div className="space-y-3">
          <Checkbox checked={local.followSkipPrivate}  onChange={(v) => set({ followSkipPrivate: v })}  label="Skip private accounts" />
          <Checkbox checked={local.followSkipVerified} onChange={(v) => set({ followSkipVerified: v })} label="Skip verified accounts" />
        </div>
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save follow settings" />
    </div>
  );
}

// ─── Unfollow tab ─────────────────────────────────────────────────────────────

function UnfollowTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unfollow_enabled: local.unfollowEnabled, unfollow_daily_max: local.unfollowDailyMax,
        unfollow_min_delay: local.unfollowMinDelay, unfollow_max_delay: local.unfollowMaxDelay,
        unfollow_method: local.unfollowMethod, unfollow_min_age_days: local.unfollowMinAgeDays,
        unfollow_min_per_op: local.unfollowMinPerOp, unfollow_max_per_op: local.unfollowMaxPerOp,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <SectionCard title="Unfollow settings">
        <Toggle checked={local.unfollowEnabled} onChange={(v) => set({ unfollowEnabled: v })}
          label="Enable unfollow" sublabel="Automatically clean up non-followers" />
      </SectionCard>

      <SectionCard title="Unfollow method">
        <RadioGroup<"non_followers" | "everyone" | "whitelist">
          value={local.unfollowMethod}
          onChange={(v) => set({ unfollowMethod: v })}
          options={[
            { value: "non_followers", label: "Non-followers only", description: "Only unfollow users who did not follow back" },
            { value: "everyone",      label: "Everyone",           description: "Unfollow all users regardless of follow-back status" },
            { value: "whitelist",     label: "Whitelist mode",     description: "Only unfollow users on your unfollow list" },
          ]}
        />
      </SectionCard>

      <SectionCard title="Age filter">
        <FieldRow label="Min age" hint="Days since you followed them">
          <div className="flex items-center gap-2">
            <NumInput value={local.unfollowMinAgeDays} onChange={(v) => set({ unfollowMinAgeDays: v })} unit="days" min={0} />
          </div>
        </FieldRow>
        <p className="mt-2 text-[11px] text-phantom-ghost/50">
          Only unfollow accounts that were followed at least this many days ago. Prevents unfollowing too quickly.
        </p>
      </SectionCard>

      <SectionCard title="Limits">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          <NumInput value={local.unfollowMinPerOp}  onChange={(v) => set({ unfollowMinPerOp: v })}  label="Min / operation" unit="unfollows" min={1} />
          <NumInput value={local.unfollowMaxPerOp}  onChange={(v) => set({ unfollowMaxPerOp: v })}  label="Max / operation" unit="unfollows" min={1} />
          <NumInput value={local.unfollowDailyMax}  onChange={(v) => set({ unfollowDailyMax: v })}  label="Daily max"       unit="unfollows" min={0} />
          <div />
          <NumInput value={local.unfollowMinDelay}  onChange={(v) => set({ unfollowMinDelay: v })}  label="Min delay"       unit="sec" min={0} />
          <NumInput value={local.unfollowMaxDelay}  onChange={(v) => set({ unfollowMaxDelay: v })}  label="Max delay"       unit="sec" min={0} />
        </div>
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save unfollow settings" />
    </div>
  );
}

// ─── Like tab ─────────────────────────────────────────────────────────────────

function LikeTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        like_enabled: local.likeEnabled, like_daily_max: local.likeDailyMax,
        like_min_delay: local.likeMinDelay, like_max_delay: local.likeMaxDelay,
        like_source: local.likeSource, like_source_target: local.likeSourceTarget,
        like_min_per_op: local.likeMinPerOp, like_max_per_op: local.likeMaxPerOp,
        like_min_post_likes: local.likeMinPostLikes, like_max_post_likes: local.likeMaxPostLikes,
        like_min_poster_followers: local.likeMinPosterFollowers, like_skip_videos: local.likeSkipVideos,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <SectionCard title="Like settings">
        <Toggle checked={local.likeEnabled} onChange={(v) => set({ likeEnabled: v })}
          label="Enable like" sublabel="Automatically like posts from target source" />
      </SectionCard>

      <SectionCard title="Like source">
        <RadioGroup<"hashtag" | "feed" | "profile">
          value={local.likeSource}
          onChange={(v) => set({ likeSource: v })}
          options={[
            { value: "hashtag", label: "Hashtag feed",  description: "Like posts under a target hashtag" },
            { value: "feed",    label: "Home feed",     description: "Like posts from your current following feed" },
            { value: "profile", label: "User profile",  description: "Like posts from a specific user's profile" },
          ]}
        />
        {local.likeSource !== "feed" && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] uppercase tracking-wider text-phantom-ghost">
                {local.likeSource === "hashtag" ? "Hashtags" : "Usernames"} — one per line
              </label>
              <span className="text-[10px] text-phantom-ghost/40 font-mono">
                {local.likeSourceTarget.split("\n").filter(Boolean).length} targets
              </span>
            </div>
            <textarea
              value={local.likeSourceTarget}
              onChange={(e) => set({ likeSourceTarget: e.target.value })}
              rows={10}
              placeholder={local.likeSource === "hashtag" ? "#fitness\n#bodybuilding\n#gymlife\n(add as many as needed)" : "@username1\n@username2\n(add as many as needed)"}
              className="w-full px-3 py-2.5 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/30 focus:outline-none focus:border-phantom-accent/50 transition-colors font-mono resize-y min-h-[140px]"
            />
          </div>
        )}
      </SectionCard>

      <SectionCard title="Limits">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          <NumInput value={local.likeMinPerOp}   onChange={(v) => set({ likeMinPerOp: v })}   label="Min / operation" unit="likes" min={1} />
          <NumInput value={local.likeMaxPerOp}   onChange={(v) => set({ likeMaxPerOp: v })}   label="Max / operation" unit="likes" min={1} />
          <NumInput value={local.likeDailyMax}   onChange={(v) => set({ likeDailyMax: v })}   label="Daily max"       unit="likes" min={0} />
          <div />
          <NumInput value={local.likeMinDelay}   onChange={(v) => set({ likeMinDelay: v })}   label="Min delay"       unit="sec" min={0} />
          <NumInput value={local.likeMaxDelay}   onChange={(v) => set({ likeMaxDelay: v })}   label="Max delay"       unit="sec" min={0} />
        </div>
      </SectionCard>

      <SectionCard title="Post filters" collapsible>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-5 mb-4">
          <NumInput value={local.likeMinPostLikes}        onChange={(v) => set({ likeMinPostLikes: v })}        label="Min post likes" min={0} />
          <NumInput value={local.likeMaxPostLikes}        onChange={(v) => set({ likeMaxPostLikes: v })}        label="Max post likes" min={0} />
          <NumInput value={local.likeMinPosterFollowers}  onChange={(v) => set({ likeMinPosterFollowers: v })}  label="Min poster followers" min={0} />
        </div>
        <Checkbox checked={local.likeSkipVideos} onChange={(v) => set({ likeSkipVideos: v })} label="Skip video posts (Reels)" />
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save like settings" />
    </div>
  );
}

// ─── Comment tab ─────────────────────────────────────────────────────────────

function CommentTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        comment_enabled: local.commentEnabled, comment_daily_max: local.commentDailyMax,
        comment_source: local.commentSource, comment_source_target: local.commentSourceTarget,
        comment_templates: local.commentTemplates,
        comment_ai: local.commentAI, comment_min_per_op: local.commentMinPerOp,
        comment_max_per_op: local.commentMaxPerOp, comment_min_delay: local.commentMinDelay,
        comment_max_delay: local.commentMaxDelay,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <SectionCard title="Comment settings">
        <Toggle checked={local.commentEnabled} onChange={(v) => set({ commentEnabled: v })}
          label="Enable comment" sublabel="Post comments on target posts" />
      </SectionCard>

      <SectionCard title="Comment source">
        <RadioGroup<"hashtag" | "feed">
          value={local.commentSource}
          onChange={(v) => set({ commentSource: v })}
          options={[
            { value: "hashtag", label: "Hashtag feed", description: "Comment on posts under a target hashtag" },
            { value: "feed",    label: "Home feed",    description: "Comment on posts from your current following feed" },
          ]}
        />
        {local.commentSource === "hashtag" && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] uppercase tracking-wider text-phantom-ghost">Hashtags — one per line</label>
              <span className="text-[10px] text-phantom-ghost/40 font-mono">
                {local.commentSourceTarget.split("\n").filter(Boolean).length} targets
              </span>
            </div>
            <textarea
              value={local.commentSourceTarget}
              onChange={(e) => set({ commentSourceTarget: e.target.value })}
              rows={8}
              placeholder={"#fitness\n#bodybuilding\n#gymlife\n(add as many as needed)"}
              className="w-full px-3 py-2.5 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/30 focus:outline-none focus:border-phantom-accent/50 transition-colors font-mono resize-y min-h-[120px]"
            />
          </div>
        )}
      </SectionCard>

      <SectionCard title="Comment templates">
        <p className="text-xs text-phantom-ghost/60 mb-3">One comment per line. The bot picks a random one each time.</p>
        <TextareaInput
          value={local.commentTemplates}
          onChange={(v) => set({ commentTemplates: v })}
          placeholder={"Love this! 🔥\nAmazing content!\nKeep grinding! 💪"}
          rows={6}
        />
        <div className="mt-3 flex items-center justify-between">
          <span className="text-[11px] text-phantom-ghost/50">
            {local.commentTemplates.split("\n").filter(Boolean).length} template{local.commentTemplates.split("\n").filter(Boolean).length !== 1 ? "s" : ""}
          </span>
          <Toggle checked={local.commentAI} onChange={(v) => set({ commentAI: v })} label="AI variations" />
        </div>
        {local.commentAI && (
          <p className="mt-2 text-[11px] text-phantom-accent/70">
            AI will generate unique variations of your templates using Claude, keeping tone and intent intact.
          </p>
        )}
      </SectionCard>

      <SectionCard title="Limits">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          <NumInput value={local.commentMinPerOp}  onChange={(v) => set({ commentMinPerOp: v })}  label="Min / operation" unit="comments" min={1} />
          <NumInput value={local.commentMaxPerOp}  onChange={(v) => set({ commentMaxPerOp: v })}  label="Max / operation" unit="comments" min={1} />
          <NumInput value={local.commentDailyMax}  onChange={(v) => set({ commentDailyMax: v })}  label="Daily max"       unit="comments" min={0} />
          <div />
          <NumInput value={local.commentMinDelay}  onChange={(v) => set({ commentMinDelay: v })}  label="Min delay"       unit="sec" min={0} />
          <NumInput value={local.commentMaxDelay}  onChange={(v) => set({ commentMaxDelay: v })}  label="Max delay"       unit="sec" min={0} />
        </div>
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save comment settings" />
    </div>
  );
}

// ─── Story tab ────────────────────────────────────────────────────────────────

function StoryTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        story_enabled: local.storyEnabled, story_daily_max: local.storyDailyMax,
        story_source: local.storySource, story_min_per_op: local.storyMinPerOp,
        story_max_per_op: local.storyMaxPerOp, story_react: local.storyReact,
        story_reply: local.storyReply, story_like_after: local.storyLikeAfter,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <SectionCard title="Story settings">
        <Toggle checked={local.storyEnabled} onChange={(v) => set({ storyEnabled: v })}
          label="Enable story viewing" sublabel="Automatically view stories to boost visibility" />
      </SectionCard>

      <SectionCard title="Story source">
        <RadioGroup<"following" | "explore" | "hashtag">
          value={local.storySource}
          onChange={(v) => set({ storySource: v })}
          options={[
            { value: "following", label: "Following feed",  description: "View stories from accounts you follow" },
            { value: "explore",   label: "Explore / Reels", description: "View stories surfaced by the algorithm" },
            { value: "hashtag",   label: "Hashtag",         description: "View stories from a specific hashtag" },
          ]}
        />
      </SectionCard>

      <SectionCard title="Limits">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          <NumInput value={local.storyMinPerOp}  onChange={(v) => set({ storyMinPerOp: v })}  label="Min / operation" unit="stories" min={1} />
          <NumInput value={local.storyMaxPerOp}  onChange={(v) => set({ storyMaxPerOp: v })}  label="Max / operation" unit="stories" min={1} />
          <NumInput value={local.storyDailyMax}  onChange={(v) => set({ storyDailyMax: v })}  label="Daily max"       unit="stories" min={0} />
        </div>
      </SectionCard>

      <SectionCard title="Engagement options">
        <div className="space-y-3">
          <Checkbox checked={local.storyReact}      onChange={(v) => set({ storyReact: v })}      label="React to stories (❤️ 🔥 😍)" />
          <Checkbox checked={local.storyReply}      onChange={(v) => set({ storyReply: v })}      label="Reply to stories with a message" />
          <Checkbox checked={local.storyLikeAfter}  onChange={(v) => set({ storyLikeAfter: v })}  label="Like the post after viewing story" />
        </div>
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save story settings" />
    </div>
  );
}

// ─── DM tab ───────────────────────────────────────────────────────────────────

function DMTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dm_enabled: local.dmEnabled, dm_daily_max: local.dmDailyMax,
        dm_source: local.dmSource, dm_templates: local.dmTemplates,
        dm_min_per_op: local.dmMinPerOp, dm_max_per_op: local.dmMaxPerOp,
        dm_min_delay: local.dmMinDelay, dm_max_delay: local.dmMaxDelay,
        dm_track_replies: local.dmTrackReplies,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <SectionCard title="DM settings">
        <Toggle checked={local.dmEnabled} onChange={(v) => set({ dmEnabled: v })}
          label="Enable DM" sublabel="Send direct messages to target users" />
      </SectionCard>

      <SectionCard title="DM target">
        <RadioGroup<"recent_followers" | "following" | "tags">
          value={local.dmSource}
          onChange={(v) => set({ dmSource: v })}
          options={[
            { value: "recent_followers", label: "Recent followers",  description: "DM users who recently followed this account" },
            { value: "following",        label: "My following",      description: "DM users this account is following" },
            { value: "tags",             label: "From tag list",     description: "DM users scraped from your tag sources" },
          ]}
        />
      </SectionCard>

      <SectionCard title="Message templates">
        <p className="text-xs text-phantom-ghost/60 mb-3">
          One message per line. Use <code className="text-phantom-accent bg-phantom-accent/10 px-1 rounded">{"{username}"}</code> to personalise.
        </p>
        <TextareaInput
          value={local.dmTemplates}
          onChange={(v) => set({ dmTemplates: v })}
          placeholder={"Hey {username}! Thanks for connecting 🙌\nHi {username}, love your content!"}
          rows={5}
        />
        <div className="mt-2 text-[11px] text-phantom-ghost/50">
          {local.dmTemplates.split("\n").filter(Boolean).length} template{local.dmTemplates.split("\n").filter(Boolean).length !== 1 ? "s" : ""}
        </div>
      </SectionCard>

      <SectionCard title="Limits">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          <NumInput value={local.dmMinPerOp}  onChange={(v) => set({ dmMinPerOp: v })}  label="Min / operation" unit="DMs" min={1} />
          <NumInput value={local.dmMaxPerOp}  onChange={(v) => set({ dmMaxPerOp: v })}  label="Max / operation" unit="DMs" min={1} />
          <NumInput value={local.dmDailyMax}  onChange={(v) => set({ dmDailyMax: v })}  label="Daily max"       unit="DMs" min={0} />
          <div />
          <NumInput value={local.dmMinDelay}  onChange={(v) => set({ dmMinDelay: v })}  label="Min delay"       unit="sec" min={0} />
          <NumInput value={local.dmMaxDelay}  onChange={(v) => set({ dmMaxDelay: v })}  label="Max delay"       unit="sec" min={0} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <Checkbox checked={local.dmTrackReplies} onChange={(v) => set({ dmTrackReplies: v })} label="Track reply rate — log which accounts replied" />
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save DM settings" />
    </div>
  );
}

// ─── Stub for Post / Reels / Share ────────────────────────────────────────────

// ─── Targets tab ─────────────────────────────────────────────────────────────

type TargetEntry = { id: string; username: string; source: string; addedAt: string };

function TargetsTab({ accountId }: { accountId: string }) {
  const [targets, setTargets]         = useState<TargetEntry[]>([
    { id: "t1",  username: "@fitnessmotivation",   source: "manual",    addedAt: "2026-04-12" },
    { id: "t2",  username: "@gymlife_official",    source: "ai_agent",  addedAt: "2026-04-13" },
    { id: "t3",  username: "@calisthenics_pros",   source: "ai_agent",  addedAt: "2026-04-13" },
    { id: "t4",  username: "@mensphysique_ig",     source: "ai_agent",  addedAt: "2026-04-13" },
    { id: "t5",  username: "@alphamindset",        source: "manual",    addedAt: "2026-04-11" },
    { id: "t6",  username: "@iron_brotherhood",    source: "ai_agent",  addedAt: "2026-04-13" },
    { id: "t7",  username: "@aestheticphysique",   source: "ai_agent",  addedAt: "2026-04-13" },
    { id: "t8",  username: "@grindsetcoach",       source: "ai_agent",  addedAt: "2026-04-13" },
    { id: "t9",  username: "@muscleandminds",      source: "ai_agent",  addedAt: "2026-04-13" },
    { id: "t10", username: "@fitdad_official",     source: "ai_agent",  addedAt: "2026-04-13" },
  ]);
  const [newTarget, setNewTarget]     = useState("");
  const [scraping, setScraping]       = useState(false);
  const [scrapeMsg, setScrapeMsg]     = useState("");
  const [niches, setNiches]           = useState("fitness, gym, bodybuilding, men's lifestyle");
  const [minFollowers, setMinFollowers] = useState(5000);
  const [maxFollowers, setMaxFollowers] = useState(500000);
  const [autoRefill, setAutoRefill]   = useState(true);
  const [refillThreshold, setRefillThreshold] = useState(10);

  const addTarget = () => {
    const raw = newTarget.trim().replace(/^@/, "");
    if (!raw) return;
    const entry: TargetEntry = { id: `t_${Date.now()}`, username: `@${raw}`, source: "manual", addedAt: new Date().toISOString().slice(0, 10) };
    setTargets((p) => [...p, entry]);
    fetch(`http://localhost:8001/api/accounts/${accountId}/targets`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: raw }),
    }).catch(() => {});
    setNewTarget("");
  };

  const removeTarget = (id: string) => {
    setTargets((p) => p.filter((t) => t.id !== id));
    fetch(`http://localhost:8001/api/accounts/${accountId}/targets/${id}`, { method: "DELETE" }).catch(() => {});
  };

  const handleAIScrape = async () => {
    setScraping(true); setScrapeMsg("");
    try {
      const res = await fetch(`http://localhost:8001/api/accounts/${accountId}/targets/ai-scrape`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ niches, min_followers: minFollowers, max_followers: maxFollowers, count: 50 }),
      });
      const d = await res.json();
      if (d.targets?.length) {
        const newEntries: TargetEntry[] = d.targets.map((u: string, i: number) => ({
          id: `ai_${Date.now()}_${i}`, username: u.startsWith("@") ? u : `@${u}`,
          source: "ai_agent", addedAt: new Date().toISOString().slice(0, 10),
        }));
        setTargets((p) => [...p, ...newEntries]);
        setScrapeMsg(`AI agent added ${newEntries.length} new targets`);
      } else {
        setScrapeMsg(d.message ?? "Agent is running — targets will appear shortly");
      }
    } catch { setScrapeMsg("Backend offline — agent queued for next run"); }
    finally { setScraping(false); }
  };

  return (
    <div className="space-y-5">
      {/* Intro */}
      <div className="phantom-panel p-5 border-l-2 border-phantom-accent">
        <div className="flex items-start gap-3">
          <Bot className="w-5 h-5 text-phantom-accent mt-0.5 shrink-0" strokeWidth={1.5} />
          <div>
            <div className="text-sm font-medium text-white mb-1">AI-Powered Target Discovery</div>
            <p className="text-xs text-phantom-ghost/70 leading-relaxed">
              Targets are the source accounts whose followers this account will engage with (follow, like, story view, DM).
              The AI agent automatically discovers high-quality male accounts in your niche and keeps the target list topped up — zero manual work.
            </p>
          </div>
        </div>
      </div>

      {/* AI Scrape config */}
      <SectionCard title="AI agent · auto-discover targets">
        <div className="space-y-4">
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-phantom-ghost mb-1.5">Niche keywords</label>
            <input value={niches} onChange={(e) => setNiches(e.target.value)}
              placeholder="fitness, gym, bodybuilding, men's lifestyle"
              className="w-full px-3 py-2 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 transition-colors" />
            <p className="mt-1 text-[11px] text-phantom-ghost/50">Comma-separated keywords. The agent finds top accounts in these niches.</p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
            <NumInput value={minFollowers} onChange={setMinFollowers} label="Min followers" min={0} />
            <NumInput value={maxFollowers} onChange={setMaxFollowers} label="Max followers" min={0} />
          </div>
          <div className="pt-2 space-y-3">
            <div className="flex items-start gap-3">
              <Toggle checked={autoRefill} onChange={setAutoRefill}
                label="Auto-refill targets"
                sublabel="Agent checks daily and adds new targets when list drops below threshold" />
            </div>
            {autoRefill && (
              <div className="ml-12">
                <NumInput value={refillThreshold} onChange={setRefillThreshold} label="Refill when below" unit="targets" min={1} />
              </div>
            )}
          </div>
          <div className="flex items-center gap-3 pt-2 flex-wrap">
            <button onClick={handleAIScrape} disabled={scraping}
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium bg-phantom-accent text-phantom-bg hover:bg-phantom-accent/90 disabled:opacity-60 transition-colors font-semibold">
              <Bot className={cn("w-4 h-4", scraping && "animate-pulse")} strokeWidth={1.75} />
              {scraping ? "Agent scraping…" : "Run AI Agent Now"}
            </button>
            {scrapeMsg && (
              <span className="text-xs px-3 py-1.5 rounded-lg border text-phantom-accent bg-phantom-accent/10 border-phantom-accent/25">{scrapeMsg}</span>
            )}
          </div>
        </div>
      </SectionCard>

      {/* Bulk import */}
      <SectionCard title="Bulk import targets">
        <p className="text-xs text-phantom-ghost/60 mb-3">Paste thousands of usernames at once — one per line. Great for importing scraped lists.</p>
        <div className="space-y-3">
          <textarea
            value={newTarget}
            onChange={(e) => setNewTarget(e.target.value)}
            rows={8}
            placeholder={"@fitnessguru\n@gymrat_mike\n@ironmindset\n@alphacoach\n...\n(paste 1000s of usernames here, one per line)"}
            className="w-full px-3 py-2.5 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/30 focus:outline-none focus:border-phantom-accent/50 transition-colors font-mono resize-y min-h-[160px]"
          />
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-phantom-ghost/50">
              {newTarget.split("\n").filter((l) => l.trim()).length} usernames ready to import
            </span>
            <button
              onClick={() => {
                const lines = newTarget.split("\n").filter((l) => l.trim());
                const newEntries: TargetEntry[] = lines.map((line, i) => {
                  const raw = line.trim().replace(/^@/, "");
                  return { id: `bulk_${Date.now()}_${i}`, username: `@${raw}`, source: "manual", addedAt: new Date().toISOString().slice(0, 10) };
                });
                setTargets((p) => {
                  const existing = new Set(p.map((t) => t.username));
                  return [...p, ...newEntries.filter((e) => !existing.has(e.username))];
                });
                newEntries.forEach((e) => {
                  fetch(`http://localhost:8001/api/accounts/${accountId}/targets`, {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username: e.username.replace(/^@/, "") }),
                  }).catch(() => {});
                });
                setNewTarget("");
              }}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-phantom-panelHi text-white border border-phantom-border hover:bg-phantom-panelHi/80 transition-colors"
            >
              <Plus className="w-4 h-4" strokeWidth={2} />
              Import All
            </button>
          </div>
        </div>
      </SectionCard>

      {/* Target list */}
      <SectionCard title={`Target list · ${targets.length} source accounts`}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs text-phantom-ghost/60">
            The bot cycles through these source accounts and follows/engages with their followers. AI-discovered targets are marked in green.
          </p>
          <button
            onClick={() => { if (confirm(`Clear all ${targets.length} targets?`)) setTargets([]); }}
            className="text-[11px] text-phantom-ghost/40 hover:text-red-400 transition-colors px-2 py-1 rounded"
          >
            Clear all
          </button>
        </div>
        {targets.length === 0 ? (
          <div className="py-12 text-center text-phantom-ghost/40 text-sm">No targets yet — run the AI agent or bulk import above</div>
        ) : (
          <div className="overflow-y-auto max-h-[500px] space-y-0.5 -mx-1">
            {targets.map((t) => (
              <div key={t.id} className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-phantom-panelHi/40 transition-colors group">
                <div className="flex items-center gap-3">
                  <Target className="w-3.5 h-3.5 text-phantom-ghost/40 shrink-0" strokeWidth={1.5} />
                  <span className="font-mono text-sm text-white">{t.username}</span>
                  <span className={cn("text-[10px] px-2 py-0.5 rounded border font-mono",
                    t.source === "ai_agent"
                      ? "text-phantom-accent bg-phantom-accent/10 border-phantom-accent/25"
                      : "text-phantom-ghost bg-phantom-panelHi border-phantom-border")}>
                    {t.source === "ai_agent" ? "AI" : "manual"}
                  </span>
                  <span className="text-[10px] text-phantom-ghost/40">{t.addedAt}</span>
                </div>
                <button onClick={() => removeTarget(t.id)}
                  className="opacity-0 group-hover:opacity-100 p-1 rounded text-phantom-ghost hover:text-red-400 transition-all">
                  <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                </button>
              </div>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}

// ─── Post tab ─────────────────────────────────────────────────────────────────

function PostTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        post_enabled: local.postEnabled, post_source: local.postSource,
        post_source_path: local.postSourcePath, post_captions: local.postCaptions,
        post_hashtags: local.postHashtags, post_per_day: local.postPerDay,
        post_hours: local.postHours, post_type: local.postType,
        post_ai_captions: local.postAICaptions, post_watermark: local.postWatermark,
        post_min_delay: local.postMinDelay, post_max_delay: local.postMaxDelay,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <SectionCard title="Post settings">
        <Toggle checked={local.postEnabled} onChange={(v) => set({ postEnabled: v })}
          label="Enable auto-posting" sublabel="Automatically post content on a schedule" />
      </SectionCard>

      <SectionCard title="Content source">
        <RadioGroup<"content_vault" | "upload_folder" | "url">
          value={local.postSource}
          onChange={(v) => set({ postSource: v })}
          options={[
            { value: "content_vault",  label: "Content Vault",   description: "Pull posts from your Phantom Fleet Content Vault" },
            { value: "upload_folder",  label: "Upload Folder",   description: "Watch a local folder on the phone for new content" },
            { value: "url",            label: "URL / Drive link", description: "Fetch content from a Google Drive or CDN URL" },
          ]}
        />
        <div className="mt-4">
          <label className="block text-[10px] uppercase tracking-wider text-phantom-ghost mb-1.5">
            {local.postSource === "content_vault" ? "Vault path" : local.postSource === "upload_folder" ? "Folder path on device" : "Content URL"}
          </label>
          <TextInput value={local.postSourcePath} onChange={(v) => set({ postSourcePath: v })}
            placeholder={local.postSource === "url" ? "https://drive.google.com/..." : "/content/tatiannalifee"} />
        </div>
      </SectionCard>

      <SectionCard title="Post type">
        <RadioGroup<"image" | "carousel" | "video">
          value={local.postType}
          onChange={(v) => set({ postType: v })}
          options={[
            { value: "image",    label: "Single image",  description: "Post one photo" },
            { value: "carousel", label: "Carousel",      description: "Post 2–10 images as a swipeable album" },
            { value: "video",    label: "Video",         description: "Post a video (up to 60 seconds for feed)" },
          ]}
        />
      </SectionCard>

      <SectionCard title="Captions">
        <p className="text-xs text-phantom-ghost/60 mb-3">One caption per line — bot picks randomly. Use <code className="text-phantom-accent bg-phantom-accent/10 px-1 rounded">{"{username}"}</code> for personalisation.</p>
        <TextareaInput value={local.postCaptions} onChange={(v) => set({ postCaptions: v })}
          placeholder={"Living my best life ✨\nNew content dropping soon 🔥\nFollow for exclusive content 💋"} rows={6} />
        <div className="mt-3 flex items-center justify-between">
          <span className="text-[11px] text-phantom-ghost/50">
            {local.postCaptions.split("\n").filter(Boolean).length} caption{local.postCaptions.split("\n").filter(Boolean).length !== 1 ? "s" : ""}
          </span>
          <Toggle checked={local.postAICaptions} onChange={(v) => set({ postAICaptions: v })} label="AI caption variations" />
        </div>
      </SectionCard>

      <SectionCard title="Hashtags">
        <TextareaInput value={local.postHashtags} onChange={(v) => set({ postHashtags: v })}
          placeholder="#fitness #lifestyle #motivation #content" rows={3} />
        <p className="mt-2 text-[11px] text-phantom-ghost/50">Space-separated hashtags appended to every caption.</p>
      </SectionCard>

      <SectionCard title="Schedule">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5 mb-4">
          <NumInput value={local.postPerDay} onChange={(v) => set({ postPerDay: v })} label="Posts per day" min={1} max={10} />
          <NumInput value={Math.round(local.postMinDelay / 60)} onChange={(v) => set({ postMinDelay: v * 60 })} label="Min delay" unit="min" min={1} />
          <NumInput value={Math.round(local.postMaxDelay / 60)} onChange={(v) => set({ postMaxDelay: v * 60 })} label="Max delay" unit="min" min={1} />
        </div>
        <FieldRow label="Post at (hours)" hint="Comma-separated, 24h format">
          <TextInput value={local.postHours} onChange={(v) => set({ postHours: v })} placeholder="09:00, 14:00, 20:00" />
        </FieldRow>
      </SectionCard>

      <SectionCard title="Options">
        <div className="space-y-3">
          <Checkbox checked={local.postWatermark} onChange={(v) => set({ postWatermark: v })} label="Add watermark / username overlay before posting" />
        </div>
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save post settings" />
    </div>
  );
}

// ─── Reels tab ─────────────────────────────────────────────────────────────────

function ReelsTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  const handleSave = async () => {
    setSaving(true);
    await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reels_watch_enabled: local.reelsWatchEnabled, reels_watch_source: local.reelsWatchSource,
        reels_watch_target: local.reelsWatchTarget, reels_watch_min_per_op: local.reelsWatchMinPerOp,
        reels_watch_max_per_op: local.reelsWatchMaxPerOp, reels_watch_daily_max: local.reelsWatchDailyMax,
        reels_like_while_watching: local.reelsLikeWhileWatching,
        reels_comment_while_watching: local.reelsCommentWhileWatching,
        reels_save: local.reelsSave, reels_post_enabled: local.reelsPostEnabled,
        reels_post_source: local.reelsPostSource, reels_post_source_path: local.reelsPostSourcePath,
        reels_post_captions: local.reelsPostCaptions, reels_post_per_day: local.reelsPostPerDay,
        reels_post_ai_captions: local.reelsPostAICaptions,
      }),
    }).catch(() => {});
    onSave(local);
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      {/* Watch section */}
      <SectionCard title="Watch reels">
        <Toggle checked={local.reelsWatchEnabled} onChange={(v) => set({ reelsWatchEnabled: v })}
          label="Enable Reels watching" sublabel="Scroll and watch Reels to boost algorithmic reach" />
      </SectionCard>

      <SectionCard title="Watch source">
        <RadioGroup<"explore" | "following" | "hashtag">
          value={local.reelsWatchSource}
          onChange={(v) => set({ reelsWatchSource: v })}
          options={[
            { value: "explore",   label: "Explore / For You", description: "Watch Reels surfaced by the algorithm" },
            { value: "following", label: "Following feed",    description: "Watch Reels from accounts you follow" },
            { value: "hashtag",   label: "Hashtag",          description: "Watch Reels under a specific hashtag" },
          ]}
        />
        {local.reelsWatchSource === "hashtag" && (
          <div className="mt-4">
            <FieldRow label="Hashtag">
              <TextInput value={local.reelsWatchTarget} onChange={(v) => set({ reelsWatchTarget: v })} placeholder="#fitness" />
            </FieldRow>
          </div>
        )}
      </SectionCard>

      <SectionCard title="Watch limits">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          <NumInput value={local.reelsWatchMinPerOp}  onChange={(v) => set({ reelsWatchMinPerOp: v })}  label="Min / operation" unit="reels" min={1} />
          <NumInput value={local.reelsWatchMaxPerOp}  onChange={(v) => set({ reelsWatchMaxPerOp: v })}  label="Max / operation" unit="reels" min={1} />
          <NumInput value={local.reelsWatchDailyMax}  onChange={(v) => set({ reelsWatchDailyMax: v })}  label="Daily max"       unit="reels" min={0} />
        </div>
      </SectionCard>

      <SectionCard title="Watch engagement">
        <div className="space-y-3">
          <Checkbox checked={local.reelsLikeWhileWatching}    onChange={(v) => set({ reelsLikeWhileWatching: v })}    label="Like Reels while watching" />
          <Checkbox checked={local.reelsCommentWhileWatching} onChange={(v) => set({ reelsCommentWhileWatching: v })} label="Comment on Reels while watching" />
          <Checkbox checked={local.reelsSave}                 onChange={(v) => set({ reelsSave: v })}                 label="Save Reels to collection" />
        </div>
      </SectionCard>

      {/* Post Reels section */}
      <SectionCard title="Post reels" collapsible>
        <div className="mb-4">
          <Toggle checked={local.reelsPostEnabled} onChange={(v) => set({ reelsPostEnabled: v })}
            label="Enable Reels posting" sublabel="Auto-upload Reels from content source on a schedule" />
        </div>
        <div className={cn("space-y-5 transition-opacity", !local.reelsPostEnabled && "opacity-40 pointer-events-none")}>
          <RadioGroup<"content_vault" | "upload_folder">
            value={local.reelsPostSource}
            onChange={(v) => set({ reelsPostSource: v })}
            options={[
              { value: "content_vault", label: "Content Vault",  description: "Pull Reels from Phantom Fleet Content Vault" },
              { value: "upload_folder", label: "Upload Folder",  description: "Watch a folder on the phone for new Reels" },
            ]}
          />
          <FieldRow label="Source path">
            <TextInput value={local.reelsPostSourcePath} onChange={(v) => set({ reelsPostSourcePath: v })} placeholder="/reels/tatiannalifee" />
          </FieldRow>
          <div>
            <p className="text-xs text-phantom-ghost/60 mb-2">Captions — one per line, bot picks randomly:</p>
            <TextareaInput value={local.reelsPostCaptions} onChange={(v) => set({ reelsPostCaptions: v })}
              placeholder={"Watch till the end 🔥\nNew content every day 💫\nLink in bio 👆"} rows={4} />
            <div className="mt-2 flex items-center justify-between">
              <span className="text-[11px] text-phantom-ghost/50">
                {local.reelsPostCaptions.split("\n").filter(Boolean).length} captions
              </span>
              <Toggle checked={local.reelsPostAICaptions} onChange={(v) => set({ reelsPostAICaptions: v })} label="AI variations" />
            </div>
          </div>
          <NumInput value={local.reelsPostPerDay} onChange={(v) => set({ reelsPostPerDay: v })} label="Reels per day" min={1} max={10} />
        </div>
      </SectionCard>

      <SaveBar onSave={handleSave} saving={saving} label="Save Reels settings" />
    </div>
  );
}

// ─── Threads tab ──────────────────────────────────────────────────────────────

function ThreadsTab({ settings, onSave }: { settings: AccountSettings; onSave: (s: AccountSettings) => void }) {
  const [local, setLocal] = useState(settings);
  const set = (patch: Partial<AccountSettings>) => setLocal((p) => ({ ...p, ...patch }));

  // Threads-specific state (stored as JSON in a threads config field; we manage locally here)
  const [threadsEnabled, setThreadsEnabled] = useState(true);
  const [followEnabled, setFollowEnabled] = useState(true);
  const [followMinOp, setFollowMinOp] = useState(8);
  const [followMaxOp, setFollowMaxOp] = useState(20);
  const [followDailyMax, setFollowDailyMax] = useState(120);
  const [unfollowEnabled, setUnfollowEnabled] = useState(true);
  const [unfollowMinOp, setUnfollowMinOp] = useState(8);
  const [unfollowMaxOp, setUnfollowMaxOp] = useState(18);
  const [unfollowDailyMax, setUnfollowDailyMax] = useState(100);
  const [likeEnabled, setLikeEnabled] = useState(true);
  const [likeSource, setLikeSource] = useState<"following" | "hashtag" | "trending">("following");
  const [likeHashtags, setLikeHashtags] = useState("#fitness #lifestyle #motivation");
  const [likeDailyMax, setLikeDailyMax] = useState(200);
  const [replyEnabled, setReplyEnabled] = useState(true);
  const [replySource, setReplySource] = useState<"following" | "hashtag" | "trending">("trending");
  const [replyTemplates, setReplyTemplates] = useState("this is so real 😭\nnot me saving this immediately 🙌\nlowkey needed to hear this today\nthis 👆\nexactly what I've been thinking\nyou said what needed to be said 🙏\nnot enough people are talking about this");
  const [replyAI, setReplyAI] = useState(true);
  const [replyDailyMax, setReplyDailyMax] = useState(60);
  const [repostEnabled, setRepostEnabled] = useState(false);
  const [repostSource, setRepostSource] = useState<"following" | "hashtag">("following");
  const [repostDailyMax, setRepostDailyMax] = useState(30);
  const [quoteEnabled, setQuoteEnabled] = useState(false);
  const [quoteTemplates, setQuoteTemplates] = useState("this 👆\nsay it louder 🙏\nnot enough people are talking about this\nexactly what I needed to see today");
  const [postEnabled, setPostEnabled] = useState(false);
  const [postTemplates, setPostTemplates] = useState("");
  const [postPerDay, setPostPerDay] = useState(2);
  const [postAI, setPostAI] = useState(true);
  const [timeSlot, setTimeSlot] = useState<"morning" | "afternoon" | "evening" | "night">("afternoon");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    onSave(local);
    try {
      await fetch(`http://localhost:8001/api/accounts/${local.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threads_config: { threadsEnabled, followEnabled, followMinOp, followMaxOp, followDailyMax, unfollowEnabled, unfollowMinOp, unfollowMaxOp, unfollowDailyMax, likeEnabled, likeSource, likeHashtags, likeDailyMax, replyEnabled, replySource, replyTemplates, replyAI, replyDailyMax, repostEnabled, repostSource, repostDailyMax, quoteEnabled, quoteTemplates, postEnabled, postTemplates, postPerDay, postAI, timeSlot } }),
      });
    } catch {}
    setSaving(false);
  }

  return (
    <div className="space-y-5">
      {/* Master enable + time-slot */}
      <SectionCard title="Threads Configuration">
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-white">Enable Threads automation</div>
              <div className="text-[11px] text-phantom-ghost mt-0.5">Run Threads actions alongside Instagram on this account</div>
            </div>
            <Toggle checked={threadsEnabled} onChange={setThreadsEnabled} label="" />
          </div>
          {threadsEnabled && (
            <div className="space-y-2 pt-2 border-t border-phantom-border/50">
              <label className="text-[10px] uppercase tracking-wider text-phantom-ghost">Activity Time Slot</label>
              <div className="grid grid-cols-4 gap-2">
                {(["morning","afternoon","evening","night"] as const).map((s) => (
                  <button key={s} onClick={() => setTimeSlot(s)} className={cn("py-2 rounded-lg text-xs font-medium border transition-colors capitalize", timeSlot === s ? "bg-phantom-magenta/20 border-phantom-magenta/50 text-phantom-magenta" : "bg-phantom-bg border-phantom-border text-phantom-ghost hover:text-white")}>
                    {s === "morning" ? "🌅 Morning" : s === "afternoon" ? "☀️ Afternoon" : s === "evening" ? "🌆 Evening" : "🌙 Night"}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-phantom-ghost/60">Threads runs in this window — Instagram runs in the opposite window to avoid simultaneous activity on the same account.</p>
            </div>
          )}
        </div>
      </SectionCard>

      {threadsEnabled && <>
        {/* Follow */}
        <SectionCard title="Follow">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Enable following</span>
              <Toggle checked={followEnabled} onChange={setFollowEnabled} label="" />
            </div>
            {followEnabled && (
              <div className="grid grid-cols-3 gap-4">
                <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Min / Op</label><NumInput value={followMinOp} onChange={setFollowMinOp} min={1} max={50} /></div>
                <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Max / Op</label><NumInput value={followMaxOp} onChange={setFollowMaxOp} min={1} max={50} /></div>
                <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Daily Max</label><NumInput value={followDailyMax} onChange={setFollowDailyMax} min={10} max={500} /></div>
              </div>
            )}
          </div>
        </SectionCard>

        {/* Unfollow */}
        <SectionCard title="Unfollow">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Enable unfollowing</span>
              <Toggle checked={unfollowEnabled} onChange={setUnfollowEnabled} label="" />
            </div>
            {unfollowEnabled && (
              <div className="grid grid-cols-3 gap-4">
                <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Min / Op</label><NumInput value={unfollowMinOp} onChange={setUnfollowMinOp} min={1} max={50} /></div>
                <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Max / Op</label><NumInput value={unfollowMaxOp} onChange={setUnfollowMaxOp} min={1} max={50} /></div>
                <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Daily Max</label><NumInput value={unfollowDailyMax} onChange={setUnfollowDailyMax} min={10} max={500} /></div>
              </div>
            )}
          </div>
        </SectionCard>

        {/* Like */}
        <SectionCard title="Like Threads">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Enable liking</span>
              <Toggle checked={likeEnabled} onChange={setLikeEnabled} label="" />
            </div>
            {likeEnabled && <>
              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-wider text-phantom-ghost">Like Source</label>
                <div className="grid grid-cols-3 gap-2">
                  {(["following","hashtag","trending"] as const).map((s) => (
                    <button key={s} onClick={() => setLikeSource(s)} className={cn("py-2 rounded-lg text-xs font-medium border transition-colors capitalize", likeSource === s ? "bg-phantom-accent/20 border-phantom-accent/50 text-phantom-accent" : "bg-phantom-bg border-phantom-border text-phantom-ghost hover:text-white")}>
                      {s === "following" ? "Following Feed" : s === "hashtag" ? "Hashtag" : "Trending"}
                    </button>
                  ))}
                </div>
              </div>
              {likeSource === "hashtag" && (
                <div>
                  <label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Hashtags</label>
                  <TextInput value={likeHashtags} onChange={setLikeHashtags} placeholder="#fitness #lifestyle" />
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Daily Max</label><NumInput value={likeDailyMax} onChange={setLikeDailyMax} min={10} max={500} /></div>
              </div>
            </>}
          </div>
        </SectionCard>

        {/* Reply */}
        <SectionCard title="Reply to Threads">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Enable replies</span>
              <Toggle checked={replyEnabled} onChange={setReplyEnabled} label="" />
            </div>
            {replyEnabled && <>
              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-wider text-phantom-ghost">Reply Source</label>
                <div className="grid grid-cols-3 gap-2">
                  {(["following","hashtag","trending"] as const).map((s) => (
                    <button key={s} onClick={() => setReplySource(s)} className={cn("py-2 rounded-lg text-xs font-medium border transition-colors capitalize", replySource === s ? "bg-phantom-accent/20 border-phantom-accent/50 text-phantom-accent" : "bg-phantom-bg border-phantom-border text-phantom-ghost hover:text-white")}>
                      {s === "following" ? "Following Feed" : s === "hashtag" ? "Hashtag" : "Trending"}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Reply Templates (one per line)</label>
                <textarea value={replyTemplates} onChange={(e) => setReplyTemplates(e.target.value)} rows={7} className="w-full px-3 py-2.5 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 resize-y min-h-[120px]" placeholder={"this is so real 😭\nnot me saving this 🙌\nlowkey needed to hear this"} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">AI reply variations</div>
                  <div className="text-[11px] text-phantom-ghost">Generate natural variants to avoid pattern detection</div>
                </div>
                <Toggle checked={replyAI} onChange={setReplyAI} label="" />
              </div>
              <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Daily Max Replies</label><NumInput value={replyDailyMax} onChange={setReplyDailyMax} min={5} max={200} /></div>
            </>}
          </div>
        </SectionCard>

        {/* Repost */}
        <SectionCard title="Repost Threads" collapsible>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Enable reposts</span>
              <Toggle checked={repostEnabled} onChange={setRepostEnabled} label="" />
            </div>
            {repostEnabled && <>
              <div className="space-y-2">
                <label className="text-[10px] uppercase tracking-wider text-phantom-ghost">Repost Source</label>
                <div className="grid grid-cols-2 gap-2">
                  {(["following","hashtag"] as const).map((s) => (
                    <button key={s} onClick={() => setRepostSource(s)} className={cn("py-2 rounded-lg text-xs font-medium border transition-colors", repostSource === s ? "bg-phantom-accent/20 border-phantom-accent/50 text-phantom-accent" : "bg-phantom-bg border-phantom-border text-phantom-ghost hover:text-white")}>
                      {s === "following" ? "Following Feed" : "Hashtag"}
                    </button>
                  ))}
                </div>
              </div>
              <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Daily Max Reposts</label><NumInput value={repostDailyMax} onChange={setRepostDailyMax} min={5} max={100} /></div>
            </>}
          </div>
        </SectionCard>

        {/* Quote */}
        <SectionCard title="Quote Threads" collapsible>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Enable quote reposts</span>
              <Toggle checked={quoteEnabled} onChange={setQuoteEnabled} label="" />
            </div>
            {quoteEnabled && (
              <div>
                <label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Quote Templates (one per line)</label>
                <textarea value={quoteTemplates} onChange={(e) => setQuoteTemplates(e.target.value)} rows={5} className="w-full px-3 py-2.5 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 resize-y min-h-[100px]" />
              </div>
            )}
          </div>
        </SectionCard>

        {/* Post */}
        <SectionCard title="Post New Threads" collapsible>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Enable auto-posting</span>
              <Toggle checked={postEnabled} onChange={setPostEnabled} label="" />
            </div>
            {postEnabled && <>
              <div>
                <label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Thread Templates (one per line)</label>
                <textarea value={postTemplates} onChange={(e) => setPostTemplates(e.target.value)} rows={8} className="w-full px-3 py-2.5 rounded-lg bg-phantom-bg border border-phantom-border text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 resize-y min-h-[140px]" placeholder={"not me falling for someone who doesn't even know I exist 🙈\nthis is your sign to stop waiting and start doing 🔥\nthe right person won't need convincing 💌"} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-white">AI thread generation</div>
                  <div className="text-[11px] text-phantom-ghost">Generate varied, natural-sounding threads from templates</div>
                </div>
                <Toggle checked={postAI} onChange={setPostAI} label="" />
              </div>
              <div><label className="text-[10px] uppercase tracking-wider text-phantom-ghost block mb-1">Threads Per Day</label><NumInput value={postPerDay} onChange={setPostPerDay} min={1} max={10} /></div>
            </>}
          </div>
        </SectionCard>
      </>}

      {/* Save */}
      <div className="flex justify-end gap-3 pt-2">
        <button onClick={() => setLocal(settings)} className="px-4 py-2 rounded-lg border border-phantom-border text-phantom-ghost hover:text-white text-sm transition-colors">Cancel</button>
        <button onClick={save} disabled={saving} className="px-5 py-2 rounded-lg bg-phantom-magenta text-white text-sm font-semibold hover:opacity-90 disabled:opacity-50 transition-all">
          {saving ? "Saving…" : "Save Threads Settings"}
        </button>
      </div>
    </div>
  );
}

// ─── Share tab (stub) ─────────────────────────────────────────────────────────

function ComingSoonTab({ label }: { label: string }) {
  return (
    <div className="phantom-panel p-12 text-center">
      <div className="w-12 h-12 rounded-2xl bg-phantom-panelHi border border-phantom-border flex items-center justify-center mx-auto mb-4">
        <Zap className="w-6 h-6 text-phantom-ghost/40" strokeWidth={1.5} />
      </div>
      <div className="text-white font-medium">{label} — coming soon</div>
      <div className="text-xs text-phantom-ghost/40 mt-1">This module is in development</div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AccountSettingsPage({
  params,
}: {
  params: Promise<{ serial: string; account_id: string }>;
}) {
  const { serial, account_id } = use(params);
  const [settings, setSettings] = useState(() => buildDemo(account_id));
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  useEffect(() => {
    fetch(`http://localhost:8001/api/accounts/${account_id}`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => { if (d?.id) setSettings(d); })
      .catch(() => {});
  }, [account_id]);

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-phantom-ghost">
        <Link href="/fleet" className="hover:text-white transition-colors">Fleet</Link>
        <span>/</span>
        <Link href={`/fleet/${serial}`} className="hover:text-white transition-colors font-mono">{serial.slice(0, 10)}…</Link>
        <span>/</span>
        <span className="text-white">@{settings.username}</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">Account settings</div>
          <h1 className="font-display text-3xl font-bold mt-1 tracking-tight">@{settings.username}</h1>
          <div className="flex items-center gap-2 mt-1.5 text-xs text-phantom-ghost">
            <span className="font-mono">{serial}</span>
            <span>·</span>
            <span className={cn("px-2 py-0.5 rounded text-[10px] font-mono border",
              settings.loggedIn ? "text-green-400 border-green-400/25 bg-green-400/10" : "text-phantom-ghost border-phantom-border bg-phantom-panelHi")}>
              {settings.loggedIn ? "Session active" : "Logged out"}
            </span>
          </div>
        </div>
        <Link href={`/fleet/${serial}`} className="flex items-center gap-1.5 text-xs text-phantom-ghost hover:text-white transition-colors">
          <ChevronLeft className="w-3.5 h-3.5" /> Back to device
        </Link>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 overflow-x-auto pb-1 border-b border-phantom-border">
        {TABS.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={cn("flex items-center gap-1.5 px-3 py-2 rounded-t-lg text-xs font-medium whitespace-nowrap transition-colors border-b-2 -mb-px",
              activeTab === tab.id
                ? "text-phantom-accent border-phantom-accent bg-phantom-accent/5"
                : "text-phantom-ghost border-transparent hover:text-white hover:bg-phantom-panelHi")}>
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {activeTab === "overview" && <OverviewTab settings={settings} serial={serial} onSave={setSettings} />}
        {activeTab === "timer"    && <TimerTab    settings={settings} onSave={setSettings} />}
        {activeTab === "targets"  && <TargetsTab  accountId={account_id} />}
        {activeTab === "follow"   && <FollowTab   settings={settings} onSave={setSettings} />}
        {activeTab === "unfollow" && <UnfollowTab settings={settings} onSave={setSettings} />}
        {activeTab === "like"     && <LikeTab     settings={settings} onSave={setSettings} />}
        {activeTab === "comment"  && <CommentTab  settings={settings} onSave={setSettings} />}
        {activeTab === "story"    && <StoryTab    settings={settings} onSave={setSettings} />}
        {activeTab === "dm"       && <DMTab       settings={settings} onSave={setSettings} />}
        {activeTab === "post"     && <PostTab   settings={settings} onSave={setSettings} />}
        {activeTab === "reels"    && <ReelsTab  settings={settings} onSave={setSettings} />}
        {activeTab === "share"    && <ComingSoonTab label="Share" />}
        {activeTab === "threads"  && <ThreadsTab   settings={settings} onSave={setSettings} />}
      </div>
    </div>
  );
}
