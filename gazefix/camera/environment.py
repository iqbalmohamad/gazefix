"""OpenCV capture environment switches, exported before ``cv2`` is imported.

This module must stay free of ``cv2`` imports. On Windows an OpenCV build that
links the C runtime statically reads the process environment into its own copy
when the DLL loads, so a variable set after ``import cv2`` may never reach it.
Entry points therefore call ``apply_capture_environment`` first and import the
OpenCV-backed modules afterwards.
"""

from __future__ import annotations

import os
import sys
from typing import MutableMapping

from gazefix.config import AppSettings


MSMF_HW_TRANSFORMS_ENV = "OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"


def apply_capture_environment(
    settings: AppSettings,
    environ: MutableMapping[str, str] | None = None,
    platform: str | None = None,
) -> dict[str, str]:
    """Export OpenCV capture environment switches before any camera is opened.

    OpenCV's Media Foundation backend reads ``OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS``
    each time it creates a source reader (``cap_msmf.cpp``, ``getDefaultSourceConfig``)
    and forwards it as ``MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS``. With the OpenCV
    default (enabled) Media Foundation loads and negotiates hardware transform
    filters during ``VideoCapture.open``, which is the documented cause of very slow
    MSMF camera opens on some Windows machines (OpenCV issue #17687, addressed by
    adding this switch in OpenCV 4.5.3). Frame delivery itself does not depend on it.

    The variable only matters on Windows, so nothing is exported elsewhere. Call
    this before ``cv2`` is imported (see the module docstring). Returns the
    variables that were exported so callers can log them.
    """

    current_platform = sys.platform if platform is None else platform
    target = os.environ if environ is None else environ
    if current_platform != "win32":
        return {}
    value = "1" if settings.msmf_hw_transforms else "0"
    target[MSMF_HW_TRANSFORMS_ENV] = value
    return {MSMF_HW_TRANSFORMS_ENV: value}
