"""File-only validation harness for the real MediaPipe tracking adapter."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import Enum
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Sequence

import cv2

from gazefix.tracking.interfaces import FaceTracker
from gazefix.tracking.mediapipe_tracker import (
    MediaPipeFaceTracker,
    MediaPipeTrackerConfig,
    TrackerInitializationError,
)
from gazefix.tracking.model_asset import (
    DEFAULT_FACE_LANDMARKER_MODEL_PATH,
    ModelAssetError,
    provision_face_landmarker_model,
    verify_face_landmarker_model,
)
from gazefix.tracking.models import TrackingResult, TrackingState
from gazefix.tracking.overlay import DebugOverlayRenderer


class OfflineInputKind(str, Enum):
    AUTO = "auto"
    IMAGE = "image"
    VIDEO = "video"


class OfflineValidationError(RuntimeError):
    """Raised for an unreadable input or unusable overlay destination."""


@dataclass(frozen=True, slots=True)
class OfflineValidationReport:
    """Serializable outcome of a file-only tracking run."""

    input_path: str
    input_kind: str
    overlay_output_path: str | None
    total_frames_processed: int
    frames_with_face: int
    frames_with_no_face: int
    no_face_outcomes: int
    temporary_tracking_loss_frames: int
    temporary_tracking_loss_events: int
    tracking_recovery_events: int
    low_confidence_outcomes: int
    invalid_frame_outcomes: int
    tracker_error_outcomes: int
    mean_tracking_latency_ms: float
    median_tracking_latency_ms: float
    p95_tracking_latency_ms: float
    processing_elapsed_seconds: float
    effective_processing_throughput_frames_per_second: float | None
    source_video_frame_rate: float | None


class _ReportAccumulator:
    def __init__(self) -> None:
        self.total_frames = 0
        self.frames_with_face = 0
        self.frames_with_no_face = 0
        self.no_face_outcomes = 0
        self.temporary_loss_frames = 0
        self.temporary_loss_events = 0
        self.recovery_events = 0
        self.low_confidence_outcomes = 0
        self.invalid_frame_outcomes = 0
        self.tracker_error_outcomes = 0
        self.latencies_ms: list[float] = []
        self._temporary_loss_active = False
        self._face_seen = False
        self._loss_since_face = False

    def record(self, result: TrackingResult) -> None:
        self.total_frames += 1
        self.latencies_ms.append(result.processing_time_ms)
        if result.face_detected:
            self.frames_with_face += 1
            if self._loss_since_face:
                self.recovery_events += 1
            self._face_seen = True
            self._loss_since_face = False
        else:
            self.frames_with_no_face += 1

        if result.state is TrackingState.NO_FACE:
            self.no_face_outcomes += 1
            if self._face_seen:
                self._loss_since_face = True
        elif result.state is TrackingState.TEMPORARILY_LOST:
            self.temporary_loss_frames += 1
            if not self._temporary_loss_active:
                self.temporary_loss_events += 1
            self._temporary_loss_active = True
            if self._face_seen:
                self._loss_since_face = True
        elif result.state is TrackingState.LOW_CONFIDENCE:
            self.low_confidence_outcomes += 1
        elif result.state is TrackingState.INVALID_FRAME:
            self.invalid_frame_outcomes += 1
        elif result.state is TrackingState.TRACKER_ERROR:
            self.tracker_error_outcomes += 1

        if result.state is not TrackingState.TEMPORARILY_LOST:
            self._temporary_loss_active = False

    def build(
        self,
        *,
        input_path: Path,
        input_kind: OfflineInputKind,
        overlay_output_path: Path | None,
        elapsed_seconds: float,
        source_video_frame_rate: float | None,
    ) -> OfflineValidationReport:
        if not self.latencies_ms:
            raise OfflineValidationError("The input contained no decodable frames")
        throughput = (
            self.total_frames / elapsed_seconds
            if input_kind is OfflineInputKind.VIDEO and elapsed_seconds > 0
            else None
        )
        return OfflineValidationReport(
            input_path=str(input_path.resolve()),
            input_kind=input_kind.value,
            overlay_output_path=(
                str(overlay_output_path.resolve())
                if overlay_output_path is not None
                else None
            ),
            total_frames_processed=self.total_frames,
            frames_with_face=self.frames_with_face,
            frames_with_no_face=self.frames_with_no_face,
            no_face_outcomes=self.no_face_outcomes,
            temporary_tracking_loss_frames=self.temporary_loss_frames,
            temporary_tracking_loss_events=self.temporary_loss_events,
            tracking_recovery_events=self.recovery_events,
            low_confidence_outcomes=self.low_confidence_outcomes,
            invalid_frame_outcomes=self.invalid_frame_outcomes,
            tracker_error_outcomes=self.tracker_error_outcomes,
            mean_tracking_latency_ms=statistics.fmean(self.latencies_ms),
            median_tracking_latency_ms=statistics.median(self.latencies_ms),
            p95_tracking_latency_ms=_percentile(self.latencies_ms, 0.95),
            processing_elapsed_seconds=elapsed_seconds,
            effective_processing_throughput_frames_per_second=throughput,
            source_video_frame_rate=source_video_frame_rate,
        )


def _percentile(values: Sequence[float], quantile: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sequence."""

    if not values:
        raise ValueError("At least one value is required")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def run_offline_validation(
    input_path: Path,
    tracker: FaceTracker,
    *,
    input_kind: OfflineInputKind = OfflineInputKind.AUTO,
    overlay_output_path: Path | None = None,
    max_frames: int | None = None,
) -> OfflineValidationReport:
    """Track a still image or video file and always release tracker resources."""

    source_path = Path(input_path)
    if not source_path.is_file():
        raise OfflineValidationError(f"Input file not found: {source_path}")
    if max_frames is not None and max_frames <= 0:
        raise ValueError("max_frames must be positive")

    overlay_path = Path(overlay_output_path) if overlay_output_path else None
    if overlay_path is not None and _same_path(source_path, overlay_path):
        raise OfflineValidationError("Overlay output must not overwrite the input")

    resolved_kind = _resolve_input_kind(source_path, input_kind)
    accumulator = _ReportAccumulator()
    elapsed_seconds = 0.0
    source_video_frame_rate: float | None = None

    try:
        tracker.initialize()
        if resolved_kind is OfflineInputKind.IMAGE:
            elapsed_seconds = _process_image(
                source_path,
                tracker,
                accumulator,
                overlay_path,
            )
        else:
            elapsed_seconds, source_video_frame_rate = _process_video(
                source_path,
                tracker,
                accumulator,
                overlay_path,
                max_frames,
            )
    finally:
        tracker.shutdown()

    return accumulator.build(
        input_path=source_path,
        input_kind=resolved_kind,
        overlay_output_path=overlay_path,
        elapsed_seconds=elapsed_seconds,
        source_video_frame_rate=source_video_frame_rate,
    )


def _resolve_input_kind(path: Path, requested: OfflineInputKind) -> OfflineInputKind:
    if requested is not OfflineInputKind.AUTO:
        return requested
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return OfflineInputKind.IMAGE if image is not None else OfflineInputKind.VIDEO


def _process_image(
    path: Path,
    tracker: FaceTracker,
    accumulator: _ReportAccumulator,
    overlay_path: Path | None,
) -> float:
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise OfflineValidationError(f"Could not decode image: {path}")
    started = time.perf_counter()
    result = tracker.track(frame, frame_sequence=0, timestamp_ns=0)
    accumulator.record(result)
    if overlay_path is not None:
        rendered = DebugOverlayRenderer().render(frame, result)
        _prepare_output_path(overlay_path)
        if not cv2.imwrite(str(overlay_path), rendered):
            raise OfflineValidationError(
                f"Could not write overlay image: {overlay_path}"
            )
    return time.perf_counter() - started


def _process_video(
    path: Path,
    tracker: FaceTracker,
    accumulator: _ReportAccumulator,
    overlay_path: Path | None,
    max_frames: int | None,
) -> tuple[float, float | None]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise OfflineValidationError(f"Could not open video file: {path}")

    reported_frame_rate = float(capture.get(cv2.CAP_PROP_FPS))
    source_frame_rate = (
        reported_frame_rate
        if math.isfinite(reported_frame_rate) and reported_frame_rate > 0
        else None
    )
    timeline_frame_rate = source_frame_rate or 30.0
    writer: cv2.VideoWriter | None = None
    renderer = DebugOverlayRenderer() if overlay_path is not None else None
    started = time.perf_counter()
    sequence = 0
    try:
        while max_frames is None or sequence < max_frames:
            read_ok, frame = capture.read()
            if not read_ok:
                break
            timestamp_ns = round(sequence * 1_000_000_000 / timeline_frame_rate)
            result = tracker.track(
                frame,
                frame_sequence=sequence,
                timestamp_ns=timestamp_ns,
            )
            accumulator.record(result)
            if renderer is not None and overlay_path is not None:
                rendered = renderer.render(frame, result)
                if writer is None:
                    writer = _open_video_writer(
                        overlay_path,
                        width=frame.shape[1],
                        height=frame.shape[0],
                        frame_rate=timeline_frame_rate,
                    )
                writer.write(rendered)
            sequence += 1
    finally:
        capture.release()
        if writer is not None:
            writer.release()
    return time.perf_counter() - started, source_frame_rate


def _open_video_writer(
    path: Path,
    *,
    width: int,
    height: int,
    frame_rate: float,
) -> cv2.VideoWriter:
    _prepare_output_path(path)
    codec = "MJPG" if path.suffix.lower() == ".avi" else "mp4v"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*codec),
        frame_rate,
        (width, height),
    )
    if not writer.isOpened():
        writer.release()
        raise OfflineValidationError(f"Could not open overlay video output: {path}")
    return writer


def _prepare_output_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real MediaPipe face tracker against a still image or "
            "prerecorded video; no webcam is opened."
        )
    )
    parser.add_argument("input", type=Path, help="Input image or video file")
    parser.add_argument(
        "--input-kind",
        choices=tuple(kind.value for kind in OfflineInputKind),
        default=OfflineInputKind.AUTO.value,
        help="Input type (default: infer by decoding as an image first)",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_FACE_LANDMARKER_MODEL_PATH,
        help=f"Face Landmarker bundle (default: {DEFAULT_FACE_LANDMARKER_MODEL_PATH})",
    )
    parser.add_argument(
        "--download-model",
        action="store_true",
        help="Explicitly download the pinned model if it is absent or invalid",
    )
    parser.add_argument(
        "--overlay-output",
        type=Path,
        help="Write a development overlay image or video to this path",
    )
    parser.add_argument(
        "--max-frames",
        type=_positive_integer,
        help="Stop after this many video frames",
    )
    parser.add_argument(
        "--max-faces",
        type=_positive_integer,
        default=1,
        help="Maximum faces requested from MediaPipe (default: 1)",
    )
    parser.add_argument(
        "--temporary-loss-frames",
        type=int,
        default=5,
        help="Consecutive misses treated as temporary loss (default: 5)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    if arguments.temporary_loss_frames < 0:
        parser.error("--temporary-loss-frames cannot be negative")

    try:
        model = (
            provision_face_landmarker_model(arguments.model)
            if arguments.download_model
            else verify_face_landmarker_model(arguments.model)
        )
        tracker = MediaPipeFaceTracker(
            MediaPipeTrackerConfig(
                model_path=model.path,
                max_faces=arguments.max_faces,
                temporary_loss_frames=arguments.temporary_loss_frames,
            )
        )
        report = run_offline_validation(
            arguments.input,
            tracker,
            input_kind=OfflineInputKind(arguments.input_kind),
            overlay_output_path=arguments.overlay_output,
            max_frames=arguments.max_frames,
        )
    except (
        ModelAssetError,
        OfflineValidationError,
        TrackerInitializationError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return (
        1
        if report.invalid_frame_outcomes or report.tracker_error_outcomes
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
