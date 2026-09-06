from dataclasses import replace
import numpy as np
import pytest

from correction_fakes import correction_scene
from gazefix.correction import geometry as geo
from gazefix.gaze.models import direction_from_angles
from gazefix.gaze.estimator import GeometricGazeEstimator, GazeSettings


@pytest.mark.parametrize("head_yaw,head_pitch,eye_yaw,eye_pitch,target_yaw,target_pitch,strength", [
    (0, 0, 15, 0, 0, 0, 1), (0, 0, 0, 15, 0, 0, 1),
    (0, 0, 15, 0, 0, 0, .5), (0, 0, 0, 15, 0, 0, .5),
    (20, 0, -20, 0, 10, 0, 1), (0, 20, 0, 20, 0, 10, 1)])
def test_closed_loop(head_yaw, head_pitch, eye_yaw, eye_pitch, target_yaw, target_pitch, strength):
    tr = correction_scene(head_yaw_deg=head_yaw, head_pitch_deg=head_pitch,
                          eye_yaw_deg=eye_yaw, eye_pitch_deg=eye_pitch)
    target = direction_from_angles(target_yaw, target_pitch)
    change = geo.head_change(tr, target, strength, .5)
    updates = {}
    for side in ("right", "left"):
        eye = getattr(tr, side + "_eye")
        d = geo.displacement(geo.derive_eye(eye, tr.geometry), change, 1.25, 1.)
        iris = eye.iris.copy()
        iris[:, :2] += d / (tr.geometry.width, tr.geometry.height)
        updates[side + "_eye"] = replace(eye, iris=iris)
    recovered = GeometricGazeEstimator(GazeSettings(smoothing=0)).estimate(replace(tr, **updates))
    # A3.3 applies only to the two nonzero rotated-head target rows.
    tolerance = .25 if head_yaw or head_pitch else 1.5
    assert recovered.yaw_deg == pytest.approx(tr.gaze.yaw_deg + strength*(target_yaw-tr.gaze.yaw_deg), abs=tolerance)
    assert recovered.pitch_deg == pytest.approx(tr.gaze.pitch_deg + strength*(target_pitch-tr.gaze.pitch_deg), abs=tolerance)


@pytest.mark.parametrize("case", [(20, 0, -20, 0, 10, 0, 1), (0, 20, 0, 20, 0, 10, 1)])
def test_rotated_closed_loop_rejects_r_for_transpose(monkeypatch, case):
    original = geo.head_change
    def mutant(tracking, target, strength, min_cos):
        # With pose angles unchanged, supplying R.T to the real function
        # changes only its R.T @ delta into R @ delta. Cosine factors stay fixed.
        mutated_pose = replace(tracking.pose, rotation=tracking.pose.rotation.T)
        return original(replace(tracking, pose=mutated_pose), target, strength, min_cos)
    test_closed_loop(*case)
    monkeypatch.setattr(geo, "head_change", mutant)
    with pytest.raises(AssertionError):
        test_closed_loop(*case)


def test_sign_scaling_clamp_and_no_pose():
    ds = []
    for size in (2, 4):
        tr = correction_scene(eye_yaw_deg=15, eye_pitch_deg=-10, pixels_per_mm=size)
        eye = geo.derive_eye(tr.right_eye, tr.geometry)
        d = geo.displacement(eye, geo.head_change(tr, direction_from_angles(0, 0), 1, .5), 1.25, 1)
        assert d[0] < 0 and d[1] < 0
        ds.append(d)
        limited, clamped = geo.clamp_displacement(d*100, eye.half_width_px, .5)
        assert clamped and np.linalg.norm(limited) == pytest.approx(.5*eye.half_width_px)
        assert np.allclose(limited / np.linalg.norm(limited), d / np.linalg.norm(d))
        no_pose = replace(tr, pose=None, gaze=replace(tr.gaze, confidence=replace(tr.gaze.confidence, head_pose_applied=False)))
        assert np.allclose(geo.displacement(eye, geo.head_change(no_pose, direction_from_angles(0, 0), 1, .5), 1.25, 1), d)
    assert np.allclose(ds[1], ds[0]*2, atol=1e-4)
