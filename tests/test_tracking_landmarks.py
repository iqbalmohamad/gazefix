"""Invariants of the canonical 478-point topology, and a cross-check against MediaPipe."""

from __future__ import annotations

import pytest

from gazefix.tracking import landmarks as topology


SIDES = ("left", "right")


def test_each_eye_contour_has_sixteen_unique_mesh_indices() -> None:
    for side in SIDES:
        contour = topology.eye_contour(side)
        assert len(contour) == topology.EYE_CONTOUR_POINTS == 16
        assert len(set(contour)) == 16
        assert all(0 <= index < topology.LANDMARK_COUNT_WITHOUT_IRIS for index in contour)


def test_eye_contours_and_irises_are_disjoint() -> None:
    assert set(topology.LEFT_EYE_CONTOUR).isdisjoint(topology.RIGHT_EYE_CONTOUR)
    assert set(topology.iris_indices("left")).isdisjoint(topology.iris_indices("right"))
    assert set(topology.LEFT_EYE_CONTOUR).isdisjoint(topology.iris_indices("left"))
    assert set(topology.RIGHT_EYE_CONTOUR).isdisjoint(topology.iris_indices("right"))


def test_iris_indices_are_the_ten_refinement_points() -> None:
    assert topology.iris_indices("right") == (468, 469, 470, 471, 472)
    assert topology.iris_indices("left") == (473, 474, 475, 476, 477)
    assert topology.iris_indices("right")[0] == topology.RIGHT_IRIS_CENTER
    assert topology.iris_indices("left")[0] == topology.LEFT_IRIS_CENTER
    assert set(topology.iris_indices("left")) | set(topology.iris_indices("right")) == set(range(468, 478))
    assert topology.IRIS_POINTS_PER_EYE == 5
    assert topology.LANDMARK_COUNT_WITHOUT_IRIS == 468
    assert (
        topology.LANDMARK_COUNT_WITH_IRIS
        == topology.LANDMARK_COUNT_WITHOUT_IRIS + 2 * topology.IRIS_POINTS_PER_EYE
        == 478
    )


@pytest.mark.parametrize(
    ("side", "outer", "inner", "lower", "upper"),
    [
        (
            "right",
            topology.RIGHT_EYE_OUTER_CORNER,
            topology.RIGHT_EYE_INNER_CORNER,
            topology.RIGHT_EYE_LOWER_LID,
            topology.RIGHT_EYE_UPPER_LID,
        ),
        (
            "left",
            topology.LEFT_EYE_OUTER_CORNER,
            topology.LEFT_EYE_INNER_CORNER,
            topology.LEFT_EYE_LOWER_LID,
            topology.LEFT_EYE_UPPER_LID,
        ),
    ],
)
def test_contour_positions_name_the_same_points_for_both_eyes(
    side: str, outer: int, inner: int, lower: tuple[int, ...], upper: tuple[int, ...]
) -> None:
    contour = topology.eye_contour(side)
    assert contour[topology.CONTOUR_OUTER_CORNER_POSITION] == outer
    assert contour[topology.CONTOUR_INNER_CORNER_POSITION] == inner
    assert tuple(contour[p] for p in topology.CONTOUR_LOWER_LID_POSITIONS) == lower
    assert tuple(contour[p] for p in topology.CONTOUR_UPPER_LID_POSITIONS) == upper
    assert len(lower) == len(upper) == 7


def test_contour_positions_partition_the_sixteen_slots() -> None:
    positions = (
        (topology.CONTOUR_OUTER_CORNER_POSITION,)
        + topology.CONTOUR_LOWER_LID_POSITIONS
        + (topology.CONTOUR_INNER_CORNER_POSITION,)
        + topology.CONTOUR_UPPER_LID_POSITIONS
    )
    assert positions == tuple(range(topology.EYE_CONTOUR_POINTS))


def test_face_oval_is_a_closed_loop_of_named_points() -> None:
    oval = topology.FACE_OVAL
    assert len(oval) == 36 == len(set(oval))
    assert all(0 <= index < topology.LANDMARK_COUNT_WITHOUT_IRIS for index in oval)
    assert oval[0] == topology.FOREHEAD == 10
    assert topology.CHIN == 152
    assert topology.NOSE_TIP == 1
    assert {topology.CHIN, topology.LEFT_FACE_EDGE, topology.RIGHT_FACE_EDGE} <= set(oval)
    assert topology.NOSE_TIP not in oval
    assert set(oval).isdisjoint(topology.LEFT_EYE_CONTOUR)
    assert set(oval).isdisjoint(topology.RIGHT_EYE_CONTOUR)
    # Clockwise in the image: top, subject's left edge (image right), chin, subject's right edge.
    assert oval.index(topology.LEFT_FACE_EDGE) < oval.index(topology.CHIN) < oval.index(topology.RIGHT_FACE_EDGE)


@pytest.mark.parametrize("side", ["up", "", "Left", "RIGHT", "centre", "l"])
def test_lookups_reject_unknown_sides(side: str) -> None:
    with pytest.raises(ValueError):
        topology.eye_contour(side)
    with pytest.raises(ValueError):
        topology.iris_indices(side)


# --- Cross-check against the MediaPipe package (skipped when it is not installed) ---


def _indices(connections: object) -> set[int]:
    return {index for connection in connections for index in (connection.start, connection.end)}


def _pairs(connections: object) -> set[tuple[int, int]]:
    return {(connection.start, connection.end) for connection in connections}


def _is_closed_traversal(loop: tuple[int, ...], connections: object) -> bool:
    """Every consecutive pair of ``loop`` (last -> first included) is a connection, either way round."""

    pairs = _pairs(connections)
    return all(
        (loop[i], loop[(i + 1) % len(loop)]) in pairs or (loop[(i + 1) % len(loop)], loop[i]) in pairs
        for i in range(len(loop))
    )


def test_index_sets_match_mediapipe_face_landmarks_connections() -> None:
    module = pytest.importorskip("mediapipe.tasks.python.vision.face_landmarker")
    connections = module.FaceLandmarksConnections

    assert set(topology.LEFT_EYE_CONTOUR) == _indices(connections.FACE_LANDMARKS_LEFT_EYE)
    assert set(topology.RIGHT_EYE_CONTOUR) == _indices(connections.FACE_LANDMARKS_RIGHT_EYE)
    assert set(topology.FACE_OVAL) == _indices(connections.FACE_LANDMARKS_FACE_OVAL)
    # The package's LEFT_IRIS is 474-477 and RIGHT_IRIS 469-472: the same
    # anatomical naming as ours (the centres 473/468 are not part of a connection).
    assert set(topology.LEFT_IRIS_CONTOUR) == _indices(connections.FACE_LANDMARKS_LEFT_IRIS) == {474, 475, 476, 477}
    assert set(topology.RIGHT_IRIS_CONTOUR) == _indices(connections.FACE_LANDMARKS_RIGHT_IRIS) == {469, 470, 471, 472}
    assert topology.LEFT_IRIS_CENTER not in _indices(connections.FACE_LANDMARKS_LEFT_IRIS)
    assert topology.RIGHT_IRIS_CENTER not in _indices(connections.FACE_LANDMARKS_RIGHT_IRIS)


def test_contour_orders_are_valid_traversals_of_mediapipe_connections() -> None:
    module = pytest.importorskip("mediapipe.tasks.python.vision.face_landmarker")
    connections = module.FaceLandmarksConnections

    assert _is_closed_traversal(topology.LEFT_EYE_CONTOUR, connections.FACE_LANDMARKS_LEFT_EYE)
    assert _is_closed_traversal(topology.RIGHT_EYE_CONTOUR, connections.FACE_LANDMARKS_RIGHT_EYE)
    assert _is_closed_traversal(topology.FACE_OVAL, connections.FACE_LANDMARKS_FACE_OVAL)
    assert _is_closed_traversal(topology.LEFT_IRIS_CONTOUR, connections.FACE_LANDMARKS_LEFT_IRIS)
    assert _is_closed_traversal(topology.RIGHT_IRIS_CONTOUR, connections.FACE_LANDMARKS_RIGHT_IRIS)
    # The helper is not vacuous: a scrambled order is rejected.
    scrambled = topology.LEFT_EYE_CONTOUR[::2] + topology.LEFT_EYE_CONTOUR[1::2]
    assert not _is_closed_traversal(scrambled, connections.FACE_LANDMARKS_LEFT_EYE)
