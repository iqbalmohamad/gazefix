"""Command-line physical-camera diagnostic for OpenCV candidates.

Every index/backend pair is opened, configured, and first-frame validated by
``gazefix.camera.source.open_validated_backend``, the primitive the capture
worker itself runs for each backend, using the same ``AppSettings`` the
application uses (requested size and FPS, validation read count and timeout,
retry delay, Media Foundation hardware-transform switch). ``open_ms``,
``configure_ms``, ``first_frame_ms``, ``format_sets_applied``, and
``validation_reads`` therefore mean exactly what the ``camera_opened`` log
event means in production; see ``BackendOpenOutcome`` for the boundaries.

What is intentionally different from production, and how it affects reading
the numbers:

- No backend fallback. Each backend is probed on its own and reported even
  when it fails, so the two can be compared. Production tries the backends
  in platform order and stops at the first that validates, so a production
  open that falls back costs the failed attempt(s) plus the successful one.
- A backend that opens but fails validation is released without sampling,
  which is what production does with it; ``validated`` says which case
  applies and ``error`` says why.
- Sampling (``sample_seconds``, ``successful_reads``, ``failed_reads``,
  ``observed_fps``) is a plain read loop that exists only here. It measures
  steady-state delivery after validation, does not model the capture
  worker's degraded/retry handling, and does not count the validation frame.
- ``release_ms`` is measured on this thread; production releases on the
  capture worker thread, and only the owning thread ever releases.
- The application may adopt a camera that discovery already validated instead
  of opening it a second time, so an application start can cost one open less
  than the sum of these probes.

The tool is local-only, needs no Qt, and releases every camera it touches on
success, failure, interruption, and exception. Production code never imports
this module.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
import os
import time
from typing import Any, Callable

from gazefix.camera.backends import default_camera_backends
from gazefix.camera.environment import MSMF_HW_TRANSFORMS_ENV, apply_capture_environment
from gazefix.camera.models import CameraBackend
from gazefix.config import AppSettings


CaptureFactory = Callable[[], Any]


@dataclass(slots=True)
class BackendProbeResult:
    """One index/backend probe. Field meanings are documented in the module docstring."""

    camera_index: int
    requested_backend: str
    opened: bool
    validated: bool = False
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
    format_sets_applied: int = 0
    first_frame_ms: float | None = None
    validation_reads: int = 0
    release_ms: float | None = None
    msmf_hw_transforms: str | None = None
    error: str | None = None


def probe_backend(
    index: int,
    backend: CameraBackend,
    settings: AppSettings,
    duration_s: float,
    capture_factory: CaptureFactory | None = None,
) -> BackendProbeResult:
    """Open ``index`` on ``backend`` the production way, sample it, release it.

    ``capture_factory`` creates the (unopened) ``cv2.VideoCapture``; tests
    substitute a fake. The capture is released on every exit path.
    """

    # Imported here, not at module level, so the CLI can export the capture
    # environment before OpenCV loads (see gazefix.camera.environment).
    from gazefix.camera.source import open_validated_backend

    result = BackendProbeResult(
        index,
        backend.name,
        opened=False,
        msmf_hw_transforms=os.environ.get(MSMF_HW_TRANSFORMS_ENV),
    )
    capture = (capture_factory or _new_video_capture)()
    try:
        outcome = open_validated_backend(capture, index, backend, settings)
        result.opened = outcome.opened
        result.validated = outcome.validated
        result.open_ms = outcome.open_ms
        result.configure_ms = outcome.configure_ms
        result.format_sets_applied = outcome.format_sets_applied
        result.first_frame_ms = outcome.first_frame_ms
        result.validation_reads = outcome.validation_reads
        if outcome.result is not None:
            result.reported_backend = outcome.result.reported_backend
            result.width = outcome.result.width
            result.height = outcome.result.height
            result.negotiated_fps = outcome.result.fps
        if not outcome.opened:
            result.error = "open failed"
            return result
        if not outcome.validated:
            result.error = "opened but produced no validation frame"
            return result
        _sample(capture, duration_s, result)
        if result.successful_reads == 0:
            result.error = "validated but produced no frames while sampling"
        return result
    except Exception as exc:
        result.error = str(exc)
        try:
            # The open may have succeeded before a later step raised; report
            # what OpenCV says rather than leaving the field at its default.
            result.opened = bool(capture.isOpened())
        except Exception:  # noqa: BLE001  (a broken backend must not mask ``exc``)
            pass
        return result
    finally:
        # Runs for KeyboardInterrupt as well, so an interrupted probe never
        # leaves the camera open behind the tool.
        released_at = time.perf_counter()
        capture.release()
        result.release_ms = _elapsed_ms(released_at)


def _sample(capture: Any, duration_s: float, result: BackendProbeResult) -> None:
    """Diagnostic-only steady-state read loop; not a production code path."""

    started = time.perf_counter()
    while time.perf_counter() - started < duration_s:
        success, frame = capture.read()
        if success and frame is not None and frame.size > 0:
            result.successful_reads += 1
        else:
            result.failed_reads += 1
            time.sleep(0.01)
    elapsed = time.perf_counter() - started
    result.sample_seconds = elapsed
    result.observed_fps = result.successful_reads / elapsed if elapsed > 0 else 0.0


def _new_video_capture() -> Any:
    import cv2  # after apply_capture_environment in main()

    return cv2.VideoCapture()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe numerical OpenCV camera indexes through the production "
            "open/configure/validate path. Results validate candidates for "
            "this run; they are not authoritative Windows device enumeration."
        )
    )
    parser.add_argument("--max-index", type=int, default=4)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--width", type=int, default=AppSettings().capture_width)
    parser.add_argument("--height", type=int, default=AppSettings().capture_height)
    parser.add_argument("--fps", type=float, default=AppSettings().target_fps)
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
    try:
        settings = replace(
            AppSettings(),
            capture_width=args.width,
            capture_height=args.height,
            target_fps=args.fps,
            msmf_hw_transforms=(
                AppSettings().msmf_hw_transforms
                if args.msmf_hw_transforms is None
                else bool(args.msmf_hw_transforms)
            ),
        ).validated()
    except ValueError as exc:
        print(f"Invalid settings: {exc}")
        return 2

    print(
        "Numerical OpenCV probing only; indexes and availability can change "
        "between runs."
    )
    print(
        "open_ms/configure_ms/first_frame_ms come from the production open "
        "path; sampling and release are diagnostic-only (no backend fallback)."
    )
    exported = apply_capture_environment(settings)
    if exported:
        print(f"Capture environment: {json.dumps(exported, separators=(',', ':'))}")
    results: list[BackendProbeResult] = []
    try:
        for index in range(args.max_index + 1):
            for backend in default_camera_backends():
                result = probe_backend(index, backend, settings, args.duration)
                results.append(result)
                print(json.dumps(asdict(result), separators=(",", ":")))
    except KeyboardInterrupt:
        print("Interrupted; the camera being probed has been released")
        return 130

    validated = sum(result.validated for result in results)
    print(f"Validated index/backend combinations: {validated}")
    return 0 if validated else 1


if __name__ == "__main__":
    raise SystemExit(main())
