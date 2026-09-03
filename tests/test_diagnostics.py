"""Camera diagnostic fidelity against the production open/configure/validate path.

Regression coverage for the M0 carry-forward defect: the diagnostic used to
construct ``cv2.VideoCapture(index, backend)`` and set width, height, FPS,
and buffer size unconditionally, so its timings did not describe what the
application does. It now runs ``open_validated_backend``, the same primitive
``OpenCVCameraSource`` runs per backend, with the same settings.
"""

from __future__ import annotations

from dataclasses import replace
import json
import logging

import cv2
import pytest

from camera_fakes import FakeClock, FakeVideoCapture
from gazefix.camera import diagnostics
from gazefix.camera import source as source_module
from gazefix.camera.diagnostics import BackendProbeResult, probe_backend
from gazefix.camera.environment import MSMF_HW_TRANSFORMS_ENV
from gazefix.camera.models import CameraBackend, CameraDevice
from gazefix.camera.source import OpenCVCameraSource, open_validated_backend
from gazefix.config import AppSettings


MSMF = CameraBackend(cv2.CAP_MSMF, "MSMF")
DSHOW = CameraBackend(cv2.CAP_DSHOW, "DSHOW")
WIDTH, HEIGHT, FPS, BUFFER = (
    cv2.CAP_PROP_FRAME_WIDTH,
    cv2.CAP_PROP_FRAME_HEIGHT,
    cv2.CAP_PROP_FPS,
    cv2.CAP_PROP_BUFFERSIZE,
)


@pytest.fixture
def fake_cv(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    FakeVideoCapture.reset()
    # ``cv2`` is one module object: this reaches the source module's
    # ``cv2.VideoCapture()`` and the diagnostic's lazy import alike.
    monkeypatch.setattr(cv2, "VideoCapture", FakeVideoCapture)
    return FakeVideoCapture


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch, fake_cv) -> FakeClock:  # type: ignore[no-untyped-def]
    clock = FakeClock()
    fake_cv.clock = clock
    monkeypatch.setattr(source_module, "time", clock)
    monkeypatch.setattr(diagnostics, "time", clock)
    return clock


def settings(**overrides: object) -> AppSettings:
    base = dict(
        capture_width=1280,
        capture_height=720,
        target_fps=30.0,
        discovery_validation_reads=3,
        read_retry_delay_s=0.0,
        open_validation_timeout_s=3.0,
    )
    base.update(overrides)
    return replace(AppSettings(), **base)  # type: ignore[arg-type]


def only_backend(monkeypatch: pytest.MonkeyPatch, backend: CameraBackend) -> None:
    monkeypatch.setattr(source_module, "ordered_backends_for_device", lambda _b: (backend,))


@pytest.mark.parametrize("backend", [MSMF, DSHOW], ids=["msmf", "dshow"])
def test_probe_drives_the_device_exactly_like_the_production_open(fake_cv, clock, monkeypatch, backend) -> None:  # type: ignore[no-untyped-def]
    """Same open call, same parameters, same conditional sets, same validation reads."""

    fake_cv.behaviours = {backend.api_preference: "opens"}
    fake_cv.read_cost_s = 0.01
    only_backend(monkeypatch, backend)
    cfg = settings()

    OpenCVCameraSource(cfg).open(CameraDevice(2))
    production = fake_cv.instances[0].calls[:]
    assert production[-1] == ("read",)  # ends with the validation frame, no release yet

    result = probe_backend(2, backend, cfg, duration_s=0.045)  # 5 reads of 10 ms
    diagnostic = fake_cv.instances[1].calls
    assert diagnostic[: len(production)] == production
    assert diagnostic[len(production):] == [("read",)] * 5 + [("release",)]
    assert result.validated and result.successful_reads == 5
    expected_params = [WIDTH, 1280, HEIGHT, 720] if backend is DSHOW else None
    assert production[0] == ("open", 2, backend.api_preference, expected_params)


def test_production_source_and_probe_both_go_through_the_shared_primitive(fake_cv, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {MSMF.api_preference: "opens"}
    only_backend(monkeypatch, MSMF)
    calls: list[tuple[object, ...]] = []
    original = source_module.open_validated_backend

    def recording(capture, index, backend, cfg, interrupted=None):  # type: ignore[no-untyped-def]
        calls.append((capture, index, backend, cfg, interrupted))
        return original(capture, index, backend, cfg, interrupted)

    monkeypatch.setattr(source_module, "open_validated_backend", recording)
    cfg = settings()
    source = OpenCVCameraSource(cfg)
    source.open(CameraDevice(1))
    probe_backend(1, MSMF, cfg, duration_s=0.0)

    assert len(calls) == 2
    assert calls[0] == (fake_cv.instances[0], 1, MSMF, cfg, source._interrupted.is_set)
    assert calls[1] == (fake_cv.instances[1], 1, MSMF, cfg, None)


def test_directshow_probe_passes_size_as_open_parameters_and_msmf_does_not(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {DSHOW.api_preference: "opens", MSMF.api_preference: "opens"}
    cfg = settings(capture_width=640, capture_height=360)
    probe_backend(1, DSHOW, cfg, duration_s=0.0)
    probe_backend(1, MSMF, cfg, duration_s=0.0)
    dshow, msmf = fake_cv.instances
    # FPS is deliberately absent: OpenCV's DirectShow constructor ignores it.
    assert dshow.open_params == [WIDTH, 640, HEIGHT, 360]
    assert msmf.open_params is None


def test_directshow_probe_falls_back_to_plain_open_without_the_params_overload(fake_cv, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {DSHOW.api_preference: "opens"}
    calls: list[tuple[int, int]] = []
    original_open = fake_cv.open

    def two_arg_open(self, index, api):  # type: ignore[no-untyped-def]
        calls.append((index, api))
        return original_open(self, index, api)

    monkeypatch.setattr(fake_cv, "open", two_arg_open)
    result = probe_backend(0, DSHOW, settings(), duration_s=0.0)
    assert result.opened and result.validated
    assert calls == [(0, DSHOW.api_preference)]


def test_probe_sets_only_the_properties_that_differ_and_skips_an_unreported_fps(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {DSHOW.api_preference: "opens"}
    fake_cv.reported = {WIDTH: 1280.0, HEIGHT: 480.0, FPS: 0.0}
    result = probe_backend(0, DSHOW, settings(), duration_s=0.0)
    props = fake_cv.instances[0].props
    assert WIDTH not in props  # camera already reports 1280
    assert props[HEIGHT] == 720.0  # 480 -> 720 had to be set
    assert FPS not in props  # not reported: no graph rebuild for a guess
    assert props[BUFFER] == 1
    assert result.format_sets_applied == 1
    # Negotiated values are what the camera reports after configuration.
    assert (result.width, result.height, result.negotiated_fps) == (1280, 480, 0.0)
    assert result.reported_backend == f"FAKE{DSHOW.api_preference}"


def test_timing_fields_cover_exactly_open_configure_validation_sampling_and_release(fake_cv, clock) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {MSMF.api_preference: "opens"}
    fake_cv.open_cost_s = 0.250
    fake_cv.set_cost_s = 0.010
    fake_cv.read_cost_s = 0.020
    fake_cv.release_cost_s = 0.005

    # 0.09 s sits between the 5th and 6th 20 ms read, so the count is exact.
    result = probe_backend(0, MSMF, settings(), duration_s=0.09)

    assert result.open_ms == 250.0  # the open call alone
    assert result.configure_ms == 30.0  # width, height, buffer hint (FPS already 30)
    assert result.format_sets_applied == 2
    assert result.first_frame_ms == 20.0  # the single validation read
    assert result.validation_reads == 1
    assert result.sample_seconds == pytest.approx(0.1)  # 5 reads of 20 ms
    assert result.successful_reads == 5 and result.failed_reads == 0
    assert result.observed_fps == pytest.approx(50.0)
    assert result.release_ms == 5.0
    assert result.error is None


def test_production_log_timings_share_the_diagnostic_boundaries(fake_cv, clock, monkeypatch, caplog) -> None:  # type: ignore[no-untyped-def]
    """The ``camera_opened`` log and the probe report the same numbers for the same device."""

    fake_cv.behaviours = {MSMF.api_preference: "opens"}
    fake_cv.open_cost_s, fake_cv.set_cost_s, fake_cv.read_cost_s = 0.250, 0.010, 0.020
    only_backend(monkeypatch, MSMF)
    caplog.set_level(logging.INFO, logger="gazefix.camera.source")
    cfg = settings()

    OpenCVCameraSource(cfg).open(CameraDevice(0))
    opened = [r for r in caplog.records if getattr(r, "event", None) == "camera_opened"][-1]
    probe = probe_backend(0, MSMF, cfg, duration_s=0.0)

    for field in ("open_ms", "configure_ms", "first_frame_ms", "format_sets_applied", "validation_reads"):
        assert getattr(opened, field) == getattr(probe, field), field
    assert (opened.open_ms, opened.configure_ms, opened.first_frame_ms) == (250.0, 30.0, 20.0)  # type: ignore[attr-defined]


def test_first_frame_validation_includes_retry_delays_and_counts_reads(fake_cv, clock) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {MSMF.api_preference: "no_frames"}
    fake_cv.read_cost_s = 0.020
    cfg = settings(discovery_validation_reads=3, read_retry_delay_s=0.05)

    result = probe_backend(0, MSMF, cfg, duration_s=0.1)

    assert result.opened and not result.validated
    assert result.validation_reads == 3
    assert result.first_frame_ms == 160.0  # 3 reads of 20 ms plus 2 retry delays of 50 ms
    assert result.error == "opened but produced no validation frame"
    # Production would not use this backend, so nothing is sampled either.
    assert result.successful_reads == 0 and result.failed_reads == 0 and result.sample_seconds == 0.0
    assert result.reported_backend is not None and result.width == 640  # still reported
    assert fake_cv.instances[0].released == 1


def test_first_frame_validation_is_bounded_by_wall_clock(fake_cv, clock) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {MSMF.api_preference: "no_frames"}
    fake_cv.read_cost_s = 0.020
    cfg = settings(discovery_validation_reads=5, read_retry_delay_s=0.05, open_validation_timeout_s=0.03)
    result = probe_backend(0, MSMF, cfg, duration_s=0.1)
    assert result.validation_reads == 1  # the retry delay pushed it past the deadline
    assert not result.validated and fake_cv.instances[0].released == 1


def test_open_failure_is_reported_and_released_without_configuring(fake_cv, clock, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(MSMF_HW_TRANSFORMS_ENV, raising=False)
    fake_cv.open_cost_s = 0.4
    result = probe_backend(3, MSMF, settings(), duration_s=0.1)  # no behaviour: open fails
    assert result == BackendProbeResult(
        3, "MSMF", opened=False, open_ms=400.0, release_ms=0.0, error="open failed"
    )
    capture = fake_cv.instances[0]
    assert capture.props == {} and capture.reads == 0 and capture.released == 1


def test_probe_never_falls_back_to_another_backend(fake_cv, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Documented distinction: each backend is measured on its own."""

    fake_cv.behaviours = {DSHOW.api_preference: "opens"}  # MSMF fails on this device
    monkeypatch.setattr(source_module, "ordered_backends_for_device", lambda _b: (MSMF, DSHOW))
    result = probe_backend(0, MSMF, settings(), duration_s=0.0)
    assert not result.opened and result.error == "open failed"
    assert [c.api for c in fake_cv.instances] == [MSMF.api_preference]  # DSHOW never tried
    # ...whereas production falls through to the next backend for the same device.
    assert OpenCVCameraSource(settings()).open(CameraDevice(0)).backend == DSHOW


def test_probe_releases_and_reports_an_exception_raised_by_the_backend(fake_cv, clock) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {MSMF.api_preference: "opens"}
    fake_cv.read_exception = RuntimeError("driver exploded")
    result = probe_backend(0, MSMF, settings(), duration_s=0.1)
    assert result.opened and not result.validated
    assert result.error == "driver exploded"
    assert fake_cv.instances[0].released == 1


def test_keyboard_interrupt_during_sampling_releases_the_camera_and_propagates(fake_cv, clock, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {MSMF.api_preference: "opens"}
    fake_cv.read_cost_s = 0.01
    original_read = fake_cv.read

    def read_then_interrupt(self):  # type: ignore[no-untyped-def]
        if self.reads == 2:  # validation frame and one sample delivered
            raise KeyboardInterrupt
        return original_read(self)

    monkeypatch.setattr(fake_cv, "read", read_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        probe_backend(0, MSMF, settings(), duration_s=1.0)
    assert fake_cv.instances[0].released == 1


def test_main_returns_130_when_interrupted(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(diagnostics, "default_camera_backends", lambda: (MSMF,))
    monkeypatch.setattr(diagnostics, "apply_capture_environment", lambda _s: {})

    def interrupted_probe(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt

    monkeypatch.setattr(diagnostics, "probe_backend", interrupted_probe)
    assert diagnostics.main(["--max-index", "0", "--duration", "0.1"]) == 130
    assert "released" in capsys.readouterr().out


def test_main_propagates_cli_settings_and_the_hw_transform_switch(fake_cv, clock, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    seen: dict[str, AppSettings] = {}

    def record_environment(cfg: AppSettings) -> dict[str, str]:
        seen["settings"] = cfg
        return {MSMF_HW_TRANSFORMS_ENV: "1"}

    monkeypatch.setattr(diagnostics, "apply_capture_environment", record_environment)
    monkeypatch.setattr(diagnostics, "default_camera_backends", lambda: (MSMF, DSHOW))
    monkeypatch.setenv(MSMF_HW_TRANSFORMS_ENV, "1")
    fake_cv.behaviours = {MSMF.api_preference: "opens", DSHOW.api_preference: "opens"}
    fake_cv.read_cost_s = 0.01

    code = diagnostics.main([
        "--max-index", "0", "--duration", "0.05",
        "--width", "640", "--height", "360", "--fps", "15",
        "--msmf-hw-transforms", "1",
    ])

    assert code == 0
    cfg = seen["settings"]
    assert cfg.msmf_hw_transforms is True
    assert (cfg.capture_width, cfg.capture_height, cfg.target_fps) == (640, 360, 15.0)
    out = capsys.readouterr().out
    rows = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    assert [row["requested_backend"] for row in rows] == ["MSMF", "DSHOW"]
    assert all(row["validated"] and row["msmf_hw_transforms"] == "1" for row in rows)
    assert "Validated index/backend combinations: 2" in out
    # The CLI size reached the production configure step and DirectShow open parameters.
    msmf, dshow = fake_cv.instances
    assert msmf.props[HEIGHT] == 360.0 and msmf.props[FPS] == 15.0
    assert dshow.open_params == [WIDTH, 640, HEIGHT, 360]


def test_main_rejects_invalid_arguments_and_reports_no_validated_backend(fake_cv, clock, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    assert diagnostics.main(["--fps", "0"]) == 2
    assert "Invalid settings" in capsys.readouterr().out
    assert diagnostics.main(["--max-index", "40"]) == 2
    monkeypatch.setattr(diagnostics, "apply_capture_environment", lambda _s: {})
    monkeypatch.setattr(diagnostics, "default_camera_backends", lambda: (MSMF,))
    assert diagnostics.main(["--max-index", "0", "--duration", "0.05"]) == 1  # nothing opens
    assert all(c.released == 1 for c in fake_cv.instances)


def test_open_validated_backend_honours_the_interrupt_at_its_checkpoints(fake_cv) -> None:  # type: ignore[no-untyped-def]
    fake_cv.behaviours = {MSMF.api_preference: "opens"}
    outcome = open_validated_backend(FakeVideoCapture(), 0, MSMF, settings(), interrupted=lambda: True)
    assert outcome.opened and outcome.interrupted and not outcome.validated
    assert outcome.result is None and outcome.configure_ms is None
    assert fake_cv.instances[0].props == {} and fake_cv.instances[0].reads == 0  # skipped after open

    fake_cv.behaviours = {MSMF.api_preference: "no_frames"}
    reads_seen: list[int] = []
    capture = FakeVideoCapture()

    def interrupt_after_first_read() -> bool:
        reads_seen.append(capture.reads)
        return capture.reads >= 1

    outcome = open_validated_backend(capture, 0, MSMF, settings(), interrupt_after_first_read)
    assert outcome.opened and outcome.interrupted and not outcome.validated
    assert outcome.validation_reads == 1 and outcome.result is not None
    assert capture.released == 0  # the caller owns the release decision


def test_diagnostic_needs_no_qt_and_production_never_imports_the_diagnostic() -> None:
    import os
    import subprocess
    import sys

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    diagnostic_side = subprocess.run(
        [sys.executable, "-c",
         "import sys, gazefix.camera.diagnostics, gazefix.camera.source; "
         "raise SystemExit(1 if any(m.startswith('PySide6') for m in sys.modules) else 0)"],
        capture_output=True, text=True, env=env,
    )
    assert diagnostic_side.returncode == 0, diagnostic_side.stderr
    production_side = subprocess.run(
        [sys.executable, "-c",
         "import sys, gazefix.pipeline.runtime, gazefix.ui.main_window; "
         "raise SystemExit(1 if 'gazefix.camera.diagnostics' in sys.modules else 0)"],
        capture_output=True, text=True, env=env,
    )
    assert production_side.returncode == 0, production_side.stderr
