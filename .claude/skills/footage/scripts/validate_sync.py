#!/usr/bin/env python3
"""Validate audio/video alignment and timeline consistency in a footage project.

Non-destructive: reads the manifest and file system, writes a validation
report, but never modifies source data.

Phase 18 of the footage pipeline.

Usage:
    python3 validate_sync.py <project_root> [--tolerance 0.05]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Issue severity levels (ordered)
# ---------------------------------------------------------------------------

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest(project_root: Path) -> dict:
    """Load and return the footage manifest. Exits on failure."""
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.is_file():
        print(
            json.dumps({
                "status": "error",
                "message": f"Manifest not found at {manifest_path}",
                "details": {"checks_passed": 0, "checks_failed": 0, "issues": []},
            }),
        )
        sys.exit(0)

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            json.dumps({
                "status": "error",
                "message": f"Failed to read manifest: {exc}",
                "details": {"checks_passed": 0, "checks_failed": 0, "issues": []},
            }),
        )
        sys.exit(0)


def save_manifest(project_root: Path, manifest: dict) -> None:
    """Atomically write the manifest back to disk."""
    manifest_path = project_root / "footage_manifest.json"
    tmp_path = manifest_path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp_path.replace(manifest_path)
    except OSError as exc:
        print(f"Failed to write manifest: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Individual validation checks
# ---------------------------------------------------------------------------


def validate_audio_video_sync(
    clips: list[dict],
    tolerance: float,
    issues: list[dict],
) -> tuple[int, int]:
    """Compare audio duration with video duration for each clip.

    Returns (checks_passed, checks_failed).
    """
    passed = 0
    failed = 0

    for clip in clips:
        clip_id = clip.get("id", "unknown")
        audio = clip.get("audio")
        metadata = clip.get("metadata", {})

        if audio is None or not isinstance(audio, dict):
            continue

        audio_duration = audio.get("duration_seconds")
        video_duration = metadata.get("duration_seconds")

        if audio_duration is None or video_duration is None:
            issues.append({
                "severity": SEVERITY_INFO,
                "check": "audio_video_sync",
                "clip_id": clip_id,
                "message": (
                    f"Cannot compare durations: audio_duration={audio_duration}, "
                    f"video_duration={video_duration}"
                ),
            })
            continue

        drift = abs(audio_duration - video_duration)
        if drift > tolerance:
            issues.append({
                "severity": SEVERITY_WARNING,
                "check": "audio_video_sync",
                "clip_id": clip_id,
                "message": (
                    f"Audio/video drift of {drift:.4f}s exceeds tolerance "
                    f"({tolerance}s): audio={audio_duration:.4f}s, "
                    f"video={video_duration:.4f}s"
                ),
            })
            failed += 1
        else:
            passed += 1

    return passed, failed


def validate_screen_sync(
    clips: list[dict],
    issues: list[dict],
) -> tuple[int, int]:
    """Verify screen_sync correlation_score and offset_seconds for screen recordings.

    Returns (checks_passed, checks_failed).
    """
    passed = 0
    failed = 0

    for clip in clips:
        clip_id = clip.get("id", "unknown")
        screen_sync = clip.get("screen_sync")

        if screen_sync is None or not isinstance(screen_sync, dict):
            continue

        metadata = clip.get("metadata", {})
        clip_duration = metadata.get("duration_seconds")

        # Check correlation_score
        correlation_score = screen_sync.get("correlation_score")
        if correlation_score is not None:
            if correlation_score < 0.3:
                issues.append({
                    "severity": SEVERITY_WARNING,
                    "check": "screen_sync_correlation",
                    "clip_id": clip_id,
                    "message": (
                        f"Screen sync correlation_score {correlation_score:.4f} "
                        f"is below minimum threshold of 0.3"
                    ),
                })
                failed += 1
            else:
                passed += 1

        # Check offset_seconds
        offset_seconds = screen_sync.get("offset_seconds")
        if offset_seconds is not None and clip_duration is not None:
            if abs(offset_seconds) > clip_duration:
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "check": "screen_sync_offset",
                    "clip_id": clip_id,
                    "message": (
                        f"Screen sync offset_seconds {offset_seconds:.4f}s "
                        f"exceeds clip duration {clip_duration:.4f}s"
                    ),
                })
                failed += 1
            else:
                passed += 1

    return passed, failed


def validate_timeline_consistency(
    timeline: dict,
    clips: list[dict],
    issues: list[dict],
) -> tuple[int, int]:
    """Check timeline segments, order, crop bounds, transitions, and total duration.

    Returns (checks_passed, checks_failed).
    """
    passed = 0
    failed = 0

    segments_list = timeline.get("segments", [])
    order = timeline.get("order", [])
    transitions = timeline.get("transitions", [])
    declared_total = timeline.get("total_duration_seconds")

    if not segments_list and not order:
        # Timeline not yet populated -- nothing to validate
        return passed, failed

    # Build a lookup of segment IDs and a lookup of clip metadata for frame bounds
    segment_map: dict[str, dict] = {}
    for seg in segments_list:
        seg_id = seg.get("id")
        if seg_id is not None:
            segment_map[seg_id] = seg

    clip_metadata_map: dict[str, dict] = {}
    for clip in clips:
        clip_id = clip.get("id")
        if clip_id is not None:
            clip_metadata_map[clip_id] = clip.get("metadata", {})

    # 1. All segment IDs in order must exist in segments
    for seg_id in order:
        if seg_id not in segment_map:
            issues.append({
                "severity": SEVERITY_ERROR,
                "check": "timeline_order_references",
                "clip_id": None,
                "message": (
                    f"Segment '{seg_id}' referenced in timeline.order "
                    f"does not exist in timeline.segments"
                ),
            })
            failed += 1
        else:
            passed += 1

    # 2. in_point < out_point for each segment
    for seg in segments_list:
        seg_id = seg.get("id", "unknown")
        in_point = seg.get("in_point")
        out_point = seg.get("out_point")

        if in_point is not None and out_point is not None:
            if in_point >= out_point:
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "check": "timeline_segment_points",
                    "clip_id": seg_id,
                    "message": (
                        f"Segment '{seg_id}': in_point ({in_point}) >= "
                        f"out_point ({out_point})"
                    ),
                })
                failed += 1
            else:
                passed += 1

    # 3. Crop coordinates within frame bounds
    for seg in segments_list:
        seg_id = seg.get("id", "unknown")
        clip_id = seg.get("clip_id")
        meta = clip_metadata_map.get(clip_id, {}) if clip_id else {}
        frame_w = meta.get("width")
        frame_h = meta.get("height")

        for crop_key in ("crop_16_9", "crop_9_16"):
            crop = seg.get(crop_key)
            if crop is None:
                continue

            # crop_9_16 may use keyframes instead of flat x/y/w/h
            keyframes = crop.get("keyframes") if isinstance(crop, dict) else None

            crop_entries = []
            if keyframes and isinstance(keyframes, list):
                crop_entries = keyframes
            elif isinstance(crop, dict) and "x" in crop and "y" in crop:
                crop_entries = [crop]

            for entry in crop_entries:
                cx = entry.get("x")
                cy = entry.get("y")
                cw = entry.get("w")
                ch = entry.get("h")

                if cx is None or cy is None or cw is None or ch is None:
                    continue

                if frame_w is None or frame_h is None:
                    # Cannot validate without frame dimensions
                    continue

                violations = []
                if cx < 0:
                    violations.append(f"x ({cx}) < 0")
                if cy < 0:
                    violations.append(f"y ({cy}) < 0")
                if cx + cw > frame_w:
                    violations.append(f"x+w ({cx + cw}) > frame width ({frame_w})")
                if cy + ch > frame_h:
                    violations.append(f"y+h ({cy + ch}) > frame height ({frame_h})")

                if violations:
                    issues.append({
                        "severity": SEVERITY_ERROR,
                        "check": "timeline_crop_bounds",
                        "clip_id": seg_id,
                        "message": (
                            f"Segment '{seg_id}' {crop_key} out of bounds: "
                            f"{'; '.join(violations)}"
                        ),
                    })
                    failed += 1
                else:
                    passed += 1

    # 4. Transition durations don't exceed segment durations
    for trans in transitions:
        trans_duration = trans.get("duration_seconds")
        if trans_duration is None or trans_duration <= 0:
            # Cut transitions have 0 duration -- always fine
            passed += 1
            continue

        from_id = trans.get("from_segment")
        to_id = trans.get("to_segment")

        for seg_id in (from_id, to_id):
            if seg_id is None:
                continue
            seg = segment_map.get(seg_id)
            if seg is None:
                continue

            seg_duration = seg.get("duration")
            if seg_duration is None:
                in_pt = seg.get("in_point")
                out_pt = seg.get("out_point")
                if in_pt is not None and out_pt is not None:
                    seg_duration = out_pt - in_pt

            if seg_duration is not None and trans_duration > seg_duration:
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "check": "timeline_transition_duration",
                    "clip_id": seg_id,
                    "message": (
                        f"Transition duration ({trans_duration}s) exceeds "
                        f"segment '{seg_id}' duration ({seg_duration}s)"
                    ),
                })
                failed += 1
            else:
                passed += 1

    # 5. total_duration_seconds matches sum of included segments
    if declared_total is not None and order:
        computed_total = 0.0
        computable = True

        for seg_id in order:
            seg = segment_map.get(seg_id)
            if seg is None:
                computable = False
                break

            include = seg.get("include", True)
            if not include:
                continue

            seg_duration = seg.get("duration")
            if seg_duration is None:
                in_pt = seg.get("in_point")
                out_pt = seg.get("out_point")
                if in_pt is not None and out_pt is not None:
                    seg_duration = out_pt - in_pt

            if seg_duration is None:
                computable = False
                break

            speed_factor = seg.get("speed_factor", 1.0)
            if speed_factor and speed_factor > 0:
                seg_duration = seg_duration / speed_factor

            computed_total += seg_duration

        # Subtract transition overlap durations
        if computable:
            for trans in transitions:
                td = trans.get("duration_seconds", 0.0)
                if td and td > 0:
                    computed_total -= td

        if computable:
            drift = abs(declared_total - computed_total)
            # Allow up to 0.5s tolerance for rounding across many segments
            if drift > 0.5:
                issues.append({
                    "severity": SEVERITY_WARNING,
                    "check": "timeline_total_duration",
                    "clip_id": None,
                    "message": (
                        f"Declared total_duration_seconds ({declared_total:.3f}s) "
                        f"differs from computed sum ({computed_total:.3f}s) "
                        f"by {drift:.3f}s"
                    ),
                })
                failed += 1
            else:
                passed += 1

    return passed, failed


def validate_audio_references(
    manifest: dict,
    project_root: Path,
    issues: list[dict],
) -> tuple[int, int]:
    """Verify that all audio file paths in the manifest exist on disk.

    Returns (checks_passed, checks_failed).
    """
    passed = 0
    failed = 0

    clips = manifest.get("clips", [])

    # Check clip audio files
    for clip in clips:
        clip_id = clip.get("id", "unknown")
        audio = clip.get("audio")

        if audio is None or not isinstance(audio, dict):
            continue

        for path_key in ("extracted_path", "denoised_path"):
            rel_path = audio.get(path_key)
            if rel_path is None:
                continue

            abs_path = project_root / rel_path
            if not abs_path.exists():
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "check": "audio_file_exists",
                    "clip_id": clip_id,
                    "message": (
                        f"Audio file not found: {rel_path} "
                        f"(clip {clip_id}, key: {path_key})"
                    ),
                })
                failed += 1
            else:
                passed += 1

    # Check SFX files
    sfx_list = manifest.get("sfx", [])
    if isinstance(sfx_list, list):
        for sfx in sfx_list:
            sfx_id = sfx.get("id", "unknown")
            generated_path = sfx.get("generated_path")
            if generated_path is None:
                continue

            abs_path = project_root / generated_path
            if not abs_path.exists():
                issues.append({
                    "severity": SEVERITY_WARNING,
                    "check": "sfx_file_exists",
                    "clip_id": sfx_id,
                    "message": f"SFX file not found: {generated_path} (sfx {sfx_id})",
                })
                failed += 1
            else:
                passed += 1

    # Check music files
    music = manifest.get("music", {})
    tracks = music.get("tracks", []) if isinstance(music, dict) else []
    if isinstance(tracks, list):
        for track in tracks:
            track_id = track.get("id", "unknown")
            generated_path = track.get("generated_path")
            if generated_path is None:
                continue

            abs_path = project_root / generated_path
            if not abs_path.exists():
                issues.append({
                    "severity": SEVERITY_WARNING,
                    "check": "music_file_exists",
                    "clip_id": track_id,
                    "message": (
                        f"Music file not found: {generated_path} "
                        f"(track {track_id})"
                    ),
                })
                failed += 1
            else:
                passed += 1

    return passed, failed


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


def write_validation_report(
    project_root: Path,
    issues: list[dict],
    checks_passed: int,
    checks_failed: int,
) -> Path:
    """Write the validation report JSON to disk. Returns the report path."""
    report_dir = project_root / "analysis"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation_report.json"

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "total_issues": len(issues),
        "issues_by_severity": {
            SEVERITY_ERROR: [i for i in issues if i["severity"] == SEVERITY_ERROR],
            SEVERITY_WARNING: [i for i in issues if i["severity"] == SEVERITY_WARNING],
            SEVERITY_INFO: [i for i in issues if i["severity"] == SEVERITY_INFO],
        },
        "all_issues": issues,
    }

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as exc:
        print(f"Failed to write validation report: {exc}", file=sys.stderr)

    return report_path


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(
    manifest: dict,
    checks_passed: int,
    checks_failed: int,
    issues: list[dict],
) -> None:
    """Mark phase 18 as complete in pipeline_state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state = manifest.setdefault("pipeline_state", {
        "current_phase": 18,
        "completed_phases": [],
        "phase_results": {},
        "errors": [],
        "warnings": [],
        "last_updated": now,
    })

    error_count = sum(1 for i in issues if i["severity"] == SEVERITY_ERROR)
    warning_count = sum(1 for i in issues if i["severity"] == SEVERITY_WARNING)

    phase_results = state.setdefault("phase_results", {})
    phase_results["18"] = {
        "status": "success",
        "timestamp": now,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "errors_found": error_count,
        "warnings_found": warning_count,
    }

    completed = state.setdefault("completed_phases", [])
    if 18 not in completed:
        completed.append(18)
        completed.sort()

    current = state.get("current_phase", 0)
    if current <= 18:
        state["current_phase"] = 19

    state["last_updated"] = now


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate audio/video alignment and timeline consistency.",
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Path to the project root directory",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Maximum acceptable audio/video drift in seconds (default: 0.05)",
    )
    args = parser.parse_args()

    project_root: Path = args.project_root.resolve()
    if not project_root.is_dir():
        print(
            json.dumps({
                "status": "error",
                "message": f"Project root does not exist: {project_root}",
                "details": {"checks_passed": 0, "checks_failed": 0, "issues": []},
            }),
        )
        sys.exit(0)

    if args.tolerance < 0:
        print(
            json.dumps({
                "status": "error",
                "message": f"--tolerance must be non-negative, got {args.tolerance}",
                "details": {"checks_passed": 0, "checks_failed": 0, "issues": []},
            }),
        )
        sys.exit(0)

    manifest = load_manifest(project_root)

    clips = manifest.get("clips", [])
    timeline = manifest.get("timeline", {})
    issues: list[dict] = []
    total_passed = 0
    total_failed = 0

    # --- Check 1: Audio/video sync ---
    p, f = validate_audio_video_sync(clips, args.tolerance, issues)
    total_passed += p
    total_failed += f

    # --- Check 2: Screen sync data ---
    p, f = validate_screen_sync(clips, issues)
    total_passed += p
    total_failed += f

    # --- Check 3: Timeline consistency ---
    if isinstance(timeline, dict):
        p, f = validate_timeline_consistency(timeline, clips, issues)
        total_passed += p
        total_failed += f

    # --- Check 4: Audio file references ---
    p, f = validate_audio_references(manifest, project_root, issues)
    total_passed += p
    total_failed += f

    # --- Write report ---
    write_validation_report(project_root, issues, total_passed, total_failed)

    # --- Update pipeline state ---
    update_pipeline_state(manifest, total_passed, total_failed, issues)
    save_manifest(project_root, manifest)

    # --- Determine overall status ---
    error_issues = [i for i in issues if i["severity"] == SEVERITY_ERROR]
    warning_issues = [i for i in issues if i["severity"] == SEVERITY_WARNING]

    if error_issues:
        status = "warning"
        message = (
            f"Validation complete: {total_passed} passed, {total_failed} failed "
            f"({len(error_issues)} errors, {len(warning_issues)} warnings)"
        )
    elif warning_issues:
        status = "warning"
        message = (
            f"Validation complete with warnings: {total_passed} passed, "
            f"{total_failed} failed ({len(warning_issues)} warnings)"
        )
    else:
        status = "success"
        message = f"Validation complete: all {total_passed} checks passed"

    # Build condensed issue list for stdout (full details are in the report file)
    condensed_issues = [
        {
            "severity": i["severity"],
            "check": i["check"],
            "clip_id": i.get("clip_id"),
            "message": i["message"],
        }
        for i in issues
    ]

    output = {
        "status": status,
        "message": message,
        "details": {
            "checks_passed": total_passed,
            "checks_failed": total_failed,
            "issues": condensed_issues,
        },
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
