#!/usr/bin/env python3
"""Merge refined unit manifests back into the main footage manifest.

Reads every ``units/*/footage_manifest.json``, collects updated segments,
SFX, music, animations, and approval state, and writes them back to the
main ``footage_manifest.json``.  This prepares the project for the Blender
assembly phase (Phase 17) which needs one unified manifest.

Usage:
    python3 merge_units.py <project_root> [--force]
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

# ──────────────────────────────────────────────────────────────────────────────
# Manifest I/O
# ──────────────────────────────────────────────────────────────────────────────


def load_manifest(path: Path) -> dict:
    """Load a manifest from *path*, or exit on failure."""
    if not path.exists():
        _fatal(f"Manifest not found at {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        _fatal(f"Failed to read manifest at {path}: {exc}")


def save_manifest(path: Path, manifest: dict) -> None:
    """Atomically write *manifest* to *path*."""
    tmp = path.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        tmp.replace(path)
    except OSError as exc:
        _fatal(f"Failed to write manifest to {path}: {exc}")


def _fatal(msg: str) -> NoReturn:
    print(json.dumps({"status": "error", "message": msg}))
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# Discover unit manifests
# ──────────────────────────────────────────────────────────────────────────────


def discover_units(project_root: Path) -> list[tuple[str, Path, dict]]:
    """Find and load all unit manifests under ``{project_root}/units/``.

    Returns a list of ``(unit_id, unit_dir, unit_manifest)`` tuples sorted
    by unit_id to guarantee deterministic merge order.
    """
    units_dir = project_root / "units"
    if not units_dir.is_dir():
        return []

    found: list[tuple[str, Path, dict]] = []

    for child in sorted(units_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "footage_manifest.json"
        if not manifest_path.is_file():
            print(
                f"WARNING: skipping {child.name} — no footage_manifest.json",
                file=sys.stderr,
            )
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                unit_manifest = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(
                f"WARNING: skipping {child.name} — {exc}",
                file=sys.stderr,
            )
            continue

        unit_info = unit_manifest.get("unit_info", {})
        unit_id = unit_info.get("unit_id", child.name)
        found.append((unit_id, child, unit_manifest))

    return found


# ──────────────────────────────────────────────────────────────────────────────
# Rewrite relative paths from unit → project scope
# ──────────────────────────────────────────────────────────────────────────────


def _rebase_path(rel_path: str | None, unit_dir_rel: str) -> str | None:
    """Rewrite a path relative to a unit dir so it's relative to the project root.

    If the path is None or empty, returns None.
    ``unit_dir_rel`` is e.g. ``"units/unit_001_video_intro"``.
    """
    if not rel_path:
        return None
    # If the path already starts with "units/", leave it alone — it's
    # already project-relative.
    if rel_path.startswith("units/"):
        return rel_path
    return f"{unit_dir_rel}/{rel_path}"


def _rebase_sfx(sfx_list: list[dict], unit_dir_rel: str) -> list[dict]:
    """Adjust generated_path in SFX entries to be project-relative."""
    rebased: list[dict] = []
    for entry in sfx_list:
        entry = dict(entry)  # shallow copy
        gp = entry.get("generated_path")
        if gp:
            entry["generated_path"] = _rebase_path(gp, unit_dir_rel) or gp
        rebased.append(entry)
    return rebased


def _rebase_music(music: dict, unit_dir_rel: str) -> dict:
    """Adjust generated_path in music tracks."""
    music = dict(music)  # shallow copy
    tracks = music.get("tracks", [])
    rebased_tracks: list[dict] = []
    for track in tracks:
        track = dict(track)
        gp = track.get("generated_path")
        if gp:
            track["generated_path"] = _rebase_path(gp, unit_dir_rel) or gp
        rebased_tracks.append(track)
    music["tracks"] = rebased_tracks
    return music


def _rebase_animations(anims: list[dict], unit_dir_rel: str) -> list[dict]:
    """Adjust source_code_path and rendered_path in animation entries."""
    rebased: list[dict] = []
    for entry in anims:
        entry = dict(entry)
        for key in ("source_code_path", "rendered_path", "voiceover_path"):
            val = entry.get(key)
            if val:
                entry[key] = _rebase_path(val, unit_dir_rel) or val
        rebased.append(entry)
    return rebased


# ──────────────────────────────────────────────────────────────────────────────
# Merge logic
# ──────────────────────────────────────────────────────────────────────────────


def merge_units_into_manifest(
    main_manifest: dict,
    units: list[tuple[str, Path, dict]],
) -> dict:
    """Merge data from all unit manifests back into the main manifest.

    Updated fields:
      - timeline.segments  (take refined versions from units)
      - timeline.order     (rebuild from units in order)
      - timeline.transitions (rebuild inter- and intra-unit transitions)
      - sfx[]
      - music.tracks[]
      - animations[]
      - units[] summary statuses
    """
    all_segments: list[dict] = []
    all_sfx: list[dict] = []
    all_music_tracks: list[dict] = []
    all_animations: list[dict] = []
    unit_summaries: list[dict] = []
    warnings: list[str] = []

    # Build lookup of existing segments by id (for segments NOT in any unit)
    existing_seg_ids_in_units: set[str] = set()
    for _, _, umanifest in units:
        for seg in umanifest.get("timeline", {}).get("segments", []):
            existing_seg_ids_in_units.add(seg["id"])

    for unit_id, unit_dir, unit_manifest in units:
        unit_info = unit_manifest.get("unit_info", {})
        unit_dir_rel = f"units/{unit_dir.name}"

        # ── segments ──────────────────────────────────────────────────────
        unit_segments = unit_manifest.get("timeline", {}).get("segments", [])
        all_segments.extend(unit_segments)

        # ── SFX ───────────────────────────────────────────────────────────
        unit_sfx = unit_manifest.get("sfx", [])
        all_sfx.extend(_rebase_sfx(unit_sfx, unit_dir_rel))

        # ── music ─────────────────────────────────────────────────────────
        unit_music = unit_manifest.get("music", {})
        if isinstance(unit_music, dict):
            rebased = _rebase_music(unit_music, unit_dir_rel)
            all_music_tracks.extend(rebased.get("tracks", []))

        # ── animations ────────────────────────────────────────────────────
        unit_anims = unit_manifest.get("animations", [])
        all_animations.extend(_rebase_animations(unit_anims, unit_dir_rel))

        # ── unit summary ──────────────────────────────────────────────────
        total_dur = sum(
            s.get("duration", 0.0) for s in unit_segments
            if s.get("include", True)
        )
        unit_summaries.append({
            "unit_id": unit_id,
            "unit_type": unit_info.get("unit_type", "video"),
            "display_name": unit_info.get("display_name", unit_id),
            "dir": unit_dir_rel,
            "source_clip_id": unit_info.get("source_clip_id", ""),
            "segment_ids": [s["id"] for s in unit_segments],
            "time_range": unit_info.get("time_range", {}),
            "total_duration_seconds": round(total_dur, 4),
            "status": unit_info.get("status", "pending"),
            "approved": unit_info.get("approved", False),
        })

    # ── Include any orphan segments not claimed by a unit ─────────────────
    existing_timeline = main_manifest.get("timeline", {})
    for seg in existing_timeline.get("segments", []):
        if seg["id"] not in existing_seg_ids_in_units:
            all_segments.append(seg)
            warnings.append(f"Segment {seg['id']} not in any unit — kept as-is")

    # ── Rebuild order: all included segments, in unit order ───────────────
    new_order: list[str] = []
    for seg in all_segments:
        if seg.get("include", True):
            new_order.append(seg["id"])

    # ── Rebuild transitions ───────────────────────────────────────────────
    new_transitions = _build_merged_transitions(all_segments, new_order)

    # ── Calculate total duration ──────────────────────────────────────────
    total_dur = sum(
        s.get("duration", 0.0) for s in all_segments
        if s.get("include", True)
    )
    for tr in new_transitions:
        total_dur -= tr.get("duration_seconds", 0.0)
    total_dur = round(max(total_dur, 0.0), 4)

    # ── Write back to manifest ────────────────────────────────────────────
    main_manifest["timeline"] = {
        "segments": all_segments,
        "order": new_order,
        "transitions": new_transitions,
        "total_duration_seconds": total_dur,
    }
    main_manifest["sfx"] = all_sfx
    main_manifest["music"] = {"tracks": all_music_tracks}
    main_manifest["animations"] = all_animations
    main_manifest["units"] = unit_summaries

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = main_manifest.setdefault("pipeline_state", {})
    state["units_merged"] = True
    state["units_merged_at"] = now
    state["last_updated"] = now
    if warnings:
        state.setdefault("warnings", []).extend(warnings)

    return main_manifest


def _build_merged_transitions(
    all_segments: list[dict],
    order: list[str],
) -> list[dict]:
    """Build transitions between consecutive included segments.

    Uses the same heuristic as build_manifest.py:
      - Same clip + continuous  → cut
      - Same clip + gap removed → crossfade (0.5s)
      - Different clips         → fade_black (0.8s)
    """
    if len(order) < 2:
        return []

    seg_by_id: dict[str, dict] = {s["id"]: s for s in all_segments}
    transitions: list[dict] = []

    for i in range(len(order) - 1):
        from_seg = seg_by_id.get(order[i])
        to_seg = seg_by_id.get(order[i + 1])
        if from_seg is None or to_seg is None:
            continue

        from_clip = from_seg["clip_id"]
        to_clip = to_seg["clip_id"]

        if from_clip == to_clip:
            gap = abs(to_seg["in_point"] - from_seg["out_point"])
            if gap < 0.01:
                transitions.append({
                    "from_segment": from_seg["id"],
                    "to_segment": to_seg["id"],
                    "type": "cut",
                    "duration_seconds": 0.0,
                })
            else:
                transitions.append({
                    "from_segment": from_seg["id"],
                    "to_segment": to_seg["id"],
                    "type": "crossfade",
                    "duration_seconds": 0.5,
                })
        else:
            transitions.append({
                "from_segment": from_seg["id"],
                "to_segment": to_seg["id"],
                "type": "fade_black",
                "duration_seconds": 0.8,
            })

    return transitions


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = ArgumentParser(
        description="Merge refined unit manifests into the main project manifest.",
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
        help="Re-merge even if already merged",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        _fatal(f"Project root does not exist: {project_root}")

    main_manifest = load_manifest(project_root / "footage_manifest.json")

    # Check if already merged
    state = main_manifest.get("pipeline_state", {})
    if state.get("units_merged") and not args.force:
        result = {
            "status": "success",
            "message": "Units already merged (use --force to re-merge)",
            "details": {"unit_count": len(main_manifest.get("units", []))},
        }
        print(json.dumps(result))
        return

    # Discover unit manifests
    units = discover_units(project_root)
    if not units:
        _fatal(
            "No unit manifests found under units/. "
            "Run decompose_units.py first."
        )

    print(f"Merging {len(units)} units…", file=sys.stderr)
    for uid, _, _ in units:
        print(f"  → {uid}", file=sys.stderr)

    # Back up the pre-merge timeline
    pre_merge = main_manifest.get("timeline")
    if pre_merge:
        main_manifest["_pre_merge_timeline"] = pre_merge

    # Merge
    main_manifest = merge_units_into_manifest(main_manifest, units)

    # Save
    save_manifest(project_root / "footage_manifest.json", main_manifest)

    # Report
    unit_summaries = main_manifest.get("units", [])
    total_segments = len(main_manifest.get("timeline", {}).get("segments", []))
    total_dur = main_manifest.get("timeline", {}).get("total_duration_seconds", 0.0)

    result = {
        "status": "success",
        "message": (
            f"Merged {len(units)} units → "
            f"{total_segments} segments, {total_dur:.1f}s total"
        ),
        "details": {
            "unit_count": len(units),
            "total_segments": total_segments,
            "total_duration": total_dur,
            "units": [
                {
                    "unit_id": u["unit_id"],
                    "status": u["status"],
                    "approved": u["approved"],
                }
                for u in unit_summaries
            ],
        },
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
