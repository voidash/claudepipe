import { useRef, useCallback, useMemo } from "react";
import type { Marker, ClipEdit, WordCut } from "../../types/edit-manifest";

interface ScrubBarProps {
  currentTime: number;
  duration: number;
  markers: Marker[];
  markerMode: boolean;
  clipEdit?: ClipEdit;
  wordCuts?: WordCut[];
  clipId?: string;
  onSeek: (time: number) => void;
  onMarkerClick: (time: number) => void;
  onRemoveSplit?: (index: number) => void;
}

export function ScrubBar({
  currentTime,
  duration,
  markers,
  markerMode,
  clipEdit,
  wordCuts,
  clipId,
  onSeek,
  onMarkerClick,
  onRemoveSplit,
}: ScrubBarProps) {
  const barRef = useRef<HTMLDivElement>(null);

  const splits = clipEdit?.splits ?? [];
  const deletedRanges = clipEdit?.deleted_ranges ?? [];
  const trimIn = clipEdit?.trim?.in ?? 0;
  const trimOut = clipEdit?.trim?.out ?? duration;
  const hasTrim = clipEdit?.trim != null;

  const clipWordCuts = useMemo(
    () => (wordCuts ?? []).filter((wc) => clipId && wc.clip_id === clipId),
    [wordCuts, clipId],
  );

  const getTimeFromEvent = useCallback(
    (e: React.MouseEvent | MouseEvent) => {
      const bar = barRef.current;
      if (!bar || duration === 0) return 0;
      const rect = bar.getBoundingClientRect();
      const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      return x * duration;
    },
    [duration],
  );

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      const time = getTimeFromEvent(e);
      if (markerMode) {
        onMarkerClick(time);
      } else {
        onSeek(time);
      }
    },
    [getTimeFromEvent, markerMode, onMarkerClick, onSeek],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (markerMode) return;
      const onMouseMove = (ev: MouseEvent) => {
        const bar = barRef.current;
        if (!bar || duration === 0) return;
        const rect = bar.getBoundingClientRect();
        const x = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
        onSeek(x * duration);
      };
      const onMouseUp = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
      onSeek(getTimeFromEvent(e));
    },
    [duration, markerMode, onSeek, getTimeFromEvent],
  );

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="px-3 py-1.5 bg-cp-bg-elevated">
      <div
        ref={barRef}
        className="relative h-5 bg-cp-bg rounded cursor-pointer group"
        onClick={handleClick}
        onMouseDown={handleMouseDown}
      >
        {/* Trim region dimming — gray out regions outside [trim.in, trim.out] */}
        {hasTrim && duration > 0 && (
          <>
            {trimIn > 0 && (
              <div
                className="absolute top-0 h-full bg-cp-bg/60 pointer-events-none z-[1]"
                style={{ left: 0, width: `${(trimIn / duration) * 100}%` }}
                title={`Trimmed: 0 — ${trimIn.toFixed(2)}s`}
              />
            )}
            {trimOut < duration && (
              <div
                className="absolute top-0 h-full bg-cp-bg/60 pointer-events-none z-[1]"
                style={{ left: `${(trimOut / duration) * 100}%`, width: `${((duration - trimOut) / duration) * 100}%` }}
                title={`Trimmed: ${trimOut.toFixed(2)}s — ${duration.toFixed(2)}s`}
              />
            )}
          </>
        )}

        {/* Deleted ranges — red overlay */}
        {deletedRanges.map((range, i) => {
          if (duration === 0) return null;
          const left = (range.start / duration) * 100;
          const width = ((range.end - range.start) / duration) * 100;
          return (
            <div
              key={`del-${i}`}
              className="absolute top-0 h-full bg-cp-error/30 pointer-events-none z-[2]"
              style={{ left: `${left}%`, width: `${width}%` }}
              title={`Deleted: ${range.reason}`}
            />
          );
        })}

        {/* Word cut ranges — red overlay */}
        {clipWordCuts.map((wc) => {
          if (duration === 0) return null;
          const left = (wc.start / duration) * 100;
          const width = ((wc.end - wc.start) / duration) * 100;
          return (
            <div
              key={`wc-${wc.id}`}
              className="absolute top-0 h-full bg-cp-error/25 pointer-events-none z-[2]"
              style={{ left: `${left}%`, width: `${width}%` }}
              title={`Word cut: "${wc.text}"`}
            />
          );
        })}

        {/* Progress fill */}
        <div
          className="absolute left-0 top-0 h-full bg-cp-primary/40 rounded-l pointer-events-none"
          style={{ width: `${progress}%` }}
        />

        {/* Split markers — click to remove */}
        {splits.map((split, i) => {
          if (duration === 0) return null;
          const pos = (split.at / duration) * 100;
          return (
            <div
              key={`split-${i}`}
              className="absolute top-0 h-full z-[5] group/split"
              style={{ left: `calc(${pos}% - 4px)`, width: "8px" }}
              onClick={(e) => {
                e.stopPropagation();
                onRemoveSplit?.(i);
              }}
              title={`Split at ${split.at.toFixed(2)}s — click to remove`}
              role="button"
            >
              <div className="absolute left-1/2 top-0 w-px h-full bg-cp-accent group-hover/split:bg-cp-error transition-colors" />
              <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-cp-accent group-hover/split:bg-cp-error rotate-45 transition-colors cursor-pointer" />
            </div>
          );
        })}

        {/* Marker diamonds/flags */}
        {markers.map((marker) => {
          if (duration === 0) return null;
          const pos = (marker.time / duration) * 100;
          const isSpatial = marker.type === "spatial";
          return (
            <div
              key={marker.id}
              className="absolute top-1/2 -translate-y-1/2 pointer-events-none z-[3]"
              style={{ left: `${pos}%` }}
            >
              {isSpatial ? (
                <div className="w-2 h-2 bg-cp-accent rotate-45 -translate-x-1" />
              ) : (
                <div className="w-0 h-0 border-l-[4px] border-r-[4px] border-b-[6px] border-transparent border-b-cp-secondary -translate-x-1 -translate-y-0.5" />
              )}
            </div>
          );
        })}

        {/* Playhead */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-cp-primary rounded-full shadow pointer-events-none z-[4]"
          style={{ left: `calc(${progress}% - 6px)` }}
        />
      </div>
    </div>
  );
}
