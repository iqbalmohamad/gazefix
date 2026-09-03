"""Minimal, responsive Milestone 0 application window."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gazefix.camera.capture import SourceFactory
from gazefix.camera.discovery import CameraDiscoveryService, DiscoveryResult
from gazefix.camera.models import CameraDevice, CaptureState, CaptureStatus
from gazefix.camera.source import PreparedCamera, PreparedCameraCloser
from gazefix.config import AppSettings
from gazefix.pipeline.runtime import PipelineRuntime


logger = logging.getLogger(__name__)


class UiSignals(QObject):
    capture_status = Signal(object)
    discovery_finished = Signal(object)
    discovery_error = Signal(str)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: AppSettings,
        log_path: str,
        source_factory: SourceFactory | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._signals = UiSignals()
        self._signals.capture_status.connect(self._on_capture_status)
        self._signals.discovery_finished.connect(self._on_discovery_finished)
        self._signals.discovery_error.connect(self._on_discovery_error)

        # Cleanup is owner-scoped: the runtime owns its own cleanup thread
        # (created inside PipelineRuntime, never shared, so discovery work
        # can never appear as runtime lifecycle state), and the window owns a
        # separate one for discovery's unadopted prepared cameras. closeEvent
        # joins both, bounded, within the one shutdown deadline.
        self._discovery_closer = PreparedCameraCloser("gazefix-discovery-prepared-close")
        self._runtime = PipelineRuntime(
            settings,
            on_status=self._signals.capture_status.emit,
            source_factory=source_factory,
        )
        discovery_kwargs = {} if source_factory is None else {"source_factory": source_factory}
        self._discovery = CameraDiscoveryService(
            settings,
            on_finished=self._signals.discovery_finished.emit,
            on_error=self._signals.discovery_error.emit,
            prepared_closer=self._discovery_closer,
            **discovery_kwargs,
        )
        self._devices: list[CameraDevice] = []
        self._preferred_index: int | None = None
        self._last_output_sequence = 0
        self._last_image: QImage | None = None
        self._first_frame_presented = False
        self._refresh_pending = False
        self._closing = False

        self.setWindowTitle("GazeFix")
        self.setMinimumSize(760, 580)
        self.resize(960, 720)
        self._build_ui(log_path)

        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._present_latest_frame)
        self._preview_timer.start(settings.preview_poll_ms)

        self._metrics_timer = QTimer(self)
        self._metrics_timer.timeout.connect(self._refresh_metrics)
        self._metrics_timer.start(settings.metrics_refresh_ms)

        self._runtime.start()
        QTimer.singleShot(0, self.refresh_cameras)

    def _build_ui(self, log_path: str) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._preview = QLabel("Searching for camera candidates…")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(640, 360)
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview.setStyleSheet(
            "QLabel { background: #17191d; color: #c9cdd4; "
            "border: 1px solid #343840; border-radius: 6px; }"
        )
        layout.addWidget(self._preview, stretch=1)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Camera:"))
        self._camera_selector = QComboBox()
        self._camera_selector.setEnabled(False)
        self._camera_selector.currentIndexChanged.connect(self._select_camera)
        selector_row.addWidget(self._camera_selector, stretch=1)
        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.clicked.connect(self.refresh_cameras)
        selector_row.addWidget(self._refresh_button)
        layout.addLayout(selector_row)

        metrics = QGridLayout()
        self._capture_fps = QLabel("0.0 FPS")
        self._display_fps = QLabel("0.0 FPS")
        self._processing_ms = QLabel("0.000 ms")
        self._dropped_frames = QLabel("0")
        metrics.addWidget(QLabel("Capture FPS:"), 0, 0)
        metrics.addWidget(self._capture_fps, 0, 1)
        metrics.addWidget(QLabel("Display FPS:"), 0, 2)
        metrics.addWidget(self._display_fps, 0, 3)
        metrics.addWidget(QLabel("Processing:"), 1, 0)
        metrics.addWidget(self._processing_ms, 1, 1)
        metrics.addWidget(QLabel("Replaced frames:"), 1, 2)
        metrics.addWidget(self._dropped_frames, 1, 3)
        layout.addLayout(metrics)

        self._status = QLabel("Starting…")
        self._status.setWordWrap(True)
        self._status.setToolTip(f"Local log: {log_path}")
        layout.addWidget(self._status)
        self.setCentralWidget(root)

    @Slot()
    def refresh_cameras(self) -> None:
        if self._closing or self._discovery.is_running:
            return
        self._refresh_pending = True
        # Remember the camera in use so a refresh keeps it (and its open handle).
        current = self._camera_selector.currentIndex()
        if 0 <= current < len(self._devices):
            self._preferred_index = self._devices[current].index
        self._runtime.select_camera(None)
        self._clear_preview("Searching for camera candidates…")
        self._camera_selector.setEnabled(False)
        self._refresh_button.setEnabled(False)
        # Probing starts only once the worker has released its camera, which
        # can take as long as the driver call it is inside; say so.
        self._status.setText("Status: releasing camera before probing…")

    @Slot()
    def _start_discovery(self) -> None:
        if self._closing or not self._refresh_pending:
            return
        self._refresh_pending = False
        if self._discovery.start(self._preferred_index):
            self._status.setText("Status: probing OpenCV camera indexes…")
        else:
            self._refresh_button.setEnabled(True)

    @Slot(object)
    def _on_discovery_finished(self, result: DiscoveryResult) -> None:
        if self._closing:
            # The discovery service closes an unclaimed prepared camera on stop.
            return
        devices = result.devices
        self._devices = devices
        self._refresh_pending = False
        selected = 0
        if result.prepared is not None and result.prepared.device in devices:
            selected = devices.index(result.prepared.device)
        elif self._preferred_index is not None:
            for position, device in enumerate(devices):
                if device.index == self._preferred_index:
                    selected = position
                    break
        self._camera_selector.blockSignals(True)
        self._camera_selector.clear()
        for device in devices:
            self._camera_selector.addItem(device.display_name)
        if not devices:
            self._camera_selector.addItem("No validated camera candidates")
        else:
            self._camera_selector.setCurrentIndex(selected)
        self._camera_selector.blockSignals(False)
        self._camera_selector.setEnabled(bool(devices))
        self._refresh_button.setEnabled(True)
        if devices:
            self._select_camera(selected, result.prepared)
        else:
            self._status.setText(
                "Status: no camera produced a validation frame. Check Windows "
                "camera privacy settings, connections, then Refresh."
            )
            self._clear_preview("No validated camera available")

    @Slot(str)
    def _on_discovery_error(self, message: str) -> None:
        if self._closing:
            return
        self._refresh_pending = False
        self._camera_selector.setEnabled(False)
        self._refresh_button.setEnabled(True)
        self._status.setText(f"Status: camera probing failed: {message}")
        self._clear_preview("Camera probing failed")

    @Slot(int)
    def _select_camera(
        self, index: int, prepared: PreparedCamera | None = None
    ) -> None:
        if self._closing or not 0 <= index < len(self._devices):
            return
        self._last_output_sequence = 0
        self._runtime.select_camera(self._devices[index], prepared)
        self._clear_preview(
            "Starting selected camera…" if prepared else "Opening selected camera…"
        )

    @Slot(object)
    def _on_capture_status(self, status: CaptureStatus) -> None:
        if self._closing:
            return
        if 0 <= status.request_id < self._runtime.current_request_id:
            # A status for a camera request the user has already replaced.
            return
        self._status.setText(f"Status: {status.message}")
        if status.state is CaptureState.IDLE and self._refresh_pending:
            QTimer.singleShot(0, self._start_discovery)
        if status.state in {
            CaptureState.ERROR,
            CaptureState.RETRYING,
            CaptureState.STOPPED,
        }:
            self._clear_preview(status.message)

    @Slot()
    def _present_latest_frame(self) -> None:
        item = self._runtime.consume_latest_output(self._last_output_sequence)
        if item is None:
            return
        self._last_output_sequence = item.sequence
        frame = item.value.frame
        if frame.ndim != 3 or frame.shape[2] != 3:
            logger.error(
                "Unsupported preview frame shape",
                extra={"event": "preview_frame_invalid", "shape": frame.shape},
            )
            return
        height, width, _ = frame.shape
        image = QImage(
            frame.data,
            width,
            height,
            int(frame.strides[0]),
            QImage.Format.Format_BGR888,
        ).copy()
        self._last_image = image
        self._preview.setPixmap(
            QPixmap.fromImage(image).scaled(
                self._preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )
        self._runtime.record_display()
        if not self._first_frame_presented:
            self._first_frame_presented = True
            logger.info(
                "First camera frame presented in preview",
                extra={
                    "event": "preview_first_frame",
                    "width": width,
                    "height": height,
                },
            )

    @Slot()
    def _refresh_metrics(self) -> None:
        metrics = self._runtime.metrics()
        self._capture_fps.setText(f"{metrics.capture_fps:.1f} FPS")
        self._display_fps.setText(f"{metrics.display_fps:.1f} FPS")
        self._processing_ms.setText(f"{metrics.processing_ms:.3f} ms")
        replacements = metrics.capture_replacements + metrics.output_replacements
        self._dropped_frames.setText(str(replacements))

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self._last_image is not None:
            self._preview.setPixmap(
                QPixmap.fromImage(self._last_image).scaled(
                    self._preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self._preview_timer.stop()
        self._metrics_timer.stop()
        # Disappear immediately; the joins below may wait on a camera driver.
        self.hide()
        metrics = self._runtime.metrics()
        logger.info(
            "Runtime metrics at shutdown",
            extra={
                "event": "runtime_metrics",
                "capture_fps": metrics.capture_fps,
                "display_fps": metrics.display_fps,
                "processing_ms": metrics.processing_ms,
                "captured_frames": metrics.captured_frames,
                "displayed_frames": metrics.displayed_frames,
                "read_failures": metrics.read_failures,
                "capture_replacements": metrics.capture_replacements,
                "output_replacements": metrics.output_replacements,
            },
        )
        # Signal discovery first so both workers wind down concurrently, then
        # bound the whole close by one join timeout instead of two in sequence.
        # Every wait below is bounded by that deadline and none of them
        # releases a camera on this thread: the capture worker releases its
        # own camera, and unadopted prepared cameras go to the cleanup thread.
        deadline = time.perf_counter() + self._settings.worker_join_timeout_s
        self._discovery.request_stop()
        pipeline_stopped = self._runtime.stop()
        discovery_stopped = self._discovery.join(
            max(0.0, deadline - time.perf_counter())
        )
        runtime_cleanup_done = self._runtime.join_cleanup(
            max(0.0, deadline - time.perf_counter())
        )
        discovery_cleanup_done = self._discovery_closer.join(
            max(0.0, deadline - time.perf_counter())
        )
        if not discovery_stopped:
            logger.error(
                "Discovery worker did not stop before timeout",
                extra={"event": "discovery_shutdown_timeout"},
            )
        if not pipeline_stopped:
            # The runtime stays STOPPING while the abandoned worker is alive;
            # it is a daemon thread and ends with the process. Nothing here
            # waits on it further, so the window never blocks the UI thread
            # beyond the single join deadline above.
            logger.error(
                "Pipeline worker did not stop before timeout",
                extra={
                    "event": "pipeline_shutdown_timeout",
                    "runtime_state": self._runtime.state.value,
                },
            )
        if not (runtime_cleanup_done and discovery_cleanup_done):
            # Say which owner still has work; each count is that owner's own.
            logger.error(
                "Prepared camera release still outstanding at close",
                extra={
                    "event": "prepared_cleanup_timeout",
                    "runtime_cleanup_outstanding": self._runtime.cleanup_outstanding,
                    "discovery_cleanup_outstanding": self._discovery_closer.outstanding,
                },
            )
        event.accept()

    def _clear_preview(self, message: str) -> None:
        self._last_image = None
        self._preview.clear()
        self._preview.setText(message)
