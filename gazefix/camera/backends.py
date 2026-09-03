"""Platform-localized OpenCV backend policy."""

from __future__ import annotations

import sys

import cv2

from gazefix.camera.models import CameraBackend


def default_camera_backends(platform: str | None = None) -> tuple[CameraBackend, ...]:
    """Return ordered camera backends, preferring MSMF then DirectShow on Windows."""

    current_platform = sys.platform if platform is None else platform
    if current_platform == "win32":
        return (
            CameraBackend(cv2.CAP_MSMF, "MSMF"),
            CameraBackend(cv2.CAP_DSHOW, "DSHOW"),
        )
    return (CameraBackend(cv2.CAP_ANY, "ANY"),)


def ordered_backends_for_device(
    device_backend: CameraBackend | None,
    platform: str | None = None,
) -> tuple[CameraBackend, ...]:
    defaults = default_camera_backends(platform)
    if device_backend is None:
        return defaults
    return (device_backend,) + tuple(
        backend
        for backend in defaults
        if backend.api_preference != device_backend.api_preference
    )

