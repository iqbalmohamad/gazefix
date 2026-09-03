"""Platform-localized OpenCV backend policy.

``cv2`` is imported lazily so that entry points can export the capture
environment (``gazefix.camera.environment``) before OpenCV loads.
"""

from __future__ import annotations

import sys

from gazefix.camera.environment import (  # noqa: F401  (re-exported)
    MSMF_HW_TRANSFORMS_ENV,
    apply_capture_environment,
)
from gazefix.camera.models import CameraBackend


def default_camera_backends(platform: str | None = None) -> tuple[CameraBackend, ...]:
    """Return ordered camera backends, preferring MSMF then DirectShow on Windows."""

    import cv2

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


def supports_thread_handoff(backend: CameraBackend) -> bool:
    """Whether a capture opened on one thread may be read and released on another.

    OpenCV's DirectShow capture calls ``CoInitialize`` in its constructor and
    ``CoUninitialize`` in its destructor (``cap_dshow.cpp``), which must pair on
    the same thread. Media Foundation initialises COM and MF once per process and
    its source reader is free-threaded, so an MSMF capture can change owner.
    """

    import cv2  # lazy, see module docstring

    return backend.api_preference != cv2.CAP_DSHOW


def next_backend_after(
    backend: CameraBackend | None,
    platform: str | None = None,
) -> CameraBackend | None:
    """Return the backend to prefer after ``backend`` stalled or failed to stream.

    Cycles through the platform order so a Media Foundation source that opened
    but stopped delivering frames is reopened through DirectShow first, and the
    other way round. With a single platform backend there is nothing to rotate
    to and the input is returned unchanged.
    """

    defaults = default_camera_backends(platform)
    if len(defaults) < 2:
        return backend if backend is not None else defaults[0]
    for position, candidate in enumerate(defaults):
        if backend is not None and candidate.api_preference == backend.api_preference:
            return defaults[(position + 1) % len(defaults)]
    return defaults[0]
