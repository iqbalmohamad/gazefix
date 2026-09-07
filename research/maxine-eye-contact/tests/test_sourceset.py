"""Held-out set discovery and the mandatory pre-inference freeze."""

import pytest

from eval import scenarios, sourceset

PROVENANCE = {"head": "0" * 40, "branch": "test", "tracked_changes": False}


def _inputs(tmp_path, names, payload=b"video-bytes"):
    root = tmp_path / "inputs"
    root.mkdir(exist_ok=True)
    for index, name in enumerate(names):
        (root / name).write_bytes(payload + bytes([index]))
    return root


def test_m3_role_classification():
    assert sourceset.m3_role("lens-no-glasses") == sourceset.ROLE_SCORED
    assert sourceset.m3_role("horizontal-no-glasses") == sourceset.ROLE_SCORED
    assert sourceset.m3_role("speaking-smiling") == sourceset.ROLE_MATRIX
    assert sourceset.m3_role("lens-glasses") == sourceset.ROLE_MATRIX
    assert sourceset.m3_role("something-else") == sourceset.ROLE_OUTSIDE


def test_discovery_orders_m3_clips_canonically(tmp_path):
    root = _inputs(tmp_path, ["minor-rotation.mp4", "blink-wink-squint.mp4",
                              "speaking-smiling.mp4", "aardvark.mp4"])
    candidates, _ = sourceset.discover(root)
    assert [c["stem"] for c in candidates] == [
        "speaking-smiling", "minor-rotation", "blink-wink-squint", "aardvark"]


def test_discovery_skips_stills_with_a_reason(tmp_path):
    root = _inputs(tmp_path, ["lens-no-glasses.png"])
    candidates, skipped = sourceset.discover(root)
    assert candidates == []
    assert skipped and "STILL IMAGE" in skipped[0]["reason"]


def test_discovery_reports_ambiguous_stems(tmp_path):
    root = _inputs(tmp_path, ["minor-rotation.mp4", "minor-rotation.mov"])
    candidates, skipped = sourceset.discover(root)
    assert candidates == []
    assert any("AMBIGUOUS" in s["reason"] for s in skipped)


def test_discovery_requires_an_existing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        sourceset.discover(tmp_path / "absent")


def test_freeze_records_hashes_and_ids(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4", "minor-rotation.mp4"])
    candidates, _ = sourceset.discover(root)
    plan = sourceset.build_plan(candidates, root)
    manifest = sourceset.freeze(plan, "2026-09-07T00:00:00Z", PROVENANCE)
    assert manifest["clip_count"] == 2
    ids = [c["clip_id"] for c in manifest["clips"]]
    assert ids == ["P1A-01", "P1A-02"]
    for clip in manifest["clips"]:
        assert len(clip["source_sha256"]) == 64
        assert clip["source_bytes"] > 0
        assert clip["exclusion"] is None


def test_freeze_records_not_measured_when_ffprobe_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(sourceset, "probe",
                        lambda p: (_ for _ in ()).throw(sourceset.ProbeUnavailable("x")))
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    candidates, _ = sourceset.discover(root)
    manifest = sourceset.freeze(sourceset.build_plan(candidates, root),
                                "t", PROVENANCE)
    assert manifest["clips"][0]["media"]["codec"] == "NOT MEASURED"


def test_freeze_can_be_made_strict_about_probing(tmp_path, monkeypatch):
    monkeypatch.setattr(sourceset, "probe",
                        lambda p: (_ for _ in ()).throw(sourceset.ProbeUnavailable("x")))
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    candidates, _ = sourceset.discover(root)
    with pytest.raises(sourceset.ProbeUnavailable):
        sourceset.freeze(sourceset.build_plan(candidates, root), "t",
                         PROVENANCE, strict_probe=True)


def test_freeze_reports_uncovered_scenarios(tmp_path):
    root = _inputs(tmp_path, ["blink-wink-squint.mp4"])
    candidates, _ = sourceset.discover(root)
    manifest = sourceset.freeze(sourceset.build_plan(candidates, root),
                                "t", PROVENANCE)
    assert "glasses" in manifest["uncovered_scenarios"]
    assert "blink" not in manifest["uncovered_scenarios"]
    statuses = {r["scenario"]: r["status"] for r in manifest["coverage"]}
    assert statuses["glasses"] == scenarios.NOT_AVAILABLE


def test_freeze_rejects_a_duplicate_clip_id(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4", "minor-rotation.mp4"])
    plan = {"inputs_root": str(root), "clips": [
        {"clip_id": "P1A-01", "source_name": "speaking-smiling.mp4"},
        {"clip_id": "P1A-01", "source_name": "minor-rotation.mp4"}]}
    with pytest.raises(ValueError, match="duplicate clip_id"):
        sourceset.freeze(plan, "t", PROVENANCE)


def test_freeze_rejects_the_same_source_used_twice(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    plan = {"inputs_root": str(root), "clips": [
        {"clip_id": "P1A-01", "source_name": "speaking-smiling.mp4"},
        {"clip_id": "P1A-02", "source_name": "speaking-smiling.mp4"}]}
    with pytest.raises(ValueError, match="already used"):
        sourceset.freeze(plan, "t", PROVENANCE)


def test_freeze_rejects_a_missing_source(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    plan = {"inputs_root": str(root),
            "clips": [{"clip_id": "P1A-01", "source_name": "absent.mp4"}]}
    with pytest.raises(FileNotFoundError):
        sourceset.freeze(plan, "t", PROVENANCE)


def test_freeze_rejects_an_unknown_scenario_tag(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    plan = {"inputs_root": str(root), "clips": [
        {"clip_id": "P1A-01", "source_name": "speaking-smiling.mp4",
         "scenarios": ["not-a-scenario"]}]}
    with pytest.raises(ValueError, match="unknown scenario"):
        sourceset.freeze(plan, "t", PROVENANCE)


@pytest.mark.parametrize("trim", [
    {"start_s": -1, "duration_s": 5},
    {"start_s": 0, "duration_s": 0},
    {"start_s": 0},
    {"start_s": "x", "duration_s": 5},
    "not-an-object",
])
def test_freeze_rejects_an_invalid_trim(tmp_path, trim):
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    plan = {"inputs_root": str(root), "clips": [
        {"clip_id": "P1A-01", "source_name": "speaking-smiling.mp4", "trim": trim}]}
    with pytest.raises(ValueError):
        sourceset.freeze(plan, "t", PROVENANCE)


def test_manifest_digest_is_stable_and_self_describing(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    candidates, _ = sourceset.discover(root)
    plan = sourceset.build_plan(candidates, root)
    first = sourceset.freeze(plan, "t", PROVENANCE)
    second = sourceset.freeze(plan, "t", PROVENANCE)
    assert first["manifest_sha256"] == second["manifest_sha256"]


def test_verify_unchanged_detects_edited_and_missing_sources(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4", "minor-rotation.mp4"])
    candidates, _ = sourceset.discover(root)
    manifest = sourceset.freeze(sourceset.build_plan(candidates, root), "t", PROVENANCE)
    assert all(r["status"] == "OK" for r in sourceset.verify_unchanged(manifest))
    (root / "speaking-smiling.mp4").write_bytes(b"tampered")
    (root / "minor-rotation.mp4").unlink()
    statuses = {r["clip_id"]: r["status"] for r in sourceset.verify_unchanged(manifest)}
    assert statuses == {"P1A-01": "CHANGED", "P1A-02": "MISSING"}


def test_exclusion_retains_the_clip_and_its_reason(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4", "minor-rotation.mp4"])
    candidates, _ = sourceset.discover(root)
    manifest = sourceset.freeze(sourceset.build_plan(candidates, root), "t", PROVENANCE)
    sourceset.exclude(manifest, "P1A-02", "no face detected in any frame")
    assert len(manifest["clips"]) == 2
    excluded = next(c for c in manifest["clips"] if c["clip_id"] == "P1A-02")
    assert excluded["exclusion"]["reason"]
    assert [c["clip_id"] for c in sourceset.active_clips(manifest)] == ["P1A-01"]


def test_exclusion_requires_a_reason(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    candidates, _ = sourceset.discover(root)
    manifest = sourceset.freeze(sourceset.build_plan(candidates, root), "t", PROVENANCE)
    with pytest.raises(ValueError):
        sourceset.exclude(manifest, "P1A-01", "")
    with pytest.raises(KeyError):
        sourceset.exclude(manifest, "P1A-99", "reason")


def test_membership_diff_catches_cherry_picking(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4", "minor-rotation.mp4"])
    candidates, _ = sourceset.discover(root)
    plan = sourceset.build_plan(candidates, root)
    frozen = sourceset.freeze(plan, "t", PROVENANCE)

    dropped = {"clips": [c for c in frozen["clips"] if c["clip_id"] != "P1A-02"]}
    assert sourceset.diff_membership(frozen, dropped)["removed"] == ["P1A-02"]

    added = {"clips": frozen["clips"] + [{"clip_id": "P1A-09", "source_sha256": "x"}]}
    assert sourceset.diff_membership(frozen, added)["added"] == ["P1A-09"]

    swapped = {"clips": [dict(c, source_sha256="z" * 64) for c in frozen["clips"]]}
    assert sourceset.diff_membership(frozen, swapped)["rehashed"] == ["P1A-01", "P1A-02"]


def test_membership_diff_is_empty_for_an_unchanged_manifest(tmp_path):
    root = _inputs(tmp_path, ["speaking-smiling.mp4"])
    candidates, _ = sourceset.discover(root)
    frozen = sourceset.freeze(sourceset.build_plan(candidates, root), "t", PROVENANCE)
    diff = sourceset.diff_membership(frozen, frozen)
    assert diff == {"added": [], "removed": [], "rehashed": []}


def test_freeze_digest_is_reproducible_when_the_probe_fails(tmp_path):
    """ffmpeg embeds an ASLR pointer in its errors; a freeze token must not."""
    root = _inputs(tmp_path, ["speaking-smiling.mp4"], payload=b"not-a-real-mp4")
    candidates, _ = sourceset.discover(root)
    plan = sourceset.build_plan(candidates, root)
    first = sourceset.freeze(plan, "t", PROVENANCE)
    second = sourceset.freeze(plan, "t", PROVENANCE)
    assert first["manifest_sha256"] == second["manifest_sha256"]
    note = first["clips"][0]["media"].get("probe_note", "")
    assert "0x" not in note or "0x<addr>" in note
