"""Deterministic blinding of the two correction conditions."""

import collections

import pytest

from eval import blinding


def test_assignment_is_deterministic():
    first = blinding.assign("seed-1", "P1A-01")
    second = blinding.assign("seed-1", "P1A-01")
    assert first == second


def test_assignment_depends_on_the_seed():
    seeds = {tuple(sorted(blinding.assign(f"seed-{i}", "P1A-01").items()))
             for i in range(40)}
    assert len(seeds) > 1


def test_assignment_is_a_bijection():
    mapping = blinding.assign("s", "P1A-03")
    assert sorted(mapping) == list(blinding.LABELS)
    assert sorted(mapping.values()) == sorted(blinding.CONDITIONS)


def test_one_clip_assignment_does_not_depend_on_other_clips():
    """Excluding a clip must not re-roll the remaining clips' labels."""
    before = blinding.assign("s", "P1A-07")
    _ = [blinding.assign("s", f"P1A-{i:02d}") for i in range(1, 7)]
    assert blinding.assign("s", "P1A-07") == before


def test_each_condition_reaches_every_label_across_clips():
    seen = collections.defaultdict(set)
    for i in range(200):
        for label, condition in blinding.assign("s", f"P1A-{i:03d}").items():
            seen[condition].add(label)
    for condition in blinding.CONDITIONS:
        assert seen[condition] == set(blinding.LABELS)


def test_no_condition_is_pinned_to_one_label():
    counts = collections.Counter(
        blinding.assign("s", f"P1A-{i:03d}")["A"] for i in range(300))
    assert len(counts) == len(blinding.CONDITIONS)
    assert min(counts.values()) > 30


def test_subset_of_conditions_is_supported():
    mapping = blinding.assign("s", "P1A-01", (blinding.ORIGINAL, blinding.MAXINE))
    assert sorted(mapping) == ["A", "B"]
    assert sorted(mapping.values()) == sorted([blinding.ORIGINAL, blinding.MAXINE])


def test_duplicate_conditions_are_rejected():
    with pytest.raises(ValueError):
        blinding.assign("s", "c", (blinding.MAXINE, blinding.MAXINE))


def test_too_many_conditions_are_rejected():
    with pytest.raises(ValueError):
        blinding.assign("s", "c", ("A", "B", "C", "D"))


def test_answer_key_round_trips():
    key = blinding.answer_key("s", [("P1A-01", blinding.CONDITIONS),
                                    ("P1A-02", blinding.CONDITIONS)])
    for row in key["clips"]:
        for label, condition in row["labels"].items():
            assert blinding.condition_for(key, row["clip_id"], label) == condition
            assert blinding.label_for(key, row["clip_id"], condition) == label


def test_answer_key_rejects_unknown_lookups():
    key = blinding.answer_key("s", [("P1A-01", blinding.CONDITIONS)])
    with pytest.raises(KeyError):
        blinding.label_for(key, "P1A-99", blinding.MAXINE)
    with pytest.raises(KeyError):
        blinding.condition_for(key, "P1A-01", "Z")


def test_leaks_finds_method_tokens():
    assert blinding.leaks("P1A-01_MAXINE.mp4") == ["MAXINE"]
    assert "GEOMETRIC" in blinding.leaks("the geometric output")
    assert "NVIDIA" in blinding.leaks("nvidia hosted")


def test_leaks_does_not_flag_the_rubric_column():
    """The gate's subject is not a secret; which method produced a clip is."""
    assert blinding.leaks("perceived_eye_contact") == []
    assert blinding.leaks("Does the person appear to be looking at you?") == []


def test_pinning_check_needs_enough_clips_to_be_meaningful():
    """With one or two clips a shared label is unavoidable, not a defect."""
    single = [blinding.assign("s", "P1A-01")]
    assert blinding.pinned_conditions(single) == []
    assert blinding.pinned_conditions([]) == []


def test_pinned_conditions_detects_a_constant_label():
    constant = [{"A": blinding.MAXINE, "B": blinding.GEOMETRIC,
                 "C": blinding.ORIGINAL} for _ in range(4)]
    assert blinding.pinned_conditions(constant) == sorted(blinding.CONDITIONS)


def test_pinned_conditions_is_quiet_on_a_varied_assignment():
    varied = [{"A": blinding.MAXINE, "B": blinding.GEOMETRIC, "C": blinding.ORIGINAL},
              {"A": blinding.GEOMETRIC, "B": blinding.ORIGINAL, "C": blinding.MAXINE},
              {"A": blinding.ORIGINAL, "B": blinding.MAXINE, "C": blinding.GEOMETRIC}]
    assert blinding.pinned_conditions(varied) == []


def test_suggest_seed_returns_none_when_nothing_works():
    assert blinding.suggest_seed("s", lambda seed: [
        {"A": blinding.MAXINE, "B": blinding.GEOMETRIC, "C": blinding.ORIGINAL}
    ] * 4) is None
