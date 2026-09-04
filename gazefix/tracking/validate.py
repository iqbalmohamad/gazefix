"""Command-line tracking diagnostic (``scripts/tracking_test.py``).

Runs the real face landmarker, through the same ``create_mediapipe_tracker``
factory and ``analysis`` code the application uses, on either a local image
(``--image``; a licensed still such as ``tests/assets/astronaut_face.png``)
or a physical camera (``--camera INDEX``, opened through the M0
``OpenCVCameraSource`` path) and prints one JSON object with detection,
validity, pose and timing statistics. It never stores or transmits frames.

What is intentionally different from the running application:

- Inference is synchronous on this thread (no tracker thread, no bounded
  wait, no timeout passthrough), so ``inference_ms`` is the pure backend
  cost per frame while the application additionally reports the processor
  wait and pipeline latency.
- No stabilisation and no primary-face memory: each frame is analysed on
  its own (the largest face is reported).
- With ``--image`` the still is scaled into a canvas of ``--width`` ×
  ``--height`` (face centred, at ``--face-scale`` of the canvas height) and
  optionally moved sideways each frame (``--motion-px``) so video-mode
  tracking is exercised; this is a synthetic sequence, not a webcam.

Exit codes: 0 when at least one frame was TRACKED, 1 otherwise (including
tracker initialisation failure, whose message is printed), 2 bad arguments.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

from gazefix.camera.environment import apply_capture_environment
from gazefix.config import AppSettings, default_model_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GazeFix tracking diagnostic (real model, local only)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path, help="run on a still image scaled into a canvas")
    source.add_argument("--camera", type=int, help="run on a physical camera index (OpenCV probing index)")
    parser.add_argument("--model-dir", type=Path, default=None, help=f"directory containing face_landmarker.task (default: {default_model_directory()})")
    parser.add_argument("--duration", type=float, default=5.0, help="seconds to sample a camera (default: 5)")
    parser.add_argument("--frames", type=int, default=60, help="frames to synthesise from an image (default: 60)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--face-scale", type=float, default=0.8, help="image mode: still height as a fraction of the canvas height")
    parser.add_argument("--motion-px", type=int, default=60, help="image mode: horizontal sway amplitude in pixels")
    parser.add_argument("--max-faces", type=int, default=2)
    parser.add_argument("--msmf-hw-transforms", type=int, choices=(0, 1), default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.frames <= 0 or args.width <= 0 or args.height <= 0 or args.fps <= 0:
        parser.error("duration, frames, width, height and fps must be positive")
    if not 0.05 <= args.face_scale <= 1.0:
        parser.error("--face-scale must be between 0.05 and 1")
    try:
        settings = replace(
            AppSettings(),
            capture_width=args.width,
            capture_height=args.height,
            target_fps=args.fps,
            model_directory=args.model_dir or default_model_directory(),
            tracking_max_faces=args.max_faces,
            msmf_hw_transforms=(
                AppSettings().msmf_hw_transforms if args.msmf_hw_transforms is None else bool(args.msmf_hw_transforms)
            ),
        ).validated()
    except ValueError as exc:
        parser.error(str(exc))
    apply_capture_environment(settings)  # before OpenCV loads (see camera.environment)

    import cv2  # noqa: E402  (after the environment export)
    import numpy as np  # noqa: E402

    from gazefix.tracking.analysis import (  # noqa: E402
        AnalysisSettings,
        compute_quality,
        extract_eye,
        head_pose_from_matrix,
        validate_landmarks,
    )
    from gazefix.tracking.mediapipe_tracker import create_mediapipe_tracker  # noqa: E402
    from gazefix.tracking.models import FrameGeometry  # noqa: E402
    from gazefix.tracking.tracker import TrackerInitializationError  # noqa: E402

    report: dict[str, Any] = {
        "source": {"image": str(args.image)} if args.image else {"camera_index": args.camera},
        "requested": {"width": args.width, "height": args.height, "fps": args.fps},
        "model_dir": str(settings.model_directory),
    }
    started = time.perf_counter()
    try:
        tracker = create_mediapipe_tracker(settings)
    except TrackerInitializationError as exc:
        report.update({"tracker": None, "error_kind": exc.kind, "error": str(exc), "tracked_frames": 0})
        print(json.dumps(report, indent=2))
        return 1
    report["tracker"] = tracker.description
    report["init_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    analysis = AnalysisSettings(
        min_quality=settings.tracking_min_quality, min_eye_width_px=settings.tracking_min_eye_width_px
    )

    frames_iter: Any
    source_close = None
    if args.image is not None:
        still = cv2.imread(str(args.image))
        if still is None:
            report["error"] = f"could not read image {args.image}"
            print(json.dumps(report, indent=2))
            tracker.close()
            return 1

        def synthetic() -> Any:
            for index in range(args.frames):
                dx = int(args.motion_px * math.sin(index / 8.0))
                yield _canvas(np, cv2, still, args.width, args.height, args.face_scale, dx), index * int(1000 / args.fps)

        frames_iter = synthetic()
    else:
        from gazefix.camera.models import CameraDevice  # noqa: E402
        from gazefix.camera.source import OpenCVCameraSource  # noqa: E402

        source = OpenCVCameraSource(settings)
        try:
            open_result = source.open(CameraDevice(index=args.camera))
        except Exception as exc:
            report["error"] = f"camera open failed: {exc}"
            print(json.dumps(report, indent=2))
            tracker.close()
            return 1
        report["camera"] = {
            "backend": open_result.reported_backend,
            "width": open_result.width,
            "height": open_result.height,
            "fps": open_result.fps,
        }
        source_close = source.close

        def captured() -> Any:
            deadline = time.perf_counter() + args.duration
            base = time.perf_counter_ns()
            while time.perf_counter() < deadline:
                success, frame = source.read()
                if not success or frame is None:
                    yield None, 0
                    continue
                yield frame, (time.perf_counter_ns() - base) // 1_000_000

        frames_iter = captured()

    inference: list[float] = []
    statuses: dict[str, int] = {}
    yaw: list[float] = []
    pitch: list[float] = []
    roll: list[float] = []
    openness: list[float] = []
    read_failures = 0
    frame_count = 0
    loop_started = time.perf_counter()
    try:
        for frame, timestamp_ms in frames_iter:
            if frame is None:
                read_failures += 1
                continue
            frame_count += 1
            geometry = FrameGeometry(frame.shape[1], frame.shape[0])
            try:
                detection = tracker.detect(frame, timestamp_ms)
            except Exception as exc:  # noqa: BLE001  (diagnostic reports it)
                statuses["error"] = statuses.get("error", 0) + 1
                report.setdefault("last_error", str(exc))
                continue
            inference.append(detection.inference_ms)
            if not detection.faces:
                statuses["no_face"] = statuses.get("no_face", 0) + 1
                continue
            largest = max(detection.faces, key=lambda f: float(np.ptp(f.landmarks[:, 1])))
            try:
                landmarks, iris_available = validate_landmarks(largest.landmarks)
            except ValueError as exc:
                statuses["malformed"] = statuses.get("malformed", 0) + 1
                report.setdefault("last_error", str(exc))
                continue
            quality = compute_quality(landmarks, geometry, analysis, tracker.backend_thresholds)
            right = extract_eye(landmarks, "right", geometry, analysis, iris_available)
            left = extract_eye(landmarks, "left", geometry, analysis, iris_available)
            tracked = quality.score >= analysis.min_quality and right.valid and left.valid
            key = "tracked" if tracked else "low_quality"
            statuses[key] = statuses.get(key, 0) + 1
            openness.extend((right.openness, left.openness))
            pose = head_pose_from_matrix(largest.transform)
            if pose is not None:
                yaw.append(pose.yaw_deg)
                pitch.append(pose.pitch_deg)
                roll.append(pose.roll_deg)
            report["iris_available"] = iris_available
            report["last_quality"] = {
                "score": round(quality.score, 3),
                "in_frame_fraction": round(quality.in_frame_fraction, 3),
                "face_height_fraction": round(quality.face_height_fraction, 3),
            }
    finally:
        elapsed = time.perf_counter() - loop_started
        tracker.close()
        if source_close is not None:
            source_close()
    report.update(
        {
            "frames": frame_count,
            "read_failures": read_failures,
            "elapsed_s": round(elapsed, 2),
            "loop_fps": round(frame_count / elapsed, 1) if elapsed > 0 else 0.0,
            "statuses": statuses,
            "tracked_frames": statuses.get("tracked", 0),
            "inference_ms": _stats(inference),
            "head_pose_deg": {"yaw": _stats(yaw), "pitch": _stats(pitch), "roll": _stats(roll)},
            "eye_openness": _stats(openness),
        }
    )
    print(json.dumps(report, indent=2))
    return 0 if statuses.get("tracked", 0) > 0 else 1


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    return {
        "count": count,
        "median": round(ordered[count // 2], 2),
        "p90": round(ordered[min(count - 1, int(count * 0.9))], 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
    }


def _canvas(np: Any, cv2: Any, still: Any, width: int, height: int, face_scale: float, dx: int) -> Any:
    canvas = np.full((height, width, 3), 96, np.uint8)
    still_height, still_width = still.shape[:2]
    scale = (height * 0.95 * face_scale) / still_height
    resized = cv2.resize(still, (max(1, int(still_width * scale)), max(1, int(still_height * scale))), interpolation=cv2.INTER_LINEAR)
    rh, rw = resized.shape[:2]
    y0 = max(0, (height - rh) // 2)
    x0 = max(0, (width - rw) // 2 + dx)
    y1, x1 = min(height, y0 + rh), min(width, x0 + rw)
    canvas[y0:y1, x0:x1] = resized[: y1 - y0, : x1 - x0]
    canvas.setflags(write=False)
    return canvas


if __name__ == "__main__":
    sys.exit(main())
