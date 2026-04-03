#!/usr/bin/env python3
"""Generate background music using Google Lyria RealTime (via google-genai)
and create auto-ducking keyframes from VAD data.

Phase 15 of the footage pipeline.

Usage:
    python3 generate_music.py <project_root> [--force] [--dry-run] [--style "chill lo-fi"]

Reads the footage manifest, generates a background music track via the
Google GenAI audio generation API, and builds ducking keyframes from
per-clip VAD speech segments mapped onto the editorial timeline.

If music generation fails (missing credentials, unsupported model, etc.)
the script still produces ducking keyframes -- those are independently
valuable for mixing with any music source.

Exit codes:
    0 - Processing completed
    1 - Fatal error (manifest missing, timeline empty, etc.)
"""

import argparse
import base64
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional import: google-genai
# ---------------------------------------------------------------------------

_genai_available = False
try:
    from google import genai
    from google.genai import types

    _genai_available = True
except ImportError:
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MUSIC_OUTPUT_DIR = "music"
FFMPEG_CONVERT_TIMEOUT = 60

# Style auto-detection tag sets
_TECH_TAGS = {"demo", "code", "coding", "programming", "terminal", "ide", "screen_recording"}
_TALKING_HEAD_TAGS = {"talking_head", "interview", "monologue", "intro", "outro"}
_ACTION_TAGS = {"outdoor", "action", "travel", "drone", "b_roll", "adventure"}

# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest(project_root: Path) -> dict:
    """Load and return the footage manifest.  Raises on failure."""
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(project_root: Path, manifest: dict) -> None:
    """Atomically write the manifest back to disk."""
    manifest_path = project_root / "footage_manifest.json"
    tmp_path = manifest_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp_path.replace(manifest_path)


# ---------------------------------------------------------------------------
# Style config loader
# ---------------------------------------------------------------------------


def load_audio_config(project_root: Path) -> dict:
    """Load audio settings from style_config.json, falling back to defaults."""
    defaults = {
        "music_volume_db": -18.0,
        "music_duck_volume_db": -26.0,
        "music_duck_attack_seconds": 0.3,
        "music_duck_release_seconds": 0.8,
        "fade_in_seconds": 2.0,
        "fade_out_seconds": 3.0,
    }

    style_path = project_root / "style_config.json"
    if not style_path.is_file():
        logger.warning("style_config.json not found at %s, using built-in defaults", style_path)
        return defaults

    try:
        with style_path.open("r", encoding="utf-8") as fh:
            style = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read style_config.json (%s), using built-in defaults", exc)
        return defaults

    audio_section = style.get("audio", {})
    if not isinstance(audio_section, dict):
        logger.warning("style_config.json 'audio' key is not a dict, using built-in defaults")
        return defaults

    # Overlay file values on top of defaults so missing keys don't break us
    merged = dict(defaults)
    for key in defaults:
        if key in audio_section:
            val = audio_section[key]
            if isinstance(val, (int, float)):
                merged[key] = float(val)
            else:
                logger.warning(
                    "style_config.json audio.%s has non-numeric value %r, keeping default",
                    key,
                    val,
                )
    return merged


# ---------------------------------------------------------------------------
# Style auto-detection
# ---------------------------------------------------------------------------


def detect_style(manifest: dict) -> str:
    """Analyse manifest tags and clip types to suggest a music style prompt."""
    timeline = manifest.get("timeline", {})
    segments = timeline.get("segments", [])
    clips = manifest.get("clips", [])

    # Collect all tags from included timeline segments
    all_tags: set[str] = set()
    clip_types: dict[str, int] = {}

    for seg in segments:
        if not seg.get("include", True):
            continue
        tags = seg.get("tags", [])
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, str):
                    all_tags.add(t.lower())

    for clip in clips:
        ctype = clip.get("type", "unknown")
        clip_types[ctype] = clip_types.get(ctype, 0) + 1

    lower_tags = {t.lower() for t in all_tags}

    tech_overlap = lower_tags & _TECH_TAGS
    talking_overlap = lower_tags & _TALKING_HEAD_TAGS
    action_overlap = lower_tags & _ACTION_TAGS

    # Also treat screen_recording clip type as tech content
    screen_count = clip_types.get("screen_recording", 0)
    camera_count = clip_types.get("camera", 0)

    if tech_overlap or screen_count > camera_count:
        return "ambient electronic, minimal, subtle"
    if talking_overlap and len(talking_overlap) >= len(action_overlap):
        return "chill lo-fi hip hop, warm and unobtrusive"
    if action_overlap:
        return "upbeat acoustic, energetic but not overwhelming"
    return "modern cinematic background, versatile and subtle"


# ---------------------------------------------------------------------------
# Duration calculation
# ---------------------------------------------------------------------------


def calculate_required_duration(manifest: dict, audio_cfg: dict) -> float:
    """Return the total music duration needed (timeline + fade buffers)."""
    timeline = manifest.get("timeline", {})
    total = timeline.get("total_duration_seconds", 0.0)

    if total <= 0:
        # Fallback: sum durations of included segments
        for seg in timeline.get("segments", []):
            if seg.get("include", True):
                seg_dur = seg.get("duration")
                if seg_dur is None:
                    in_pt = seg.get("in_point", 0.0)
                    out_pt = seg.get("out_point", 0.0)
                    seg_dur = out_pt - in_pt
                total += max(0.0, seg_dur)

    if total <= 0:
        logger.warning("Timeline total duration is 0, returning 0")
        return 0.0

    fade_in = audio_cfg.get("fade_in_seconds", 2.0)
    fade_out = audio_cfg.get("fade_out_seconds", 3.0)
    return total + fade_in + fade_out


# ---------------------------------------------------------------------------
# Music generation via Google GenAI
# ---------------------------------------------------------------------------


def generate_music_audio(
    style_prompt: str,
    duration: float,
    hint: str,
    output_path: Path,
) -> bool:
    """Generate a background music WAV file using Google GenAI.

    Returns True if audio was successfully generated and saved, False otherwise.
    """
    if not _genai_available:
        logger.warning("google-genai not installed, skipping music generation")
        return False

    try:
        client = genai.Client()
    except Exception as exc:
        logger.error("Failed to create google-genai client (missing API key?): %s", exc)
        return False

    prompt = (
        f"Generate background music: {style_prompt}. Duration: {duration:.0f}s. "
        f"The music should be suitable for a YouTube video about {hint}. "
        f"It should loop cleanly and not compete with speech."
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            ),
        )
    except Exception as exc:
        logger.error("Google GenAI audio generation request failed: %s", exc)
        return False

    # Extract audio data from the response
    audio_data = None
    mime_type = None

    try:
        candidates = response.candidates
        if not candidates:
            logger.error("GenAI response contains no candidates")
            return False

        content = candidates[0].content
        if content is None or not content.parts:
            logger.error("GenAI response candidate has no content parts")
            return False

        for part in content.parts:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            part_mime = getattr(inline, "mime_type", "") or ""
            if part_mime.startswith("audio/"):
                audio_data = inline.data
                mime_type = part_mime
                break
    except (AttributeError, IndexError, TypeError) as exc:
        logger.error("Failed to parse GenAI audio response structure: %s", exc)
        return False

    if audio_data is None:
        logger.error("GenAI response contained no audio parts (model may not support audio output)")
        return False

    # If data is base64-encoded string, decode it
    if isinstance(audio_data, str):
        try:
            audio_data = base64.b64decode(audio_data)
        except Exception as exc:
            logger.error("Failed to base64-decode audio data: %s", exc)
            return False

    if not isinstance(audio_data, (bytes, bytearray)):
        logger.error("Unexpected audio data type: %s", type(audio_data).__name__)
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write raw audio to a temporary file, then convert to WAV via ffmpeg
    # to guarantee a consistent output format regardless of what the API returns.
    tmp_raw = output_path.with_suffix(_mime_to_extension(mime_type))

    try:
        tmp_raw.write_bytes(audio_data)
    except OSError as exc:
        logger.error("Failed to write raw audio to %s: %s", tmp_raw, exc)
        return False

    # If the API already returned WAV, just rename; otherwise convert.
    if mime_type == "audio/wav" or mime_type == "audio/x-wav":
        try:
            tmp_raw.rename(output_path)
        except OSError as exc:
            logger.error("Failed to rename %s -> %s: %s", tmp_raw, output_path, exc)
            return False
        return True

    success = _convert_to_wav(tmp_raw, output_path)

    # Clean up temp file
    try:
        if tmp_raw.exists():
            tmp_raw.unlink()
    except OSError:
        pass

    return success


def _mime_to_extension(mime_type: str) -> str:
    """Map an audio MIME type to a plausible file extension."""
    mapping = {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/flac": ".flac",
        "audio/aac": ".aac",
        "audio/mp4": ".m4a",
    }
    return mapping.get(mime_type, ".audio")


def _convert_to_wav(input_path: Path, output_path: Path) -> bool:
    """Convert an audio file to 16-bit PCM WAV using ffmpeg."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(input_path),
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FFMPEG_CONVERT_TIMEOUT,
        )
    except FileNotFoundError:
        logger.error("ffmpeg not found on PATH; cannot convert audio to WAV")
        return False
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out converting %s to WAV", input_path)
        return False

    if result.returncode != 0:
        logger.error("ffmpeg conversion failed: %s", result.stderr.strip())
        return False

    if not output_path.is_file() or output_path.stat().st_size == 0:
        logger.error("ffmpeg produced an empty or missing WAV file at %s", output_path)
        return False

    return True


# ---------------------------------------------------------------------------
# Ducking keyframes from VAD data
# ---------------------------------------------------------------------------


def build_ducking_keyframes(
    manifest: dict,
    audio_cfg: dict,
) -> list[dict]:
    """Build ducking keyframes from timeline segments and their clip VAD data.

    Maps each clip's speech segments to absolute timeline positions, then creates
    attack/release ramps around speech regions.

    Returns a sorted list of keyframe dicts.
    """
    timeline = manifest.get("timeline", {})
    segments = timeline.get("segments", [])
    order = timeline.get("order", [])
    clips_by_id = {c["id"]: c for c in manifest.get("clips", [])}

    vol_full = audio_cfg["music_volume_db"]
    vol_duck = audio_cfg["music_duck_volume_db"]
    attack = audio_cfg["music_duck_attack_seconds"]
    release = audio_cfg["music_duck_release_seconds"]

    # Build a segment lookup by id
    segments_by_id = {seg["id"]: seg for seg in segments}

    # Walk the timeline in order, accumulating absolute time offset
    absolute_offset = 0.0
    raw_keyframes: list[dict] = []

    ordered_segment_ids = order if order else [seg["id"] for seg in segments]

    for seg_id in ordered_segment_ids:
        seg = segments_by_id.get(seg_id)
        if seg is None:
            continue
        if not seg.get("include", True):
            continue

        clip_id = seg.get("clip_id")
        if clip_id is None:
            continue

        in_point = seg.get("in_point", 0.0)
        out_point = seg.get("out_point", 0.0)
        seg_duration = seg.get("duration")
        if seg_duration is None:
            seg_duration = out_point - in_point
        seg_duration = max(0.0, seg_duration)

        speed_factor = seg.get("speed_factor", 1.0)
        if speed_factor <= 0:
            speed_factor = 1.0

        clip = clips_by_id.get(clip_id)
        if clip is None:
            absolute_offset += seg_duration / speed_factor
            continue

        vad = clip.get("vad")
        if vad is None or not isinstance(vad, dict):
            absolute_offset += seg_duration / speed_factor
            continue

        speech_segments = vad.get("speech_segments", [])
        if not isinstance(speech_segments, list) or not speech_segments:
            absolute_offset += seg_duration / speed_factor
            continue

        # Map each speech segment within the clip's [in_point, out_point] window
        # to absolute timeline time, accounting for speed_factor.
        for sp in speech_segments:
            sp_start = sp.get("start")
            sp_end = sp.get("end")
            if sp_start is None or sp_end is None:
                continue

            # Clip the speech region to the segment window
            sp_start_clipped = max(sp_start, in_point)
            sp_end_clipped = min(sp_end, out_point)
            if sp_start_clipped >= sp_end_clipped:
                continue

            # Convert clip-local time to absolute timeline time
            # Offset within segment = (clip_time - in_point) / speed_factor
            abs_speech_start = absolute_offset + (sp_start_clipped - in_point) / speed_factor
            abs_speech_end = absolute_offset + (sp_end_clipped - in_point) / speed_factor

            # Attack: ramp down before speech starts
            attack_start = max(0.0, abs_speech_start - attack)
            raw_keyframes.append({
                "time": round(attack_start, 4),
                "volume_db": vol_duck,
                "reason": "speech_start",
            })

            # Release: ramp up after speech ends
            raw_keyframes.append({
                "time": round(abs_speech_end, 4),
                "volume_db": vol_full,
                "reason": "speech_end",
            })

        absolute_offset += seg_duration / speed_factor

    if not raw_keyframes:
        # No speech at all: single constant-volume keyframe
        return [{"time": 0.0, "volume_db": vol_full}]

    # Sort by time
    raw_keyframes.sort(key=lambda kf: kf["time"])

    # Merge keyframes that are very close together (< 0.1s)
    merged = _merge_close_keyframes(raw_keyframes, threshold=0.1)

    # Ensure timeline starts with a full-volume keyframe at t=0
    if not merged or merged[0]["time"] > 0.0:
        merged.insert(0, {"time": 0.0, "volume_db": vol_full})

    return merged


def _merge_close_keyframes(keyframes: list[dict], threshold: float) -> list[dict]:
    """Merge consecutive keyframes that are closer than *threshold* seconds.

    When two keyframes collide, keep the one that ducks lower (more conservative
    for speech protection).  Preserve the reason from whichever one survives.
    """
    if not keyframes:
        return []

    result: list[dict] = [keyframes[0]]
    for kf in keyframes[1:]:
        prev = result[-1]
        if kf["time"] - prev["time"] < threshold:
            # Keep the more-ducked (lower dB) keyframe
            if kf["volume_db"] < prev["volume_db"]:
                result[-1] = kf
            # else keep prev
        else:
            result.append(kf)

    return result


# ---------------------------------------------------------------------------
# Output: write manifest.music
# ---------------------------------------------------------------------------


def build_music_entry(
    track_id: str,
    style_prompt: str,
    generated_path: str | None,
    duration: float,
    ducking_keyframes: list[dict],
    audio_cfg: dict,
    generation_succeeded: bool,
) -> dict:
    """Build a single music track dict matching the manifest schema."""
    return {
        "id": track_id,
        "style_prompt": style_prompt,
        "generated_path": generated_path,
        "duration_seconds": round(duration, 4),
        "loop": True,
        "ducking_keyframes": ducking_keyframes,
        "placement": {
            "start_time": 0.0,
            "end_time": None,
            "fade_in_seconds": audio_cfg["fade_in_seconds"],
            "fade_out_seconds": audio_cfg["fade_out_seconds"],
        },
        "approved": False,
    }


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(
    manifest: dict,
    tracks_generated: int,
    ducking_keyframes_count: int,
    total_duration: float,
    warnings: list[str],
) -> None:
    """Mark phase 15 as complete in pipeline_state."""
    now = datetime.now(timezone.utc).isoformat()
    ps = manifest.setdefault("pipeline_state", {})

    status = "success"
    if tracks_generated == 0 and ducking_keyframes_count == 0:
        status = "skipped"

    phase_results = ps.setdefault("phase_results", {})
    phase_results["15"] = {
        "status": status,
        "timestamp": now,
        "tracks_generated": tracks_generated,
        "ducking_keyframes": ducking_keyframes_count,
        "total_duration": round(total_duration, 4),
    }

    completed = ps.setdefault("completed_phases", [])
    if status == "success" and 15 not in completed:
        completed.append(15)
        completed.sort()

    current = ps.get("current_phase", 0)
    if current < 15:
        ps["current_phase"] = 15

    existing_warnings = ps.setdefault("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)

    ps["last_updated"] = now


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def process(
    project_root: Path,
    force: bool,
    dry_run: bool,
    style_override: str | None,
) -> dict:
    """Run music generation and ducking keyframe creation.

    Returns a result dict suitable for JSON output.
    """
    manifest = load_manifest(project_root)
    audio_cfg = load_audio_config(project_root)
    warnings: list[str] = []

    # Check if music already exists
    existing_music = manifest.get("music", {})
    existing_tracks = existing_music.get("tracks", [])
    if existing_tracks and not force:
        # Check if generated files actually exist on disk
        all_exist = True
        for track in existing_tracks:
            gp = track.get("generated_path")
            if gp and not (project_root / gp).is_file():
                all_exist = False
                break
        if all_exist:
            return {
                "status": "success",
                "message": "Music already exists, use --force to regenerate",
                "details": {
                    "tracks_generated": 0,
                    "ducking_keyframes": sum(
                        len(t.get("ducking_keyframes", [])) for t in existing_tracks
                    ),
                    "total_duration": sum(
                        t.get("duration_seconds", 0) for t in existing_tracks
                    ),
                },
            }

    # Determine style
    if style_override:
        style_prompt = style_override
    else:
        style_prompt = detect_style(manifest)
    logger.info("Music style: %s", style_prompt)

    # Calculate duration
    duration = calculate_required_duration(manifest, audio_cfg)
    if duration <= 0:
        msg = "Timeline has zero duration; cannot determine music length"
        logger.warning(msg)
        warnings.append(msg)
        update_pipeline_state(manifest, 0, 0, 0.0, warnings)
        save_manifest(project_root, manifest)
        return {
            "status": "success",
            "message": msg,
            "details": {"tracks_generated": 0, "ducking_keyframes": 0, "total_duration": 0.0},
        }

    logger.info("Required music duration: %.1fs", duration)

    # Build ducking keyframes (always, regardless of dry_run or generation success)
    ducking_keyframes = build_ducking_keyframes(manifest, audio_cfg)
    logger.info("Built %d ducking keyframes", len(ducking_keyframes))

    # Get project hint for the generation prompt
    hint = manifest.get("project", {}).get("hint", "")
    if not hint:
        hint = "various topics"

    # Generate music
    track_id = "music_001"
    music_relative_path = f"{MUSIC_OUTPUT_DIR}/{track_id}.wav"
    music_absolute_path = project_root / music_relative_path
    generation_succeeded = False
    tracks_generated = 0

    if dry_run:
        logger.info("Dry run: skipping music generation")
        if not _genai_available:
            warnings.append("google-genai not installed; generation would fail in non-dry-run mode")
    else:
        (project_root / MUSIC_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        generation_succeeded = generate_music_audio(
            style_prompt=style_prompt,
            duration=duration,
            hint=hint,
            output_path=music_absolute_path,
        )
        if generation_succeeded:
            tracks_generated = 1
            logger.info("Music generated: %s", music_relative_path)
        else:
            warnings.append("Music generation failed; ducking keyframes were still created")
            logger.warning("Music generation failed, but ducking keyframes are available")

    # Build the track entry
    generated_path = music_relative_path if generation_succeeded else None
    track = build_music_entry(
        track_id=track_id,
        style_prompt=f"{style_prompt} background music, subtle and unobtrusive",
        generated_path=generated_path,
        duration=duration,
        ducking_keyframes=ducking_keyframes,
        audio_cfg=audio_cfg,
        generation_succeeded=generation_succeeded,
    )

    # Write to manifest.music
    manifest["music"] = {"tracks": [track]}

    # Update pipeline state and save
    update_pipeline_state(
        manifest,
        tracks_generated=tracks_generated,
        ducking_keyframes_count=len(ducking_keyframes),
        total_duration=duration,
        warnings=warnings,
    )
    save_manifest(project_root, manifest)

    return {
        "status": "success",
        "message": (
            f"Generated {tracks_generated} track(s), "
            f"{len(ducking_keyframes)} ducking keyframes, "
            f"duration={duration:.1f}s"
        ),
        "details": {
            "tracks_generated": tracks_generated,
            "ducking_keyframes": len(ducking_keyframes),
            "total_duration": round(duration, 4),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate background music and auto-ducking keyframes.",
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Root directory of the footage project",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Regenerate music even if it already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Only create ducking keyframes, skip actual music generation",
    )
    parser.add_argument(
        "--style",
        type=str,
        default=None,
        dest="style",
        help='Override music style (e.g. "chill lo-fi"). Default: auto-detect from content.',
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        output = {
            "status": "error",
            "message": f"Project root does not exist: {project_root}",
            "details": {"tracks_generated": 0, "ducking_keyframes": 0, "total_duration": 0.0},
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 1

    try:
        result = process(
            project_root,
            force=args.force,
            dry_run=args.dry_run,
            style_override=args.style,
        )
    except FileNotFoundError as exc:
        result = {
            "status": "error",
            "message": str(exc),
            "details": {"tracks_generated": 0, "ducking_keyframes": 0, "total_duration": 0.0},
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "error",
            "message": f"Manifest JSON is malformed: {exc}",
            "details": {"tracks_generated": 0, "ducking_keyframes": 0, "total_duration": 0.0},
        }
    except Exception as exc:
        result = {
            "status": "error",
            "message": f"Unexpected error: {exc}",
            "details": {"tracks_generated": 0, "ducking_keyframes": 0, "total_duration": 0.0},
        }
        print(f"Unexpected error: {exc}", file=sys.stderr)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
