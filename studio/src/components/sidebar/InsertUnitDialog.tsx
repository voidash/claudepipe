import { useState } from "react";
import type { EditUnit } from "../../types/edit-manifest";
import { initUnit } from "../../api/client";

interface InsertUnitDialogProps {
  open: boolean;
  onClose: () => void;
  onInsert: (unitId: string, unit: EditUnit) => void;
  afterIndex: number;
}

export function InsertUnitDialog({ open, onClose, onInsert, afterIndex }: InsertUnitDialogProps) {
  const [name, setName] = useState("");
  const [unitType, setUnitType] = useState<EditUnit["unit_type"]>("video");
  const [instructions, setInstructions] = useState("");
  const [pipelineRequested, setPipelineRequested] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || submitting) return;

    const slug = name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_|_$/g, "")
      .slice(0, 30);
    const unitId = `unit_ins_${unitType}_${slug}_${Date.now()}`;

    // If pipeline requested, create unit directory on disk first
    if (pipelineRequested) {
      setSubmitting(true);
      setError(null);
      try {
        await initUnit(unitId, unitType, name.trim());
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to initialize unit directory";
        setError(msg);
        setSubmitting(false);
        return;
      }
      setSubmitting(false);
    }

    const unit: EditUnit = {
      display_name: name.trim(),
      unit_type: unitType,
      instructions,
      bundle_clip_ids: [],
      added_media: [],
      markers: [],
      word_cuts: [],
      discarded_clips: [],
      clip_edits: {},
      pipeline_requested: pipelineRequested,
      is_inserted: true,
      status: "draft",
    };

    onInsert(unitId, unit);
    setName("");
    setInstructions("");
    setPipelineRequested(false);
    setError(null);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-cp-bg-elevated border border-cp-border rounded-lg w-[420px] p-5">
        <h2 className="text-lg font-heading font-semibold mb-4">Insert Unit</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-cp-text-secondary mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-cp-bg border border-cp-border rounded px-3 py-1.5 text-sm focus:border-cp-primary outline-none"
              placeholder="e.g. B-Roll City Skyline"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm text-cp-text-secondary mb-1">Type</label>
            <select
              value={unitType}
              onChange={(e) => setUnitType(e.target.value as EditUnit["unit_type"])}
              className="w-full bg-cp-bg border border-cp-border rounded px-3 py-1.5 text-sm focus:border-cp-primary outline-none"
            >
              <option value="video">Video</option>
              <option value="screencast">Screencast</option>
              <option value="audio">Audio</option>
              <option value="text_image">Text / Image</option>
              <option value="animation">Animation</option>
            </select>
          </div>

          <div>
            <label className="block text-sm text-cp-text-secondary mb-1">Instructions</label>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              className="w-full bg-cp-bg border border-cp-border rounded px-3 py-1.5 text-sm focus:border-cp-primary outline-none resize-none h-20"
              placeholder="Instructions for Claude..."
            />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={pipelineRequested}
              onChange={(e) => setPipelineRequested(e.target.checked)}
              className="accent-cp-primary"
            />
            Request pipeline analysis
          </label>

          {error && (
            <div className="text-xs text-cp-error bg-cp-error/10 border border-cp-error/30 rounded px-3 py-2">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-1.5 text-sm rounded border border-cp-border hover:bg-cp-bg-surface disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || submitting}
              className="px-4 py-1.5 text-sm rounded bg-cp-primary hover:bg-cp-primary-hover disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? "Creating..." : "Insert"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
