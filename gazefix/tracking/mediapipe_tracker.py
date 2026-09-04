"""MediaPipe Face Landmarker backend behind the ``FaceTracker`` protocol.

This is the only module that imports MediaPipe, and it does so lazily inside
``create_mediapipe_tracker`` so that importing GazeFix never pays the cost
(about half a second, plus OpenCV and matplotlib) or fails when the native
library cannot load. The factory runs on the tracker thread.

Backend facts the adapter relies on (verified against mediapipe 1.0.1):

- ``FaceLandmarker`` runs every native call on its own dispatcher thread and
  blocks the caller; a call after ``close()`` returns an empty result instead
  of raising, so this adapter tracks its own closed state.
- ``detect_for_video`` needs strictly increasing millisecond timestamps.
- The CPU delegate is selected explicitly; no GPU, NPU or network is used.
  The image passed to the backend is a fresh RGB copy of the frame.
- With ``output_face_blendshapes`` disabled the backend produces landmarks
  and the facial transformation matrix only; the blendshape model, which
  includes eye-direction categories, is never run.
"""

from __future__ import annotations

import importlib.metadata
import logging
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

from gazefix.config import AppSettings
from gazefix.tracking.assets import FACE_LANDMARKER, ModelAssetError, VerifiedModel, verify_model
from gazefix.tracking.tracker import (
    Frame,
    RawDetection,
    RawFace,
    TrackerClosedError,
    TrackerFactory,
    TrackerInitializationError,
)


logger = logging.getLogger(__name__)


class MediaPipeFaceTracker:
    """One ``FaceLandmarker`` in VIDEO mode; owned and used by a single thread."""

    def __init__(
        self,
        landmarker: Any,
        image_class: Any,
        image_format: Any,
        cv2_module: Any,
        thresholds: tuple[float, float, float],
        description: str,
    ) -> None:
        self._landmarker = landmarker
        self._image_class = image_class
        self._image_format = image_format
        self._cv2 = cv2_module
        self._thresholds = thresholds
        self._description = description
        self._last_timestamp_ms: int | None = None
        self._closed = False

    @property
    def description(self) -> str:
        return self._description

    @property
    def backend_thresholds(self) -> tuple[float, float, float]:
        return self._thresholds

    def detect(self, frame_bgr: Frame, timestamp_ms: int) -> RawDetection:
        if self._closed:
            raise TrackerClosedError("MediaPipe tracker used after close")
        started = time.perf_counter()
        # A new contiguous RGB array: the capture frame is read-only and shared.
        rgb = self._cv2.cvtColor(frame_bgr, self._cv2.COLOR_BGR2RGB)
        image = self._image_class(image_format=self._image_format, data=rgb)
        stamp = int(timestamp_ms)
        if self._last_timestamp_ms is not None and stamp <= self._last_timestamp_ms:
            stamp = self._last_timestamp_ms + 1
        self._last_timestamp_ms = stamp
        result = self._landmarker.detect_for_video(image, stamp)
        faces = []
        matrices = list(getattr(result, "facial_transformation_matrixes", None) or [])
        for index, face in enumerate(result.face_landmarks or []):
            points = np.fromiter(
                (value for landmark in face for value in (landmark.x, landmark.y, landmark.z)),
                dtype=np.float32,
            ).reshape(-1, 3)
            transform = None
            if index < len(matrices):
                matrix = np.asarray(matrices[index], dtype=np.float32)
                transform = matrix if matrix.shape == (4, 4) else None
            faces.append(RawFace(landmarks=points, transform=transform))
        inference_ms = (time.perf_counter() - started) * 1000.0
        iris_available = bool(faces) and all(f.landmarks.shape[0] == 478 for f in faces)
        return RawDetection(tuple(faces), inference_ms, iris_available)

    def reset(self) -> None:
        """Drop the backend's face-tracking state without rebuilding it.

        In video mode the landmarker re-uses the previous face region until
        the face presence check fails. Feeding one small black frame makes
        that check fail, so the next real frame runs the face detector
        first, exactly as on a fresh instance. The black frame is synthetic
        (no camera pixels) and costs a few milliseconds; rebuilding would
        cost a model load and a ``close()``.
        """

        if self._closed:
            raise TrackerClosedError("MediaPipe tracker used after close")
        blank = np.zeros((64, 64, 3), dtype=np.uint8)
        self.detect(blank, (self._last_timestamp_ms or 0) + 1)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        started = time.perf_counter()
        try:
            self._landmarker.close()
        finally:
            logger.info(
                "MediaPipe tracker closed",
                extra={
                    "event": "tracker_closed",
                    "close_ms": round((time.perf_counter() - started) * 1000.0, 1),
                },
            )


def create_mediapipe_tracker(settings: AppSettings, model_path: Path | None = None) -> MediaPipeFaceTracker:
    """Verify the model, import MediaPipe, and build a CPU video-mode landmarker.

    Raises ``TrackerInitializationError``; ``retryable`` is ``False`` for a
    missing/invalid model or an import failure (a retry cannot fix those
    without user action) and ``True`` for a runtime failure of the backend.
    """

    path = model_path or FACE_LANDMARKER.path_in(settings.model_directory)
    started = time.perf_counter()
    try:
        verified: VerifiedModel = verify_model(path)
    except ModelAssetError as exc:
        raise TrackerInitializationError(str(exc), retryable=False, kind=f"model_{exc.kind}") from exc
    verify_ms = (time.perf_counter() - started) * 1000.0

    _warn_about_duplicate_opencv()
    # MediaPipe's audio package imports ``sounddevice`` at import time and
    # tolerates its absence; registering ``None`` makes that import fail
    # cleanly so PortAudio is never loaded or initialised (GazeFix uses no
    # audio, and on Windows the bundled PortAudio DLL would otherwise be
    # loaded and initialised inside the import).
    sys.modules.setdefault("sounddevice", None)  # type: ignore[assignment]
    try:
        import cv2  # already loaded by the camera modules; kept explicit
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core import base_options as base_options_module
    except Exception as exc:  # ImportError, OSError from a native library, ...
        raise TrackerInitializationError(
            f"MediaPipe could not be imported ({type(exc).__name__}: {exc}). Install the "
            "project dependencies (`pip install -e .`) and, on Linux, the libEGL/libGLESv2 "
            "system libraries.",
            retryable=False,
            kind="import",
        ) from exc

    thresholds = (
        settings.tracking_min_detection_confidence,
        settings.tracking_min_presence_confidence,
        settings.tracking_min_tracking_confidence,
    )
    try:
        base_options = base_options_module.BaseOptions(
            model_asset_path=str(verified.path),
            delegate=base_options_module.BaseOptions.Delegate.CPU,
        )
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=settings.tracking_max_faces,
            min_face_detection_confidence=thresholds[0],
            min_face_presence_confidence=thresholds[1],
            min_tracking_confidence=thresholds[2],
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=True,
        )
        landmarker = vision.FaceLandmarker.create_from_options(options)
    except Exception as exc:
        raise TrackerInitializationError(
            f"MediaPipe face landmarker could not be created ({type(exc).__name__}: {exc})",
            retryable=True,
            kind="create",
        ) from exc
    init_ms = (time.perf_counter() - started) * 1000.0
    version = getattr(mp, "__version__", "unknown")
    description = f"mediapipe {version} FaceLandmarker CPU, {FACE_LANDMARKER.version}"
    logger.info(
        "MediaPipe tracker created",
        extra={
            "event": "tracker_created",
            "mediapipe_version": version,
            "model_path": str(verified.path),
            "model_sha256": verified.sha256,
            "model_version": FACE_LANDMARKER.version,
            "delegate": "CPU",
            "num_faces": settings.tracking_max_faces,
            "thresholds": thresholds,
            "verify_ms": round(verify_ms, 1),
            "init_ms": round(init_ms, 1),
        },
    )
    return MediaPipeFaceTracker(
        landmarker, mp.Image, mp.ImageFormat.SRGB, cv2, thresholds, description
    )


def installed_opencv_distributions() -> list[str]:
    """Names of the OpenCV distributions present in this environment."""

    names = set()
    for distribution in importlib.metadata.distributions():
        name = (distribution.metadata["Name"] or "").lower()
        if name.startswith("opencv-"):
            names.add(name)
    return sorted(names)


def _warn_about_duplicate_opencv() -> None:
    """Two OpenCV distributions share one ``cv2`` directory; pip does not notice.

    Upgrading an M0 environment in place installs opencv-contrib-python over
    opencv-python; both remain registered, ``pip check`` stays silent, and a
    later uninstall of either breaks ``cv2``. Say so once, in the log.
    """

    try:
        installed = installed_opencv_distributions()
    except Exception:  # noqa: BLE001  (diagnostic only)
        return
    if len(installed) > 1:
        logger.warning(
            "More than one OpenCV distribution is installed; they overwrite the "
            "same cv2 package. Recreate the virtual environment or uninstall the "
            "extra distributions and reinstall opencv-contrib-python.",
            extra={"event": "opencv_duplicate_distributions", "distributions": installed},
        )


def mediapipe_tracker_factory(settings: AppSettings) -> TrackerFactory:
    def factory() -> MediaPipeFaceTracker:
        return create_mediapipe_tracker(settings)

    return factory
