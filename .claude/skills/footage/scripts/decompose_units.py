#!/usr/bin/env python3
"""Decompose the timeline into isolated units of footage.

Each unit gets its own directory with a self-contained manifest that follows
the *same schema* as the main project manifest.  This means every existing
pipeline script (generate_sfx, generate_music, …) works unchanged when
pointed at a unit directory.

Unit types
----------
video       — Camera footage (talking head, b-roll, outdoor, etc.)
screencast  — Screen recording content
audio       — Audio-only content needing Remotion visual overlay
text_image  — Text / image content needing Remotion conversion
animation   — Placeholder for animation inserts (detected from ASR)

Runs after Phase 11 (build_manifest).  The main manifest gains a ``units``
array that tracks every unit and its directory path.

Usage:
    python3 decompose_units.py <project_root> [--force] [--min-unit-duration 5.0]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

UNIT_SUBDIRS = [
    "raw",
    "audio",
    "audio/denoised",
    "frames",
    "analysis",
    "analysis/transcripts",
    "analysis/vad",
    "analysis/pitch",
    "analysis/scenes",
    "analysis/yolo",
    "analysis/vision",
    "sfx",
    "music",
    "animations",
    "thumbnails",
    "blender",
    "tmp",
]

# Maps segment tags → unit type.  ``None`` means "fold into adjacent unit".
ACTIVITY_TO_UNIT_TYPE: dict[str, str | None] = {
    "talking_head": "video",
    "demo": "screencast",
    "b_roll": "video",
    "action": "video",
    "emphasis": "video",
    "silence": None,
    "intro": None,
    "outro": None,
}

SLUG_MAX_WORDS = 4
SLUG_MAX_CHARS = 30

# Audio-only file extensions (lowercase, without dot)
AUDIO_ONLY_EXTENSIONS = {"mp3", "wav", "flac", "ogg", "aac", "m4a", "wma", "opus"}
# Image / text file extensions
TEXT_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp", "svg",
                         "pdf", "txt", "md"}


# ──────────────────────────────────────────────────────────────────────────────
# Manifest I/O
# ──────────────────────────────────────────────────────────────────────────────


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


def save_manifest_to(path: Path, manifest: dict) -> None:
    """Atomically write a manifest dict to the given file path."""
    tmp_path = path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        tmp_path.replace(path)
    except OSError as exc:
        _fatal(f"Failed to write manifest to {path}: {exc}")


def _fatal(message: str) -> NoReturn:
    """Print structured error JSON to stdout and exit."""
    print(json.dumps({"status": "error", "message": message}))
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# Slug generation
# ──────────────────────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Convert arbitrary text to a filesystem-safe slug.

    Keeps only ASCII alphanumerics and underscores.  Strips leading/trailing
    underscores and collapses runs of underscores.
    """
    # Transliterate common Devanagari → keep only ascii word chars + spaces
    cleaned = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    # Keep only ASCII characters for the slug
    ascii_only = cleaned.encode("ascii", "ignore").decode("ascii")
    words = ascii_only.split()[:SLUG_MAX_WORDS]
    slug = "_".join(w.lower() for w in words if w)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if len(slug) > SLUG_MAX_CHARS:
        slug = slug[:SLUG_MAX_CHARS].rstrip("_")
    return slug or "untitled"


def _generate_unit_slug(
    segments: list[dict],
    clip: dict,
) -> str:
    """Derive a human-readable slug from transcript text, tags, or filename."""
    # 1. Try transcript text
    transcript = clip.get("transcript", {})
    if transcript and isinstance(transcript, dict):
        transcript_segs = transcript.get("segments", [])
        if transcript_segs and segments:
            in_pt = segments[0]["in_point"]
            out_pt = segments[-1]["out_point"]
            text_parts: list[str] = []
            for tseg in transcript_segs:
                ts = float(tseg.get("start", 0))
                te = float(tseg.get("end", 0))
                if te > in_pt and ts < out_pt:
                    text = tseg.get("text", "").strip()
                    if text:
                        text_parts.append(text)
                    if len(text_parts) >= 3:
                        break
            if text_parts:
                return _slugify(" ".join(text_parts))

    # 2. Fallback: tags
    all_tags: set[str] = set()
    for seg in segments:
        all_tags.update(seg.get("tags", []))
    if all_tags:
        tag_slug = "_".join(sorted(all_tags))
        return tag_slug[:SLUG_MAX_CHARS]

    # 3. Last resort: source filename
    source_path = clip.get("source_path", "")
    if source_path:
        return _slugify(Path(source_path).stem)

    return "untitled"


# ──────────────────────────────────────────────────────────────────────────────
# Unit type detection
# ──────────────────────────────────────────────────────────────────────────────


def _clip_unit_type(clip: dict) -> str:
    """Determine the base unit type from clip-level metadata.

    Checks clip type, file extension, and metadata to distinguish
    audio-only, text/image, screencast, and video clips.
    """
    # Screen recording → screencast
    if clip.get("type") == "screen_recording":
        return "screencast"

    # Check source file extension for audio-only or text/image
    source_path = clip.get("source_path", "")
    if source_path:
        ext = Path(source_path).suffix.lstrip(".").lower()
        if ext in AUDIO_ONLY_EXTENSIONS:
            return "audio"
        if ext in TEXT_IMAGE_EXTENSIONS:
            return "text_image"

    # Check metadata for missing video stream
    metadata = clip.get("metadata", {})
    has_audio = metadata.get("has_audio", True)
    width = metadata.get("width")
    height = metadata.get("height")
    if has_audio and (width is None or height is None or width == 0 or height == 0):
        return "audio"

    return "video"


def _segment_unit_type(segment: dict, clip_type: str) -> str:
    """Determine unit type for a single segment, considering clip type and tags."""
    if clip_type in ("audio", "text_image", "screencast"):
        return clip_type

    tags = segment.get("tags", [])
    for tag in tags:
        mapped = ACTIVITY_TO_UNIT_TYPE.get(tag)
        if mapped is not None:
            return mapped

    return "video"


# ──────────────────────────────────────────────────────────────────────────────
# Grouping segments → units
# ──────────────────────────────────────────────────────────────────────────────


def _group_segments(
    timeline: dict,
    clips_by_id: dict[str, dict],
    min_unit_duration: float,
) -> list[dict]:
    """Group timeline segments into logical units.

    Rules:
    1. Contiguous segments from the same clip + same unit_type → one unit.
    2. A type change or clip change starts a new unit.
    3. Segments whose only activity tag is ``silence`` fold into the
       preceding unit.
    4. Units shorter than *min_unit_duration* merge into their neighbour.

    Returns a list of ``{"clip_id", "unit_type", "segments"}`` dicts.
    """
    segments = timeline.get("segments", [])
    if not segments:
        return []

    # ── pass 1: build raw groups ──────────────────────────────────────────
    raw_groups: list[dict] = []
    current: dict | None = None

    for seg in segments:
        clip_id = seg["clip_id"]
        clip = clips_by_id.get(clip_id, {"id": clip_id})
        clip_type = _clip_unit_type(clip)
        unit_type = _segment_unit_type(seg, clip_type)

        # Pure silence folds into the current group
        tags = seg.get("tags", [])
        is_pure_silence = tags == ["silence"] or (len(tags) == 1 and tags[0] == "silence")
        if is_pure_silence and current is not None:
            current["segments"].append(seg)
            continue

        # Continue current group if same clip + same type
        if (
            current is not None
            and current["clip_id"] == clip_id
            and current["unit_type"] == unit_type
        ):
            current["segments"].append(seg)
        else:
            if current is not None:
                raw_groups.append(current)
            current = {
                "clip_id": clip_id,
                "unit_type": unit_type,
                "segments": [seg],
            }

    if current is not None:
        raw_groups.append(current)

    # ── pass 2: merge tiny groups into neighbours ─────────────────────────
    if not raw_groups:
        return []

    merged: list[dict] = [raw_groups[0]]
    for group in raw_groups[1:]:
        dur = sum(s.get("duration", 0.0) for s in group["segments"])
        prev = merged[-1]
        prev_dur = sum(s.get("duration", 0.0) for s in prev["segments"])

        if dur < min_unit_duration:
            # Merge into previous if same clip, else into previous anyway
            # but keep the type of whichever is longer.
            prev["segments"].extend(group["segments"])
            if dur > prev_dur:
                prev["unit_type"] = group["unit_type"]
                prev["clip_id"] = group["clip_id"]
        else:
            merged.append(group)

    return merged


# ──────────────────────────────────────────────────────────────────────────────
# Symlink helpers
# ──────────────────────────────────────────────────────────────────────────────


def _symlink_safe(src: Path, dst: Path) -> bool:
    """Create symlink ``dst → src``.  No-op if dst already exists.

    Returns True on success or if already present.
    """
    if dst.exists() or dst.is_symlink():
        return True
    try:
        resolved = src.resolve()
        if resolved.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(resolved)
            return True
    except OSError as exc:
        print(f"WARNING: symlink failed {dst} → {src}: {exc}", file=sys.stderr)
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Unit directory + manifest creation
# ──────────────────────────────────────────────────────────────────────────────


def _create_unit_dir(unit_dir: Path) -> None:
    """Create the unit directory tree (mirrors the main project layout)."""
    unit_dir.mkdir(parents=True, exist_ok=True)
    for sub in UNIT_SUBDIRS:
        (unit_dir / sub).mkdir(parents=True, exist_ok=True)


def _populate_unit_files(
    unit_dir: Path,
    project_root: Path,
    clip: dict,
    segments: list[dict],
) -> None:
    """Symlink relevant source files, audio, frames, and analysis into the unit dir."""
    # ── source video ──────────────────────────────────────────────────────
    symlink_rel = clip.get("symlink_path")
    if symlink_rel:
        _symlink_safe(
            project_root / symlink_rel,
            unit_dir / "raw" / Path(symlink_rel).name,
        )

    # ── audio (extracted + denoised) ──────────────────────────────────────
    audio = clip.get("audio", {})
    if isinstance(audio, dict):
        for key in ("extracted_path", "denoised_path"):
            rel = audio.get(key)
            if rel:
                _symlink_safe(project_root / rel, unit_dir / rel)

    # ── frames (only those within this unit's time range) ─────────────────
    in_pt = segments[0]["in_point"] if segments else 0.0
    out_pt = segments[-1]["out_point"] if segments else float("inf")

    frames_data = clip.get("frames", {})
    if isinstance(frames_data, dict):
        for fe in frames_data.get("extracted", []):
            ft = float(fe.get("time", 0.0))
            if in_pt <= ft <= out_pt:
                fp = fe.get("path")
                if fp:
                    _symlink_safe(project_root / fp, unit_dir / fp)

    # ── analysis JSON files ───────────────────────────────────────────────
    for analysis_key in ("transcript", "vad", "pitch", "scenes", "yolo", "vision"):
        data = clip.get(analysis_key, {})
        if isinstance(data, dict):
            rel_path = data.get("path")
            if rel_path:
                _symlink_safe(project_root / rel_path, unit_dir / rel_path)

    # ── style config ──────────────────────────────────────────────────────
    _symlink_safe(project_root / "style_config.json", unit_dir / "style_config.json")


# ──────────────────────────────────────────────────────────────────────────────
# Filtering helpers — scope clip data to a unit's time range
# ──────────────────────────────────────────────────────────────────────────────


def _filter_list_by_time(
    items: list[dict],
    in_pt: float,
    out_pt: float,
    *,
    start_key: str = "start",
    end_key: str = "end",
    single_key: str | None = None,
) -> list[dict]:
    """Return items whose time range overlaps [in_pt, out_pt].

    If *single_key* is given (e.g. ``"time"``), uses that field for a
    point-in-range check instead of an interval overlap check.
    """
    result: list[dict] = []
    for item in items:
        if single_key is not None:
            t = item.get(single_key)
            if t is not None and in_pt <= float(t) <= out_pt:
                result.append(item)
        else:
            s = item.get(start_key)
            e = item.get(end_key)
            if s is not None and e is not None:
                if float(e) > in_pt and float(s) < out_pt:
                    result.append(item)
    return result


def _scope_clip_to_unit(clip: dict, segments: list[dict]) -> dict:
    """Return a deep-ish copy of *clip* with analysis data scoped to the
    unit's time range.  Only data overlapping the unit's segments is kept.
    """
    if not segments:
        return dict(clip)

    in_pt = segments[0]["in_point"]
    out_pt = segments[-1]["out_point"]
    scoped = dict(clip)  # shallow top-level copy

    # ── transcript segments ───────────────────────────────────────────────
    transcript = clip.get("transcript")
    if transcript and isinstance(transcript, dict):
        scoped["transcript"] = {
            "path": transcript.get("path"),
            "engine": transcript.get("engine"),
            "segments": _filter_list_by_time(
                transcript.get("segments", []), in_pt, out_pt,
            ),
        }

    # ── VAD ───────────────────────────────────────────────────────────────
    vad = clip.get("vad")
    if vad and isinstance(vad, dict):
        scoped["vad"] = {
            "path": vad.get("path"),
            "engine": vad.get("engine"),
            "speech_segments": _filter_list_by_time(
                vad.get("speech_segments", []), in_pt, out_pt,
            ),
            "silence_segments": _filter_list_by_time(
                vad.get("silence_segments", []), in_pt, out_pt,
            ),
            "speech_ratio": vad.get("speech_ratio"),
        }

    # ── pitch ─────────────────────────────────────────────────────────────
    pitch = clip.get("pitch")
    if pitch and isinstance(pitch, dict):
        scoped["pitch"] = {
            "path": pitch.get("path"),
            "mean_hz": pitch.get("mean_hz"),
            "std_hz": pitch.get("std_hz"),
            "emphasis_points": _filter_list_by_time(
                pitch.get("emphasis_points", []), in_pt, out_pt,
                single_key="time",
            ),
        }

    # ── scenes ────────────────────────────────────────────────────────────
    scenes = clip.get("scenes")
    if scenes and isinstance(scenes, dict):
        scoped["scenes"] = {
            "path": scenes.get("path"),
            "boundaries": _filter_list_by_time(
                scenes.get("boundaries", []), in_pt, out_pt,
                single_key="time",
            ),
        }

    # ── frames ────────────────────────────────────────────────────────────
    frames = clip.get("frames")
    if frames and isinstance(frames, dict):
        filtered = _filter_list_by_time(
            frames.get("extracted", []), in_pt, out_pt,
            single_key="time",
        )
        scoped["frames"] = {
            "dir": frames.get("dir"),
            "count": len(filtered),
            "extracted": filtered,
        }

    # ── YOLO detections ───────────────────────────────────────────────────
    yolo = clip.get("yolo")
    if yolo and isinstance(yolo, dict):
        frame_paths_in_unit = {
            fe.get("path")
            for fe in scoped.get("frames", {}).get("extracted", [])
            if fe.get("path")
        }
        dbf = yolo.get("detections_by_frame", {})
        scoped["yolo"] = {
            "path": yolo.get("path"),
            "model": yolo.get("model"),
            "detections_by_frame": {
                fp: dets for fp, dets in dbf.items()
                if fp in frame_paths_in_unit
            },
            "tracking_summary": yolo.get("tracking_summary"),
        }

    # ── vision analyses ───────────────────────────────────────────────────
    vision = clip.get("vision")
    if vision and isinstance(vision, dict):
        scoped["vision"] = {
            "path": vision.get("path"),
            "analyses": _filter_list_by_time(
                vision.get("analyses", []), in_pt, out_pt,
                single_key="time",
            ),
        }

    return scoped


# ──────────────────────────────────────────────────────────────────────────────
# Build a self-contained unit manifest
# ──────────────────────────────────────────────────────────────────────────────


def _build_unit_manifest(
    unit_id: str,
    unit_type: str,
    display_name: str,
    unit_dir: Path,
    clip: dict,
    segments: list[dict],
    main_manifest: dict,
) -> dict:
    """Build a manifest for one unit that mirrors the main project schema.

    Existing scripts can run against ``unit_dir`` without modification.
    """
    now = datetime.now(timezone.utc).isoformat()

    scoped_clip = _scope_clip_to_unit(clip, segments)

    # ── timeline ──────────────────────────────────────────────────────────
    included_ids = [s["id"] for s in segments if s.get("include", True)]

    # Filter main transitions to only those within this unit
    main_transitions = main_manifest.get("timeline", {}).get("transitions", [])
    unit_seg_ids = {s["id"] for s in segments}
    unit_transitions = [
        t for t in main_transitions
        if t.get("from_segment") in unit_seg_ids
        and t.get("to_segment") in unit_seg_ids
    ]

    total_dur = sum(
        s.get("duration", 0.0) for s in segments if s.get("include", True)
    )

    in_pt = segments[0]["in_point"] if segments else 0.0
    out_pt = segments[-1]["out_point"] if segments else 0.0

    return {
        "version": "1.0.0",
        "project": {
            "id": unit_id,
            "created": now,
            "root_dir": str(unit_dir.resolve()),
            "hint": main_manifest.get("project", {}).get("hint", ""),
            "source_files": [clip.get("source_path", "")],
        },
        "unit_info": {
            "unit_id": unit_id,
            "unit_type": unit_type,
            "display_name": display_name,
            "parent_project": main_manifest.get("project", {}).get("root_dir", ""),
            "source_clip_id": clip["id"],
            "time_range": {"start": round(in_pt, 4), "end": round(out_pt, 4)},
            "status": "pending",
            "approved": False,
            "notes": "",
        },
        "clips": [scoped_clip],
        "timeline": {
            "segments": segments,
            "order": included_ids,
            "transitions": unit_transitions,
            "total_duration_seconds": round(total_dur, 4),
        },
        "sfx": [],
        "music": {"tracks": []},
        "animations": [],
        "thumbnails": [],
        "outputs": {
            "long_16_9": {
                "blender_path": None,
                "resolution": {"w": 1920, "h": 1080},
                "fps": 30,
                "render_path": None,
                "render_status": "pending",
            },
            "long_9_16": {
                "blender_path": None,
                "resolution": {"w": 1080, "h": 1920},
                "fps": 30,
                "render_path": None,
                "render_status": "pending",
            },
            "shorts": [],
        },
        "youtube": {"long_form": None, "shorts": []},
        "pipeline_state": {
            "current_phase": 11,
            "completed_phases": list(range(1, 12)),
            "phase_results": {},
            "errors": [],
            "warnings": [],
            "last_updated": now,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main orchestration
# ──────────────────────────────────────────────────────────────────────────────


def decompose(
    project_root: Path,
    manifest: dict,
    min_unit_duration: float,
) -> list[dict]:
    """Decompose the manifest timeline into isolated units.

    Creates unit directories under ``{project_root}/units/`` and returns
    a list of unit summary dicts for the main manifest.
    """
    timeline = manifest.get("timeline")
    if not timeline or not timeline.get("segments"):
        _fatal("No timeline segments found — run build_manifest.py first (Phase 11)")

    clips = manifest.get("clips", [])
    if not clips:
        _fatal("No clips in manifest")

    clips_by_id: dict[str, dict] = {c["id"]: c for c in clips}

    # Group segments into logical units
    groups = _group_segments(timeline, clips_by_id, min_unit_duration)
    if not groups:
        _fatal("Segment grouping produced zero units — nothing to decompose")

    units_dir = project_root / "units"
    units_dir.mkdir(parents=True, exist_ok=True)

    unit_summaries: list[dict] = []

    for idx, group in enumerate(groups, start=1):
        clip_id = group["clip_id"]
        unit_type = group["unit_type"]
        segments = group["segments"]
        clip = clips_by_id.get(clip_id, {"id": clip_id})

        slug = _generate_unit_slug(segments, clip)
        unit_id = f"unit_{idx:03d}_{unit_type}_{slug}"

        # Ensure unique directory name
        unit_dir = units_dir / unit_id
        suffix = 0
        while unit_dir.exists() and (unit_dir / "footage_manifest.json").exists():
            suffix += 1
            unit_dir = units_dir / f"{unit_id}_{suffix}"
            if suffix > 100:
                _fatal(f"Could not find unique directory name for {unit_id}")

        if suffix > 0:
            unit_id = f"{unit_id}_{suffix}"

        in_pt = segments[0]["in_point"] if segments else 0.0
        out_pt = segments[-1]["out_point"] if segments else 0.0
        total_dur = sum(s.get("duration", 0.0) for s in segments)
        display_name = slug.replace("_", " ").title()

        print(
            f"  Unit {idx}/{len(groups)}: {unit_id} "
            f"({unit_type}, {total_dur:.1f}s, "
            f"[{in_pt:.1f}–{out_pt:.1f}])",
            file=sys.stderr,
        )

        # Create directory tree
        _create_unit_dir(unit_dir)

        # Symlink relevant files
        _populate_unit_files(unit_dir, project_root, clip, segments)

        # Build and write unit manifest
        unit_manifest = _build_unit_manifest(
            unit_id, unit_type, display_name,
            unit_dir, clip, segments, manifest,
        )
        save_manifest_to(unit_dir / "footage_manifest.json", unit_manifest)

        # Collect summary for main manifest
        unit_summaries.append({
            "unit_id": unit_id,
            "unit_type": unit_type,
            "display_name": display_name,
            "dir": f"units/{unit_id}",
            "source_clip_id": clip_id,
            "segment_ids": [s["id"] for s in segments],
            "time_range": {"start": round(in_pt, 4), "end": round(out_pt, 4)},
            "total_duration_seconds": round(total_dur, 4),
            "status": "pending",
            "approved": False,
        })

    return unit_summaries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decompose the timeline into isolated units of footage.",
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Project root directory containing footage_manifest.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-decompose even if units already exist",
    )
    parser.add_argument(
        "--min-unit-duration",
        type=float,
        default=5.0,
        help="Units shorter than this (seconds) are merged with neighbours (default: 5.0)",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        _fatal(f"Project root does not exist: {project_root}")

    if args.min_unit_duration <= 0:
        _fatal(f"--min-unit-duration must be positive, got {args.min_unit_duration}")

    manifest = load_manifest(project_root)

    # Check for existing decomposition
    existing_units = manifest.get("units", [])
    if existing_units and not args.force:
        result = {
            "status": "success",
            "message": (
                f"Already decomposed into {len(existing_units)} units "
                "(use --force to re-decompose)"
            ),
            "details": {
                "unit_count": len(existing_units),
                "units": existing_units,
            },
        }
        print(json.dumps(result))
        return

    # Run decomposition
    print("Decomposing timeline into units…", file=sys.stderr)
    unit_summaries = decompose(project_root, manifest, args.min_unit_duration)

    # Update main manifest
    manifest["units"] = unit_summaries

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = manifest.setdefault("pipeline_state", {})
    state["units_decomposed"] = True
    state["units_decomposed_at"] = now
    state["last_updated"] = now

    save_manifest_to(project_root / "footage_manifest.json", manifest)

    # Report
    result = {
        "status": "success",
        "message": f"Decomposed into {len(unit_summaries)} units",
        "details": {
            "unit_count": len(unit_summaries),
            "units": [
                {
                    "unit_id": u["unit_id"],
                    "unit_type": u["unit_type"],
                    "display_name": u["display_name"],
                    "duration": u["total_duration_seconds"],
                    "segments": len(u["segment_ids"]),
                }
                for u in unit_summaries
            ],
        },
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
