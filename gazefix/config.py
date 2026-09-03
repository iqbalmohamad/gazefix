"""Central application settings for the Milestone 0 prototype."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path


def default_log_directory() -> Path:
    """Return a per-user, local-only log directory appropriate for Windows."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "state"
    return base / "GazeFix" / "logs"


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
        return replace(self, log_level=self.log_level.upper())

