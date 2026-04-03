#!/usr/bin/env python3
"""Generate YouTube thumbnail options using Pillow with text overlay on frames.

Selects the best frames from manifest data (vision analysis, YOLO detections,
scene boundaries) and generates multiple thumbnail style variations for each.

Phase 16 of the footage pipeline.

Usage:
    python3 generate_thumbnail.py <project_root> [--force] [--count 3] [--title "Custom Title"]
"""

import argparse
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print(
        json.dumps({
            "status": "error",
            "message": (
                "Pillow is not installed. Install it with: pip install Pillow"
            ),
        }),
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STYLES = ("bold_text_overlay", "minimal", "dramatic")

# Font search paths — ordered by preference.
LATIN_FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

DEVANAGARI_FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/System/Library/Fonts/Noto Sans Devanagari.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
)

# Devanagari Unicode block range.
DEVANAGARI_START = 0x0900
DEVANAGARI_END = 0x097F

# Default thumbnail config — overridden by style_config.json if present.
DEFAULT_THUMBNAIL_CONFIG = {
    "width": 1280,
    "height": 720,
    "title_font_size": 72,
    "title_stroke_width": 4,
    "title_stroke_color": "#000000",
    "title_position": "center",
    "overlay_opacity": 0.3,
    "overlay_color": "#000000",
}


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest(project_root: Path) -> dict:
    """Load the footage manifest. Exits on failure."""
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.exists():
        print(
            json.dumps({
                "status": "error",
                "message": f"Manifest not found at {manifest_path}",
            }),
        )
        sys.exit(1)

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            json.dumps({
                "status": "error",
                "message": f"Failed to read manifest: {exc}",
            }),
        )
        sys.exit(1)


def save_manifest(project_root: Path, manifest: dict) -> None:
    """Atomically write the manifest back to disk."""
    manifest_path = project_root / "footage_manifest.json"
    tmp_path = manifest_path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp_path.replace(manifest_path)
    except OSError as exc:
        print(
            json.dumps({
                "status": "error",
                "message": f"Failed to write manifest: {exc}",
            }),
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Style config loading
# ---------------------------------------------------------------------------


def load_thumbnail_config(project_root: Path) -> dict:
    """Load thumbnail config from style_config.json, falling back to defaults."""
    config = dict(DEFAULT_THUMBNAIL_CONFIG)

    style_config_path = project_root / "style_config.json"
    if not style_config_path.is_file():
        return config

    try:
        with open(style_config_path, "r", encoding="utf-8") as f:
            full_config = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"WARNING: Failed to read style_config.json, using defaults: {exc}",
            file=sys.stderr,
        )
        return config

    thumb_section = full_config.get("thumbnail")
    if isinstance(thumb_section, dict):
        for key in DEFAULT_THUMBNAIL_CONFIG:
            if key in thumb_section:
                config[key] = thumb_section[key]

    return config


# ---------------------------------------------------------------------------
# Title derivation
# ---------------------------------------------------------------------------


def derive_title(manifest: dict) -> str:
    """Derive thumbnail title text from manifest youtube data or project hint.

    Priority:
    1. youtube.long_form.title
    2. project.hint
    3. "Untitled"
    """
    youtube = manifest.get("youtube")
    if isinstance(youtube, dict):
        long_form = youtube.get("long_form")
        if isinstance(long_form, dict):
            title = long_form.get("title")
            if title and isinstance(title, str) and title.strip():
                return title.strip()

    project = manifest.get("project")
    if isinstance(project, dict):
        hint = project.get("hint")
        if hint and isinstance(hint, str) and hint.strip():
            return hint.strip()

    return "Untitled"


# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------


def _contains_devanagari(text: str) -> bool:
    """Check whether a string contains any Devanagari characters."""
    return any(DEVANAGARI_START <= ord(ch) <= DEVANAGARI_END for ch in text)


def _try_load_font(paths: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont | None:
    """Try loading a font from the first existing path in *paths*."""
    for font_path in paths:
        if Path(font_path).is_file():
            try:
                return ImageFont.truetype(font_path, size)
            except OSError:
                continue
    return None


def load_font(size: int, text: str) -> ImageFont.FreeTypeFont:
    """Load the best available font for *text* at the given size.

    Falls back to Pillow's built-in default bitmap font when no system
    font can be loaded.
    """
    if _contains_devanagari(text):
        font = _try_load_font(DEVANAGARI_FONT_PATHS, size)
        if font is not None:
            return font
        # Fall through to Latin fonts — at least the Latin portions render.
        print(
            "WARNING: No Devanagari font found; Devanagari glyphs may not render correctly",
            file=sys.stderr,
        )

    font = _try_load_font(LATIN_FONT_PATHS, size)
    if font is not None:
        return font

    # Ultimate fallback.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Older Pillow versions do not accept a size parameter.
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Frame scoring and selection
# ---------------------------------------------------------------------------


def _score_frame_vision(
    frame_path: str,
    vision_analyses: list[dict],
) -> dict | None:
    """Find and return a vision analysis entry matching *frame_path*."""
    for analysis in vision_analyses:
        if analysis.get("frame_path") == frame_path:
            return analysis
    return None


def _person_facing_camera(
    frame_path: str,
    yolo_data: dict,
) -> bool:
    """Return True if YOLO detected a person facing the camera in *frame_path*."""
    detections_by_frame = yolo_data.get("detections_by_frame", {})
    detections = detections_by_frame.get(frame_path, [])
    for det in detections:
        if det.get("class_id") == 0 and det.get("class") == "person":
            pose = det.get("pose")
            if isinstance(pose, dict) and pose.get("facing") == "camera":
                return True
    return False


def _has_person(frame_path: str, yolo_data: dict) -> bool:
    """Return True if YOLO detected any person in *frame_path*."""
    detections_by_frame = yolo_data.get("detections_by_frame", {})
    detections = detections_by_frame.get(frame_path, [])
    for det in detections:
        if det.get("class_id") == 0 and det.get("class") == "person":
            return True
    return False


def _score_frame(
    frame_entry: dict,
    clip: dict,
) -> float:
    """Compute a composite score for a single frame entry.

    Higher is better.  Score components:
    - interest_score from vision (0-1, weight 3.0)
    - quality_score from vision (0-1, weight 1.5)
    - person facing camera from YOLO (boolean, weight 2.0)
    - person present from YOLO (boolean, weight 1.0)
    - scene_start/scene_boundary reason bonus (weight 0.5)
    """
    score = 0.0
    frame_path = frame_entry.get("path", "")

    # Vision data.
    vision = clip.get("vision")
    if isinstance(vision, dict):
        analyses = vision.get("analyses", [])
        if isinstance(analyses, list):
            va = _score_frame_vision(frame_path, analyses)
            if va is not None:
                interest = va.get("interest_score")
                if isinstance(interest, (int, float)):
                    score += float(interest) * 3.0
                quality = va.get("quality_score")
                if isinstance(quality, (int, float)):
                    score += float(quality) * 1.5

    # YOLO data.
    yolo = clip.get("yolo")
    if isinstance(yolo, dict):
        if _person_facing_camera(frame_path, yolo):
            score += 2.0
        elif _has_person(frame_path, yolo):
            score += 1.0

    # Reason bonus.
    reason = frame_entry.get("reason", "")
    if reason in ("scene_start", "scene_boundary"):
        score += 0.5

    return score


def select_best_frames(
    manifest: dict,
    count: int,
) -> list[dict]:
    """Select the best *count* frames across all clips.

    Returns a list of dicts with keys: path, time, clip_id, score.
    Ensures variety by not picking frames within 5 seconds of each other
    from the same clip.
    """
    clips = manifest.get("clips", [])
    if not clips:
        return []

    # Strategy 1: score all frames using vision + YOLO data.
    all_scored: list[dict] = []
    has_vision = False

    for clip in clips:
        clip_id = clip.get("id", "unknown")
        frames = clip.get("frames")
        if not isinstance(frames, dict):
            continue
        extracted = frames.get("extracted", [])
        if not isinstance(extracted, list):
            continue

        vision = clip.get("vision")
        if isinstance(vision, dict) and vision.get("analyses"):
            has_vision = True

        for frame_entry in extracted:
            frame_path = frame_entry.get("path", "")
            if not frame_path:
                continue
            score = _score_frame(frame_entry, clip)
            all_scored.append({
                "path": frame_path,
                "time": frame_entry.get("time", 0.0),
                "clip_id": clip_id,
                "score": score,
            })

    if not all_scored:
        return _fallback_frame_selection(manifest, count)

    # Sort descending by score.
    all_scored.sort(key=lambda f: f["score"], reverse=True)

    # Pick top frames enforcing variety: no two frames within 5s of each
    # other from the same clip.
    selected: list[dict] = []
    min_time_gap = 5.0

    for candidate in all_scored:
        if len(selected) >= count:
            break

        too_close = False
        for already in selected:
            if (
                already["clip_id"] == candidate["clip_id"]
                and abs(already["time"] - candidate["time"]) < min_time_gap
            ):
                too_close = True
                break
        if not too_close:
            selected.append(candidate)

    # If we still don't have enough (rare), relax the time constraint.
    if len(selected) < count:
        for candidate in all_scored:
            if len(selected) >= count:
                break
            if candidate not in selected:
                selected.append(candidate)

    return selected[:count]


def _fallback_frame_selection(
    manifest: dict,
    count: int,
) -> list[dict]:
    """Fallback frame selection when no vision/YOLO data is available.

    Strategy:
    1. Scene start frames
    2. Frames with YOLO person detections
    3. Periodic frames from the middle of clips
    """
    clips = manifest.get("clips", [])
    candidates: list[dict] = []

    for clip in clips:
        clip_id = clip.get("id", "unknown")
        frames = clip.get("frames")
        if not isinstance(frames, dict):
            continue
        extracted = frames.get("extracted", [])
        if not isinstance(extracted, list) or not extracted:
            continue

        yolo = clip.get("yolo")

        # Prefer scene start frames.
        for frame_entry in extracted:
            reason = frame_entry.get("reason", "")
            frame_path = frame_entry.get("path", "")
            if not frame_path:
                continue

            score = 0.0
            if reason in ("scene_start", "scene_boundary"):
                score += 2.0
            if isinstance(yolo, dict) and _has_person(frame_path, yolo):
                score += 1.5
                if _person_facing_camera(frame_path, yolo):
                    score += 1.0

            candidates.append({
                "path": frame_path,
                "time": frame_entry.get("time", 0.0),
                "clip_id": clip_id,
                "score": score,
            })

    if not candidates:
        # Absolute fallback: pick periodic frames from the middle of clips.
        return _periodic_fallback(manifest, count)

    candidates.sort(key=lambda f: f["score"], reverse=True)

    # Enforce variety.
    selected: list[dict] = []
    min_time_gap = 5.0
    for candidate in candidates:
        if len(selected) >= count:
            break
        too_close = any(
            s["clip_id"] == candidate["clip_id"]
            and abs(s["time"] - candidate["time"]) < min_time_gap
            for s in selected
        )
        if not too_close:
            selected.append(candidate)

    if len(selected) < count:
        for candidate in candidates:
            if len(selected) >= count:
                break
            if candidate not in selected:
                selected.append(candidate)

    return selected[:count]


def _periodic_fallback(
    manifest: dict,
    count: int,
) -> list[dict]:
    """Pick frames from around the middle of each clip's extracted frames."""
    clips = manifest.get("clips", [])
    selected: list[dict] = []

    for clip in clips:
        clip_id = clip.get("id", "unknown")
        frames = clip.get("frames")
        if not isinstance(frames, dict):
            continue
        extracted = frames.get("extracted", [])
        if not isinstance(extracted, list) or not extracted:
            continue

        # Pick frame(s) from the middle third.
        n = len(extracted)
        start_idx = n // 3
        end_idx = max(start_idx + 1, 2 * n // 3)
        middle_frames = extracted[start_idx:end_idx]

        # Take evenly spaced frames from the middle third.
        picks_from_clip = max(1, count - len(selected))
        step = max(1, len(middle_frames) // picks_from_clip)
        for i in range(0, len(middle_frames), step):
            if len(selected) >= count:
                break
            entry = middle_frames[i]
            frame_path = entry.get("path", "")
            if frame_path:
                selected.append({
                    "path": frame_path,
                    "time": entry.get("time", 0.0),
                    "clip_id": clip_id,
                    "score": 0.0,
                })

    return selected[:count]


# ---------------------------------------------------------------------------
# Color parsing
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse a '#RRGGBB' string into an (R, G, B) tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (0, 0, 0)
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b)
    except ValueError:
        return (0, 0, 0)


# ---------------------------------------------------------------------------
# Text drawing helpers
# ---------------------------------------------------------------------------


def _wrap_text(text: str, max_chars_per_line: int) -> list[str]:
    """Wrap text into lines, capped at 3 lines max."""
    lines = textwrap.wrap(text, width=max_chars_per_line)
    if len(lines) > 3:
        # Truncate to 3 lines, add ellipsis to the last.
        lines = lines[:3]
        if len(lines[2]) > 3:
            lines[2] = lines[2][:-3] + "..."
    return lines if lines else [text]


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    position: tuple[int, int],
    text_color: tuple[int, int, int],
    stroke_width: int,
    stroke_color: tuple[int, int, int],
    anchor: str = "mm",
    line_spacing: int = 10,
) -> None:
    """Draw multiple lines of text with stroke, centered on *position*.

    anchor 'mm' = middle-center, 'lm' = left-middle, etc.
    """
    # Calculate total block height.
    line_heights = []
    for line in lines:
        bbox = font.getbbox(line)
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + line_spacing * (len(lines) - 1)
    x, y = position

    # Determine starting y so the block is centered on the given position.
    if anchor.startswith("m") or anchor.endswith("m"):
        current_y = y - total_height // 2
    else:
        current_y = y

    for i, line in enumerate(lines):
        line_anchor = anchor
        draw.text(
            (x, current_y + line_heights[i] // 2),
            line,
            font=font,
            fill=text_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
            anchor=line_anchor,
        )
        current_y += line_heights[i] + line_spacing


# ---------------------------------------------------------------------------
# Thumbnail generation — one per style
# ---------------------------------------------------------------------------


def _generate_bold_text_overlay(
    source_img: Image.Image,
    title_text: str,
    config: dict,
) -> Image.Image:
    """Bold text overlay style: semi-transparent overlay + large centered text."""
    width = config["width"]
    height = config["height"]
    img = source_img.copy().resize((width, height), Image.LANCZOS)
    img = img.convert("RGBA")

    # Semi-transparent dark overlay.
    overlay_rgb = _hex_to_rgb(config.get("overlay_color", "#000000"))
    overlay_alpha = int(255 * config.get("overlay_opacity", 0.3))
    overlay = Image.new("RGBA", img.size, (*overlay_rgb, overlay_alpha))
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)

    font_size = config.get("title_font_size", 72)
    font = load_font(font_size, title_text)
    stroke_width = config.get("title_stroke_width", 4)
    stroke_color = _hex_to_rgb(config.get("title_stroke_color", "#000000"))

    lines = _wrap_text(title_text, max_chars_per_line=20)
    center_x = width // 2
    center_y = height // 2

    _draw_text_block(
        draw,
        lines,
        font,
        position=(center_x, center_y),
        text_color=(255, 255, 255),
        stroke_width=stroke_width,
        stroke_color=stroke_color,
        anchor="mm",
    )

    return img.convert("RGB")


def _generate_minimal(
    source_img: Image.Image,
    title_text: str,
    config: dict,
) -> Image.Image:
    """Minimal style: small text in bottom-left corner, no overlay."""
    width = config["width"]
    height = config["height"]
    img = source_img.copy().resize((width, height), Image.LANCZOS)
    img = img.convert("RGBA")

    draw = ImageDraw.Draw(img)

    # Smaller font for minimal style.
    font_size = max(24, config.get("title_font_size", 72) // 2)
    font = load_font(font_size, title_text)
    stroke_width = max(1, config.get("title_stroke_width", 4) // 2)
    stroke_color = _hex_to_rgb(config.get("title_stroke_color", "#000000"))

    lines = _wrap_text(title_text, max_chars_per_line=30)

    # Position: bottom-left with padding.
    padding = 40
    x = padding
    y = height - padding

    # Draw from bottom up.
    line_spacing = 6
    line_heights = []
    for line in lines:
        bbox = font.getbbox(line)
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + line_spacing * (len(lines) - 1)
    current_y = y - total_height

    for i, line in enumerate(lines):
        draw.text(
            (x, current_y),
            line,
            font=font,
            fill=(255, 255, 255),
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
            anchor="lt",
        )
        current_y += line_heights[i] + line_spacing

    return img.convert("RGB")


def _generate_dramatic(
    source_img: Image.Image,
    title_text: str,
    config: dict,
) -> Image.Image:
    """Dramatic style: full dark gradient overlay, large text, high contrast."""
    width = config["width"]
    height = config["height"]
    img = source_img.copy().resize((width, height), Image.LANCZOS)
    img = img.convert("RGBA")

    # Full gradient overlay: heavy at bottom, lighter at top.
    # Build row-by-row for performance (putpixel per-pixel is too slow).
    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for y_pos in range(height):
        # Opacity increases from top to bottom: 30 -> 200.
        alpha = int(30 + (200 - 30) * (y_pos / height))
        row = Image.new("RGBA", (width, 1), (0, 0, 0, alpha))
        gradient.paste(row, (0, y_pos))

    img = Image.alpha_composite(img, gradient)

    draw = ImageDraw.Draw(img)

    # Larger font for dramatic style.
    font_size = int(config.get("title_font_size", 72) * 1.3)
    font = load_font(font_size, title_text)
    stroke_width = max(3, config.get("title_stroke_width", 4) + 2)
    stroke_color = _hex_to_rgb(config.get("title_stroke_color", "#000000"))

    lines = _wrap_text(title_text, max_chars_per_line=16)

    # Position: lower-center.
    center_x = width // 2
    y_pos = int(height * 0.70)

    _draw_text_block(
        draw,
        lines,
        font,
        position=(center_x, y_pos),
        text_color=(255, 255, 255),
        stroke_width=stroke_width,
        stroke_color=stroke_color,
        anchor="mm",
    )

    return img.convert("RGB")


# Use a dict dispatch instead of if/elif chains.
STYLE_GENERATORS = {
    "bold_text_overlay": _generate_bold_text_overlay,
    "minimal": _generate_minimal,
    "dramatic": _generate_dramatic,
}


# ---------------------------------------------------------------------------
# Thumbnail generation orchestrator
# ---------------------------------------------------------------------------


def generate_thumbnails(
    project_root: Path,
    manifest: dict,
    title_text: str,
    count: int,
    config: dict,
) -> list[dict]:
    """Generate thumbnail images and return manifest entries for each.

    For each of the *count* best frames, generates one thumbnail per style
    (bold_text_overlay, minimal, dramatic).
    """
    thumbs_dir = project_root / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    selected_frames = select_best_frames(manifest, count)
    if not selected_frames:
        print(
            "WARNING: No frames available for thumbnail generation",
            file=sys.stderr,
        )
        return []

    thumbnail_entries: list[dict] = []
    thumb_index = 1

    for frame_info in selected_frames:
        frame_rel_path = frame_info["path"]
        frame_abs_path = project_root / frame_rel_path

        if not frame_abs_path.is_file():
            print(
                f"WARNING: Frame file not found, skipping: {frame_abs_path}",
                file=sys.stderr,
            )
            continue

        try:
            source_img = Image.open(frame_abs_path)
        except (OSError, Image.UnidentifiedImageError) as exc:
            print(
                f"WARNING: Cannot open frame {frame_abs_path}, skipping: {exc}",
                file=sys.stderr,
            )
            continue

        for style in STYLES:
            generator = STYLE_GENERATORS.get(style)
            if generator is None:
                print(
                    f"WARNING: Unknown style '{style}', skipping",
                    file=sys.stderr,
                )
                continue

            thumb_id = f"thumb_{thumb_index:03d}"
            thumb_filename = f"{thumb_id}.png"
            thumb_abs_path = thumbs_dir / thumb_filename
            thumb_rel_path = f"thumbnails/{thumb_filename}"

            try:
                result_img = generator(source_img, title_text, config)
            except Exception as exc:
                print(
                    f"WARNING: Failed to generate {style} thumbnail from "
                    f"{frame_rel_path}: {exc}",
                    file=sys.stderr,
                )
                continue

            try:
                result_img.save(thumb_abs_path, format="PNG")
            except OSError as exc:
                print(
                    f"WARNING: Failed to save thumbnail {thumb_abs_path}: {exc}",
                    file=sys.stderr,
                )
                continue

            # Verify the file was written and has content.
            if not thumb_abs_path.is_file():
                print(
                    f"WARNING: Thumbnail file not created: {thumb_abs_path}",
                    file=sys.stderr,
                )
                continue

            file_size = thumb_abs_path.stat().st_size
            if file_size == 0:
                print(
                    f"WARNING: Thumbnail file is empty (0 bytes), removing: "
                    f"{thumb_abs_path}",
                    file=sys.stderr,
                )
                thumb_abs_path.unlink(missing_ok=True)
                continue

            thumbnail_entries.append({
                "id": thumb_id,
                "path": thumb_rel_path,
                "source_frame": frame_rel_path,
                "title_text": title_text,
                "subtitle_text": "",
                "style": style,
                "resolution": {
                    "w": config["width"],
                    "h": config["height"],
                },
                "selected": False,
            })

            thumb_index += 1

    return thumbnail_entries


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(
    manifest: dict,
    thumbnails_generated: int,
    warnings: list[str],
) -> None:
    """Mark phase 16 as complete in pipeline_state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if "pipeline_state" not in manifest:
        manifest["pipeline_state"] = {
            "current_phase": 16,
            "completed_phases": [],
            "phase_results": {},
            "errors": [],
            "warnings": [],
            "last_updated": now,
        }

    state = manifest["pipeline_state"]

    state.setdefault("phase_results", {})["16"] = {
        "status": "success",
        "timestamp": now,
        "thumbnails_generated": thumbnails_generated,
    }

    completed = state.setdefault("completed_phases", [])
    if 16 not in completed:
        completed.append(16)
        completed.sort()

    if state.get("current_phase", 0) <= 16:
        state["current_phase"] = 17

    existing_warnings = state.setdefault("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)

    state["last_updated"] = now


# ---------------------------------------------------------------------------
# Existing thumbnail check
# ---------------------------------------------------------------------------


def thumbnails_already_exist(manifest: dict, project_root: Path) -> bool:
    """Return True if the manifest already has thumbnail entries with files on disk."""
    thumbnails = manifest.get("thumbnails")
    if not isinstance(thumbnails, list) or not thumbnails:
        return False

    # Verify at least one thumbnail file actually exists.
    for entry in thumbnails:
        thumb_path = entry.get("path", "")
        if thumb_path and (project_root / thumb_path).is_file():
            return True

    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate YouTube thumbnail options using Pillow with text "
            "overlay on selected frames."
        ),
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Path to the project root directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Regenerate thumbnails even if they already exist",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of best source frames to use (default: 3)",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Override title text (default: derive from manifest youtube data or hint)",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        output = {
            "status": "error",
            "message": f"Project root does not exist: {project_root}",
            "details": {"thumbnails_generated": 0, "styles": []},
        }
        print(json.dumps(output))
        return 1

    if args.count < 1:
        output = {
            "status": "error",
            "message": f"--count must be at least 1, got {args.count}",
            "details": {"thumbnails_generated": 0, "styles": []},
        }
        print(json.dumps(output))
        return 1

    manifest = load_manifest(project_root)

    # Check if thumbnails already exist.
    if not args.force and thumbnails_already_exist(manifest, project_root):
        existing_count = len(manifest.get("thumbnails", []))
        output = {
            "status": "success",
            "message": (
                f"Thumbnails already exist ({existing_count} found). "
                f"Use --force to regenerate."
            ),
            "details": {
                "thumbnails_generated": 0,
                "styles": [],
                "existing_thumbnails": existing_count,
            },
        }
        print(json.dumps(output))
        return 0

    # Derive title.
    title_text = args.title if args.title else derive_title(manifest)

    # Load thumbnail style config.
    config = load_thumbnail_config(project_root)

    # Generate thumbnails.
    warnings: list[str] = []
    thumbnail_entries = generate_thumbnails(
        project_root,
        manifest,
        title_text,
        args.count,
        config,
    )

    if not thumbnail_entries:
        output = {
            "status": "error",
            "message": (
                "No thumbnails could be generated. Check that frames have been "
                "extracted (phase 7) and frame files exist on disk."
            ),
            "details": {"thumbnails_generated": 0, "styles": []},
        }
        print(json.dumps(output))
        return 1

    # Update manifest.
    manifest["thumbnails"] = thumbnail_entries

    generated_styles = sorted(set(entry["style"] for entry in thumbnail_entries))

    update_pipeline_state(manifest, len(thumbnail_entries), warnings)
    save_manifest(project_root, manifest)

    output = {
        "status": "success",
        "message": (
            f"Generated {len(thumbnail_entries)} thumbnails from "
            f"{args.count} source frames"
        ),
        "details": {
            "thumbnails_generated": len(thumbnail_entries),
            "styles": generated_styles,
        },
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
