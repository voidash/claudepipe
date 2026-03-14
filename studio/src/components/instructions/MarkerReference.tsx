import { MapPin, Clock } from "lucide-react";
import type { Marker } from "../../types/edit-manifest";
import { formatTimecode } from "../../lib/manifest-utils";

interface MarkerReferenceProps {
  markers: Marker[];
  onSeek: (time: number) => void;
}

export function MarkerReference({ markers, onSeek }: MarkerReferenceProps) {
  if (markers.length === 0) return null;

  return (
    <div>
      <label className="block text-xs text-cp-text-secondary mb-1 font-medium">
        Markers
      </label>
      <div className="space-y-0.5">
        {markers.map((m) => (
          <button
            key={m.id}
            onClick={() => onSeek(m.time)}
            className="w-full flex items-center gap-2 px-2 py-1 text-xs hover:bg-cp-bg-surface rounded text-left"
          >
            {m.type === "spatial" ? (
              <MapPin className="w-3 h-3 text-cp-accent shrink-0" />
            ) : (
              <Clock className="w-3 h-3 text-cp-secondary shrink-0" />
            )}
            <span className="font-code text-cp-primary">{m.name}</span>
            <span className="text-cp-text-muted">
              {formatTimecode(m.time)}
              {m.position
                ? `, (${m.position.x.toFixed(2)}, ${m.position.y.toFixed(2)})`
                : ""}
            </span>
            <span className="ml-auto text-cp-text-muted">{m.type}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
