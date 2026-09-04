"""Central application settings (M0 camera pipeline and M1 tracking)."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path


def _local_app_data() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return Path(local_app_data) if local_app_data else Path.home() / ".local" / "state"


def default_log_directory() -> Path:
    """Return a per-user, local-only log directory appropriate for Windows."""

    return _local_app_data() / "GazeFix" / "logs"


def default_model_directory() -> Path:
    """Per-user directory that holds the verified face landmarker model.

    ``%LOCALAPPDATA%\\GazeFix\\models`` on Windows; the model is placed there
    by the explicit setup command and read from there at runtime.
    """

    return _local_app_data() / "GazeFix" / "models"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Small, validated collection of runtime settings.

    The class deliberately contains only foundation settings. Future processing
    options can be added here without scattering constants across the UI and
    camera modules.

    ``discovery_validation_reads`` and ``open_validation_timeout_s`` bound the
    frame reads every camera open performs before it is considered successful;
    a backend that opens but never delivers a frame is treated as an open
    failure so the next backend is tried. A failed read that took longer than
    ``stalled_read_s`` (Media Foundation waits 10 s internally) counts as a
    stall and triggers a reopen at once instead of one transient failure.
    Repeated open failures back off from ``reconnect_delay_s`` up to
    ``reconnect_delay_max_s``.
    ``msmf_hw_transforms`` controls OpenCV's Media Foundation hardware-transform
    negotiation (``OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS``); it is off by
    default because it is the documented cause of multi-second MSMF opens.

    Tracking (M1): ``tracking_wait_ms`` bounds how long the processor thread
    waits for a frame's own tracking result before publishing the frame
    untracked (the wait never cancels the native call; it only stops
    waiting). ``tracking_max_faces`` is how many faces the backend may report
    so that primary-face selection has a second candidate; only the primary
    face is output. The ``tracking_min_*_confidence`` values are the backend's
    own internal thresholds. ``tracking_min_quality`` and
    ``tracking_min_eye_width_px`` decide ``TRACKED`` versus ``LOW_QUALITY``
    (see docs/tracking.md). ``tracking_smoothing`` (0 = off) sets the
    velocity-adaptive landmark smoothing strength. Tracker initialisation is
    retried with exponential backoff from ``tracking_init_retry_s`` to
    ``tracking_init_retry_max_s`` for at most ``tracking_init_max_attempts``
    per camera generation; ``tracking_max_consecutive_errors`` inference
    failures in a row rebuild the tracker. ``tracking_join_timeout_s`` bounds
    the wait for the tracker thread at shutdown.
    """

    capture_width: int = 1280
    capture_height: int = 720
    target_fps: float = 30.0
    camera_probe_limit: int = 5
    preview_poll_ms: int = 15
    metrics_refresh_ms: int = 500
    transient_read_failures: int = 5
    read_retry_delay_s: float = 0.05
    stalled_read_s: float = 2.0
    reconnect_delay_s: float = 1.0
    reconnect_delay_max_s: float = 5.0
    worker_join_timeout_s: float = 5.0
    discovery_validation_reads: int = 3
    open_validation_timeout_s: float = 3.0
    msmf_hw_transforms: bool = False
    log_level: str = "INFO"
    log_directory: Path = default_log_directory()
    developer_mode: bool = False
    tracking_enabled: bool = True
    overlay_enabled: bool = False
    model_directory: Path = default_model_directory()
    tracking_wait_ms: int = 200
    tracking_max_faces: int = 2
    tracking_min_detection_confidence: float = 0.5
    tracking_min_presence_confidence: float = 0.5
    tracking_min_tracking_confidence: float = 0.5
    tracking_min_quality: float = 0.5
    tracking_min_eye_width_px: float = 12.0
    tracking_smoothing: float = 0.5
    tracking_init_retry_s: float = 2.0
    tracking_init_retry_max_s: float = 30.0
    tracking_init_max_attempts: int = 5
    tracking_max_consecutive_errors: int = 3
    tracking_join_timeout_s: float = 1.0

    def validated(self) -> "AppSettings":
        if self.capture_width <= 0 or self.capture_height <= 0:
            raise ValueError("Capture dimensions must be positive")
        if self.target_fps <= 0:
            raise ValueError("Target FPS must be positive")
        if not 1 <= self.camera_probe_limit <= 32:
            raise ValueError("Camera probe limit must be between 1 and 32")
        if self.preview_poll_ms <= 0 or self.metrics_refresh_ms <= 0:
            raise ValueError("Timer intervals must be positive")
        if self.transient_read_failures < 1:
            raise ValueError("Transient read failure limit must be positive")
        if self.read_retry_delay_s < 0 or self.reconnect_delay_s < 0:
            raise ValueError("Retry delays cannot be negative")
        if self.reconnect_delay_max_s < self.reconnect_delay_s:
            raise ValueError("Maximum reconnect delay cannot be below the initial delay")
        if self.stalled_read_s <= 0 or self.open_validation_timeout_s <= 0:
            raise ValueError("Stall and validation timeouts must be positive")
        if self.worker_join_timeout_s <= 0:
            raise ValueError("Worker join timeout must be positive")
        if self.discovery_validation_reads < 1:
            raise ValueError("Discovery validation reads must be positive")
        if self.tracking_wait_ms <= 0:
            raise ValueError("Tracking wait must be positive")
        if not 1 <= self.tracking_max_faces <= 4:
            raise ValueError("Tracking max faces must be between 1 and 4")
        for name in (
            "tracking_min_detection_confidence",
            "tracking_min_presence_confidence",
            "tracking_min_tracking_confidence",
            "tracking_min_quality",
            "tracking_smoothing",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.tracking_min_eye_width_px < 0:
            raise ValueError("Minimum eye width cannot be negative")
        if self.tracking_init_retry_s <= 0 or self.tracking_init_retry_max_s < self.tracking_init_retry_s:
            raise ValueError("Tracker retry delays must be positive and ordered")
        if self.tracking_init_max_attempts < 1 or self.tracking_max_consecutive_errors < 1:
            raise ValueError("Tracker attempt limits must be positive")
        if self.tracking_join_timeout_s <= 0:
            raise ValueError("Tracker join timeout must be positive")
        return replace(self, log_level=self.log_level.upper())

