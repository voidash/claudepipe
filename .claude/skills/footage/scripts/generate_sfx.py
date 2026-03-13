#!/usr/bin/env python3
"""
Generate sound effects using ElevenLabs text-to-sound-effects API.

Identifies SFX placement candidates from the timeline (transitions,
scene changes, text appearances, pitch emphasis, speech pauses) and
optionally generates audio files via ElevenLabs.

Phase 14 of the footage pipeline.

Usage:
    python3 generate_sfx.py <project_root> [--force] [--dry-run]

Exit codes:
    0 - Processing completed (even if some generations were skipped)
    1 - Fatal error (manifest missing, no timeline, etc.)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional heavy imports -- guarded so the script can degrade gracefully.
# ---------------------------------------------------------------------------

_elevenlabs_available = False
try:
    from elevenlabs import ElevenLabs
    _elevenlabs_available = True
except ImportError:
    ElevenLabs = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_FILENAME = "footage_manifest.json"
STYLE_CONFIG_FILENAME = "style_config.json"
SFX_OUTPUT_DIR = "sfx"
PHASE_NUMBER = 14

MAX_API_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 2.0

# Minimum silence duration (seconds) to qualify as a pause candidate.
PAUSE_MIN_DURATION_SECONDS = 0.5

# Emphasis magnitude threshold (0-1 normalised) to qualify as emphasis SFX.
EMPHASIS_MIN_MAGNITUDE = 0.5

# ---------------------------------------------------------------------------
# Prompt templates: auto_reason -> (template, default_duration, default_volume)
# ---------------------------------------------------------------------------

PROMPT_TEMPLATES: dict[str, tuple[str, float, float]] = {
    "transition": (
        "quick whoosh swoosh transition sound effect, clean and modern, {duration}s",
        1.0,
        -6.0,
    ),
    "scene_change": (
        "subtle scene transition sound, soft and clean, {duration}s",
        0.8,
        -12.0,
    ),
    "text_appear": (
        "light pop notification sound, clean digital, {duration}s",
        0.5,
        -12.0,
    ),
    "emphasis": (
        "subtle rising tone accent sound effect, brief, {duration}s",
        0.5,
        -9.0,
    ),
    "pause": (
        "very subtle tick or breath sound, barely audible, {duration}s",
        0.3,
        -12.0,
    ),
}

# Map auto_reason to volume category for style_config lookup.
_VOLUME_CATEGORY: dict[str, str] = {
    "transition": "transition",
    "scene_change": "subtle",
    "text_appear": "subtle",
    "emphasis": "emphasis",
    "pause": "subtle",
}

# Default volume overrides by category (used when style_config is absent).
_VOLUME_DEFAULTS: dict[str, float] = {
    "transition": -6.0,
    "subtle": -12.0,
    "emphasis": -9.0,
}


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def load_manifest(project_root: Path) -> dict:
    """Load and return the footage manifest. Raises on failure."""
    manifest_path = project_root / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(project_root: Path, manifest: dict) -> None:
    """Atomically write the manifest back to disk."""
    manifest_path = project_root / MANIFEST_FILENAME
    tmp_path = manifest_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp_path.replace(manifest_path)


def load_style_config(project_root: Path) -> dict | None:
    """Load style_config.json if it exists. Returns None on failure."""
    style_path = project_root / STYLE_CONFIG_FILENAME
    if not style_path.is_file():
        return None
    try:
        with style_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: failed to load style_config.json: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Volume resolution
# ---------------------------------------------------------------------------


def resolve_volume(auto_reason: str, style_config: dict | None) -> float:
    """Determine volume_db for an SFX candidate.

    Checks style_config.audio.sfx_volume_db as a global override,
    then falls back to category-based defaults.
    """
    category = _VOLUME_CATEGORY.get(auto_reason, "subtle")

    if style_config is not None:
        audio_cfg = style_config.get("audio", {})
        # style_config has a single sfx_volume_db -- use it as the
        # transition-level default, but keep subtle sounds quieter.
        global_sfx_vol = audio_cfg.get("sfx_volume_db")
        if global_sfx_vol is not None:
            if category == "transition":
                return float(global_sfx_vol)
            if category == "emphasis":
                return float(global_sfx_vol) - 3.0
            # subtle
            return float(global_sfx_vol) - 6.0

    return _VOLUME_DEFAULTS.get(category, -12.0)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def _next_sfx_id(existing_sfx: list[dict]) -> str:
    """Generate the next sfx_NNN ID that does not collide with existing ones."""
    existing_ids: set[str] = set()
    max_num = 0
    for entry in existing_sfx:
        sid = entry.get("id", "")
        existing_ids.add(sid)
        if sid.startswith("sfx_"):
            try:
                num = int(sid[4:])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    return f"sfx_{max_num + 1:03d}"


def _allocate_ids(existing_sfx: list[dict], count: int) -> list[str]:
    """Pre-allocate *count* unique SFX IDs."""
    existing_ids: set[str] = set()
    max_num = 0
    for entry in existing_sfx:
        sid = entry.get("id", "")
        existing_ids.add(sid)
        if sid.startswith("sfx_"):
            try:
                num = int(sid[4:])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass

    ids: list[str] = []
    for i in range(1, count + 1):
        new_id = f"sfx_{max_num + i:03d}"
        ids.append(new_id)
    return ids


# ---------------------------------------------------------------------------
# Timeline helpers
# ---------------------------------------------------------------------------


def _build_segment_map(clips: list[dict]) -> dict[str, dict]:
    """Build clip_id -> clip lookup."""
    return {clip["id"]: clip for clip in clips}


def _get_segment_absolute_start(
    segment_id: str,
    order: list[str],
    segments_by_id: dict[str, dict],
    transitions: list[dict],
) -> float | None:
    """Compute the absolute start time of a segment in the timeline.

    Walks the order list, accumulating durations and transition overlaps.
    Returns None if the segment is not found in the order.
    """
    # Build a quick transition lookup: (from, to) -> duration
    trans_map: dict[tuple[str, str], float] = {}
    for tr in transitions:
        key = (tr.get("from_segment", ""), tr.get("to_segment", ""))
        trans_map[key] = tr.get("duration_seconds", 0.0)

    current_time = 0.0
    for idx, seg_id in enumerate(order):
        if seg_id == segment_id:
            return current_time

        seg = segments_by_id.get(seg_id)
        if seg is None:
            continue

        seg_duration = seg.get("duration", seg.get("out_point", 0.0) - seg.get("in_point", 0.0))
        speed = seg.get("speed_factor", 1.0) or 1.0
        effective_duration = seg_duration / speed

        # Subtract transition overlap with next segment
        if idx + 1 < len(order):
            next_id = order[idx + 1]
            overlap = trans_map.get((seg_id, next_id), 0.0)
            current_time += effective_duration - overlap
        else:
            current_time += effective_duration

    return None


def _get_segment_absolute_end(
    segment_id: str,
    order: list[str],
    segments_by_id: dict[str, dict],
    transitions: list[dict],
) -> float | None:
    """Compute the absolute end time of a segment in the timeline."""
    start = _get_segment_absolute_start(segment_id, order, segments_by_id, transitions)
    if start is None:
        return None

    seg = segments_by_id.get(segment_id)
    if seg is None:
        return None

    seg_duration = seg.get("duration", seg.get("out_point", 0.0) - seg.get("in_point", 0.0))
    speed = seg.get("speed_factor", 1.0) or 1.0
    return start + seg_duration / speed


# ---------------------------------------------------------------------------
# Candidate identification
# ---------------------------------------------------------------------------


def identify_transition_candidates(
    timeline: dict,
    segments_by_id: dict[str, dict],
    style_config: dict | None,
) -> list[dict]:
    """Identify SFX candidates at transition points between segments.

    Non-cut transitions get high confidence; cuts get no SFX (they are
    inherently silent transitions).
    """
    order = timeline.get("order", [])
    transitions = timeline.get("transitions", [])
    if len(order) < 2:
        return []

    # Index transitions by (from, to)
    trans_map: dict[tuple[str, str], dict] = {}
    for tr in transitions:
        key = (tr.get("from_segment", ""), tr.get("to_segment", ""))
        trans_map[key] = tr

    candidates: list[dict] = []
    for idx in range(len(order) - 1):
        from_id = order[idx]
        to_id = order[idx + 1]
        tr = trans_map.get((from_id, to_id))

        # Only generate SFX for non-cut transitions
        if tr is not None and tr.get("type", "cut") != "cut":
            trans_duration = tr.get("duration_seconds", 0.5)
            sfx_duration = max(0.5, min(2.0, trans_duration + 0.5))

            candidates.append({
                "description": f"whoosh transition between {from_id} and {to_id}",
                "auto_reason": "transition",
                "auto_confidence": "high",
                "duration_seconds": round(sfx_duration, 2),
                "placement": {
                    "type": "between_segments",
                    "after_segment": from_id,
                    "before_segment": to_id,
                    "absolute_time": None,
                    "time_offset_seconds": -0.2,
                },
                "volume_db": resolve_volume("transition", style_config),
            })

    return candidates


def identify_scene_change_candidates(
    timeline: dict,
    segments_by_id: dict[str, dict],
    clips: list[dict],
    clip_map: dict[str, dict],
    style_config: dict | None,
) -> list[dict]:
    """Identify SFX candidates at scene boundaries within segments."""
    order = timeline.get("order", [])
    transitions = timeline.get("transitions", [])
    candidates: list[dict] = []

    for seg_id in order:
        seg = segments_by_id.get(seg_id)
        if seg is None:
            continue

        clip_id = seg.get("clip_id")
        if clip_id is None:
            continue

        clip = clip_map.get(clip_id)
        if clip is None:
            continue

        scenes = clip.get("scenes")
        if scenes is None:
            continue

        boundaries = scenes.get("boundaries", [])
        in_point = seg.get("in_point", 0.0)
        out_point = seg.get("out_point", float("inf"))

        seg_abs_start = _get_segment_absolute_start(
            seg_id, order, segments_by_id, transitions,
        )
        if seg_abs_start is None:
            continue

        for boundary in boundaries:
            boundary_time = boundary.get("time", 0.0)
            # Only include boundaries within this segment's range
            if in_point < boundary_time < out_point:
                # Convert clip-relative time to timeline-absolute time
                offset_in_seg = boundary_time - in_point
                speed = seg.get("speed_factor", 1.0) or 1.0
                abs_time = seg_abs_start + offset_in_seg / speed

                candidates.append({
                    "description": f"scene change in {seg_id} at clip time {boundary_time:.1f}s",
                    "auto_reason": "scene_change",
                    "auto_confidence": "high",
                    "duration_seconds": 0.8,
                    "placement": {
                        "type": "within_segment",
                        "after_segment": seg_id,
                        "before_segment": None,
                        "absolute_time": round(abs_time, 3),
                        "time_offset_seconds": -0.1,
                    },
                    "volume_db": resolve_volume("scene_change", style_config),
                })

    return candidates


def identify_text_appear_candidates(
    timeline: dict,
    segments_by_id: dict[str, dict],
    animations: list[dict],
    style_config: dict | None,
) -> list[dict]:
    """Identify SFX candidates where text/graphics appear (animations with overlay placement)."""
    order = timeline.get("order", [])
    transitions = timeline.get("transitions", [])
    candidates: list[dict] = []

    for anim in animations:
        placement = anim.get("placement", {})
        placement_type = placement.get("type", "")

        # Only consider overlays (not full replacements which already have their own audio)
        if placement_type != "overlay":
            continue

        target_seg = placement.get("target_segment")
        if target_seg is None:
            continue

        seg_abs_start = _get_segment_absolute_start(
            target_seg, order, segments_by_id, transitions,
        )
        if seg_abs_start is None:
            continue

        start_time = placement.get("start_time")
        abs_time = seg_abs_start + (start_time if start_time is not None else 0.0)

        candidates.append({
            "description": f"text/graphic appear for animation {anim.get('id', 'unknown')}",
            "auto_reason": "text_appear",
            "auto_confidence": "high",
            "duration_seconds": 0.5,
            "placement": {
                "type": "within_segment",
                "after_segment": target_seg,
                "before_segment": None,
                "absolute_time": round(abs_time, 3),
                "time_offset_seconds": 0.0,
            },
            "volume_db": resolve_volume("text_appear", style_config),
        })

    return candidates


def identify_emphasis_candidates(
    timeline: dict,
    segments_by_id: dict[str, dict],
    clips: list[dict],
    clip_map: dict[str, dict],
    style_config: dict | None,
) -> list[dict]:
    """Identify SFX candidates at pitch emphasis points (medium confidence)."""
    order = timeline.get("order", [])
    transitions = timeline.get("transitions", [])
    candidates: list[dict] = []

    for seg_id in order:
        seg = segments_by_id.get(seg_id)
        if seg is None:
            continue

        clip_id = seg.get("clip_id")
        if clip_id is None:
            continue

        clip = clip_map.get(clip_id)
        if clip is None:
            continue

        pitch = clip.get("pitch")
        if pitch is None:
            continue

        emphasis_points = pitch.get("emphasis_points", [])
        in_point = seg.get("in_point", 0.0)
        out_point = seg.get("out_point", float("inf"))

        seg_abs_start = _get_segment_absolute_start(
            seg_id, order, segments_by_id, transitions,
        )
        if seg_abs_start is None:
            continue

        for ep in emphasis_points:
            ep_time = ep.get("time", 0.0)
            magnitude = ep.get("magnitude", 0.0)

            if ep_time < in_point or ep_time >= out_point:
                continue
            if magnitude < EMPHASIS_MIN_MAGNITUDE:
                continue

            offset_in_seg = ep_time - in_point
            speed = seg.get("speed_factor", 1.0) or 1.0
            abs_time = seg_abs_start + offset_in_seg / speed

            candidates.append({
                "description": f"pitch emphasis ({ep.get('type', 'unknown')}) in {seg_id} at {ep_time:.2f}s",
                "auto_reason": "emphasis",
                "auto_confidence": "medium",
                "duration_seconds": 0.5,
                "placement": {
                    "type": "within_segment",
                    "after_segment": seg_id,
                    "before_segment": None,
                    "absolute_time": round(abs_time, 3),
                    "time_offset_seconds": 0.0,
                },
                "volume_db": resolve_volume("emphasis", style_config),
            })

    return candidates


def identify_pause_candidates(
    timeline: dict,
    segments_by_id: dict[str, dict],
    clips: list[dict],
    clip_map: dict[str, dict],
    style_config: dict | None,
) -> list[dict]:
    """Identify SFX candidates at speech pauses > 0.5s (medium confidence)."""
    order = timeline.get("order", [])
    transitions = timeline.get("transitions", [])
    candidates: list[dict] = []

    for seg_id in order:
        seg = segments_by_id.get(seg_id)
        if seg is None:
            continue

        clip_id = seg.get("clip_id")
        if clip_id is None:
            continue

        clip = clip_map.get(clip_id)
        if clip is None:
            continue

        vad = clip.get("vad")
        if vad is None:
            continue

        silence_segments = vad.get("silence_segments", [])
        in_point = seg.get("in_point", 0.0)
        out_point = seg.get("out_point", float("inf"))

        seg_abs_start = _get_segment_absolute_start(
            seg_id, order, segments_by_id, transitions,
        )
        if seg_abs_start is None:
            continue

        for silence in silence_segments:
            sil_start = silence.get("start", 0.0)
            sil_duration = silence.get("duration", 0.0)

            if sil_start < in_point or sil_start >= out_point:
                continue
            if sil_duration < PAUSE_MIN_DURATION_SECONDS:
                continue

            # Place SFX at the start of the pause
            offset_in_seg = sil_start - in_point
            speed = seg.get("speed_factor", 1.0) or 1.0
            abs_time = seg_abs_start + offset_in_seg / speed

            candidates.append({
                "description": f"speech pause ({sil_duration:.2f}s) in {seg_id}",
                "auto_reason": "pause",
                "auto_confidence": "medium",
                "duration_seconds": 0.3,
                "placement": {
                    "type": "within_segment",
                    "after_segment": seg_id,
                    "before_segment": None,
                    "absolute_time": round(abs_time, 3),
                    "time_offset_seconds": 0.1,
                },
                "volume_db": resolve_volume("pause", style_config),
            })

    return candidates


def identify_all_candidates(
    manifest: dict,
    style_config: dict | None,
) -> list[dict]:
    """Identify all SFX placement candidates from the manifest timeline.

    Returns a list of candidate dicts (without id or generated_path yet).
    """
    timeline = manifest.get("timeline")
    if timeline is None:
        return []

    segments = timeline.get("segments", [])
    if not segments:
        return []

    # Build segment lookup by id
    segments_by_id: dict[str, dict] = {s["id"]: s for s in segments if "id" in s}
    clips = manifest.get("clips", [])
    clip_map = _build_segment_map(clips)
    animations = manifest.get("animations", [])

    candidates: list[dict] = []

    # High confidence: transitions between segments (non-cut)
    candidates.extend(
        identify_transition_candidates(timeline, segments_by_id, style_config)
    )

    # High confidence: scene changes within segments
    candidates.extend(
        identify_scene_change_candidates(
            timeline, segments_by_id, clips, clip_map, style_config,
        )
    )

    # High confidence: text/graphic appearances
    candidates.extend(
        identify_text_appear_candidates(
            timeline, segments_by_id, animations, style_config,
        )
    )

    # Medium confidence: pitch emphasis
    candidates.extend(
        identify_emphasis_candidates(
            timeline, segments_by_id, clips, clip_map, style_config,
        )
    )

    # Medium confidence: speech pauses
    candidates.extend(
        identify_pause_candidates(
            timeline, segments_by_id, clips, clip_map, style_config,
        )
    )

    # Sort candidates by absolute time (where available), then by segment order
    def _sort_key(c: dict) -> float:
        abs_t = c.get("placement", {}).get("absolute_time")
        if abs_t is not None:
            return abs_t
        # Fallback: use a large value so they sort last
        return float("inf")

    candidates.sort(key=_sort_key)
    return candidates


# ---------------------------------------------------------------------------
# Build full SFX entries from candidates
# ---------------------------------------------------------------------------


def build_sfx_entries(
    candidates: list[dict],
    existing_sfx: list[dict],
) -> list[dict]:
    """Assign IDs, prompts, and generated_paths to candidate dicts.

    Returns fully-formed SFX entries ready for the manifest.
    """
    ids = _allocate_ids(existing_sfx, len(candidates))
    entries: list[dict] = []

    for candidate, sfx_id in zip(candidates, ids):
        reason = candidate["auto_reason"]
        template, default_dur, _default_vol = PROMPT_TEMPLATES.get(
            reason, PROMPT_TEMPLATES["transition"],
        )
        duration = candidate.get("duration_seconds", default_dur)
        prompt = template.format(duration=duration)

        entry = {
            "id": sfx_id,
            "description": candidate["description"],
            "prompt": prompt,
            "duration_seconds": duration,
            "placement": candidate["placement"],
            "generated_path": f"{SFX_OUTPUT_DIR}/{sfx_id}.wav",
            "auto_confidence": candidate["auto_confidence"],
            "auto_reason": reason,
            "approved": False,
            "volume_db": candidate["volume_db"],
        }
        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# SFX generation via ElevenLabs
# ---------------------------------------------------------------------------


def _check_api_key() -> str | None:
    """Return the ElevenLabs API key from environment, or None."""
    return os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")


def generate_single_sfx(
    client: "ElevenLabs",  # type: ignore[name-defined]
    sfx_entry: dict,
    project_root: Path,
) -> bool:
    """Generate a single SFX file via the ElevenLabs API.

    Retries up to MAX_API_RETRIES times on failure.
    Returns True on success, False on failure.
    """
    output_path = project_root / sfx_entry["generated_path"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    last_exc: Exception | None = None
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            result = client.text_to_sound_effects.convert(
                text=sfx_entry["prompt"],
                duration_seconds=sfx_entry["duration_seconds"],
            )
            # result is a generator of bytes
            with output_path.open("wb") as fh:
                for chunk in result:
                    fh.write(chunk)

            # Verify non-empty
            if output_path.stat().st_size == 0:
                print(
                    f"WARNING: generated file is empty for {sfx_entry['id']}, "
                    f"attempt {attempt}/{MAX_API_RETRIES}",
                    file=sys.stderr,
                )
                output_path.unlink(missing_ok=True)
                last_exc = RuntimeError("empty file generated")
                continue

            return True

        except Exception as exc:
            last_exc = exc
            print(
                f"WARNING: API call failed for {sfx_entry['id']} "
                f"(attempt {attempt}/{MAX_API_RETRIES}): {exc}",
                file=sys.stderr,
            )
            if attempt < MAX_API_RETRIES:
                backoff = RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                time.sleep(backoff)

    print(
        f"ERROR: all {MAX_API_RETRIES} attempts failed for {sfx_entry['id']}: {last_exc}",
        file=sys.stderr,
    )
    return False


def generate_sfx_files(
    sfx_entries: list[dict],
    project_root: Path,
    force: bool,
) -> tuple[int, list[str]]:
    """Generate SFX audio files for eligible candidates.

    Only generates for high-confidence or already-approved entries.
    Skips entries that already have a file on disk (unless --force).

    Returns (generated_count, error_messages).
    """
    api_key = _check_api_key()
    if api_key is None:
        msg = "ELEVEN_API_KEY not set; skipping SFX generation (candidates still saved to manifest)"
        print(f"WARNING: {msg}", file=sys.stderr)
        return 0, [msg]

    if not _elevenlabs_available:
        msg = "elevenlabs package not installed; skipping SFX generation"
        print(f"WARNING: {msg}", file=sys.stderr)
        return 0, [msg]

    client = ElevenLabs()  # type: ignore[misc]

    generated = 0
    errors: list[str] = []

    for entry in sfx_entries:
        # Only generate for high-confidence auto-placements or approved entries
        if entry["auto_confidence"] != "high" and not entry.get("approved", False):
            continue

        output_path = project_root / entry["generated_path"]
        if output_path.is_file() and not force:
            # Already exists on disk, skip
            continue

        success = generate_single_sfx(client, entry, project_root)
        if success:
            generated += 1
        else:
            errors.append(f"Failed to generate {entry['id']}")

    return generated, errors


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(
    manifest: dict,
    candidates_count: int,
    generated_count: int,
    dry_run: bool,
    warnings: list[str],
) -> None:
    """Update pipeline_state for phase 14."""
    now = datetime.now(timezone.utc).isoformat()
    ps = manifest.setdefault("pipeline_state", {})

    if candidates_count == 0:
        status = "skipped"
    elif dry_run:
        status = "success"
    else:
        status = "success"

    phase_results = ps.setdefault("phase_results", {})
    phase_results[str(PHASE_NUMBER)] = {
        "status": status,
        "timestamp": now,
        "candidates": candidates_count,
        "generated": generated_count,
        "dry_run": dry_run,
    }

    if status == "success":
        completed = ps.setdefault("completed_phases", [])
        if PHASE_NUMBER not in completed:
            completed.append(PHASE_NUMBER)
            completed.sort()
        current = ps.get("current_phase", 0)
        if current < PHASE_NUMBER:
            ps["current_phase"] = PHASE_NUMBER

    existing_warnings = ps.setdefault("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)

    ps["last_updated"] = now


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def process(project_root: Path, force: bool, dry_run: bool) -> dict:
    """Identify SFX candidates, optionally generate them, and update manifest.

    Returns a result dict suitable for JSON output.
    """
    manifest = load_manifest(project_root)
    style_config = load_style_config(project_root)
    warnings: list[str] = []

    # Check for timeline
    timeline = manifest.get("timeline")
    if timeline is None or not timeline.get("segments"):
        return {
            "status": "success",
            "message": "No timeline segments found, nothing to process",
            "details": {"candidates": 0, "generated": 0, "dry_run": dry_run},
        }

    # Identify candidates
    candidates = identify_all_candidates(manifest, style_config)

    if not candidates:
        update_pipeline_state(manifest, 0, 0, dry_run, warnings)
        save_manifest(project_root, manifest)
        return {
            "status": "success",
            "message": "No SFX candidates identified from timeline",
            "details": {"candidates": 0, "generated": 0, "dry_run": dry_run},
        }

    # Build full SFX entries
    existing_sfx = manifest.get("sfx", [])

    # When not forcing, avoid duplicating candidates that already exist
    # in the manifest by matching on auto_reason + placement type + segment.
    if not force:
        existing_keys: set[str] = set()
        for existing in existing_sfx:
            pl = existing.get("placement", {})
            key = (
                f"{existing.get('auto_reason', '')}|"
                f"{pl.get('type', '')}|"
                f"{pl.get('after_segment', '')}|"
                f"{pl.get('before_segment', '')}|"
                f"{pl.get('absolute_time', '')}"
            )
            existing_keys.add(key)

        filtered_candidates: list[dict] = []
        for c in candidates:
            pl = c.get("placement", {})
            key = (
                f"{c.get('auto_reason', '')}|"
                f"{pl.get('type', '')}|"
                f"{pl.get('after_segment', '')}|"
                f"{pl.get('before_segment', '')}|"
                f"{pl.get('absolute_time', '')}"
            )
            if key not in existing_keys:
                filtered_candidates.append(c)

        candidates = filtered_candidates

    if not candidates and not force:
        update_pipeline_state(manifest, 0, 0, dry_run, warnings)
        save_manifest(project_root, manifest)
        return {
            "status": "success",
            "message": "All SFX candidates already exist in manifest",
            "details": {"candidates": 0, "generated": 0, "dry_run": dry_run},
        }

    sfx_entries = build_sfx_entries(candidates, existing_sfx)

    # Generate SFX files (unless dry-run)
    generated_count = 0
    if dry_run:
        # In dry-run, just report candidates
        if not _elevenlabs_available:
            warnings.append("elevenlabs package not installed")
        if _check_api_key() is None:
            warnings.append("ELEVEN_API_KEY not set")

        print("Dry-run mode: identified candidates:", file=sys.stderr)
        for entry in sfx_entries:
            print(
                f"  {entry['id']}: {entry['description']} "
                f"[{entry['auto_confidence']}] -> {entry['generated_path']}",
                file=sys.stderr,
            )
    else:
        generated_count, gen_errors = generate_sfx_files(
            sfx_entries, project_root, force,
        )
        warnings.extend(gen_errors)

    # Update manifest sfx array
    if force:
        # Replace the entire sfx list
        manifest["sfx"] = sfx_entries
    else:
        # Append new entries
        if "sfx" not in manifest:
            manifest["sfx"] = []
        manifest["sfx"].extend(sfx_entries)

    total_candidates = len(sfx_entries)
    update_pipeline_state(manifest, total_candidates, generated_count, dry_run, warnings)
    save_manifest(project_root, manifest)

    if dry_run:
        message = f"Dry run: identified {total_candidates} SFX candidates"
    else:
        message = f"Identified {total_candidates} candidates, generated {generated_count} SFX files"

    return {
        "status": "success",
        "message": message,
        "details": {
            "candidates": total_candidates,
            "generated": generated_count,
            "dry_run": dry_run,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate sound effects using ElevenLabs text-to-sound-effects API.",
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
        help="Regenerate SFX even if they already exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Only identify candidates, do not call the API",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        output = {
            "status": "error",
            "message": f"Project root does not exist: {project_root}",
            "details": {"candidates": 0, "generated": 0, "dry_run": args.dry_run},
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 1

    try:
        result = process(project_root, force=args.force, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        result = {
            "status": "error",
            "message": str(exc),
            "details": {"candidates": 0, "generated": 0, "dry_run": args.dry_run},
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "error",
            "message": f"Manifest JSON is malformed: {exc}",
            "details": {"candidates": 0, "generated": 0, "dry_run": args.dry_run},
        }
    except Exception as exc:
        result = {
            "status": "error",
            "message": f"Unexpected error: {exc}",
            "details": {"candidates": 0, "generated": 0, "dry_run": args.dry_run},
        }
        print(f"Unexpected error: {exc}", file=sys.stderr)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
