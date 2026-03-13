#!/usr/bin/env python3
"""Assemble Blender VSE projects from the footage manifest.

Generates three output formats: 16:9 long-form, 9:16 long-form, and 9:16
shorts.  For each format, a temporary Python script is produced and executed
inside Blender headlessly.  The resulting .blend files are saved under the
project's ``blender/`` directory and their paths written back to the manifest.

Phase 17 of the footage pipeline.

Usage:
    python3 build_blender_project.py <project_root> [--force] \
        [--formats 16x9,9x16,shorts] [--blender-path PATH]
"""

import argparse
import json
import logging
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BLENDER_PATH = Path("/Applications/Blender.app/Contents/MacOS/Blender")
BLENDER_TIMEOUT_SECONDS = 300
VALID_FORMATS = {"16x9", "9x16", "shorts"}

RESOLUTION_MAP = {
    "16x9": (1920, 1080),
    "9x16": (1080, 1920),
    "shorts": (1080, 1920),
}

FPS = 30

# Blender easing lookup.
# Each entry maps our easing name -> (interpolation, easing_type).
# easing_type may be None when the interpolation constant is sufficient.
EASING_MAP = {
    "BEZIER":   ("BEZIER",   None),
    "SINE":     ("SINE",     "EASE_IN_OUT"),
    "EXPO":     ("EXPO",     "EASE_IN_OUT"),
    "BACK":     ("BACK",     "EASE_OUT"),
    "ELASTIC":  ("ELASTIC",  "EASE_OUT"),
    "BOUNCE":   ("BOUNCE",   "EASE_OUT"),
    "CONSTANT": ("CONSTANT", None),
}


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def _fatal(message: str) -> NoReturn:
    """Print an error JSON payload to stdout and exit with code 1."""
    print(json.dumps({"status": "error", "message": message}))
    sys.exit(1)


def load_manifest(project_root: Path) -> dict:
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        _fatal(f"Manifest not found at {manifest_path}")
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        _fatal(f"Failed to read manifest: {exc}")


def save_manifest(project_root: Path, manifest: dict) -> None:
    manifest_path = project_root / "footage_manifest.json"
    tmp_path = manifest_path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        tmp_path.replace(manifest_path)
    except OSError as exc:
        _fatal(f"Failed to write manifest: {exc}")


# ---------------------------------------------------------------------------
# Helpers: resolve data structures from manifest
# ---------------------------------------------------------------------------


def _escape_path_for_python(path: str) -> str:
    """Escape a filesystem path for embedding in a Python string literal."""
    r = repr(path)
    return r[1:-1]


def _resolve_clips(manifest: dict) -> dict[str, dict]:
    """Return a dict mapping clip_id -> clip entry."""
    return {clip["id"]: clip for clip in manifest.get("clips", [])}


def _resolve_segments(manifest: dict) -> dict[str, dict]:
    """Return a dict mapping segment_id -> segment entry."""
    timeline = manifest.get("timeline", {})
    return {seg["id"]: seg for seg in timeline.get("segments", [])}


def _get_timeline_order(manifest: dict) -> list[str]:
    return manifest.get("timeline", {}).get("order", [])


def _get_transitions(manifest: dict) -> list[dict]:
    return manifest.get("timeline", {}).get("transitions", [])


def _get_transition_for_pair(
    transitions: list[dict],
    from_id: str,
    to_id: str,
) -> dict | None:
    for tr in transitions:
        if tr.get("from_segment") == from_id and tr.get("to_segment") == to_id:
            return tr
    return None


def _resolve_source_path(
    segment: dict,
    clips_by_id: dict[str, dict],
    project_root: Path,
) -> str | None:
    """Return the absolute source path for a segment's clip, or None."""
    clip_id = segment.get("clip_id")
    if not clip_id or clip_id not in clips_by_id:
        return None
    clip = clips_by_id[clip_id]
    source = clip.get("source_path")
    if not source:
        return None
    p = Path(source)
    if p.is_absolute():
        return str(p)
    return str(project_root / source)


# ---------------------------------------------------------------------------
# Blender script generation: common header
# ---------------------------------------------------------------------------


def _blender_header(res_x: int, res_y: int, fps: int) -> str:
    """Return the common Blender Python script header."""
    return textwrap.dedent(f"""\
        import bpy
        import os
        import math

        # ---- Reset scene ----
        bpy.ops.wm.read_homefile(use_empty=True)
        scene = bpy.context.scene

        # ---- Render settings ----
        scene.render.resolution_x = {res_x}
        scene.render.resolution_y = {res_y}
        scene.render.fps = {fps}
        scene.render.image_settings.file_format = 'FFMPEG'
        scene.render.ffmpeg.format = 'MPEG4'
        scene.render.ffmpeg.codec = 'H264'

        # ---- Create sequence editor ----
        scene.sequence_editor_create()
        sed = scene.sequence_editor

        # ---- Channel assignments ----
        CH_VIDEO = 1
        CH_AUDIO = 2
        CH_SFX = 3
        CH_MUSIC = 4
        CH_SPEED = 5
        CH_TRANSFORM = 6
        CH_ANIM = 7
        CH_OVERLAY = 8

        FPS = {fps}
        warnings = []
    """)


# ---------------------------------------------------------------------------
# Blender script generation: segment placement
# ---------------------------------------------------------------------------


def _blender_place_segments(
    order: list[str],
    segments_by_id: dict[str, dict],
    clips_by_id: dict[str, dict],
    transitions: list[dict],
    project_root: Path,
    apply_crop: bool,
    source_res: tuple[int, int] | None = None,
) -> str:
    """Generate Python code to place video+audio strips on the timeline.

    If *apply_crop* is True, crop keyframes from crop_9_16 are applied to
    each strip.  *source_res* is (width, height) of the source footage,
    needed for crop calculations.
    """
    lines: list[str] = []
    lines.append("# ---- Place segments ----")
    lines.append("timeline_frame = 1")
    lines.append("segment_start_frames = {}")
    lines.append("")

    for idx, seg_id in enumerate(order):
        seg = segments_by_id.get(seg_id)
        if seg is None:
            lines.append(f"# WARNING: segment {seg_id!r} not found in manifest, skipping")
            continue

        source_path = _resolve_source_path(seg, clips_by_id, project_root)
        if source_path is None:
            lines.append(f"# WARNING: no source path for segment {seg_id!r}, skipping")
            continue

        clip_id = seg["clip_id"]
        clip = clips_by_id.get(clip_id, {})
        clip_meta = clip.get("metadata", {})
        clip_fps = clip_meta.get("fps", FPS) or FPS

        in_seconds = seg.get("in_point", 0.0)
        out_seconds = seg.get("out_point", 0.0)
        duration_seconds = seg.get("duration", out_seconds - in_seconds)
        speed_factor = seg.get("speed_factor", 1.0) or 1.0
        audio_gain_db = seg.get("audio_gain_db", 0.0) or 0.0

        # Handle transition overlap: if there is a crossfade or fade_black
        # coming FROM the previous segment TO this one, pull timeline_frame
        # back by the transition duration to create overlap.
        if idx > 0:
            prev_id = order[idx - 1]
            tr = _get_transition_for_pair(transitions, prev_id, seg_id)
            if tr and tr.get("type") in ("crossfade", "fade_black"):
                tr_dur = tr.get("duration_seconds", 0.0)
                tr_dur_frames = int(tr_dur * FPS)
                if tr_dur_frames > 0:
                    lines.append(f"# Transition overlap ({tr['type']} {tr_dur}s)")
                    lines.append(f"timeline_frame -= {tr_dur_frames}")
                    lines.append("")

        safe_path = _escape_path_for_python(source_path)

        lines.append(f"# ---- Segment: {seg_id} (clip {clip_id}) ----")
        lines.append(f"_src = '{safe_path}'")
        lines.append(f"if os.path.exists(_src):")
        lines.append(f"    segment_start_frames[{seg_id!r}] = timeline_frame")
        lines.append(f"    _in_frame = int({in_seconds} * {clip_fps})")
        lines.append(f"    _dur_frames = int({duration_seconds} * {clip_fps})")
        lines.append(f"")
        lines.append(f"    _vstrip = sed.sequences.new_movie(")
        lines.append(f"        name='v_{seg_id}',")
        lines.append(f"        filepath=_src,")
        lines.append(f"        channel=CH_VIDEO,")
        lines.append(f"        frame_start=timeline_frame,")
        lines.append(f"    )")
        lines.append(f"    _vstrip.frame_offset_start = _in_frame")
        lines.append(f"    _vstrip.frame_final_duration = _dur_frames")
        lines.append(f"")
        lines.append(f"    _astrip = sed.sequences.new_sound(")
        lines.append(f"        name='a_{seg_id}',")
        lines.append(f"        filepath=_src,")
        lines.append(f"        channel=CH_AUDIO,")
        lines.append(f"        frame_start=timeline_frame,")
        lines.append(f"    )")
        lines.append(f"    _astrip.frame_offset_start = _in_frame")
        lines.append(f"    _astrip.frame_final_duration = _dur_frames")

        # Audio gain
        if audio_gain_db != 0.0:
            lines.append(f"    _astrip.volume = 10 ** ({audio_gain_db} / 20.0)")

        # Speed factor
        if speed_factor != 1.0:
            lines.append(f"")
            lines.append(f"    _speed = sed.sequences.new_effect(")
            lines.append(f"        name='speed_{seg_id}',")
            lines.append(f"        type='SPEED',")
            lines.append(f"        channel=CH_SPEED,")
            lines.append(f"        frame_start=timeline_frame,")
            lines.append(f"        seq1=_vstrip,")
            lines.append(f"    )")
            lines.append(f"    _speed.speed_factor = {speed_factor}")

        # Crop for 9:16 format
        if apply_crop:
            crop_data = seg.get("crop_9_16", {})
            keyframes = crop_data.get("keyframes", [])
            if keyframes and source_res:
                src_w, src_h = source_res
                lines.append(f"")
                lines.append(f"    # ---- Crop keyframes for 9:16 ----")
                lines.append(f"    _vstrip.use_crop = True")

                for kf_idx, kf in enumerate(keyframes):
                    kf_time = kf.get("time", 0.0)
                    crop_x = kf.get("x", 0)
                    crop_w = kf.get("w", src_w)
                    crop_y = kf.get("y", 0)
                    crop_h = kf.get("h", src_h)
                    easing = kf.get("easing", "BEZIER")

                    # Blender crop: min_x = left crop, max_x = right crop,
                    # min_y = bottom crop, max_y = top crop.
                    min_x = crop_x
                    max_x = src_w - crop_x - crop_w
                    min_y = crop_y
                    max_y = src_h - crop_y - crop_h

                    # Clamp to non-negative
                    min_x = max(0, min_x)
                    max_x = max(0, max_x)
                    min_y = max(0, min_y)
                    max_y = max(0, max_y)

                    # Frame number relative to the segment start in timeline
                    kf_rel_seconds = kf_time - in_seconds
                    kf_frame = f"timeline_frame + int({kf_rel_seconds} * FPS)"

                    lines.append(f"")
                    lines.append(f"    # Crop keyframe {kf_idx}: time={kf_time}, easing={easing}")
                    lines.append(f"    _kf_frame = {kf_frame}")
                    lines.append(f"    _vstrip.crop.min_x = {min_x}")
                    lines.append(f"    _vstrip.crop.max_x = {max_x}")
                    lines.append(f"    _vstrip.crop.min_y = {min_y}")
                    lines.append(f"    _vstrip.crop.max_y = {max_y}")
                    lines.append(f"    _vstrip.crop.keyframe_insert(data_path='min_x', frame=_kf_frame)")
                    lines.append(f"    _vstrip.crop.keyframe_insert(data_path='max_x', frame=_kf_frame)")
                    lines.append(f"    _vstrip.crop.keyframe_insert(data_path='min_y', frame=_kf_frame)")
                    lines.append(f"    _vstrip.crop.keyframe_insert(data_path='max_y', frame=_kf_frame)")

                # Apply easing to fcurves after all keyframes are set
                lines.append(f"")
                lines.append(f"    # Apply easing to crop keyframes")
                lines.append(f"    _easing_map = {{")
                for ename, (interp, etype) in EASING_MAP.items():
                    lines.append(f"        {ename!r}: ({interp!r}, {etype!r}),")
                lines.append(f"    }}")
                lines.append(f"    _kf_easings = [")
                for kf in keyframes:
                    lines.append(f"        {kf.get('easing', 'BEZIER')!r},")
                lines.append(f"    ]")
                lines.append(f"    if _vstrip.crop.animation_data and _vstrip.crop.animation_data.action:")
                lines.append(f"        for _fc in _vstrip.crop.animation_data.action.fcurves:")
                lines.append(f"            for _ki, _kp in enumerate(_fc.keyframe_points):")
                lines.append(f"                if _ki < len(_kf_easings):")
                lines.append(f"                    _ename = _kf_easings[_ki]")
                lines.append(f"                    _interp, _etype = _easing_map.get(_ename, ('BEZIER', None))")
                lines.append(f"                    _kp.interpolation = _interp")
                lines.append(f"                    if _etype is not None:")
                lines.append(f"                        _kp.easing = _etype")

        # Handle transition effects between this segment and the previous one
        if idx > 0:
            prev_id = order[idx - 1]
            tr = _get_transition_for_pair(transitions, prev_id, seg_id)
            if tr:
                tr_type = tr.get("type", "cut")
                tr_dur = tr.get("duration_seconds", 0.0)
                tr_dur_frames = int(tr_dur * FPS)

                if tr_type == "crossfade" and tr_dur_frames > 0:
                    lines.append(f"")
                    lines.append(f"    # Crossfade transition from {prev_id}")
                    lines.append(f"    try:")
                    lines.append(f"        _prev_strip = sed.sequences.get('v_{prev_id}')")
                    lines.append(f"        if _prev_strip:")
                    lines.append(f"            sed.sequences.new_effect(")
                    lines.append(f"                name='xfade_{prev_id}_{seg_id}',")
                    lines.append(f"                type='CROSS',")
                    lines.append(f"                channel=CH_OVERLAY,")
                    lines.append(f"                frame_start=timeline_frame,")
                    lines.append(f"                frame_end=timeline_frame + {tr_dur_frames},")
                    lines.append(f"                seq1=_prev_strip,")
                    lines.append(f"                seq2=_vstrip,")
                    lines.append(f"            )")
                    lines.append(f"    except Exception as _e:")
                    lines.append(f"        warnings.append(f'Crossfade {prev_id}->{seg_id} failed: {{_e}}')")

                elif tr_type == "fade_black" and tr_dur_frames > 0:
                    lines.append(f"")
                    lines.append(f"    # Fade-through-black transition from {prev_id}")
                    lines.append(f"    try:")
                    lines.append(f"        _prev_strip = sed.sequences.get('v_{prev_id}')")
                    lines.append(f"        if _prev_strip:")
                    lines.append(f"            _black = sed.sequences.new_effect(")
                    lines.append(f"                name='black_{prev_id}_{seg_id}',")
                    lines.append(f"                type='COLOR',")
                    lines.append(f"                channel=CH_OVERLAY + 1,")
                    lines.append(f"                frame_start=timeline_frame,")
                    lines.append(f"                frame_end=timeline_frame + {tr_dur_frames},")
                    lines.append(f"            )")
                    lines.append(f"            _black.color = (0.0, 0.0, 0.0)")
                    lines.append(f"            sed.sequences.new_effect(")
                    lines.append(f"                name='fade_out_{prev_id}',")
                    lines.append(f"                type='CROSS',")
                    lines.append(f"                channel=CH_OVERLAY + 2,")
                    lines.append(f"                frame_start=timeline_frame,")
                    lines.append(f"                frame_end=timeline_frame + {tr_dur_frames // 2},")
                    lines.append(f"                seq1=_prev_strip,")
                    lines.append(f"                seq2=_black,")
                    lines.append(f"            )")
                    lines.append(f"            sed.sequences.new_effect(")
                    lines.append(f"                name='fade_in_{seg_id}',")
                    lines.append(f"                type='CROSS',")
                    lines.append(f"                channel=CH_OVERLAY + 3,")
                    lines.append(f"                frame_start=timeline_frame + {tr_dur_frames // 2},")
                    lines.append(f"                frame_end=timeline_frame + {tr_dur_frames},")
                    lines.append(f"                seq1=_black,")
                    lines.append(f"                seq2=_vstrip,")
                    lines.append(f"            )")
                    lines.append(f"    except Exception as _e:")
                    lines.append(f"        warnings.append(f'Fade-black {prev_id}->{seg_id} failed: {{_e}}')")

        # Advance timeline
        lines.append(f"")
        lines.append(f"    timeline_frame += _dur_frames")
        lines.append(f"else:")
        lines.append(f"    warnings.append('Missing media: {safe_path}')")
        lines.append(f"")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Blender script generation: SFX, music, animations
# ---------------------------------------------------------------------------


def _blender_place_sfx(
    manifest: dict,
    project_root: Path,
) -> str:
    """Generate Python code to place SFX strips."""
    sfx_list = manifest.get("sfx", [])
    if not sfx_list:
        return "# No SFX entries in manifest\n"

    lines: list[str] = []
    lines.append("# ---- SFX placement ----")

    for sfx in sfx_list:
        sfx_id = sfx.get("id", "unknown")
        approved = sfx.get("approved", False)
        confidence = sfx.get("auto_confidence", "low")

        # Only place approved SFX or high-confidence auto-generated ones
        if not approved and confidence != "high":
            lines.append(f"# SFX {sfx_id} skipped: not approved and confidence={confidence}")
            continue

        gen_path = sfx.get("generated_path")
        if not gen_path:
            lines.append(f"# SFX {sfx_id} skipped: no generated_path")
            continue

        abs_path = str((project_root / gen_path).resolve())
        safe_path = _escape_path_for_python(abs_path)
        volume_db = sfx.get("volume_db", 0.0) or 0.0

        # The frame position will be calculated dynamically in the Blender
        # script using segment_start_frames built during segment placement.
        placement = sfx.get("placement", {})
        ptype = placement.get("type", "")
        offset = placement.get("time_offset_seconds", 0.0) or 0.0

        lines.append(f"")
        lines.append(f"# SFX: {sfx_id}")
        lines.append(f"_sfx_src = '{safe_path}'")
        lines.append(f"if os.path.exists(_sfx_src):")

        if ptype == "at_time":
            abs_time = placement.get("absolute_time", 0.0) or 0.0
            lines.append(f"    _sfx_frame = max(1, int({abs_time} * FPS) + 1)")
        elif ptype == "between_segments":
            after_id = placement.get("after_segment")
            before_id = placement.get("before_segment")
            if after_id:
                lines.append(f"    _after_seg = segment_start_frames.get({after_id!r})")
                lines.append(f"    if _after_seg is not None:")
                # We need the duration of the after segment to find its end frame
                seg = None
                segments_by_id = _resolve_segments(manifest)
                seg = segments_by_id.get(after_id)
                seg_dur = seg.get("duration", 0.0) if seg else 0.0
                lines.append(f"        _sfx_frame = max(1, _after_seg + int({seg_dur} * FPS) + int({offset} * FPS))")
                lines.append(f"    else:")
                if before_id:
                    lines.append(f"        _before_seg = segment_start_frames.get({before_id!r})")
                    lines.append(f"        _sfx_frame = max(1, _before_seg + int({offset} * FPS)) if _before_seg is not None else None")
                else:
                    lines.append(f"        _sfx_frame = None")
            elif before_id:
                lines.append(f"    _before_seg = segment_start_frames.get({before_id!r})")
                lines.append(f"    _sfx_frame = max(1, _before_seg + int({offset} * FPS)) if _before_seg is not None else None")
            else:
                lines.append(f"    _sfx_frame = None")
        elif ptype == "within_segment":
            target_seg = placement.get("after_segment") or placement.get("target_segment")
            if target_seg:
                lines.append(f"    _t_seg = segment_start_frames.get({target_seg!r})")
                lines.append(f"    _sfx_frame = max(1, _t_seg + int({offset} * FPS)) if _t_seg is not None else None")
            else:
                lines.append(f"    _sfx_frame = None")
        else:
            lines.append(f"    _sfx_frame = None")

        lines.append(f"    if _sfx_frame is not None:")
        lines.append(f"        _sfx_strip = sed.sequences.new_sound(")
        lines.append(f"            name='sfx_{sfx_id}',")
        lines.append(f"            filepath=_sfx_src,")
        lines.append(f"            channel=CH_SFX,")
        lines.append(f"            frame_start=_sfx_frame,")
        lines.append(f"        )")
        if volume_db != 0.0:
            lines.append(f"        _sfx_strip.volume = 10 ** ({volume_db} / 20.0)")
        lines.append(f"    else:")
        lines.append(f"        warnings.append('SFX {sfx_id}: could not resolve frame position')")
        lines.append(f"else:")
        lines.append(f"    warnings.append('SFX {sfx_id}: file not found at {safe_path}')")

    lines.append("")
    return "\n".join(lines) + "\n"


def _blender_place_music(
    manifest: dict,
    project_root: Path,
) -> str:
    """Generate Python code to place background music strips with ducking."""
    music = manifest.get("music", {})
    tracks = music.get("tracks", [])
    if not tracks:
        return "# No music tracks in manifest\n"

    lines: list[str] = []
    lines.append("# ---- Music placement ----")

    for track in tracks:
        track_id = track.get("id", "unknown")
        gen_path = track.get("generated_path")
        if not gen_path:
            lines.append(f"# Music {track_id} skipped: no generated_path")
            continue

        abs_path = str((project_root / gen_path).resolve())
        safe_path = _escape_path_for_python(abs_path)
        placement = track.get("placement", {})
        fade_in = placement.get("fade_in_seconds", 0.0) or 0.0
        fade_out = placement.get("fade_out_seconds", 0.0) or 0.0
        ducking = track.get("ducking_keyframes", [])

        lines.append(f"")
        lines.append(f"# Music track: {track_id}")
        lines.append(f"_mus_src = '{safe_path}'")
        lines.append(f"if os.path.exists(_mus_src):")
        lines.append(f"    _mus_strip = sed.sequences.new_sound(")
        lines.append(f"        name='music_{track_id}',")
        lines.append(f"        filepath=_mus_src,")
        lines.append(f"        channel=CH_MUSIC,")
        lines.append(f"        frame_start=1,")
        lines.append(f"    )")

        # Ducking keyframes
        if ducking:
            lines.append(f"")
            lines.append(f"    # Ducking keyframes")
            for kf in ducking:
                kf_time = kf.get("time", 0.0)
                kf_vol_db = kf.get("volume_db", 0.0)
                lines.append(f"    _mus_strip.volume = 10 ** ({kf_vol_db} / 20.0)")
                lines.append(f"    _mus_strip.keyframe_insert(data_path='volume', frame=int({kf_time} * FPS) + 1)")

        # Fade in
        if fade_in > 0:
            lines.append(f"")
            lines.append(f"    # Fade in over {fade_in}s")
            lines.append(f"    _mus_strip.volume = 0.0")
            lines.append(f"    _mus_strip.keyframe_insert(data_path='volume', frame=1)")
            # Determine target volume from first ducking keyframe, or default -18 dB
            if ducking:
                first_vol_db = ducking[0].get("volume_db", -18.0)
            else:
                first_vol_db = -18.0
            lines.append(f"    _mus_strip.volume = 10 ** ({first_vol_db} / 20.0)")
            lines.append(f"    _mus_strip.keyframe_insert(data_path='volume', frame=int({fade_in} * FPS) + 1)")

        # Fade out
        if fade_out > 0:
            lines.append(f"")
            lines.append(f"    # Fade out over {fade_out}s")
            lines.append(f"    # (frame calculated relative to strip end at save time)")
            lines.append(f"    _mus_end_frame = _mus_strip.frame_final_end")
            lines.append(f"    _fade_out_start = _mus_end_frame - int({fade_out} * FPS)")
            if ducking:
                last_vol_db = ducking[-1].get("volume_db", -18.0)
            else:
                last_vol_db = -18.0
            lines.append(f"    _mus_strip.volume = 10 ** ({last_vol_db} / 20.0)")
            lines.append(f"    _mus_strip.keyframe_insert(data_path='volume', frame=_fade_out_start)")
            lines.append(f"    _mus_strip.volume = 0.0")
            lines.append(f"    _mus_strip.keyframe_insert(data_path='volume', frame=_mus_end_frame)")

        lines.append(f"else:")
        lines.append(f"    warnings.append('Music {track_id}: file not found at {safe_path}')")

    lines.append("")
    return "\n".join(lines) + "\n"


def _blender_place_animations(
    manifest: dict,
    project_root: Path,
    segments_by_id: dict[str, dict],
) -> str:
    """Generate Python code to place animation inserts."""
    animations = manifest.get("animations", [])
    if not animations:
        return "# No animation entries in manifest\n"

    lines: list[str] = []
    lines.append("# ---- Animation inserts ----")

    for anim in animations:
        anim_id = anim.get("id", "unknown")
        if not anim.get("approved", False):
            lines.append(f"# Animation {anim_id} skipped: not approved")
            continue

        rendered_path = anim.get("rendered_path")
        if not rendered_path:
            lines.append(f"# Animation {anim_id} skipped: no rendered_path")
            continue

        abs_path = str((project_root / rendered_path).resolve())
        safe_path = _escape_path_for_python(abs_path)

        placement = anim.get("placement", {})
        placement_type = placement.get("type", "overlay")
        target_seg = placement.get("target_segment")

        lines.append(f"")
        lines.append(f"# Animation: {anim_id} (type={placement_type})")
        lines.append(f"_anim_src = '{safe_path}'")
        lines.append(f"if os.path.exists(_anim_src):")

        if placement_type == "replace_segment" and target_seg:
            lines.append(f"    _target_start = segment_start_frames.get({target_seg!r})")
            lines.append(f"    if _target_start is not None:")
            lines.append(f"        # Mute the original video strip")
            lines.append(f"        _orig = sed.sequences.get('v_{target_seg}')")
            lines.append(f"        if _orig:")
            lines.append(f"            _orig.mute = True")
            lines.append(f"        _anim_strip = sed.sequences.new_movie(")
            lines.append(f"            name='anim_{anim_id}',")
            lines.append(f"            filepath=_anim_src,")
            lines.append(f"            channel=CH_ANIM,")
            lines.append(f"            frame_start=_target_start,")
            lines.append(f"        )")
            # Also add voiceover if available
            vo_path = anim.get("voiceover_path")
            if vo_path:
                abs_vo = str((project_root / vo_path).resolve())
                safe_vo = _escape_path_for_python(abs_vo)
                lines.append(f"        _vo_src = '{safe_vo}'")
                lines.append(f"        if os.path.exists(_vo_src):")
                lines.append(f"            sed.sequences.new_sound(")
                lines.append(f"                name='vo_{anim_id}',")
                lines.append(f"                filepath=_vo_src,")
                lines.append(f"                channel=CH_ANIM + 1,")
                lines.append(f"                frame_start=_target_start,")
                lines.append(f"            )")
            lines.append(f"    else:")
            lines.append(f"        warnings.append('Animation {anim_id}: target segment {target_seg} not placed')")

        elif placement_type == "overlay" and target_seg:
            lines.append(f"    _target_start = segment_start_frames.get({target_seg!r})")
            lines.append(f"    if _target_start is not None:")
            lines.append(f"        _anim_strip = sed.sequences.new_movie(")
            lines.append(f"            name='anim_{anim_id}',")
            lines.append(f"            filepath=_anim_src,")
            lines.append(f"            channel=CH_OVERLAY,")
            lines.append(f"            frame_start=_target_start,")
            lines.append(f"        )")
            lines.append(f"        _anim_strip.blend_type = 'ALPHA_OVER'")
            lines.append(f"    else:")
            lines.append(f"        warnings.append('Animation {anim_id}: target segment {target_seg} not placed')")

        elif placement_type == "insert_after" and target_seg:
            seg = segments_by_id.get(target_seg)
            seg_dur = seg.get("duration", 0.0) if seg else 0.0
            lines.append(f"    _target_start = segment_start_frames.get({target_seg!r})")
            lines.append(f"    if _target_start is not None:")
            lines.append(f"        _insert_at = _target_start + int({seg_dur} * FPS)")
            lines.append(f"        _anim_strip = sed.sequences.new_movie(")
            lines.append(f"            name='anim_{anim_id}',")
            lines.append(f"            filepath=_anim_src,")
            lines.append(f"            channel=CH_ANIM,")
            lines.append(f"            frame_start=_insert_at,")
            lines.append(f"        )")
            vo_path = anim.get("voiceover_path")
            if vo_path:
                abs_vo = str((project_root / vo_path).resolve())
                safe_vo = _escape_path_for_python(abs_vo)
                lines.append(f"        _vo_src = '{safe_vo}'")
                lines.append(f"        if os.path.exists(_vo_src):")
                lines.append(f"            sed.sequences.new_sound(")
                lines.append(f"                name='vo_{anim_id}',")
                lines.append(f"                filepath=_vo_src,")
                lines.append(f"                channel=CH_ANIM + 1,")
                lines.append(f"                frame_start=_insert_at,")
                lines.append(f"            )")
            lines.append(f"    else:")
            lines.append(f"        warnings.append('Animation {anim_id}: target segment {target_seg} not placed')")

        else:
            lines.append(f"    warnings.append('Animation {anim_id}: unsupported placement type {placement_type!r}')")

        lines.append(f"else:")
        lines.append(f"    warnings.append('Animation {anim_id}: file not found at {safe_path}')")

    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Blender script generation: footer (warnings + save)
# ---------------------------------------------------------------------------


def _blender_footer(output_blend_path: str) -> str:
    safe_path = _escape_path_for_python(output_blend_path)
    return textwrap.dedent(f"""\
        # ---- Set scene frame range ----
        scene.frame_start = 1
        # Find last frame across all strips
        _last_frame = 1
        for _s in sed.sequences_all:
            if hasattr(_s, 'frame_final_end'):
                _last_frame = max(_last_frame, _s.frame_final_end)
        scene.frame_end = _last_frame

        # ---- Report warnings ----
        if warnings:
            import sys
            for _w in warnings:
                print(f'BLENDER WARNING: {{_w}}', file=sys.stderr)

        # ---- Save .blend file ----
        bpy.ops.wm.save_as_mainfile(filepath='{safe_path}')
        print(f'Saved: {safe_path}')
    """)


# ---------------------------------------------------------------------------
# Full Blender script assembly per format
# ---------------------------------------------------------------------------


def _get_source_resolution(manifest: dict) -> tuple[int, int] | None:
    """Determine the dominant source resolution from clips.

    Returns (width, height) of the first clip that has resolution info,
    or None if no clips have resolution data.
    """
    for clip in manifest.get("clips", []):
        meta = clip.get("metadata", {})
        w = meta.get("width")
        h = meta.get("height")
        if w and h:
            return (int(w), int(h))
    return None


def generate_blender_script_16x9(
    manifest: dict,
    project_root: Path,
    output_blend_path: str,
) -> str:
    """Generate the full Blender Python script for 16:9 long-form."""
    clips_by_id = _resolve_clips(manifest)
    segments_by_id = _resolve_segments(manifest)
    order = _get_timeline_order(manifest)
    transitions = _get_transitions(manifest)
    res_x, res_y = RESOLUTION_MAP["16x9"]

    parts = [
        _blender_header(res_x, res_y, FPS),
        _blender_place_segments(
            order, segments_by_id, clips_by_id, transitions,
            project_root, apply_crop=False,
        ),
        _blender_place_sfx(manifest, project_root),
        _blender_place_music(manifest, project_root),
        _blender_place_animations(manifest, project_root, segments_by_id),
        _blender_footer(output_blend_path),
    ]
    return "\n".join(parts)


def generate_blender_script_9x16(
    manifest: dict,
    project_root: Path,
    output_blend_path: str,
) -> str:
    """Generate the full Blender Python script for 9:16 long-form."""
    clips_by_id = _resolve_clips(manifest)
    segments_by_id = _resolve_segments(manifest)
    order = _get_timeline_order(manifest)
    transitions = _get_transitions(manifest)
    source_res = _get_source_resolution(manifest)
    res_x, res_y = RESOLUTION_MAP["9x16"]

    parts = [
        _blender_header(res_x, res_y, FPS),
        _blender_place_segments(
            order, segments_by_id, clips_by_id, transitions,
            project_root, apply_crop=True, source_res=source_res,
        ),
        _blender_place_sfx(manifest, project_root),
        _blender_place_music(manifest, project_root),
        _blender_place_animations(manifest, project_root, segments_by_id),
        _blender_footer(output_blend_path),
    ]
    return "\n".join(parts)


def generate_blender_script_short(
    manifest: dict,
    project_root: Path,
    short_entry: dict,
    output_blend_path: str,
) -> str:
    """Generate the full Blender Python script for a single 9:16 short."""
    clips_by_id = _resolve_clips(manifest)
    segments_by_id = _resolve_segments(manifest)
    source_res = _get_source_resolution(manifest)
    res_x, res_y = RESOLUTION_MAP["shorts"]

    short_segments = short_entry.get("segments", [])
    if not short_segments:
        logger.warning(
            "Short %s has no segments, generating empty project",
            short_entry.get("id", "?"),
        )

    # Build a mini-transitions list: cuts between consecutive short segments
    transitions: list[dict] = []
    all_transitions = _get_transitions(manifest)
    for i in range(len(short_segments) - 1):
        tr = _get_transition_for_pair(all_transitions, short_segments[i], short_segments[i + 1])
        if tr:
            transitions.append(tr)
        else:
            transitions.append({
                "from_segment": short_segments[i],
                "to_segment": short_segments[i + 1],
                "type": "cut",
                "duration_seconds": 0.0,
            })

    parts = [
        _blender_header(res_x, res_y, FPS),
        _blender_place_segments(
            short_segments, segments_by_id, clips_by_id, transitions,
            project_root, apply_crop=True, source_res=source_res,
        ),
        # SFX and music are typically not placed in shorts, but we include
        # SFX since they might apply.  Music is skipped for shorts.
        _blender_place_sfx(manifest, project_root),
        "# Music skipped for shorts\n",
        _blender_footer(output_blend_path),
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Blender execution
# ---------------------------------------------------------------------------


def _run_blender(
    blender_path: Path,
    script_path: Path,
    label: str,
) -> bool:
    """Invoke Blender headlessly with the given Python script.

    Returns True on success, False on failure.
    """
    cmd = [
        str(blender_path),
        "--background",
        "--factory-startup",
        "--python",
        str(script_path),
    ]
    logger.info("Running Blender for %s: %s", label, " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BLENDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.error("Blender timed out after %ds for %s", BLENDER_TIMEOUT_SECONDS, label)
        return False
    except FileNotFoundError:
        logger.error("Blender executable not found at %s", blender_path)
        return False
    except OSError as exc:
        logger.error("Failed to execute Blender: %s", exc)
        return False

    # Log Blender output
    if result.stdout:
        for line in result.stdout.splitlines():
            logger.info("[Blender %s stdout] %s", label, line)
    if result.stderr:
        for line in result.stderr.splitlines():
            if "BLENDER WARNING:" in line:
                logger.warning("[Blender %s] %s", label, line)
            else:
                logger.info("[Blender %s stderr] %s", label, line)

    if result.returncode != 0:
        logger.error(
            "Blender exited with code %d for %s. stderr:\n%s",
            result.returncode, label, result.stderr[-2000:] if result.stderr else "(empty)",
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Format builders
# ---------------------------------------------------------------------------


def build_16x9(
    manifest: dict,
    project_root: Path,
    blender_path: Path,
    force: bool,
) -> str | None:
    """Build the 16:9 long-form .blend file. Returns output path or None on failure."""
    outputs = manifest.get("outputs", {})
    long_16_9 = outputs.get("long_16_9", {})
    blend_rel = long_16_9.get("blender_path", "blender/long_16_9.blend")
    blend_abs = str((project_root / blend_rel).resolve())

    if not force and Path(blend_abs).exists():
        logger.info("16x9 blend already exists, skipping (use --force to rebuild)")
        return blend_abs

    script_content = generate_blender_script_16x9(manifest, project_root, blend_abs)
    script_path = project_root / "tmp" / "blender_build_16x9.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(script_content)
    except OSError as exc:
        logger.error("Failed to write Blender script: %s", exc)
        return None

    success = _run_blender(blender_path, script_path, "16x9")
    if not success:
        return None

    if not Path(blend_abs).exists():
        logger.error("Blender completed but .blend file not found at %s", blend_abs)
        return None

    return blend_abs


def build_9x16(
    manifest: dict,
    project_root: Path,
    blender_path: Path,
    force: bool,
) -> str | None:
    """Build the 9:16 long-form .blend file. Returns output path or None on failure."""
    outputs = manifest.get("outputs", {})
    long_9_16 = outputs.get("long_9_16", {})
    blend_rel = long_9_16.get("blender_path", "blender/long_9_16.blend")
    blend_abs = str((project_root / blend_rel).resolve())

    if not force and Path(blend_abs).exists():
        logger.info("9x16 blend already exists, skipping (use --force to rebuild)")
        return blend_abs

    script_content = generate_blender_script_9x16(manifest, project_root, blend_abs)
    script_path = project_root / "tmp" / "blender_build_9x16.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(script_content)
    except OSError as exc:
        logger.error("Failed to write Blender script: %s", exc)
        return None

    success = _run_blender(blender_path, script_path, "9x16")
    if not success:
        return None

    if not Path(blend_abs).exists():
        logger.error("Blender completed but .blend file not found at %s", blend_abs)
        return None

    return blend_abs


def build_shorts(
    manifest: dict,
    project_root: Path,
    blender_path: Path,
    force: bool,
) -> list[dict]:
    """Build 9:16 short .blend files. Returns list of {id, blend_path} dicts."""
    outputs = manifest.get("outputs", {})
    shorts_list = outputs.get("shorts", [])

    if not shorts_list:
        logger.info("No shorts defined in manifest.outputs.shorts, skipping")
        return []

    results: list[dict] = []
    for short_entry in shorts_list:
        short_id = short_entry.get("id", "unknown_short")
        blend_rel = short_entry.get("blender_path", f"blender/{short_id}_9_16.blend")
        blend_abs = str((project_root / blend_rel).resolve())

        if not force and Path(blend_abs).exists():
            logger.info("Short %s blend already exists, skipping", short_id)
            results.append({"id": short_id, "blend_path": blend_abs})
            continue

        script_content = generate_blender_script_short(
            manifest, project_root, short_entry, blend_abs,
        )
        script_path = project_root / "tmp" / f"blender_build_short_{short_id}.py"
        script_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(script_path, "w", encoding="utf-8") as fh:
                fh.write(script_content)
        except OSError as exc:
            logger.error("Failed to write Blender script for short %s: %s", short_id, exc)
            continue

        success = _run_blender(blender_path, script_path, f"short_{short_id}")
        if not success:
            logger.error("Blender build failed for short %s", short_id)
            continue

        if not Path(blend_abs).exists():
            logger.error(
                "Blender completed but .blend file not found for short %s at %s",
                short_id, blend_abs,
            )
            continue

        results.append({"id": short_id, "blend_path": blend_abs})

    return results


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(manifest: dict) -> None:
    """Mark phase 17 as completed in pipeline_state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state = manifest.setdefault("pipeline_state", {})
    phase_results = state.setdefault("phase_results", {})
    completed = state.setdefault("completed_phases", [])

    phase_results["17"] = {
        "status": "success",
        "timestamp": now,
    }

    if 17 not in completed:
        completed.append(17)
        completed.sort()

    current = state.get("current_phase", 0)
    if current < 17:
        state["current_phase"] = 17

    state["last_updated"] = now


def update_manifest_outputs(
    manifest: dict,
    formats_built: list[str],
    blend_paths: dict[str, str | list[dict]],
) -> None:
    """Write the generated .blend paths back into manifest.outputs."""
    outputs = manifest.setdefault("outputs", {})

    if "16x9" in formats_built and "16x9" in blend_paths:
        long_16_9 = outputs.setdefault("long_16_9", {})
        long_16_9["render_status"] = "pending"

    if "9x16" in formats_built and "9x16" in blend_paths:
        long_9_16 = outputs.setdefault("long_9_16", {})
        long_9_16["render_status"] = "pending"

    if "shorts" in formats_built and "shorts" in blend_paths:
        short_results = blend_paths["shorts"]
        if isinstance(short_results, list):
            existing_shorts = outputs.get("shorts", [])
            shorts_by_id = {s.get("id"): s for s in existing_shorts}
            for result in short_results:
                sid = result["id"]
                if sid in shorts_by_id:
                    shorts_by_id[sid]["render_status"] = "pending"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_manifest_for_build(manifest: dict) -> list[str]:
    """Check that the manifest has enough data to build Blender projects.

    Returns a list of error messages (empty if valid).
    """
    errors: list[str] = []

    timeline = manifest.get("timeline")
    if not timeline:
        errors.append("No timeline in manifest. Run build_manifest.py first.")
        return errors

    segments = timeline.get("segments", [])
    if not segments:
        errors.append("Timeline has no segments.")

    order = timeline.get("order", [])
    if not order:
        errors.append("Timeline has no ordered segments (all excluded?).")

    clips = manifest.get("clips", [])
    if not clips:
        errors.append("No clips in manifest.")

    return errors


def _validate_blender(blender_path: Path) -> str | None:
    """Verify Blender executable exists and can report its version.

    Returns an error message or None if valid.
    """
    if not blender_path.is_file():
        return f"Blender not found at {blender_path}"

    try:
        result = subprocess.run(
            [str(blender_path), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"Failed to run Blender --version: {exc}"

    if result.returncode != 0:
        return f"Blender --version returned exit code {result.returncode}"

    logger.info("Blender version: %s", result.stdout.strip().splitlines()[0] if result.stdout else "unknown")
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Blender VSE projects from the footage manifest.",
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Path to the project root containing footage_manifest.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Rebuild .blend files even if they already exist",
    )
    parser.add_argument(
        "--formats",
        type=str,
        default="16x9,9x16,shorts",
        help="Comma-separated list of formats to build (default: 16x9,9x16,shorts)",
    )
    parser.add_argument(
        "--blender-path",
        type=Path,
        default=DEFAULT_BLENDER_PATH,
        help=f"Path to the Blender executable (default: {DEFAULT_BLENDER_PATH})",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        _fatal(f"Project root does not exist: {project_root}")

    # Parse requested formats
    requested_formats = {f.strip() for f in args.formats.split(",")}
    invalid = requested_formats - VALID_FORMATS
    if invalid:
        _fatal(f"Invalid formats: {', '.join(sorted(invalid))}. Valid: {', '.join(sorted(VALID_FORMATS))}")

    # Validate Blender
    blender_error = _validate_blender(args.blender_path)
    if blender_error:
        _fatal(blender_error)

    # Load and validate manifest
    manifest = load_manifest(project_root)
    validation_errors = _validate_manifest_for_build(manifest)
    if validation_errors:
        _fatal("; ".join(validation_errors))

    # Ensure output directories exist
    (project_root / "blender").mkdir(parents=True, exist_ok=True)
    (project_root / "tmp").mkdir(parents=True, exist_ok=True)

    # Build each requested format
    formats_built: list[str] = []
    blend_files: list[str] = []
    blend_paths: dict[str, str | list[dict]] = {}
    errors: list[str] = []

    if "16x9" in requested_formats:
        result = build_16x9(manifest, project_root, args.blender_path, args.force)
        if result:
            formats_built.append("16x9")
            blend_files.append(result)
            blend_paths["16x9"] = result
        else:
            errors.append("16x9 build failed")

    if "9x16" in requested_formats:
        result = build_9x16(manifest, project_root, args.blender_path, args.force)
        if result:
            formats_built.append("9x16")
            blend_files.append(result)
            blend_paths["9x16"] = result
        else:
            errors.append("9x16 build failed")

    if "shorts" in requested_formats:
        short_results = build_shorts(manifest, project_root, args.blender_path, args.force)
        if short_results:
            formats_built.append("shorts")
            blend_paths["shorts"] = short_results
            for sr in short_results:
                blend_files.append(sr["blend_path"])
        else:
            # Not an error if there are simply no shorts defined
            shorts_defined = manifest.get("outputs", {}).get("shorts", [])
            if shorts_defined:
                errors.append("All shorts builds failed")
            else:
                logger.info("No shorts defined in manifest, nothing to build")

    # Update manifest
    if formats_built:
        update_manifest_outputs(manifest, formats_built, blend_paths)
        update_pipeline_state(manifest)
        save_manifest(project_root, manifest)

    # Report
    if not formats_built and errors:
        _fatal(f"No formats built successfully. Errors: {'; '.join(errors)}")

    output = {
        "status": "success",
        "message": f"Built Blender projects for {len(formats_built)} format(s): {', '.join(formats_built)}",
        "details": {
            "formats_built": formats_built,
            "blend_files": blend_files,
        },
    }
    if errors:
        output["details"]["errors"] = errors

    print(json.dumps(output))


if __name__ == "__main__":
    main()
