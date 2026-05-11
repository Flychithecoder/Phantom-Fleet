"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/panel";
import {
  Image as ImageIcon,
  Video,
  Upload,
  Trash2,
  Send,
  CalendarDays,
  Filter,
  RefreshCw,
  CheckCircle2,
  Loader2,
  X,
  ChevronDown,
  BarChart3,
  Smartphone,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentItem = {
  item_id: string;
  file_path: string;
  file_type: "image/jpeg" | "image/png" | "video/mp4";
  caption: string;
  platform_tags: string[];
  content_tags: string[];
  persona_id: string | null;
  source: "contentforge" | "manual_upload" | "recycled";
  created_at_iso: string;
  used_count: number;
  last_used_iso: string | null;
};

type VaultStats = {
  total_items: number;
  unused_items: number;
  used_this_week: number;
  by_platform: Record<string, number>;
  by_source: Record<string, number>;
  by_tag: Record<string, number>;
  total_file_size_bytes: number;
};

const API = "http://localhost:8001";

const PLATFORM_OPTIONS = ["instagram", "threads", "tiktok", "x", "reddit"];
const SOURCE_LABELS: Record<string, string> = {
  contentforge: "ContentForge",
  manual_upload: "Manual",
  recycled: "Recycled",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatRelative(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PlatformBadge({ tag }: { tag: string }) {
  const map: Record<string, string> = {
    instagram: "bg-pink-500/10 text-pink-400 border-pink-500/20",
    threads:   "bg-purple-500/10 text-purple-400 border-purple-500/20",
    tiktok:    "bg-red-500/10 text-red-400 border-red-500/20",
    x:         "bg-blue-500/10 text-blue-400 border-blue-500/20",
    reddit:    "bg-orange-500/10 text-orange-400 border-orange-500/20",
  };
  return (
    <span
      className={cn(
        "px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border",
        map[tag] ?? "bg-phantom-panelHi text-phantom-ghost border-phantom-border"
      )}
    >
      {tag}
    </span>
  );
}

function SourceBadge({ source }: { source: string }) {
  const map: Record<string, string> = {
    contentforge: "bg-phantom-accent/10 text-phantom-accent border-phantom-accent/20",
    manual_upload: "bg-phantom-panelHi text-phantom-ghost border-phantom-border",
    recycled:     "bg-blue-500/10 text-blue-400 border-blue-500/20",
  };
  return (
    <span
      className={cn(
        "px-1.5 py-0.5 rounded text-[9px] font-medium border",
        map[source] ?? "bg-phantom-panelHi text-phantom-ghost border-phantom-border"
      )}
    >
      {SOURCE_LABELS[source] ?? source}
    </span>
  );
}

function MediaThumb({ item }: { item: ContentItem }) {
  const isVideo = item.file_type === "video/mp4";
  const filename = item.file_path.split(/[\\/]/).pop() ?? item.item_id;

  return (
    <div className="relative aspect-square bg-phantom-panelHi rounded-lg overflow-hidden flex items-center justify-center border border-phantom-border">
      {isVideo ? (
        <div className="flex flex-col items-center gap-1 text-phantom-ghost">
          <Video className="w-8 h-8" strokeWidth={1.5} />
          <span className="text-[10px]">video</span>
        </div>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`${API}/api/content-vault/media/${filename}`}
          alt={item.caption || "content"}
          className="w-full h-full object-cover"
          onError={(e) => {
            const el = e.currentTarget;
            el.style.display = "none";
            const parent = el.parentElement;
            if (parent) {
              const fallback = document.createElement("div");
              fallback.className = "flex flex-col items-center gap-1 text-phantom-ghost";
              fallback.innerHTML = `<svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg><span style="font-size:10px">image</span>`;
              parent.appendChild(fallback);
            }
          }}
        />
      )}
      {/* Used count chip */}
      {item.used_count > 0 && (
        <div className="absolute top-1 right-1 bg-phantom-bg/80 text-[9px] text-white px-1 py-0.5 rounded font-mono">
          ×{item.used_count}
        </div>
      )}
    </div>
  );
}

function MediaCard({
  item,
  onDelete,
  onDeliver,
  delivering,
}: {
  item: ContentItem;
  onDelete: (id: string) => void;
  onDeliver: (id: string) => void;
  delivering: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="phantom-panel p-3 flex flex-col gap-2 hover:border-phantom-accent/20 transition-all duration-200 group">
      <MediaThumb item={item} />

      <div className="space-y-1.5">
        {/* Caption */}
        <p
          className={cn(
            "text-[11px] text-white leading-relaxed cursor-pointer",
            !expanded && "line-clamp-2"
          )}
          onClick={() => setExpanded((e) => !e)}
        >
          {item.caption || <span className="text-phantom-ghost italic">No caption</span>}
        </p>

        {/* Tags row */}
        <div className="flex flex-wrap gap-1">
          {item.platform_tags.map((t) => (
            <PlatformBadge key={t} tag={t} />
          ))}
          <SourceBadge source={item.source} />
        </div>

        {/* Content tags */}
        {item.content_tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {item.content_tags.map((t) => (
              <span
                key={t}
                className="text-[9px] text-phantom-ghost border border-phantom-border/50 px-1.5 py-0.5 rounded"
              >
                {t}
              </span>
            ))}
          </div>
        )}

        {/* Meta row */}
        <div className="flex items-center justify-between text-[10px] text-phantom-ghost">
          <span>{formatRelative(item.created_at_iso)}</span>
          {item.used_count > 0 && (
            <span className="flex items-center gap-1">
              <CheckCircle2 className="w-2.5 h-2.5 text-phantom-accent" />
              {item.used_count} post{item.used_count !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Action row */}
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
          <button
            onClick={() => onDeliver(item.item_id)}
            disabled={delivering}
            className="flex-1 flex items-center justify-center gap-1 py-1 rounded-md text-[10px] font-medium bg-phantom-accent/10 text-phantom-accent border border-phantom-accent/20 hover:bg-phantom-accent/20 transition-colors disabled:opacity-50"
          >
            {delivering ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Send className="w-3 h-3" />
            )}
            {delivering ? "Sending..." : "Deliver"}
          </button>
          <button
            onClick={() => onDelete(item.item_id)}
            className="px-2 py-1 rounded-md text-[10px] font-medium bg-phantom-red/10 text-phantom-red border border-phantom-red/20 hover:bg-phantom-red/20 transition-colors"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

function StatsStrip({ stats }: { stats: VaultStats | null }) {
  if (!stats) return null;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {[
        { label: "Total Items", value: stats.total_items, icon: <ImageIcon className="w-4 h-4 text-phantom-ghost" /> },
        { label: "Ready to Post", value: stats.unused_items, icon: <CheckCircle2 className="w-4 h-4 text-phantom-accent" />, accent: true },
        { label: "Used This Week", value: stats.used_this_week, icon: <BarChart3 className="w-4 h-4 text-yellow-400" /> },
        { label: "Storage", value: formatBytes(stats.total_file_size_bytes), icon: <BarChart3 className="w-4 h-4 text-blue-400" /> },
      ].map((chip) => (
        <div key={chip.label} className="phantom-panel px-4 py-3 flex items-center gap-3">
          <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", chip.accent ? "bg-phantom-accent/10" : "bg-phantom-panelHi")}>
            {chip.icon}
          </div>
          <div>
            <div className="text-lg font-display font-bold">{chip.value}</div>
            <div className="text-[10px] text-phantom-ghost uppercase tracking-wider">{chip.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload modal
// ---------------------------------------------------------------------------

function UploadModal({
  onClose,
  onUploaded,
}: {
  onClose: () => void;
  onUploaded: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");
  const [platforms, setPlatforms] = useState("instagram");
  const [tags, setTags] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("caption", caption);
    fd.append("platform_tags", platforms);
    fd.append("content_tags", tags);
    try {
      const res = await fetch(`${API}/api/content-vault/upload`, {
        method: "POST",
        body: fd,
      });
      if (res.ok) {
        onUploaded();
        onClose();
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Upload failed");
      }
    } catch {
      setError("Could not reach the backend.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-phantom-bg/70 backdrop-blur-sm">
      <div className="phantom-panel p-6 w-full max-w-md space-y-4 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-phantom-ghost hover:text-white"
        >
          <X className="w-5 h-5" />
        </button>
        <h3 className="font-display text-lg font-bold">Upload Media</h3>

        {/* Drop zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all duration-200",
            dragging ? "border-phantom-accent bg-phantom-accent/5" : "border-phantom-border hover:border-phantom-accent/40"
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,video/mp4"
            className="hidden"
            onChange={(e) => { if (e.target.files?.[0]) setFile(e.target.files[0]); }}
          />
          {file ? (
            <div className="space-y-1">
              <CheckCircle2 className="w-8 h-8 text-phantom-accent mx-auto" />
              <p className="text-sm text-white font-medium">{file.name}</p>
              <p className="text-xs text-phantom-ghost">{formatBytes(file.size)}</p>
            </div>
          ) : (
            <div className="space-y-2">
              <Upload className="w-8 h-8 text-phantom-ghost mx-auto" strokeWidth={1.5} />
              <p className="text-sm text-white">Drag & drop or click to browse</p>
              <p className="text-xs text-phantom-ghost">JPEG, PNG, MP4 — max 100 MB</p>
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs text-phantom-ghost uppercase tracking-wider font-medium">Caption</label>
            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              rows={3}
              className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50 resize-none"
              placeholder="Your caption here..."
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-phantom-ghost uppercase tracking-wider font-medium">Platforms</label>
              <input
                value={platforms}
                onChange={(e) => setPlatforms(e.target.value)}
                className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50"
                placeholder="instagram,threads"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-phantom-ghost uppercase tracking-wider font-medium">Content Tags</label>
              <input
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                className="w-full bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-phantom-ghost/40 focus:outline-none focus:border-phantom-accent/50"
                placeholder="sfw,lifestyle"
              />
            </div>
          </div>
        </div>

        {error && (
          <p className="text-xs text-phantom-red">{error}</p>
        )}

        <button
          onClick={handleUpload}
          disabled={!file || uploading}
          className={cn(
            "w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-all duration-200 border",
            "bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25",
            (!file || uploading) && "opacity-50 cursor-not-allowed"
          )}
        >
          {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
          {uploading ? "Uploading..." : "Upload"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ContentVaultPage() {
  const [items, setItems] = useState<ContentItem[]>([]);
  const [stats, setStats] = useState<VaultStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [scheduleMsg, setScheduleMsg] = useState<string | null>(null);

  // Filters
  const [filterPlatform, setFilterPlatform] = useState<string>("");
  const [filterTags, setFilterTags] = useState<string>("");
  const [filterPersona, setFilterPersona] = useState<string>("");
  const [filterUnused, setFilterUnused] = useState(false);

  // Deliver state: item_id → loading bool
  const [delivering, setDelivering] = useState<Record<string, boolean>>({});

  const fetchItems = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (filterPlatform) params.set("platform", filterPlatform);
    if (filterTags) params.set("content_tags", filterTags);
    if (filterPersona) params.set("persona_id", filterPersona);
    if (filterUnused) params.set("unused_only", "true");
    params.set("limit", "200");

    try {
      const res = await fetch(`${API}/api/content-vault?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setItems(data.items ?? []);
      }
    } catch {
      // Backend offline
    } finally {
      setLoading(false);
    }
  }, [filterPlatform, filterTags, filterPersona, filterUnused]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/content-vault/stats`);
      if (res.ok) setStats(await res.json());
    } catch {
      // Backend offline
    }
  }, []);

  useEffect(() => {
    fetchItems();
    fetchStats();
  }, [fetchItems, fetchStats]);

  const handleDelete = async (itemId: string) => {
    if (!confirm("Delete this content item?")) return;
    try {
      await fetch(`${API}/api/content-vault/${itemId}`, { method: "DELETE" });
      setItems((prev) => prev.filter((i) => i.item_id !== itemId));
      fetchStats();
    } catch {
      // Backend offline
    }
  };

  const handleDeliver = async (itemId: string) => {
    const serial = prompt("Enter phone ADB serial to deliver to:");
    if (!serial) return;
    setDelivering((prev) => ({ ...prev, [itemId]: true }));
    try {
      await fetch(
        `${API}/api/content-vault/${itemId}/deliver?phone_serial=${encodeURIComponent(serial)}`,
        { method: "POST" }
      );
    } catch {
      // Backend offline
    } finally {
      setDelivering((prev) => ({ ...prev, [itemId]: false }));
    }
  };

  const handleAutoSchedule = async () => {
    setScheduling(true);
    setScheduleMsg(null);
    try {
      const res = await fetch(`${API}/api/content-vault/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_ids: [],   // API derives from provisioned accounts
          days_ahead: 7,
          platform: filterPlatform || "instagram",
          persona_id: filterPersona || null,
          content_tags: filterTags ? filterTags.split(",").map((t) => t.trim()) : null,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setScheduleMsg(`Scheduled ${data.assignments} posts across ${data.days} days.`);
      } else {
        setScheduleMsg("Scheduling failed — check the backend logs.");
      }
    } catch {
      setScheduleMsg("Backend offline — scheduling not available.");
    } finally {
      setScheduling(false);
      fetchItems();
      fetchStats();
    }
  };

  return (
    <div className="space-y-8">
      {showUpload && (
        <UploadModal
          onClose={() => setShowUpload(false)}
          onUploaded={() => { fetchItems(); fetchStats(); }}
        />
      )}

      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
            Media Pipeline
          </div>
          <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
            <ImageIcon className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
            Content <span className="phantom-accent-text">Vault</span>
          </h1>
          <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
            ContentForge pushes generated media here. The scheduler pulls from here to fill
            phone galleries. Manage, preview, and deliver content to your fleet.
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={fetchItems}
            className="p-2 rounded-lg border border-phantom-border bg-phantom-panelHi text-phantom-ghost hover:text-white transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            onClick={() => setShowUpload(true)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-all duration-200",
              "bg-phantom-panelHi text-white border-phantom-border hover:bg-phantom-panelHi/80"
            )}
          >
            <Upload className="w-4 h-4" strokeWidth={1.75} />
            Upload
          </button>
          <button
            onClick={handleAutoSchedule}
            disabled={scheduling}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-all duration-200",
              "bg-phantom-accent/15 text-phantom-accent border-phantom-accent/30 hover:bg-phantom-accent/25 hover:shadow-[0_0_16px_hsl(162_100%_54%/0.2)]",
              scheduling && "opacity-60 cursor-not-allowed"
            )}
          >
            {scheduling ? <Loader2 className="w-4 h-4 animate-spin" /> : <CalendarDays className="w-4 h-4" strokeWidth={1.75} />}
            {scheduling ? "Scheduling..." : "Auto-schedule 7 Days"}
          </button>
        </div>
      </div>

      {scheduleMsg && (
        <div className="flex items-center gap-2 text-sm text-phantom-accent border border-phantom-accent/20 bg-phantom-accent/5 px-4 py-3 rounded-lg">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          {scheduleMsg}
        </div>
      )}

      {/* Stats strip */}
      <StatsStrip stats={stats} />

      {/* Filter bar */}
      <div className="phantom-panel p-4">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 text-phantom-ghost text-sm">
            <Filter className="w-4 h-4" />
            <span className="text-xs uppercase tracking-wider font-medium">Filters</span>
          </div>

          {/* Platform filter */}
          <select
            value={filterPlatform}
            onChange={(e) => setFilterPlatform(e.target.value)}
            className="bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-phantom-accent/50 transition-colors"
          >
            <option value="">All platforms</option>
            {PLATFORM_OPTIONS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>

          {/* Content tags filter */}
          <input
            value={filterTags}
            onChange={(e) => setFilterTags(e.target.value)}
            placeholder="Tags (sfw, lifestyle...)"
            className="bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-1.5 text-sm text-white placeholder:text-phantom-ghost/50 focus:outline-none focus:border-phantom-accent/50 transition-colors w-44"
          />

          {/* Persona filter */}
          <input
            value={filterPersona}
            onChange={(e) => setFilterPersona(e.target.value)}
            placeholder="Persona ID"
            className="bg-phantom-panelHi border border-phantom-border rounded-lg px-3 py-1.5 text-sm text-white placeholder:text-phantom-ghost/50 focus:outline-none focus:border-phantom-accent/50 transition-colors w-36"
          />

          {/* Unused only toggle */}
          <label className="flex items-center gap-2 cursor-pointer">
            <div
              onClick={() => setFilterUnused((v) => !v)}
              className={cn(
                "w-8 h-4 rounded-full transition-all duration-200 relative cursor-pointer",
                filterUnused ? "bg-phantom-accent" : "bg-phantom-panelHi border border-phantom-border"
              )}
            >
              <div
                className={cn(
                  "absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all duration-200",
                  filterUnused ? "left-4" : "left-0.5"
                )}
              />
            </div>
            <span className="text-xs text-phantom-ghost">Unused only</span>
          </label>

          <button
            onClick={fetchItems}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-phantom-accent/10 text-phantom-accent border border-phantom-accent/20 hover:bg-phantom-accent/20 transition-colors"
          >
            Apply
          </button>
        </div>
      </div>

      {/* Media grid */}
      <Panel
        label="content vault · media"
        title={`${items.length} item${items.length !== 1 ? "s" : ""}`}
        subtitle="Hover a card to see deliver / delete actions."
      >
        {loading ? (
          <div className="py-20 text-center">
            <Loader2 className="w-8 h-8 text-phantom-accent animate-spin mx-auto" />
            <p className="text-phantom-ghost text-sm mt-3">Loading vault...</p>
          </div>
        ) : items.length === 0 ? (
          <div className="py-20 text-center space-y-3">
            <ImageIcon className="w-12 h-12 text-phantom-ghost/30 mx-auto" strokeWidth={1} />
            <p className="text-phantom-ghost text-sm">No content items found.</p>
            <p className="text-phantom-ghost/60 text-xs">
              Upload manually or connect ContentForge to start pushing media here.
            </p>
            <button
              onClick={() => setShowUpload(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border bg-phantom-accent/10 text-phantom-accent border-phantom-accent/20 hover:bg-phantom-accent/20 transition-colors"
            >
              <Upload className="w-4 h-4" />
              Upload first item
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
            {items.map((item) => (
              <MediaCard
                key={item.item_id}
                item={item}
                onDelete={handleDelete}
                onDeliver={handleDeliver}
                delivering={!!delivering[item.item_id]}
              />
            ))}
          </div>
        )}
      </Panel>

      {/* ContentForge integration guide */}
      <Panel
        label="integration"
        title="ContentForge Bridge"
        subtitle="Add this single API call to ContentForge after generating media to automatically push content into this vault."
        dense
      >
        <pre className="bg-phantom-bg rounded-lg p-4 text-[11px] text-phantom-ghost font-mono overflow-x-auto leading-relaxed border border-phantom-border">
{`# In ContentForge, after generating media:
await httpx.post(
    f"{PHANTOM_FLEET_URL}/api/content-vault/push",
    headers={"X-ContentForge-Key": CONTENTFORGE_API_KEY},
    files={"file": open(media_path, "rb")},
    data={"metadata": json.dumps({
        "caption": caption,
        "platform_tags": ["instagram"],
        "content_tags": ["lifestyle", "sfw"],
        "persona_id": persona_id,
        "source": "contentforge",
    })}
)`}
        </pre>
      </Panel>
    </div>
  );
}
