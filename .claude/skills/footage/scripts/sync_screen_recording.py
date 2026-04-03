#!/usr/bin/env python3
"""Synchronize screen recordings with camera footage using audio cross-correlation.

Identifies screen recording clips in the manifest, finds the best-matching
camera clip for each by cross-correlating their audio, and writes sync
metadata (offset, correlation score, default layout) back to the manifest.

Phase 9 of the footage pipeline.

Usage:
    python3 sync_screen_recording.py <project_root> [--force]
"""

import argparse
import json
import logging
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# scipy is critical for this script -- guard the import and abort early
# if it is not available.
_scipy_available = False
try:
    from scipy.signal import fftconvolve, resample
    _scipy_available = True
except ImportError:
    fftconvolve = None  # type: ignore[assignment]
    resample = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INITIAL_SR = 8000       # Downsample rate for the fast initial search
REFINE_SR = 16000       # Higher rate for offset refinement
INITIAL_DURATION_S = 60 # Seconds of audio used for the initial search
MIN_AUDIO_DURATION_S = 1.0
MIN_CORRELATION_SCORE = 0.3

# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def load_manifest(project_root: Path) -> dict:
    """Load and return the footage manifest."""
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        logger.error("Manifest not found at %s", manifest_path)
        sys.exit(1)
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read manifest: %s", exc)
        sys.exit(1)


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
        logger.error("Failed to write manifest: %s", exc)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------------


def load_wav_as_numpy(path: Path, target_sr: int, max_duration_s: float | None = None) -> np.ndarray:
    """Load a WAV file as a float32 numpy array, optionally truncated and resampled.

    Parameters
    ----------
    path:
        Path to the WAV file.
    target_sr:
        Desired sample rate for the returned audio.
    max_duration_s:
        If not None, only load this many seconds of audio from the start
        of the file.

    Returns
    -------
    np.ndarray of float32, normalised to [-1, 1].
    """
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        total_frames = wf.getnframes()

        if max_duration_s is not None:
            frames_to_read = min(total_frames, int(sr * max_duration_s))
        else:
            frames_to_read = total_frames

        raw = wf.readframes(frames_to_read)

    # extract_audio.py produces 16-bit PCM (pcm_s16le), so int16 is correct.
    if len(raw) == 0:
        return np.array([], dtype=np.float32)

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    # If stereo (or more channels), take only the first channel
    if n_channels > 1:
        audio = audio[::n_channels]

    # Resample if the source rate differs from target
    if sr != target_sr and len(audio) > 0:
        assert resample is not None, "scipy.signal.resample required"
        n_samples = int(len(audio) * target_sr / sr)
        if n_samples == 0:
            return np.array([], dtype=np.float32)
        resampled = resample(audio, n_samples)
        audio = np.asarray(resampled, dtype=np.float32)

    return audio


# ---------------------------------------------------------------------------
# Audio path resolution
# ---------------------------------------------------------------------------


def resolve_audio_path(clip: dict, project_root: Path) -> Path | None:
    """Return the best available audio file path for a clip.

    Prefers denoised audio, falls back to extracted audio.
    Returns None if no audio is available.
    """
    audio = clip.get("audio")
    if audio is None:
        return None

    # Try denoised first
    denoised = audio.get("denoised_path")
    if denoised:
        candidate = project_root / denoised
        if candidate.is_file():
            return candidate

    # Fall back to extracted
    extracted = audio.get("extracted_path")
    if extracted:
        candidate = project_root / extracted
        if candidate.is_file():
            return candidate

    return None


# ---------------------------------------------------------------------------
# Cross-correlation sync
# ---------------------------------------------------------------------------


def find_sync_offset(audio_a: np.ndarray, audio_b: np.ndarray, sr: int) -> tuple[float, float]:
    """Find time offset between audio_a and audio_b using cross-correlation.

    Parameters
    ----------
    audio_a:
        Reference audio (camera clip), float32, normalised.
    audio_b:
        Audio to sync (screen recording), float32, normalised.
    sr:
        Sample rate of both arrays (must already be the same).

    Returns
    -------
    (offset_seconds, correlation_score)
        offset_seconds: positive means audio_b starts later than audio_a.
        correlation_score: normalised peak correlation in [0, 1].
    """
    # Normalise both to zero mean to reduce DC-offset bias
    a_mean = np.mean(audio_a)
    b_mean = np.mean(audio_b)
    a = audio_a - a_mean
    b = audio_b - b_mean

    assert fftconvolve is not None, "scipy.signal.fftconvolve required"
    correlation = fftconvolve(a, b[::-1], mode="full")

    peak_index = int(np.argmax(np.abs(correlation)))
    offset_samples = peak_index - len(b) + 1
    offset_seconds = offset_samples / sr

    # Normalised score: peak / geometric mean of energies
    energy_a = float(np.sum(a ** 2))
    energy_b = float(np.sum(b ** 2))
    denominator = np.sqrt(energy_a * energy_b) + 1e-10
    score = float(np.abs(correlation[peak_index]) / denominator)

    return offset_seconds, min(1.0, score)


def find_best_camera_match(
    screen_clip: dict,
    camera_clips: list[dict],
    project_root: Path,
) -> tuple[dict | None, float, float]:
    """Find the camera clip whose audio best matches the screen recording.

    Uses a two-pass strategy:
    1. Fast pass: first INITIAL_DURATION_S seconds at INITIAL_SR
    2. Refinement: full audio at REFINE_SR for the top candidate

    Returns
    -------
    (best_camera_clip, offset_seconds, correlation_score)
    Returns (None, 0.0, 0.0) if no suitable match is found.
    """
    screen_audio_path = resolve_audio_path(screen_clip, project_root)
    if screen_audio_path is None:
        logger.warning(
            "No audio file for screen recording %s, cannot sync",
            screen_clip["id"],
        )
        return None, 0.0, 0.0

    # Load screen recording audio for the fast initial search
    try:
        screen_audio_fast = load_wav_as_numpy(
            screen_audio_path, target_sr=INITIAL_SR, max_duration_s=INITIAL_DURATION_S,
        )
    except Exception as exc:
        logger.error("Failed to load audio for %s: %s", screen_clip["id"], exc)
        return None, 0.0, 0.0

    if len(screen_audio_fast) < INITIAL_SR * MIN_AUDIO_DURATION_S:
        logger.warning(
            "Screen recording %s audio too short (%.2f s), skipping",
            screen_clip["id"],
            len(screen_audio_fast) / INITIAL_SR if INITIAL_SR > 0 else 0,
        )
        return None, 0.0, 0.0

    # --- Pass 1: Fast initial search across all camera clips ---
    best_clip: dict | None = None
    best_score: float = 0.0
    best_offset: float = 0.0

    for cam_clip in camera_clips:
        cam_audio_path = resolve_audio_path(cam_clip, project_root)
        if cam_audio_path is None:
            logger.info(
                "Camera clip %s has no audio, skipping for sync comparison",
                cam_clip["id"],
            )
            continue

        try:
            cam_audio_fast = load_wav_as_numpy(
                cam_audio_path, target_sr=INITIAL_SR, max_duration_s=INITIAL_DURATION_S,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load audio for camera clip %s: %s", cam_clip["id"], exc,
            )
            continue

        if len(cam_audio_fast) < INITIAL_SR * MIN_AUDIO_DURATION_S:
            logger.info(
                "Camera clip %s audio too short for correlation, skipping",
                cam_clip["id"],
            )
            continue

        offset, score = find_sync_offset(cam_audio_fast, screen_audio_fast, INITIAL_SR)
        logger.info(
            "Initial pass: %s vs %s -> offset=%.3f s, score=%.4f",
            screen_clip["id"], cam_clip["id"], offset, score,
        )

        if score > best_score:
            best_score = score
            best_offset = offset
            best_clip = cam_clip

    if best_clip is None or best_score < MIN_CORRELATION_SCORE:
        logger.warning(
            "No camera match found for %s (best score: %.4f, threshold: %.2f)",
            screen_clip["id"], best_score, MIN_CORRELATION_SCORE,
        )
        return None, 0.0, best_score

    # --- Pass 2: Refine with full audio at higher sample rate ---
    logger.info(
        "Refining sync for %s against best candidate %s (initial score=%.4f)",
        screen_clip["id"], best_clip["id"], best_score,
    )

    try:
        screen_audio_full = load_wav_as_numpy(
            screen_audio_path, target_sr=REFINE_SR, max_duration_s=None,
        )
        cam_audio_path = resolve_audio_path(best_clip, project_root)
        if cam_audio_path is None:
            # Shouldn't happen since we already loaded it above, but be safe
            return best_clip, best_offset, best_score

        cam_audio_full = load_wav_as_numpy(
            cam_audio_path, target_sr=REFINE_SR, max_duration_s=None,
        )
    except Exception as exc:
        logger.warning(
            "Failed to load full audio for refinement: %s. Using initial estimate.",
            exc,
        )
        return best_clip, best_offset, best_score

    if (len(screen_audio_full) < REFINE_SR * MIN_AUDIO_DURATION_S or
            len(cam_audio_full) < REFINE_SR * MIN_AUDIO_DURATION_S):
        logger.warning("Audio too short for refinement, using initial estimate.")
        return best_clip, best_offset, best_score

    refined_offset, refined_score = find_sync_offset(
        cam_audio_full, screen_audio_full, REFINE_SR,
    )
    logger.info(
        "Refined: %s vs %s -> offset=%.3f s, score=%.4f",
        screen_clip["id"], best_clip["id"], refined_offset, refined_score,
    )

    # Use the refined result if its score is at least as good as the initial.
    # If the refinement score drops drastically, something is off -- fall back
    # to the initial estimate.
    if refined_score >= best_score * 0.5:
        return best_clip, refined_offset, refined_score

    logger.warning(
        "Refined score (%.4f) dropped significantly from initial (%.4f). "
        "Falling back to initial estimate.",
        refined_score, best_score,
    )
    return best_clip, best_offset, best_score


# ---------------------------------------------------------------------------
# Layout defaults
# ---------------------------------------------------------------------------


def determine_default_layout(manifest: dict) -> dict:
    """Determine the default screen recording layout based on output formats.

    Inspects the outputs section of the manifest to decide:
    - 9:16 targets -> default "split" (top/bottom)
    - 16:9 targets -> default "pip"
    Returns a dict with suggestions for both aspect ratios.
    """
    outputs = manifest.get("outputs", {})

    has_16_9 = "long_16_9" in outputs
    has_9_16 = "long_9_16" in outputs or bool(outputs.get("shorts"))

    # Default suggestion depends on what outputs exist
    if has_9_16 and not has_16_9:
        default_layout = "split"
    else:
        default_layout = "pip"

    return {
        "layout": default_layout,
        "layout_params": {
            "pip_position": "top_right",
            "pip_scale": 0.25,
            "switch_timestamps": [],
        },
        "layout_suggestions": {
            "16_9": {
                "layout": "pip",
                "pip_position": "top_right",
                "pip_scale": 0.25,
            },
            "9_16": {
                "layout": "split",
                "split_ratio": 0.5,
                "camera_position": "top",
            },
        },
    }


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------


def update_pipeline_state(
    manifest: dict,
    status: str,
    screen_recordings_found: int,
    synced: int,
    unmatched: int,
    warnings: list[str],
) -> None:
    """Update pipeline_state for phase 9."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ps = manifest.setdefault("pipeline_state", {})

    phase_results = ps.setdefault("phase_results", {})

    if status == "skipped":
        phase_results["9"] = {
            "status": "skipped",
            "reason": "no_screen_recordings",
            "timestamp": now,
        }
    else:
        phase_results["9"] = {
            "status": status,
            "timestamp": now,
            "screen_recordings_found": screen_recordings_found,
            "synced": synced,
            "unmatched": unmatched,
        }

    completed = ps.setdefault("completed_phases", [])
    if status in ("success", "skipped"):
        if 9 not in completed:
            completed.append(9)
            completed.sort()

    current = ps.get("current_phase", 0)
    if current < 9:
        ps["current_phase"] = 9

    # Merge warnings without duplicates
    existing_warnings = ps.setdefault("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)

    ps["last_updated"] = now


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def process(project_root: Path, force: bool) -> dict:
    """Run screen recording sync across all clips.

    Returns a result dict suitable for JSON output.
    """
    manifest = load_manifest(project_root)
    clips = manifest.get("clips", [])
    warnings: list[str] = []

    # Partition clips by type
    screen_recordings: list[dict] = []
    camera_clips: list[dict] = []

    for clip in clips:
        clip_type = clip.get("type", "")
        if clip_type == "screen_recording":
            screen_recordings.append(clip)
        elif clip_type == "camera":
            camera_clips.append(clip)

    # If no screen recordings, skip gracefully
    if not screen_recordings:
        logger.info("No screen recordings found in manifest, skipping phase 9.")
        update_pipeline_state(manifest, "skipped", 0, 0, 0, warnings)
        save_manifest(project_root, manifest)
        return {
            "status": "success",
            "message": "No screen recordings found, phase skipped",
            "details": {
                "screen_recordings_found": 0,
                "synced": 0,
                "unmatched": 0,
            },
        }

    if not camera_clips:
        msg = "Screen recordings found but no camera clips to sync against"
        logger.warning(msg)
        warnings.append(msg)
        update_pipeline_state(
            manifest, "success",
            screen_recordings_found=len(screen_recordings),
            synced=0,
            unmatched=len(screen_recordings),
            warnings=warnings,
        )
        save_manifest(project_root, manifest)
        return {
            "status": "success",
            "message": msg,
            "details": {
                "screen_recordings_found": len(screen_recordings),
                "synced": 0,
                "unmatched": len(screen_recordings),
            },
        }

    layout_defaults = determine_default_layout(manifest)
    synced_count = 0
    unmatched_count = 0

    for sr_clip in screen_recordings:
        clip_id = sr_clip["id"]

        # Skip if already synced (unless --force)
        if not force and sr_clip.get("screen_sync") is not None:
            existing_sync = sr_clip["screen_sync"]
            if existing_sync.get("synced_to_clip"):
                logger.info(
                    "Clip %s already synced to %s, skipping (use --force to re-sync)",
                    clip_id, existing_sync["synced_to_clip"],
                )
                synced_count += 1
                continue

        # Check that the screen recording has audio
        has_audio = sr_clip.get("metadata", {}).get("has_audio", False)
        if not has_audio:
            msg = f"Screen recording {clip_id} has no audio, cannot sync"
            logger.warning(msg)
            warnings.append(msg)
            sr_clip["screen_sync"] = {
                "synced_to_clip": None,
                "offset_seconds": 0.0,
                "correlation_score": 0.0,
                "error": "no_audio",
                "layout": layout_defaults["layout"],
                "layout_params": layout_defaults["layout_params"],
                "layout_suggestions": layout_defaults["layout_suggestions"],
            }
            unmatched_count += 1
            continue

        logger.info("Syncing screen recording %s against %d camera clips...",
                     clip_id, len(camera_clips))

        best_cam, offset, score = find_best_camera_match(
            sr_clip, camera_clips, project_root,
        )

        if best_cam is None or score < MIN_CORRELATION_SCORE:
            msg = (
                f"Screen recording {clip_id}: no match found "
                f"(best score: {score:.4f}, threshold: {MIN_CORRELATION_SCORE})"
            )
            logger.warning(msg)
            warnings.append(msg)
            sr_clip["screen_sync"] = {
                "synced_to_clip": None,
                "offset_seconds": 0.0,
                "correlation_score": round(score, 4),
                "error": "no_match_found",
                "layout": layout_defaults["layout"],
                "layout_params": layout_defaults["layout_params"],
                "layout_suggestions": layout_defaults["layout_suggestions"],
            }
            unmatched_count += 1
        else:
            logger.info(
                "Matched %s -> %s (offset=%.3f s, score=%.4f)",
                clip_id, best_cam["id"], offset, score,
            )
            sr_clip["screen_sync"] = {
                "synced_to_clip": best_cam["id"],
                "offset_seconds": round(offset, 3),
                "correlation_score": round(score, 4),
                "layout": layout_defaults["layout"],
                "layout_params": layout_defaults["layout_params"],
                "layout_suggestions": layout_defaults["layout_suggestions"],
            }
            synced_count += 1

    status = "success"
    update_pipeline_state(
        manifest, status,
        screen_recordings_found=len(screen_recordings),
        synced=synced_count,
        unmatched=unmatched_count,
        warnings=warnings,
    )
    save_manifest(project_root, manifest)

    message = (
        f"Processed {len(screen_recordings)} screen recording(s): "
        f"{synced_count} synced, {unmatched_count} unmatched"
    )

    return {
        "status": status,
        "message": message,
        "details": {
            "screen_recordings_found": len(screen_recordings),
            "synced": synced_count,
            "unmatched": unmatched_count,
        },
    }


def main() -> int:
    if not _scipy_available:
        error_result = {
            "status": "error",
            "message": (
                "scipy is required for audio cross-correlation but is not installed. "
                "Install it with: pip install scipy"
            ),
            "details": {
                "screen_recordings_found": 0,
                "synced": 0,
                "unmatched": 0,
            },
        }
        print(json.dumps(error_result))
        return 1

    parser = argparse.ArgumentParser(
        description="Synchronize screen recordings with camera footage using audio cross-correlation.",
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
        help="Re-sync screen recordings even if sync data already exists",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        error_result = {
            "status": "error",
            "message": f"Project root does not exist: {project_root}",
            "details": {
                "screen_recordings_found": 0,
                "synced": 0,
                "unmatched": 0,
            },
        }
        print(json.dumps(error_result))
        return 1

    try:
        result = process(project_root, force=args.force)
    except FileNotFoundError as exc:
        result = {
            "status": "error",
            "message": str(exc),
            "details": {"screen_recordings_found": 0, "synced": 0, "unmatched": 0},
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "error",
            "message": f"Manifest JSON is malformed: {exc}",
            "details": {"screen_recordings_found": 0, "synced": 0, "unmatched": 0},
        }
    except Exception as exc:
        result = {
            "status": "error",
            "message": f"Unexpected error: {exc}",
            "details": {"screen_recordings_found": 0, "synced": 0, "unmatched": 0},
        }
        logger.exception("Unexpected error during screen recording sync")

    print(json.dumps(result))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
