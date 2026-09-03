"""Camera value objects independent of the UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class CameraBackend:
    api_preference: int
    name: str


@dataclass(frozen=True, slots=True)
class CameraDevice:
    """A validated numerical OpenCV camera candidate.

    ``index`` is not an authoritative operating-system device identifier. It is
    the index which OpenCV successfully opened and read during this run.
    """

    index: int
    validated_backend: CameraBackend | None = None

    @property
    def display_name(self) -> str:
        suffix = (
            f" — {self.validated_backend.name} validated"
            if self.validated_backend
            else ""
        )
        return f"Camera index {self.index}{suffix}"


@dataclass(frozen=True, slots=True)
class CameraOpenResult:
    backend: CameraBackend
    reported_backend: str
    width: int
    height: int
    fps: float


class CaptureState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    RETRYING = "retrying"
    ERROR = "error"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class CaptureStatus:
    state: CaptureState
    message: str
    camera: CameraDevice | None = None
    open_result: CameraOpenResult | None = None

