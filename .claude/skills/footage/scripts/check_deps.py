#!/usr/bin/env python3
"""
Dependency verification script for the footage processing pipeline.

Checks all required tools and Python packages, optionally initializes
a project directory with the standard structure and manifest.

Usage:
    python3 check_deps.py [project_root]

Exit codes:
    0 - All critical dependencies present
    1 - One or more critical dependencies missing
"""

import importlib
import json
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STYLE_CONFIG_TEMPLATE = TEMPLATES_DIR / "style_config_default.json"

PROJECT_SUBDIRS = [
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
    "exports",
    "units",
    "tmp",
]

BLENDER_MACOS_PATH = Path("/Applications/Blender.app/Contents/MacOS/Blender")
BLENDER_MIN_MAJOR = 4

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a command, returning the CompletedProcess. Never raises on failure."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr="not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="timeout")
    except Exception as exc:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr=str(exc))


def _which(name: str) -> str | None:
    """Return the absolute path to *name* on PATH, or None."""
    result = _run(["which", name])
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _extract_version(text: str) -> str | None:
    """Best-effort extraction of a semver-ish version string from arbitrary text."""
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Tool checks
# ---------------------------------------------------------------------------


def check_ffmpeg() -> dict:
    """Check for ffmpeg availability and version."""
    path = _which("ffmpeg")
    if path is None:
        return {"available": False, "path": None, "version": None, "error": "ffmpeg not found on PATH"}

    result = _run(["ffmpeg", "-version"])
    version = _extract_version(result.stdout) if result.returncode == 0 else None
    return {"available": True, "path": path, "version": version, "error": None}


def check_ffprobe() -> dict:
    """Check for ffprobe availability and version."""
    path = _which("ffprobe")
    if path is None:
        return {"available": False, "path": None, "version": None, "error": "ffprobe not found on PATH"}

    result = _run(["ffprobe", "-version"])
    version = _extract_version(result.stdout) if result.returncode == 0 else None
    return {"available": True, "path": path, "version": version, "error": None}


def check_blender() -> dict:
    """
    Check for Blender >= 4.x.

    On macOS, first tries the standard .app bundle path. Falls back to PATH.
    """
    blender_path: str | None = None

    if platform.system() == "Darwin" and BLENDER_MACOS_PATH.is_file():
        blender_path = str(BLENDER_MACOS_PATH)
    else:
        blender_path = _which("blender")

    if blender_path is None:
        return {"available": False, "path": None, "version": None, "error": "Blender not found"}

    result = _run([blender_path, "--version"])
    version = _extract_version(result.stdout) if result.returncode == 0 else None

    if version is not None:
        try:
            major = int(version.split(".")[0])
        except (ValueError, IndexError):
            major = 0
        if major < BLENDER_MIN_MAJOR:
            return {
                "available": False,
                "path": blender_path,
                "version": version,
                "error": f"Blender {version} found but >= {BLENDER_MIN_MAJOR}.x required",
            }

    return {"available": True, "path": blender_path, "version": version, "error": None}


def check_npx() -> dict:
    """Check for npx (Node.js) availability."""
    path = _which("npx")
    if path is None:
        return {"available": False, "path": None, "version": None, "error": "npx not found on PATH"}

    result = _run(["npx", "--version"])
    version = result.stdout.strip() if result.returncode == 0 else None
    return {"available": True, "path": path, "version": version, "error": None}


# ---------------------------------------------------------------------------
# Python package checks
# ---------------------------------------------------------------------------


def check_python_package(import_name: str) -> dict:
    """
    Attempt to import *import_name* and report availability + version.

    Uses importlib so we never pollute the module namespace with unused imports.
    """
    try:
        mod = importlib.import_module(import_name)
    except ImportError as exc:
        return {"available": False, "version": None, "error": str(exc)}
    except Exception as exc:
        return {"available": False, "version": None, "error": f"unexpected error: {exc}"}

    version = getattr(mod, "__version__", None)
    # Some packages expose version under a nested attribute
    if version is None:
        version_mod = getattr(mod, "version", None)
        if isinstance(version_mod, str):
            version = version_mod
    return {"available": True, "version": version, "error": None}


def check_silero_vad() -> dict:
    """
    Check whether Silero VAD can be loaded through torch.hub.

    This is heavier than a simple import, so we treat it separately.
    """
    torch_info = check_python_package("torch")
    if not torch_info["available"]:
        return {"available": False, "version": None, "error": "torch not available, cannot load silero_vad"}

    try:
        import torch  # noqa: E402 — guarded by the check above

        torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            verbose=False,
        )
    except Exception as exc:
        return {"available": False, "version": None, "error": f"silero_vad hub load failed: {exc}"}

    return {"available": True, "version": None, "error": None}


# ---------------------------------------------------------------------------
# Dependency registry
# ---------------------------------------------------------------------------

# Each entry: (human_label, checker_callable)
# checker_callable returns a dict with keys: available, version|path, error

CRITICAL_DEPS: list[tuple[str, Callable[[], dict]]] = [
    ("ffmpeg", check_ffmpeg),
    ("ffprobe", check_ffprobe),
    ("blender", check_blender),
    ("ultralytics", lambda: check_python_package("ultralytics")),
    ("cv2", lambda: check_python_package("cv2")),
    ("numpy", lambda: check_python_package("numpy")),
]

REQUIRED_DEPS: list[tuple[str, Callable[[], dict]]] = [
    ("librosa", lambda: check_python_package("librosa")),
    ("scipy", lambda: check_python_package("scipy")),
    ("pydub", lambda: check_python_package("pydub")),
    ("torch", lambda: check_python_package("torch")),
    ("PIL", lambda: check_python_package("PIL")),
]

OPTIONAL_DEPS: list[tuple[str, Callable[[], dict]]] = [
    ("google.genai", lambda: check_python_package("google.genai")),
    ("elevenlabs", lambda: check_python_package("elevenlabs")),
    ("manim", lambda: check_python_package("manim")),
    ("npx", check_npx),
    ("deepfilternet", lambda: check_python_package("df")),
    ("google.cloud.speech", lambda: check_python_package("google.cloud.speech")),
    ("whisper", lambda: check_python_package("whisper")),
    ("faster_whisper", lambda: check_python_package("faster_whisper")),
    ("silero_vad", check_silero_vad),
]


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------


def run_checks() -> tuple[dict, list[str], bool]:
    """
    Execute every dependency check.

    Returns:
        (results_dict, warnings_list, all_critical_ok)
    """
    results: dict[str, dict] = {"critical": {}, "required": {}, "optional": {}}
    warnings: list[str] = []
    all_critical_ok = True

    for label, checker in CRITICAL_DEPS:
        info = checker()
        results["critical"][label] = info
        if not info["available"]:
            all_critical_ok = False

    for label, checker in REQUIRED_DEPS:
        info = checker()
        results["required"][label] = info
        if not info["available"]:
            warnings.append(f"required dependency missing: {label} — {info.get('error', 'unknown')}")

    for label, checker in OPTIONAL_DEPS:
        info = checker()
        results["optional"][label] = info
        if not info["available"]:
            warnings.append(f"optional dependency missing: {label} — {info.get('error', 'unknown')}")

    return results, warnings, all_critical_ok


# ---------------------------------------------------------------------------
# Project initialization
# ---------------------------------------------------------------------------


def _build_initial_manifest(project_root: Path) -> dict:
    """Build the initial footage_manifest.json content for a new project."""
    now = datetime.now(timezone.utc).isoformat()
    date_stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return {
        "version": "1.0.0",
        "project": {
            "id": f"footage_project_{date_stamp}",
            "created": now,
            "root_dir": str(project_root.resolve()),
            "hint": "",
            "source_files": [],
        },
        "clips": [],
        "timeline": {
            "segments": [],
            "order": [],
            "transitions": [],
            "total_duration_seconds": 0,
        },
        "sfx": [],
        "music": {"tracks": []},
        "animations": [],
        "thumbnails": [],
        "outputs": {
            "long_16_9": {
                "blender_path": "blender/long_16_9.blend",
                "fcpxml_path": None,
                "resolution": {"w": 1920, "h": 1080},
                "fps": 30,
                "render_path": None,
                "render_status": "pending",
            },
            "long_9_16": {
                "blender_path": "blender/long_9_16.blend",
                "fcpxml_path": None,
                "resolution": {"w": 1080, "h": 1920},
                "fps": 30,
                "render_path": None,
                "render_status": "pending",
            },
            "shorts": [],
        },
        "youtube": {"long_form": None, "shorts": []},
        "pipeline_state": {
            "current_phase": 0,
            "completed_phases": [],
            "phase_results": {},
            "errors": [],
            "warnings": [],
            "last_updated": now,
        },
    }


def init_project(project_root: Path, warnings: list[str], dep_results: dict) -> dict:
    """
    Create the project directory tree, initial manifest, and copy the style
    config template.  Returns the manifest dict (already written to disk).

    Idempotent: skips directories/files that already exist.
    """
    project_root = project_root.resolve()
    project_root.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    for subdir in PROJECT_SUBDIRS:
        (project_root / subdir).mkdir(parents=True, exist_ok=True)

    # Manifest
    manifest_path = project_root / "footage_manifest.json"
    if manifest_path.exists():
        try:
            with manifest_path.open("r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            # Corrupted manifest — back up and recreate
            backup = manifest_path.with_suffix(".json.bak")
            shutil.copy2(manifest_path, backup)
            warnings.append(f"existing manifest was corrupted ({exc}), backed up to {backup.name}")
            manifest = _build_initial_manifest(project_root)
    else:
        manifest = _build_initial_manifest(project_root)

    # Inject dependency-check results into pipeline_state
    now = datetime.now(timezone.utc).isoformat()
    ps = manifest.setdefault("pipeline_state", {})
    ps["warnings"] = list(set(ps.get("warnings", []) + warnings))
    ps["last_updated"] = now

    all_critical_ok = all(
        info.get("available", False) for info in dep_results.get("critical", {}).values()
    )
    phase_status = "success" if all_critical_ok else "error"
    phase_results = ps.setdefault("phase_results", {})
    phase_results["1"] = {"status": phase_status, "timestamp": now}

    if all_critical_ok and 1 not in ps.get("completed_phases", []):
        completed = ps.setdefault("completed_phases", [])
        if 1 not in completed:
            completed.append(1)
        ps["current_phase"] = 1

    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # Style config
    style_dest = project_root / "style_config.json"
    if not style_dest.exists():
        if STYLE_CONFIG_TEMPLATE.is_file():
            shutil.copy2(STYLE_CONFIG_TEMPLATE, style_dest)
        else:
            warnings.append(
                f"style_config_default.json not found at {STYLE_CONFIG_TEMPLATE}, skipping copy"
            )

    return manifest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    project_root: Path | None = None
    if len(sys.argv) > 1:
        project_root = Path(sys.argv[1])

    dep_results, warnings, all_critical_ok = run_checks()

    if project_root is not None:
        try:
            init_project(project_root, warnings, dep_results)
        except OSError as exc:
            output = {
                "status": "error",
                "message": f"Failed to initialize project directory: {exc}",
                "dependencies": dep_results,
                "warnings": warnings,
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 1

    if all_critical_ok:
        message = "All critical dependencies satisfied"
    else:
        missing = [
            label for label, info in dep_results["critical"].items() if not info["available"]
        ]
        message = f"Missing critical dependencies: {', '.join(missing)}"

    output = {
        "status": "success" if all_critical_ok else "error",
        "message": message,
        "dependencies": dep_results,
        "warnings": warnings,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

    return 0 if all_critical_ok else 1


if __name__ == "__main__":
    sys.exit(main())
