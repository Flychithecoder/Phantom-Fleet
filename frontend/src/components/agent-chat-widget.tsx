"use client";

import { useState, useRef, useEffect } from "react";
import { Bot, X, Send, Minimize2 } from "lucide-react";

type Agent = "chief" | "instagram" | "tiktok" | "reddit" | "dating";

interface Message {
  id: string;
  role: "user" | "agent";
  text: string;
  ts: Date;
}

const AGENT_LABELS: Record<Agent, string> = {
  chief: "Chief",
  instagram: "Instagram",
  tiktok: "TikTok",
  reddit: "Reddit",
  dating: "Dating",
};

const MOCK_REPLIES = [
  "Roger that. Processing your request.",
  "Understood. Executing now.",
  "On it. I'll report back when complete.",
  "Command received. Running the operation.",
  "Affirmative. Queued for fleet dispatch.",
];

function formatTime(d: Date) {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function AgentChatWidget() {
  const [open, setOpen] = useState(false);
  const [agent, setAgent] = useState<Agent>("chief");
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "init",
      role: "agent",
      text: "Agent Command online. How can I assist?",
      ts: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      inputRef.current?.focus();
    }
  }, [open, messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || typing) return;
    setInput("");

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      text,
      ts: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setTyping(true);

    try {
      const history = messages.map((m) => ({ role: m.role, text: m.text }));
      const res = await fetch("http://localhost:8001/api/v1/agents/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent, message: text, history }),
      });
      if (res.ok) {
        const data = await res.json();
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "agent",
            text: data?.reply ?? MOCK_REPLIES[Math.floor(Math.random() * MOCK_REPLIES.length)],
            ts: new Date(),
          },
        ]);
      } else {
        throw new Error("non-ok");
      }
    } catch {
      await new Promise((r) => setTimeout(r, 900 + Math.random() * 600));
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "agent",
          text: MOCK_REPLIES[Math.floor(Math.random() * MOCK_REPLIES.length)],
          ts: new Date(),
        },
      ]);
    } finally {
      setTyping(false);
    }
  }

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <>
      {/* Floating button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          aria-label="Open Agent Command"
          className="fixed bottom-6 right-6 z-50 w-13 h-13 rounded-full bg-phantom-accent shadow-lg flex items-center justify-center hover:opacity-90 active:scale-95 transition-all"
          style={{ width: 52, height: 52 }}
        >
          <Bot className="w-6 h-6 text-phantom-bg" strokeWidth={1.75} />
        </button>
      )}

      {/* Chat panel */}
      {open && (
        <div
          className="fixed bottom-6 right-6 z-50 flex flex-col rounded-xl border border-phantom-border bg-phantom-panel shadow-2xl overflow-hidden"
          style={{ width: 380, height: 520 }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-phantom-border bg-phantom-panelHi shrink-0">
            <div className="flex items-center gap-2">
              <Bot className="w-4 h-4 text-phantom-accent" strokeWidth={1.75} />
              <span className="text-sm font-display font-semibold">Agent Command</span>
              <span className="flex items-center gap-1 text-[10px] text-phantom-ghost ml-1">
                <span className="w-1.5 h-1.5 rounded-full bg-phantom-alive inline-block" />
                Chief Online
              </span>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-phantom-ghost hover:text-white transition-colors p-1 rounded"
              aria-label="Close"
            >
              <Minimize2 className="w-4 h-4" />
            </button>
          </div>

          {/* Agent selector */}
          <div className="flex items-center gap-1.5 px-4 py-2 border-b border-phantom-border/50 shrink-0 overflow-x-auto">
            {(Object.keys(AGENT_LABELS) as Agent[]).map((a) => (
              <button
                key={a}
                onClick={() => setAgent(a)}
                className={`shrink-0 px-3 py-1 rounded-full text-[11px] font-medium transition-colors ${
                  agent === a
                    ? "bg-phantom-accent text-phantom-bg"
                    : "bg-phantom-bg text-phantom-ghost hover:text-white border border-phantom-border"
                }`}
              >
                {AGENT_LABELS[a]}
              </button>
            ))}
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-0">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex flex-col gap-0.5 ${msg.role === "user" ? "items-end" : "items-start"}`}
              >
                <div
                  className={`max-w-[80%] px-3 py-2 rounded-xl text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-phantom-accent text-phantom-bg rounded-br-sm"
                      : "bg-phantom-bg text-white border border-phantom-border/60 rounded-bl-sm"
                  }`}
                >
                  {msg.text}
                </div>
                <span className="text-[10px] text-phantom-ghost/60 px-1">{formatTime(msg.ts)}</span>
              </div>
            ))}

            {/* Typing indicator */}
            {typing && (
              <div className="flex items-start gap-1">
                <div className="bg-phantom-bg border border-phantom-border/60 rounded-xl rounded-bl-sm px-3 py-2.5 flex items-center gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-phantom-ghost/60 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input row */}
          <div className="shrink-0 border-t border-phantom-border px-3 py-3 flex items-center gap-2 bg-phantom-panelHi">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder={`Command ${AGENT_LABELS[agent]}…`}
              disabled={typing}
              className="flex-1 bg-phantom-bg border border-phantom-border rounded-lg px-3 py-2 text-sm text-phantom-ghost placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/60 transition-colors disabled:opacity-50"
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || typing}
              aria-label="Send"
              className="w-9 h-9 rounded-lg bg-phantom-accent flex items-center justify-center hover:opacity-90 active:scale-95 transition-all disabled:opacity-40 shrink-0"
            >
              <Send className="w-4 h-4 text-phantom-bg" strokeWidth={1.75} />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
