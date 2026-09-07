"""Scenario coverage reporting."""

from eval import scenarios


def test_all_eight_required_scenarios_are_present():
    assert len(scenarios.SCENARIOS) == 8
    assert len(set(scenarios.SCENARIO_IDS)) == 8


def test_every_scenario_maps_to_m3_capture_stems():
    known = set(scenarios.M3_STILL_STEMS) | set(scenarios.M3_CLIP_STEMS)
    for record in scenarios.SCENARIOS:
        assert record["m3_stems"], record["id"]
        assert set(record["m3_stems"]) <= known, record["id"]


def test_stem_to_scenario_mapping():
    assert scenarios.scenarios_for_stem("lens-glasses") == (
        "near-normal-gaze", "glasses")
    assert scenarios.scenarios_for_stem("blink-wink-squint") == ("blink",)
    assert scenarios.scenarios_for_stem("unknown-stem") == ()


def test_uncovered_scenarios_are_reported_not_backfilled():
    clips = [{"clip_id": "P1A-01", "scenarios": ["blink"]}]
    report = scenarios.coverage(clips)
    covered = [r for r in report if r["status"] == "COVERED"]
    assert [r["scenario"] for r in covered] == ["blink"]
    assert len(report) == 8
    for row in report:
        if row["scenario"] != "blink":
            assert row["status"] == scenarios.NOT_AVAILABLE
            assert row["clip_ids"] == []


def test_uncovered_lists_every_missing_scenario():
    assert set(scenarios.uncovered([])) == set(scenarios.SCENARIO_IDS)


def test_coverage_lists_every_covering_clip():
    clips = [{"clip_id": "P1A-01", "scenarios": ["glasses"]},
             {"clip_id": "P1A-02", "scenarios": ["glasses", "blink"]}]
    row = next(r for r in scenarios.coverage(clips) if r["scenario"] == "glasses")
    assert row["clip_ids"] == ["P1A-01", "P1A-02"]


def test_coverage_tolerates_a_clip_with_no_tags():
    assert scenarios.coverage([{"clip_id": "P1A-01"}])[0]["clip_ids"] == []
