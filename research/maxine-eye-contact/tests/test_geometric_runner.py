"""Frozen geometric baseline invocation."""

import pytest

from eval import geometric


def test_frozen_clip_settings_match_the_m3_po_batch():
    """scripts/correction_batch.py 'po' mode runs clips at these exact flags."""
    assert geometric.FROZEN_CLIP_ARGS == (
        "--strength", ".7", "--debug", "--max-frames", "1200")


def test_frozen_defaults_record_variant_c_and_the_optical_axis():
    assert geometric.FROZEN_DEFAULTS["variant"] == "layered"
    assert geometric.FROZEN_DEFAULTS["target_yaw"] == 0.0
    assert geometric.FROZEN_DEFAULTS["target_pitch"] == 0.0
    assert geometric.FROZEN_DEFAULTS["effective_strength"] is None


def test_argv_invokes_the_frozen_harness_on_a_video():
    argv = geometric.build_argv("clip.mp4", "out", "P1A-01")
    assert argv[:2] == ["--video", "clip.mp4"]
    for flag in geometric.FROZEN_CLIP_ARGS:
        assert flag in argv
    assert argv[argv.index("--name") + 1] == "P1A-01"


def test_command_targets_the_frozen_harness_module():
    command = geometric.build_command("py", "c.mp4", "out", "P1A-01")
    assert command[1:3] == ["-m", geometric.HARNESS_MODULE]


def test_unmirror_is_passed_through():
    assert "--unmirror" in geometric.build_argv("c.mp4", "o", "n", unmirror=True)
    assert "--unmirror" not in geometric.build_argv("c.mp4", "o", "n")


@pytest.mark.parametrize("flag", [
    "--strength", "--effective-strength", "--variant", "--set", "--target-yaw",
    "--target-pitch", "--eye-model-ratio", "--stabilizer", "--gaze-smoothing",
    "--max-frames", "--every", "--repeat", "--face-scale", "--canvas",
    "--sweep-strength",
])
def test_retuning_the_frozen_baseline_is_refused(flag):
    with pytest.raises(geometric.FrozenSettingsViolation):
        geometric.build_argv("c.mp4", "o", "n", extra=[flag, "1"])


def test_retuning_is_refused_in_equals_form():
    with pytest.raises(geometric.FrozenSettingsViolation):
        geometric.build_argv("c.mp4", "o", "n", extra=["--strength=0.9"])


def test_model_dir_is_still_allowed():
    argv = geometric.build_argv("c.mp4", "o", "n", extra=["--model-dir", "/m"])
    assert argv[-2:] == ["--model-dir", "/m"]


def test_clean_output_is_the_corrected_video_not_a_labelled_sheet():
    """side_by_side and debug carry burned-in text and must never be presented."""
    assert geometric.CLEAN_OUTPUT == "corrected.mp4"
    assert "side_by_side.mp4" in geometric.UNBLINDABLE_OUTPUTS
    assert "debug.mp4" in geometric.UNBLINDABLE_OUTPUTS
    assert geometric.CLEAN_OUTPUT not in geometric.UNBLINDABLE_OUTPUTS


def test_run_records_the_command_and_output_paths(tmp_path):
    def runner(command, cwd, timeout):
        return {"returncode": 0, "stdout": "done", "stderr": ""}

    record = geometric.run("c.mp4", tmp_path, "P1A-01", python_executable="py",
                           runner=runner)
    assert record["returncode"] == 0
    assert record["corrected_path"].endswith("P1A-01/corrected.mp4")
    assert record["report_path"].endswith("P1A-01/report.json")
    assert record["frozen_settings"]["explicit_flags"] == list(
        geometric.FROZEN_CLIP_ARGS)


def test_reused_output_must_match_the_source_bytes():
    """Canonical geometric output only counts if it came from the same bytes."""
    assert geometric.baseline_matches_source({"source": {"sha256": "a" * 64}}, "a" * 64)
    assert not geometric.baseline_matches_source({"source": {"sha256": "a" * 64}}, "b" * 64)
    assert not geometric.baseline_matches_source({"source": {}}, "a" * 64)
    assert not geometric.baseline_matches_source({}, "a" * 64)
    assert not geometric.baseline_matches_source(None, "a" * 64)
