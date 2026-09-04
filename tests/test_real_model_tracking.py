"""Opt-in tests that run the real MediaPipe face landmarker on the licensed fixture.

They cover M1 tracking and the M2 gaze estimate built from the same real
detections, so the gaze evidence is not limited to synthetic geometry.

Skipped unless ``GAZEFIX_REAL_MODEL_TESTS=1`` is set, ``mediapipe`` imports,
and the verified model bundle is present (in ``GAZEFIX_MODEL_DIR`` or the
default model directory). The fixture is the public-domain NASA astronaut
crop documented in ``tests/assets/README.md``; it is scaled into a 1280×720
canvas inside the measured detection envelope, so these tests establish
that the real pipeline produces anatomically labelled, frame-attached
landmarks, iris points and head pose on a real face, not the detector's
general limits (see the fixture README).
"""

from __future__ import annotations

from dataclasses import replace
import math
import os
from pathlib import Path

import numpy as np
import pytest

from gazefix.config import AppSettings, default_model_directory
from gazefix.diagnostics.metrics import PipelineMetrics
from gazefix.pipeline.processor import FrameContext
from gazefix.tracking import landmarks as topology
from gazefix.tracking.analysis import (
    AnalysisSettings,
    compute_quality,
    extract_eye,
    head_pose_from_matrix,
    validate_landmarks,
)
from gazefix.tracking.assets import FACE_LANDMARKER, verify_model
from gazefix.tracking.models import FrameGeometry, TrackingResult, TrackingStatus
from gazefix.tracking.processor import TrackingProcessor
from tracker_fakes import tracking_settings, wait_until


pytestmark = pytest.mark.real_model

FIXTURE = Path(__file__).parent / "assets" / "astronaut_face.png"
MODEL_DIR = Path(os.environ.get("GAZEFIX_MODEL_DIR") or default_model_directory())


def _skip_unless_enabled() -> None:
    if os.environ.get("GAZEFIX_REAL_MODEL_TESTS") != "1":
        pytest.skip("GAZEFIX_REAL_MODEL_TESTS not set (real-model tests are opt-in)")
    try:
        verify_model(FACE_LANDMARKER.path_in(MODEL_DIR))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"model missing or invalid at {MODEL_DIR} (run scripts/fetch_model.py): {exc}")
    try:
        import mediapipe  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        # With the tests explicitly enabled, a broken MediaPipe installation is
        # an AC6 failure, not a reason to skip.
        pytest.fail(f"mediapipe cannot be imported although real-model tests were requested: {exc}")


@pytest.fixture(scope="module")
def cv2():  # type: ignore[no-untyped-def]
    _skip_unless_enabled()
    import cv2 as module

    return module


@pytest.fixture(scope="module")
def still(cv2):  # type: ignore[no-untyped-def]
    image = cv2.imread(str(FIXTURE))
    assert image is not None, FIXTURE
    return image


@pytest.fixture(scope="module")
def tracker(cv2):  # type: ignore[no-untyped-def]
    from gazefix.tracking.mediapipe_tracker import create_mediapipe_tracker

    instance = create_mediapipe_tracker(replace(AppSettings(), model_directory=MODEL_DIR))
    yield instance
    instance.close()


def canvas(cv2, still, dx: int = 0, dy: int = 0, scale: float = 0.8, width: int = 1280, height: int = 720):  # type: ignore[no-untyped-def]
    frame = np.full((height, width, 3), 96, np.uint8)
    sh, sw = still.shape[:2]
    factor = (height * 0.95 * scale) / sh
    resized = cv2.resize(still, (int(sw * factor), int(sh * factor)), interpolation=cv2.INTER_LINEAR)
    rh, rw = resized.shape[:2]
    y0, x0 = (height - rh) // 2 + dy, (width - rw) // 2 + dx
    frame[y0 : y0 + rh, x0 : x0 + rw] = resized
    frame.setflags(write=False)
    return frame


class Clock:
    def __init__(self) -> None:
        self.ms = 0

    def next(self) -> int:
        self.ms += 33
        return self.ms


@pytest.fixture(scope="module")
def clock() -> Clock:
    return Clock()


def analyse(detection, frame):  # type: ignore[no-untyped-def]
    geometry = FrameGeometry(frame.shape[1], frame.shape[0])
    landmarks, iris = validate_landmarks(detection.faces[0].landmarks)
    settings = AnalysisSettings()
    return (
        landmarks,
        iris,
        extract_eye(landmarks, "right", geometry, settings, iris),
        extract_eye(landmarks, "left", geometry, settings, iris),
        compute_quality(landmarks, geometry, settings, (0.5, 0.5, 0.5)),
        head_pose_from_matrix(detection.faces[0].transform),
    )


def test_fixture_face_is_tracked_with_anatomical_eyes_iris_and_pose(cv2, still, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    frame = canvas(cv2, still)
    detection = tracker.detect(frame, clock.next())
    assert len(detection.faces) == 1
    assert detection.iris_available
    assert not frame.flags.writeable  # the input stayed read-only and untouched
    landmarks, iris, right, left, quality, pose = analyse(detection, frame)
    assert landmarks.shape == (478, 3) and iris
    assert right.valid and left.valid
    assert right.outer_corner[0] < right.inner_corner[0] < left.inner_corner[0] < left.outer_corner[0]
    assert right.iris is not None and left.iris is not None
    assert right.outer_corner[0] < right.iris_center[0] < right.inner_corner[0]
    assert 0.1 < right.openness < 0.6 and 0.1 < left.openness < 0.6
    assert quality.score == pytest.approx(1.0)
    assert pose is not None and abs(pose.yaw_deg) < 15 and abs(pose.roll_deg) < 15 and abs(pose.pitch_deg) < 30
    assert pose.translation[2] < 0  # in front of the camera
    assert 1.0 < detection.inference_ms < 1000.0


def test_blank_frame_reports_no_face(cv2, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    blank = np.full((720, 1280, 3), 96, np.uint8)
    blank.setflags(write=False)
    detection = tracker.detect(blank, clock.next())
    assert detection.faces == ()


def test_landmarks_follow_the_face_through_motion(cv2, still, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    previous = None
    previous_dx = 0
    errors = []
    for index in range(30):
        dx = int(120 * math.sin(index / 6.0))
        detection = tracker.detect(canvas(cv2, still, dx=dx), clock.next())
        assert len(detection.faces) == 1, f"lost the face at frame {index}"
        pixels = detection.faces[0].landmarks[:, 0] * 1280
        if previous is not None:
            errors.append(abs(float(np.mean(pixels - previous)) - (dx - previous_dx)))
        previous, previous_dx = pixels, dx
    assert max(errors) < 3.0 and float(np.mean(errors)) < 1.0


def test_mirrored_frame_negates_yaw_and_roll_and_keeps_pitch(cv2, still, clock) -> None:  # type: ignore[no-untyped-def]
    from gazefix.tracking.mediapipe_tracker import create_mediapipe_tracker

    settings = replace(AppSettings(), model_directory=MODEL_DIR)
    # Rotate the frontal fixture by 8° so roll is well above the model's jitter
    # and the sign flip is a real measurement rather than noise around zero.
    matrix = cv2.getRotationMatrix2D((640, 360), 8, 1.0)
    frame = cv2.warpAffine(np.array(canvas(cv2, still)), matrix, (1280, 720))
    frame.setflags(write=False)
    mirrored = np.ascontiguousarray(frame[:, ::-1])
    mirrored.setflags(write=False)
    plain, flipped = create_mediapipe_tracker(settings), create_mediapipe_tracker(settings)
    try:
        for _ in range(3):
            a = plain.detect(frame, clock.next())
            b = flipped.detect(mirrored, clock.next())
    finally:
        plain.close()
        flipped.close()
    pose_a = head_pose_from_matrix(a.faces[0].transform)
    pose_b = head_pose_from_matrix(b.faces[0].transform)
    assert pose_a is not None and pose_b is not None
    assert abs(pose_a.roll_deg) > 4.0  # a real signal, not jitter
    assert pose_b.yaw_deg == pytest.approx(-pose_a.yaw_deg, abs=2.5)
    assert pose_b.roll_deg == pytest.approx(-pose_a.roll_deg, abs=2.5)
    # The landmark model is not exactly mirror-symmetric (about 3° of pitch
    # difference was measured on this fixture); the sign and magnitude agree.
    assert pose_b.pitch_deg == pytest.approx(pose_a.pitch_deg, abs=5.0)
    # The backend labels sides for the face it sees: in the mirrored image the
    # "right eye" indices still land on the image's left, which is why the
    # contract keeps coordinates in the unmirrored frame and mirrors only x.
    lm_b = b.faces[0].landmarks
    assert lm_b[topology.RIGHT_EYE_OUTER_CORNER, 0] < lm_b[topology.LEFT_EYE_OUTER_CORNER, 0]
    assert pose_a.mirrored().yaw_deg == pytest.approx(pose_b.yaw_deg, abs=2.5)


def test_in_plane_rotation_raises_roll_by_the_rotation_angle(cv2, still, clock) -> None:  # type: ignore[no-untyped-def]
    from gazefix.tracking.mediapipe_tracker import create_mediapipe_tracker

    settings = replace(AppSettings(), model_directory=MODEL_DIR)
    frame = canvas(cv2, still)
    matrix = cv2.getRotationMatrix2D((640, 360), 10, 1.0)  # +10° counter-clockwise on screen
    rotated = cv2.warpAffine(np.array(frame), matrix, (1280, 720))
    rotated.setflags(write=False)
    plain, turned = create_mediapipe_tracker(settings), create_mediapipe_tracker(settings)
    try:
        for _ in range(3):
            a = plain.detect(frame, clock.next())
            b = turned.detect(rotated, clock.next())
    finally:
        plain.close()
        turned.close()
    roll_a = head_pose_from_matrix(a.faces[0].transform).roll_deg
    roll_b = head_pose_from_matrix(b.faces[0].transform).roll_deg
    assert roll_b - roll_a == pytest.approx(10.0, abs=3.0)


def test_pitch_sign_agrees_with_landmark_depth_ordering(cv2, still, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    detection = tracker.detect(canvas(cv2, still), clock.next())
    landmarks, _, _, _, _, pose = analyse(detection, canvas(cv2, still))
    assert pose is not None
    forehead_z = float(landmarks[topology.FOREHEAD, 2])
    chin_z = float(landmarks[topology.CHIN, 2])
    if abs(pose.pitch_deg) > 3.0:
        # pitch > 0 means the head is tilted down: the forehead is closer to
        # the camera (smaller z) than the chin.
        assert (pose.pitch_deg > 0) == (forehead_z < chin_z)


def test_processor_end_to_end_with_the_real_tracker(cv2, still) -> None:  # type: ignore[no-untyped-def]
    from gazefix.tracking.mediapipe_tracker import mediapipe_tracker_factory

    settings = tracking_settings(
        model_directory=MODEL_DIR, tracking_wait_ms=500, tracking_smoothing=0.5, worker_join_timeout_s=2.0
    )
    metrics = PipelineMetrics()
    processor = TrackingProcessor(mediapipe_tracker_factory(settings), settings, metrics)
    processor.start()
    assert wait_until(lambda: processor.status().state == "ready", timeout=30.0)
    try:
        statuses = []
        for index in range(15):
            frame = canvas(cv2, still, dx=int(40 * math.sin(index / 4.0)))
            output = processor.process(frame, FrameContext(index + 1, (index + 1) * 33_000_000, 1))
            assert output.frame is frame
            assert output.tracking is not None and output.tracking.belongs_to(index + 1, 1)
            statuses.append(output.tracking.status)
        assert statuses[-1] is TrackingStatus.TRACKED
        assert statuses.count(TrackingStatus.TRACKED) >= 12
        last = output.tracking
        assert last.stabilized and last.iris_available and last.pose is not None
        assert last.timing.inference_ms > 1.0 and last.timing.total_ms >= last.timing.inference_ms
        processor.set_overlay_enabled(True)
        output = processor.process(frame, FrameContext(99, 99 * 33_000_000, 1))
        assert output.frame is not frame and output.frame.flags.writeable
        assert metrics.snapshot().tracking_inference_ms > 0
    finally:
        processor.close()
    assert not processor.worker_alive


def test_backend_adds_no_python_threads_so_a_wedged_call_cannot_hold_the_process(cv2, still, clock) -> None:  # type: ignore[no-untyped-def]
    """The premise behind removing the forced-exit path, checked on the real backend.

    GazeFix runs the tracker on a daemon thread. That only guarantees a
    wedged native call cannot keep the interpreter alive if the backend does
    not add non-daemon Python threads of its own (MediaPipe 1.0.1 did: one
    ``ThreadPoolExecutor`` worker per landmarker, which CPython joins at
    exit).
    """

    import threading

    from gazefix.tracking.mediapipe_tracker import create_mediapipe_tracker

    before = {t.ident for t in threading.enumerate()}
    tracker = create_mediapipe_tracker(replace(AppSettings(), model_directory=MODEL_DIR))
    try:
        frame = canvas(cv2, still)
        for _ in range(3):
            tracker.detect(frame, clock.next())
        added = [t for t in threading.enumerate() if t.ident not in before]
        assert [t for t in added if not t.daemon] == [], (
            "the backend added a non-daemon Python thread; a wedged native call on it "
            f"would block interpreter exit: {[t.name for t in added if not t.daemon]}"
        )
    finally:
        tracker.close()


# --- M2: gaze estimated from real MediaPipe iris landmarks ---


def _real_result(detection, frame):  # type: ignore[no-untyped-def]
    """Build a TRACKED result from a real detection, for the gaze estimator."""

    landmarks, iris, right, left, quality, pose = analyse(detection, frame)
    return TrackingResult(
        status=TrackingStatus.TRACKED,
        capture_sequence=1,
        captured_at_ns=1,
        camera_request_id=1,
        geometry=FrameGeometry(frame.shape[1], frame.shape[0]),
        landmarks=landmarks,
        iris_available=iris,
        right_eye=right,
        left_eye=left,
        pose=pose,
        quality=quality,
    )


def test_real_iris_landmarks_produce_a_usable_gaze_estimate(cv2, still, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    """The estimator works on real backend output, not only synthetic geometry."""

    from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator
    from gazefix.gaze.models import GazeStatus

    frame = canvas(cv2, still)
    result = _real_result(tracker.detect(frame, clock.next()), frame)
    assert result.eyes_valid

    gaze = GeometricGazeEstimator(GazeSettings(smoothing=0.0)).estimate(result)
    assert gaze.status is GazeStatus.ESTIMATED, gaze.message
    assert gaze.yaw_deg is not None and gaze.pitch_deg is not None
    # The fixture is a portrait looking near the camera, so the estimate must
    # be modest rather than extreme. This is a plausibility bound, not an
    # accuracy claim: the ground truth of this photograph is unknown.
    assert abs(gaze.yaw_deg) < 25.0
    assert abs(gaze.pitch_deg) < 25.0
    assert gaze.confidence.eyes_used == 2
    assert gaze.confidence.head_pose_applied is True


def test_real_gaze_is_not_a_restatement_of_real_head_pose(cv2, still, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    """On the fixture the head is pitched down while the eyes look up.

    Head-pose pitch is positive-down and gaze pitch is positive-up, so a
    person whose head is tilted down but who is looking at the camera has a
    positive head pitch, a positive eye-in-head pitch, and a near-zero gaze
    pitch. Those three numbers cannot all come from one signal.
    """

    from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator

    frame = canvas(cv2, still)
    result = _real_result(tracker.detect(frame, clock.next()), frame)
    gaze = GeometricGazeEstimator(GazeSettings(smoothing=0.0)).estimate(result)
    assert result.pose is not None
    assert gaze.eye_pitch_deg is not None and gaze.pitch_deg is not None
    # The head is tilted down by a visible amount...
    assert result.pose.pitch_deg > 5.0
    # ...the eyes are raised inside their sockets by a comparable amount...
    assert gaze.eye_pitch_deg > 5.0
    # ...and the two largely cancel, which head pose alone could never produce.
    assert abs(gaze.pitch_deg) < result.pose.pitch_deg - 3.0


def test_real_gaze_is_stable_when_the_same_face_moves_around_the_frame(cv2, still, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    """Placement must not change the estimate much; the face is unchanged."""

    from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator
    from gazefix.gaze.models import GazeStatus

    estimator = GeometricGazeEstimator(GazeSettings(smoothing=0.0))
    yaws = []
    for dx, dy, scale in ((0, 0, 0.8), (-160, 0, 0.8), (160, 0, 0.8), (0, -60, 0.8), (0, 0, 0.9)):
        frame = canvas(cv2, still, dx=dx, dy=dy, scale=scale)
        detection = tracker.detect(frame, clock.next())
        if not detection.faces:
            continue
        estimator.reset()
        gaze = estimator.estimate(_real_result(detection, frame))
        assert gaze.status is GazeStatus.ESTIMATED, (dx, dy, scale, gaze.message)
        assert gaze.yaw_deg is not None
        yaws.append(gaze.yaw_deg)
    assert len(yaws) >= 4
    assert max(yaws) - min(yaws) < 20.0


def test_real_eyes_disagree_structurally_and_averaging_absorbs_it(cv2, still, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    """The measurement that sets ``agreement_deadband_deg``; see docs/gaze.md.

    Both irises read as displaced temporally from the corner midpoint, because
    the nasal canthus extends further medially than the globe. The bias is
    mirror-symmetric, so the two eyes disagree while their mean is sound. If
    this ever falls inside the deadband by accident the deadband is no longer
    justified, and if it grows past it, ordinary faces would lose confidence.
    """

    from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator

    settings = GazeSettings()
    frame = canvas(cv2, still)
    gaze = GeometricGazeEstimator(replace(settings, smoothing=0.0)).estimate(
        _real_result(tracker.detect(frame, clock.next()), frame)
    )
    by_side = {eye.side: eye for eye in gaze.per_eye}
    assert set(by_side) == {"left", "right"}
    # Both irises sit temporally of the corner midpoint: for the subject's
    # right eye that is negative u (toward the subject's right), for the left
    # eye positive u (toward the subject's left).
    assert by_side["right"].offset_u < 0.0
    assert by_side["left"].offset_u > 0.0
    spread = abs(by_side["left"].yaw_deg - by_side["right"].yaw_deg)
    assert 5.0 < spread < settings.agreement_deadband_deg
    # The averaged estimate is far smaller than either eye's disagreement.
    assert gaze.eye_yaw_deg is not None
    assert abs(gaze.eye_yaw_deg) < spread / 2.0


def test_real_gaze_estimation_is_fast_enough_to_be_free_on_the_frame_path(cv2, still, tracker, clock) -> None:  # type: ignore[no-untyped-def]
    """Gaze must not be a meaningful share of the tracking budget."""

    import time as _time

    from gazefix.gaze.estimator import GazeSettings, GeometricGazeEstimator

    frame = canvas(cv2, still)
    result = _real_result(tracker.detect(frame, clock.next()), frame)
    estimator = GeometricGazeEstimator(GazeSettings())
    for _ in range(20):  # warm the code paths
        estimator.estimate(result)
    started = _time.perf_counter()
    runs = 200
    for _ in range(runs):
        estimator.estimate(result)
    per_frame_ms = (_time.perf_counter() - started) / runs * 1000.0
    # The MediaPipe inference this sits beside costs tens of milliseconds.
    assert per_frame_ms < 5.0, per_frame_ms
