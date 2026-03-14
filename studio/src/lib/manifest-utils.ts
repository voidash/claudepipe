import type { FootageManifest, UnitEntry, Clip, TimelineSegment } from "../types/manifest";
import type { EditManifest } from "../types/edit-manifest";
import { createEmptyEditManifest } from "../types/edit-manifest";

export function buildEditManifestFromFootage(manifest: FootageManifest): EditManifest {
  const edit = createEmptyEditManifest("footage_manifest.json");

  if (!manifest.units || manifest.units.length === 0) {
    return edit;
  }

  for (const unit of manifest.units) {
    edit.unit_order.push(unit.unit_id);
    edit.units[unit.unit_id] = {
      display_name: unit.display_name,
      unit_type: unit.type,
      instructions: "",
      bundle_clip_ids: unit.clip_ids,
      added_media: [],
      markers: [],
      word_cuts: [],
      discarded_clips: [],
      clip_edits: {},
      pipeline_requested: false,
      is_inserted: false,
      status: "draft",
    };
  }

  return edit;
}

export function getUnitClips(manifest: FootageManifest, unit: UnitEntry): Clip[] {
  return manifest.clips.filter((c) => unit.clip_ids.includes(c.id));
}

export function getUnitSegments(manifest: FootageManifest, unit: UnitEntry): TimelineSegment[] {
  return manifest.timeline.segments.filter((s) => unit.clip_ids.includes(s.clip_id));
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const f = Math.floor((seconds % 1) * 30); // assume 30fps

  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}:${String(f).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}:${String(f).padStart(2, "0")}`;
}

export function formatTimecode(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function unitTypeIcon(type: string): string {
  switch (type) {
    case "video": return "Video";
    case "screencast": return "Monitor";
    case "audio": return "Mic";
    case "text_image": return "Type";
    case "animation": return "Sparkles";
    default: return "FileVideo";
  }
}
