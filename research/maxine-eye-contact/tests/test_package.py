"""Blind comparison package and answer key."""

import pytest

from eval import blinding, package, rubric
from eval.hashing import read_json, sha256_file


def _clips(tmp_path, count=4, conditions=blinding.CONDITIONS):
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    clips = []
    for index in range(1, count + 1):
        clip_id = f"P1A-{index:02d}"
        paths = {}
        for condition in conditions:
            path = source / f"{clip_id}_{condition}.mp4"
            path.write_bytes(f"{clip_id}:{condition}".encode())
            paths[condition] = str(path)
        clips.append({"clip_id": clip_id, "conditions": paths})
    return clips


def test_package_presents_every_condition_under_a_neutral_label(tmp_path):
    manifest, _ = package.build(tmp_path / "pkg", "seed-1", _clips(tmp_path))
    assert manifest["clip_count"] == 4
    for clip in manifest["clips"]:
        labels = sorted(e["label"] for e in clip["entries"])
        assert labels == list(blinding.LABELS)


def test_presented_filenames_carry_only_the_label(tmp_path):
    manifest, _ = package.build(tmp_path / "pkg", "seed-1", _clips(tmp_path))
    for clip in manifest["clips"]:
        for entry in clip["entries"]:
            assert entry["file"].endswith(f"{clip['clip_id']}_{entry['label']}.mp4")


def test_presentation_never_leaks_a_method_name(tmp_path):
    package.build(tmp_path / "pkg", "seed-1", _clips(tmp_path))
    assert package.audit_presentation(tmp_path / "pkg" / "presentation") == []


def test_scorer_facing_manifest_contains_no_condition(tmp_path):
    manifest, _ = package.build(tmp_path / "pkg", "seed-1", _clips(tmp_path))
    text = str(manifest)
    for condition in (blinding.GEOMETRIC, blinding.MAXINE):
        assert condition not in text


def test_answer_key_lives_outside_the_presentation_tree(tmp_path):
    root = tmp_path / "pkg"
    package.build(root, "seed-1", _clips(tmp_path))
    key_file = root / package.KEY_DIRNAME / "answer-key.json"
    assert key_file.is_file()
    assert package.PRESENTATION_DIRNAME not in str(key_file.relative_to(root))
    assert not list((root / package.PRESENTATION_DIRNAME).rglob("answer-key*"))


def test_answer_key_maps_every_presented_file_back(tmp_path):
    root = tmp_path / "pkg"
    manifest, key = package.build(root, "seed-1", _clips(tmp_path))
    presented = {(c["clip_id"], e["label"]): e["sha256"]
                 for c in manifest["clips"] for e in c["entries"]}
    assert len(key["assignments"]) == len(presented)
    for row in key["assignments"]:
        assert presented[(row["clip_id"], row["label"])] == row["sha256"]
        assert row["condition"] in blinding.CONDITIONS


def test_presented_bytes_are_copied_verbatim(tmp_path):
    root = tmp_path / "pkg"
    _, key = package.build(root, "seed-1", _clips(tmp_path))
    for row in key["assignments"]:
        presented = root / package.PRESENTATION_DIRNAME / row["presented_file"]
        assert sha256_file(presented) == sha256_file(row["source_path"])


def test_package_is_reproducible_from_the_seed(tmp_path):
    clips = _clips(tmp_path)
    _, first = package.build(tmp_path / "a", "seed-9", clips)
    _, second = package.build(tmp_path / "b", "seed-9", clips)
    strip = lambda k: [(r["clip_id"], r["label"], r["condition"])
                       for r in k["assignments"]]
    assert strip(first) == strip(second)


def test_a_different_seed_reshuffles(tmp_path):
    clips = _clips(tmp_path, count=8)
    _, first = package.build(tmp_path / "a", "seed-1", clips)
    _, second = package.build(tmp_path / "b", "seed-2", clips)
    strip = lambda k: [(r["clip_id"], r["label"], r["condition"])
                       for r in k["assignments"]]
    assert strip(first) != strip(second)


def test_missing_condition_is_reported_not_hidden(tmp_path):
    clips = _clips(tmp_path, count=2)
    clips[0]["conditions"].pop(blinding.MAXINE)
    manifest, key = package.build(tmp_path / "pkg", "seed-1", clips)
    missing = {r["clip_id"]: r["missing"] for r in key["clips_missing_conditions"]}
    assert missing["P1A-01"] == [blinding.MAXINE]
    first = next(c for c in manifest["clips"] if c["clip_id"] == "P1A-01")
    assert len(first["entries"]) == 2


def test_a_clip_with_no_output_at_all_is_dropped_and_reported(tmp_path):
    clips = _clips(tmp_path, count=2)
    clips[1]["conditions"] = {}
    manifest, key = package.build(tmp_path / "pkg", "seed-1", clips)
    assert [c["clip_id"] for c in manifest["clips"]] == ["P1A-01"]
    assert any(r["clip_id"] == "P1A-02" for r in key["clips_missing_conditions"])


def test_scoring_sheet_has_a_row_per_clip_and_label(tmp_path):
    root = tmp_path / "pkg"
    manifest, _ = package.build(root, "seed-1", _clips(tmp_path))
    lines = (root / package.PRESENTATION_DIRNAME / "scores.csv").read_text().splitlines()
    assert lines[0].split(",") == list(rubric.COLUMNS)
    assert len(lines) == 1 + sum(len(c["entries"]) for c in manifest["clips"])


def test_viewer_marks_the_output_as_evaluation_only(tmp_path):
    root = tmp_path / "pkg"
    package.build(root, "seed-1", _clips(tmp_path))
    html = (root / package.PRESENTATION_DIRNAME / "index.html").read_text()
    assert "NOT AUTHORIZED FOR GAZEFIX PRODUCTION" in html


def test_package_manifest_is_written_and_self_hashed(tmp_path):
    root = tmp_path / "pkg"
    manifest, _ = package.build(root, "seed-1", _clips(tmp_path))
    written = read_json(root / package.PRESENTATION_DIRNAME / "package.json")
    assert written["manifest_sha256"] == manifest["manifest_sha256"]


def test_audit_catches_a_leaking_filename(tmp_path):
    root = tmp_path / "pkg"
    package.build(root, "seed-1", _clips(tmp_path))
    presentation = root / package.PRESENTATION_DIRNAME
    (presentation / "P1A-01" / "MAXINE_notes.txt").write_text("x", encoding="utf-8")
    findings = package.audit_presentation(presentation)
    assert any(f["kind"] == "path" and "MAXINE" in f["tokens"] for f in findings)


def test_audit_catches_leaking_content(tmp_path):
    root = tmp_path / "pkg"
    package.build(root, "seed-1", _clips(tmp_path))
    presentation = root / package.PRESENTATION_DIRNAME
    (presentation / "readme.txt").write_text("B is the geometric one",
                                             encoding="utf-8")
    findings = package.audit_presentation(presentation)
    assert any(f["kind"] == "content" for f in findings)


def test_a_seed_that_pins_a_condition_is_refused(tmp_path):
    """A deterministic shuffle can still, by chance, produce a weak blind."""
    clips = _clips(tmp_path, count=4)
    ids = [c["clip_id"] for c in clips]
    pinning = next(
        seed for seed in (f"s{i}" for i in range(500))
        if blinding.pinned_conditions([blinding.assign(seed, i) for i in ids]))
    with pytest.raises(package.WeakBlindError):
        package.build(tmp_path / "pkg", pinning, clips)


def test_suggest_seed_finds_a_usable_alternative(tmp_path):
    clips = _clips(tmp_path, count=4)
    ids = [c["clip_id"] for c in clips]
    pinning = next(
        seed for seed in (f"s{i}" for i in range(500))
        if blinding.pinned_conditions([blinding.assign(seed, i) for i in ids]))
    better = blinding.suggest_seed(
        pinning, lambda s: [blinding.assign(s, i) for i in ids])
    assert better and not blinding.pinned_conditions(
        [blinding.assign(better, i) for i in ids])
    manifest, _ = package.build(tmp_path / "pkg", better, clips)
    assert manifest["clip_count"] == 4
