import type { EditManifest, ClipEdit, ClipMove } from "../types/edit-manifest";
import type { EditOperation } from "../types/edit-operations";

export type ApplyResult =
  | { ok: true; manifest: EditManifest }
  | { ok: false; error: string };

function ensureUnit(manifest: EditManifest, unitId: string): string | null {
  if (!manifest.units[unitId]) return `Unit not found: ${unitId}`;
  return null;
}

function getOrCreateClipEdit(unit: EditManifest["units"][string], clipId: string): ClipEdit {
  return unit.clip_edits?.[clipId] ?? {};
}

export function applyOperation(manifest: EditManifest, operation: EditOperation): ApplyResult {
  switch (operation.type) {
    case "update_unit_order":
      return { ok: true, manifest: { ...manifest, unit_order: operation.order } };

    case "update_unit_instructions": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: { ...manifest.units[operation.unit_id], instructions: operation.instructions },
          },
        },
      };
    }

    case "update_unit_markers": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: { ...manifest.units[operation.unit_id], markers: operation.markers },
          },
        },
      };
    }

    case "update_unit_word_cuts": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: { ...manifest.units[operation.unit_id], word_cuts: operation.cuts },
          },
        },
      };
    }

    case "toggle_discard_clip": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      const existing = unit.discarded_clips || [];
      const isDiscarded = existing.includes(operation.clip_id);
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: {
              ...unit,
              discarded_clips: isDiscarded
                ? existing.filter((id) => id !== operation.clip_id)
                : [...existing, operation.clip_id],
            },
          },
        },
      };
    }

    case "add_unit_media": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: {
              ...unit,
              added_media: [
                ...(unit.added_media || []),
                { ...operation.media, added_at: new Date().toISOString() },
              ],
            },
          },
        },
      };
    }

    case "remove_unit_media": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      const existing = unit.added_media || [];
      if (operation.media_index < 0 || operation.media_index >= existing.length) {
        return { ok: false, error: `Media index out of bounds: ${operation.media_index}` };
      }
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: {
              ...unit,
              added_media: existing.filter((_, i) => i !== operation.media_index),
            },
          },
        },
      };
    }

    case "insert_unit": {
      const newOrder = [...manifest.unit_order];
      newOrder.splice(operation.after_index + 1, 0, operation.unit_id);
      return {
        ok: true,
        manifest: {
          ...manifest,
          unit_order: newOrder,
          units: { ...manifest.units, [operation.unit_id]: operation.unit },
        },
      };
    }

    case "delete_unit": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const newOrder = manifest.unit_order.filter((id) => id !== operation.unit_id);
      const newUnits = { ...manifest.units };
      delete newUnits[operation.unit_id];
      return { ok: true, manifest: { ...manifest, unit_order: newOrder, units: newUnits } };
    }

    case "update_clip_trim": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      const existing = unit.clip_edits || {};
      const clipEdit = getOrCreateClipEdit(unit, operation.clip_id);
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: {
              ...unit,
              clip_edits: {
                ...existing,
                [operation.clip_id]: {
                  ...clipEdit,
                  trim: {
                    in: operation.in_point,
                    out: operation.out_point,
                    original_in: clipEdit.trim?.original_in ?? 0,
                    original_out: clipEdit.trim?.original_out ?? operation.duration,
                  },
                },
              },
            },
          },
        },
      };
    }

    case "clear_clip_trim": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      const existing = unit.clip_edits || {};
      const clipEdit = existing[operation.clip_id];
      if (!clipEdit?.trim) return { ok: true, manifest };
      const { trim: _, ...rest } = clipEdit;
      const hasOtherEdits = Object.keys(rest).some((k) => {
        const val = rest[k as keyof typeof rest];
        return Array.isArray(val) ? val.length > 0 : val != null;
      });
      const newEdits = { ...existing };
      if (hasOtherEdits) {
        newEdits[operation.clip_id] = rest;
      } else {
        delete newEdits[operation.clip_id];
      }
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: { ...unit, clip_edits: newEdits },
          },
        },
      };
    }

    case "split_clip_at": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      const existing = unit.clip_edits || {};
      const clipEdit = getOrCreateClipEdit(unit, operation.clip_id);
      const splits = clipEdit.splits || [];
      // Don't add duplicate splits at the same position (within 0.1s)
      if (splits.some((s) => Math.abs(s.at - operation.time) < 0.1)) {
        return { ok: true, manifest };
      }
      const splitIndex = splits.length;
      const newSplit = {
        at: operation.time,
        produces: [`${operation.clip_id}_${splitIndex}a`, `${operation.clip_id}_${splitIndex}b`] as [string, string],
      };
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: {
              ...unit,
              clip_edits: {
                ...existing,
                [operation.clip_id]: {
                  ...clipEdit,
                  splits: [...splits, newSplit],
                },
              },
            },
          },
        },
      };
    }

    case "remove_split": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      const existing = unit.clip_edits || {};
      const clipEdit = existing[operation.clip_id];
      if (!clipEdit?.splits || operation.index < 0 || operation.index >= clipEdit.splits.length) {
        return { ok: false, error: `Split index out of bounds: ${operation.index}` };
      }
      const newSplits = clipEdit.splits.filter((_, i) => i !== operation.index);
      const { splits: _, ...rest } = clipEdit;
      const newClipEdit = newSplits.length > 0 ? { ...rest, splits: newSplits } : rest;
      const hasEdits = Object.keys(newClipEdit).some((k) => {
        const val = newClipEdit[k as keyof typeof newClipEdit];
        return Array.isArray(val) ? val.length > 0 : val != null;
      });
      const newEdits = { ...existing };
      if (hasEdits) {
        newEdits[operation.clip_id] = newClipEdit;
      } else {
        delete newEdits[operation.clip_id];
      }
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: { ...manifest.units, [operation.unit_id]: { ...unit, clip_edits: newEdits } },
        },
      };
    }

    case "add_deleted_range": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      const existing = unit.clip_edits || {};
      const clipEdit = getOrCreateClipEdit(unit, operation.clip_id);
      const ranges = clipEdit.deleted_ranges || [];
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: {
              ...unit,
              clip_edits: {
                ...existing,
                [operation.clip_id]: {
                  ...clipEdit,
                  deleted_ranges: [...ranges, { start: operation.start, end: operation.end, reason: operation.reason }],
                },
              },
            },
          },
        },
      };
    }

    case "remove_deleted_range": {
      const err = ensureUnit(manifest, operation.unit_id);
      if (err) return { ok: false, error: err };
      const unit = manifest.units[operation.unit_id];
      const existing = unit.clip_edits || {};
      const clipEdit = getOrCreateClipEdit(unit, operation.clip_id);
      const ranges = clipEdit.deleted_ranges || [];
      if (operation.index < 0 || operation.index >= ranges.length) {
        return { ok: false, error: `Deleted range index out of bounds: ${operation.index}` };
      }
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.unit_id]: {
              ...unit,
              clip_edits: {
                ...existing,
                [operation.clip_id]: {
                  ...clipEdit,
                  deleted_ranges: ranges.filter((_, i) => i !== operation.index),
                },
              },
            },
          },
        },
      };
    }

    case "move_clip_to_unit": {
      const errFrom = ensureUnit(manifest, operation.from_unit_id);
      if (errFrom) return { ok: false, error: errFrom };
      const errTo = ensureUnit(manifest, operation.to_unit_id);
      if (errTo) return { ok: false, error: errTo };
      if (operation.from_unit_id === operation.to_unit_id) return { ok: true, manifest };
      const fromUnit = manifest.units[operation.from_unit_id];
      const toUnit = manifest.units[operation.to_unit_id];
      const fromClips = (fromUnit.bundle_clip_ids || []).filter((id) => id !== operation.clip_id);
      const toClips = [...(toUnit.bundle_clip_ids || []), operation.clip_id];
      const move: ClipMove = {
        clip_id: operation.clip_id,
        from_unit: operation.from_unit_id,
        to_unit: operation.to_unit_id,
        moved_at: new Date().toISOString(),
      };
      return {
        ok: true,
        manifest: {
          ...manifest,
          units: {
            ...manifest.units,
            [operation.from_unit_id]: { ...fromUnit, bundle_clip_ids: fromClips },
            [operation.to_unit_id]: { ...toUnit, bundle_clip_ids: toClips },
          },
          clip_moves: [...(manifest.clip_moves || []), move],
        },
      };
    }

    case "end_session":
      return {
        ok: true,
        manifest: {
          ...manifest,
          session: {
            ...manifest.session,
            ended: new Date().toISOString(),
            active: false,
          },
        },
      };

    case "set_claude_note": {
      return {
        ok: true,
        manifest: {
          ...manifest,
          claude_notes: {
            ...manifest.claude_notes,
            [operation.unit_id]: {
              notes: operation.notes,
              updated: new Date().toISOString(),
            },
          },
        },
      };
    }

    case "batch": {
      let current = manifest;
      for (const op of operation.operations) {
        const result = applyOperation(current, op);
        if (!result.ok) return result;
        current = result.manifest;
      }
      return { ok: true, manifest: current };
    }

    default:
      return { ok: false, error: `Unknown operation type: ${(operation as { type: string }).type}` };
  }
}
