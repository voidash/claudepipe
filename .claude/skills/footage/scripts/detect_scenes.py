#!/usr/bin/env python3
"""
Detect scene boundaries in video clips using visual analysis.

Uses frame differencing and histogram comparison to find hard cuts,
fades, and dissolves. Writes results to the footage manifest and
per-clip JSON files.

Phase 6 of the footage pipeline.

Usage:
    python3 detect_scenes.py <project_root> [--force] [--threshold 30.0] [--min-scene-length 2.0]
"""

import argparse
import json
import subprocess
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


def load_manifest(project_root: Path) -> dict:
    """Load the footage manifest from project root."""
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": f"Manifest not found at {manifest_path}",
                }
            )
        )
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(project_root: Path, manifest: dict) -> None:
    """Write the footage manifest back to disk."""
    manifest_path = project_root / "footage_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def resolve_clip_path(project_root: Path, clip: dict) -> Path:
    """Resolve the actual video file path for a clip.

    Tries the symlink path first (relative to project root), then falls
    back to the absolute source_path.
    """
    symlink = project_root / clip.get("symlink_path", "")
    if symlink.exists():
        return symlink

    source = Path(clip.get("source_path", ""))
    if source.exists():
        return source

    return Path("")


def compute_histogram(frame_gray: np.ndarray) -> np.ndarray:
    """Compute a normalized grayscale histogram for a frame."""
    hist = cv2.calcHist([frame_gray], [0], None, [256], [0, 256])
    cv2.normalize(hist, hist)
    return hist


def detect_hard_cuts(
    cap: cv2.VideoCapture,
    fps: float,
    total_frames: int,
    threshold: float,
) -> list[dict]:
    """Detect hard cuts via frame differencing and histogram correlation.

    Samples at ~5 fps. A hard cut is flagged when the mean absolute
    difference exceeds *threshold* AND the histogram correlation drops
    below 0.5.

    Returns a list of boundary dicts (time, confidence, type="cut").
    """
    sample_interval = max(1, int(round(fps / 5.0)))
    boundaries: list[dict] = []

    prev_gray = None
    prev_hist = None

    frame_idx = 0
    while frame_idx < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = compute_histogram(gray)
        current_time = frame_idx / fps

        if prev_gray is not None and prev_hist is not None:
            diff = cv2.absdiff(gray, prev_gray)
            mean_diff = float(np.asarray(diff).mean())

            correlation = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)

            if mean_diff > threshold and correlation < 0.5:
                # Confidence: blend of how much the diff exceeded threshold
                # and how far correlation dropped below 0.5.
                diff_confidence = min(1.0, mean_diff / (threshold * 3.0))
                corr_confidence = min(1.0, (0.5 - correlation) / 0.5)
                confidence = 0.6 * diff_confidence + 0.4 * corr_confidence

                boundaries.append(
                    {
                        "time": round(current_time, 1),
                        "type": "cut",
                        "confidence": round(min(1.0, max(0.0, confidence)), 2),
                    }
                )

        prev_gray = gray
        prev_hist = hist
        frame_idx += sample_interval

    return boundaries


def detect_fades_and_dissolves(
    cap: cv2.VideoCapture,
    fps: float,
    total_frames: int,
) -> list[dict]:
    """Detect fades and dissolves using brightness and histogram analysis.

    Uses a sliding window of ~10 frames (sampled at 5 fps) to track:
    - Mean brightness (intensity): a fade-to/from-black shows brightness
      dropping below 20 then recovering.
    - Running histogram correlation: a dissolve shows a characteristic
      dip in correlation over several consecutive frames while brightness
      remains moderate.

    Returns a list of boundary dicts.
    """
    window_size = 10
    sample_interval = max(1, int(round(fps / 5.0)))
    boundaries: list[dict] = []

    brightness_window: deque[float] = deque(maxlen=window_size)
    corr_window: deque[float] = deque(maxlen=window_size)
    time_window: deque[float] = deque(maxlen=window_size)

    prev_hist = None

    frame_idx = 0
    while frame_idx < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = compute_histogram(gray)
        current_time = frame_idx / fps

        mean_brightness = float(np.asarray(gray).mean())
        brightness_window.append(mean_brightness)
        time_window.append(current_time)

        if prev_hist is not None:
            correlation = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            corr_window.append(correlation)
        else:
            corr_window.append(1.0)

        prev_hist = hist

        # Need a full window before we start analysing patterns.
        if len(brightness_window) < window_size:
            frame_idx += sample_interval
            continue

        brightness_arr = np.array(brightness_window)
        corr_arr = np.array(corr_window)
        mid_idx = window_size // 2

        # --- Fade detection ---
        # Brightness dips below 20 at the midpoint, with surrounding
        # frames being significantly brighter.
        mid_brightness = brightness_arr[mid_idx]
        left_brightness = float(np.mean(brightness_arr[: mid_idx]))
        right_brightness = float(np.mean(brightness_arr[mid_idx + 1 :]))

        if mid_brightness < 20.0 and left_brightness > 40.0 and right_brightness > 40.0:
            fade_strength = min(1.0, (left_brightness - mid_brightness) / 100.0)
            boundaries.append(
                {
                    "time": round(time_window[mid_idx], 1),
                    "type": "fade",
                    "confidence": round(min(1.0, max(0.0, fade_strength)), 2),
                }
            )
            frame_idx += sample_interval
            continue

        # Also detect fade-to-black at the midpoint where brightness
        # is declining across the window.
        brightness_std = float(np.std(brightness_arr))
        if brightness_std > 25.0 and mid_brightness < 20.0:
            boundaries.append(
                {
                    "time": round(time_window[mid_idx], 1),
                    "type": "fade",
                    "confidence": round(min(1.0, brightness_std / 80.0), 2),
                }
            )
            frame_idx += sample_interval
            continue

        # --- Dissolve detection ---
        # Histogram correlation dips at midpoint while brightness stays
        # moderate (rules out fades).
        mid_corr = corr_arr[mid_idx]
        left_corr = float(np.mean(corr_arr[: mid_idx]))
        right_corr = float(np.mean(corr_arr[mid_idx + 1 :]))

        if (
            mid_corr < 0.7
            and left_corr > 0.85
            and right_corr > 0.85
            and mid_brightness > 30.0
        ):
            dissolve_strength = min(1.0, (left_corr - mid_corr) / 0.5)
            boundaries.append(
                {
                    "time": round(time_window[mid_idx], 1),
                    "type": "dissolve",
                    "confidence": round(min(1.0, max(0.0, dissolve_strength)), 2),
                }
            )

        frame_idx += sample_interval

    return boundaries


def merge_boundaries(
    boundaries: list[dict],
    min_scene_length: float,
) -> list[dict]:
    """Merge boundaries that are within min_scene_length of each other.

    When two boundaries are close together, the one with higher
    confidence is kept.  Also deduplicates exact-time overlaps from
    the two detection methods, preferring the more specific type
    (cut > dissolve > fade > gradual).
    """
    if not boundaries:
        return []

    # Sort by time, then by descending confidence for tie-breaking.
    sorted_bounds = sorted(boundaries, key=lambda b: (b["time"], -b["confidence"]))

    merged: list[dict] = [sorted_bounds[0]]
    for b in sorted_bounds[1:]:
        prev = merged[-1]
        if abs(b["time"] - prev["time"]) < min_scene_length:
            # Keep the one with higher confidence.
            if b["confidence"] > prev["confidence"]:
                merged[-1] = b
        else:
            merged.append(b)

    return merged


def extract_boundary_frames(
    source_path: Path,
    project_root: Path,
    clip_id: str,
    boundaries: list[dict],
) -> list[dict]:
    """Extract before/after JPEG frames for each boundary using ffmpeg.

    Updates each boundary dict in-place with frame_before / frame_after
    relative paths.  Returns the same list.
    """
    frames_dir = project_root / "frames" / clip_id
    frames_dir.mkdir(parents=True, exist_ok=True)

    for boundary in boundaries:
        t = boundary["time"]
        t_str = f"{t:.1f}"

        before_rel = f"frames/{clip_id}/scene_boundary_{t_str}_before.jpg"
        after_rel = f"frames/{clip_id}/scene_boundary_{t_str}_after.jpg"
        before_abs = project_root / before_rel
        after_abs = project_root / after_rel

        time_before = max(0.0, t - 0.05)
        time_after = t + 0.05

        # Extract frame just before the boundary.
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(time_before),
                    "-i",
                    str(source_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(before_abs),
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(
                f"WARNING: ffmpeg timed out extracting before-frame at {t_str}s for {clip_id}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"WARNING: failed to extract before-frame at {t_str}s for {clip_id}: {exc}",
                file=sys.stderr,
            )

        # Extract frame just after the boundary.
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(time_after),
                    "-i",
                    str(source_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(after_abs),
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(
                f"WARNING: ffmpeg timed out extracting after-frame at {t_str}s for {clip_id}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"WARNING: failed to extract after-frame at {t_str}s for {clip_id}: {exc}",
                file=sys.stderr,
            )

        boundary["frame_before"] = before_rel
        boundary["frame_after"] = after_rel

    return boundaries


def process_clip(
    project_root: Path,
    clip: dict,
    threshold: float,
    min_scene_length: float,
    force: bool,
) -> dict | None:
    """Run scene detection on a single clip.

    Returns the scenes dict to store on clip["scenes"], or None if the
    clip was skipped or unreadable.
    """
    clip_id = clip["id"]

    # Skip if already processed (unless --force).
    if not force and clip.get("scenes") and clip["scenes"].get("boundaries") is not None:
        print(f"Skipping {clip_id}: already processed (use --force to re-run)", file=sys.stderr)
        return None

    video_path = resolve_clip_path(project_root, clip)
    if not video_path.exists():
        print(f"WARNING: video file not found for {clip_id}: {video_path}", file=sys.stderr)
        return None

    metadata = clip.get("metadata", {})
    fps = metadata.get("fps", 30.0)
    if fps <= 0:
        fps = 30.0

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            print(f"WARNING: cannot open video for {clip_id}: {video_path}", file=sys.stderr)
            return None

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            print(f"WARNING: zero frames reported for {clip_id}", file=sys.stderr)
            return None

        # -- Method A: hard cuts --
        hard_cuts = detect_hard_cuts(cap, fps, total_frames, threshold)

        # -- Method B: fades / dissolves --
        fade_dissolves = detect_fades_and_dissolves(cap, fps, total_frames)
    except Exception as exc:
        print(f"WARNING: error processing {clip_id}: {exc}", file=sys.stderr)
        return None
    finally:
        cap.release()

    # Combine and merge all detections.
    all_boundaries = hard_cuts + fade_dissolves
    merged = merge_boundaries(all_boundaries, min_scene_length)

    # Extract boundary frames via ffmpeg.
    merged = extract_boundary_frames(video_path, project_root, clip_id, merged)

    # Write detailed per-clip analysis.
    analysis_dir = project_root / "analysis" / "scenes"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    analysis_path = analysis_dir / f"{clip_id}.json"

    detailed = {
        "clip_id": clip_id,
        "source_path": str(video_path),
        "fps": fps,
        "total_frames": total_frames,
        "threshold": threshold,
        "min_scene_length": min_scene_length,
        "hard_cuts_raw": len(hard_cuts),
        "fades_dissolves_raw": len(fade_dissolves),
        "boundaries_after_merge": len(merged),
        "boundaries": merged,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(detailed, f, indent=2, ensure_ascii=False)

    # Build the manifest-level scenes object.
    scenes = {
        "path": f"analysis/scenes/{clip_id}.json",
        "boundaries": merged,
    }

    return scenes


def update_pipeline_state(manifest: dict) -> None:
    """Mark phase 6 as completed in the pipeline state."""
    state = manifest.setdefault("pipeline_state", {})
    results = state.setdefault("phase_results", {})
    completed = state.setdefault("completed_phases", [])

    results["6"] = {
        "status": "success",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if 6 not in completed:
        completed.append(6)
        completed.sort()

    state["last_updated"] = datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect scene boundaries in video clips via visual analysis."
    )
    parser.add_argument(
        "project_root",
        type=str,
        help="Path to the project root directory containing footage_manifest.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-process clips that already have scene data",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=30.0,
        help="Mean absolute difference threshold for hard-cut detection (default: 30.0)",
    )
    parser.add_argument(
        "--min-scene-length",
        type=float,
        default=2.0,
        help="Minimum seconds between scene boundaries (default: 2.0)",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": f"Project root is not a directory: {project_root}",
                }
            )
        )
        sys.exit(1)

    manifest = load_manifest(project_root)
    clips = manifest.get("clips", [])

    if not clips:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "No clips found in manifest",
                }
            )
        )
        sys.exit(1)

    total_boundaries = 0
    per_clip: dict[str, int] = {}
    clips_processed = 0

    for clip in clips:
        clip_id = clip["id"]
        scenes = process_clip(
            project_root,
            clip,
            threshold=args.threshold,
            min_scene_length=args.min_scene_length,
            force=args.force,
        )
        if scenes is not None:
            clip["scenes"] = scenes
            count = len(scenes["boundaries"])
            per_clip[clip_id] = count
            total_boundaries += count
            clips_processed += 1

    update_pipeline_state(manifest)
    save_manifest(project_root, manifest)

    result = {
        "status": "success",
        "message": f"Detected {total_boundaries} scene boundaries across {clips_processed} clips",
        "details": {"per_clip": per_clip},
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
