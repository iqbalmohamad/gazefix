"""Command-line physical-camera diagnostic for OpenCV candidates."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
import os
import time

from gazefix.camera.backends import default_camera_backends
from gazefix.camera.environment import MSMF_HW_TRANSFORMS_ENV, apply_capture_environment
from gazefix.camera.models import CameraBackend
from gazefix.config import AppSettings


@dataclass(slots=True)
class BackendProbeResult:
    camera_index: int
    requested_backend: str
    opened: bool
    reported_backend: str | None = None
    width: int | None = None
    height: int | None = None
    negotiated_fps: float | None = None
    observed_fps: float | None = None
    successful_reads: int = 0
    failed_reads: int = 0
    sample_seconds: float = 0.0
    open_ms: float | None = None
    configure_ms: float | None = None
    first_frame_ms: float | None = None
    release_ms: float | None = None
    msmf_hw_transforms: str | None = None
    error: str | None = None


def probe_backend(
    index: int,
    backend: CameraBackend,
    width: int,
    height: int,
    target_fps: float,
    duration_s: float,
) -> BackendProbeResult:
    import cv2  # after apply_capture_environment in main()

    result = BackendProbeResult(
        index,
        backend.name,
        opened=False,
        msmf_hw_transforms=os.environ.get(MSMF_HW_TRANSFORMS_ENV),
    )
    opened_at = time.perf_counter()
    capture = cv2.VideoCapture(index, backend.api_preference)
    result.open_ms = _elapsed_ms(opened_at)
    try:
        if not capture.isOpened():
            result.error = "open failed"
            return result
        result.opened = True
        configured_at = time.perf_counter()
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, target_fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        result.configure_ms = _elapsed_ms(configured_at)
        try:
            result.reported_backend = capture.getBackendName()
        except Exception:
            result.reported_backend = "unknown"
        result.width = round(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        result.height = round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        result.negotiated_fps = float(capture.get(cv2.CAP_PROP_FPS))

        started = time.perf_counter()
        while time.perf_counter() - started < duration_s:
            success, frame = capture.read()
            if success and frame is not None and frame.size > 0:
                if result.successful_reads == 0:
                    result.first_frame_ms = _elapsed_ms(started)
                result.successful_reads += 1
            else:
                result.failed_reads += 1
                time.sleep(0.01)
        elapsed = time.perf_counter() - started
        result.sample_seconds = elapsed
        result.observed_fps = (
            result.successful_reads / elapsed if elapsed > 0 else 0.0
        )
        if result.successful_reads == 0:
            result.error = "opened but produced no frames"
        return result
    except Exception as exc:
        result.error = str(exc)
        return result
    finally:
        released_at = time.perf_counter()
        capture.release()
        result.release_ms = _elapsed_ms(released_at)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe numerical OpenCV camera indexes. Results validate candidates "
            "for this run; they are not authoritative Windows device enumeration."
        )
    )
    parser.add_argument("--max-index", type=int, default=4)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument(
        "--msmf-hw-transforms",
        type=int,
        choices=(0, 1),
        default=None,
        help=(
            "Windows only: 1 = OpenCV default (Media Foundation negotiates "
            "hardware transforms on open), 0 = GazeFix default (skip them). "
            "Run both to compare open_ms on this machine."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_index < 0 or args.max_index > 31 or args.duration <= 0:
        print("--max-index must be 0..31 and --duration must be positive")
        return 2

    print(
        "Numerical OpenCV probing only; indexes and availability can change "
        "between runs."
    )
    settings = AppSettings()
    if args.msmf_hw_transforms is not None:
        settings = replace(settings, msmf_hw_transforms=bool(args.msmf_hw_transforms))
    exported = apply_capture_environment(settings)
    if exported:
        print(f"Capture environment: {json.dumps(exported, separators=(',', ':'))}")
    results: list[BackendProbeResult] = []
    for index in range(args.max_index + 1):
        for backend in default_camera_backends():
            result = probe_backend(
                index,
                backend,
                args.width,
                args.height,
                args.fps,
                args.duration,
            )
            results.append(result)
            print(json.dumps(asdict(result), separators=(",", ":")))

    validated = sum(
        result.successful_reads > 0 for result in results
    )
    print(f"Validated index/backend combinations: {validated}")
    return 0 if validated else 1


if __name__ == "__main__":
    raise SystemExit(main())

