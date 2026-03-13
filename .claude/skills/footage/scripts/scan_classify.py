"""Scan input video files, extract metadata via ffprobe, classify each as
camera footage or screen recording, and populate the footage manifest.

Usage:
    python3 scan_classify.py <project_root> [--force]
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

FFPROBE_TIMEOUT = 30

# Common screen resolutions (width, height) used in classification heuristics.
COMMON_SCREEN_RESOLUTIONS = frozenset({
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
    (1440, 900),
    (2560, 1600),
    (1680, 1050),
    (1280, 800),
    (1366, 768),
    (2880, 1800),
    (3024, 1964),
    (2560, 1664),
    (3456, 2234),
    (2048, 1536),
    (1920, 1200),
})

# Camera model keywords that indicate genuine camera hardware.
CAMERA_MODEL_KEYWORDS = (
    "gopro", "iphone", "samsung", "pixel", "canon", "nikon", "sony",
    "fujifilm", "panasonic", "olympus", "dji", "insta360", "ricoh",
    "blackmagic", "red", "arri", "hero",
)

# Filename patterns that suggest screen recording.
SCREEN_RECORDING_FILENAME_RE = re.compile(
    r"screen|capture|obs|screencast|recording|rec\d", re.IGNORECASE,
)


def run_ffprobe(file_path: Path) -> Optional[dict]:
    """Run ffprobe on *file_path* and return parsed JSON, or None on failure."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT,
        )
    except FileNotFoundError:
        logger.error("ffprobe not found on PATH — is ffmpeg installed?")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe timed out for %s", file_path)
        return None

    if result.returncode != 0:
        logger.warning(
            "ffprobe returned %d for %s: %s",
            result.returncode, file_path, result.stderr.strip(),
        )
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse ffprobe JSON for %s: %s", file_path, exc)
        return None


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_rational_fps(r_frame_rate: Optional[str]) -> Optional[float]:
    """Parse a rational frame rate string like '30000/1001' into a float."""
    if not r_frame_rate:
        return None
    if "/" in r_frame_rate:
        parts = r_frame_rate.split("/")
        if len(parts) == 2:
            num = _safe_float(parts[0])
            den = _safe_float(parts[1])
            if num is not None and den is not None and den != 0:
                return num / den
    return _safe_float(r_frame_rate)


def _find_video_stream(probe: dict) -> Optional[dict]:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return None


def _find_audio_stream(probe: dict) -> Optional[dict]:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "audio":
            return stream
    return None


def _extract_creation_time(probe: dict) -> Optional[str]:
    """Try multiple locations for creation_time metadata."""
    fmt_tags = probe.get("format", {}).get("tags", {})
    for key in ("creation_time", "date", "com.apple.quicktime.creationdate"):
        if key in fmt_tags:
            return fmt_tags[key]

    # Fall back to stream-level tags.
    for stream in probe.get("streams", []):
        tags = stream.get("tags", {})
        for key in ("creation_time", "date"):
            if key in tags:
                return tags[key]
    return None


def _extract_camera_model(probe: dict) -> Optional[str]:
    """Extract camera/device model from metadata tags."""
    fmt_tags = probe.get("format", {}).get("tags", {})
    for key in (
        "com.apple.quicktime.model",
        "model",
        "camera_model",
        "com.android.model",
    ):
        if key in fmt_tags:
            return fmt_tags[key]

    # Some containers expose it via handler_name in a video stream tag.
    for stream in probe.get("streams", []):
        tags = stream.get("tags", {})
        handler = tags.get("handler_name", "")
        # GoPro, DJI etc. often set handler_name to something identifiable.
        if handler and handler.lower() not in (
            "videohandler", "video handler", "video", "core media video",
            "soundhandler", "sound handler",
        ):
            return handler

    return None


def _extract_rotation(probe: dict) -> int:
    """Extract video rotation degrees from side_data or stream tags."""
    video = _find_video_stream(probe)
    if video is None:
        return 0

    # Modern ffprobe exposes rotation via side_data_list / displaymatrix.
    for sd in video.get("side_data_list", []):
        rotation = _safe_int(sd.get("rotation"))
        if rotation is not None:
            return rotation

    # Older metadata tag.
    tags = video.get("tags", {})
    rotation = _safe_int(tags.get("rotate"))
    if rotation is not None:
        return rotation

    return 0


def _has_gps_metadata(probe: dict) -> bool:
    """Return True if GPS/location metadata is present anywhere."""
    fmt_tags = probe.get("format", {}).get("tags", {})
    gps_keys = (
        "location", "com.apple.quicktime.location.ISO6709",
        "location-eng", "GPSCoordinates", "xyz",
    )
    for key in gps_keys:
        if key in fmt_tags:
            return True
    for stream in probe.get("streams", []):
        tags = stream.get("tags", {})
        for key in gps_keys:
            if key in tags:
                return True
    return False


def extract_metadata(probe: dict, file_path: Path) -> dict:
    """Build the metadata dict from ffprobe output."""
    video_stream = _find_video_stream(probe)
    audio_stream = _find_audio_stream(probe)
    fmt = probe.get("format", {})

    fps_rational = video_stream.get("r_frame_rate") if video_stream else None
    fps = _parse_rational_fps(fps_rational)

    width = _safe_int(video_stream.get("width")) if video_stream else None
    height = _safe_int(video_stream.get("height")) if video_stream else None

    # Account for rotation — if 90 or 270, swap width/height for the
    # effective resolution the viewer sees.
    rotation = _extract_rotation(probe)
    effective_width = width
    effective_height = height
    if abs(rotation) in (90, 270) and width is not None and height is not None:
        effective_width, effective_height = height, width

    duration = _safe_float(fmt.get("duration"))
    if duration is None and video_stream:
        duration = _safe_float(video_stream.get("duration"))

    bit_rate = _safe_int(fmt.get("bit_rate"))

    creation_time = _extract_creation_time(probe)
    camera_model = _extract_camera_model(probe)

    codec_video = video_stream.get("codec_name") if video_stream else None
    codec_audio = audio_stream.get("codec_name") if audio_stream else None
    audio_channels = _safe_int(audio_stream.get("channels")) if audio_stream else None
    audio_sample_rate = _safe_int(audio_stream.get("sample_rate")) if audio_stream else None

    file_size_bytes = _safe_int(fmt.get("size"))
    if file_size_bytes is None:
        try:
            file_size_bytes = file_path.stat().st_size
        except OSError:
            file_size_bytes = None

    return {
        "duration_seconds": duration,
        "width": effective_width,
        "height": effective_height,
        "fps": round(fps, 3) if fps is not None else None,
        "fps_rational": fps_rational,
        "codec_video": codec_video,
        "codec_audio": codec_audio,
        "audio_channels": audio_channels,
        "audio_sample_rate": audio_sample_rate,
        "bit_rate_bps": bit_rate,
        "creation_time": creation_time,
        "camera_model": camera_model,
        "rotation": rotation,
        "file_size_bytes": file_size_bytes,
        "has_audio": audio_stream is not None,
    }


def classify_clip(metadata: dict, filename: str, probe: dict) -> tuple[str, float]:
    """Return (type, confidence) for a clip using a score-based heuristic.

    Positive scores lean toward screen_recording; negative toward camera.
    """
    score = 0

    width = metadata.get("width")
    height = metadata.get("height")
    fps = metadata.get("fps")

    # 1. Resolution matches common screen res AND fps is exactly 30 or 60.
    if (width, height) in COMMON_SCREEN_RESOLUTIONS:
        if fps is not None and fps in (30.0, 60.0):
            score += 3

    # 2. No audio stream.
    if not metadata.get("has_audio"):
        score += 2

    # 3. Codec is h264 with high profile AND constant bitrate pattern.
    video_stream = _find_video_stream(probe)
    if video_stream:
        codec = (video_stream.get("codec_name") or "").lower()
        profile = (video_stream.get("profile") or "").lower()
        if codec == "h264" and "high" in profile:
            # Constant bitrate heuristic: stream bit_rate closely matches
            # format bit_rate (within 10%), suggesting CBR.
            stream_br = _safe_int(video_stream.get("bit_rate"))
            fmt_br = metadata.get("bit_rate_bps")
            if stream_br and fmt_br and fmt_br > 0:
                ratio = stream_br / fmt_br
                if 0.90 <= ratio <= 1.10:
                    score += 1

    # 4. No camera model in metadata.
    if not metadata.get("camera_model"):
        score += 1

    # 5. Filename contains screen-recording keywords.
    if SCREEN_RECORDING_FILENAME_RE.search(filename):
        score += 3

    # 6. Has recognizable camera model tag.
    camera_model = (metadata.get("camera_model") or "").lower()
    if any(kw in camera_model for kw in CAMERA_MODEL_KEYWORDS):
        score -= 3

    # 7. Typical camera fps (non-integer NTSC frame rates).
    if fps is not None:
        # Check for 23.976 (actually 24000/1001 ≈ 23.976) and 29.97.
        if abs(fps - 23.976) < 0.01 or abs(fps - 29.97) < 0.01:
            score -= 2

    # 8. Variable bitrate indication.
    if video_stream:
        # Check format vs stream bit_rate divergence as a VBR signal.
        stream_br = _safe_int(video_stream.get("bit_rate"))
        fmt_br = metadata.get("bit_rate_bps")
        is_vbr = False
        if stream_br and fmt_br and fmt_br > 0:
            ratio = stream_br / fmt_br
            if ratio < 0.85 or ratio > 1.15:
                is_vbr = True
        if is_vbr:
            score -= 1

    # 9. GPS/location metadata.
    if _has_gps_metadata(probe):
        score -= 3

    clip_type = "screen_recording" if score >= 3 else "camera"
    confidence = min(abs(score) / 6.0, 1.0)
    confidence = round(confidence, 3)

    logger.info(
        "Classification for %s: score=%d → %s (confidence=%.3f)",
        filename, score, clip_type, confidence,
    )

    return clip_type, confidence


def _creation_time_sortkey(entry: dict) -> str:
    """Return a string suitable for sorting — creation_time first, filename fallback."""
    ct = entry["metadata"].get("creation_time")
    if ct:
        return ct
    return entry["source_path"]


def create_symlink(project_root: Path, source: Path, clip_id: str) -> str:
    """Create a symlink at raw/clip_NNN.ext → source and return the relative symlink path."""
    raw_dir = project_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    ext = source.suffix  # e.g. ".mp4"
    symlink_name = f"{clip_id}{ext}"
    symlink_path = raw_dir / symlink_name
    relative_symlink = f"raw/{symlink_name}"

    if symlink_path.is_symlink() or symlink_path.exists():
        symlink_path.unlink()

    symlink_path.symlink_to(source.resolve())
    return relative_symlink


def build_clip_entry(
    clip_id: str,
    source_path: str,
    symlink_path: str,
    clip_type: str,
    confidence: float,
    metadata: dict,
) -> dict:
    """Build a full clip entry with all analysis fields initialized to null."""
    return {
        "id": clip_id,
        "source_path": source_path,
        "symlink_path": symlink_path,
        "type": clip_type,
        "classification_confidence": confidence,
        "metadata": metadata,
        "audio": None,
        "transcript": None,
        "vad": None,
        "pitch": None,
        "scenes": None,
        "frames": None,
        "yolo": None,
        "vision": None,
        "screen_sync": None,
    }


def load_manifest(project_root: Path) -> dict:
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.is_file():
        logger.error("Manifest not found: %s", manifest_path)
        sys.exit(1)
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read manifest: %s", exc)
        sys.exit(1)


def save_manifest(project_root: Path, manifest: dict) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan and classify footage source files.",
    )
    parser.add_argument("project_root", type=Path, help="Path to the project root directory")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process clips even if they already exist in the manifest",
    )
    args = parser.parse_args()

    project_root: Path = args.project_root.resolve()
    if not project_root.is_dir():
        logger.error("Project root does not exist: %s", project_root)
        sys.exit(1)

    manifest = load_manifest(project_root)

    source_files = manifest.get("project", {}).get("source_files", [])
    if not source_files:
        logger.error("No source_files listed in manifest.project.source_files")
        sys.exit(1)

    # Build a set of already-processed source paths so we can skip them
    # unless --force is given.
    existing_sources: set[str] = set()
    if not args.force:
        for clip in manifest.get("clips", []):
            existing_sources.add(clip.get("source_path", ""))

    # First pass: probe every file, collect intermediate records for sorting.
    scanned: list[dict] = []
    skipped_existing = 0
    skipped_error = 0

    for src_str in source_files:
        src_path = Path(src_str)

        if str(src_path) in existing_sources:
            logger.info("Skipping already-processed file: %s", src_path.name)
            skipped_existing += 1
            continue

        if not src_path.is_file():
            logger.warning("Source file not found, skipping: %s", src_path)
            skipped_error += 1
            continue

        probe = run_ffprobe(src_path)
        if probe is None:
            logger.warning("ffprobe failed for %s, skipping", src_path.name)
            skipped_error += 1
            continue

        video_stream = _find_video_stream(probe)
        if video_stream is None:
            logger.warning("No video stream found in %s, skipping", src_path.name)
            skipped_error += 1
            continue

        metadata = extract_metadata(probe, src_path)
        clip_type, confidence = classify_clip(metadata, src_path.name, probe)

        scanned.append({
            "source_path": str(src_path),
            "metadata": metadata,
            "clip_type": clip_type,
            "confidence": confidence,
        })

    # Sort by creation_time if available, else by filename.
    scanned.sort(key=_creation_time_sortkey)

    # Determine starting index: if clips already exist in manifest (non-force mode),
    # continue numbering from where we left off.
    existing_clips = manifest.get("clips", [])
    if args.force:
        # Wipe existing clips — we re-process everything.
        existing_clips = []
    next_index = len(existing_clips) + 1

    new_clips: list[dict] = []
    camera_count = 0
    screen_count = 0

    for entry in scanned:
        clip_id = f"clip_{next_index:03d}"
        src_path = Path(entry["source_path"])

        symlink_rel = create_symlink(project_root, src_path, clip_id)

        clip_entry = build_clip_entry(
            clip_id=clip_id,
            source_path=entry["source_path"],
            symlink_path=symlink_rel,
            clip_type=entry["clip_type"],
            confidence=entry["confidence"],
            metadata=entry["metadata"],
        )
        new_clips.append(clip_entry)

        if entry["clip_type"] == "camera":
            camera_count += 1
        else:
            screen_count += 1

        next_index += 1

    # Merge into manifest.
    manifest["clips"] = existing_clips + new_clips

    # Update pipeline_state.
    pipeline_state = manifest.setdefault("pipeline_state", {})
    total_clips = len(manifest["clips"])
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    phase_results = pipeline_state.setdefault("phase_results", {})
    phase_results["2"] = {
        "status": "success",
        "timestamp": now_iso,
        "clips_found": total_clips,
    }

    completed = pipeline_state.setdefault("completed_phases", [])
    if 2 not in completed:
        completed.append(2)
        completed.sort()

    pipeline_state["current_phase"] = max(pipeline_state.get("current_phase", 2), 2)
    pipeline_state["last_updated"] = now_iso

    save_manifest(project_root, manifest)

    total_new = len(new_clips)
    result = {
        "status": "success",
        "message": f"Scanned {total_new} files",
        "details": {
            "camera": camera_count,
            "screen_recording": screen_count,
        },
    }

    if skipped_existing > 0:
        result["details"]["skipped_existing"] = skipped_existing
    if skipped_error > 0:
        result["details"]["skipped_error"] = skipped_error

    print(json.dumps(result))


if __name__ == "__main__":
    main()
