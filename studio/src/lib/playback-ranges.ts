import type { ClipEdit, WordCut } from "../types/edit-manifest";

export interface SkipRange {
  start: number;
  end: number;
}

export interface PlaybackConstraints {
  playableStart: number;
  playableEnd: number;
  skipRanges: SkipRange[];
}

/**
 * Merge overlapping/adjacent ranges. Input must be sorted by start.
 */
function mergeRanges(ranges: SkipRange[]): SkipRange[] {
  if (ranges.length === 0) return [];
  const merged: SkipRange[] = [{ ...ranges[0] }];
  for (let i = 1; i < ranges.length; i++) {
    const last = merged[merged.length - 1];
    const curr = ranges[i];
    if (curr.start <= last.end) {
      last.end = Math.max(last.end, curr.end);
    } else {
      merged.push({ ...curr });
    }
  }
  return merged;
}

/**
 * Compute playback constraints from edit metadata.
 * Trims define the playable window; deleted_ranges and word_cuts define skip ranges within it.
 */
export function computePlaybackRanges(
  clipEdit: ClipEdit | undefined,
  wordCuts: WordCut[],
  clipId: string,
  duration: number,
): PlaybackConstraints {
  const playableStart = clipEdit?.trim?.in ?? 0;
  const playableEnd = clipEdit?.trim?.out ?? duration;

  const raw: SkipRange[] = [];

  // Collect deleted ranges
  if (clipEdit?.deleted_ranges) {
    for (const dr of clipEdit.deleted_ranges) {
      raw.push({ start: dr.start, end: dr.end });
    }
  }

  // Collect word cuts for this clip
  for (const wc of wordCuts) {
    if (wc.clip_id === clipId) {
      raw.push({ start: wc.start, end: wc.end });
    }
  }

  // Clamp to playable window, discard out-of-bounds
  const clamped: SkipRange[] = [];
  for (const r of raw) {
    const s = Math.max(r.start, playableStart);
    const e = Math.min(r.end, playableEnd);
    if (s < e) {
      clamped.push({ start: s, end: e });
    }
  }

  // Sort by start, merge overlapping
  clamped.sort((a, b) => a.start - b.start);
  const skipRanges = mergeRanges(clamped);

  return { playableStart, playableEnd, skipRanges };
}

/**
 * Check if a time falls inside any skip range.
 * Returns the range if inside, null otherwise.
 */
export function findContainingSkipRange(
  time: number,
  skipRanges: SkipRange[],
  epsilon: number,
): SkipRange | null {
  for (const r of skipRanges) {
    if (time >= r.start - epsilon && time < r.end - epsilon) {
      return r;
    }
  }
  return null;
}

/**
 * Clamp a time to the playable region, skipping over any skip ranges in the given direction.
 */
export function clampToPlayable(
  time: number,
  constraints: PlaybackConstraints,
  direction: 1 | -1,
  epsilon: number,
): number {
  let t = Math.max(constraints.playableStart, Math.min(constraints.playableEnd, time));

  const skip = findContainingSkipRange(t, constraints.skipRanges, epsilon);
  if (skip) {
    t = direction >= 0 ? skip.end : skip.start - epsilon;
    // Re-clamp after skip adjustment
    t = Math.max(constraints.playableStart, Math.min(constraints.playableEnd, t));
  }

  return t;
}

/**
 * Check if there's any playable content (i.e., not everything is skipped).
 */
export function hasPlayableContent(constraints: PlaybackConstraints): boolean {
  const totalDuration = constraints.playableEnd - constraints.playableStart;
  if (totalDuration <= 0) return false;

  let skippedDuration = 0;
  for (const r of constraints.skipRanges) {
    skippedDuration += r.end - r.start;
  }
  return skippedDuration < totalDuration;
}
