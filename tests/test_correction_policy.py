from dataclasses import replace
import pytest
from correction_fakes import correction_scene
from gazefix.correction.policy import PolicySettings, resolve_effective_strength
from gazefix.gaze.models import direction_from_angles, GazeStatus


@pytest.mark.parametrize("deviation,factor", [(0,.3), (5,1), (15,1), (25,1), (30,.5), (35,0), (60,0)])
def test_curve(deviation, factor):
    gaze = correction_scene().gaze
    result = resolve_effective_strength(.8, gaze, direction_from_angles(deviation, 0))
    assert result.effective_strength == pytest.approx(.8*factor, abs=1e-6)
    if deviation >= 35: assert result.reason == "deviation above disable threshold"


def test_confidence_cap_and_unavailable():
    gaze = correction_scene().gaze
    target = direction_from_angles(15,0)
    mid = replace(gaze, confidence=replace(gaze.confidence, score=.475))
    assert resolve_effective_strength(1, mid, target).effective_strength == pytest.approx(.5)
    low = replace(gaze, confidence=replace(gaze.confidence, score=.35))
    assert resolve_effective_strength(1, low, target).reason == "low confidence"
    assert resolve_effective_strength(1, replace(gaze,status=GazeStatus.LOW_CONFIDENCE), target).reason == "gaze not estimated"
    assert resolve_effective_strength(1, None, target).effective_strength == 0
    assert resolve_effective_strength(1, gaze, target, PolicySettings(max_effective_strength=.6)).effective_strength == .6
    assert resolve_effective_strength(0, gaze, target).reason == "requested strength 0"
