#!/usr/bin/env python3
"""Delete temporary files from a footage project while preserving deliverables.

Phase 20 of the footage pipeline.

Usage:
    python3 cleanup.py <project_root> [--dry-run] [--keep-frames] [--keep-analysis]
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest(project_root: Path) -> dict:
    """Load and return the footage manifest. Exits on failure."""
    manifest_path = project_root / "footage_manifest.json"
    if not manifest_path.is_file():
        print(
            json.dumps({
                "status": "error",
                "message": f"Manifest not found at {manifest_path}",
                "details": {"deleted_dirs": [], "freed_bytes": 0, "dry_run": False},
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
                "details": {"deleted_dirs": [], "freed_bytes": 0, "dry_run": False},
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
        print(f"Failed to write manifest: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Safety check
# ---------------------------------------------------------------------------


def is_safe_path(target: Path, project_root: Path) -> bool:
    """Return True only if target is strictly within project_root.

    Resolves symlinks to prevent directory traversal attacks.
    """
    try:
        resolved_target = target.resolve()
        resolved_root = project_root.resolve()
        # The target must be the root itself or a child of it.
        # We only delete children, never the root itself.
        return resolved_target != resolved_root and (
            resolved_target == resolved_root
            or str(resolved_target).startswith(str(resolved_root) + "/")
        )
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Size calculation
# ---------------------------------------------------------------------------


def get_directory_size(dir_path: Path) -> int:
    """Calculate total size of all files in a directory tree, in bytes.

    Returns 0 if the directory does not exist or is not accessible.
    Follows symlinks for size calculation but only counts regular files.
    """
    if not dir_path.is_dir():
        return 0

    total = 0
    try:
        for entry in dir_path.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                # Skip files we cannot stat (permissions, broken symlinks, etc.)
                continue
    except OSError:
        pass

    return total


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def delete_directory(
    dir_path: Path,
    project_root: Path,
    dry_run: bool,
    deleted_dirs: list[str],
    warnings: list[str],
) -> int:
    """Delete a directory and return the bytes freed.

    In dry-run mode, calculates size but does not delete.
    Appends the relative path to deleted_dirs on success.
    """
    if not dir_path.is_dir():
        return 0

    if not is_safe_path(dir_path, project_root):
        msg = f"Refusing to delete path outside project root: {dir_path}"
        print(msg, file=sys.stderr)
        warnings.append(msg)
        return 0

    size = get_directory_size(dir_path)

    # Compute relative path for reporting
    try:
        rel_path = str(dir_path.relative_to(project_root))
    except ValueError:
        rel_path = str(dir_path)

    if dry_run:
        deleted_dirs.append(rel_path)
        return size

    try:
        shutil.rmtree(dir_path)
        deleted_dirs.append(rel_path)
        return size
    except PermissionError as exc:
        msg = f"Permission denied deleting {rel_path}: {exc}"
        print(msg, file=sys.stderr)
        warnings.append(msg)
        return 0
    except OSError as exc:
        msg = f"Error deleting {rel_path}: {exc}"
        print(msg, file=sys.stderr)
        warnings.append(msg)
        return 0


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(
    manifest: dict,
    deleted_dirs: list[str],
    freed_bytes: int,
    dry_run: bool,
) -> None:
    """Mark phase 20 as complete in pipeline_state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state = manifest.setdefault("pipeline_state", {
        "current_phase": 20,
        "completed_phases": [],
        "phase_results": {},
        "errors": [],
        "warnings": [],
        "last_updated": now,
    })

    phase_results = state.setdefault("phase_results", {})
    phase_results["20"] = {
        "status": "success",
        "timestamp": now,
        "deleted_dirs": deleted_dirs,
        "freed_bytes": freed_bytes,
        "dry_run": dry_run,
    }

    if not dry_run:
        completed = state.setdefault("completed_phases", [])
        if 20 not in completed:
            completed.append(20)
            completed.sort()

    current = state.get("current_phase", 0)
    if current <= 20 and not dry_run:
        state["current_phase"] = 21

    state["last_updated"] = now


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete temporary files from a footage project.",
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Path to the project root directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="Do not delete extracted frames",
    )
    parser.add_argument(
        "--keep-analysis",
        action="store_true",
        help="Do not delete analysis JSON files",
    )
    parser.add_argument(
        "--keep-units",
        action="store_true",
        help="Do not delete unit directories (units/*/tmp/ is still cleaned)",
    )
    parser.add_argument(
        "--keep-exports",
        action="store_true",
        help="Do not delete FCPXML exports (exports/ directory)",
    )
    args = parser.parse_args()

    project_root: Path = args.project_root.resolve()
    if not project_root.is_dir():
        print(
            json.dumps({
                "status": "error",
                "message": f"Project root does not exist: {project_root}",
                "details": {"deleted_dirs": [], "freed_bytes": 0, "dry_run": args.dry_run},
            }),
        )
        sys.exit(1)

    manifest = load_manifest(project_root)

    deleted_dirs: list[str] = []
    warnings: list[str] = []
    freed_bytes = 0

    # 1. Always delete tmp/
    tmp_dir = project_root / "tmp"
    freed_bytes += delete_directory(
        tmp_dir, project_root, args.dry_run, deleted_dirs, warnings,
    )

    # 2. Conditionally delete frames/
    if not args.keep_frames:
        frames_dir = project_root / "frames"
        freed_bytes += delete_directory(
            frames_dir, project_root, args.dry_run, deleted_dirs, warnings,
        )

    # 3. Conditionally delete analysis/
    if not args.keep_analysis:
        analysis_dir = project_root / "analysis"
        freed_bytes += delete_directory(
            analysis_dir, project_root, args.dry_run, deleted_dirs, warnings,
        )

    # 4. Conditionally delete exports/
    if not args.keep_exports:
        exports_dir = project_root / "exports"
        freed_bytes += delete_directory(
            exports_dir, project_root, args.dry_run, deleted_dirs, warnings,
        )

    # 5. Handle units/ — either delete entirely or clean each unit's tmp/
    units_dir = project_root / "units"
    if units_dir.is_dir():
        if not args.keep_units:
            freed_bytes += delete_directory(
                units_dir, project_root, args.dry_run, deleted_dirs, warnings,
            )
        else:
            # Clean tmp/ inside each unit directory
            for child in sorted(units_dir.iterdir()):
                if child.is_dir():
                    unit_tmp = child / "tmp"
                    freed_bytes += delete_directory(
                        unit_tmp, project_root, args.dry_run, deleted_dirs, warnings,
                    )

    # Update pipeline state (only if not dry-run, but record phase result either way)
    update_pipeline_state(manifest, deleted_dirs, freed_bytes, args.dry_run)

    # Only save manifest if we actually modified something (or dry-run pipeline state update)
    save_manifest(project_root, manifest)

    # Build output message
    if args.dry_run:
        if deleted_dirs:
            message = (
                f"Dry run: would delete {len(deleted_dirs)} directories, "
                f"freeing ~{freed_bytes:,} bytes"
            )
        else:
            message = "Dry run: nothing to delete"
    else:
        if deleted_dirs:
            message = (
                f"Deleted {len(deleted_dirs)} directories, "
                f"freed {freed_bytes:,} bytes"
            )
        else:
            message = "Nothing to delete (directories already clean)"

    output = {
        "status": "success",
        "message": message,
        "details": {
            "deleted_dirs": deleted_dirs,
            "freed_bytes": freed_bytes,
            "dry_run": args.dry_run,
        },
    }

    if warnings:
        output["details"]["warnings"] = warnings

    print(json.dumps(output))


if __name__ == "__main__":
    main()
