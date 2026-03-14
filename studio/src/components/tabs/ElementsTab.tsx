import { useCallback, useMemo, useState } from "react";
import {
  Play, FileVideo, Monitor, Upload, X, RotateCcw, Film, Music, Image,
  MoveRight, Layers, Sparkles, ArrowRightLeft, Volume2, ChevronDown, ChevronRight as ChevronRightIcon,
} from "lucide-react";
import type { FootageManifest, Clip } from "../../types/manifest";
import type { UnitEntry } from "../../types/manifest";
import type { AddedMedia, ClipEdit, Marker, WordCut } from "../../types/edit-manifest";
import { formatTimecode } from "../../lib/manifest-utils";
import { frameUrl } from "../../api/client";
import { cn } from "../../lib/cn";

interface ElementsTabProps {
  unitManifest: FootageManifest | null;
  unit: UnitEntry | null;
  loading: boolean;
  error: string | null;
  discardedClips: string[];
  clipEdits?: Record<string, ClipEdit>;
  wordCuts: WordCut[];
  addedMedia: AddedMedia[];
  availableUnits?: { id: string; name: string }[];
  markers?: Marker[];
  onRemoveMedia: (index: number) => void;
  onPlayClip: (clipId: string) => void;
  onDropFiles: (files: File[]) => void;
  onToggleDiscard: (clipId: string) => void;
  onMoveClip?: (clipId: string, toUnitId: string) => void;
  onSeekToMarker?: (time: number) => void;
}

// --- Processing pipeline: arrow-connected chain showing clip transformations ---

function ProcessingPipeline({ clip, clipEdit, wordCutCount }: {
  clip: Clip;
  clipEdit?: ClipEdit;
  wordCutCount: number;
}) {
  const denoised = !!(clip.audio as any)?.muxed;
  const asrEngine = (clip.transcript as any)?.engine;
  const hasTranscript = !!(asrEngine || (clip.transcript?.segments?.length ?? 0) > 0);
  const splitCount = clipEdit?.splits?.length || 0;
  const deletedCount = clipEdit?.deleted_ranges?.length || 0;

  const steps: { label: string; color: string }[] = [
    { label: "Raw", color: "text-cp-text-secondary" },
  ];

  if (denoised) steps.push({ label: "Denoised", color: "text-cp-success" });
  if (hasTranscript) steps.push({ label: asrEngine ? `ASR: ${asrEngine}` : "Transcribed", color: "text-cp-secondary" });
  if (wordCutCount > 0) steps.push({ label: `${wordCutCount} word cuts`, color: "text-cp-error" });
  if (splitCount > 0) steps.push({ label: `${splitCount} split${splitCount !== 1 ? "s" : ""}`, color: "text-cp-accent" });
  if (deletedCount > 0) steps.push({ label: `${deletedCount} deleted`, color: "text-cp-error" });

  if (steps.length <= 1) return null;

  return (
    <div className="flex flex-wrap items-center gap-0.5 mt-1.5">
      {steps.map((step, i) => (
        <span key={i} className="flex items-center gap-0.5">
          {i > 0 && <span className="text-cp-text-muted text-[11px]">&rarr;</span>}
          <span className={cn("px-1.5 py-0.5 rounded text-[11px] font-medium bg-cp-bg/50", step.color)}>
            {step.label}
          </span>
        </span>
      ))}
    </div>
  );
}

// --- Clip card ---

function ClipCard({
  clip,
  discarded,
  clipEdit,
  wordCutCount,
  availableUnits,
  onPlay,
  onToggleDiscard,
  onMoveClip,
}: {
  clip: Clip;
  discarded: boolean;
  clipEdit?: ClipEdit;
  wordCutCount: number;
  availableUnits?: { id: string; name: string }[];
  onPlay: () => void;
  onToggleDiscard: () => void;
  onMoveClip?: (toUnitId: string) => void;
}) {
  const [showMoveMenu, setShowMoveMenu] = useState(false);
  const firstFrame = clip.frames?.extracted?.[0];
  const thumbnailUrl = firstFrame
    ? frameUrl(clip.id, firstFrame.path.split("/").pop()!)
    : null;
  const transcriptSegments = clip.transcript?.segments;
  const transcriptExcerpt = Array.isArray(transcriptSegments)
    ? transcriptSegments
        .slice(0, 2)
        .map((s: any) => s.text)
        .join(" ")
        .slice(0, 120)
    : null;
  const sceneCount = clip.scenes?.boundaries?.length || 0;
  const yoloClasses: string[] = [];
  if (clip.yolo && typeof clip.yolo === "object") {
    const detByFrame = (clip.yolo as any).detections_by_frame;
    if (detByFrame && typeof detByFrame === "object") {
      const allDets = Object.values(detByFrame).flat() as any[];
      const classSet = new Set(allDets.map((d: any) => d.class).filter(Boolean));
      yoloClasses.push(...[...classSet].slice(0, 5));
    }
  }
  const visionSummary = (clip.vision as any)?.primary_activity || null;
  const interestAvg = (clip.vision as any)?.avg_interest
    ? Number((clip.vision as any).avg_interest).toFixed(2)
    : null;
  const langList = (clip.transcript as any)?.languages_detected;
  const lang = Array.isArray(langList) ? langList[0] || "?" : "?";

  return (
    <div className={cn(
      "rounded-md p-3 space-y-1.5 transition-opacity",
      discarded ? "bg-cp-bg-surface/50 opacity-50" : "bg-cp-bg-surface",
    )}>
      <div className="flex items-start gap-3">
        {thumbnailUrl ? (
          <div className={cn(
            "relative w-24 h-14 rounded overflow-hidden shrink-0 bg-black",
            discarded && "grayscale",
          )}>
            <img src={thumbnailUrl} alt={clip.id} className="w-full h-full object-cover" />
            {!discarded && (
              <button
                onClick={onPlay}
                className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 hover:opacity-100 transition-opacity"
              >
                <Play className="w-6 h-6 fill-white text-white" />
              </button>
            )}
          </div>
        ) : (
          <div className="relative w-24 h-14 rounded bg-cp-bg flex items-center justify-center shrink-0">
            <FileVideo className="w-6 h-6 text-cp-text-muted" />
            {!discarded && (
              <button
                onClick={onPlay}
                className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 hover:opacity-100 transition-opacity rounded"
              >
                <Play className="w-6 h-6 fill-white text-white" />
              </button>
            )}
          </div>
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            {clip.type === "screen_recording" ? (
              <Monitor className="w-3.5 h-3.5 text-cp-secondary" />
            ) : (
              <FileVideo className="w-3.5 h-3.5 text-cp-primary" />
            )}
            <span className={cn("truncate", discarded && "line-through")}>{clip.id}</span>
          </div>
          <div className="text-xs text-cp-text-muted mt-0.5">
            {clip.metadata.width}x{clip.metadata.height} · {clip.metadata.fps}fps ·{" "}
            {formatTimecode(clip.metadata.duration_seconds)} · {lang.toUpperCase()}
          </div>
        </div>

        <button
          onClick={onToggleDiscard}
          className={cn(
            "shrink-0 p-1.5 rounded transition-colors",
            discarded
              ? "text-cp-success hover:bg-cp-success/20"
              : "text-cp-text-muted hover:text-cp-error hover:bg-cp-error/20",
          )}
          title={discarded ? "Restore clip" : "Discard clip"}
        >
          {discarded ? <RotateCcw className="w-4 h-4" /> : <X className="w-4 h-4" />}
        </button>
      </div>

      {/* Processing pipeline */}
      {!discarded && (
        <ProcessingPipeline clip={clip} clipEdit={clipEdit} wordCutCount={wordCutCount} />
      )}

      {/* Analysis summary */}
      {!discarded && (
        <div className="text-xs space-y-1 text-cp-text-secondary">
          {transcriptExcerpt && (
            <p className="italic truncate">"{transcriptExcerpt}"</p>
          )}
          <div className="flex flex-wrap gap-x-3 gap-y-0.5">
            {sceneCount > 0 && <span>{sceneCount} scenes</span>}
            {interestAvg && <span>interest: {interestAvg}</span>}
            {yoloClasses.length > 0 && (
              <span>objects: {yoloClasses.join(", ")}</span>
            )}
          </div>
          {visionSummary && (
            <p className="text-cp-text-muted truncate">{visionSummary}</p>
          )}
        </div>
      )}

      {/* Move to unit */}
      {!discarded && onMoveClip && availableUnits && availableUnits.length > 0 && (
        <div className="relative">
          <button
            onClick={() => setShowMoveMenu(!showMoveMenu)}
            className="flex items-center gap-1 text-xs text-cp-text-muted hover:text-cp-secondary transition-colors"
          >
            <MoveRight className="w-3 h-3" />
            Move to...
          </button>
          {showMoveMenu && (
            <div className="absolute left-0 top-full mt-1 z-20 bg-cp-bg-elevated border border-cp-border rounded shadow-lg py-1 min-w-[180px]">
              {availableUnits.map((u) => (
                <button
                  key={u.id}
                  onClick={() => { onMoveClip(u.id); setShowMoveMenu(false); }}
                  className="w-full text-left px-3 py-1 text-xs hover:bg-cp-bg-surface transition-colors truncate"
                >
                  {u.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {discarded && (
        <div className="text-xs text-cp-error/70">Discarded — excluded from final edit</div>
      )}
    </div>
  );
}

// --- Media grouping types and logic ---

interface MediaVariant {
  media: AddedMedia;
  index: number;
  ext: string;
  codec: string;
  hasAlpha: boolean;
}

interface MediaGroup {
  stem: string;
  label: string;
  variants: MediaVariant[];
  overlayMarker?: string;
  notes?: string;
  durationSeconds?: number;
  hasAlpha: boolean;
}

const codecDisplayNames: Record<string, string> = {
  prores: "ProRes", h264: "H.264", hevc: "HEVC", vp9: "VP9", vp8: "VP8", av1: "AV1",
};

function codecFromExt(ext: string): string {
  switch (ext) {
    case ".mov": return "ProRes";
    case ".mp4": return "H.264";
    case ".webm": return "VP9";
    default: return ext.replace(".", "").toUpperCase();
  }
}

function canonicalStem(filename: string): string {
  return filename
    .replace(/\.[^.]+$/, "")
    .replace(/_alpha$/, "");
}

function humanizeLabel(stem: string): string {
  return stem
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function pickBestPlayable(variants: MediaVariant[]): MediaVariant {
  const priority = [".mp4", ".webm", ".mov"];
  let best = variants[0];
  for (const v of variants) {
    const vPri = priority.indexOf(v.ext);
    const bestPri = priority.indexOf(best.ext);
    if (vPri !== -1 && (bestPri === -1 || vPri < bestPri)) {
      best = v;
    }
  }
  return best;
}

function groupMediaVariants(items: { media: AddedMedia; index: number }[]): MediaGroup[] {
  const groups = new Map<string, MediaGroup>();

  for (const item of items) {
    const ext = item.media.filename.match(/\.[^.]+$/)?.[0] || "";
    const stem = canonicalStem(item.media.filename);
    const hasAlpha = !!item.media.has_alpha;
    const rawCodec = item.media.codec_video;
    const codec = rawCodec
      ? (codecDisplayNames[rawCodec.toLowerCase()] || rawCodec)
      : codecFromExt(ext);

    if (!groups.has(stem)) {
      groups.set(stem, {
        stem,
        label: humanizeLabel(stem),
        variants: [],
        overlayMarker: item.media.overlay_at_marker,
        notes: item.media.notes,
        durationSeconds: item.media.duration_seconds,
        hasAlpha: false,
      });
    }

    const group = groups.get(stem)!;
    group.variants.push({ media: item.media, index: item.index, ext, codec, hasAlpha });
    if (hasAlpha) group.hasAlpha = true;
    if (!group.overlayMarker && item.media.overlay_at_marker) group.overlayMarker = item.media.overlay_at_marker;
    if (!group.notes && item.media.notes) group.notes = item.media.notes;
    if (group.durationSeconds == null && item.media.duration_seconds != null) group.durationSeconds = item.media.duration_seconds;
  }

  return [...groups.values()];
}

// --- Format pill for variant display ---

function FormatPill({ variant }: { variant: MediaVariant }) {
  return (
    <span className={cn(
      "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium",
      "bg-cp-bg border border-cp-border",
    )}>
      {variant.codec}
      {variant.hasAlpha && <span className="text-cp-accent">/alpha</span>}
    </span>
  );
}

// --- Grouped media card ---

const mediaIcon: Record<string, React.ComponentType<{ className?: string }>> = {
  video: Film,
  audio: Music,
  image: Image,
};

function GroupedMediaCard({ group, markers, onPlay, onRemove, onSeekToMarker }: {
  group: MediaGroup;
  markers?: Marker[];
  onPlay: () => void;
  onRemove: () => void;
  onSeekToMarker?: (time: number) => void;
}) {
  const isPlayable = group.variants.some((v) => v.media.type === "video" || v.media.type === "audio");
  const marker = group.overlayMarker && markers
    ? markers.find((m) => m.name === group.overlayMarker || m.id === group.overlayMarker)
    : null;
  const Icon = mediaIcon[group.variants[0]?.media.type] || FileVideo;

  return (
    <div className="rounded-md bg-cp-bg-surface mb-1 overflow-hidden">
      <div className="p-2.5 space-y-1.5">
        <div className="flex items-center gap-3">
          {isPlayable ? (
            <button
              onClick={onPlay}
              className="relative w-9 h-9 rounded bg-cp-bg flex items-center justify-center shrink-0 hover:bg-cp-primary/20 transition-colors"
            >
              <Play className="w-4 h-4 fill-cp-primary text-cp-primary" />
            </button>
          ) : (
            <div className="w-9 h-9 rounded bg-cp-bg flex items-center justify-center shrink-0">
              <Icon className="w-4 h-4 text-cp-accent" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">{group.label}</div>
            <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-cp-text-muted mt-0.5">
              {marker && onSeekToMarker ? (
                <button
                  onClick={() => onSeekToMarker(marker.time)}
                  className="text-cp-primary hover:underline"
                >
                  @ {marker.name}
                </button>
              ) : group.overlayMarker ? (
                <span className="text-cp-primary">@ {group.overlayMarker}</span>
              ) : null}
              {group.durationSeconds != null && <span>{group.durationSeconds}s</span>}
              {group.hasAlpha && <span className="text-cp-accent">alpha</span>}
            </div>
          </div>
          <button
            onClick={onRemove}
            className="shrink-0 p-1.5 rounded text-cp-text-muted hover:text-cp-error hover:bg-cp-error/20 transition-colors"
            title="Remove all variants"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        {group.variants.length > 1 && (
          <div className="flex flex-wrap gap-1.5 pl-12">
            {group.variants.map((v) => (
              <FormatPill key={v.index} variant={v} />
            ))}
          </div>
        )}

        {group.notes && (
          <div className="text-[10px] text-cp-text-muted pl-12 truncate">{group.notes}</div>
        )}
      </div>
    </div>
  );
}

// --- Collection section (collapsible) ---

function CollectionSection({ title, icon: Icon, groupCount, fileCount, children, defaultOpen = true }: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  groupCount: number;
  fileCount: number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (groupCount === 0) return null;

  const countDisplay = groupCount === fileCount
    ? `(${groupCount})`
    : `(${groupCount} asset${groupCount !== 1 ? "s" : ""} \u00b7 ${fileCount} file${fileCount !== 1 ? "s" : ""})`;

  return (
    <div className="border-t border-cp-border pt-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full text-left mb-1.5 hover:text-cp-text transition-colors"
      >
        {open ? <ChevronDown className="w-3 h-3 text-cp-text-muted" /> : <ChevronRightIcon className="w-3 h-3 text-cp-text-muted" />}
        <Icon className="w-3.5 h-3.5 text-cp-text-secondary" />
        <span className="text-xs font-medium text-cp-text-secondary">{title}</span>
        <span className="text-xs text-cp-text-muted">{countDisplay}</span>
      </button>
      {open && <div className="space-y-1">{children}</div>}
    </div>
  );
}

// --- Classify added media into grouped collections ---

interface MediaCollection {
  composited: MediaGroup[];
  overlays: MediaGroup[];
  transitions: MediaGroup[];
  audio: MediaGroup[];
  other: MediaGroup[];
}

function classifyMedia(addedMedia: AddedMedia[]): MediaCollection {
  const classified = {
    composited: [] as { media: AddedMedia; index: number }[],
    overlays: [] as { media: AddedMedia; index: number }[],
    transitions: [] as { media: AddedMedia; index: number }[],
    audio: [] as { media: AddedMedia; index: number }[],
    other: [] as { media: AddedMedia; index: number }[],
  };

  addedMedia.forEach((m, i) => {
    const entry = { media: m, index: i };
    if (m.placement === "composited") {
      classified.composited.push(entry);
    } else if (m.overlay_at_marker || m.has_alpha) {
      classified.overlays.push(entry);
    } else if (m.placement === "end_of_unit" || m.filename.toLowerCase().includes("transition")) {
      classified.transitions.push(entry);
    } else if (m.type === "audio") {
      classified.audio.push(entry);
    } else {
      classified.other.push(entry);
    }
  });

  return {
    composited: groupMediaVariants(classified.composited),
    overlays: groupMediaVariants(classified.overlays),
    transitions: groupMediaVariants(classified.transitions),
    audio: groupMediaVariants(classified.audio),
    other: groupMediaVariants(classified.other),
  };
}

function totalFiles(groups: MediaGroup[]): number {
  return groups.reduce((sum, g) => sum + g.variants.length, 0);
}

// --- Composited output card with version history ---

function CompositedOutputCard({ group, onPlay, onRemove }: {
  group: MediaGroup;
  onPlay: (variant: MediaVariant) => void;
  onRemove: (variant: MediaVariant) => void;
}) {
  const [showHistory, setShowHistory] = useState(false);

  // Sort variants by added_at descending (latest first)
  const sorted = [...group.variants].sort((a, b) => {
    const da = a.media.added_at || "";
    const db = b.media.added_at || "";
    return db.localeCompare(da);
  });

  const latest = sorted[0];
  const history = sorted.slice(1);

  if (!latest) return null;

  const formatDate = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
        " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    } catch { return iso; }
  };

  return (
    <div className="rounded-md bg-cp-bg-surface mb-1 overflow-hidden">
      {/* Latest render */}
      <div className="p-2.5 space-y-1.5">
        <div className="flex items-center gap-3">
          <button
            onClick={() => onPlay(latest)}
            className="relative w-9 h-9 rounded bg-cp-primary/10 flex items-center justify-center shrink-0 hover:bg-cp-primary/20 transition-colors"
          >
            <Play className="w-4 h-4 fill-cp-primary text-cp-primary" />
          </button>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">{latest.media.filename}</div>
            <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-cp-text-muted mt-0.5">
              {latest.media.duration_seconds != null && <span>{latest.media.duration_seconds.toFixed(1)}s</span>}
              {latest.media.width && latest.media.height && (
                <span>{latest.media.width}x{latest.media.height}</span>
              )}
              <span>{formatDate(latest.media.added_at)}</span>
            </div>
          </div>
          <button
            onClick={() => onRemove(latest)}
            className="shrink-0 p-1.5 rounded text-cp-text-muted hover:text-cp-error hover:bg-cp-error/20 transition-colors"
            title="Remove render"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        {latest.media.notes && (
          <div className="text-[10px] text-cp-text-muted pl-12 truncate">{latest.media.notes}</div>
        )}
      </div>

      {/* Version history */}
      {history.length > 0 && (
        <div className="border-t border-cp-border/50">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="flex items-center gap-1.5 w-full px-2.5 py-1.5 text-[10px] text-cp-text-muted hover:text-cp-text-secondary transition-colors"
          >
            {showHistory
              ? <ChevronDown className="w-3 h-3" />
              : <ChevronRightIcon className="w-3 h-3" />
            }
            {history.length} previous render{history.length !== 1 ? "s" : ""}
          </button>
          {showHistory && (
            <div className="px-2.5 pb-2 space-y-1">
              {history.map((v) => (
                <div key={v.index} className="flex items-center gap-2 text-[10px] text-cp-text-muted opacity-70">
                  <button
                    onClick={() => onPlay(v)}
                    className="p-1 rounded hover:bg-cp-bg transition-colors"
                  >
                    <Play className="w-3 h-3" />
                  </button>
                  <span className="truncate flex-1">{v.media.filename}</span>
                  <span className="shrink-0">{formatDate(v.media.added_at)}</span>
                  <button
                    onClick={() => onRemove(v)}
                    className="p-1 rounded hover:text-cp-error transition-colors"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// --- Main component ---

export function ElementsTab({
  unitManifest,
  unit,
  loading,
  error,
  discardedClips,
  clipEdits,
  wordCuts,
  addedMedia,
  availableUnits,
  markers,
  onRemoveMedia,
  onPlayClip,
  onDropFiles,
  onToggleDiscard,
  onMoveClip,
  onSeekToMarker,
}: ElementsTabProps) {
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) onDropFiles(files);
    },
    [onDropFiles],
  );

  // Count word cuts per clip
  const wordCutsByClip = useMemo(() => {
    const counts = new Map<string, number>();
    for (const wc of wordCuts) {
      counts.set(wc.clip_id, (counts.get(wc.clip_id) || 0) + 1);
    }
    return counts;
  }, [wordCuts]);

  // Classify and group added media
  const collections = useMemo(() => classifyMedia(addedMedia), [addedMedia]);

  if (!unit) {
    return (
      <div className="h-full flex items-center justify-center text-cp-text-muted text-sm">
        Select a unit to see its elements
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-cp-text-muted text-sm">
        Loading unit data...
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-cp-error text-sm">
        {error}
      </div>
    );
  }

  const clips = unitManifest?.clips || [];
  const activeClips = clips.filter((c) => !discardedClips.includes(c.id));
  const discardedClipList = clips.filter((c) => discardedClips.includes(c.id));

  const makePlayId = (m: AddedMedia) =>
    `added_${m.filename.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_")}`;

  const renderGroupedMedia = (groups: MediaGroup[]) => {
    return groups.map((group) => {
      const bestVariant = pickBestPlayable(group.variants);
      return (
        <GroupedMediaCard
          key={group.stem}
          group={group}
          markers={markers}
          onPlay={() => onPlayClip(makePlayId(bestVariant.media))}
          onRemove={() => {
            // Remove all variants in descending index order — safe with React 18 batched functional updaters
            const indices = group.variants.map((v) => v.index).sort((a, b) => b - a);
            indices.forEach((i) => onRemoveMedia(i));
          }}
          onSeekToMarker={onSeekToMarker}
        />
      );
    });
  };

  return (
    <div
      className="h-full overflow-y-auto p-4 space-y-3"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Source footage */}
      {activeClips.length > 0 && (
        <CollectionSection title="Source Footage" icon={FileVideo} groupCount={activeClips.length} fileCount={activeClips.length}>
          {activeClips.map((clip) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              discarded={false}
              clipEdit={clipEdits?.[clip.id]}
              wordCutCount={wordCutsByClip.get(clip.id) || 0}
              availableUnits={availableUnits}
              onPlay={() => onPlayClip(clip.id)}
              onToggleDiscard={() => onToggleDiscard(clip.id)}
              onMoveClip={onMoveClip ? (toUnitId) => onMoveClip(clip.id, toUnitId) : undefined}
            />
          ))}
        </CollectionSection>
      )}

      {/* Composited Output */}
      {collections.composited.length > 0 && (
        <CollectionSection
          title="Composited Output"
          icon={Film}
          groupCount={collections.composited.length}
          fileCount={totalFiles(collections.composited)}
        >
          {collections.composited.map((group) => (
            <CompositedOutputCard
              key={group.stem}
              group={group}
              onPlay={(v) => onPlayClip(makePlayId(v.media))}
              onRemove={(v) => onRemoveMedia(v.index)}
            />
          ))}
        </CollectionSection>
      )}

      {/* Overlays */}
      <CollectionSection title="Overlays" icon={Sparkles} groupCount={collections.overlays.length} fileCount={totalFiles(collections.overlays)}>
        {renderGroupedMedia(collections.overlays)}
      </CollectionSection>

      {/* Transitions */}
      <CollectionSection title="Transitions" icon={ArrowRightLeft} groupCount={collections.transitions.length} fileCount={totalFiles(collections.transitions)}>
        {renderGroupedMedia(collections.transitions)}
      </CollectionSection>

      {/* Audio */}
      <CollectionSection title="Audio" icon={Volume2} groupCount={collections.audio.length} fileCount={totalFiles(collections.audio)}>
        {renderGroupedMedia(collections.audio)}
      </CollectionSection>

      {/* Other added media */}
      <CollectionSection title="Other Media" icon={Layers} groupCount={collections.other.length} fileCount={totalFiles(collections.other)}>
        {renderGroupedMedia(collections.other)}
      </CollectionSection>

      {/* Discarded */}
      {discardedClipList.length > 0 && (
        <CollectionSection title="Discarded" icon={X} groupCount={discardedClipList.length} fileCount={discardedClipList.length} defaultOpen={false}>
          {discardedClipList.map((clip) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              discarded={true}
              wordCutCount={0}
              onPlay={() => onPlayClip(clip.id)}
              onToggleDiscard={() => onToggleDiscard(clip.id)}
            />
          ))}
        </CollectionSection>
      )}

      {clips.length === 0 && addedMedia.length === 0 && (
        <div className="text-center text-cp-text-muted text-sm py-8">
          No clips in this unit
        </div>
      )}

      {/* Drop zone */}
      <div className="border-2 border-dashed border-cp-border rounded-md p-6 text-center hover:border-cp-primary transition-colors">
        <Upload className="w-6 h-6 mx-auto mb-2 text-cp-text-muted" />
        <p className="text-sm text-cp-text-muted">Drop files to add media</p>
      </div>
    </div>
  );
}
