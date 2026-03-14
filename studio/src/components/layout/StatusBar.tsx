import { Loader2, Circle, CheckCircle2 } from "lucide-react";

interface StatusBarProps {
  saving: boolean;
  error: string | null;
  unitCount: number;
  markerMode: boolean;
}

export function StatusBar({
  saving,
  error,
  unitCount,
  markerMode,
}: StatusBarProps) {
  return (
    <div className="h-6 bg-cp-bg border-t border-cp-border flex items-center px-3 text-xs text-cp-text-muted gap-4 shrink-0">
      <span>{unitCount} units</span>

      {markerMode && (
        <span className="text-cp-accent flex items-center gap-1">
          <Circle className="w-2 h-2 fill-cp-accent" />
          Marker Mode
        </span>
      )}

      <div className="ml-auto flex items-center gap-3">
        {error && <span className="text-cp-error">{error}</span>}

        {saving && (
          <span className="flex items-center gap-1">
            <Loader2 className="w-3 h-3 animate-spin" />
            Saving...
          </span>
        )}

        {!saving && !error && (
          <span className="flex items-center gap-1 text-cp-success">
            <CheckCircle2 className="w-3 h-3" />
            Saved
          </span>
        )}
      </div>
    </div>
  );
}
