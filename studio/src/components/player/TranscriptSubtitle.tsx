import { useMemo } from "react";
import type { TranscriptSegment } from "../../types/manifest";

interface TranscriptSubtitleProps {
  segments: TranscriptSegment[];
  currentTime: number;
}

export function TranscriptSubtitle({ segments, currentTime }: TranscriptSubtitleProps) {
  const activeSegment = useMemo(() => {
    return segments.find((s) => currentTime >= s.start && currentTime <= s.end);
  }, [segments, currentTime]);

  if (!activeSegment) return null;

  return (
    <div className="px-4 py-1 text-center bg-black/80">
      <span className="text-sm text-cp-text">
        {activeSegment.text}
      </span>
      <span className="ml-2 text-xs text-cp-text-muted uppercase">
        {activeSegment.language}
      </span>
    </div>
  );
}
