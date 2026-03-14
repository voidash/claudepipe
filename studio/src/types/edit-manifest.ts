// Edit manifest schema — studio reads/writes, Claude reads/writes

export interface EditManifest {
  version: string;
  source_manifest_path: string;
  created: string;
  last_synced: string;
  unit_order: string[];
  units: Record<string, EditUnit>;
  claude_notes: Record<string, ClaudeNote>;
  clip_moves: ClipMove[];
  session: Session;
}

export interface WordCut {
  id: string;
  clip_id: string;
  start: number;
  end: number;
  text: string;
}

export interface TrimRange {
  in: number;
  out: number;
  original_in?: number;
  original_out?: number;
}

export interface SplitPoint {
  at: number;
  produces: [string, string];
}

export interface DeletedRange {
  start: number;
  end: number;
  reason: string;
}

export interface ClipEdit {
  trim?: TrimRange;
  splits?: SplitPoint[];
  deleted_ranges?: DeletedRange[];
}

export interface ClipMove {
  clip_id: string;
  from_unit: string;
  to_unit: string;
  moved_at: string;
}

export interface EditUnit {
  display_name: string;
  unit_type: string;
  instructions: string;
  bundle_clip_ids: string[];
  added_media: AddedMedia[];
  markers: Marker[];
  word_cuts: WordCut[];
  discarded_clips: string[];
  clip_edits: Record<string, ClipEdit>;
  pipeline_requested: boolean;
  is_inserted: boolean;
  status: "draft" | "reviewing" | "approved";
}

export interface AddedMedia {
  path: string;
  filename: string;
  type: string;
  added_at: string;
  codec_video?: string;
  has_alpha?: boolean;
  pix_fmt?: string;
  duration_seconds?: number;
  width?: number;
  height?: number;
  fps?: number;
  overlay_at_marker?: string;
  notes?: string;
  replaces?: string;
  placement?: string;
  sfx_cue?: string;
}

export interface Marker {
  id: string;
  name: string;
  time: number;
  frame_number: number;
  position: { x: number; y: number } | null;
  type: "spatial" | "temporal";
  source_clip_id: string;
}

export interface ClaudeNote {
  notes: string;
  updated: string;
}

export interface Session {
  started: string;
  ended: string | null;
  active: boolean;
}

export function createEmptyEditManifest(sourceManifestPath: string): EditManifest {
  return {
    version: "1.0.0",
    source_manifest_path: sourceManifestPath,
    created: new Date().toISOString(),
    last_synced: new Date().toISOString(),
    unit_order: [],
    units: {},
    claude_notes: {},
    clip_moves: [],
    session: {
      started: new Date().toISOString(),
      ended: null,
      active: true,
    },
  };
}
