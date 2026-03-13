#!/usr/bin/env python3
"""Export the footage manifest timeline to FCPXML format.

FCPXML (Final Cut Pro XML) is a standard interchange format importable by:
  - DaVinci Resolve  (File > Import Timeline > Import AAF/EDL/XML)
  - Final Cut Pro     (native)
  - Adobe Premiere    (File > Import)

Generates one .fcpxml file per requested format (16:9, 9:16, shorts).

Targets FCPXML **1.9** for maximum NLE compatibility — DaVinci Resolve
does not reliably import 1.10/1.11.

Usage:
    python3 export_fcpxml.py <project_root> [--force] \
        [--formats 16x9,9x16,shorts]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import NoReturn
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

FCPXML_VERSION = "1.9"
VALID_FORMATS = {"16x9", "9x16", "shorts"}

RESOLUTION_MAP = {
    "16x9": (1920, 1080),
    "9x16": (1080, 1920),
    "shorts": (1080, 1920),
}

FPS = 30

# Transition names as recognised by DaVinci Resolve / FCP
TRANSITION_NAMES = {
    "crossfade": "Cross Dissolve",
    "fade_black": "Dip to Color",
    "cut": None,  # no transition element needed
}

# ──────────────────────────────────────────────────────────────────────────────
# Manifest I/O
# ──────────────────────────────────────────────────────────────────────────────


def _fatal(msg: str) -> NoReturn:
    print(json.dumps({"status": "error", "message": msg}))
    sys.exit(1)


def load_manifest(project_root: Path) -> dict:
    path = project_root / "footage_manifest.json"
    if not path.exists():
        _fatal(f"Manifest not found at {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        _fatal(f"Failed to read manifest: {exc}")


def save_manifest(project_root: Path, manifest: dict) -> None:
    path = project_root / "footage_manifest.json"
    tmp = path.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        tmp.replace(path)
    except OSError as exc:
        _fatal(f"Failed to write manifest: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# Time helpers — FCPXML rational time
# ──────────────────────────────────────────────────────────────────────────────


def _t(seconds: float, fps: int = FPS) -> str:
    """Convert seconds to FCPXML rational time: ``frames/fps s``.

    >>> _t(5.5, 30)
    '165/30s'
    >>> _t(0.0, 30)
    '0/30s'
    """
    frames = int(round(seconds * fps))
    return f"{frames}/{fps}s"


def _dur(seconds: float, fps: int = FPS) -> str:
    """Duration — same format, but clamp to at least 1 frame."""
    frames = max(1, int(round(seconds * fps)))
    return f"{frames}/{fps}s"


def _uid(path: str) -> str:
    """Generate a stable UID from a file path (MD5 hex)."""
    return hashlib.md5(path.encode("utf-8")).hexdigest().upper()


def _file_url(path: str) -> str:
    """Convert an absolute path to a ``file://`` URL."""
    # Ensure absolute
    p = Path(path).resolve()
    return f"file://{p}"


# ──────────────────────────────────────────────────────────────────────────────
# Manifest data helpers
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_clips(manifest: dict) -> dict[str, dict]:
    return {c["id"]: c for c in manifest.get("clips", [])}


def _resolve_segments(manifest: dict) -> dict[str, dict]:
    tl = manifest.get("timeline", {})
    return {s["id"]: s for s in tl.get("segments", [])}


def _get_clip_duration(clip: dict) -> float:
    """Get clip total duration in seconds."""
    meta = clip.get("metadata", {})
    return float(meta.get("duration_seconds", 0.0))


def _get_clip_fps(clip: dict) -> float:
    meta = clip.get("metadata", {})
    return float(meta.get("fps", FPS) or FPS)


def _get_transition(
    transitions: list[dict],
    from_id: str,
    to_id: str,
) -> dict | None:
    for tr in transitions:
        if tr.get("from_segment") == from_id and tr.get("to_segment") == to_id:
            return tr
    return None


# ──────────────────────────────────────────────────────────────────────────────
# FCPXML document builder
# ──────────────────────────────────────────────────────────────────────────────


def _build_resources(
    manifest: dict,
    clips_by_id: dict[str, dict],
    project_root: Path,
    fmt_id: str,
    width: int,
    height: int,
    fps: int,
) -> Element:
    """Build the <resources> element with format + asset definitions."""
    resources = Element("resources")

    # ── format definition ─────────────────────────────────────────────────
    fmt = SubElement(resources, "format")
    fmt.set("id", fmt_id)
    fmt.set("name", f"{width}x{height}p{fps}")
    fmt.set("frameDuration", f"1/{fps}s")
    fmt.set("width", str(width))
    fmt.set("height", str(height))

    # ── media assets ──────────────────────────────────────────────────────
    seen_clips: set[str] = set()
    for clip_id, clip in clips_by_id.items():
        sp = clip.get("source_path")
        if not sp:
            continue
        p = Path(sp)
        abs_path = str(p.resolve()) if p.is_absolute() else str((project_root / sp).resolve())

        if abs_path in seen_clips:
            continue
        seen_clips.add(abs_path)

        asset_id = f"a_{clip_id}"
        dur = _get_clip_duration(clip)
        clip_fps = int(_get_clip_fps(clip))
        uid = _uid(abs_path)

        asset = SubElement(resources, "asset")
        asset.set("id", asset_id)
        asset.set("name", Path(abs_path).name)
        asset.set("uid", uid)
        asset.set("start", "0/1s")
        asset.set("duration", _t(dur, clip_fps))
        asset.set("hasVideo", "1" if clip.get("metadata", {}).get("width") else "0")
        asset.set("hasAudio", "1" if clip.get("metadata", {}).get("has_audio", True) else "0")
        asset.set("format", fmt_id)
        asset.set("audioSources", "1")
        asset.set("audioChannels", str(clip.get("metadata", {}).get("audio_channels", 2)))
        asset.set("audioRate", str(clip.get("metadata", {}).get("audio_sample_rate", 48000)))

        media_rep = SubElement(asset, "media-rep")
        media_rep.set("kind", "original-media")
        media_rep.set("sig", uid)
        media_rep.set("src", _file_url(abs_path))

    # ── SFX assets ────────────────────────────────────────────────────────
    for sfx in manifest.get("sfx", []):
        gen_path = sfx.get("generated_path")
        if not gen_path:
            continue
        abs_path = str((project_root / gen_path).resolve())
        sfx_id = sfx.get("id", "sfx_unknown")
        uid = _uid(abs_path)

        asset = SubElement(resources, "asset")
        asset.set("id", f"a_{sfx_id}")
        asset.set("name", Path(abs_path).name)
        asset.set("uid", uid)
        asset.set("start", "0/1s")
        asset.set("duration", _dur(sfx.get("duration_seconds", 1.0), fps))
        asset.set("hasVideo", "0")
        asset.set("hasAudio", "1")
        asset.set("audioSources", "1")
        asset.set("audioChannels", "1")
        asset.set("audioRate", "48000")

        media_rep = SubElement(asset, "media-rep")
        media_rep.set("kind", "original-media")
        media_rep.set("sig", uid)
        media_rep.set("src", _file_url(abs_path))

    # ── Music assets ──────────────────────────────────────────────────────
    for track in manifest.get("music", {}).get("tracks", []):
        gen_path = track.get("generated_path")
        if not gen_path:
            continue
        abs_path = str((project_root / gen_path).resolve())
        track_id = track.get("id", "music_unknown")
        uid = _uid(abs_path)

        asset = SubElement(resources, "asset")
        asset.set("id", f"a_{track_id}")
        asset.set("name", Path(abs_path).name)
        asset.set("uid", uid)
        asset.set("start", "0/1s")
        asset.set("duration", _dur(track.get("duration_seconds", 60.0), fps))
        asset.set("hasVideo", "0")
        asset.set("hasAudio", "1")
        asset.set("audioSources", "1")
        asset.set("audioChannels", "2")
        asset.set("audioRate", "48000")

        media_rep = SubElement(asset, "media-rep")
        media_rep.set("kind", "original-media")
        media_rep.set("sig", uid)
        media_rep.set("src", _file_url(abs_path))

    # ── Animation assets ──────────────────────────────────────────────────
    for anim in manifest.get("animations", []):
        rpath = anim.get("rendered_path")
        if not rpath or not anim.get("approved", False):
            continue
        abs_path = str((project_root / rpath).resolve())
        anim_id = anim.get("id", "anim_unknown")
        uid = _uid(abs_path)

        asset = SubElement(resources, "asset")
        asset.set("id", f"a_{anim_id}")
        asset.set("name", Path(abs_path).name)
        asset.set("uid", uid)
        asset.set("start", "0/1s")
        asset.set("duration", _dur(anim.get("duration_seconds", 5.0), fps))
        asset.set("hasVideo", "1")
        asset.set("hasAudio", "0")
        asset.set("format", fmt_id)

        media_rep = SubElement(asset, "media-rep")
        media_rep.set("kind", "original-media")
        media_rep.set("sig", uid)
        media_rep.set("src", _file_url(abs_path))

    return resources


# ──────────────────────────────────────────────────────────────────────────────
# Build the primary spine (video + transitions)
# ──────────────────────────────────────────────────────────────────────────────


def _build_spine(
    order: list[str],
    segments_by_id: dict[str, dict],
    transitions: list[dict],
    fps: int,
) -> Element:
    """Build the <spine> element containing video segments and transitions."""
    spine = Element("spine")
    timeline_seconds = 0.0

    for idx, seg_id in enumerate(order):
        seg = segments_by_id.get(seg_id)
        if seg is None:
            continue

        clip_id = seg.get("clip_id")
        if not clip_id:
            continue

        source_in = seg.get("in_point", 0.0)
        source_out = seg.get("out_point", 0.0)
        seg_duration = seg.get("duration", source_out - source_in)
        speed_factor = seg.get("speed_factor", 1.0) or 1.0
        audio_gain_db = seg.get("audio_gain_db", 0.0) or 0.0

        # Handle transition overlap: pull back timeline for crossfade/fade
        tr_overlap = 0.0
        if idx > 0:
            prev_id = order[idx - 1]
            tr = _get_transition(transitions, prev_id, seg_id)
            if tr and tr.get("type") in ("crossfade", "fade_black"):
                tr_dur = tr.get("duration_seconds", 0.0)
                if tr_dur > 0:
                    tr_overlap = tr_dur
                    timeline_seconds -= tr_overlap

                    # Add transition element
                    tr_name = TRANSITION_NAMES.get(tr["type"])
                    if tr_name:
                        tr_elem = SubElement(spine, "transition")
                        tr_elem.set("name", tr_name)
                        tr_elem.set("offset", _t(timeline_seconds, fps))
                        tr_elem.set("duration", _dur(tr_dur, fps))

        # Effective duration considering speed
        effective_duration = seg_duration / speed_factor if speed_factor != 1.0 else seg_duration

        # Asset clip
        clip_elem = SubElement(spine, "asset-clip")
        clip_elem.set("ref", f"a_{clip_id}")
        clip_elem.set("name", seg_id)
        clip_elem.set("offset", _t(timeline_seconds, fps))
        clip_elem.set("start", _t(source_in, fps))
        clip_elem.set("duration", _dur(effective_duration, fps))
        clip_elem.set("tcFormat", "NDF")

        # Audio gain
        if audio_gain_db != 0.0:
            vol_elem = SubElement(clip_elem, "adjust-volume")
            vol_elem.set("amount", f"{audio_gain_db:+.1f}dB")

        # Speed change
        if speed_factor != 1.0:
            rate_elem = SubElement(clip_elem, "timeMap")
            timept = SubElement(rate_elem, "timept")
            timept.set("time", "0/1s")
            timept.set("value", "0/1s")
            timept.set("interp", "smooth2")
            timept2 = SubElement(rate_elem, "timept")
            timept2.set("time", _t(effective_duration, fps))
            timept2.set("value", _t(seg_duration, fps))
            timept2.set("interp", "smooth2")

        timeline_seconds += effective_duration

    return spine


# ──────────────────────────────────────────────────────────────────────────────
# Build SFX and music as connected storylines
# ──────────────────────────────────────────────────────────────────────────────


def _build_sfx_elements(
    manifest: dict,
    segments_by_id: dict[str, dict],
    order: list[str],
    fps: int,
) -> list[Element]:
    """Build <asset-clip> elements for SFX as connected clips."""
    sfx_list = manifest.get("sfx", [])
    if not sfx_list:
        return []

    # Build segment timeline positions
    seg_positions: dict[str, float] = {}
    pos = 0.0
    for seg_id in order:
        seg = segments_by_id.get(seg_id)
        if seg:
            seg_positions[seg_id] = pos
            dur = seg.get("duration", 0.0)
            speed = seg.get("speed_factor", 1.0) or 1.0
            pos += dur / speed if speed != 1.0 else dur

    elements: list[Element] = []
    for sfx in sfx_list:
        sfx_id = sfx.get("id", "sfx_unknown")
        if not sfx.get("approved", False) and sfx.get("auto_confidence") != "high":
            continue
        if not sfx.get("generated_path"):
            continue

        # Resolve timeline position
        placement = sfx.get("placement", {})
        ptype = placement.get("type", "")
        offset_sec = placement.get("time_offset_seconds", 0.0) or 0.0
        sfx_time: float | None = None

        if ptype == "at_time":
            sfx_time = float(placement.get("absolute_time", 0.0) or 0.0)
        elif ptype == "between_segments":
            after_id = placement.get("after_segment")
            if after_id and after_id in seg_positions:
                seg = segments_by_id.get(after_id)
                seg_dur = seg.get("duration", 0.0) if seg else 0.0
                sfx_time = seg_positions[after_id] + seg_dur + offset_sec
        elif ptype == "within_segment":
            target = placement.get("after_segment") or placement.get("target_segment")
            if target and target in seg_positions:
                sfx_time = seg_positions[target] + offset_sec

        if sfx_time is None:
            continue

        sfx_time = max(0.0, sfx_time)
        sfx_dur = sfx.get("duration_seconds", 1.0)
        volume_db = sfx.get("volume_db", 0.0) or 0.0

        clip = Element("asset-clip")
        clip.set("ref", f"a_{sfx_id}")
        clip.set("name", f"SFX: {sfx_id}")
        clip.set("lane", "1")
        clip.set("offset", _t(sfx_time, fps))
        clip.set("start", "0/1s")
        clip.set("duration", _dur(sfx_dur, fps))
        clip.set("audioRole", "effects")

        if volume_db != 0.0:
            vol = SubElement(clip, "adjust-volume")
            vol.set("amount", f"{volume_db:+.1f}dB")

        elements.append(clip)

    return elements


def _build_music_elements(
    manifest: dict,
    fps: int,
) -> list[Element]:
    """Build <asset-clip> elements for music tracks with ducking keyframes."""
    music = manifest.get("music", {})
    tracks = music.get("tracks", [])
    elements: list[Element] = []

    for track in tracks:
        track_id = track.get("id", "music_unknown")
        if not track.get("generated_path"):
            continue

        placement = track.get("placement", {})
        start_time = float(placement.get("start_time", 0.0) or 0.0)
        dur = float(track.get("duration_seconds", 60.0))
        fade_in = float(placement.get("fade_in_seconds", 0.0) or 0.0)
        fade_out = float(placement.get("fade_out_seconds", 0.0) or 0.0)
        ducking = track.get("ducking_keyframes", [])

        clip = Element("asset-clip")
        clip.set("ref", f"a_{track_id}")
        clip.set("name", f"Music: {track_id}")
        clip.set("lane", "2")
        clip.set("offset", _t(start_time, fps))
        clip.set("start", "0/1s")
        clip.set("duration", _dur(dur, fps))
        clip.set("audioRole", "music")

        # Volume keyframes for ducking
        if ducking or fade_in > 0 or fade_out > 0:
            adjust = SubElement(clip, "adjust-volume")

            # Collect all keyframes
            kfs: list[tuple[float, float]] = []

            if fade_in > 0:
                kfs.append((0.0, 0.0))

            for kf in ducking:
                kf_time = float(kf.get("time", 0.0))
                kf_vol_db = float(kf.get("volume_db", -18.0))
                # Convert dB to linear (0dB = 1.0)
                linear = 10.0 ** (kf_vol_db / 20.0)
                kfs.append((kf_time, linear))

            if fade_out > 0:
                kfs.append((dur - fade_out, kfs[-1][1] if kfs else 1.0))
                kfs.append((dur, 0.0))

            # Sort and deduplicate
            kfs.sort(key=lambda x: x[0])

            for kf_time, kf_vol in kfs:
                param = SubElement(adjust, "param")
                param.set("name", "volume")
                keyframe = SubElement(param, "keyframe")
                keyframe.set("time", _t(kf_time, fps))
                keyframe.set("value", f"{kf_vol:.3f}")
                keyframe.set("interp", "smooth")

        elements.append(clip)

    return elements


# ──────────────────────────────────────────────────────────────────────────────
# Build a complete FCPXML sequence for one format
# ──────────────────────────────────────────────────────────────────────────────


def build_fcpxml_for_format(
    manifest: dict,
    project_root: Path,
    format_name: str,
    project_name: str,
    order: list[str],
    transitions: list[dict],
) -> Element:
    """Build a complete <fcpxml> Element for one output format."""
    width, height = RESOLUTION_MAP[format_name]
    fps = FPS
    fmt_id = f"r_fmt_{format_name}"

    clips_by_id = _resolve_clips(manifest)
    segments_by_id = _resolve_segments(manifest)

    # Root
    root = Element("fcpxml")
    root.set("version", FCPXML_VERSION)

    # Resources
    resources = _build_resources(
        manifest, clips_by_id, project_root,
        fmt_id, width, height, fps,
    )
    root.append(resources)

    # Library > Event > Project > Sequence
    library = SubElement(root, "library")
    event = SubElement(library, "event")
    event.set("name", manifest.get("project", {}).get("id", "Footage Project"))

    project = SubElement(event, "project")
    project.set("name", project_name)

    # Calculate total duration
    total_dur = manifest.get("timeline", {}).get("total_duration_seconds", 0.0)
    if total_dur <= 0:
        total_dur = sum(
            (segments_by_id.get(sid, {}).get("duration", 0.0)) for sid in order
        )

    sequence = SubElement(project, "sequence")
    sequence.set("format", fmt_id)
    sequence.set("duration", _t(total_dur, fps))
    sequence.set("tcStart", "0/1s")
    sequence.set("tcFormat", "NDF")
    sequence.set("audioLayout", "stereo")
    sequence.set("audioRate", "48k")

    # Primary spine (video segments + transitions)
    spine = _build_spine(
        order, segments_by_id,
        transitions, fps,
    )
    sequence.append(spine)

    # SFX as connected clips on the spine
    sfx_elements = _build_sfx_elements(manifest, segments_by_id, order, fps)
    if sfx_elements and len(spine) > 0:
        # Attach SFX to the first clip on the spine
        first_clip = spine[0]
        for sfx_elem in sfx_elements:
            first_clip.append(sfx_elem)

    # Music as connected clips
    music_elements = _build_music_elements(manifest, fps)
    if music_elements and len(spine) > 0:
        first_clip = spine[0]
        for mus_elem in music_elements:
            first_clip.append(mus_elem)

    return root


# ──────────────────────────────────────────────────────────────────────────────
# XML serialisation
# ──────────────────────────────────────────────────────────────────────────────


def _serialize_fcpxml(root: Element) -> str:
    """Serialise an FCPXML Element tree to a pretty-printed XML string
    with the required DOCTYPE declaration."""
    rough = tostring(root, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(rough)
    pretty = dom.toprettyxml(indent="  ", encoding=None)

    # minidom adds an xml declaration; replace it with our own + DOCTYPE
    lines = pretty.split("\n")
    # Remove minidom's xml declaration line
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]

    header = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
    body = "\n".join(line for line in lines if line.strip())
    return header + body + "\n"


# ──────────────────────────────────────────────────────────────────────────────
# Format builders
# ──────────────────────────────────────────────────────────────────────────────


def export_16x9(
    manifest: dict,
    project_root: Path,
    output_path: Path,
    force: bool,
) -> str | None:
    """Export 16:9 long-form FCPXML. Returns output path or None."""
    if not force and output_path.exists():
        print(f"16x9 FCPXML already exists at {output_path}, skipping", file=sys.stderr)
        return str(output_path)

    tl = manifest.get("timeline", {})
    order = tl.get("order", [])
    transitions = tl.get("transitions", [])

    root = build_fcpxml_for_format(
        manifest, project_root, "16x9",
        "Long Form 16:9", order, transitions,
    )
    xml_str = _serialize_fcpxml(root)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    return str(output_path)


def export_9x16(
    manifest: dict,
    project_root: Path,
    output_path: Path,
    force: bool,
) -> str | None:
    """Export 9:16 long-form FCPXML."""
    if not force and output_path.exists():
        print(f"9x16 FCPXML already exists at {output_path}, skipping", file=sys.stderr)
        return str(output_path)

    tl = manifest.get("timeline", {})
    order = tl.get("order", [])
    transitions = tl.get("transitions", [])

    root = build_fcpxml_for_format(
        manifest, project_root, "9x16",
        "Long Form 9:16", order, transitions,
    )

    # Add crop keyframe data as markers (NLE-agnostic hint)
    # DaVinci / FCP user can read these markers and apply crops manually
    _add_crop_markers(root, manifest, order)

    xml_str = _serialize_fcpxml(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    return str(output_path)


def export_shorts(
    manifest: dict,
    project_root: Path,
    output_dir: Path,
    force: bool,
) -> list[dict]:
    """Export 9:16 short FCPXML files. Returns list of {id, path} dicts."""
    shorts = manifest.get("outputs", {}).get("shorts", [])
    if not shorts:
        return []

    all_transitions = manifest.get("timeline", {}).get("transitions", [])
    results: list[dict] = []

    for short_entry in shorts:
        short_id = short_entry.get("id", "unknown_short")
        output_path = output_dir / f"{short_id}_9x16.fcpxml"

        if not force and output_path.exists():
            results.append({"id": short_id, "path": str(output_path)})
            continue

        short_segments = short_entry.get("segments", [])
        if not short_segments:
            continue

        # Build transitions for this short
        short_transitions: list[dict] = []
        for i in range(len(short_segments) - 1):
            tr = _get_transition(all_transitions, short_segments[i], short_segments[i + 1])
            if tr:
                short_transitions.append(tr)
            else:
                short_transitions.append({
                    "from_segment": short_segments[i],
                    "to_segment": short_segments[i + 1],
                    "type": "cut",
                    "duration_seconds": 0.0,
                })

        root = build_fcpxml_for_format(
            manifest, project_root, "shorts",
            f"Short: {short_entry.get('title', short_id)}",
            short_segments, short_transitions,
        )
        xml_str = _serialize_fcpxml(root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml_str, encoding="utf-8")
        results.append({"id": short_id, "path": str(output_path)})

    return results


def _add_crop_markers(root: Element, manifest: dict, order: list[str]) -> None:
    """Add markers to the 9:16 FCPXML with crop keyframe hints.

    FCPXML doesn't support animated crop keyframes natively across NLEs,
    so we encode them as timeline markers the editor can reference.
    """
    segments_by_id = _resolve_segments(manifest)
    fps = FPS

    # Find the spine element
    spine = root.find(".//spine")
    if spine is None:
        return

    for seg_id in order:
        seg = segments_by_id.get(seg_id)
        if not seg:
            continue
        crop_data = seg.get("crop_9_16", {})
        keyframes = crop_data.get("keyframes", [])
        if not keyframes:
            continue

        # Find the asset-clip for this segment
        for clip_elem in spine.iter("asset-clip"):
            if clip_elem.get("name") == seg_id:
                for kf in keyframes:
                    kf_time = kf.get("time", 0.0)
                    crop_x = kf.get("x", 0)
                    crop_w = kf.get("w", 608)
                    easing = kf.get("easing", "SINE")
                    in_pt = seg.get("in_point", 0.0)
                    rel_time = kf_time - in_pt

                    marker = SubElement(clip_elem, "marker")
                    marker.set("start", _t(rel_time, fps))
                    marker.set("duration", "1/30s")
                    marker.set("value", f"CROP x={crop_x} w={crop_w} easing={easing}")
                break


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the footage manifest timeline to FCPXML format.",
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
        help="Overwrite existing FCPXML files",
    )
    parser.add_argument(
        "--formats",
        type=str,
        default="16x9,9x16,shorts",
        help="Comma-separated formats to export (default: 16x9,9x16,shorts)",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        _fatal(f"Project root does not exist: {project_root}")

    requested = {f.strip() for f in args.formats.split(",")}
    invalid = requested - VALID_FORMATS
    if invalid:
        _fatal(f"Invalid formats: {', '.join(sorted(invalid))}")

    manifest = load_manifest(project_root)

    # Validate
    tl = manifest.get("timeline", {})
    if not tl.get("order"):
        _fatal("No timeline order — run build_manifest.py first")

    exports_dir = project_root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    exported: list[str] = []
    export_paths: dict[str, str | list[dict]] = {}
    errors: list[str] = []

    if "16x9" in requested:
        path = export_16x9(manifest, project_root, exports_dir / "long_16x9.fcpxml", args.force)
        if path:
            exported.append("16x9")
            export_paths["16x9"] = path
        else:
            errors.append("16x9 export failed")

    if "9x16" in requested:
        path = export_9x16(manifest, project_root, exports_dir / "long_9x16.fcpxml", args.force)
        if path:
            exported.append("9x16")
            export_paths["9x16"] = path
        else:
            errors.append("9x16 export failed")

    if "shorts" in requested:
        results = export_shorts(manifest, project_root, exports_dir, args.force)
        if results:
            exported.append("shorts")
            export_paths["shorts"] = results

    # Update manifest outputs with export paths
    outputs = manifest.setdefault("outputs", {})
    if "16x9" in export_paths:
        outputs.setdefault("long_16_9", {})["fcpxml_path"] = f"exports/long_16x9.fcpxml"
    if "9x16" in export_paths:
        outputs.setdefault("long_9_16", {})["fcpxml_path"] = f"exports/long_9x16.fcpxml"
    if "shorts" in export_paths and isinstance(export_paths["shorts"], list):
        existing_shorts = outputs.get("shorts", [])
        shorts_by_id = {s.get("id"): s for s in existing_shorts}
        for result in export_paths["shorts"]:
            if isinstance(result, dict):
                sid = result.get("id")
                if sid and sid in shorts_by_id:
                    shorts_by_id[sid]["fcpxml_path"] = f"exports/{sid}_9x16.fcpxml"

    save_manifest(project_root, manifest)

    # Report
    output = {
        "status": "success",
        "message": f"Exported FCPXML for {len(exported)} format(s): {', '.join(exported)}",
        "details": {
            "formats_exported": exported,
            "export_paths": {
                k: v if isinstance(v, str) else [r.get("path") for r in v if isinstance(r, dict)]
                for k, v in export_paths.items()
            },
            "fcpxml_version": FCPXML_VERSION,
            "note": "Import into DaVinci Resolve via File > Import Timeline > Import AAF/EDL/XML",
        },
    }
    if errors:
        output["details"]["errors"] = errors

    print(json.dumps(output))


if __name__ == "__main__":
    main()
