"""Whole-protocol walk-through with every external tool stubbed.

This exercises the ordering guarantees the protocol depends on: the held-out
set is frozen before any output exists, one derived input feeds both
conditions, and the resulting package is blind and reversible only through the
separate answer key.
"""

import json

import pytest

from eval import (blinding, geometric, maxine, package, preprocess, provenance,
                  redaction, sourceset)
from eval.hashing import read_json, sha256_file

FAKE_KEY = "nvapi-" + "Q1w2E3r4T5y6U7i8O9p0A1s2D3f4G5h6"


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "experiments" / "inputs"
    root.mkdir(parents=True)
    for index, stem in enumerate(sourceset.scen.M3_CLIP_STEMS):
        (root / f"{stem}.mp4").write_bytes(b"po-footage-" + bytes([index]) * 32)
    return root


def _freeze(inputs):
    candidates, _ = sourceset.discover(inputs)
    plan = sourceset.build_plan(candidates, inputs)
    return sourceset.freeze(plan, "2026-09-07T12:00:00Z",
                            provenance.repository_provenance())


def _derive(manifest, workspace):
    derived = {}
    for clip in sourceset.active_clips(manifest):
        destination = workspace / "derived" / f"{clip['clip_id']}.mp4"

        def runner(command, _dest=destination, _clip=clip):
            _dest.parent.mkdir(parents=True, exist_ok=True)
            _dest.write_bytes(b"derived:" + _clip["clip_id"].encode())
            return {"returncode": 0, "stdout": "", "stderr": ""}

        derived[clip["clip_id"]] = preprocess.derive(
            clip["source_path"], destination, trim=clip.get("trim"),
            runner=runner, ffmpeg="ffmpeg")
    return derived


def test_full_protocol_produces_a_blind_reversible_package(tmp_path, inputs):
    workspace = tmp_path / "ws"
    manifest = _freeze(inputs)
    assert manifest["clip_count"] == 3

    derived = _derive(manifest, workspace)

    # One derived input, shared by both conditions.
    for record in derived.values():
        assert record["shared_by"] == ["MAXINE", "GEOMETRIC"]

    geo, mx = {}, {}
    for clip_id, record in derived.items():
        out_dir = workspace / "geometric" / clip_id
        out_dir.mkdir(parents=True)
        (out_dir / "corrected.mp4").write_bytes(b"geo:" + clip_id.encode())
        geo[clip_id] = geometric.run(
            record["derived_path"], workspace / "geometric", clip_id,
            python_executable="py",
            runner=lambda c, w, t: {"returncode": 0, "stdout": "", "stderr": ""})

        maxine_out = workspace / "maxine" / f"{clip_id}.mp4"
        maxine_out.parent.mkdir(parents=True, exist_ok=True)

        def runner(command, cwd, env, timeout, _out=maxine_out, _id=clip_id):
            _out.write_bytes(b"mx:" + _id.encode())
            return {"returncode": 0, "stdout": "done", "stderr": ""}

        mx[clip_id] = maxine.run_clip(
            "/c/eye-contact.py", record["derived_path"], maxine_out,
            workspace / "l.py", env={maxine.API_KEY_ENV: FAKE_KEY},
            runner=runner, clock=iter([0.0, 4.0]).__next__)
        assert mx[clip_id]["success"]

    clips = [{"clip_id": c["clip_id"], "conditions": {
        blinding.ORIGINAL: derived[c["clip_id"]]["derived_path"],
        blinding.GEOMETRIC: geo[c["clip_id"]]["corrected_path"],
        blinding.MAXINE: mx[c["clip_id"]]["output"]}}
        for c in sourceset.active_clips(manifest)]

    built, key = package.build(workspace / "package", "phase1a-seed-2026-1", clips)

    assert built["clip_count"] == 3
    assert package.audit_presentation(workspace / "package" / "presentation") == []

    # Every presented file is a verbatim copy, and the answer key is the only
    # thing that maps a label back to the method that produced it.
    presentation = workspace / "package" / "presentation"
    for row in key["assignments"]:
        assert sha256_file(presentation / row["presented_file"]) == sha256_file(
            row["source_path"])
    for clip in built["clips"]:
        labels = {row["label"]: row["condition"] for row in key["assignments"]
                  if row["clip_id"] == clip["clip_id"]}
        assert sorted(labels) == sorted(e["label"] for e in clip["entries"])
        assert sorted(labels.values()) == sorted(blinding.CONDITIONS)

    # Nothing written anywhere in the run leaks the credential.
    assert redaction.scan_tree(workspace) == []
    assert redaction.scan_text(json.dumps(
        {k: v for k, v in mx.items()}, default=str)) == []


def test_freezing_after_outputs_exist_would_change_the_manifest(tmp_path, inputs):
    """A re-freeze that drops a clip is detectable, which is the whole point."""
    frozen = _freeze(inputs)
    (inputs / "minor-rotation.mp4").unlink()
    candidates, _ = sourceset.discover(inputs)
    refrozen = sourceset.freeze(sourceset.build_plan(candidates, inputs), "t",
                                provenance.repository_provenance())
    diff = sourceset.diff_membership(frozen, refrozen)
    assert diff["removed"] or diff["rehashed"]


def test_an_invalid_clip_is_excluded_but_still_presented_in_the_record(tmp_path, inputs):
    manifest = _freeze(inputs)
    sourceset.exclude(manifest, "P1A-02", "tracker found no face in any frame")
    assert len(manifest["clips"]) == 3
    assert len(sourceset.active_clips(manifest)) == 2
    excluded = next(c for c in manifest["clips"] if c["clip_id"] == "P1A-02")
    assert "no face" in excluded["exclusion"]["reason"]


def test_coverage_gaps_are_stated_for_the_three_clip_reality(tmp_path, inputs):
    """The three M3 clips cannot cover the still-only scenarios."""
    manifest = _freeze(inputs)
    uncovered = set(manifest["uncovered_scenarios"])
    assert {"near-normal-gaze", "horizontal-deviation", "downward-read",
            "glasses"} <= uncovered
    assert "blink" not in uncovered
    for row in manifest["coverage"]:
        if row["scenario"] in uncovered:
            assert row["status"] == sourceset.scen.NOT_AVAILABLE


def test_manifest_written_to_disk_matches_its_recorded_digest(tmp_path, inputs):
    from eval.hashing import manifest_digest, write_json
    manifest = _freeze(inputs)
    recorded = manifest.pop("manifest_sha256")
    assert manifest_digest(manifest) == recorded
    manifest["manifest_sha256"] = recorded
    write_json(tmp_path / "m.json", manifest)
    assert read_json(tmp_path / "m.json")["manifest_sha256"] == recorded
