#!/usr/bin/env python3
"""Adaptively extract key frames from video clips based on scene boundaries,
speech emphasis points, VAD silence boundaries, and periodic sampling.

Usage:
    python3 extract_frames.py <project_root> [--force] [--max-frames-per-clip 100] [--periodic-interval 10.0]

Reads manifest data from phases 4-6 (transcript, vad, pitch, scenes) and
extracts frames at interesting moments. Falls back to periodic + start/end
when upstream analysis data is missing.

Phase: 7 (frames)
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Priority ordering: lower number = higher priority.
# Used for deduplication and capping.
REASON_PRIORITY = {
    "scene_start": 0,
    "scene_end": 0,
    "scene_boundary": 1,
    "speech_emphasis": 2,
    "silence_boundary": 3,
    "periodic": 4,
}

FFMPEG_FRAME_TIMEOUT = 10
DEDUP_WINDOW_SECONDS = 0.5
PERIODIC_PROXIMITY_THRESHOLD = 2.0
TOP_EMPHASIS_COUNT = 20
MIN_SILENCE_DURATION = 0.5


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def read_manifest(project_root: Path) -> dict:
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        logger.error("Manifest not found at %s", manifest_path)
        sys.exit(1)
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read manifest: %s", exc)
        sys.exit(1)


def write_manifest(project_root: Path, manifest: dict) -> None:
    manifest_path = project_root / "footage_manifest.json"
    tmp_path = manifest_path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp_path.replace(manifest_path)
    except OSError as exc:
        logger.error("Failed to write manifest: %s", exc)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Source video resolution
# ---------------------------------------------------------------------------


def resolve_source_path(clip: dict, project_root: Path) -> Path:
    """Resolve the actual file path for a clip's source video."""
    source = Path(clip["source_path"])
    if source.exists():
        return source

    symlink = project_root / clip["symlink_path"]
    if symlink.exists():
        return symlink

    raise FileNotFoundError(
        f"Cannot find source video for clip {clip['id']}: "
        f"tried {source} and {symlink}"
    )


# ---------------------------------------------------------------------------
# Candidate collection
# ---------------------------------------------------------------------------


def collect_candidates(
    clip: dict,
    clip_duration: float,
    periodic_interval: float,
) -> list[dict]:
    """Collect all candidate frame timestamps for a single clip.

    Each candidate is a dict with keys: time, reason, priority.
    """
    candidates: list[dict] = []

    def add(time: float, reason: str) -> None:
        # Clamp to valid range
        t = max(0.0, min(time, clip_duration))
        candidates.append({
            "time": round(t, 4),
            "reason": reason,
            "priority": REASON_PRIORITY.get(reason, 99),
        })

    # Always: start and end
    add(0.0, "scene_start")
    if clip_duration > 0.5:
        add(clip_duration - 0.5, "scene_end")
    else:
        add(clip_duration, "scene_end")

    # Scene boundaries (phase 6)
    scenes = clip.get("scenes")
    if scenes and isinstance(scenes, dict):
        boundaries = scenes.get("boundaries", [])
        if isinstance(boundaries, list):
            for boundary in boundaries:
                t = boundary.get("time")
                if t is not None:
                    add(t + 0.1, "scene_boundary")

    # VAD silence segments (phase 5)
    vad = clip.get("vad")
    if vad and isinstance(vad, dict):
        silence_segments = vad.get("silence_segments", [])
        if isinstance(silence_segments, list):
            for seg in silence_segments:
                duration = seg.get("duration")
                start = seg.get("start")
                end = seg.get("end")

                # Only consider silence segments longer than threshold
                seg_duration = duration
                if seg_duration is None and start is not None and end is not None:
                    seg_duration = end - start
                if seg_duration is None or seg_duration <= MIN_SILENCE_DURATION:
                    continue

                if start is not None:
                    add(start, "silence_boundary")
                if end is not None:
                    add(end, "silence_boundary")

    # Pitch emphasis points (phase 5)
    pitch = clip.get("pitch")
    if pitch and isinstance(pitch, dict):
        emphasis_points = pitch.get("emphasis_points", [])
        if isinstance(emphasis_points, list) and emphasis_points:
            # Sort by magnitude descending, take top N
            sorted_points = sorted(
                [p for p in emphasis_points if p.get("time") is not None],
                key=lambda p: abs(p.get("magnitude", 0)),
                reverse=True,
            )
            for point in sorted_points[:TOP_EMPHASIS_COUNT]:
                add(point["time"], "speech_emphasis")

    # Periodic sampling: every periodic_interval seconds, but only if no
    # other candidate is within PERIODIC_PROXIMITY_THRESHOLD seconds.
    if periodic_interval > 0 and clip_duration > 0:
        non_periodic_times = [c["time"] for c in candidates]
        t = periodic_interval
        while t < clip_duration:
            # Check proximity to existing non-periodic candidates
            too_close = any(
                abs(t - nt) < PERIODIC_PROXIMITY_THRESHOLD
                for nt in non_periodic_times
            )
            if not too_close:
                add(t, "periodic")
            t += periodic_interval

    return candidates


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def deduplicate_candidates(candidates: list[dict]) -> list[dict]:
    """Sort by time and merge candidates within DEDUP_WINDOW_SECONDS.

    When two candidates are within the window, the one with higher priority
    (lower priority number) wins.
    """
    if not candidates:
        return []

    sorted_candidates = sorted(candidates, key=lambda c: (c["time"], c["priority"]))
    result: list[dict] = [sorted_candidates[0]]

    for candidate in sorted_candidates[1:]:
        prev = result[-1]
        if candidate["time"] - prev["time"] < DEDUP_WINDOW_SECONDS:
            # Merge: keep the higher-priority one
            if candidate["priority"] < prev["priority"]:
                result[-1] = candidate
            # else keep prev
        else:
            result.append(candidate)

    return result


# ---------------------------------------------------------------------------
# Capping
# ---------------------------------------------------------------------------


def cap_candidates(candidates: list[dict], max_frames: int) -> list[dict]:
    """If over the limit, drop candidates from lowest priority first."""
    if len(candidates) <= max_frames:
        return candidates

    # Group by priority bucket, drop from highest priority number first
    priority_buckets: dict[int, list[dict]] = {}
    for c in candidates:
        priority_buckets.setdefault(c["priority"], []).append(c)

    # Sort bucket keys descending (lowest priority = highest number first)
    bucket_keys = sorted(priority_buckets.keys(), reverse=True)

    remaining = list(candidates)
    for key in bucket_keys:
        if len(remaining) <= max_frames:
            break
        bucket = priority_buckets[key]
        # Remove all candidates in this bucket
        bucket_set = {id(c) for c in bucket}
        reduced = [c for c in remaining if id(c) not in bucket_set]
        if len(reduced) >= max_frames:
            remaining = reduced
        else:
            # Removing all from this bucket would overshoot.
            # Keep enough from this bucket to reach exactly max_frames.
            need_to_keep = max_frames - len(reduced)
            # Keep the ones spread evenly by time
            bucket_sorted = sorted(bucket, key=lambda c: c["time"])
            if need_to_keep >= len(bucket_sorted):
                # Keep all of them
                break
            # Select evenly spaced indices
            step = len(bucket_sorted) / need_to_keep
            kept_indices = set()
            for i in range(need_to_keep):
                idx = int(i * step)
                idx = min(idx, len(bucket_sorted) - 1)
                kept_indices.add(idx)
            kept = {id(bucket_sorted[i]) for i in kept_indices}
            remaining = [c for c in remaining if id(c) not in bucket_set or id(c) in kept]
            break

    # Final sort by time
    remaining.sort(key=lambda c: c["time"])
    return remaining[:max_frames]


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------


def extract_single_frame(
    source_video: Path,
    timestamp: float,
    output_path: Path,
) -> bool:
    """Extract a single frame at the given timestamp using ffmpeg.

    Returns True if the frame was successfully extracted and the file exists.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-ss", f"{timestamp:.4f}",
        "-i", str(source_video),
        "-frames:v", "1",
        "-q:v", "2",
        "-y",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FFMPEG_FRAME_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "ffmpeg timed out extracting frame at %.4fs from %s",
            timestamp, source_video,
        )
        return False
    except FileNotFoundError:
        logger.error("ffmpeg not found on PATH")
        return False

    if result.returncode != 0:
        logger.warning(
            "ffmpeg returned %d extracting frame at %.4fs from %s: %s",
            result.returncode, timestamp, source_video, result.stderr.strip(),
        )
        return False

    if not output_path.is_file():
        logger.warning(
            "Frame file not created at %s despite ffmpeg returning 0",
            output_path,
        )
        return False

    # Verify the file has non-zero size
    if output_path.stat().st_size == 0:
        logger.warning(
            "Frame file %s is empty (0 bytes), removing",
            output_path,
        )
        output_path.unlink()
        return False

    return True


# ---------------------------------------------------------------------------
# Per-clip processing
# ---------------------------------------------------------------------------


def clip_already_processed(clip: dict, project_root: Path) -> bool:
    """Check if frames have already been extracted for this clip."""
    frames = clip.get("frames")
    if frames is None or not isinstance(frames, dict):
        return False

    frame_dir = frames.get("dir")
    if not frame_dir:
        return False

    count = frames.get("count", 0)
    extracted = frames.get("extracted", [])
    if count == 0 or not extracted:
        return False

    # Verify at least the first and last frame files exist
    full_dir = project_root / frame_dir
    if not full_dir.is_dir():
        return False

    for entry in (extracted[0], extracted[-1]):
        frame_path = project_root / entry["path"]
        if not frame_path.is_file():
            return False

    return True


def process_clip(
    clip: dict,
    project_root: Path,
    max_frames: int,
    periodic_interval: float,
) -> int:
    """Extract frames for a single clip. Returns the number of frames extracted."""
    clip_id = clip["id"]

    source_video = resolve_source_path(clip, project_root)

    metadata = clip.get("metadata", {})
    clip_duration = metadata.get("duration_seconds")
    if clip_duration is None or clip_duration <= 0:
        logger.warning(
            "Clip %s has no valid duration (got %s), skipping frame extraction",
            clip_id, clip_duration,
        )
        return 0

    # 1. Collect candidates
    candidates = collect_candidates(clip, clip_duration, periodic_interval)
    logger.info(
        "Clip %s: collected %d candidate timestamps (duration=%.1fs)",
        clip_id, len(candidates), clip_duration,
    )

    # 2. Deduplicate
    candidates = deduplicate_candidates(candidates)
    logger.info(
        "Clip %s: %d candidates after deduplication",
        clip_id, len(candidates),
    )

    # 3. Cap
    candidates = cap_candidates(candidates, max_frames)
    logger.info(
        "Clip %s: %d candidates after capping (max=%d)",
        clip_id, len(candidates), max_frames,
    )

    if not candidates:
        logger.warning("Clip %s: no candidate frames to extract", clip_id)
        clip["frames"] = {
            "dir": f"frames/{clip_id}/",
            "count": 0,
            "extracted": [],
        }
        return 0

    # 4. Extract
    frames_dir = project_root / "frames" / clip_id
    frames_dir.mkdir(parents=True, exist_ok=True)

    extracted_entries: list[dict] = []
    frame_index = 1

    for candidate in candidates:
        frame_filename = f"frame_{frame_index:06d}.jpg"
        output_path = frames_dir / frame_filename
        relative_path = f"frames/{clip_id}/{frame_filename}"

        success = extract_single_frame(source_video, candidate["time"], output_path)
        if success:
            extracted_entries.append({
                "path": relative_path,
                "time": candidate["time"],
                "reason": candidate["reason"],
            })
            frame_index += 1
        else:
            logger.warning(
                "Clip %s: failed to extract frame at %.4fs (reason=%s)",
                clip_id, candidate["time"], candidate["reason"],
            )

    # 5. Sort by time (should already be sorted, but guarantee it)
    extracted_entries.sort(key=lambda e: e["time"])

    # 6. Write to clip.frames
    clip["frames"] = {
        "dir": f"frames/{clip_id}/",
        "count": len(extracted_entries),
        "extracted": extracted_entries,
    }

    logger.info(
        "Clip %s: extracted %d frames out of %d candidates",
        clip_id, len(extracted_entries), len(candidates),
    )

    return len(extracted_entries)


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(
    manifest: dict,
    total_frames: int,
    warnings: list[str],
) -> None:
    """Mark phase 7 as complete in pipeline_state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if "pipeline_state" not in manifest:
        manifest["pipeline_state"] = {
            "current_phase": 7,
            "completed_phases": [],
            "phase_results": {},
            "errors": [],
            "warnings": [],
            "last_updated": now,
        }

    state = manifest["pipeline_state"]

    state.setdefault("phase_results", {})["7"] = {
        "status": "success",
        "timestamp": now,
        "frames_extracted": total_frames,
    }

    completed = state.setdefault("completed_phases", [])
    if 7 not in completed:
        completed.append(7)
        completed.sort()

    if state.get("current_phase", 0) <= 7:
        state["current_phase"] = 8

    # Merge warnings without duplicates
    existing_warnings = state.get("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)
    state["warnings"] = existing_warnings
    state["last_updated"] = now


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract key frames from video clips based on analysis data.",
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Path to the project root directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract frames even if already present",
    )
    parser.add_argument(
        "--max-frames-per-clip",
        type=int,
        default=100,
        help="Maximum number of frames to extract per clip (default: 100)",
    )
    parser.add_argument(
        "--periodic-interval",
        type=float,
        default=10.0,
        help="Seconds between periodic frame samples (default: 10.0)",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        logger.error("Project root does not exist: %s", project_root)
        sys.exit(1)

    if args.max_frames_per_clip < 1:
        logger.error("--max-frames-per-clip must be at least 1, got %d", args.max_frames_per_clip)
        sys.exit(1)

    if args.periodic_interval <= 0:
        logger.error("--periodic-interval must be positive, got %f", args.periodic_interval)
        sys.exit(1)

    manifest = read_manifest(project_root)

    clips = manifest.get("clips", [])
    if not clips:
        output = {
            "status": "success",
            "message": "No clips found in manifest, nothing to extract",
            "details": {"total_frames": 0, "per_clip": {}},
        }
        print(json.dumps(output))
        return

    warnings: list[str] = []
    errors: list[str] = []
    total_frames = 0
    per_clip: dict[str, int] = {}
    clips_processed = 0

    for clip in clips:
        clip_id = clip.get("id", "unknown")

        if not args.force and clip_already_processed(clip, project_root):
            logger.info("Clip %s: frames already extracted, skipping", clip_id)
            existing_count = clip.get("frames", {}).get("count", 0)
            per_clip[clip_id] = existing_count
            total_frames += existing_count
            continue

        try:
            count = process_clip(
                clip,
                project_root,
                args.max_frames_per_clip,
                args.periodic_interval,
            )
            per_clip[clip_id] = count
            total_frames += count
            clips_processed += 1
        except FileNotFoundError as exc:
            msg = f"Clip {clip_id}: {exc}"
            logger.error(msg)
            errors.append(msg)
        except subprocess.TimeoutExpired as exc:
            msg = f"Clip {clip_id}: subprocess timed out: {exc}"
            logger.error(msg)
            errors.append(msg)
        except OSError as exc:
            msg = f"Clip {clip_id}: OS error: {exc}"
            logger.error(msg)
            errors.append(msg)

    # If all clips errored out and we extracted nothing, report failure
    if errors and total_frames == 0 and clips_processed == 0:
        for err in errors:
            print(err, file=sys.stderr)
        output = {
            "status": "error",
            "message": f"All clips failed: {len(errors)} error(s)",
            "details": {
                "total_frames": 0,
                "per_clip": per_clip,
                "errors": errors,
            },
        }
        print(json.dumps(output))
        sys.exit(1)

    # Non-fatal errors become warnings
    if errors:
        for err in errors:
            warnings.append(err)

    update_pipeline_state(manifest, total_frames, warnings)
    write_manifest(project_root, manifest)

    output = {
        "status": "success",
        "message": f"Extracted {total_frames} frames across {len(per_clip)} clips",
        "details": {
            "total_frames": total_frames,
            "per_clip": per_clip,
        },
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
