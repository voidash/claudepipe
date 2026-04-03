#!/usr/bin/env python3
"""Run YOLO object detection and pose estimation on extracted frames.

Processes frames previously extracted by extract_frames.py (phase 7),
runs YOLOv11 detection to find objects, and runs pose estimation on
frames containing people. Writes per-clip JSON analysis and updates
the footage manifest.

Phase 8 of the footage pipeline.

Usage:
    python3 run_yolo.py <project_root> [--force] [--model yolo11x.pt] \
        [--pose-model yolo11x-pose.pt] [--conf-threshold 0.5]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from ultralytics import YOLO

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE = 16
PERSON_CLASS_ID = 0

# COCO keypoint indices used for facing determination.
NOSE_IDX = 0
LEFT_EYE_IDX = 1
RIGHT_EYE_IDX = 2
LEFT_SHOULDER_IDX = 5
RIGHT_SHOULDER_IDX = 6
LEFT_HIP_IDX = 11
RIGHT_HIP_IDX = 12

# Minimum confidence for a keypoint to be considered "visible".
KEYPOINT_VISIBLE_CONF = 0.5


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
        print(f"Failed to write manifest: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Detailed JSON writer
# ---------------------------------------------------------------------------


def write_detail_json(project_root: Path, relative_path: str, data: dict) -> None:
    """Write a detailed analysis JSON file to the project tree."""
    out_path = project_root / relative_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def load_models(
    model_name: str,
    pose_model_name: str,
) -> tuple:
    """Load YOLO detection and pose models.

    Both models auto-download if not present locally. Raises on failure
    so the caller can abort with a clear message.
    """
    try:
        detect_model = YOLO(model_name)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load detection model '{model_name}': {exc}"
        ) from exc

    try:
        pose_model = YOLO(pose_model_name)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load pose model '{pose_model_name}': {exc}"
        ) from exc

    return detect_model, pose_model


# ---------------------------------------------------------------------------
# Facing determination from pose keypoints
# ---------------------------------------------------------------------------


def determine_facing(keypoints: list[list[float]]) -> str:
    """Determine which direction a person is facing based on COCO keypoints.

    Each keypoint is [x, y, confidence].

    Rules:
    - Both eyes and nose visible with high confidence -> "camera"
    - One eye visible, the other not -> "left" or "right"
    - Neither eye visible but back keypoints (shoulders/hips) are -> "away"
    - Default: "camera"
    """
    if len(keypoints) < 13:
        return "camera"

    nose = keypoints[NOSE_IDX]
    left_eye = keypoints[LEFT_EYE_IDX]
    right_eye = keypoints[RIGHT_EYE_IDX]
    left_shoulder = keypoints[LEFT_SHOULDER_IDX]
    right_shoulder = keypoints[RIGHT_SHOULDER_IDX]
    left_hip = keypoints[LEFT_HIP_IDX]
    right_hip = keypoints[RIGHT_HIP_IDX]

    nose_visible = nose[2] >= KEYPOINT_VISIBLE_CONF
    left_eye_visible = left_eye[2] >= KEYPOINT_VISIBLE_CONF
    right_eye_visible = right_eye[2] >= KEYPOINT_VISIBLE_CONF

    # Both eyes and nose visible -> facing camera
    if left_eye_visible and right_eye_visible and nose_visible:
        return "camera"

    # One eye visible, other not -> facing left or right
    if left_eye_visible and not right_eye_visible:
        return "right"
    if right_eye_visible and not left_eye_visible:
        return "left"

    # Neither eye visible -> check if back keypoints are visible (facing away)
    if not left_eye_visible and not right_eye_visible:
        back_visible_count = sum(
            1 for kp in [left_shoulder, right_shoulder, left_hip, right_hip]
            if kp[2] >= KEYPOINT_VISIBLE_CONF
        )
        if back_visible_count >= 2:
            return "away"

    return "camera"


# ---------------------------------------------------------------------------
# Detection parsing
# ---------------------------------------------------------------------------


def parse_detections(results, conf_threshold: float) -> list[dict]:
    """Parse YOLO detection Results into a list of plain-Python dicts.

    Filters detections below conf_threshold. Converts all numpy types
    to native Python types for JSON serialization.
    """
    detections = []
    for result in results:
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            continue

        names = result.names  # class_id -> class_name mapping

        for i in range(len(boxes)):
            conf = float(boxes.conf[i].item())
            if conf < conf_threshold:
                continue

            class_id = int(boxes.cls[i].item())
            class_name = names.get(class_id, f"class_{class_id}")

            xyxy = boxes.xyxy[i].cpu().numpy().tolist()
            xyxy = [round(v, 1) for v in xyxy]

            xywh = boxes.xywh[i].cpu().numpy().tolist()
            xywh = [round(v, 1) for v in xywh]

            detections.append({
                "class": class_name,
                "class_id": class_id,
                "confidence": round(conf, 4),
                "bbox_xyxy": xyxy,
                "bbox_xywh": xywh,
                "pose": None,
            })

    return detections


def parse_pose_results(results) -> list[dict]:  # type: ignore[no-untyped-def]
    """Parse YOLO pose Results and return a list of pose data dicts.

    Each dict contains "keypoints", "facing", and "bbox_xyxy".
    We match pose results to detection results by comparing bounding boxes.
    Since we run pose on the same frame, the person bboxes should be very close.
    """
    all_poses: list[dict] = []

    for result in results:
        if result.keypoints is None:
            continue

        keypoints_data = result.keypoints.data  # (N, 17, 3)
        boxes = result.boxes

        if boxes is None or keypoints_data is None:
            continue

        for i in range(len(keypoints_data)):
            kp_array = keypoints_data[i].cpu().numpy()
            kp_list = [[round(float(x), 1), round(float(y), 1), round(float(c), 4)]
                       for x, y, c in kp_array]

            bbox_xyxy = boxes.xyxy[i].cpu().numpy().tolist() if i < len(boxes) else None

            facing = determine_facing(kp_list)

            all_poses.append({
                "keypoints": kp_list,
                "facing": facing,
                "bbox_xyxy": bbox_xyxy,
            })

    return all_poses


def match_poses_to_detections(
    detections: list[dict],
    pose_list: list[dict],
) -> None:
    """Attach pose data to person detections by matching bounding boxes.

    Modifies detections in place. Uses IoU (intersection over union) to
    match each pose bbox to the closest person detection bbox.
    """
    person_indices = [
        i for i, d in enumerate(detections)
        if d["class_id"] == PERSON_CLASS_ID
    ]

    if not person_indices or not pose_list:
        return

    for pose_entry in pose_list:
        pose_bbox = pose_entry.get("bbox_xyxy")
        if pose_bbox is None:
            continue

        best_iou = 0.0
        best_idx = -1

        for det_idx in person_indices:
            det_bbox = detections[det_idx]["bbox_xyxy"]
            iou = _compute_iou(det_bbox, pose_bbox)
            if iou > best_iou:
                best_iou = iou
                best_idx = det_idx

        if best_idx >= 0 and best_iou > 0.3:
            detections[best_idx]["pose"] = {
                "keypoints": pose_entry["keypoints"],
                "facing": pose_entry["facing"],
            }


def _compute_iou(box_a: list[float], box_b: list[float]) -> float:
    """Compute intersection-over-union between two [x1, y1, x2, y2] boxes."""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h

    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union_area = area_a + area_b - inter_area

    if union_area < 1e-6:
        return 0.0

    return inter_area / union_area


# ---------------------------------------------------------------------------
# Tracking summary
# ---------------------------------------------------------------------------


def build_tracking_summary(detections_by_frame: dict) -> dict:
    """Build a tracking summary from all person detections across frames.

    - primary_subject_bbox_median: median bbox of the most frequently detected
      person (approximated as the largest average-area person track).
    - subject_movement_range: min/max x and y across all person bboxes.
    """
    # Collect all person bboxes (xyxy format)
    all_person_bboxes: list[list[float]] = []
    for frame_dets in detections_by_frame.values():
        for det in frame_dets:
            if det["class_id"] == PERSON_CLASS_ID:
                all_person_bboxes.append(det["bbox_xyxy"])

    if not all_person_bboxes:
        return {
            "primary_subject_bbox_median": None,
            "subject_movement_range": None,
        }

    bboxes_arr = np.array(all_person_bboxes)

    # Compute area for each bbox
    areas = (bboxes_arr[:, 2] - bboxes_arr[:, 0]) * (bboxes_arr[:, 3] - bboxes_arr[:, 1])

    # Use the largest-area bboxes as the "primary subject" heuristic:
    # Take bboxes whose area is above the median area to approximate the
    # most prominent / frequently appearing person.
    if len(areas) >= 2:
        area_median = float(np.median(areas))
        primary_mask = areas >= area_median
        primary_bboxes = bboxes_arr[primary_mask]
    else:
        primary_bboxes = bboxes_arr

    # Median bbox
    median_bbox = np.median(primary_bboxes, axis=0).tolist()
    median_bbox = [round(v, 1) for v in median_bbox]

    # Movement range across ALL person bboxes
    x_min = round(float(bboxes_arr[:, 0].min()), 1)
    x_max = round(float(bboxes_arr[:, 2].max()), 1)
    y_min = round(float(bboxes_arr[:, 1].min()), 1)
    y_max = round(float(bboxes_arr[:, 3].max()), 1)

    return {
        "primary_subject_bbox_median": median_bbox,
        "subject_movement_range": {
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max,
        },
    }


# ---------------------------------------------------------------------------
# Per-clip processing
# ---------------------------------------------------------------------------


def clip_already_processed(clip: dict, project_root: Path) -> bool:
    """Check whether YOLO data already exists for a clip."""
    yolo = clip.get("yolo")
    if yolo is None or not isinstance(yolo, dict):
        return False

    detail_path = yolo.get("path")
    if not detail_path:
        return False

    full_path = project_root / detail_path
    if not full_path.is_file():
        return False

    # Check that detections_by_frame has at least one entry
    detections = yolo.get("detections_by_frame")
    if not detections or not isinstance(detections, dict):
        return False

    return True


def get_clip_frame_paths(clip: dict, project_root: Path) -> list[tuple[str, Path]]:
    """Return a list of (relative_path, absolute_path) for extracted frames.

    Only returns frames that actually exist on disk.
    """
    frames = clip.get("frames")
    if frames is None or not isinstance(frames, dict):
        return []

    extracted = frames.get("extracted", [])
    if not extracted or not isinstance(extracted, list):
        return []

    result = []
    for entry in extracted:
        rel_path = entry.get("path")
        if not rel_path:
            continue
        abs_path = project_root / rel_path
        if abs_path.is_file():
            result.append((rel_path, abs_path))
        else:
            print(
                f"WARNING: frame file not found, skipping: {abs_path}",
                file=sys.stderr,
            )

    return result


def process_clip(
    clip: dict,
    project_root: Path,
    detect_model: YOLO,
    pose_model: YOLO,
    model_name: str,
    conf_threshold: float,
) -> tuple[int, int]:
    """Run YOLO detection and pose estimation on a single clip's frames.

    Returns (num_frames_processed, num_total_detections).
    """
    clip_id = clip["id"]

    frame_entries = get_clip_frame_paths(clip, project_root)
    if not frame_entries:
        print(
            f"WARNING: no frames found for clip {clip_id}, skipping",
            file=sys.stderr,
        )
        clip["yolo"] = None
        return 0, 0

    detections_by_frame: dict[str, list[dict]] = {}
    total_detections = 0

    # Process frames in batches for efficiency
    for batch_start in range(0, len(frame_entries), BATCH_SIZE):
        batch_entries = frame_entries[batch_start:batch_start + BATCH_SIZE]
        batch_abs_paths = [str(abs_path) for _, abs_path in batch_entries]

        # Run detection on the batch
        try:
            det_results = detect_model(batch_abs_paths, conf=conf_threshold, verbose=False)
        except Exception as exc:
            print(
                f"WARNING: detection failed for batch starting at index "
                f"{batch_start} in clip {clip_id}: {exc}",
                file=sys.stderr,
            )
            # Record empty detections for these frames
            for rel_path, _ in batch_entries:
                detections_by_frame[rel_path] = []
            continue

        # Parse detections per frame
        for i, (rel_path, _) in enumerate(batch_entries):
            if i < len(det_results):
                frame_dets = parse_detections([det_results[i]], conf_threshold)
            else:
                frame_dets = []

            detections_by_frame[rel_path] = frame_dets
            total_detections += len(frame_dets)

    # Second pass: run pose estimation on frames that have person detections
    frames_needing_pose = [
        (rel_path, abs_path)
        for rel_path, abs_path in frame_entries
        if any(
            d["class_id"] == PERSON_CLASS_ID
            for d in detections_by_frame.get(rel_path, [])
        )
    ]

    if frames_needing_pose:
        for batch_start in range(0, len(frames_needing_pose), BATCH_SIZE):
            batch_entries = frames_needing_pose[batch_start:batch_start + BATCH_SIZE]
            batch_abs_paths = [str(abs_path) for _, abs_path in batch_entries]

            try:
                pose_results = pose_model(batch_abs_paths, conf=conf_threshold, verbose=False)
            except Exception as exc:
                print(
                    f"WARNING: pose estimation failed for batch starting at index "
                    f"{batch_start} in clip {clip_id}: {exc}",
                    file=sys.stderr,
                )
                continue

            for i, (rel_path, _) in enumerate(batch_entries):
                if i >= len(pose_results):
                    continue

                pose_list = parse_pose_results([pose_results[i]])
                if pose_list:
                    match_poses_to_detections(
                        detections_by_frame[rel_path],
                        pose_list,
                    )

    # Build tracking summary
    tracking_summary = build_tracking_summary(detections_by_frame)

    # Build the manifest-level yolo object
    relative_analysis_path = f"analysis/yolo/{clip_id}.json"
    yolo_data = {
        "path": relative_analysis_path,
        "model": model_name,
        "detections_by_frame": detections_by_frame,
        "tracking_summary": tracking_summary,
    }

    clip["yolo"] = yolo_data

    # Write detailed JSON
    write_detail_json(project_root, relative_analysis_path, yolo_data)

    return len(frame_entries), total_detections


# ---------------------------------------------------------------------------
# Pipeline state update
# ---------------------------------------------------------------------------


def update_pipeline_state(
    manifest: dict,
    clips_processed: int,
    total_frames: int,
    total_detections: int,
    warnings: list[str],
) -> None:
    """Mark phase 8 as complete in pipeline_state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state = manifest.setdefault("pipeline_state", {
        "current_phase": 8,
        "completed_phases": [],
        "phase_results": {},
        "errors": [],
        "warnings": [],
        "last_updated": now,
    })

    phase_results = state.setdefault("phase_results", {})
    phase_results["8"] = {
        "status": "success",
        "timestamp": now,
        "clips_processed": clips_processed,
        "total_frames": total_frames,
        "total_detections": total_detections,
    }

    completed = state.setdefault("completed_phases", [])
    if 8 not in completed:
        completed.append(8)
        completed.sort()

    current = state.get("current_phase", 0)
    if current <= 8:
        state["current_phase"] = 9

    existing_warnings = state.setdefault("warnings", [])
    for w in warnings:
        if w not in existing_warnings:
            existing_warnings.append(w)

    state["last_updated"] = now


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run YOLO object detection and pose estimation on extracted frames.",
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
        help="Re-process clips even if YOLO data already exists",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolo11x.pt",
        help="YOLO detection model name (default: yolo11x.pt, auto-downloads)",
    )
    parser.add_argument(
        "--pose-model",
        type=str,
        default="yolo11x-pose.pt",
        help="YOLO pose model name (default: yolo11x-pose.pt, auto-downloads)",
    )
    parser.add_argument(
        "--conf-threshold",
        type=float,
        default=0.5,
        help="Minimum confidence threshold for detections (default: 0.5)",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        output = {
            "status": "error",
            "message": f"Project root does not exist: {project_root}",
            "details": {"clips_processed": 0, "total_frames": 0, "total_detections": 0},
        }
        print(json.dumps(output))
        return 1

    if not 0.0 < args.conf_threshold <= 1.0:
        output = {
            "status": "error",
            "message": f"--conf-threshold must be in (0.0, 1.0], got {args.conf_threshold}",
            "details": {"clips_processed": 0, "total_frames": 0, "total_detections": 0},
        }
        print(json.dumps(output))
        return 1

    manifest = load_manifest(project_root)

    clips = manifest.get("clips", [])
    if not clips:
        output = {
            "status": "success",
            "message": "No clips found in manifest, nothing to process",
            "details": {"clips_processed": 0, "total_frames": 0, "total_detections": 0},
        }
        print(json.dumps(output))
        return 0

    # Load models once
    try:
        detect_model, pose_model = load_models(args.model, args.pose_model)
    except RuntimeError as exc:
        output = {
            "status": "error",
            "message": str(exc),
            "details": {"clips_processed": 0, "total_frames": 0, "total_detections": 0},
        }
        print(json.dumps(output))
        return 1

    warnings: list[str] = []
    errors: list[str] = []
    clips_processed = 0
    total_frames = 0
    total_detections = 0

    for clip in clips:
        clip_id = clip.get("id", "unknown")

        # Skip clips without extracted frames
        frames_data = clip.get("frames")
        if frames_data is None or not isinstance(frames_data, dict):
            print(
                f"Clip {clip_id}: no frames data, skipping YOLO",
                file=sys.stderr,
            )
            continue

        frame_count = frames_data.get("count", 0)
        if frame_count == 0:
            print(
                f"Clip {clip_id}: zero extracted frames, skipping YOLO",
                file=sys.stderr,
            )
            continue

        # Skip already-processed unless --force
        if not args.force and clip_already_processed(clip, project_root):
            print(
                f"Clip {clip_id}: YOLO already processed, skipping (use --force to re-run)",
                file=sys.stderr,
            )
            existing_dets = clip.get("yolo", {}).get("detections_by_frame", {})
            existing_frame_count = len(existing_dets)
            existing_det_count = sum(len(v) for v in existing_dets.values())
            total_frames += existing_frame_count
            total_detections += existing_det_count
            continue

        try:
            n_frames, n_dets = process_clip(
                clip,
                project_root,
                detect_model,
                pose_model,
                args.model,
                args.conf_threshold,
            )
            total_frames += n_frames
            total_detections += n_dets
            if n_frames > 0:
                clips_processed += 1
        except Exception as exc:
            msg = f"Clip {clip_id}: YOLO processing failed: {exc}"
            print(msg, file=sys.stderr)
            errors.append(msg)

    # Check if all clips errored and we processed nothing
    if errors and clips_processed == 0 and total_frames == 0:
        output = {
            "status": "error",
            "message": f"All clips failed: {len(errors)} error(s)",
            "details": {
                "clips_processed": 0,
                "total_frames": 0,
                "total_detections": 0,
                "errors": errors,
            },
        }
        print(json.dumps(output))
        return 1

    # Non-fatal errors become warnings
    for err in errors:
        warnings.append(err)

    update_pipeline_state(manifest, clips_processed, total_frames, total_detections, warnings)

    if errors:
        state = manifest.setdefault("pipeline_state", {})
        existing_errors = state.setdefault("errors", [])
        for e in errors:
            if e not in existing_errors:
                existing_errors.append(e)

    save_manifest(project_root, manifest)

    output = {
        "status": "success",
        "message": (
            f"YOLO processed {clips_processed} clips, "
            f"{total_frames} frames, {total_detections} detections"
        ),
        "details": {
            "clips_processed": clips_processed,
            "total_frames": total_frames,
            "total_detections": total_detections,
        },
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
