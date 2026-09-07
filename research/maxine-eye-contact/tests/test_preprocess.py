"""Deterministic, symmetric source preparation."""

import pytest

from eval import preprocess


def test_encode_targets_mp4_h264_cfr_without_audio():
    args = " ".join(preprocess.ENCODE_ARGS)
    assert "-c:v libx264" in args
    assert "-an" in args
    assert "-vsync cfr" in args
    assert "-movflags +faststart" in args


def test_no_enhancement_filter_is_ever_applied():
    args = " ".join(preprocess.ENCODE_ARGS).lower()
    for forbidden in ("unsharp", "hqdn3d", "nlmeans", "eq=", "curves",
                      "colorbalance", "crop", "-vf", "-filter"):
        assert forbidden not in args


def test_command_is_identical_for_two_clips_apart_from_paths():
    first = preprocess.build_command("a.mp4", "x.mp4", ffmpeg="ffmpeg")
    second = preprocess.build_command("b.mp4", "y.mp4", ffmpeg="ffmpeg")
    strip = lambda cmd: [c for c in cmd if c not in
                         ("a.mp4", "b.mp4", "x.mp4", "y.mp4")]
    assert strip(first) == strip(second)


def test_trim_is_frame_accurate_after_the_input():
    command = preprocess.build_command(
        "a.mp4", "b.mp4", {"start_s": 1.5, "duration_s": 8}, ffmpeg="ffmpeg")
    assert command.index("-i") < command.index("-ss")
    assert command[command.index("-ss") + 1] == "1.500"
    assert command[command.index("-t") + 1] == "8.000"


def test_no_trim_means_no_seek_flags():
    command = preprocess.build_command("a.mp4", "b.mp4", ffmpeg="ffmpeg")
    assert "-ss" not in command and "-t" not in command


def test_missing_ffmpeg_is_reported(monkeypatch):
    monkeypatch.setattr(preprocess, "tool_path", lambda name: None)
    with pytest.raises(preprocess.FfmpegUnavailable):
        preprocess.build_command("a.mp4", "b.mp4")


def test_derive_records_both_hashes_and_shared_use(tmp_path, monkeypatch):
    source = tmp_path / "in.mov"
    source.write_bytes(b"source-bytes")
    destination = tmp_path / "out" / "P1A-01.mp4"

    def runner(command):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"derived-bytes")
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(preprocess, "tool_version", lambda name: "ffmpeg n7.0")
    record = preprocess.derive(source, destination, runner=runner, ffmpeg="ffmpeg")
    assert record["source_sha256"] != record["derived_sha256"]
    assert record["derived_bytes"] == len(b"derived-bytes")
    assert record["shared_by"] == ["MAXINE", "GEOMETRIC"]
    assert record["profile_id"] == preprocess.PROFILE_ID


def test_derive_reports_an_ffmpeg_failure(tmp_path):
    source = tmp_path / "in.mov"
    source.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        preprocess.derive(source, tmp_path / "o.mp4",
                          runner=lambda c: {"returncode": 1, "stderr": "boom"},
                          ffmpeg="ffmpeg")


def test_derive_reports_a_silently_missing_output(tmp_path):
    source = tmp_path / "in.mov"
    source.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        preprocess.derive(source, tmp_path / "o.mp4",
                          runner=lambda c: {"returncode": 0, "stderr": ""},
                          ffmpeg="ffmpeg")
