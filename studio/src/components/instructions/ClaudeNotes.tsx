import { useState } from "react";
import { ChevronDown, ChevronRight, Bot } from "lucide-react";
import type { ClaudeNote } from "../../types/edit-manifest";

interface ClaudeNotesProps {
  note: ClaudeNote | null;
}

export function ClaudeNotes({ note }: ClaudeNotesProps) {
  const [expanded, setExpanded] = useState(true);

  if (!note) return null;

  return (
    <div className="border border-cp-border rounded">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-cp-text-secondary hover:bg-cp-bg-surface"
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronRight className="w-3 h-3" />
        )}
        <Bot className="w-3 h-3 text-cp-secondary" />
        <span className="font-medium">Claude Notes</span>
        <span className="ml-auto text-cp-text-muted">
          {new Date(note.updated).toLocaleString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </button>

      {expanded && (
        <div className="px-3 py-2 text-sm text-cp-text-secondary border-t border-cp-border whitespace-pre-wrap">
          {note.notes}
        </div>
      )}
    </div>
  );
}
