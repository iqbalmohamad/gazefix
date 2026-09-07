"""Product Owner scoring rubric."""

import pytest

from eval import rubric


def test_all_nine_assignment_dimensions_are_present():
    assert [d["key"] for d in rubric.DIMENSIONS] == [
        "eye_realism", "iris_realism", "blink_realism", "eyelid_preservation",
        "identity_preservation", "temporal_stability", "artifact_visibility",
        "perceived_eye_contact", "overall_distraction"]


def test_both_closing_questions_use_the_assignment_choices():
    questions = {q["key"]: q["choices"] for q in rubric.QUESTIONS}
    assert questions["less_distracting_than_original"] == ("YES", "NO", "UNSURE")
    assert questions["would_use_in_real_call"] == ("YES", "NO", "MAYBE")


def test_every_dimension_declares_its_scale_direction():
    for dimension in rubric.DIMENSIONS:
        assert dimension["high_is_good"] is True
        assert dimension["low"].startswith("1 =")
        assert dimension["high"].startswith("5 =")


def test_verdicts_are_the_product_owner_vocabulary():
    assert rubric.VERDICTS == ("PASS", "ITERATE", "CHANGE APPROACH")


@pytest.mark.parametrize("value", [1, 3, 5, "4"])
def test_valid_scores_are_accepted(value):
    assert rubric.validate_score("eye_realism", value) == int(value)


@pytest.mark.parametrize("value", [0, 6, -1, "x", 2.5])
def test_out_of_range_scores_are_rejected(value):
    with pytest.raises(ValueError):
        rubric.validate_score("eye_realism", value)


def test_blank_score_means_unscored():
    assert rubric.validate_score("eye_realism", "") is None
    assert rubric.validate_score("eye_realism", None) is None


def test_unknown_dimension_is_rejected():
    with pytest.raises(KeyError):
        rubric.validate_score("charisma", 3)


def test_answers_are_normalised_and_validated():
    assert rubric.validate_answer("would_use_in_real_call", "maybe") == "MAYBE"
    assert rubric.validate_answer("would_use_in_real_call", "") is None
    with pytest.raises(ValueError):
        rubric.validate_answer("would_use_in_real_call", "UNSURE")
    with pytest.raises(ValueError):
        rubric.validate_answer("less_distracting_than_original", "MAYBE")


def test_blank_row_covers_every_column():
    row = rubric.blank_row("P1A-01", "A")
    assert set(row) == set(rubric.COLUMNS)
    assert row["clip_id"] == "P1A-01" and row["label"] == "A"


def test_sheet_validation_collects_errors_without_discarding_rows():
    rows = [{"clip_id": "P1A-01", "label": "A", "eye_realism": "4",
             "would_use_in_real_call": "no"},
            {"clip_id": "P1A-01", "label": "B", "eye_realism": "9"}]
    clean, errors = rubric.validate_sheet(rows)
    assert len(clean) == 2
    assert clean[0]["eye_realism"] == 4
    assert clean[0]["would_use_in_real_call"] == "NO"
    assert clean[1]["eye_realism"] is None
    assert len(errors) == 1 and "P1A-01/B" in errors[0]


def test_rubric_assigns_no_verdict_itself():
    """The engineer never holds the visual verdict."""
    assert not hasattr(rubric, "decide")
    assert not hasattr(rubric, "verdict")
