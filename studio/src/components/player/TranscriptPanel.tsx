import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { Scissors } from "lucide-react";
import type { TranscriptData } from "../../api/client";
import type { WordCut } from "../../types/edit-manifest";
import { cn } from "../../lib/cn";

interface WordInfo {
  key: string;
  word: string;
  start: number;
  end: number;
  confidence: number;
  segmentIndex: number;
  wordIndex: number;
  language: string;
}

interface TranscriptPanelProps {
  transcript: TranscriptData | null;
  currentTime: number;
  clipId: string | null;
  wordCuts: WordCut[];
  onSeek: (time: number) => void;
  onWordCutsChange: (cuts: WordCut[]) => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TranscriptPanel({
  transcript,
  currentTime,
  clipId,
  wordCuts,
  onSeek,
  onWordCutsChange,
}: TranscriptPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeWordRef = useRef<HTMLSpanElement>(null);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [lastClickedKey, setLastClickedKey] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    words: WordInfo[];
  } | null>(null);

  // Flatten all words into a list and a lookup map.
  // Includes a repair pass for degenerate ASR timestamps (e.g. Chirp 2 producing
  // identical timestamps for many consecutive words when it loses track).
  const { allWords, wordMap } = useMemo(() => {
    if (!transcript?.segments) return { allWords: [] as WordInfo[], wordMap: new Map<string, WordInfo>() };
    const segments = transcript.segments;
    const words: WordInfo[] = [];
    const map = new Map<string, WordInfo>();

    segments.forEach((seg, si) => {
      if (!seg.words) return;
      const nextSegStart = si + 1 < segments.length ? segments[si + 1].start : null;

      // Build word infos for this segment
      const segWords: WordInfo[] = seg.words.map((w, wi) => ({
        key: `s${si}:w${wi}`,
        word: w.word,
        start: w.start,
        end: w.end,
        confidence: w.confidence,
        segmentIndex: si,
        wordIndex: wi,
        language: seg.language,
      }));

      // Repair: find the first degenerate word (duration > 30s or gap > 30s from prev)
      let firstBadIdx = -1;
      for (let i = 0; i < segWords.length; i++) {
        const prevEnd = i > 0 ? segWords[i - 1].end : seg.start;
        const wordDur = segWords[i].end - segWords[i].start;
        const gap = segWords[i].start - prevEnd;
        if (wordDur > 30 || gap > 30) {
          firstBadIdx = i;
          break;
        }
      }

      if (firstBadIdx >= 0) {
        const startBound = firstBadIdx > 0 ? segWords[firstBadIdx - 1].end : seg.start;
        const endBound = nextSegStart ?? startBound + (segWords.length - firstBadIdx) * 0.4;
        const count = segWords.length - firstBadIdx;
        const slotDur = (endBound - startBound) / count;
        for (let i = firstBadIdx; i < segWords.length; i++) {
          const offset = i - firstBadIdx;
          segWords[i] = {
            ...segWords[i],
            start: startBound + offset * slotDur,
            end: startBound + (offset + 1) * slotDur,
          };
        }
      }

      for (const w of segWords) {
        words.push(w);
        map.set(w.key, w);
      }
    });

    return { allWords: words, wordMap: map };
  }, [transcript]);

  // Build a set of cut word keys for quick lookup
  const cutKeys = useMemo(() => {
    if (!clipId) return new Set<string>();
    const keys = new Set<string>();
    for (const cut of wordCuts) {
      if (cut.clip_id !== clipId) continue;
      for (const w of allWords) {
        if (Math.abs(w.start - cut.start) < 0.05 && Math.abs(w.end - cut.end) < 0.05) {
          keys.add(w.key);
        }
      }
    }
    return keys;
  }, [wordCuts, allWords, clipId]);

  // Find current word based on playback time
  const activeWordKey = useMemo(() => {
    for (const w of allWords) {
      if (currentTime >= w.start && currentTime <= w.end) {
        return w.key;
      }
    }
    return null;
  }, [allWords, currentTime]);

  // Auto-scroll to active word
  useEffect(() => {
    if (activeWordRef.current && containerRef.current) {
      const container = containerRef.current;
      const el = activeWordRef.current;
      const elRect = el.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();

      if (elRect.top < containerRect.top || elRect.bottom > containerRect.bottom) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
  }, [activeWordKey]);

  // Keyboard handler for Delete/Backspace
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (selection.size === 0) return;
      if (e.key === "Backspace" || e.key === "Delete") {
        e.preventDefault();
        e.stopPropagation();
        const selectedWords = allWords.filter((w) => selection.has(w.key));
        if (selectedWords.length > 0) {
          setConfirmDialog({ words: selectedWords });
        }
      }
      if (e.key === "Escape") {
        setSelection(new Set());
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [selection, allWords]);

  const handleWordClick = useCallback(
    (w: WordInfo, e: React.MouseEvent) => {
      e.stopPropagation();
      // Shift+click: range selection
      if (e.shiftKey && lastClickedKey) {
        const startIdx = allWords.findIndex((x) => x.key === lastClickedKey);
        const endIdx = allWords.findIndex((x) => x.key === w.key);
        if (startIdx >= 0 && endIdx >= 0) {
          const from = Math.min(startIdx, endIdx);
          const to = Math.max(startIdx, endIdx);
          const newSel = new Set(selection);
          for (let i = from; i <= to; i++) {
            newSel.add(allWords[i].key);
          }
          setSelection(newSel);
        }
      }
      // Ctrl/Cmd+click: toggle selection
      else if (e.ctrlKey || e.metaKey) {
        const newSel = new Set(selection);
        if (newSel.has(w.key)) {
          newSel.delete(w.key);
        } else {
          newSel.add(w.key);
        }
        setSelection(newSel);
      }
      // Plain click: seek + single select
      else {
        onSeek(w.start);
        setSelection(new Set([w.key]));
      }
      setLastClickedKey(w.key);
    },
    [allWords, selection, lastClickedKey, onSeek],
  );

  const handleConfirmCut = useCallback(() => {
    if (!confirmDialog || !clipId) return;
    const newCuts: WordCut[] = [...wordCuts];
    for (const w of confirmDialog.words) {
      const exists = newCuts.some(
        (c) => c.clip_id === clipId && Math.abs(c.start - w.start) < 0.05 && Math.abs(c.end - w.end) < 0.05,
      );
      if (!exists) {
        newCuts.push({
          id: `wc_${clipId}_${w.start.toFixed(3)}`,
          clip_id: clipId,
          start: w.start,
          end: w.end,
          text: w.word,
        });
      }
    }
    onWordCutsChange(newCuts);
    setSelection(new Set());
    setConfirmDialog(null);
  }, [confirmDialog, clipId, wordCuts, onWordCutsChange]);

  const handleRestoreWord = useCallback(
    (w: WordInfo) => {
      if (!clipId) return;
      const newCuts = wordCuts.filter(
        (c) => !(c.clip_id === clipId && Math.abs(c.start - w.start) < 0.05 && Math.abs(c.end - w.end) < 0.05),
      );
      onWordCutsChange(newCuts);
    },
    [clipId, wordCuts, onWordCutsChange],
  );

  if (!transcript || allWords.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-cp-text-muted text-xs">
        No transcript available
      </div>
    );
  }

  const segments = transcript.segments || [];

  return (
    <>
      <div ref={containerRef} className="h-full overflow-y-auto px-3 py-2 select-none">
        {selection.size > 0 && (
          <div className="sticky top-0 z-10 flex items-center gap-2 mb-2 px-2 py-1 bg-cp-bg-elevated border border-cp-border rounded text-xs">
            <span className="text-cp-text-secondary">{selection.size} word{selection.size > 1 ? "s" : ""} selected</span>
            <button
              onClick={() => {
                const selectedWords = allWords.filter((w) => selection.has(w.key));
                setConfirmDialog({ words: selectedWords });
              }}
              className="flex items-center gap-1 px-2 py-0.5 bg-cp-error/20 text-cp-error rounded hover:bg-cp-error/30"
            >
              <Scissors className="w-3 h-3" />
              Cut
            </button>
            <button
              onClick={() => setSelection(new Set())}
              className="text-cp-text-muted hover:text-cp-text ml-auto"
            >
              Esc
            </button>
          </div>
        )}

        {segments.map((seg, si) => (
          <div key={si} className="mb-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] text-cp-text-muted font-code tabular-nums">
                {formatTime(seg.start)}
              </span>
              <span className="text-[10px] text-cp-text-muted uppercase">
                {seg.language}
              </span>
            </div>
            <div className="flex flex-wrap gap-x-0.5 gap-y-0.5 leading-relaxed">
              {(seg.words || []).map((w, wi) => {
                const key = `s${si}:w${wi}`;
                const isActive = key === activeWordKey;
                const isSelected = selection.has(key);
                const isCut = cutKeys.has(key);
                const wordInfo = wordMap.get(key);
                if (!wordInfo) return null;

                return (
                  <span
                    key={key}
                    ref={isActive ? activeWordRef : null}
                    onClick={(e) => handleWordClick(wordInfo, e)}
                    onDoubleClick={() => {
                      if (isCut) {
                        handleRestoreWord(wordInfo);
                      } else {
                        setConfirmDialog({ words: [wordInfo] });
                      }
                    }}
                    className={cn(
                      "px-0.5 py-px rounded cursor-pointer text-sm transition-colors select-none",
                      isActive && !isCut && "bg-cp-primary/30 text-cp-text",
                      isSelected && !isCut && "bg-cp-accent/30",
                      isCut && "line-through text-cp-error/50 bg-cp-error/10",
                      !isActive && !isSelected && !isCut && "text-cp-text-secondary hover:bg-cp-bg-surface",
                    )}
                    title={isCut ? "Double-click to restore" : `${formatTime(w.start)} — click to seek`}
                  >
                    {w.word}
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Confirmation dialog */}
      {confirmDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-cp-bg-elevated border border-cp-border rounded-lg p-4 max-w-sm">
            <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
              <Scissors className="w-4 h-4 text-cp-error" />
              Cut {confirmDialog.words.length} word{confirmDialog.words.length > 1 ? "s" : ""} from footage?
            </h3>
            <div className="bg-cp-bg rounded p-2 mb-3 text-sm max-h-24 overflow-y-auto">
              <span className="text-cp-error line-through">
                {confirmDialog.words.map((w) => w.word).join(" ")}
              </span>
            </div>
            <p className="text-xs text-cp-text-muted mb-3">
              Time range: {formatTime(confirmDialog.words[0].start)} — {formatTime(confirmDialog.words[confirmDialog.words.length - 1].end)}
              <br />
              This will be removed from the final edit on next sync.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setConfirmDialog(null);
                  setSelection(new Set());
                }}
                className="px-3 py-1 text-xs rounded border border-cp-border hover:bg-cp-bg-surface"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmCut}
                className="px-3 py-1 text-xs rounded bg-cp-error hover:bg-cp-error/80 text-white"
              >
                Cut
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
