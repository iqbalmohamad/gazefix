"""Deterministic primary-face selection across frames."""

from __future__ import annotations

import numpy as np

from gazefix.tracking.selection import PrimaryFaceSelector, Selection, SelectionSettings
from gazefix.tracking.tracker import RawFace
from tracking_fakes import make_raw_face, shift, synthetic_landmarks


def _face(center: tuple[float, float], face_height: float = 0.3, seed: int = 0) -> RawFace:
    return make_raw_face(synthetic_landmarks(center=center, face_height=face_height, seed=seed))


def _box_face(x0: float, y0: float, x1: float, y1: float) -> RawFace:
    """A face whose bounding box is exactly the given (binary-fraction) box, so ties are exact."""

    points = np.full((478, 3), (x0 + x1) / 2.0, dtype=np.float32)
    points[:, 1] = (y0 + y1) / 2.0
    points[0, :2] = (x0, y0)
    points[1, :2] = (x1, y1)
    points[2, :2] = (x0, y1)
    points[3, :2] = (x1, y0)
    points[:, 2] = 0.0
    return make_raw_face(points)


def test_no_faces_gives_none_and_identity_expires_after_memory_frames() -> None:
    selector = PrimaryFaceSelector(SelectionSettings(memory_frames=3))
    assert not selector.has_identity
    assert selector.select([]) is None
    assert not selector.has_identity

    assert selector.select([_face((0.5, 0.5))]) is not None
    assert selector.has_identity
    assert selector.select([]) is None
    assert selector.has_identity  # 1 miss
    assert selector.select([]) is None
    assert selector.has_identity  # 2 misses
    assert selector.select([]) is None
    assert not selector.has_identity  # 3 misses = memory_frames


def test_default_memory_is_fifteen_frames_and_a_hit_resets_the_count() -> None:
    selector = PrimaryFaceSelector()
    assert SelectionSettings() == SelectionSettings(identity_max_jump=0.25, memory_frames=15)
    selector.select([_face((0.5, 0.5))])
    for _ in range(14):
        selector.select([])
    assert selector.has_identity
    selector.select([_face((0.5, 0.5))])  # a detection resets the miss counter
    for _ in range(14):
        selector.select([])
    assert selector.has_identity
    selector.select([])
    assert not selector.has_identity


def test_largest_face_wins_when_nothing_is_remembered() -> None:
    small_centred = _face((0.5, 0.5), face_height=0.2)
    large_off_centre = _face((0.25, 0.5), face_height=0.45)

    selection = PrimaryFaceSelector().select([small_centred, large_off_centre])

    assert selection is not None
    assert selection.index == 1
    assert not selection.identity_changed
    assert selection.center == (0.25, 0.5) or np.allclose(selection.center, (0.25, 0.5), atol=1e-6)
    assert selection.area > 0.45 * 0.45 * 0.75 * 0.99


def test_ties_go_to_the_face_nearest_the_frame_centre() -> None:
    off_centre = _box_face(0.125, 0.375, 0.375, 0.625)  # centre (0.25, 0.5)
    centred = _box_face(0.375, 0.375, 0.625, 0.625)  # centre (0.5, 0.5), same area

    selection = PrimaryFaceSelector().select([off_centre, centred])
    assert selection is not None and selection.index == 1

    selection = PrimaryFaceSelector().select([centred, off_centre])
    assert selection is not None and selection.index == 0


def test_full_ties_go_to_the_lowest_backend_index() -> None:
    left = _box_face(0.25, 0.375, 0.5, 0.625)  # centre (0.375, 0.5), 0.125 from the frame centre
    right = _box_face(0.5, 0.375, 0.75, 0.625)  # centre (0.625, 0.5), also 0.125 away

    selection = PrimaryFaceSelector().select([left, right])
    assert selection is not None and selection.index == 0

    selection = PrimaryFaceSelector().select([right, left])
    assert selection is not None and selection.index == 0

    twin_a, twin_b = _box_face(0.25, 0.25, 0.5, 0.5), _box_face(0.25, 0.25, 0.5, 0.5)
    selection = PrimaryFaceSelector().select([twin_a, twin_b])
    assert selection is not None and selection.index == 0


def test_a_remembered_face_is_kept_when_a_larger_one_appears_elsewhere() -> None:
    selector = PrimaryFaceSelector(SelectionSettings(identity_max_jump=0.25))
    first = selector.select([_face((0.65, 0.5), face_height=0.25)])
    assert first is not None and first.index == 0 and not first.identity_changed

    large = _face((0.25, 0.5), face_height=0.45)
    same_person = make_raw_face(shift(synthetic_landmarks(center=(0.65, 0.5), face_height=0.25), 0.02, 0.01))

    selection = selector.select([large, same_person])

    assert selection is not None
    assert selection.index == 1
    assert not selection.identity_changed
    assert np.allclose(selection.center, (0.67, 0.51), atol=1e-5)


def test_identity_switches_to_the_largest_face_after_a_jump_beyond_the_limit() -> None:
    selector = PrimaryFaceSelector(SelectionSettings(identity_max_jump=0.25))
    selector.select([_face((0.65, 0.5), face_height=0.25)])

    large = _face((0.25, 0.5), face_height=0.45)  # 0.4 from the remembered centre
    selection = selector.select([large])
    assert selection is not None
    assert selection.index == 0
    assert selection.identity_changed

    # The new identity is the one that is now remembered.
    returning = _face((0.65, 0.5), face_height=0.25)
    following = selector.select([returning, large])
    assert following is not None
    assert following.index == 1
    assert not following.identity_changed


def test_jump_limit_is_inclusive() -> None:
    selector = PrimaryFaceSelector(SelectionSettings(identity_max_jump=0.25))
    selector.select([_box_face(0.25, 0.25, 0.5, 0.5)])  # centre (0.375, 0.375)

    at_limit = selector.select([_box_face(0.5, 0.25, 0.75, 0.5)])  # centre (0.625, 0.375): exactly 0.25 away
    assert at_limit is not None and not at_limit.identity_changed

    selector = PrimaryFaceSelector(SelectionSettings(identity_max_jump=0.25))
    selector.select([_box_face(0.25, 0.25, 0.5, 0.5)])
    beyond = selector.select([_box_face(0.5, 0.25, 0.8125, 0.5)])  # centre (0.65625, 0.375): 0.28 away
    assert beyond is not None and beyond.identity_changed


def test_a_drifting_face_stays_primary_next_to_a_larger_static_one() -> None:
    selector = PrimaryFaceSelector(SelectionSettings(identity_max_jump=0.25))
    static_large = _face((0.25, 0.5), face_height=0.45)
    small = synthetic_landmarks(center=(0.7, 0.3), face_height=0.25)
    assert selector.select([make_raw_face(small)]) is not None

    for step in range(1, 9):  # drifts 0.4 in total, far more than one jump limit
        drifted = make_raw_face(shift(small, 0.0, 0.05 * step))
        selection = selector.select([static_large, drifted])
        assert selection is not None
        assert selection.index == 1, step
        assert not selection.identity_changed


def test_reset_forgets_the_identity() -> None:
    selector = PrimaryFaceSelector()
    small = _face((0.65, 0.5), face_height=0.25)
    large = _face((0.25, 0.5), face_height=0.45)
    selector.select([small])
    assert selector.has_identity

    selector.reset()

    assert not selector.has_identity
    selection = selector.select([small, large])
    assert selection is not None
    assert selection.index == 1  # largest wins again
    assert not selection.identity_changed  # nothing was remembered, so nothing changed


def test_selection_is_deterministic_for_the_same_input_sequence() -> None:
    frames: list[list[RawFace]] = [
        [_face((0.5, 0.5), face_height=0.3)],
        [_face((0.25, 0.5), face_height=0.45), _face((0.52, 0.5), face_height=0.3)],
        [],
        [_face((0.25, 0.5), face_height=0.45), _face((0.55, 0.52), face_height=0.3)],
        [_face((0.25, 0.5), face_height=0.45)],
        [_face((0.6, 0.5), face_height=0.3), _face((0.25, 0.5), face_height=0.45)],
    ]

    def run() -> list[Selection | None]:
        selector = PrimaryFaceSelector()
        return [selector.select(frame) for frame in frames]

    first, second = run(), run()
    assert first == second
    assert [None if s is None else (s.index, s.identity_changed) for s in first] == [
        (0, False),
        (1, False),
        None,
        (1, False),
        (0, True),
        (1, False),
    ]


def test_smaller_nearby_face_cannot_capture_the_memory_while_the_primary_is_missing() -> None:
    from gazefix.tracking.selection import PrimaryFaceSelector, SelectionSettings
    from tracking_fakes import make_raw_face, synthetic_landmarks

    selector = PrimaryFaceSelector(SelectionSettings(identity_max_jump=0.3, identity_area_ratio=2.0))
    primary = make_raw_face(synthetic_landmarks(center=(0.5, 0.5), face_height=0.5))
    background = make_raw_face(synthetic_landmarks(center=(0.6, 0.45), face_height=0.15))
    first = selector.select((primary, background))
    assert first is not None and first.index == 0
    # The primary is undetected for a frame; the small background face is
    # near the remembered centre but far outside the area ratio: it is
    # selected (largest available) with an explicit identity change, and it
    # does not inherit the memory. When the user reappears they are matched
    # again without an identity change.
    second = selector.select((background,))
    assert second is not None and second.identity_changed
    third = selector.select((primary, background))
    assert third is not None and third.index == 0 and not third.identity_changed
    # A clearly larger newcomer does take over at once.
    newcomer = make_raw_face(synthetic_landmarks(center=(0.3, 0.5), face_height=0.8))
    fourth = selector.select((newcomer, background))
    assert fourth is not None and fourth.index == 0 and fourth.identity_changed
    fifth = selector.select((newcomer, primary))
    assert fifth is not None and fifth.index == 0 and not fifth.identity_changed
