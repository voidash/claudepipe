import type { EditUnit, Marker, WordCut } from "./edit-manifest";

export type EditOperation =
  | { type: "update_unit_order"; order: string[] }
  | { type: "update_unit_instructions"; unit_id: string; instructions: string }
  | { type: "update_unit_markers"; unit_id: string; markers: Marker[] }
  | { type: "update_unit_word_cuts"; unit_id: string; cuts: WordCut[] }
  | { type: "toggle_discard_clip"; unit_id: string; clip_id: string }
  | { type: "add_unit_media"; unit_id: string; media: { path: string; filename: string; type: string } }
  | { type: "remove_unit_media"; unit_id: string; media_index: number }
  | { type: "insert_unit"; unit_id: string; unit: EditUnit; after_index: number }
  | { type: "delete_unit"; unit_id: string }
  | { type: "update_clip_trim"; unit_id: string; clip_id: string; in_point: number; out_point: number; duration: number }
  | { type: "clear_clip_trim"; unit_id: string; clip_id: string }
  | { type: "split_clip_at"; unit_id: string; clip_id: string; time: number }
  | { type: "remove_split"; unit_id: string; clip_id: string; index: number }
  | { type: "add_deleted_range"; unit_id: string; clip_id: string; start: number; end: number; reason: string }
  | { type: "remove_deleted_range"; unit_id: string; clip_id: string; index: number }
  | { type: "move_clip_to_unit"; clip_id: string; from_unit_id: string; to_unit_id: string }
  | { type: "end_session" }
  | { type: "set_claude_note"; unit_id: string; notes: string }
  | { type: "batch"; operations: EditOperation[] };
