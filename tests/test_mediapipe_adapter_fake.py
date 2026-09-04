"""The MediaPipe adapter against a fake ``mediapipe`` package.

No model, no native library: the fake records the options the adapter
builds and scripts the results it returns, so the scope-relevant facts
(blendshapes disabled, CPU delegate, video mode), the timestamp rule, the
reset flush and the use-after-close guard are asserted, not just described.
"""

from __future__ import annotations

from dataclasses import replace
import enum
from pathlib import Path
import sys
import types

import numpy as np
import pytest

from gazefix.config import AppSettings
from gazefix.tracking.assets import FACE_LANDMARKER, VerifiedModel
import gazefix.tracking.mediapipe_tracker as adapter_module
from gazefix.tracking.tracker import TrackerClosedError, TrackerInitializationError


class _Landmark:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.x, self.y, self.z = x, y, z


class _Result:
    def __init__(self, faces: list[list[_Landmark]], matrices: list[np.ndarray]) -> None:
        self.face_landmarks = faces
        self.facial_transformation_matrixes = matrices


class _FakeLandmarker:
    instances: list["_FakeLandmarker"] = []

    def __init__(self, options) -> None:  # type: ignore[no-untyped-def]
        self.options = options
        self.calls: list[tuple[object, int]] = []
        self.closed = 0
        self.script: list[_Result] = []
        _FakeLandmarker.instances.append(self)

    @classmethod
    def create_from_options(cls, options):  # type: ignore[no-untyped-def]
        if getattr(options.base_options, "fail", False):
            raise RuntimeError("Unable to open zip archive.")
        return cls(options)

    def detect_for_video(self, image, timestamp_ms: int):  # type: ignore[no-untyped-def]
        if self.calls and timestamp_ms <= self.calls[-1][1]:
            raise ValueError("Input timestamp must be monotonically increasing.")
        self.calls.append((image, timestamp_ms))
        return self.script.pop(0) if self.script else _Result([], [])

    def close(self) -> None:
        self.closed += 1


class _FakeImage:
    def __init__(self, image_format, data) -> None:  # type: ignore[no-untyped-def]
        self.image_format = image_format
        self.data = data


def _install_fake_mediapipe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mp = types.ModuleType("mediapipe")
    mp.__version__ = "fake"
    mp.Image = _FakeImage
    mp.ImageFormat = enum.Enum("ImageFormat", {"SRGB": 1})
    tasks = types.ModuleType("mediapipe.tasks")
    python = types.ModuleType("mediapipe.tasks.python")
    vision = types.ModuleType("mediapipe.tasks.python.vision")
    core = types.ModuleType("mediapipe.tasks.python.core")
    base_options = types.ModuleType("mediapipe.tasks.python.core.base_options")

    class BaseOptions:
        class Delegate(enum.Enum):
            CPU = 0
            GPU = 1

        def __init__(self, model_asset_path=None, delegate=None) -> None:  # type: ignore[no-untyped-def]
            self.model_asset_path = model_asset_path
            self.delegate = delegate
            self.fail = "fail" in str(model_asset_path)

    class FaceLandmarkerOptions:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.__dict__.update(kwargs)

    base_options.BaseOptions = BaseOptions
    vision.FaceLandmarkerOptions = FaceLandmarkerOptions
    vision.RunningMode = enum.Enum("RunningMode", {"IMAGE": 1, "VIDEO": 2, "LIVE_STREAM": 3})
    vision.FaceLandmarker = _FakeLandmarker
    mp.tasks = tasks
    tasks.python = python
    python.vision = vision
    python.core = core
    core.base_options = base_options
    for name, module in (
        ("mediapipe", mp),
        ("mediapipe.tasks", tasks),
        ("mediapipe.tasks.python", python),
        ("mediapipe.tasks.python.vision", vision),
        ("mediapipe.tasks.python.core", core),
        ("mediapipe.tasks.python.core.base_options", base_options),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    _FakeLandmarker.instances.clear()


@pytest.fixture
def fake_backend(monkeypatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    _install_fake_mediapipe(monkeypatch)
    model_path = FACE_LANDMARKER.path_in(tmp_path)
    monkeypatch.setattr(
        adapter_module,
        "verify_model",
        lambda path, manifest=FACE_LANDMARKER: VerifiedModel(manifest, Path(path), manifest.size_bytes, manifest.sha256),
    )
    return replace(AppSettings(), model_directory=tmp_path, tracking_max_faces=2)


def _face(count: int = 478) -> list[_Landmark]:
    return [_Landmark(0.5 + i * 1e-4, 0.5, -0.01) for i in range(count)]


def test_adapter_builds_cpu_video_options_without_blendshapes(fake_backend) -> None:  # type: ignore[no-untyped-def]
    tracker = adapter_module.create_mediapipe_tracker(fake_backend)
    options = _FakeLandmarker.instances[0].options
    assert options.output_face_blendshapes is False  # eye-look categories are never computed
    assert options.output_facial_transformation_matrixes is True
    assert options.num_faces == 2
    assert options.running_mode.name == "VIDEO"
    assert options.base_options.delegate.name == "CPU"
    assert (
        options.min_face_detection_confidence,
        options.min_face_presence_confidence,
        options.min_tracking_confidence,
    ) == tracker.backend_thresholds == (0.5, 0.5, 0.5)
    assert "FaceLandmarker CPU" in tracker.description
    assert sys.modules.get("sounddevice", "missing") is None  # PortAudio import blocked
    tracker.close()


def test_detect_converts_to_rgb_copies_and_keeps_timestamps_strictly_increasing(fake_backend) -> None:  # type: ignore[no-untyped-def]
    tracker = adapter_module.create_mediapipe_tracker(fake_backend)
    landmarker = _FakeLandmarker.instances[0]
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    frame[..., 0] = 200  # blue in BGR
    frame.setflags(write=False)
    landmarker.script = [_Result([_face()], [np.eye(4, dtype=np.float32)]), _Result([_face()], []), _Result([_face(468)], [])]
    first = tracker.detect(frame, 10)
    second = tracker.detect(frame, 10)  # equal timestamp is bumped, not rejected
    third = tracker.detect(frame, 5)  # smaller timestamp is bumped as well
    assert [ts for _, ts in landmarker.calls] == [10, 11, 12]
    image = landmarker.calls[0][0]
    assert image.image_format.name == "SRGB"
    assert image.data[0, 0].tolist() == [0, 0, 200]  # BGR -> RGB
    assert image.data is not frame and not frame.flags.writeable
    assert first.faces[0].landmarks.shape == (478, 3) and first.faces[0].transform.shape == (4, 4)
    assert first.iris_available and second.faces[0].transform is None
    assert not third.iris_available and third.faces[0].landmarks.shape == (468, 3)
    assert first.inference_ms >= 0.0
    tracker.close()


def test_reset_flushes_with_a_black_frame_and_close_is_guarded(fake_backend) -> None:  # type: ignore[no-untyped-def]
    tracker = adapter_module.create_mediapipe_tracker(fake_backend)
    landmarker = _FakeLandmarker.instances[0]
    frame = np.full((4, 6, 3), 90, dtype=np.uint8)
    tracker.detect(frame, 100)
    tracker.reset()
    assert len(landmarker.calls) == 2
    flushed = landmarker.calls[1][0].data
    assert flushed.shape[2] == 3 and int(flushed.max()) == 0  # synthetic black frame, no camera pixels
    assert landmarker.calls[1][1] == 101
    tracker.close()
    tracker.close()
    assert landmarker.closed == 1
    with pytest.raises(TrackerClosedError):
        tracker.detect(frame, 200)
    with pytest.raises(TrackerClosedError):
        tracker.reset()


def test_backend_creation_failure_is_a_retryable_initialization_error(fake_backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = replace(fake_backend, model_directory=tmp_path / "fail")
    with pytest.raises(TrackerInitializationError) as info:
        adapter_module.create_mediapipe_tracker(settings)
    assert info.value.kind == "create" and info.value.retryable is True
    assert "Unable to open zip archive" in str(info.value)


def test_import_failure_is_non_retryable(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import builtins

    monkeypatch.setattr(
        adapter_module,
        "verify_model",
        lambda path, manifest=FACE_LANDMARKER: VerifiedModel(manifest, Path(path), manifest.size_bytes, manifest.sha256),
    )
    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "mediapipe" or name.startswith("mediapipe."):
            raise OSError("libmediapipe could not be loaded")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    for name in list(sys.modules):
        if name == "mediapipe" or name.startswith("mediapipe."):
            monkeypatch.delitem(sys.modules, name)
    with pytest.raises(TrackerInitializationError) as info:
        adapter_module.create_mediapipe_tracker(replace(AppSettings(), model_directory=tmp_path))
    assert info.value.kind == "import" and info.value.retryable is False
    assert "pip install -e ." in str(info.value)
