import { useState, useCallback, useRef, useEffect } from "react";
import type { EditManifest, EditUnit, Marker, WordCut } from "../types/edit-manifest";
import type { EditOperation } from "../types/edit-operations";
import { patchEditManifest, initializeEditManifest, fetchEditManifest } from "../api/client";
import { applyOperation } from "../lib/apply-operation";

interface UseEditManifestResult {
  editManifest: EditManifest | null;
  loading: boolean;
  error: string | null;
  saving: boolean;
  updateUnitOrder: (order: string[]) => void;
  updateUnitInstructions: (unitId: string, instructions: string) => void;
  updateUnitMarkers: (unitId: string, markers: Marker[]) => void;
  updateUnitWordCuts: (unitId: string, cuts: WordCut[]) => void;
  toggleDiscardClip: (unitId: string, clipId: string) => void;
  addUnitMedia: (unitId: string, media: { path: string; filename: string; type: string }) => void;
  removeUnitMedia: (unitId: string, mediaIndex: number) => void;
  insertUnit: (unitId: string, unit: EditUnit, afterIndex: number) => void;
  deleteUnit: (unitId: string) => void;
  updateClipTrim: (unitId: string, clipId: string, inPoint: number, outPoint: number, duration: number) => void;
  clearClipTrim: (unitId: string, clipId: string) => void;
  splitClipAt: (unitId: string, clipId: string, time: number) => void;
  removeSplit: (unitId: string, clipId: string, index: number) => void;
  addDeletedRange: (unitId: string, clipId: string, start: number, end: number, reason: string) => void;
  removeDeletedRange: (unitId: string, clipId: string, index: number) => void;
  moveClipToUnit: (clipId: string, fromUnitId: string, toUnitId: string) => void;
  endSession: () => Promise<void>;
  initialize: () => void;
}

export function useEditManifest(): UseEditManifestResult {
  const [editManifest, setEditManifest] = useState<EditManifest | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Ref tracks the latest manifest so dispatch can read it without
  // being in the dependency array (keeps dispatch stable).
  const manifestRef = useRef<EditManifest | null>(null);
  useEffect(() => {
    manifestRef.current = editManifest;
  }, [editManifest]);

  const initialize = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const manifest = await initializeEditManifest();
      setEditManifest(manifest);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to initialize edit manifest");
    } finally {
      setLoading(false);
    }
  }, []);

  // Core dispatch: optimistic local apply + server persist.
  // Side effects (patchEditManifest) are OUTSIDE the setState updater
  // to avoid StrictMode double-firing them.
  const dispatch = useCallback((operation: EditOperation) => {
    const prev = manifestRef.current;
    if (!prev) return;

    const result = applyOperation(prev, operation);
    if (!result.ok) {
      setError(result.error);
      return;
    }

    // Optimistic update
    setEditManifest(result.manifest);
    manifestRef.current = result.manifest;

    // Persist to server
    setSaving(true);
    patchEditManifest(operation)
      .then(() => {
        setError(null);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Operation failed");
        fetchEditManifest()
          .then((current) => {
            if (current) {
              setEditManifest(current);
              manifestRef.current = current;
            }
          })
          .catch(() => {
            // Refetch also failed — keep optimistic state, show error
          });
      })
      .finally(() => {
        setSaving(false);
      });
  }, []);

  // Thin wrappers — each mutation is a one-liner
  const updateUnitOrder = useCallback(
    (order: string[]) => dispatch({ type: "update_unit_order", order }),
    [dispatch],
  );

  const updateUnitInstructions = useCallback(
    (unitId: string, instructions: string) =>
      dispatch({ type: "update_unit_instructions", unit_id: unitId, instructions }),
    [dispatch],
  );

  const updateUnitMarkers = useCallback(
    (unitId: string, markers: Marker[]) =>
      dispatch({ type: "update_unit_markers", unit_id: unitId, markers }),
    [dispatch],
  );

  const updateUnitWordCuts = useCallback(
    (unitId: string, cuts: WordCut[]) =>
      dispatch({ type: "update_unit_word_cuts", unit_id: unitId, cuts }),
    [dispatch],
  );

  const toggleDiscardClip = useCallback(
    (unitId: string, clipId: string) =>
      dispatch({ type: "toggle_discard_clip", unit_id: unitId, clip_id: clipId }),
    [dispatch],
  );

  const addUnitMedia = useCallback(
    (unitId: string, media: { path: string; filename: string; type: string }) =>
      dispatch({ type: "add_unit_media", unit_id: unitId, media }),
    [dispatch],
  );

  const removeUnitMedia = useCallback(
    (unitId: string, mediaIndex: number) =>
      dispatch({ type: "remove_unit_media", unit_id: unitId, media_index: mediaIndex }),
    [dispatch],
  );

  const insertUnit = useCallback(
    (unitId: string, unit: EditUnit, afterIndex: number) =>
      dispatch({ type: "insert_unit", unit_id: unitId, unit, after_index: afterIndex }),
    [dispatch],
  );

  const deleteUnit = useCallback(
    (unitId: string) => dispatch({ type: "delete_unit", unit_id: unitId }),
    [dispatch],
  );

  const updateClipTrim = useCallback(
    (unitId: string, clipId: string, inPoint: number, outPoint: number, duration: number) =>
      dispatch({ type: "update_clip_trim", unit_id: unitId, clip_id: clipId, in_point: inPoint, out_point: outPoint, duration }),
    [dispatch],
  );

  const clearClipTrim = useCallback(
    (unitId: string, clipId: string) =>
      dispatch({ type: "clear_clip_trim", unit_id: unitId, clip_id: clipId }),
    [dispatch],
  );

  const splitClipAt = useCallback(
    (unitId: string, clipId: string, time: number) =>
      dispatch({ type: "split_clip_at", unit_id: unitId, clip_id: clipId, time }),
    [dispatch],
  );

  const removeSplit = useCallback(
    (unitId: string, clipId: string, index: number) =>
      dispatch({ type: "remove_split", unit_id: unitId, clip_id: clipId, index }),
    [dispatch],
  );

  const addDeletedRange = useCallback(
    (unitId: string, clipId: string, start: number, end: number, reason: string) =>
      dispatch({ type: "add_deleted_range", unit_id: unitId, clip_id: clipId, start, end, reason }),
    [dispatch],
  );

  const removeDeletedRange = useCallback(
    (unitId: string, clipId: string, index: number) =>
      dispatch({ type: "remove_deleted_range", unit_id: unitId, clip_id: clipId, index }),
    [dispatch],
  );

  const moveClipToUnit = useCallback(
    (clipId: string, fromUnitId: string, toUnitId: string) =>
      dispatch({ type: "move_clip_to_unit", clip_id: clipId, from_unit_id: fromUnitId, to_unit_id: toUnitId }),
    [dispatch],
  );

  const endSession = useCallback(async () => {
    if (!editManifest) return;
    // End session is synchronous — we await the server response before returning
    setSaving(true);
    try {
      const serverManifest = await patchEditManifest({ type: "end_session" });
      setEditManifest(serverManifest);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to end session");
      throw err;
    } finally {
      setSaving(false);
    }
  }, [editManifest]);

  return {
    editManifest,
    loading,
    error,
    saving,
    updateUnitOrder,
    updateUnitInstructions,
    updateUnitMarkers,
    updateUnitWordCuts,
    toggleDiscardClip,
    addUnitMedia,
    removeUnitMedia,
    insertUnit,
    deleteUnit,
    updateClipTrim,
    clearClipTrim,
    splitClipAt,
    removeSplit,
    addDeletedRange,
    removeDeletedRange,
    moveClipToUnit,
    endSession,
    initialize,
  };
}
