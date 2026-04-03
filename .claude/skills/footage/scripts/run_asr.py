#!/usr/bin/env python3
"""
Automatic Speech Recognition for the footage pipeline.

Transcribes extracted audio clips using a multi-engine fallback chain
optimized for Nepali + English code-switching:

    1. Google Chirp 2  (best WER for ne-EN, requires google.cloud.speech)
    2. Google Gemini   (good Nepali support, uses google.genai)
    3. OpenAI Whisper   (last resort, poor Nepali WER)

Phase 4 of the footage pipeline.

Usage:
    python3 run_asr.py <project_root> [--force] [--engine auto|gemini|chirp2|whisper]

Exit codes:
    0 - Processing completed (even if some clips were skipped)
    1 - Fatal error (manifest missing, no clips, etc.)
"""

import argparse
import json
import math
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional engine imports -- guarded so the script degrades gracefully.
# ---------------------------------------------------------------------------

_genai_available = False
try:
    from google import genai
    from google.genai import types as genai_types

    _genai_available = True
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

_chirp2_available = False
try:
    from google.cloud import speech as cloud_speech

    _chirp2_available = True
except ImportError:
    cloud_speech = None  # type: ignore[assignment]

_whisper_available = False
try:
    import whisper as openai_whisper

    _whisper_available = True
except ImportError:
    openai_whisper = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEMINI_MODEL = "gemini-2.0-flash"
CHIRP2_SAMPLE_RATE = 16000
WHISPER_MODEL_SIZE = "large-v3"

# Audio chunking: Gemini file size limit.
# Files above this threshold (bytes) are split before upload.
CHUNK_SIZE_THRESHOLD = 20 * 1024 * 1024  # 20 MB
CHUNK_DURATION_SECONDS = 600  # 10 minutes per chunk

# Retry configuration for transient API errors.
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds
RETRYABLE_STATUS_CODES = {429, 503}

# Minimum file size to consider an audio file non-empty.
MIN_AUDIO_FILE_BYTES = 100

# Engine priority order for --engine auto.
ENGINE_PRIORITY = ["chirp2", "gemini", "whisper"]

# Gemini prompt for transcription.
GEMINI_TRANSCRIPTION_PROMPT = (
    "Transcribe this audio with word-level timestamps. The speaker uses Nepali and English code-switching. "
    'Return JSON with format: {"segments": [{"start": 0.0, "end": 2.5, "text": "...", "language": "ne"|"en", '
    '"words": [{"word": "...", "start": 0.0, "end": 0.3}]}]}. '
    "Segment by natural pauses/sentences. Detect language per segment."
)


# ---------------------------------------------------------------------------
# Manifest helpers (consistent with other pipeline scripts)
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
# JSON parsing utilities
# ---------------------------------------------------------------------------


def extract_json_from_response(text: str) -> dict | None:
    """
    Parse JSON from a Gemini response.

    Gemini may return:
    - Raw JSON
    - JSON wrapped in markdown code blocks (```json ... ``` or ``` ... ```)

    Returns the parsed dict, or None if parsing fails.
    """
    text = text.strip()

    # Attempt 1: direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: extract from markdown code blocks
    # Match ```json\n...\n``` or ```\n...\n```
    code_block_pattern = re.compile(
        r"```(?:json)?\s*\n?(.*?)\n?\s*```",
        re.DOTALL,
    )
    match = code_block_pattern.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Attempt 3: find first { ... } or [ ... ] block in the text
    # This handles cases where Gemini adds explanatory text around the JSON.
    brace_start = text.find("{")
    if brace_start != -1:
        # Find matching closing brace by counting depth
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break

    return None


def validate_transcript_segments(segments: list) -> list[dict]:
    """
    Validate and normalize transcript segments from any engine.

    Ensures each segment has the required fields with correct types.
    Drops segments that cannot be fixed.
    """
    validated = []
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            print(
                f"  Warning: segment {idx} is not a dict, skipping",
                file=sys.stderr,
            )
            continue

        text = seg.get("text")
        if not text or not isinstance(text, str) or not text.strip():
            continue

        start = seg.get("start")
        end = seg.get("end")

        # Coerce to float
        try:
            start = float(start) if start is not None else 0.0
        except (ValueError, TypeError):
            start = 0.0
        try:
            end = float(end) if end is not None else start
        except (ValueError, TypeError):
            end = start

        if end < start:
            end = start

        language = seg.get("language", "ne")
        if language not in ("ne", "en"):
            language = "ne"

        confidence = seg.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (ValueError, TypeError):
            confidence = None

        # Validate words
        raw_words = seg.get("words", [])
        words = []
        if isinstance(raw_words, list):
            for w in raw_words:
                if not isinstance(w, dict):
                    continue
                word_text = w.get("word")
                if not word_text or not isinstance(word_text, str):
                    continue
                w_start = w.get("start")
                w_end = w.get("end")
                try:
                    w_start = float(w_start) if w_start is not None else None
                except (ValueError, TypeError):
                    w_start = None
                try:
                    w_end = float(w_end) if w_end is not None else None
                except (ValueError, TypeError):
                    w_end = None

                word_entry: dict = {"word": word_text.strip()}
                if w_start is not None:
                    word_entry["start"] = round(w_start, 4)
                if w_end is not None:
                    word_entry["end"] = round(w_end, 4)
                w_conf = w.get("confidence")
                if w_conf is not None:
                    try:
                        word_entry["confidence"] = round(float(w_conf), 4)
                    except (ValueError, TypeError):
                        pass
                words.append(word_entry)

        segment_id = f"tseg_{idx + 1:03d}"
        entry: dict = {
            "id": segment_id,
            "start": round(start, 4),
            "end": round(end, 4),
            "text": text.strip(),
            "language": language,
        }
        if confidence is not None:
            entry["confidence"] = round(confidence, 4)
        if words:
            entry["words"] = words

        validated.append(entry)

    return validated


# ---------------------------------------------------------------------------
# Audio chunking for large files
# ---------------------------------------------------------------------------


def get_audio_duration(audio_path: Path) -> float | None:
    """Get audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "format=duration",
        "-of", "json",
        str(audio_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        probe_data = json.loads(result.stdout)
        duration_str = probe_data.get("format", {}).get("duration")
        if duration_str is not None:
            return float(duration_str)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError):
        pass
    return None


def split_audio_into_chunks(
    audio_path: Path,
    tmp_dir: Path,
    chunk_duration: int = CHUNK_DURATION_SECONDS,
) -> list[tuple[Path, float]]:
    """
    Split an audio file into chunks of approximately chunk_duration seconds.

    Returns a list of (chunk_path, offset_seconds) tuples.
    The offset is the start time of each chunk within the original file.
    """
    total_duration = get_audio_duration(audio_path)
    if total_duration is None:
        raise RuntimeError(f"Cannot determine duration for {audio_path}")

    if total_duration <= 0:
        return []

    tmp_dir.mkdir(parents=True, exist_ok=True)
    stem = audio_path.stem

    chunks = []
    offset = 0.0
    chunk_idx = 0

    while offset < total_duration:
        remaining = total_duration - offset
        this_chunk_dur = min(chunk_duration, remaining)
        if this_chunk_dur < 0.5:
            # Skip tiny leftover
            break

        chunk_path = tmp_dir / f"{stem}_chunk_{chunk_idx:03d}.wav"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(audio_path),
            "-ss", str(offset),
            "-t", str(this_chunk_dur),
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(chunk_path),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(this_chunk_dur * 2 + 60),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg chunk split failed for {audio_path} at offset {offset}: "
                f"{result.stderr.strip()}"
            )

        if chunk_path.is_file() and chunk_path.stat().st_size > MIN_AUDIO_FILE_BYTES:
            chunks.append((chunk_path, offset))
        else:
            print(
                f"  Warning: chunk {chunk_idx} at offset {offset} is empty, skipping",
                file=sys.stderr,
            )

        offset += this_chunk_dur
        chunk_idx += 1

    return chunks


def offset_segments(segments: list[dict], offset: float) -> list[dict]:
    """Add a time offset to all timestamps in a list of segments."""
    adjusted = []
    for seg in segments:
        seg_copy = dict(seg)
        seg_copy["start"] = round(seg_copy.get("start", 0.0) + offset, 4)
        seg_copy["end"] = round(seg_copy.get("end", 0.0) + offset, 4)

        # Offset word timestamps too
        if "words" in seg_copy and isinstance(seg_copy["words"], list):
            new_words = []
            for w in seg_copy["words"]:
                w_copy = dict(w)
                if "start" in w_copy and w_copy["start"] is not None:
                    w_copy["start"] = round(w_copy["start"] + offset, 4)
                if "end" in w_copy and w_copy["end"] is not None:
                    w_copy["end"] = round(w_copy["end"] + offset, 4)
                new_words.append(w_copy)
            seg_copy["words"] = new_words

        adjusted.append(seg_copy)
    return adjusted


# ---------------------------------------------------------------------------
# Engine: Gemini
# ---------------------------------------------------------------------------


def _is_retryable_error(exc: Exception) -> bool:
    """Check whether an exception represents a transient/retryable API error."""
    exc_str = str(exc)
    # Check for HTTP status codes in exception message
    for code in RETRYABLE_STATUS_CODES:
        if str(code) in exc_str:
            return True
    # Check for common transient error phrases
    retryable_phrases = [
        "resource exhausted",
        "rate limit",
        "too many requests",
        "service unavailable",
        "deadline exceeded",
        "temporarily unavailable",
        "internal error",
        "503",
        "429",
    ]
    exc_lower = exc_str.lower()
    for phrase in retryable_phrases:
        if phrase in exc_lower:
            return True
    return False


def _call_gemini_with_retry(client, audio_file_uri: str, mime_type: str) -> str:  # type: ignore[no-untyped-def]
    """
    Call Gemini API with exponential backoff retry on transient errors.

    Returns the response text.
    Raises the last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    genai_types.Part.from_uri(  # type: ignore[union-attr]
                        file_uri=audio_file_uri,
                        mime_type=mime_type,
                    ),
                    GEMINI_TRANSCRIPTION_PROMPT,
                ],
                config=genai_types.GenerateContentConfig(  # type: ignore[union-attr]
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            return response.text
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES and _is_retryable_error(exc):
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(
                    f"  Retryable error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {exc}. "
                    f"Retrying in {delay:.1f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
            else:
                raise

    # Should not reach here, but just in case
    assert last_exc is not None
    raise last_exc


def transcribe_with_gemini_single(client, audio_path: Path) -> list[dict]:
    """
    Transcribe a single audio file (not chunked) using Gemini.

    Returns a list of raw segment dicts from the Gemini response.
    """
    # Determine mime type
    suffix = audio_path.suffix.lower()
    mime_map = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
    }
    mime_type = mime_map.get(suffix, "audio/wav")

    # Upload the file
    uploaded_file = client.files.upload(file=audio_path)
    try:
        response_text = _call_gemini_with_retry(
            client, uploaded_file.uri, mime_type,
        )

        parsed = extract_json_from_response(response_text)
        if parsed is None:
            print(
                f"  Warning: Gemini returned non-JSON response for {audio_path.name}: "
                f"{response_text[:200]}",
                file=sys.stderr,
            )
            return []

        segments = parsed.get("segments", [])
        if not isinstance(segments, list):
            print(
                f"  Warning: Gemini response 'segments' is not a list for {audio_path.name}",
                file=sys.stderr,
            )
            return []

        return segments
    finally:
        # Clean up uploaded file
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception as cleanup_exc:
            print(
                f"  Warning: failed to delete uploaded Gemini file {uploaded_file.name}: {cleanup_exc}",
                file=sys.stderr,
            )


def transcribe_with_gemini(audio_path: Path, clip_id: str, project_root: Path) -> dict:
    """
    Transcribe audio using Google Gemini, with chunking for large files.

    Returns a transcript result dict for the manifest.
    """
    if not _genai_available or genai is None:
        raise ImportError("google.genai is not installed")

    client = genai.Client()
    file_size = audio_path.stat().st_size
    all_segments: list[dict] = []

    if file_size > CHUNK_SIZE_THRESHOLD:
        # Split into chunks
        tmp_dir = project_root / "tmp" / f"asr_chunks_{clip_id}"
        try:
            chunks = split_audio_into_chunks(audio_path, tmp_dir)
            if not chunks:
                print(
                    f"  Warning: chunking produced no valid chunks for {clip_id}",
                    file=sys.stderr,
                )
                return _build_transcript_result(clip_id, "gemini", [])

            for chunk_path, chunk_offset in chunks:
                print(
                    f"  Processing chunk at offset {chunk_offset:.1f}s: {chunk_path.name}",
                    file=sys.stderr,
                )
                chunk_segments = transcribe_with_gemini_single(client, chunk_path)
                adjusted = offset_segments(chunk_segments, chunk_offset)
                all_segments.extend(adjusted)
        finally:
            # Clean up chunk files
            if tmp_dir.is_dir():
                for f in tmp_dir.iterdir():
                    try:
                        f.unlink()
                    except OSError:
                        pass
                try:
                    tmp_dir.rmdir()
                except OSError:
                    pass
    else:
        all_segments = transcribe_with_gemini_single(client, audio_path)

    validated = validate_transcript_segments(all_segments)
    return _build_transcript_result(clip_id, "gemini", validated)


# ---------------------------------------------------------------------------
# Engine: Chirp 2
# ---------------------------------------------------------------------------


def transcribe_with_chirp2(audio_path: Path, clip_id: str) -> dict:
    """
    Transcribe audio using Google Cloud Speech Chirp 2.

    Returns a transcript result dict for the manifest.
    """
    if not _chirp2_available or cloud_speech is None:
        raise ImportError("google.cloud.speech is not installed")

    client = cloud_speech.SpeechClient()

    with audio_path.open("rb") as fh:
        audio_content = fh.read()

    config = cloud_speech.RecognitionConfig(
        explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
            encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=CHIRP2_SAMPLE_RATE,
            audio_channel_count=1,
        ),
        language_codes=["ne-NP", "en-US"],
        model="chirp_2",
        features=cloud_speech.RecognitionFeatures(
            enable_word_time_offsets=True,
            enable_automatic_punctuation=True,
        ),
    )

    audio_obj = cloud_speech.RecognitionAudio(content=audio_content)

    # Use recognize for short audio, long_running_recognize for longer files.
    # The sync API limit is ~1 minute; for longer files we need async.
    audio_duration = get_audio_duration(audio_path)
    segments: list[dict] = []

    if audio_duration is not None and audio_duration > 55:
        # Use long-running (async) recognition
        request = cloud_speech.LongRunningRecognizeRequest(
            config=config,
            audio=audio_obj,
        )
        operation = client.long_running_recognize(request=request)
        response = operation.result(timeout=600)
    else:
        request = cloud_speech.RecognizeRequest(
            config=config,
            audio=audio_obj,
        )
        response = client.recognize(request=request)

    for result in response.results:
        if not result.alternatives:
            continue
        alt = result.alternatives[0]
        text = alt.transcript
        if not text or not text.strip():
            continue

        words = []
        seg_start = None
        seg_end = None

        for word_info in alt.words:
            w_start = word_info.start_offset.total_seconds()
            w_end = word_info.end_offset.total_seconds()

            if seg_start is None or w_start < seg_start:
                seg_start = w_start
            if seg_end is None or w_end > seg_end:
                seg_end = w_end

            words.append({
                "word": word_info.word,
                "start": round(w_start, 4),
                "end": round(w_end, 4),
            })

        segment = {
            "start": round(seg_start, 4) if seg_start is not None else 0.0,
            "end": round(seg_end, 4) if seg_end is not None else 0.0,
            "text": text.strip(),
            "language": "ne",  # Chirp 2 doesn't reliably report per-segment language
            "confidence": round(alt.confidence, 4) if alt.confidence else None,
            "words": words,
        }
        segments.append(segment)

    validated = validate_transcript_segments(segments)
    return _build_transcript_result(clip_id, "chirp2", validated)


# ---------------------------------------------------------------------------
# Engine: Whisper
# ---------------------------------------------------------------------------


def transcribe_with_whisper(audio_path: Path, clip_id: str) -> dict:
    """
    Transcribe audio using OpenAI Whisper (local model).

    Returns a transcript result dict for the manifest.
    """
    if not _whisper_available or openai_whisper is None:
        raise ImportError("openai-whisper is not installed")

    model = openai_whisper.load_model(WHISPER_MODEL_SIZE)
    result = model.transcribe(
        str(audio_path),
        language=None,  # auto-detect
        word_timestamps=True,
    )

    segments: list[dict] = []
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue

        words = []
        if "words" in seg:
            for w in seg["words"]:
                word_entry: dict = {"word": w.get("word", "").strip()}
                if "start" in w:
                    word_entry["start"] = round(float(w["start"]), 4)
                if "end" in w:
                    word_entry["end"] = round(float(w["end"]), 4)
                if "probability" in w:
                    word_entry["confidence"] = round(float(w["probability"]), 4)
                if word_entry["word"]:
                    words.append(word_entry)

        # Whisper's language detection is per-file, not per-segment.
        detected_lang = result.get("language", "ne")
        language = "en" if detected_lang == "en" else "ne"

        segment = {
            "start": round(float(seg.get("start", 0.0)), 4),
            "end": round(float(seg.get("end", 0.0)), 4),
            "text": text,
            "language": language,
            "words": words,
        }
        if "avg_logprob" in seg:
            # Convert log probability to a 0-1 confidence approximation
            segment["confidence"] = round(math.exp(seg["avg_logprob"]), 4)

        segments.append(segment)

    validated = validate_transcript_segments(segments)
    return _build_transcript_result(clip_id, "whisper", validated)


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------


def _build_transcript_result(
    clip_id: str,
    engine: str,
    segments: list[dict],
) -> dict:
    """Build the transcript result dict for the manifest and detail JSON."""
    relative_path = f"analysis/transcripts/{clip_id}.json"
    return {
        "path": relative_path,
        "engine": engine,
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# Engine selection and dispatch
# ---------------------------------------------------------------------------


def get_available_engines() -> list[str]:
    """Return a list of engine names that are currently available."""
    available = []
    if _chirp2_available:
        available.append("chirp2")
    if _genai_available:
        available.append("gemini")
    if _whisper_available:
        available.append("whisper")
    return available


def select_engine(requested: str) -> str | None:
    """
    Select the best available engine based on the request.

    For 'auto', tries engines in priority order.
    For a specific engine name, checks availability.

    Returns the engine name, or None if no engine is available.
    """
    if requested == "auto":
        for engine in ENGINE_PRIORITY:
            if engine == "chirp2" and _chirp2_available:
                return "chirp2"
            if engine == "gemini" and _genai_available:
                return "gemini"
            if engine == "whisper" and _whisper_available:
                return "whisper"
        return None
    else:
        engine_map = {
            "chirp2": _chirp2_available,
            "gemini": _genai_available,
            "whisper": _whisper_available,
        }
        if engine_map.get(requested, False):
            return requested
        return None


def transcribe_clip(
    audio_path: Path,
    clip_id: str,
    engine: str,
    project_root: Path,
) -> dict:
    """
    Dispatch transcription to the selected engine.

    Returns a transcript result dict.
    Raises on engine failure.
    """
    if engine == "gemini":
        return transcribe_with_gemini(audio_path, clip_id, project_root)
    elif engine == "chirp2":
        return transcribe_with_chirp2(audio_path, clip_id)
    elif engine == "whisper":
        return transcribe_with_whisper(audio_path, clip_id)
    else:
        raise ValueError(f"Unknown engine: {engine}")


# ---------------------------------------------------------------------------
# Detail JSON writer
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


def update_pipeline_state(
    manifest: dict,
    transcribed_count: int,
    engine_used: str | None,
    total_segments: int,
    warnings: list[str],
) -> None:
    """Update pipeline_state for phase 4 in the manifest."""
    now = datetime.now(timezone.utc).isoformat()
    ps = manifest.setdefault("pipeline_state", {})

    status = "success"
    if transcribed_count == 0:
        status = "skipped"

    phase_results = ps.setdefault("phase_results", {})
    phase_results["4"] = {
        "status": status,
        "timestamp": now,
        "transcribed": transcribed_count,
        "engine": engine_used,
        "total_segments": total_segments,
    }

    if status == "success":
        completed = ps.setdefault("completed_phases", [])
        if 4 not in completed:
            completed.append(4)
            completed.sort()
        current = ps.get("current_phase", 0)
        if current < 4:
            ps["current_phase"] = 4

    existing_warnings = ps.setdefault("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)

    ps["last_updated"] = now


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------


def process(project_root: Path, force: bool, engine_request: str) -> dict:
    """
    Run ASR across all clips in the manifest.

    Returns a result dict suitable for JSON output.
    """
    manifest = load_manifest(project_root)
    clips = manifest.get("clips", [])

    if not clips:
        return {
            "status": "success",
            "message": "No clips in manifest, nothing to process",
            "details": {"transcribed": 0, "engine": None, "total_segments": 0},
        }

    # Determine which engine to use
    engine = select_engine(engine_request)
    if engine is None:
        available = get_available_engines()
        if not available:
            msg = (
                "No ASR engine is available. Install one of: "
                "google-genai (pip install google-genai), "
                "google-cloud-speech (pip install google-cloud-speech), "
                "openai-whisper (pip install openai-whisper)"
            )
            return {
                "status": "error",
                "message": msg,
                "details": {"transcribed": 0, "engine": None, "total_segments": 0},
            }
        else:
            msg = (
                f"Requested engine '{engine_request}' is not available. "
                f"Available engines: {', '.join(available)}"
            )
            return {
                "status": "error",
                "message": msg,
                "details": {"transcribed": 0, "engine": None, "total_segments": 0},
            }

    print(f"Using ASR engine: {engine}", file=sys.stderr)

    warnings: list[str] = []
    errors: list[str] = []
    transcribed_count = 0
    total_segments = 0

    for clip in clips:
        clip_id = clip.get("id", "unknown")

        if not clip_has_audio(clip):
            continue

        audio_path = resolve_audio_path(clip, project_root)
        if audio_path is None:
            msg = f"{clip_id}: no audio file found on disk, skipping"
            print(f"  {msg}", file=sys.stderr)
            warnings.append(msg)
            continue

        # Check for empty audio files
        if audio_path.stat().st_size < MIN_AUDIO_FILE_BYTES:
            msg = f"{clip_id}: audio file is too small ({audio_path.stat().st_size} bytes), skipping"
            print(f"  {msg}", file=sys.stderr)
            warnings.append(msg)
            continue

        # Skip if already transcribed (unless --force)
        already_done = clip.get("transcript") is not None and not force
        if already_done:
            transcript_path = project_root / clip["transcript"].get("path", "")
            if transcript_path.is_file():
                print(f"  {clip_id}: transcript exists, skipping (use --force to re-transcribe)", file=sys.stderr)
                continue
            # Manifest says done but file is missing -- re-transcribe
            print(f"  {clip_id}: transcript file missing, re-transcribing", file=sys.stderr)

        print(f"  Transcribing {clip_id} with {engine}...", file=sys.stderr)

        try:
            result = transcribe_clip(audio_path, clip_id, engine, project_root)
            segment_count = len(result.get("segments", []))

            # Store summary in manifest (without full segments to keep manifest lean)
            manifest_transcript = {
                "path": result["path"],
                "engine": result["engine"],
                "segment_count": segment_count,
            }
            clip["transcript"] = manifest_transcript

            # Write full detail to separate JSON
            write_detail_json(project_root, result["path"], result)

            transcribed_count += 1
            total_segments += segment_count
            print(f"  {clip_id}: {segment_count} segments transcribed", file=sys.stderr)

        except Exception as exc:
            msg = f"{clip_id}: transcription failed ({engine}): {exc}"
            print(f"  {msg}", file=sys.stderr)
            errors.append(msg)

    # Update pipeline state and save
    update_pipeline_state(manifest, transcribed_count, engine, total_segments, warnings)

    if errors:
        ps = manifest.setdefault("pipeline_state", {})
        existing_errors = ps.setdefault("errors", [])
        for e in errors:
            if e not in existing_errors:
                existing_errors.append(e)

    save_manifest(project_root, manifest)

    # Build result message
    if errors and transcribed_count == 0:
        status = "error"
        message = f"All transcriptions failed. Errors: {len(errors)}"
    elif errors:
        status = "success"
        message = (
            f"Transcribed {transcribed_count} clips with {engine} "
            f"({total_segments} segments, {len(errors)} errors)"
        )
    else:
        status = "success"
        message = (
            f"Transcribed {transcribed_count} clips with {engine} "
            f"({total_segments} segments)"
        )

    return {
        "status": status,
        "message": message,
        "details": {
            "transcribed": transcribed_count,
            "engine": engine,
            "total_segments": total_segments,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Automatic Speech Recognition on clip audio.",
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
        help="Re-transcribe clips even if transcript already exists",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "gemini", "chirp2", "whisper"],
        default="auto",
        help="ASR engine to use (default: auto, tries engines in priority order)",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        output = {
            "status": "error",
            "message": f"Project root does not exist: {project_root}",
            "details": {"transcribed": 0, "engine": None, "total_segments": 0},
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 1

    try:
        result = process(project_root, force=args.force, engine_request=args.engine)
    except FileNotFoundError as exc:
        result = {
            "status": "error",
            "message": str(exc),
            "details": {"transcribed": 0, "engine": None, "total_segments": 0},
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "error",
            "message": f"Manifest JSON is malformed: {exc}",
            "details": {"transcribed": 0, "engine": None, "total_segments": 0},
        }
    except Exception as exc:
        result = {
            "status": "error",
            "message": f"Unexpected error: {exc}",
            "details": {"transcribed": 0, "engine": None, "total_segments": 0},
        }
        print(f"Unexpected error: {exc}", file=sys.stderr)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
