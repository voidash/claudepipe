import { useState } from "react";
import { Trash2, MapPin, Clock } from "lucide-react";
import type { Marker } from "../../types/edit-manifest";
import { formatTimecode } from "../../lib/manifest-utils";
import { cn } from "../../lib/cn";

interface MarkerListProps {
  markers: Marker[];
  selectedMarkerId: string | null;
  onSelect: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onSeek: (time: number) => void;
}

export function MarkerList({
  markers,
  selectedMarkerId,
  onSelect,
  onRename,
  onDelete,
  onSeek,
}: MarkerListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  if (markers.length === 0) {
    return (
      <div className="text-xs text-cp-text-muted p-2">
        No markers. Press M to enter marker mode.
      </div>
    );
  }

  return (
    <div className="text-xs divide-y divide-cp-border">
      {markers.map((marker) => (
        <div
          key={marker.id}
          className={cn(
            "flex items-center gap-2 px-2 py-1.5 hover:bg-cp-bg-surface cursor-pointer",
            selectedMarkerId === marker.id && "bg-cp-bg-surface",
          )}
          onClick={() => {
            onSelect(marker.id);
            onSeek(marker.time);
          }}
        >
          {marker.type === "spatial" ? (
            <MapPin className="w-3 h-3 text-cp-accent shrink-0" />
          ) : (
            <Clock className="w-3 h-3 text-cp-secondary shrink-0" />
          )}

          {editingId === marker.id ? (
            <input
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onBlur={() => {
                if (editValue.trim()) onRename(marker.id, editValue.trim());
                setEditingId(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  if (editValue.trim()) onRename(marker.id, editValue.trim());
                  setEditingId(null);
                }
                if (e.key === "Escape") setEditingId(null);
              }}
              className="flex-1 bg-cp-bg border border-cp-border rounded px-1 py-0.5 text-xs outline-none"
              autoFocus
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <span
              className="flex-1 truncate"
              onDoubleClick={(e) => {
                e.stopPropagation();
                setEditingId(marker.id);
                setEditValue(marker.name);
              }}
            >
              {marker.name}
            </span>
          )}

          <span className="text-cp-text-muted tabular-nums shrink-0">
            {formatTimecode(marker.time)}
          </span>

          {marker.position && (
            <span className="text-cp-text-muted tabular-nums shrink-0">
              ({marker.position.x.toFixed(2)}, {marker.position.y.toFixed(2)})
            </span>
          )}

          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(marker.id);
            }}
            className="text-cp-text-muted hover:text-cp-error shrink-0"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      ))}
    </div>
  );
}
