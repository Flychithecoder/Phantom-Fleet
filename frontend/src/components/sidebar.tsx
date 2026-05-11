"use client";

import type { ElementType } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Smartphone, Users, Bot, Activity, Target, DollarSign,
  LineChart, Image as ImageIcon, ShieldAlert, Settings, CalendarDays, Gauge,
  Globe, Wand2, Vault, Brain, RotateCcw, MessageSquare, Network, Bookmark,
  Film, ArrowRight, Server, MessageCircle, Repeat2, Zap, Newspaper,
  TrendingUp, FlaskConical, Video, Flame, Heart, ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

type NavSection = {
  label: string;
  items: { href: string; label: string; icon: ElementType }[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Command",
    items: [
      { href: "/",          label: "Overview",       icon: LayoutDashboard },
      { href: "/briefing",  label: "Daily Briefing", icon: Newspaper },
      { href: "/fleet",     label: "Fleet",          icon: Smartphone },
      { href: "/onboarding",label: "Onboarding",     icon: Wand2 },
      { href: "/accounts",  label: "Accounts",       icon: Activity },
      { href: "/ops",       label: "Ops Brain",      icon: Brain },
      { href: "/agents",    label: "Agents",         icon: Bot },
      { href: "/schedule",  label: "Schedule",       icon: CalendarDays },
      { href: "/calendar",  label: "Content Calendar", icon: CalendarDays },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/personas",  label: "Personas",         icon: Users },
      { href: "/targets",   label: "Fresh Targets",    icon: Target },
      { href: "/cluster",   label: "Cluster Monitor",  icon: ShieldAlert },
      { href: "/analytics", label: "Analytics",        icon: LineChart },
      { href: "/capacity",  label: "Capacity Planner", icon: Gauge },
      { href: "/platforms", label: "Platforms",        icon: Globe },
      { href: "/pipeline",  label: "Gmail → Reddit",   icon: ArrowRight },
    ],
  },
  {
    label: "Instagram",
    items: [
      { href: "/ig/unfollow",  label: "Unfollow Engine", icon: RotateCcw },
      { href: "/ig/notes",     label: "IG Notes",        icon: MessageSquare },
      { href: "/ig/pods",      label: "Pod Network",     icon: Network },
      { href: "/ig/saves",     label: "Save Farming",    icon: Bookmark },
      { href: "/ig/reels",     label: "Reel Farming",    icon: Film },
      { href: "/ig/warmup",    label: "Warm-up Curves",  icon: TrendingUp },
      { href: "/ig/shadowban", label: "Shadowban Check", icon: ShieldCheck },
      { href: "/ig/abtest",    label: "A/B Testing",     icon: FlaskConical },
    ],
  },
  {
    label: "Threads",
    items: [
      { href: "/threads",          label: "Command Center",  icon: MessageCircle },
      { href: "/threads/replies",  label: "Reply Engine",    icon: MessageSquare },
      { href: "/threads/reposts",  label: "Repost Engine",   icon: Repeat2 },
      { href: "/threads/feed",     label: "Feed Engagement", icon: Zap },
      { href: "/threads/unfollow", label: "Unfollow Queue",  icon: RotateCcw },
    ],
  },
  {
    label: "TikTok",
    items: [
      { href: "/tiktok",          label: "Command Center",  icon: Video },
      { href: "/tiktok/warmup",   label: "Warm-up Queue",   icon: Flame },
      { href: "/tiktok/content",  label: "Content Schedule", icon: CalendarDays },
      { href: "/tiktok/geo",      label: "Geo Distribution", icon: Globe },
      { href: "/tiktok/unfollow", label: "Unfollow Engine",  icon: RotateCcw },
    ],
  },
  {
    label: "Dating",
    items: [
      { href: "/dating",              label: "Command Center",    icon: Heart },
      { href: "/dating/tinder",       label: "Tinder",            icon: Flame },
      { href: "/dating/bumble",       label: "Bumble",            icon: MessageCircle },
      { href: "/dating/verification", label: "Verification Queue", icon: ShieldCheck },
    ],
  },
  {
    label: "Revenue",
    items: [
      { href: "/funnel",        label: "Funnel",       icon: DollarSign },
      { href: "/content",       label: "Content Vault", icon: ImageIcon },
      { href: "/content-vault", label: "Media Bridge",  icon: Vault },
      { href: "/alerts",        label: "Alerts",        icon: ShieldAlert },
    ],
  },
  {
    label: "Infrastructure",
    items: [
      { href: "/proxy",   label: "Proxy Health",  icon: Globe },
      { href: "/s10-box", label: "S10 Male Box",  icon: Server },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-[240px] shrink-0 border-r border-phantom-border bg-phantom-panel/40 backdrop-blur-xl sticky top-0 h-screen flex flex-col">
      {/* Brand */}
      <div className="px-6 py-6 border-b border-phantom-border">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-8 h-8 rounded-md bg-gradient-accent flex items-center justify-center shadow-[0_0_24px_hsl(162_100%_54%/0.4)]">
            <span className="text-phantom-bg font-black text-sm">Φ</span>
          </div>
          <div className="flex flex-col">
            <span className="font-display font-bold tracking-tight text-sm leading-none">
              PHANTOM
              <span className="block text-phantom-ghost font-medium tracking-[0.2em] text-[9px] mt-0.5">FLEET</span>
            </span>
          </div>
        </Link>
      </div>
      {/* Nav */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost px-3 mb-1.5 font-medium">
              {section.label}
            </div>
            <ul className="space-y-0.5">
              {section.items.map(({ href, label, icon: Icon }) => {
                const active = href === "/" ? pathname === href : pathname === href || pathname.startsWith(href + "/");
                return (
                  <li key={href}>
                    <Link
                      href={href}
                      className={cn(
                        "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-200 group",
                        active
                          ? "bg-phantom-accent/10 text-phantom-accent border border-phantom-accent/20"
                          : "text-phantom-ghost hover:text-white hover:bg-phantom-panelHi/60 border border-transparent"
                      )}
                    >
                      <Icon className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                      <span className="font-medium">{label}</span>
                      {active && (
                        <span className="ml-auto phantom-dot phantom-dot-accent animate-phantom-pulse" />
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      {/* Footer */}
      <div className="px-4 py-4 border-t border-phantom-border">
        <div className="flex items-center justify-between text-[10px] text-phantom-ghost">
          <span>A Scaler Pro product</span>
          <span className="font-mono">v0.0.1</span>
        </div>
      </div>
    </aside>
  );
}
