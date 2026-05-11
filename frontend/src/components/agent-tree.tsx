"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { ChatTierBadge, type ChatTier } from "@/components/chat-tier-badge";
import { PlatformBadge, type Platform } from "@/components/platform-badge";
import {
  ChevronRight,
  Bot,
  Shield,
  Zap,
  DollarSign,
  Clock,
  Activity,
  Settings,
  AlertTriangle,
} from "lucide-react";

export type AgentStatus = "idle" | "running" | "error";

export type SpecialistAgent = {
  name: string;
  role: string;
  status: AgentStatus;
  lastRun: string;
  costToday: number;
  loopCap: number;
  toolsAllowed: string[];
};

export type PlatformManager = {
  name: string;
  platform: Platform | null;
  status: AgentStatus;
  lastRun: string;
  costToday: number;
  maxIterations: number;
  maxUsd: number;
  chatTier: ChatTier | null;
  supervisedAgents: SpecialistAgent[];
};

export type ChiefAgent = {
  name: string;
  status: AgentStatus;
  lastRun: string;
  costToday: number;
  managers: PlatformManager[];
};

const STATUS_DOT: Record<AgentStatus, string> = {
  idle: "bg-phantom-ghost/40",
  running: "phantom-dot-accent animate-phantom-pulse",
  error: "phantom-dot-critical",
};

const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: "IDLE",
  running: "RUNNING",
  error: "ERROR",
};

const STATUS_TEXT: Record<AgentStatus, string> = {
  idle: "text-phantom-ghost",
  running: "text-phantom-accent",
  error: "text-phantom-red",
};

function SpecialistRow({ agent }: { agent: SpecialistAgent }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-md hover:bg-phantom-panelHi/30 transition-colors">
      <span className={cn("phantom-dot shrink-0", STATUS_DOT[agent.status])} />
      <div className="flex-1 min-w-0">
        <div className="font-mono text-[11px] text-white">{agent.name}</div>
        <div className="text-[10px] text-phantom-ghost truncate">{agent.role}</div>
      </div>
      <div className="flex items-center gap-3 shrink-0 text-[10px] text-phantom-ghost">
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {agent.lastRun}
        </span>
        <span className="font-mono text-phantom-accent w-10 text-right">
          ${agent.costToday.toFixed(2)}
        </span>
        <span
          className={cn(
            "font-mono text-[9px] tracking-wider",
            STATUS_TEXT[agent.status]
          )}
        >
          {STATUS_LABEL[agent.status]}
        </span>
      </div>
    </div>
  );
}

function ManagerCard({
  manager,
  isSelected,
  onClick,
}: {
  manager: PlatformManager;
  isSelected: boolean;
  onClick: () => void;
}) {
  return (
    <div className="space-y-1">
      {/* Manager header row — clickable */}
      <button
        onClick={onClick}
        className={cn(
          "w-full flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-all duration-200",
          isSelected
            ? "bg-phantom-accent/8 border-phantom-accent/25 shadow-[0_0_12px_hsl(162_100%_54%/0.06)]"
            : "bg-phantom-panelHi/40 border-phantom-border hover:border-phantom-accent/15 hover:bg-phantom-panelHi/60"
        )}
      >
        {/* Status dot */}
        <span className={cn("phantom-dot shrink-0", STATUS_DOT[manager.status])} />

        {/* Platform badge or name */}
        <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
          {manager.platform ? (
            <PlatformBadge platform={manager.platform} size="xs" />
          ) : null}
          <span className="font-mono text-xs text-white">{manager.name}</span>
          {manager.chatTier && (
            <ChatTierBadge tier={manager.chatTier} size="xs" />
          )}
        </div>

        {/* Right side metrics */}
        <div className="flex items-center gap-3 shrink-0 text-[10px] text-phantom-ghost">
          <span className="hidden sm:flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {manager.lastRun}
          </span>
          <span className="font-mono text-phantom-accent">
            ${manager.costToday.toFixed(2)}
          </span>
          <span
            className={cn("font-mono text-[9px] tracking-wider", STATUS_TEXT[manager.status])}
          >
            {STATUS_LABEL[manager.status]}
          </span>
          <ChevronRight
            className={cn(
              "w-3.5 h-3.5 transition-transform duration-200",
              isSelected && "rotate-90"
            )}
          />
        </div>
      </button>

      {/* Expanded config + specialists */}
      {isSelected && (
        <div className="ml-4 pl-4 border-l border-phantom-accent/20 space-y-2">
          {/* Config strip */}
          <div className="flex items-center gap-4 px-3 py-2 text-[10px] text-phantom-ghost bg-phantom-bg/60 rounded-lg">
            <span className="flex items-center gap-1">
              <Activity className="w-3 h-3 text-phantom-accent" />
              max_iter: <span className="text-white font-mono">{manager.maxIterations}</span>
            </span>
            <span className="flex items-center gap-1">
              <DollarSign className="w-3 h-3 text-phantom-accent" />
              max_usd: <span className="text-white font-mono">${manager.maxUsd}</span>
            </span>
            <span className="flex items-center gap-1">
              <Bot className="w-3 h-3 text-phantom-accent" />
              specialists: <span className="text-white font-mono">{manager.supervisedAgents.length}</span>
            </span>
          </div>

          {/* Specialists */}
          <div className="space-y-0.5">
            {manager.supervisedAgents.map((s) => (
              <SpecialistRow key={s.name} agent={s} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function AgentTree({ chief }: { chief: ChiefAgent }) {
  const [selectedManager, setSelectedManager] = useState<string | null>(null);

  const totalCost = chief.managers.reduce((acc, m) => acc + m.costToday, 0);
  const runningCount = chief.managers.filter((m) => m.status === "running").length;
  const errorCount = chief.managers.filter((m) => m.status === "error").length;

  return (
    <div className="space-y-4">
      {/* Chief node */}
      <div className="phantom-panel-accent p-4 rounded-xl flex items-center gap-4">
        <div className="w-10 h-10 rounded-xl bg-phantom-accent/15 flex items-center justify-center border border-phantom-accent/30 shrink-0">
          <Shield className="w-5 h-5 text-phantom-accent" strokeWidth={1.75} />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className={cn("phantom-dot", STATUS_DOT[chief.status])} />
            <span className="font-display font-semibold text-sm">{chief.name}</span>
            <span className="text-[9px] font-mono tracking-wider text-phantom-accent bg-phantom-accent/10 px-1.5 py-0.5 rounded border border-phantom-accent/20">
              CHIEF
            </span>
          </div>
          <div className="text-[10px] text-phantom-ghost mt-0.5">
            Orchestrates {chief.managers.length} platform managers · last run {chief.lastRun}
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0 text-[10px]">
          {errorCount > 0 && (
            <span className="flex items-center gap-1 text-phantom-red">
              <AlertTriangle className="w-3 h-3" />
              {errorCount} errors
            </span>
          )}
          <span className="flex items-center gap-1 text-phantom-ghost">
            <Zap className="w-3 h-3 text-phantom-accent" />
            {runningCount} running
          </span>
          <span className="font-mono text-phantom-accent font-semibold">
            ${totalCost.toFixed(2)}/day
          </span>
        </div>
      </div>

      {/* Connector line */}
      <div className="flex justify-center">
        <div className="w-px h-4 bg-phantom-accent/20" />
      </div>

      {/* Manager nodes */}
      <div className="space-y-2">
        <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost px-1 mb-3 flex items-center gap-2">
          <Settings className="w-3 h-3" />
          Platform managers · {chief.managers.length} nodes
        </div>
        {chief.managers.map((manager) => (
          <ManagerCard
            key={manager.name}
            manager={manager}
            isSelected={selectedManager === manager.name}
            onClick={() =>
              setSelectedManager(
                selectedManager === manager.name ? null : manager.name
              )
            }
          />
        ))}
      </div>
    </div>
  );
}
