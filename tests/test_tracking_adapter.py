"""MediaPipe adapter behaviour that needs no MediaPipe: asset gating and errors."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from gazefix.config import AppSettings
from gazefix.tracking.assets import FACE_LANDMARKER, SETUP_COMMAND
from gazefix.tracking.mediapipe_tracker import create_mediapipe_tracker, mediapipe_tracker_factory
from gazefix.tracking.tracker import TrackerInitializationError


def test_missing_model_is_an_actionable_non_retryable_initialization_error(tmp_path: Path) -> None:
    settings = replace(AppSettings(), model_directory=tmp_path)
    try:
        create_mediapipe_tracker(settings)
    except TrackerInitializationError as exc:
        assert exc.kind == "model_missing"
        assert exc.retryable is False
        assert SETUP_COMMAND in str(exc)
        assert str(FACE_LANDMARKER.path_in(tmp_path)) in str(exc)
    else:
        raise AssertionError("a missing model must fail initialization")


def test_wrong_model_bytes_are_rejected_before_mediapipe_is_imported(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import builtins
    import sys

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "mediapipe" or name.startswith("mediapipe."):
            raise AssertionError("mediapipe must not be imported when the model is invalid")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    sys.modules.pop("mediapipe", None)
    target = FACE_LANDMARKER.path_in(tmp_path)
    target.write_bytes(b"x" * FACE_LANDMARKER.size_bytes)  # right size, wrong content
    settings = replace(AppSettings(), model_directory=tmp_path)
    try:
        create_mediapipe_tracker(settings)
    except TrackerInitializationError as exc:
        assert exc.kind == "model_checksum"
        assert exc.retryable is False
    else:
        raise AssertionError("a corrupt model must fail initialization")


def test_truncated_model_reports_size_mismatch(tmp_path: Path) -> None:
    FACE_LANDMARKER.path_in(tmp_path).write_bytes(b"short")
    try:
        mediapipe_tracker_factory(replace(AppSettings(), model_directory=tmp_path))()
    except TrackerInitializationError as exc:
        assert exc.kind == "model_size"
        assert str(FACE_LANDMARKER.size_bytes) in str(exc)
    else:
        raise AssertionError("a truncated model must fail initialization")
