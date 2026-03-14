import { useState, useEffect, useRef } from "react";
import type { EditUnit, ClaudeNote, Marker } from "../../types/edit-manifest";
import { ClaudeNotes } from "./ClaudeNotes";
import { MarkerReference } from "./MarkerReference";

interface InstructionsPanelProps {
  unitId: string | null;
  editUnit: EditUnit | null;
  claudeNote: ClaudeNote | null;
  markers: Marker[];
  onInstructionsChange: (unitId: string, instructions: string) => void;
  onMarkerSeek: (time: number) => void;
}

export function InstructionsPanel({
  unitId,
  editUnit,
  claudeNote,
  markers,
  onInstructionsChange,
  onMarkerSeek,
}: InstructionsPanelProps) {
  const [localInstructions, setLocalInstructions] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync local state when unit changes
  useEffect(() => {
    setLocalInstructions(editUnit?.instructions || "");
  }, [unitId, editUnit?.instructions]);

  const handleChange = (value: string) => {
    setLocalInstructions(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (unitId) onInstructionsChange(unitId, value);
    }, 500);
  };

  if (!unitId || !editUnit) {
    return (
      <div className="h-full flex items-center justify-center text-cp-text-muted text-sm">
        Select a unit to write instructions
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-cp-border bg-cp-bg-elevated">
        <h3 className="text-sm font-heading font-semibold">{editUnit.display_name}</h3>
        <span className="text-xs text-cp-text-muted">{editUnit.unit_type}</span>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Instructions textarea */}
        <div>
          <label className="block text-xs text-cp-text-secondary mb-1 font-medium">
            Instructions for Claude
          </label>
          <textarea
            value={localInstructions}
            onChange={(e) => handleChange(e.target.value)}
            className="w-full bg-cp-bg border border-cp-border rounded px-3 py-2 text-sm focus:border-cp-primary outline-none resize-none font-body"
            rows={6}
            placeholder="Tell Claude how to handle this unit...&#10;&#10;e.g. Switch to pixel camera on code sections. Add zoom effect at m1. Cut 5s of dead air around 0:32."
          />
        </div>

        {/* Marker reference */}
        <MarkerReference markers={markers} onSeek={onMarkerSeek} />

        {/* Claude notes */}
        <ClaudeNotes note={claudeNote} />
      </div>
    </div>
  );
}
