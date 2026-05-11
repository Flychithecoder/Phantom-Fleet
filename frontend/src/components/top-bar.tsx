"use client";

import { Search, Bell, Command } from "lucide-react";

export function TopBar() {
  return (
    <header className="h-16 border-b border-phantom-border bg-phantom-panel/40 backdrop-blur-xl sticky top-0 z-40 flex items-center justify-between px-8">
      {/* Left — live fleet stats ticker */}
      <div className="flex items-center gap-6 text-xs">
        <div className="flex items-center gap-2">
          <span className="phantom-dot phantom-dot-alive" />
          <span className="text-phantom-ghost">19 phones</span>
          <span className="text-white font-medium">online</span>
        </div>
        <div className="hidden md:flex items-center gap-2">
          <span className="text-phantom-ghost">Active accounts</span>
          <span className="text-white font-medium tabular-nums">219</span>
        </div>
        <div className="hidden lg:flex items-center gap-2">
          <span className="text-phantom-ghost">Agents</span>
          <span className="text-phantom-accent font-medium">14 running</span>
        </div>
        <div className="hidden xl:flex items-center gap-2">
          <span className="text-phantom-ghost">OF revenue (30d)</span>
          <span className="text-phantom-accent font-mono font-semibold">—</span>
        </div>
      </div>
      {/* Right — search + notifications */}
      <div className="flex items-center gap-3">
        <button className="flex items-center gap-2 px-3 h-9 rounded-lg bg-phantom-panelHi border border-phantom-border text-phantom-ghost text-sm hover:text-white transition-colors min-w-[260px]">
          <Search className="w-4 h-4" strokeWidth={1.75} />
          <span>Search accounts, personas, phones...</span>
          <span className="ml-auto flex items-center gap-1">
            <kbd className="phantom-kbd">⌘</kbd>
            <kbd className="phantom-kbd">K</kbd>
          </span>
        </button>
        <button className="relative w-9 h-9 rounded-lg bg-phantom-panelHi border border-phantom-border flex items-center justify-center text-phantom-ghost hover:text-white transition-colors">
          <Bell className="w-4 h-4" strokeWidth={1.75} />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-phantom-accent shadow-[0_0_8px_hsl(162_100%_54%)]" />
        </button>
      </div>
    </header>
  );
}
