#!/usr/bin/env python3
"""
Voice Activity Detection (VAD) and pitch contour analysis for the footage pipeline.

Uses Silero VAD (via torch.hub) for speech/silence segmentation and
librosa's pYIN algorithm for fundamental frequency (F0) extraction and
emphasis-point detection.

Usage:
    python3 run_vad_pitch.py <project_root> [--force]

Reads footage_manifest.json, processes each clip's denoised audio
(falls back to extracted audio), and writes results back to the manifest
plus detailed per-clip JSON files under analysis/vad/ and analysis/pitch/.

Exit codes:
    0 - Processing completed (even if some clips were skipped)
    1 - Fatal error (manifest missing, no clips, etc.)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Optional heavy imports -- guarded so the script can degrade gracefully.
# ---------------------------------------------------------------------------

_torch_available = False
try:
    import torch
    _torch_available = True
except ImportError:
    torch = None  # type: ignore[assignment]

_librosa_available = False
try:
    import librosa
    _librosa_available = True
except ImportError:
    librosa = None  # type: ignore[assignment]

# scipy.signal is needed for emphasis-point peak detection
_scipy_available = False
try:
    from scipy.signal import find_peaks
    _scipy_available = True
except ImportError:
    find_peaks = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLING_RATE = 16000
VAD_THRESHOLD = 0.5
VAD_MIN_SPEECH_MS = 250
VAD_MIN_SILENCE_MS = 100
VAD_DEFAULT_CONFIDENCE = 0.95

PITCH_FMIN_NOTE = "C2"
PITCH_FMAX_NOTE = "C7"
PITCH_HOP_LENGTH = 512

EMPHASIS_DERIVATIVE_THRESHOLD_FACTOR = 1.5
MAX_EMPHASIS_POINTS = 50

# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def load_manifest(project_root: Path) -> dict:
    """Load and return the footage manifest. Raises on failure."""
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(project_root: Path, manifest: dict) -> None:
    """Atomically-ish write the manifest back to disk."""
    manifest_path = project_root / "footage_manifest.json"
    tmp_path = manifest_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp_path.replace(manifest_path)


def resolve_audio_path(clip: dict, project_root: Path) -> Path | None:
    """
    Return the best available audio file path for a clip.

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


def clip_has_audio(clip: dict) -> bool:
    """Check whether the clip's metadata indicates it has audio."""
    metadata = clip.get("metadata", {})
    return metadata.get("has_audio", False)


# ---------------------------------------------------------------------------
# Part 1: VAD with Silero
# ---------------------------------------------------------------------------


def _load_silero_model():
    """
    Load Silero VAD model and return (model, utils_tuple).

    Raises ImportError if torch is not available, RuntimeError on load failure.
    """
    if not _torch_available or torch is None:
        raise ImportError("torch is not installed; cannot load Silero VAD")

    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        trust_repo=True,
    )
    return model, utils


def run_vad_for_clip(
    audio_path: Path,
    clip_id: str,
    model,
    utils: tuple,
) -> dict:
    """
    Run Silero VAD on a single clip's audio.

    Returns a dict matching the manifest ``vad`` schema.
    """
    get_speech_timestamps, _, read_audio, *_ = utils

    wav = read_audio(str(audio_path), sampling_rate=SAMPLING_RATE)
    total_duration = len(wav) / SAMPLING_RATE

    speech_timestamps = get_speech_timestamps(
        wav,
        model,
        threshold=VAD_THRESHOLD,
        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        sampling_rate=SAMPLING_RATE,
        return_seconds=True,
    )

    # Build speech segments
    speech_segments = []
    for ts in speech_timestamps:
        speech_segments.append({
            "start": round(float(ts["start"]), 4),
            "end": round(float(ts["end"]), 4),
            "confidence": VAD_DEFAULT_CONFIDENCE,
        })

    # Build silence segments (gaps between speech)
    silence_segments = []
    prev_end = 0.0
    for seg in speech_segments:
        if seg["start"] > prev_end + 1e-4:
            sil_start = round(prev_end, 4)
            sil_end = round(seg["start"], 4)
            silence_segments.append({
                "start": sil_start,
                "end": sil_end,
                "duration": round(sil_end - sil_start, 4),
            })
        prev_end = seg["end"]

    # Trailing silence
    if prev_end < total_duration - 1e-4:
        sil_start = round(prev_end, 4)
        sil_end = round(total_duration, 4)
        silence_segments.append({
            "start": sil_start,
            "end": sil_end,
            "duration": round(sil_end - sil_start, 4),
        })

    # Speech ratio
    total_speech = sum(s["end"] - s["start"] for s in speech_segments)
    speech_ratio = round(total_speech / total_duration, 4) if total_duration > 0 else 0.0

    relative_path = f"analysis/vad/{clip_id}.json"
    return {
        "path": relative_path,
        "engine": "silero",
        "speech_segments": speech_segments,
        "silence_segments": silence_segments,
        "speech_ratio": speech_ratio,
    }


# ---------------------------------------------------------------------------
# Part 2: Pitch analysis with librosa
# ---------------------------------------------------------------------------


def run_pitch_for_clip(audio_path: Path, clip_id: str) -> dict:
    """
    Extract pitch contour and emphasis points for a single clip.

    Returns a dict matching the manifest ``pitch`` schema.
    """
    if not _librosa_available or librosa is None:
        raise ImportError("librosa is not installed; cannot perform pitch analysis")

    y, sr = librosa.load(str(audio_path), sr=SAMPLING_RATE)

    f0, *_ = librosa.pyin(
        y,
        fmin=float(librosa.note_to_hz(PITCH_FMIN_NOTE)),
        fmax=float(librosa.note_to_hz(PITCH_FMAX_NOTE)),
        sr=sr,
        hop_length=PITCH_HOP_LENGTH,
    )

    # Filter out NaN (unvoiced frames) for statistics
    valid_mask = ~np.isnan(f0)
    valid_f0 = f0[valid_mask]

    if len(valid_f0) == 0:
        # Entirely unvoiced -- still write a result
        relative_path = f"analysis/pitch/{clip_id}.json"
        return {
            "path": relative_path,
            "mean_hz": 0.0,
            "std_hz": 0.0,
            "emphasis_points": [],
        }

    mean_hz = round(float(np.mean(valid_f0)), 2)
    std_hz = round(float(np.std(valid_f0)), 2)

    # Time axis: each frame is hop_length / sr seconds
    frame_duration = PITCH_HOP_LENGTH / sr
    times = np.arange(len(f0)) * frame_duration

    # Emphasis detection via first derivative of f0
    emphasis_points = _find_emphasis_points(f0, times)

    relative_path = f"analysis/pitch/{clip_id}.json"
    return {
        "path": relative_path,
        "mean_hz": mean_hz,
        "std_hz": std_hz,
        "emphasis_points": emphasis_points,
    }


def _find_emphasis_points(f0: np.ndarray, times: np.ndarray) -> list[dict]:
    """
    Detect significant pitch changes (emphasis points) from the F0 contour.

    Uses the first derivative of F0 to find rapid pitch changes, then
    classifies each as a rise, fall, or peak.

    Returns at most MAX_EMPHASIS_POINTS entries, sorted by magnitude descending.
    """
    # Replace NaN with 0 for derivative computation -- we will mask them out
    f0_filled = np.copy(f0)
    nan_mask = np.isnan(f0_filled)
    f0_filled[nan_mask] = 0.0

    # First derivative (rate of pitch change)
    df0 = np.gradient(f0_filled)
    # Zero out derivative at NaN boundaries to avoid artefacts
    df0[nan_mask] = 0.0
    # Also zero out frames adjacent to NaN (transition artefacts)
    nan_shifted_left = np.roll(nan_mask, -1)
    nan_shifted_right = np.roll(nan_mask, 1)
    df0[nan_shifted_left] = 0.0
    df0[nan_shifted_right] = 0.0

    abs_df0 = np.abs(df0)

    # Threshold: 1.5 * std of derivative (non-zero entries only)
    nonzero_abs = abs_df0[abs_df0 > 0]
    if len(nonzero_abs) == 0:
        return []
    threshold = EMPHASIS_DERIVATIVE_THRESHOLD_FACTOR * float(np.std(nonzero_abs))
    if threshold < 1e-6:
        return []

    # Find peaks in the absolute derivative
    if _scipy_available and find_peaks is not None:
        peak_indices, _properties = find_peaks(abs_df0, height=threshold, distance=3)
    else:
        # Fallback: simple threshold crossing without scipy
        peak_indices = np.where(abs_df0 > threshold)[0]

    if len(peak_indices) == 0:
        return []

    # Normalize magnitudes to 0-1 scale
    max_abs_df0 = float(np.max(abs_df0))
    if max_abs_df0 < 1e-9:
        return []

    emphasis_points = []
    for idx in peak_indices:
        # Skip if original f0 was NaN at this point
        if nan_mask[idx]:
            continue

        time_val = round(float(times[idx]), 4)
        magnitude = round(float(abs_df0[idx]) / max_abs_df0, 4)
        hz_val = round(float(f0_filled[idx]), 2)
        derivative_val = float(df0[idx])

        # Classify the emphasis type
        # Check if this is a local maximum in f0 (peak)
        is_peak = False
        if 1 <= idx <= len(f0_filled) - 2:
            if (f0_filled[idx] > f0_filled[idx - 1] and
                    f0_filled[idx] > f0_filled[idx + 1] and
                    not nan_mask[idx - 1] and not nan_mask[idx + 1]):
                is_peak = True

        if is_peak:
            emphasis_type = "peak"
        elif derivative_val > 0:
            emphasis_type = "rise"
        else:
            emphasis_type = "fall"

        emphasis_points.append({
            "time": time_val,
            "type": emphasis_type,
            "magnitude": magnitude,
            "hz": hz_val,
        })

    # Sort by magnitude descending and limit
    emphasis_points.sort(key=lambda p: p["magnitude"], reverse=True)
    emphasis_points = emphasis_points[:MAX_EMPHASIS_POINTS]

    # Re-sort by time for chronological output
    emphasis_points.sort(key=lambda p: p["time"])

    return emphasis_points


# ---------------------------------------------------------------------------
# Detailed JSON writers
# ---------------------------------------------------------------------------


def write_detail_json(project_root: Path, relative_path: str, data: dict) -> None:
    """Write a detailed analysis JSON file to the project tree."""
    out_path = project_root / relative_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(manifest: dict, vad_count: int, pitch_count: int, warnings: list[str]) -> None:
    """Update pipeline_state for phase 5 in the manifest."""
    now = datetime.now(timezone.utc).isoformat()
    ps = manifest.setdefault("pipeline_state", {})

    status = "success"
    if vad_count == 0 and pitch_count == 0:
        status = "skipped"

    phase_results = ps.setdefault("phase_results", {})
    phase_results["5"] = {
        "status": status,
        "timestamp": now,
        "vad_processed": vad_count,
        "pitch_processed": pitch_count,
    }

    if status == "success":
        completed = ps.setdefault("completed_phases", [])
        if 5 not in completed:
            completed.append(5)
        current = ps.get("current_phase", 0)
        if current < 5:
            ps["current_phase"] = 5

    existing_warnings = ps.setdefault("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)

    ps["last_updated"] = now


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------


def process(project_root: Path, force: bool) -> dict:
    """
    Run VAD and pitch analysis across all clips in the manifest.

    Returns a result dict suitable for JSON output.
    """
    manifest = load_manifest(project_root)
    clips = manifest.get("clips", [])

    if not clips:
        return {
            "status": "success",
            "message": "No clips in manifest, nothing to process",
            "details": {"vad_processed": 0, "pitch_processed": 0},
        }

    warnings: list[str] = []

    # --- Load Silero model once (if possible) ---
    silero_model = None
    silero_utils = None
    if _torch_available:
        try:
            silero_model, silero_utils = _load_silero_model()
        except Exception as exc:
            msg = f"Failed to load Silero VAD model: {exc}"
            print(msg, file=sys.stderr)
            warnings.append(msg)
    else:
        warnings.append("torch not available, VAD processing will be skipped")

    if not _librosa_available:
        warnings.append("librosa not available, pitch analysis will be skipped")

    vad_processed = 0
    pitch_processed = 0
    errors: list[str] = []

    for clip in clips:
        clip_id = clip.get("id", "unknown")

        if not clip_has_audio(clip):
            continue

        audio_path = resolve_audio_path(clip, project_root)
        if audio_path is None:
            msg = f"{clip_id}: no audio file found on disk, skipping"
            print(msg, file=sys.stderr)
            warnings.append(msg)
            continue

        # ----- VAD -----
        if silero_model is not None:
            already_done = clip.get("vad") is not None and not force
            if already_done:
                vad_path = project_root / clip["vad"].get("path", "")
                if not vad_path.is_file():
                    already_done = False

            if not already_done:
                try:
                    assert silero_utils is not None
                    vad_result = run_vad_for_clip(audio_path, clip_id, silero_model, silero_utils)
                    clip["vad"] = vad_result
                    write_detail_json(project_root, vad_result["path"], vad_result)
                    vad_processed += 1
                except Exception as exc:
                    msg = f"{clip_id}: VAD failed: {exc}"
                    print(msg, file=sys.stderr)
                    errors.append(msg)

        # ----- Pitch -----
        if _librosa_available:
            already_done = clip.get("pitch") is not None and not force
            if already_done:
                pitch_path = project_root / clip["pitch"].get("path", "")
                if not pitch_path.is_file():
                    already_done = False

            if not already_done:
                try:
                    pitch_result = run_pitch_for_clip(audio_path, clip_id)
                    clip["pitch"] = pitch_result
                    write_detail_json(project_root, pitch_result["path"], pitch_result)
                    pitch_processed += 1
                except Exception as exc:
                    msg = f"{clip_id}: Pitch analysis failed: {exc}"
                    print(msg, file=sys.stderr)
                    errors.append(msg)

    # Update pipeline state and save
    update_pipeline_state(manifest, vad_processed, pitch_processed, warnings)

    if errors:
        ps = manifest.setdefault("pipeline_state", {})
        existing_errors = ps.setdefault("errors", [])
        for e in errors:
            if e not in existing_errors:
                existing_errors.append(e)

    save_manifest(project_root, manifest)

    total = vad_processed + pitch_processed
    if errors and total == 0:
        status = "error"
        message = f"All processing failed. Errors: {len(errors)}"
    elif errors:
        status = "success"
        message = (
            f"Processed with warnings: VAD={vad_processed}, pitch={pitch_processed}, "
            f"errors={len(errors)}"
        )
    else:
        status = "success"
        message = f"VAD processed={vad_processed}, pitch processed={pitch_processed}"

    return {
        "status": status,
        "message": message,
        "details": {
            "vad_processed": vad_processed,
            "pitch_processed": pitch_processed,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Voice Activity Detection and pitch analysis on clip audio.",
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
        help="Re-process clips even if results already exist",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        output = {
            "status": "error",
            "message": f"Project root does not exist: {project_root}",
            "details": {"vad_processed": 0, "pitch_processed": 0},
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 1

    try:
        result = process(project_root, force=args.force)
    except FileNotFoundError as exc:
        result = {
            "status": "error",
            "message": str(exc),
            "details": {"vad_processed": 0, "pitch_processed": 0},
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "error",
            "message": f"Manifest JSON is malformed: {exc}",
            "details": {"vad_processed": 0, "pitch_processed": 0},
        }
    except Exception as exc:
        result = {
            "status": "error",
            "message": f"Unexpected error: {exc}",
            "details": {"vad_processed": 0, "pitch_processed": 0},
        }
        print(f"Unexpected error: {exc}", file=sys.stderr)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
