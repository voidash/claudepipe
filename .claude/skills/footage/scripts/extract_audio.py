#!/usr/bin/env python3
"""Extract audio from video clips and optionally apply noise removal via deepfilternet.

Usage:
    python3 extract_audio.py <project_root> [--force] [--sample-rate 16000] [--skip-denoise]
"""

import argparse
import importlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

# Attempt deepfilternet import at module level so we know early
_deepfilter_available = False
_df_enhance_module: ModuleType | None = None
try:
    _df_enhance_module = importlib.import_module("df.enhance")
    _deepfilter_available = True
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def read_manifest(project_root: Path) -> dict:
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        logger.error("Manifest not found at %s", manifest_path)
        sys.exit(1)
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_manifest(project_root: Path, manifest: dict) -> None:
    manifest_path = project_root / "footage_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


def probe_audio_info(audio_path: Path) -> dict:
    """Run ffprobe on a wav file and return duration_seconds and sample_rate."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        str(audio_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {audio_path}: {result.stderr.strip()}"
        )

    probe_data = json.loads(result.stdout)

    # Extract duration: prefer stream duration, fall back to format duration
    duration = None
    if probe_data.get("streams"):
        stream = probe_data["streams"][0]
        if stream.get("duration"):
            duration = float(stream["duration"])

    if duration is None and probe_data.get("format", {}).get("duration"):
        duration = float(probe_data["format"]["duration"])

    if duration is None:
        raise RuntimeError(
            f"Could not determine duration from ffprobe output for {audio_path}"
        )

    # Extract sample rate
    sample_rate = None
    if probe_data.get("streams"):
        stream = probe_data["streams"][0]
        if stream.get("sample_rate"):
            sample_rate = int(stream["sample_rate"])

    if sample_rate is None:
        raise RuntimeError(
            f"Could not determine sample_rate from ffprobe output for {audio_path}"
        )

    return {"duration_seconds": duration, "sample_rate": sample_rate}


def extract_audio_ffmpeg(
    source_path: Path,
    output_path: Path,
    sample_rate: int,
    duration_hint_seconds: float,
) -> None:
    """Extract mono 16-bit PCM audio from a video file using ffmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timeout = int(duration_hint_seconds * 2 + 30)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(source_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        str(output_path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio extraction failed for {source_path}: {result.stderr.strip()}"
        )


def denoise_audio(
    input_path: Path,
    output_path: Path,
) -> bool:
    """Apply deepfilternet noise removal. Returns True if denoising was applied."""
    if not _deepfilter_available or _df_enhance_module is None:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        _init_df = _df_enhance_module.init_df
        _load_audio = _df_enhance_module.load_audio
        _enhance = _df_enhance_module.enhance
        _save_audio = _df_enhance_module.save_audio

        model, df_state, _ = _init_df()
        audio, sr = _load_audio(str(input_path), sr=df_state.sr())
        enhanced = _enhance(model, df_state, audio)
        _save_audio(str(output_path), enhanced, sr=sr)
        return True
    except Exception:
        logger.exception("deepfilternet processing failed for %s", input_path)
        return False


def resolve_source_path(clip: dict, project_root: Path) -> Path:
    """Resolve the actual file path for a clip's source video."""
    # source_path is absolute per the schema
    source = Path(clip["source_path"])
    if source.exists():
        return source

    # Fall back to symlink_path (relative to project_root)
    symlink = project_root / clip["symlink_path"]
    if symlink.exists():
        return symlink

    raise FileNotFoundError(
        f"Cannot find source video for clip {clip['id']}: "
        f"tried {source} and {symlink}"
    )


def clip_already_processed(clip: dict, project_root: Path) -> bool:
    """Check if a clip's audio has already been extracted and files exist."""
    audio = clip.get("audio")
    if audio is None:
        return False
    if not isinstance(audio, dict):
        return False

    extracted = audio.get("extracted_path")
    if not extracted:
        return False

    extracted_full = project_root / extracted
    if not extracted_full.exists():
        return False

    denoised = audio.get("denoised_path")
    if denoised:
        denoised_full = project_root / denoised
        if not denoised_full.exists():
            return False

    return True


def process_clip(
    clip: dict,
    project_root: Path,
    sample_rate: int,
    skip_denoise: bool,
    force: bool,
    warnings: list,
) -> str:
    """Process a single clip. Returns 'extracted', 'skipped_processed', or 'skipped_no_audio'."""
    clip_id = clip["id"]
    metadata = clip.get("metadata", {})
    has_audio = metadata.get("has_audio", False)

    if not has_audio:
        clip["audio"] = None
        logger.info("Clip %s has no audio, skipping.", clip_id)
        return "skipped_no_audio"

    if not force and clip_already_processed(clip, project_root):
        logger.info("Clip %s already processed, skipping.", clip_id)
        return "skipped_processed"

    # Resolve source
    source_path = resolve_source_path(clip, project_root)
    video_duration = metadata.get("duration_seconds", 60.0)

    # Extract audio
    audio_dir = project_root / "audio"
    extracted_path = audio_dir / f"{clip_id}.wav"

    logger.info("Extracting audio for %s from %s", clip_id, source_path)
    extract_audio_ffmpeg(source_path, extracted_path, sample_rate, video_duration)

    # Verify extracted audio
    probe_info = probe_audio_info(extracted_path)
    actual_duration = probe_info["duration_seconds"]
    actual_sample_rate = probe_info["sample_rate"]

    if actual_sample_rate != sample_rate:
        msg = (
            f"Clip {clip_id}: extracted sample rate {actual_sample_rate} "
            f"differs from requested {sample_rate}"
        )
        logger.warning(msg)
        warnings.append(msg)

    duration_diff = abs(actual_duration - video_duration)
    if duration_diff > 1.0:
        msg = (
            f"Clip {clip_id}: extracted audio duration {actual_duration:.2f}s "
            f"differs from video duration {video_duration:.2f}s by {duration_diff:.2f}s"
        )
        logger.warning(msg)
        warnings.append(msg)

    # Noise removal
    denoised_dir = project_root / "audio" / "denoised"
    denoised_path = denoised_dir / f"{clip_id}.wav"
    noise_removal_applied = False
    noise_removal_engine = "none"

    if not skip_denoise:
        denoised_dir.mkdir(parents=True, exist_ok=True)

        if _deepfilter_available:
            logger.info("Applying deepfilternet denoising for %s", clip_id)
            denoised_ok = denoise_audio(extracted_path, denoised_path)
            if denoised_ok:
                noise_removal_applied = True
                noise_removal_engine = "deepfilternet"
            else:
                # Denoising failed at runtime; fall through to symlink
                msg = (
                    f"deepfilternet processing failed for {clip_id}, "
                    "using original audio"
                )
                logger.warning(msg)
                warnings.append(msg)

        if not noise_removal_applied:
            # deepfilternet not available or failed: symlink original
            if not _deepfilter_available:
                msg = (
                    f"deepfilternet not available, skipping noise removal "
                    f"for {clip_id}"
                )
                logger.warning(msg)
                # Only add the generic warning once
                generic_warning = "deepfilternet not available, skipping noise removal"
                if generic_warning not in warnings:
                    warnings.append(generic_warning)

            # Remove stale symlink/file if present
            if denoised_path.exists() or denoised_path.is_symlink():
                denoised_path.unlink()

            # Use relative symlink so the project directory is portable
            relative_target = os.path.relpath(extracted_path, denoised_path.parent)
            denoised_path.symlink_to(relative_target)
    else:
        # --skip-denoise: still create the denoised path as symlink for consistency
        denoised_dir.mkdir(parents=True, exist_ok=True)
        if denoised_path.exists() or denoised_path.is_symlink():
            denoised_path.unlink()
        relative_target = os.path.relpath(extracted_path, denoised_path.parent)
        denoised_path.symlink_to(relative_target)

    # Build audio metadata
    clip["audio"] = {
        "extracted_path": f"audio/{clip_id}.wav",
        "denoised_path": f"audio/denoised/{clip_id}.wav",
        "noise_removal_applied": noise_removal_applied,
        "noise_removal_engine": noise_removal_engine,
        "sample_rate": actual_sample_rate,
        "duration_seconds": round(actual_duration, 6),
    }

    return "extracted"


def update_pipeline_state(manifest: dict, warnings: list) -> None:
    """Mark phase 3 as complete in pipeline_state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if "pipeline_state" not in manifest:
        manifest["pipeline_state"] = {
            "current_phase": 3,
            "completed_phases": [],
            "phase_results": {},
            "errors": [],
            "warnings": [],
            "last_updated": now,
        }

    state = manifest["pipeline_state"]

    state["phase_results"]["3"] = {
        "status": "success",
        "timestamp": now,
    }

    if 3 not in state.get("completed_phases", []):
        state.setdefault("completed_phases", []).append(3)
        state["completed_phases"].sort()

    # Advance current_phase if it was at 3
    if state.get("current_phase", 0) <= 3:
        state["current_phase"] = 4

    # Merge warnings (avoid duplicates)
    existing_warnings = state.get("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)
    state["warnings"] = existing_warnings

    state["last_updated"] = now


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract audio from video clips and optionally denoise."
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Path to the project root directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract audio even if files already exist",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Target audio sample rate in Hz (default: 16000)",
    )
    parser.add_argument(
        "--skip-denoise",
        action="store_true",
        help="Skip the noise removal step entirely",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()

    if not project_root.is_dir():
        logger.error("Project root does not exist: %s", project_root)
        sys.exit(1)

    manifest = read_manifest(project_root)

    clips = manifest.get("clips", [])
    if not clips:
        logger.warning("No clips found in manifest.")

    warnings: list[str] = []
    extracted_count = 0
    denoised_count = 0
    skipped_no_audio_count = 0
    errors: list[str] = []

    for clip in clips:
        clip_id = clip.get("id", "unknown")
        try:
            result = process_clip(
                clip,
                project_root,
                args.sample_rate,
                args.skip_denoise,
                args.force,
                warnings,
            )
            if result == "extracted":
                extracted_count += 1
                audio_info = clip.get("audio", {})
                if audio_info and audio_info.get("noise_removal_applied"):
                    denoised_count += 1
            elif result == "skipped_no_audio":
                skipped_no_audio_count += 1
            # skipped_processed doesn't increment any counter
        except FileNotFoundError as exc:
            msg = f"Clip {clip_id}: {exc}"
            logger.error(msg)
            errors.append(msg)
        except RuntimeError as exc:
            msg = f"Clip {clip_id}: {exc}"
            logger.error(msg)
            errors.append(msg)
        except subprocess.TimeoutExpired:
            msg = f"Clip {clip_id}: ffmpeg/ffprobe timed out"
            logger.error(msg)
            errors.append(msg)

    if errors:
        # Store errors in pipeline state but don't fail the whole run
        # unless every clip errored
        if extracted_count == 0 and skipped_no_audio_count == 0:
            for err in errors:
                print(err, file=sys.stderr)
            output = {
                "status": "error",
                "message": f"All clips failed: {len(errors)} error(s)",
                "details": {
                    "extracted": 0,
                    "denoised": 0,
                    "skipped_no_audio": skipped_no_audio_count,
                    "errors": errors,
                },
            }
            print(json.dumps(output))
            sys.exit(1)
        else:
            for err in errors:
                warnings.append(err)

    update_pipeline_state(manifest, warnings)
    write_manifest(project_root, manifest)

    output = {
        "status": "success",
        "message": f"Extracted audio for {extracted_count} clips",
        "details": {
            "extracted": extracted_count,
            "denoised": denoised_count,
            "skipped_no_audio": skipped_no_audio_count,
        },
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
