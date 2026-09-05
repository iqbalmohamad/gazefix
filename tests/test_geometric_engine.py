from dataclasses import replace

import numpy as np
import pytest

from correction_fakes import correction_scene, render_eyes
from gazefix.correction import geometry, masks
from gazefix.correction.geometric import GeometricCorrectionEngine as Engine, GeometricCorrectionSettings as Settings, geometric_engine_factory
from gazefix.correction.models import CorrectionStatus as Status
from gazefix.gaze.models import direction_from_angles, GazeStatus
from gazefix.tracking.models import FrameGeometry, TrackingStatus


def inputs():
    tracking = correction_scene(realistic=True)
    return render_eyes(tracking), tracking, direction_from_angles(0, 15)


def test_success_ownership_repeatability_and_metadata():
    frame, tracking, target = inputs()
    before = frame.copy()
    engine = Engine(Settings(debug=True), clock_ns=lambda: 0)
    output = engine.correct(frame, tracking, target, .75)
    assert output.result.status is Status.CORRECTED, output.result
    assert output.frame is not frame and not np.shares_memory(output.frame, frame)
    assert output.frame.flags.writeable and output.frame.shape == frame.shape and output.frame.dtype == frame.dtype
    assert np.array_equal(frame, before) and not np.array_equal(output.frame, frame)
    assert [e.side for e in output.result.eyes] == ["right", "left"]
    assert output.result.compositing_ms <= output.result.correction_ms
    assert output.result.strength == .75 and output.result.debug is not None
    again = engine.correct(frame, tracking, target, .75)
    assert np.array_equal(output.frame, again.frame) and output.result == again.result
    engine.reset()
    assert np.array_equal(output.frame, engine.correct(frame, tracking, target, .75).frame)
    engine.close(); engine.close(); engine.reset()
    closed = engine.correct(frame, tracking, target, .75)
    assert closed.frame is frame and closed.result.message == "engine closed"
    assert geometric_engine_factory()() is not geometric_engine_factory()()


@pytest.mark.parametrize("case,message", [
    ("shape", "unsupported frame"), ("size", "geometry mismatch"), ("mirror", "mirrored coordinates"),
    ("nan", "invalid strength"), ("negative", "invalid strength"), ("over", "invalid strength"),
    ("zero", "strength 0"), ("target", "invalid target"), ("target_nan", "invalid target"),
    ("gaze", "no gaze: missing"), ("low", "no gaze: low_confidence"),
    ("landmarks", "no landmarks"), ("iris", "no iris")])
def test_frame_gates(case, message):
    frame, tr, target = inputs()
    strength = 1.
    if case == "shape": frame = frame[..., 0]
    if case == "size": tr = replace(tr, geometry=FrameGeometry(1, 1))
    if case == "mirror": tr = replace(tr, geometry=replace(tr.geometry, mirrored=True))
    if case in ("nan", "negative", "over", "zero"): strength = {"nan": float("nan"), "negative": -.1, "over": 1.1, "zero": 0}[case]
    if case == "target": target = np.zeros(3)
    if case == "target_nan": target = np.full(3, np.nan)
    if case == "gaze": tr = replace(tr, gaze=None)
    if case == "low": tr = replace(tr, gaze=replace(tr.gaze, status=GazeStatus.LOW_CONFIDENCE))
    if case == "landmarks": tr = replace(tr, status=TrackingStatus.NO_FACE)
    if case == "iris": tr = replace(tr, iris_available=False)
    out = Engine().correct(frame, tr, target, strength)
    assert out.frame is frame and out.result.status is Status.SKIPPED
    assert out.result.message == message and out.result.eyes == ()
    assert out.result.strength == (0 if case in ("nan", "negative", "over") else strength)


def test_gate_order_and_normalized_target():
    f, tr, t = inputs()
    assert Engine().correct(f, replace(tr, gaze=None), np.zeros(3), 0).result.message == "strength 0"
    assert Engine().correct(f[..., 0], tr, np.zeros(3), -1).result.message == "unsupported frame"
    assert np.array_equal(Engine().correct(f, tr, t, 1).frame, Engine().correct(f, tr, t*10, 1).frame)
    low = replace(tr, status=TrackingStatus.LOW_QUALITY)
    assert Engine().correct(f, low, t, 1).result.status is Status.CORRECTED


@pytest.mark.parametrize("pair", [True, False])
def test_pair_rule(pair):
    f, tr, t = inputs()
    tr = replace(tr, right_eye=replace(tr.right_eye, valid=False))
    out = Engine(Settings(pair_coupling=pair)).correct(f, tr, t, 1)
    if pair:
        assert out.frame is f
        assert out.result.message == "both eyes skipped: right eye invalid; left pair skipped: right eye invalid"
    else:
        assert out.result.status is Status.CORRECTED
        assert out.result.eyes[1].status is Status.CORRECTED


def test_wink_and_negligible():
    tr = correction_scene(left_eye_openness=.05)
    f = render_eyes(tr)
    out = Engine().correct(f, tr, direction_from_angles(10, 0), 1)
    assert out.result.status is Status.CORRECTED
    assert out.result.eyes[1].reason == "eye closed"
    out = Engine().correct(f, tr, direction_from_angles(10, 0), .0001)
    assert out.frame is f and out.result.eyes[0].reason == "negligible displacement"


@pytest.mark.parametrize("site,prefix", [("mask", "mask generation failed"), ("remap", "compositing failed"),
    ("second_remap", "compositing failed"), ("second_blend", "compositing failed"), ("geometry", "engine exception")])
def test_atomic_fallback(monkeypatch, site, prefix):
    f, tr, t = inputs()
    before = f.copy()
    module, name = (geometry, "derive_eye") if site == "geometry" else (masks,
        "opening_fields" if site == "mask" else "blend_into" if site == "second_blend" else "sample")
    original = getattr(module, name)
    count = 0
    def fail(*args, **kwargs):
        nonlocal count
        count += 1
        # third sample is left background: right layers already exist.
        limit = 3 if site == "second_remap" else 2 if site == "second_blend" else 1
        if count == limit: raise RuntimeError("injected")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, name, fail)
    out = Engine().correct(f, tr, t, 1)
    assert out.frame is f and np.array_equal(f, before)
    assert out.result.status is Status.FAILED and out.result.message.startswith(prefix)
    assert out.result.correction_ms >= 0
    assert all(e.displacement_px == (0., 0.) for e in out.result.eyes)


@pytest.mark.parametrize("pair", [True, False])
def test_nonfinite_displacement_is_frame_fault(monkeypatch, pair):
    f, tr, t = inputs()
    monkeypatch.setattr(geometry, "displacement", lambda *a: np.array([np.nan, 0]))
    out = Engine(Settings(pair_coupling=pair)).correct(f, tr, t, 1)
    assert out.frame is f and out.result.status is Status.FAILED
    assert len(out.result.eyes) == 2 and out.result.message == "right displacement not finite"


@pytest.mark.parametrize("pitch", [10, 15])
def test_realistic_upward_containment(pitch):
    f, tr, _ = inputs()
    assert Engine().correct(f, tr, direction_from_angles(0, pitch), 1).result.status is Status.CORRECTED
    assert "iris would leave the eye" in Engine().correct(f, tr, direction_from_angles(0, 60), 1).result.message


def test_degenerate_and_closed_contours():
    f, tr, t = inputs()
    p = tr.right_eye.contour.copy(); p[[2, 5]] = p[[5, 2]]
    broken = replace(tr, right_eye=replace(tr.right_eye, contour=p))
    assert Engine().correct(f, broken, t, 1).result.eyes[0].reason == "degenerate contour"
    p = tr.right_eye.contour.copy(); p[:, 1] = p[0, 1]
    closed = replace(tr, right_eye=replace(tr.right_eye, contour=p))
    out = Engine().correct(f, closed, t, 1)
    assert out.result.status is Status.CORRECTED and out.result.eyes[0].reason == "eye closed"
