"""The development overlay draws on a copy and never touches the captured frame."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from gazefix.tracking.models import FrameGeometry, TrackingResult, TrackingStatus, TrackingTiming, untracked
from gazefix.tracking.overlay import OverlayStyle, render_overlay
from tracking_fakes import identity_transform, shift, synthetic_landmarks, tracked_result


GEOMETRY = FrameGeometry(320, 180)
CYAN = (255, 255, 0)  # subject's right eye, BGR
YELLOW = (0, 255, 255)  # subject's left eye, BGR


def _frame(seed: int = 0) -> np.ndarray:
    frame = np.random.default_rng(seed).integers(0, 256, size=(GEOMETRY.height, GEOMETRY.width, 3), dtype=np.uint8)
    frame.setflags(write=False)
    return frame


def _tracked(**overrides: object) -> TrackingResult:
    return tracked_result(synthetic_landmarks(), GEOMETRY, transform=identity_transform(), **overrides)  # type: ignore[arg-type]


def _assert_drawn_on_a_copy(frame: np.ndarray, output: np.ndarray) -> None:
    assert output is not frame
    assert output.shape == frame.shape and output.dtype == np.uint8
    assert output.flags.writeable
    assert output.flags.c_contiguous
    assert not np.array_equal(output, frame)  # something was drawn


def test_render_draws_on_a_new_writeable_copy() -> None:
    frame = _frame()
    before = frame.copy()
    result = _tracked()
    assert result.face_valid and result.eyes_valid and result.pose_available

    output = render_overlay(frame, result)

    _assert_drawn_on_a_copy(frame, output)
    assert np.array_equal(frame, before)
    assert not frame.flags.writeable
    # The next call starts from the untouched input again, not from the previous canvas.
    assert np.array_equal(render_overlay(frame, result), output)


def test_eye_colours_are_anatomical() -> None:
    black = np.zeros((GEOMETRY.height, GEOMETRY.width, 3), dtype=np.uint8)
    black.setflags(write=False)

    output = render_overlay(black, _tracked(), OverlayStyle(mesh_points=False, face_oval=False, pose_axes=False, text=False))

    cyan_x = np.nonzero(np.all(output == CYAN, axis=2))[1]
    yellow_x = np.nonzero(np.all(output == YELLOW, axis=2))[1]
    assert cyan_x.size > 0 and yellow_x.size > 0
    assert cyan_x.max() < GEOMETRY.width / 2  # subject's right eye on the image's left
    assert yellow_x.min() > GEOMETRY.width / 2


@pytest.mark.parametrize("status", [TrackingStatus.TRACKED, TrackingStatus.LOW_QUALITY])
def test_landmark_bearing_statuses_render(status: TrackingStatus) -> None:
    frame = _frame()
    before = frame.copy()

    output = render_overlay(frame, _tracked(status=status))

    _assert_drawn_on_a_copy(frame, output)
    assert np.array_equal(frame, before)


def test_result_without_iris_renders() -> None:
    frame = _frame()
    result = tracked_result(synthetic_landmarks(count=468), GEOMETRY)
    assert not result.iris_available and result.left_eye is not None and result.left_eye.iris is None

    _assert_drawn_on_a_copy(frame, render_overlay(frame, result))


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (TrackingStatus.NO_FACE, ""),
        (TrackingStatus.UNAVAILABLE, "MediaPipe is not installed"),
        (TrackingStatus.UNAVAILABLE, "x" * 300),
        (TrackingStatus.TIMEOUT, "inference exceeded 40 ms"),
        (TrackingStatus.INITIALIZING, "loading model"),
        (TrackingStatus.ERROR, "backend raised"),
        (TrackingStatus.TIMEOUT, ""),
    ],
)
def test_results_without_landmarks_render_a_text_panel(status: TrackingStatus, message: str) -> None:
    frame = _frame()
    before = frame.copy()
    result = untracked(
        status, 3, 1_000, 1, GEOMETRY, message=message, faces_detected=2,
        timing=TrackingTiming(inference_ms=12.5, total_ms=20.0, waited_ms=3.0),
    )

    output = render_overlay(frame, result)

    _assert_drawn_on_a_copy(frame, output)
    assert np.array_equal(frame, before)


def test_landmarks_far_outside_the_frame_do_not_raise() -> None:
    frame = _frame()
    far = shift(synthetic_landmarks(), 4.5, -3.5)  # around x = 5.0, y = -3.0
    result = tracked_result(far, GEOMETRY, transform=identity_transform())
    assert result.landmarks is not None
    assert result.landmarks[:, 0].min() > 4.0 and result.landmarks[:, 1].max() < -2.0
    assert not result.eyes_valid
    assert result.quality is not None and result.quality.in_frame_fraction == 0.0

    output = render_overlay(frame, result)

    assert output is not frame and output.shape == frame.shape
    # Nothing but the text panel can land on the canvas; the input is untouched.
    assert np.array_equal(frame, _frame())


def test_landmarks_straddling_the_frame_edge_do_not_raise() -> None:
    frame = _frame()
    result = tracked_result(synthetic_landmarks(center=(0.02, 0.98)), GEOMETRY, transform=identity_transform())
    _assert_drawn_on_a_copy(frame, render_overlay(frame, result))


def test_pose_axes_with_a_rotated_head_do_not_raise() -> None:
    frame = _frame()
    transform = identity_transform()
    angle = np.radians(35.0)
    transform[:3, :3] = np.array(
        [[np.cos(angle), 0.0, np.sin(angle)], [0.0, 1.0, 0.0], [-np.sin(angle), 0.0, np.cos(angle)]],
        dtype=np.float32,
    )
    result = tracked_result(synthetic_landmarks(), GEOMETRY, transform=transform)
    assert result.pose is not None and result.pose.yaw_deg == pytest.approx(35.0, abs=1e-3)

    _assert_drawn_on_a_copy(frame, render_overlay(frame, result))
    _assert_drawn_on_a_copy(frame, render_overlay(frame, result, OverlayStyle(axis_length_px=10_000)))


@pytest.mark.parametrize(
    "shape",
    [(GEOMETRY.height, GEOMETRY.width), (GEOMETRY.height, GEOMETRY.width, 4), (GEOMETRY.height, GEOMETRY.width, 1)],
)
def test_non_bgr_frames_are_returned_unchanged(shape: tuple[int, ...]) -> None:
    frame = np.zeros(shape, dtype=np.uint8)
    frame.setflags(write=False)

    output = render_overlay(frame, _tracked())

    assert output is frame
    assert not output.flags.writeable


@pytest.mark.parametrize(
    "style",
    [
        OverlayStyle(mesh_points=False),
        OverlayStyle(face_oval=False),
        OverlayStyle(pose_axes=False),
        OverlayStyle(text=False),
        OverlayStyle(mesh_points=False, face_oval=False, pose_axes=False, text=False),
        OverlayStyle(description="fake backend v0"),
        OverlayStyle(description="d" * 300),
        OverlayStyle(axis_length_px=0),
    ],
)
def test_style_flags_do_not_raise(style: OverlayStyle) -> None:
    frame = _frame()
    before = frame.copy()

    output = render_overlay(frame, _tracked(), style)

    _assert_drawn_on_a_copy(frame, output)
    assert np.array_equal(frame, before)


def test_disabled_elements_are_not_drawn() -> None:
    black = np.zeros((GEOMETRY.height, GEOMETRY.width, 3), dtype=np.uint8)
    result = _tracked()
    everything = render_overlay(black, result)
    bare = render_overlay(black, result, OverlayStyle(mesh_points=False, face_oval=False, pose_axes=False, text=False))

    assert np.count_nonzero(bare) < np.count_nonzero(everything)
    assert np.count_nonzero(bare) > 0  # the eyes are always drawn


def test_stabilized_and_quality_fields_are_rendered_without_raising() -> None:
    frame = _frame()
    result = replace(_tracked(), stabilized=True, message="note", faces_detected=4)
    _assert_drawn_on_a_copy(frame, render_overlay(frame, result))


def test_overlay_marks_are_drawn_at_the_landmark_pixel_positions() -> None:
    """AC4 alignment: the iris circle lands where landmark_pixels says it is."""

    import numpy as np

    from gazefix.tracking.models import FrameGeometry
    from gazefix.tracking.overlay import OverlayStyle, render_overlay
    from tracking_fakes import synthetic_landmarks, tracked_result

    geometry = FrameGeometry(640, 360)
    landmarks = synthetic_landmarks(center=(0.5, 0.5), face_height=0.5)
    result = tracked_result(landmarks, geometry)
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame.setflags(write=False)
    canvas = render_overlay(frame, result, OverlayStyle(mesh_points=False, face_oval=False, pose_axes=False, text=False))
    pixels = result.landmark_pixels()
    assert pixels is not None
    for eye in (result.right_eye, result.left_eye):
        assert eye is not None and eye.iris is not None
        cx, cy = (eye.iris[0][:2] * np.array([640, 360])).astype(int)
        radius = int(np.mean(np.hypot(*((eye.iris[1:, :2] - eye.iris[0, :2]) * np.array([640, 360])).T)))
        window = canvas[max(0, cy - radius - 3) : cy + radius + 4, max(0, cx - radius - 3) : cx + radius + 4]
        drawn = np.argwhere(window.max(axis=2) > 0)
        assert len(drawn) > 0
        centroid_y, centroid_x = drawn.mean(axis=0) + np.array([max(0, cy - radius - 3), max(0, cx - radius - 3)])
        assert abs(centroid_x - cx) <= 2.0 and abs(centroid_y - cy) <= 2.0
    # Nothing is drawn far away from the face.
    assert canvas[:20, :20].max() == 0


def test_eye_marks_follow_the_result_geometry_not_the_canvas_size() -> None:
    """A result drawn on a differently sized canvas keeps one coordinate mapping."""

    import numpy as np

    from gazefix.tracking.models import FrameGeometry
    from gazefix.tracking.overlay import OverlayStyle, render_overlay
    from tracking_fakes import synthetic_landmarks, tracked_result

    geometry = FrameGeometry(320, 180)
    result = tracked_result(synthetic_landmarks(center=(0.5, 0.5), face_height=0.5), geometry)
    big = np.zeros((360, 640, 3), dtype=np.uint8)
    canvas = render_overlay(big, result, OverlayStyle(mesh_points=False, face_oval=False, pose_axes=False, text=False))
    drawn = np.argwhere(canvas.max(axis=2) > 0)
    assert len(drawn) > 0
    # Everything lands inside the 320x180 region that the geometry describes.
    assert drawn[:, 0].max() < 180 + 2 and drawn[:, 1].max() < 320 + 2


def test_landmarks_outside_the_image_are_not_pinned_to_the_border() -> None:
    import numpy as np

    from gazefix.tracking.models import FrameGeometry
    from gazefix.tracking.overlay import OverlayStyle, render_overlay
    from tracking_fakes import synthetic_landmarks, tracked_result

    geometry = FrameGeometry(320, 180)
    landmarks = synthetic_landmarks(center=(0.5, 0.5), face_height=0.5).copy()
    landmarks[280:360, 0] = 5.0  # mesh-only indices (no eye contour or iris points), far outside to the right
    result = tracked_result(landmarks, geometry)
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    canvas = render_overlay(frame, result, OverlayStyle(face_oval=False, pose_axes=False, text=False))
    assert canvas[:, 316:].max() == 0  # nothing drawn along the right border
