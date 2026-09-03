"""Minimal, responsive Milestone 0 application window."""

from __future__ import annotations

import logging

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

from gazefix.camera.discovery import CameraDiscoveryService
from gazefix.camera.models import CameraDevice, CaptureState, CaptureStatus
from gazefix.config import AppSettings
from gazefix.pipeline.runtime import PipelineRuntime


logger = logging.getLogger(__name__)


class UiSignals(QObject):
    capture_status = Signal(object)
    discovery_finished = Signal(object)
    discovery_error = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, log_path: str) -> None:
        super().__init__()
        self._settings = settings
        self._signals = UiSignals()
        self._signals.capture_status.connect(self._on_capture_status)
        self._signals.discovery_finished.connect(self._on_discovery_finished)
        self._signals.discovery_error.connect(self._on_discovery_error)

        self._runtime = PipelineRuntime(
            settings, on_status=self._signals.capture_status.emit
        )
        self._discovery = CameraDiscoveryService(
            settings,
            on_finished=self._signals.discovery_finished.emit,
            on_error=self._signals.discovery_error.emit,
        )
        self._devices: list[CameraDevice] = []
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
        self._runtime.select_camera(None)
        self._clear_preview("Searching for camera candidates…")
        self._camera_selector.setEnabled(False)
        self._refresh_button.setEnabled(False)
        self._status.setText("Status: probing OpenCV camera indexes…")

    @Slot()
    def _start_discovery(self) -> None:
        if self._closing or not self._refresh_pending:
            return
        self._refresh_pending = False
        if not self._discovery.start():
            self._refresh_button.setEnabled(True)

    @Slot(object)
    def _on_discovery_finished(self, devices: list[CameraDevice]) -> None:
        if self._closing:
            return
        self._devices = devices
        self._refresh_pending = False
        self._camera_selector.blockSignals(True)
        self._camera_selector.clear()
        for device in devices:
            self._camera_selector.addItem(device.display_name)
        if not devices:
            self._camera_selector.addItem("No validated camera candidates")
        self._camera_selector.blockSignals(False)
        self._camera_selector.setEnabled(bool(devices))
        self._refresh_button.setEnabled(True)
        if devices:
            self._camera_selector.setCurrentIndex(0)
            self._select_camera(0)
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
    def _select_camera(self, index: int) -> None:
        if self._closing or not 0 <= index < len(self._devices):
            return
        self._last_output_sequence = 0
        self._runtime.select_camera(self._devices[index])
        self._clear_preview("Opening selected camera…")

    @Slot(object)
    def _on_capture_status(self, status: CaptureStatus) -> None:
        if self._closing:
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
        discovery_stopped = self._discovery.stop(
            self._settings.worker_join_timeout_s
        )
        pipeline_stopped = self._runtime.stop()
        if not discovery_stopped:
            logger.error(
                "Discovery worker did not stop before timeout",
                extra={"event": "discovery_shutdown_timeout"},
            )
        if not pipeline_stopped:
            logger.error(
                "Pipeline worker did not stop before timeout",
                extra={"event": "pipeline_shutdown_timeout"},
            )
        event.accept()

    def _clear_preview(self, message: str) -> None:
        self._last_image = None
        self._preview.clear()
        self._preview.setText(message)
