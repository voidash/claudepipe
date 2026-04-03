#!/usr/bin/env python3
"""Assemble analysis data into the timeline portion of the footage manifest.

Creates initial timeline segments from scene boundaries, silence gaps, and
forced splits.  Computes interest scores, assigns tags, sets crop keyframes,
and suggests an edit order with transitions.

Phase 11 of the footage pipeline.

Usage:
    python3 build_manifest.py <project_root> [--force] \
        [--min-segment-duration 3.0] [--silence-threshold 1.5]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SEGMENT_DURATION = 60.0
MINIMUM_CROP_MOVEMENT_PX = 20
INTEREST_INCLUDE_THRESHOLD = 0.3
SILENCE_TAG_RATIO = 0.8


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest(project_root: Path) -> dict:
    """Load and return the footage manifest, or exit on failure."""
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        _fatal(f"Manifest not found at {manifest_path}")

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        _fatal(f"Failed to read manifest: {exc}")


def save_manifest(project_root: Path, manifest: dict) -> None:
    """Atomically write the manifest back to disk."""
    manifest_path = project_root / "footage_manifest.json"
    tmp_path = manifest_path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        tmp_path.replace(manifest_path)
    except OSError as exc:
        _fatal(f"Failed to write manifest: {exc}")


def _fatal(message: str) -> NoReturn:
    """Print an error JSON message to stdout and exit with code 1."""
    print(json.dumps({"status": "error", "message": message}))
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helper: build frame-time index for a clip
# ---------------------------------------------------------------------------


def _build_frame_time_index(clip: dict) -> list[tuple[str, float]]:
    """Return a sorted list of (frame_path, time) from clip.frames.extracted.

    Used to correlate YOLO detections (keyed by frame path) with timestamps.
    """
    frames = clip.get("frames")
    if not frames or not isinstance(frames, dict):
        return []

    extracted = frames.get("extracted", [])
    if not isinstance(extracted, list):
        return []

    pairs = []
    for entry in extracted:
        path = entry.get("path")
        time = entry.get("time")
        if path is not None and time is not None:
            pairs.append((str(path), float(time)))

    pairs.sort(key=lambda p: p[1])
    return pairs


# ---------------------------------------------------------------------------
# Step 1: Segment each clip into timeline segments
# ---------------------------------------------------------------------------


def _collect_cut_points(
    clip: dict,
    clip_duration: float,
    silence_threshold: float,
) -> list[float]:
    """Gather all potential cut points for a clip.

    Sources:
      - Scene boundaries (clip.scenes.boundaries[].time)
      - Silence gaps longer than silence_threshold (midpoint of silence)
      - Forced splits at every MAX_SEGMENT_DURATION seconds
    """
    cut_points: set[float] = set()

    # Always include start and end
    cut_points.add(0.0)
    cut_points.add(clip_duration)

    # Scene boundaries
    scenes = clip.get("scenes")
    if scenes and isinstance(scenes, dict):
        for boundary in scenes.get("boundaries", []):
            t = boundary.get("time")
            if t is not None and 0.0 < float(t) < clip_duration:
                cut_points.add(round(float(t), 4))

    # Long silence gaps — use midpoint of silence as the cut point
    vad = clip.get("vad")
    if vad and isinstance(vad, dict):
        for seg in vad.get("silence_segments", []):
            start = seg.get("start")
            end = seg.get("end")
            duration = seg.get("duration")

            if start is None or end is None:
                continue

            start_f = float(start)
            end_f = float(end)

            if duration is not None:
                dur = float(duration)
            else:
                dur = end_f - start_f

            if dur > silence_threshold and 0.0 < start_f < clip_duration:
                midpoint = round((start_f + end_f) / 2.0, 4)
                midpoint = min(midpoint, clip_duration)
                cut_points.add(midpoint)

    # Forced splits at MAX_SEGMENT_DURATION intervals
    t = MAX_SEGMENT_DURATION
    while t < clip_duration:
        cut_points.add(round(t, 4))
        t += MAX_SEGMENT_DURATION

    return sorted(cut_points)


def _merge_close_cut_points(
    cut_points: list[float],
    min_segment_duration: float,
) -> list[float]:
    """Merge cut points that are within min_segment_duration of each other.

    Always keeps the first (0.0) and last (clip end) cut point.
    When two points are close, the earlier one is kept.
    """
    if len(cut_points) <= 2:
        return cut_points

    merged = [cut_points[0]]
    for pt in cut_points[1:-1]:
        if pt - merged[-1] >= min_segment_duration:
            merged.append(pt)
        # else: skip this point — too close to the previous one

    # Always keep the final cut point (clip end)
    last = cut_points[-1]
    if last - merged[-1] < min_segment_duration and len(merged) > 1:
        # The last interior point is too close to end — remove it so we
        # get one longer final segment rather than a tiny stub.
        pass
    merged.append(last)

    return merged


def build_segments_for_clip(
    clip: dict,
    clip_duration: float,
    silence_threshold: float,
    min_segment_duration: float,
    seg_counter: int,
) -> tuple[list[dict], int]:
    """Build timeline segments for a single clip.

    Returns (segments_list, updated_seg_counter).
    """
    if clip_duration is None or clip_duration <= 0:
        return [], seg_counter

    cut_points = _collect_cut_points(clip, clip_duration, silence_threshold)
    cut_points = _merge_close_cut_points(cut_points, min_segment_duration)

    # Create segments between consecutive cut points
    raw_segments: list[tuple[float, float]] = []
    for i in range(len(cut_points) - 1):
        in_pt = round(cut_points[i], 4)
        out_pt = round(cut_points[i + 1], 4)
        raw_segments.append((in_pt, out_pt))

    # Filter out segments shorter than min_segment_duration, unless it is
    # the only segment for this clip.
    if len(raw_segments) > 1:
        filtered = [
            (a, b)
            for a, b in raw_segments
            if round(b - a, 4) >= min_segment_duration
        ]
        # If filtering removed everything, keep the longest one
        if not filtered:
            filtered = [max(raw_segments, key=lambda s: s[1] - s[0])]
        raw_segments = filtered

    clip_id = clip["id"]
    segments: list[dict] = []
    for in_pt, out_pt in raw_segments:
        seg_counter += 1
        seg_id = f"seg_{seg_counter:03d}"
        duration = round(out_pt - in_pt, 4)
        segments.append({
            "id": seg_id,
            "clip_id": clip_id,
            "in_point": in_pt,
            "out_point": out_pt,
            "duration": duration,
            "include": True,
            "interest_score": 0.0,
            "tags": [],
            "notes": "",
            "crop_16_9": {},
            "crop_9_16": {"keyframes": []},
            "audio_gain_db": 0.0,
            "speed_factor": 1.0,
        })

    return segments, seg_counter


# ---------------------------------------------------------------------------
# Step 2: Compute interest score for each segment
# ---------------------------------------------------------------------------


def _speech_ratio_in_range(
    vad: dict | None,
    in_pt: float,
    out_pt: float,
) -> float:
    """Calculate the fraction of [in_pt, out_pt] that contains speech."""
    if not vad or not isinstance(vad, dict):
        return 0.0

    seg_duration = out_pt - in_pt
    if seg_duration <= 0:
        return 0.0

    total_speech = 0.0
    for seg in vad.get("speech_segments", []):
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", 0.0))

        # Clamp to segment range
        overlap_start = max(s_start, in_pt)
        overlap_end = min(s_end, out_pt)
        if overlap_end > overlap_start:
            total_speech += overlap_end - overlap_start

    return min(total_speech / seg_duration, 1.0)


def _emphasis_density(
    pitch: dict | None,
    in_pt: float,
    out_pt: float,
) -> float:
    """Count emphasis points within the segment, normalized by duration.

    Returns a value in [0, 1] — capped at 1.0 for 5+ points per 10 seconds.
    """
    if not pitch or not isinstance(pitch, dict):
        return 0.0

    seg_duration = out_pt - in_pt
    if seg_duration <= 0:
        return 0.0

    count = 0
    for pt in pitch.get("emphasis_points", []):
        t = pt.get("time")
        if t is not None and in_pt <= float(t) <= out_pt:
            count += 1

    # Normalize: expect roughly 0.5 points/second as "high"
    density = count / seg_duration
    return min(density / 0.5, 1.0)


def _scene_change_density(
    scenes: dict | None,
    in_pt: float,
    out_pt: float,
) -> float:
    """Count scene boundaries within the segment, normalized.

    Returns a value in [0, 1].
    """
    if not scenes or not isinstance(scenes, dict):
        return 0.0

    seg_duration = out_pt - in_pt
    if seg_duration <= 0:
        return 0.0

    count = 0
    for boundary in scenes.get("boundaries", []):
        t = boundary.get("time")
        if t is not None and in_pt < float(t) < out_pt:
            count += 1

    # Normalize: 1 change per 10s is "moderate", 3+ is "high"
    density = count / (seg_duration / 10.0)
    return min(density / 3.0, 1.0)


def _person_visible_in_segment(
    clip: dict,
    in_pt: float,
    out_pt: float,
    frame_time_index: list[tuple[str, float]],
) -> bool:
    """Return True if any YOLO frame in this segment range contains a person."""
    yolo = clip.get("yolo")
    if not yolo or not isinstance(yolo, dict):
        return False

    detections_by_frame = yolo.get("detections_by_frame", {})
    if not detections_by_frame:
        return False

    for frame_path, frame_time in frame_time_index:
        if frame_time < in_pt:
            continue
        if frame_time > out_pt:
            break

        detections = detections_by_frame.get(frame_path, [])
        for det in detections:
            if det.get("class") == "person":
                return True

    return False


def _silence_ratio_in_range(
    vad: dict | None,
    in_pt: float,
    out_pt: float,
) -> float:
    """Calculate the fraction of [in_pt, out_pt] that is silence."""
    speech_ratio = _speech_ratio_in_range(vad, in_pt, out_pt)
    return 1.0 - speech_ratio


def compute_interest_score(
    clip: dict,
    segment: dict,
    frame_time_index: list[tuple[str, float]],
) -> float:
    """Compute an interest score in [0.0, 1.0] for a segment.

    Weighted factors:
        speech_ratio:     0.3
        pitch_variation:  0.2
        scene_changes:    0.1
        person_present:   0.2
        not_dead_silence: 0.2
    """
    in_pt = segment["in_point"]
    out_pt = segment["out_point"]

    vad = clip.get("vad")
    pitch = clip.get("pitch")
    scenes = clip.get("scenes")

    # Factor 1: speech ratio (weight 0.3)
    speech = _speech_ratio_in_range(vad, in_pt, out_pt)

    # Factor 2: pitch emphasis density (weight 0.2)
    emphasis = _emphasis_density(pitch, in_pt, out_pt)

    # Factor 3: scene change density (weight 0.1)
    scene_changes = _scene_change_density(scenes, in_pt, out_pt)

    # Factor 4: person present (weight 0.2)
    person = 1.0 if _person_visible_in_segment(clip, in_pt, out_pt, frame_time_index) else 0.0

    # Factor 5: not dead silence (weight 0.2)
    silence_ratio = _silence_ratio_in_range(vad, in_pt, out_pt)
    if silence_ratio > SILENCE_TAG_RATIO:
        not_dead_silence = 0.0
    else:
        not_dead_silence = 1.0 - silence_ratio

    score = (
        0.3 * speech
        + 0.2 * emphasis
        + 0.1 * scene_changes
        + 0.2 * person
        + 0.2 * not_dead_silence
    )

    # Override: if segment is > 80% silence, cap interest at 0.1
    if silence_ratio > SILENCE_TAG_RATIO:
        score = min(score, 0.1)

    return round(min(max(score, 0.0), 1.0), 4)


# ---------------------------------------------------------------------------
# Step 3: Assign tags to each segment
# ---------------------------------------------------------------------------


def _person_facing_camera_in_segment(
    clip: dict,
    in_pt: float,
    out_pt: float,
    frame_time_index: list[tuple[str, float]],
) -> bool:
    """Return True if a person facing the camera is detected in the segment."""
    yolo = clip.get("yolo")
    if not yolo or not isinstance(yolo, dict):
        return False

    detections_by_frame = yolo.get("detections_by_frame", {})
    for frame_path, frame_time in frame_time_index:
        if frame_time < in_pt:
            continue
        if frame_time > out_pt:
            break

        for det in detections_by_frame.get(frame_path, []):
            if det.get("class") != "person":
                continue
            pose = det.get("pose")
            if pose and isinstance(pose, dict):
                if pose.get("facing") == "camera":
                    return True

    return False


def _has_screen_recording_activity(
    clip: dict,
    in_pt: float,
    out_pt: float,
) -> bool:
    """Return True if vision analysis labels any frame in the range as 'demo'."""
    vision = clip.get("vision")
    if not vision or not isinstance(vision, dict):
        return False

    for analysis in vision.get("analyses", []):
        t = analysis.get("time")
        if t is not None and in_pt <= float(t) <= out_pt:
            if analysis.get("activity") == "demo":
                return True

    # Also check if the clip type itself is screen_recording
    if clip.get("type") == "screen_recording":
        return True

    return False


def assign_tags(
    clip: dict,
    segment: dict,
    frame_time_index: list[tuple[str, float]],
    is_first_segment_of_first_clip: bool,
    is_last_segment_of_last_clip: bool,
) -> list[str]:
    """Determine descriptive tags for a segment."""
    tags: list[str] = []

    in_pt = segment["in_point"]
    out_pt = segment["out_point"]
    vad = clip.get("vad")

    speech_ratio = _speech_ratio_in_range(vad, in_pt, out_pt)
    silence_ratio = 1.0 - speech_ratio
    has_person = _person_visible_in_segment(clip, in_pt, out_pt, frame_time_index)
    person_facing = _person_facing_camera_in_segment(clip, in_pt, out_pt, frame_time_index)
    is_demo = _has_screen_recording_activity(clip, in_pt, out_pt)

    # talking_head: person facing camera + speech
    if person_facing and speech_ratio > 0.3:
        tags.append("talking_head")

    # b_roll: no person or person facing away + no speech
    if (not has_person or not person_facing) and speech_ratio < 0.2:
        tags.append("b_roll")

    # demo: screen recording present
    if is_demo:
        tags.append("demo")

    # intro: first segment of first clip
    if is_first_segment_of_first_clip:
        tags.append("intro")

    # outro: last segment of last clip
    if is_last_segment_of_last_clip:
        tags.append("outro")

    # silence: > 80% silence
    if silence_ratio > SILENCE_TAG_RATIO:
        tags.append("silence")

    # action: high scene change rate
    scenes = clip.get("scenes")
    scene_density = _scene_change_density(scenes, in_pt, out_pt)
    if scene_density > 0.5:
        tags.append("action")

    # emphasis: high pitch emphasis density
    pitch = clip.get("pitch")
    emph_density = _emphasis_density(pitch, in_pt, out_pt)
    if emph_density > 0.5:
        tags.append("emphasis")

    return tags


# ---------------------------------------------------------------------------
# Step 4: Set crop regions
# ---------------------------------------------------------------------------


def _round_to_even(value: float) -> int:
    """Round a float to the nearest even integer."""
    rounded = int(round(value))
    if rounded % 2 != 0:
        rounded += 1
    return rounded


def _clamp(value: int, low: int, high: int) -> int:
    """Clamp an integer to [low, high]."""
    return max(low, min(value, high))


def compute_crop_16_9(width: int, height: int) -> dict:
    """Compute the 16:9 crop region.

    If the source is already 16:9 or narrower, return full frame.
    If wider, center-crop to 16:9.
    """
    target_ratio = 16.0 / 9.0
    source_ratio = width / height if height > 0 else target_ratio

    if source_ratio <= target_ratio + 0.01:
        # Already 16:9 or narrower — use full frame
        return {"x": 0, "y": 0, "w": width, "h": height}

    # Source is wider than 16:9 — crop width
    crop_w = _round_to_even(height * target_ratio)
    crop_w = min(crop_w, width)
    crop_x = (width - crop_w) // 2
    return {"x": crop_x, "y": 0, "w": crop_w, "h": height}


def _get_person_median_center_x(
    clip: dict,
    in_pt: float,
    out_pt: float,
    frame_time_index: list[tuple[str, float]],
) -> int | None:
    """Find the median center_x of detected persons within a time range.

    Returns None if no person detected.
    """
    yolo = clip.get("yolo")
    if not yolo or not isinstance(yolo, dict):
        return None

    detections_by_frame = yolo.get("detections_by_frame", {})
    center_xs: list[float] = []

    for frame_path, frame_time in frame_time_index:
        if frame_time < in_pt:
            continue
        if frame_time > out_pt:
            break

        for det in detections_by_frame.get(frame_path, []):
            if det.get("class") != "person":
                continue

            # bbox_xywh is [center_x, center_y, w, h]
            bbox_xywh = det.get("bbox_xywh")
            if bbox_xywh and len(bbox_xywh) >= 2:
                center_xs.append(float(bbox_xywh[0]))
                continue

            # Fallback to bbox_xyxy [x1, y1, x2, y2]
            bbox_xyxy = det.get("bbox_xyxy")
            if bbox_xyxy and len(bbox_xyxy) >= 4:
                cx = (float(bbox_xyxy[0]) + float(bbox_xyxy[2])) / 2.0
                center_xs.append(cx)

    if not center_xs:
        # Try tracking_summary as a fallback
        tracking = yolo.get("tracking_summary")
        if tracking and isinstance(tracking, dict):
            bbox_median = tracking.get("primary_subject_bbox_median")
            if bbox_median and len(bbox_median) >= 4:
                cx = (float(bbox_median[0]) + float(bbox_median[2])) / 2.0
                return int(round(cx))
        return None

    center_xs.sort()
    mid = len(center_xs) // 2
    if len(center_xs) % 2 == 0 and len(center_xs) > 1:
        median = (center_xs[mid - 1] + center_xs[mid]) / 2.0
    else:
        median = center_xs[mid]

    return int(round(median))


def _get_emphasis_times_in_range(
    clip: dict,
    in_pt: float,
    out_pt: float,
) -> list[float]:
    """Return sorted emphasis point times that fall within [in_pt, out_pt]."""
    pitch = clip.get("pitch")
    if not pitch or not isinstance(pitch, dict):
        return []

    times = []
    for pt in pitch.get("emphasis_points", []):
        t = pt.get("time")
        if t is not None:
            tf = float(t)
            if in_pt <= tf <= out_pt:
                times.append(tf)

    times.sort()
    return times


def compute_crop_9_16(
    clip: dict,
    segment: dict,
    frame_time_index: list[tuple[str, float]],
    source_width: int,
    source_height: int,
) -> dict:
    """Compute 9:16 crop keyframes for a segment.

    Returns {"keyframes": [...]}.
    """
    if source_height <= 0 or source_width <= 0:
        return {"keyframes": []}

    crop_width = _round_to_even(source_height * 9.0 / 16.0)
    crop_width = min(crop_width, source_width)
    crop_height = source_height

    in_pt = segment["in_point"]
    out_pt = segment["out_point"]

    # Determine the subject's horizontal center
    person_cx = _get_person_median_center_x(clip, in_pt, out_pt, frame_time_index)

    if person_cx is not None:
        center_x = person_cx
    else:
        center_x = source_width // 2

    # Compute crop x to center on the subject
    max_x = source_width - crop_width
    crop_x = _clamp(center_x - crop_width // 2, 0, max_x)

    # Build keyframes
    keyframes: list[dict] = []

    # Keyframe at segment start
    keyframes.append({
        "time": round(in_pt, 4),
        "x": crop_x,
        "y": 0,
        "w": crop_width,
        "h": crop_height,
        "easing": "SINE",
    })

    # Keyframes at emphasis points — only if they cause a position change
    emphasis_times = _get_emphasis_times_in_range(clip, in_pt, out_pt)
    last_x = crop_x

    for et in emphasis_times:
        # At emphasis points, re-center on person if available at that moment
        person_cx_at_emphasis = _get_person_median_center_x(
            clip,
            max(in_pt, et - 1.0),
            min(out_pt, et + 1.0),
            frame_time_index,
        )
        if person_cx_at_emphasis is not None:
            new_x = _clamp(person_cx_at_emphasis - crop_width // 2, 0, max_x)
        else:
            new_x = last_x

        if abs(new_x - last_x) > MINIMUM_CROP_MOVEMENT_PX:
            keyframes.append({
                "time": round(et, 4),
                "x": new_x,
                "y": 0,
                "w": crop_width,
                "h": crop_height,
                "easing": "BACK",
            })
            last_x = new_x

    # Keyframe at segment end — only if the position moved
    # Use SINE for between-segment easing
    if abs(crop_x - last_x) > MINIMUM_CROP_MOVEMENT_PX:
        keyframes.append({
            "time": round(out_pt, 4),
            "x": crop_x,
            "y": 0,
            "w": crop_width,
            "h": crop_height,
            "easing": "SINE",
        })
    elif len(keyframes) == 1:
        # Only the start keyframe exists and nothing moved — mark as CONSTANT
        keyframes[0]["easing"] = "CONSTANT"

    # Post-process: if consecutive keyframes have the same position,
    # set easing to CONSTANT. If they differ but aren't emphasis-driven,
    # use BEZIER.
    for i in range(len(keyframes) - 1):
        kf_curr = keyframes[i]
        kf_next = keyframes[i + 1]
        if kf_curr["x"] == kf_next["x"] and kf_curr["y"] == kf_next["y"]:
            kf_curr["easing"] = "CONSTANT"
        elif kf_curr["easing"] not in ("BACK", "SINE"):
            kf_curr["easing"] = "BEZIER"

    return {"keyframes": keyframes}


# ---------------------------------------------------------------------------
# Step 5: Set include flag
# ---------------------------------------------------------------------------


def should_include_segment(segment: dict) -> bool:
    """Determine if a segment should be included in the final edit."""
    interest = segment.get("interest_score", 0.0)
    tags = segment.get("tags", [])
    duration = segment.get("duration", 0.0)

    # Silence segments longer than 3s are excluded
    if "silence" in tags and duration > 3.0:
        return False

    # Low interest segments are excluded
    if interest < INTEREST_INCLUDE_THRESHOLD:
        return False

    return True


# ---------------------------------------------------------------------------
# Step 6 & 7: Build timeline order and suggest transitions
# ---------------------------------------------------------------------------


def build_order(all_segments: list[dict]) -> list[str]:
    """Return the chronological order of included segment IDs."""
    included = [s for s in all_segments if s.get("include", False)]
    # Already in chronological order (we built them clip-by-clip, in order)
    return [s["id"] for s in included]


def suggest_transitions(
    order: list[str],
    segments_by_id: dict[str, dict],
) -> list[dict]:
    """Suggest transitions between consecutive segments in the order list."""
    transitions: list[dict] = []

    for i in range(len(order) - 1):
        from_seg = segments_by_id[order[i]]
        to_seg = segments_by_id[order[i + 1]]

        from_clip = from_seg["clip_id"]
        to_clip = to_seg["clip_id"]

        if from_clip == to_clip:
            # Same clip — check if continuous
            gap = abs(to_seg["in_point"] - from_seg["out_point"])
            if gap < 0.01:
                # Continuous: hard cut
                transitions.append({
                    "from_segment": from_seg["id"],
                    "to_segment": to_seg["id"],
                    "type": "cut",
                    "duration_seconds": 0.0,
                })
            else:
                # Same clip but non-continuous (segments were removed)
                transitions.append({
                    "from_segment": from_seg["id"],
                    "to_segment": to_seg["id"],
                    "type": "crossfade",
                    "duration_seconds": 0.5,
                })
        else:
            # Different clips
            transitions.append({
                "from_segment": from_seg["id"],
                "to_segment": to_seg["id"],
                "type": "fade_black",
                "duration_seconds": 0.8,
            })

    return transitions


# ---------------------------------------------------------------------------
# Step 8: Calculate total duration
# ---------------------------------------------------------------------------


def calculate_total_duration(
    order: list[str],
    segments_by_id: dict[str, dict],
    transitions: list[dict],
) -> float:
    """Sum durations of included segments, subtracting transition overlaps."""
    total = 0.0
    for seg_id in order:
        seg = segments_by_id.get(seg_id)
        if seg:
            total += seg.get("duration", 0.0)

    # Subtract transition durations (crossfades and fades overlap the segments)
    for tr in transitions:
        total -= tr.get("duration_seconds", 0.0)

    return round(max(total, 0.0), 4)


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(manifest: dict) -> None:
    """Mark phase 11 as completed in pipeline_state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state = manifest.setdefault("pipeline_state", {})
    phase_results = state.setdefault("phase_results", {})
    completed = state.setdefault("completed_phases", [])

    phase_results["11"] = {
        "status": "success",
        "timestamp": now,
    }

    if 11 not in completed:
        completed.append(11)
        completed.sort()

    current = state.get("current_phase", 0)
    if current < 11:
        state["current_phase"] = 11

    state["last_updated"] = now


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_timeline(
    manifest: dict,
    min_segment_duration: float,
    silence_threshold: float,
) -> dict:
    """Build the timeline structure from clip analysis data.

    Returns a dict with keys: segments, order, transitions, total_duration_seconds.
    """
    clips = manifest.get("clips", [])
    if not clips:
        _fatal("No clips found in manifest")

    all_segments: list[dict] = []
    seg_counter = 0
    total_clips = len(clips)

    for clip_idx, clip in enumerate(clips):
        clip_id = clip.get("id", f"clip_{clip_idx + 1:03d}")
        metadata = clip.get("metadata", {})
        clip_duration = metadata.get("duration_seconds")

        if clip_duration is None or clip_duration <= 0:
            print(
                f"WARNING: clip {clip_id} has no valid duration, skipping",
                file=sys.stderr,
            )
            continue

        clip_duration = float(clip_duration)
        source_width = metadata.get("width")
        source_height = metadata.get("height")

        # Build frame-time index for YOLO lookups
        frame_time_index = _build_frame_time_index(clip)

        # Step 1: Build segments
        segments, seg_counter = build_segments_for_clip(
            clip,
            clip_duration,
            silence_threshold,
            min_segment_duration,
            seg_counter,
        )

        if not segments:
            # Create at least one segment covering the whole clip
            seg_counter += 1
            segments = [{
                "id": f"seg_{seg_counter:03d}",
                "clip_id": clip_id,
                "in_point": 0.0,
                "out_point": round(clip_duration, 4),
                "duration": round(clip_duration, 4),
                "include": True,
                "interest_score": 0.0,
                "tags": [],
                "notes": "",
                "crop_16_9": {},
                "crop_9_16": {"keyframes": []},
                "audio_gain_db": 0.0,
                "speed_factor": 1.0,
            }]

        for seg_idx, segment in enumerate(segments):
            # Step 2: Compute interest score
            segment["interest_score"] = compute_interest_score(
                clip, segment, frame_time_index,
            )

            # Step 3: Assign tags
            is_first = (clip_idx == 0 and seg_idx == 0)
            is_last = (clip_idx == total_clips - 1 and seg_idx == len(segments) - 1)

            segment["tags"] = assign_tags(
                clip, segment, frame_time_index,
                is_first_segment_of_first_clip=is_first,
                is_last_segment_of_last_clip=is_last,
            )

            # Step 4: Compute crop regions
            if source_width is not None and source_height is not None:
                w = int(source_width)
                h = int(source_height)

                segment["crop_16_9"] = compute_crop_16_9(w, h)
                segment["crop_9_16"] = compute_crop_9_16(
                    clip, segment, frame_time_index, w, h,
                )
            else:
                # No resolution info — leave crops empty
                segment["crop_16_9"] = {}
                segment["crop_9_16"] = {"keyframes": []}

            # Step 5: Set include flag
            segment["include"] = should_include_segment(segment)

        all_segments.extend(segments)

    # Step 6: Build order
    order = build_order(all_segments)

    # Step 7: Suggest transitions
    segments_by_id = {s["id"]: s for s in all_segments}
    transitions = suggest_transitions(order, segments_by_id)

    # Step 8: Calculate total duration
    total_duration = calculate_total_duration(order, segments_by_id, transitions)

    return {
        "segments": all_segments,
        "order": order,
        "transitions": transitions,
        "total_duration_seconds": total_duration,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the editorial timeline from clip analysis data.",
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Path to the project root directory containing footage_manifest.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Rebuild the timeline even if it already exists",
    )
    parser.add_argument(
        "--min-segment-duration",
        type=float,
        default=3.0,
        help="Minimum segment length in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--silence-threshold",
        type=float,
        default=1.5,
        help="Silence gaps longer than this (in seconds) create segment breaks (default: 1.5)",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        _fatal(f"Project root does not exist: {project_root}")

    if args.min_segment_duration <= 0:
        _fatal(f"--min-segment-duration must be positive, got {args.min_segment_duration}")

    if args.silence_threshold <= 0:
        _fatal(f"--silence-threshold must be positive, got {args.silence_threshold}")

    manifest = load_manifest(project_root)

    # Check if timeline already exists
    existing_timeline = manifest.get("timeline")
    if existing_timeline and not args.force:
        segments = existing_timeline.get("segments", [])
        if segments:
            result = {
                "status": "success",
                "message": "Timeline already exists, skipping (use --force to rebuild)",
                "details": {
                    "total_segments": len(segments),
                    "included": len(existing_timeline.get("order", [])),
                    "excluded": len(segments) - len(existing_timeline.get("order", [])),
                    "total_duration": existing_timeline.get("total_duration_seconds", 0.0),
                },
            }
            print(json.dumps(result))
            return

    # Build the timeline
    timeline = build_timeline(
        manifest,
        min_segment_duration=args.min_segment_duration,
        silence_threshold=args.silence_threshold,
    )

    # Write to manifest
    manifest["timeline"] = timeline

    # Update pipeline state
    update_pipeline_state(manifest)

    # Save
    save_manifest(project_root, manifest)

    # Report results
    total_segments = len(timeline["segments"])
    included = len(timeline["order"])
    excluded = total_segments - included
    total_duration = timeline["total_duration_seconds"]

    result = {
        "status": "success",
        "message": (
            f"Built timeline with {total_segments} segments "
            f"({included} included, {excluded} excluded), "
            f"total duration {total_duration:.1f}s"
        ),
        "details": {
            "total_segments": total_segments,
            "included": included,
            "excluded": excluded,
            "total_duration": total_duration,
        },
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
