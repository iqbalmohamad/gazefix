"""Developer visibility for gaze: the overlay ray, the text, and the UI line.

The overlay must stay distinguishable from the head-pose axes, must never
mutate the frame it is handed, and must not print a precision the estimate
does not have.
"""

from __future__ import annotations

from dataclasses import replace
import inspect

import numpy as np
import pytest

from gazefix.gaze.models import (
    EyeGaze,
    GazeConfidence,
    GazeResult,
    GazeStatus,
    direction_from_angles,
    unavailable,
)
from gazefix.tracking.models import FrameGeometry, TrackingStatus, untracked
from gazefix.tracking.overlay import OverlayStyle, render_overlay, warm_up
from gaze_fakes import gaze_scene


GEOMETRY = FrameGeometry(640, 480)


def frame(value: int = 30) -> np.ndarray:
    canvas = np.full((GEOMETRY.height, GEOMETRY.width, 3), value, dtype=np.uint8)
    canvas.setflags(write=False)
    return canvas


def gaze(
    status: GazeStatus = GazeStatus.ESTIMATED,
    yaw: float = 20.0,
    pitch: float = -8.0,
    score: float = 0.82,
) -> GazeResult:
    return GazeResult(
        status=status,
        confidence=GazeConfidence(score, 1.0, 1.0, 1.0, 1.0, 1.0, 2, True),
        yaw_deg=yaw,
        pitch_deg=pitch,
        eye_yaw_deg=yaw / 2.0,
        eye_pitch_deg=pitch / 2.0,
        direction=direction_from_angles(yaw, pitch),
        per_eye=(
            EyeGaze("right", yaw / 2.0, pitch / 2.0, 0.1, -0.03),
            EyeGaze("left", yaw / 2.0, pitch / 2.0, 0.1, -0.03),
        ),
        estimation_ms=0.12,
    )


def tracked_with(gaze_result: GazeResult | None):  # type: ignore[no-untyped-def]
    return replace(gaze_scene(eye_yaw_deg=20.0, geometry=GEOMETRY).result(), gaze=gaze_result)


# --- ownership ---


def test_the_gaze_overlay_never_writes_the_input_frame() -> None:
    original = frame()
    before = np.array(original, copy=True)
    output = render_overlay(original, tracked_with(gaze()))
    assert output is not original
    assert np.array_equal(original, before)


def test_the_overlay_draws_something_for_gaze() -> None:
    result = tracked_with(gaze())
    with_ray = render_overlay(frame(), result, OverlayStyle(gaze_ray=True, text=False))
    without = render_overlay(frame(), result, OverlayStyle(gaze_ray=False, text=False))
    assert not np.array_equal(with_ray, without)


def test_no_gaze_ray_is_drawn_when_there_is_no_direction() -> None:
    style = OverlayStyle(gaze_ray=True, text=False)
    nothing = render_overlay(frame(), tracked_with(unavailable("no iris")), style)
    disabled = render_overlay(
        frame(), tracked_with(gaze()), OverlayStyle(gaze_ray=False, text=False)
    )
    assert np.array_equal(nothing, disabled)


def test_the_gaze_ray_uses_a_colour_no_other_overlay_element_uses() -> None:
    from gazefix.tracking import overlay as module

    others = {
        module._MESH, module._RIGHT_EYE, module._LEFT_EYE, module._OVAL, module._TEXT,
        module._DIM_TEXT, module._WARN, module._ERROR,
        module._AXIS_X, module._AXIS_Y, module._AXIS_Z,
    }
    assert module._GAZE not in others
    assert module._GAZE_DIM not in others


def test_a_low_confidence_ray_is_drawn_dimmer_than_an_estimated_one() -> None:
    style = OverlayStyle(gaze_ray=True, text=False)
    bright = render_overlay(frame(), tracked_with(gaze()), style)
    dim = render_overlay(
        frame(), tracked_with(gaze(status=GazeStatus.LOW_CONFIDENCE)), style
    )
    assert not np.array_equal(bright, dim)


def test_the_warm_up_covers_the_gaze_primitive() -> None:
    # The arrow is a new drawing primitive; warm_up must exercise it so its
    # one-time OpenCV cost is not paid on the processor thread.
    import inspect

    from gazefix.tracking import overlay as module

    assert "arrowedLine" in inspect.getsource(module.warm_up)
    warm_up()  # must not raise


# --- text ---


def text_lines(result) -> list[str]:  # type: ignore[no-untyped-def]
    from gazefix.tracking.overlay import _gaze_lines

    return _gaze_lines(result.gaze, "geometric iris-offset gaze estimator (uncalibrated)")


def test_the_gaze_text_says_it_is_approximate_and_uncalibrated() -> None:
    joined = " ".join(text_lines(tracked_with(gaze())))
    assert "approx" in joined
    assert "uncalibrated" in joined


def test_the_gaze_text_states_the_sign_convention() -> None:
    joined = " ".join(text_lines(tracked_with(gaze())))
    assert "subject's left" in joined
    assert "up" in joined


def test_the_gaze_text_prints_whole_degrees_only() -> None:
    """Decimals of a degree would imply a precision this estimate lacks."""

    import re

    for line in text_lines(tracked_with(gaze(yaw=12.345, pitch=-6.789))):
        assert not re.search(r"[-+]\d+\.\d+ ?(deg|pitch|yaw)", line), line
    joined = " ".join(text_lines(tracked_with(gaze(yaw=12.345, pitch=-6.789))))
    assert "+12" in joined and "-7" in joined


def test_the_gaze_text_shows_every_confidence_factor() -> None:
    """All six, or the printed product does not equal the printed score."""

    joined = " ".join(text_lines(tracked_with(gaze())))
    for factor in ("quality", "open", "agree", "pose", "offset", "res"):
        assert factor in joined


def test_the_printed_confidence_factors_multiply_to_the_printed_score() -> None:
    import re

    from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator
    from gaze_fakes import gaze_scene

    result = GeometricGazeEstimator(GazeSettings(smoothing=0.0)).estimate(
        gaze_scene(eye_yaw_deg=12.0, head_yaw_deg=30.0, pixels_per_mm=1.0).result()
    )
    assert result.status.has_direction
    lines = " ".join(text_lines(replace(tracked_with(None), gaze=result)))
    factors = [float(v) for v in re.findall(r"(?:quality|open|agree|pose|offset|res) (\d\.\d\d)", lines)]
    assert len(factors) == 6, lines
    product = 1.0
    for factor in factors:
        product *= factor
    assert product == pytest.approx(result.confidence.score, abs=0.02)


def test_the_gaze_text_separates_gaze_from_the_eye_in_head_component() -> None:
    joined = " ".join(text_lines(tracked_with(gaze())))
    assert "eye-in-head" in joined


def test_unavailable_gaze_says_so_and_prints_no_angles() -> None:
    lines = text_lines(tracked_with(unavailable("no gaze: the tracker delivered no iris")))
    joined = " ".join(lines)
    assert "unavailable" in joined
    assert "iris" in joined
    assert "yaw" not in joined


def test_a_result_with_no_gaze_field_produces_no_gaze_text() -> None:
    assert text_lines(tracked_with(None)) == []


def test_the_panel_still_renders_for_an_untracked_frame_with_gaze() -> None:
    result = untracked(TrackingStatus.NO_FACE, 1, 1, 1, GEOMETRY, "no face detected")
    output = render_overlay(frame(), result)
    assert output.shape == (GEOMETRY.height, GEOMETRY.width, 3)


# --- the developer UI line ---


def ui_text(gaze_result: GazeResult | None) -> str:
    from gazefix.ui.main_window import _gaze_detail_text

    return _gaze_detail_text(gaze_result)


def test_the_ui_line_marks_the_estimate_approximate_and_uncalibrated() -> None:
    line = ui_text(gaze())
    assert "approx" in line and "uncalibrated" in line


def test_the_ui_line_states_the_sign_convention_and_whole_degrees() -> None:
    line = ui_text(gaze(yaw=12.7, pitch=-6.3))
    assert "subject's left" in line
    assert "+13" in line and "-6" in line
    assert "12.7" not in line


def test_the_ui_line_reports_the_eye_in_head_component_and_the_eye_count() -> None:
    line = ui_text(gaze())
    assert "eye-in-head" in line
    assert "eyes 2" in line


def test_the_ui_line_says_when_head_pose_was_not_applied() -> None:
    without = replace(
        gaze(), confidence=GazeConfidence(0.7, 1.0, 1.0, 1.0, 0.7, 1.0, 2, False)
    )
    assert "head pose unavailable" in ui_text(without)
    assert "head pose applied" in ui_text(gaze())


def test_the_ui_line_reports_an_unavailable_gaze_with_its_reason() -> None:
    line = ui_text(unavailable("no gaze: eyelids too closed to locate the iris"))
    assert "unavailable" in line
    assert "eyelids" in line


def test_the_ui_line_handles_a_missing_gaze_field() -> None:
    assert ui_text(None) == "gaze: not estimated"


@pytest.mark.parametrize("status", [GazeStatus.ESTIMATED, GazeStatus.LOW_CONFIDENCE])
def test_the_ui_line_names_the_status_so_low_confidence_is_never_hidden(
    status: GazeStatus,
) -> None:
    assert status.value in ui_text(replace(gaze(), status=status))


# --- the wirings that carry gaze into what a human actually sees ---


def test_the_rendered_panel_carries_the_gaze_block() -> None:
    """Every other text test drives the private helper; this pins the wiring."""

    style = OverlayStyle(
        mesh_points=False, face_oval=False, pose_axes=False, gaze_ray=False, text=True
    )
    result = tracked_with(gaze())
    with_gaze = render_overlay(frame(), result, style)
    without = render_overlay(frame(), replace(result, gaze=None), style)
    assert not np.array_equal(with_gaze, without)


def test_the_consumer_tracking_label_reports_the_gaze_status() -> None:
    """The one-line status a non-developer sees."""

    from gazefix.ui import main_window as module

    source = inspect.getsource(module.MainWindow._refresh_metrics)
    assert "gaze" in source, "the consumer label must mention the gaze status"


def test_the_developer_detail_line_includes_the_gaze_readout() -> None:
    from gazefix.ui.main_window import _tracking_detail_text

    class Metrics:
        pipeline_latency_ms = 1.0
        gaze_estimation_ms = 0.2
        tracking_timeouts = 0
        tracking_errors = 0
        tracking_replaced = 0

    result = tracked_with(gaze())
    line = _tracking_detail_text(result, Metrics())
    assert "gaze" in line
    assert "approx" in line, "the detail line must carry the uncalibrated marker"
