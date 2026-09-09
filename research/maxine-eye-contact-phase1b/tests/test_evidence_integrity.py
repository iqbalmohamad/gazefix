"""Guards on the things that decide whether a run's answer can be trusted.

Each test here corresponds to a way a real run could have reported something
confidently wrong: a percentile drawn from a fraction of the stream, a FAIL with
no evidence about what the service actually returned, or a source file that
could not have answered the question in the first place.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import build_progressive_mp4

from streamexp import source
from streamexp.progressive import ProgressiveMp4Reader
from streamexp.session import SessionResult
from streamexp.stages import RunOptions, _check_stage_a_source, _corroborate, _correspondence
from streamexp.channel import ChannelSpec
from streamexp.timing import FrameRecord, Timeline, summarise_ages


def record(index: int, fed: float | None, usable: float) -> FrameRecord:
    return FrameRecord(index, index / 30, fed, usable, 100 * (index + 1))


# -- age coverage -------------------------------------------------------


def test_coverage_is_reported_so_a_partial_percentile_cannot_be_misread():
    """The p50 of a sixth of the stream is not the stream's p50."""
    records = [record(i, 0.0, 0.05) for i in range(3)]
    records += [record(i, None, 0.05) for i in range(3, 18)]
    summary = summarise_ages(records)
    assert summary["output_frames"] == 18
    assert summary["frames_with_age"] == 3
    assert summary["age_coverage"] == "3/18"
    assert summary["correspondence_intact"] is False
    assert "coverage_warning" in summary
    assert "3 of 18" in summary["coverage_warning"]


def test_full_coverage_reports_intact_and_warns_about_nothing():
    summary = summarise_ages([record(i, 0.0, 0.04) for i in range(10)])
    assert summary["age_coverage"] == "10/10"
    assert summary["correspondence_intact"] is True
    assert "coverage_warning" not in summary
    assert "correspondence_warning" not in summary
    assert summary["most_negative_age_ms"] is None


# -- correspondence integrity -------------------------------------------


def test_a_frame_arriving_before_its_source_was_sent_is_counted_not_averaged():
    """Negative age is physically impossible, so it must never enter a percentile."""
    records = [record(i, 1.0, 1.04) for i in range(8)]          # +40 ms, honest
    records += [record(i, 1.0, 0.90) for i in range(8, 10)]      # -100 ms, impossible
    summary = summarise_ages(records)
    assert summary["frames_usable_before_their_source_was_fed"] == 2
    assert summary["frames_with_age"] == 8
    assert summary["p50_frame_age_ms"] == pytest.approx(40, abs=1)
    assert summary["max_frame_age_ms"] == pytest.approx(40, abs=1)


def test_any_negative_age_says_the_ages_cannot_be_trusted():
    """The sender records the feed instant before the write, so the harness
    cannot manufacture a negative age by racing itself. One means correspondence
    broke."""
    records = [record(i, 1.0, 1.04) for i in range(9)]
    records.append(record(9, 1.0, 0.8))
    summary = summarise_ages(records)
    assert summary["most_negative_age_ms"] == pytest.approx(-200, abs=1)
    assert "cannot be trusted" in summary["correspondence_warning"]


def _result_with(frames: list[FrameRecord]) -> SessionResult:
    result = SessionResult(timeline=Timeline(), reader=ProgressiveMp4Reader())
    result.frames = frames
    return result


def test_correspondence_reports_one_to_one_when_counts_match_and_ages_are_sane():
    verdict = _correspondence(_result_with([record(i, 1.0, 1.04) for i in range(30)]), 30)
    assert verdict.startswith("1:1")


def test_correspondence_reports_a_count_mismatch():
    verdict = _correspondence(_result_with([record(i, 1.0, 1.04) for i in range(29)]), 30)
    assert verdict.startswith("MISMATCH")
    assert "29" in verdict and "30" in verdict


def test_correspondence_reports_broken_when_frames_precede_their_source():
    frames = [record(i, 1.0, 1.04) for i in range(29)] + [record(29, 1.0, 0.5)]
    assert _correspondence(_result_with(frames), 30).startswith("BROKEN")


def test_correspondence_is_not_measured_without_a_source_count():
    assert _correspondence(_result_with([record(0, 1.0, 1.04)]), None) == "NOT MEASURED"


# -- corroboration on the FAIL path -------------------------------------


def options_for(tmp_path: Path) -> RunOptions:
    return RunOptions(
        channel=ChannelSpec(target="127.0.0.1:1"),
        clone_dir=tmp_path,
        workspace=tmp_path,
        label="run",
    )


def test_a_fail_still_decodes_the_complete_output_as_evidence(tmp_path: Path, ffmpeg):
    """A bare NO cannot distinguish 'batches' from 'returned garbage'."""
    output = tmp_path / "run" / "corrected.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(build_progressive_mp4([400, 400, 400]))

    result = _result_with([])
    result.output_path = output
    result.bytes_received = output.stat().st_size
    result.first_usable_byte_end = None

    check = _corroborate(options_for(tmp_path), result, tmp_path)
    assert check["scope"].startswith("complete output")
    assert check["status"] in ("VERIFIED", "FAILED")
    assert "prefix_bytes" in check


def test_no_bytes_at_all_is_distinguished_from_an_undecodable_output(tmp_path: Path):
    output = tmp_path / "run" / "corrected.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"")

    result = _result_with([])
    result.output_path = output
    result.bytes_received = 0

    check = _corroborate(options_for(tmp_path), result, tmp_path)
    assert check["status"] == "NOT MEASURED"
    assert check["scope"] == "no output"


# -- source suitability -------------------------------------------------


def test_a_git_lfs_pointer_is_named_as_such(tmp_path: Path):
    path = tmp_path / "sample_streamable.mp4"
    path.write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:ab\nsize 1416533\n")
    with pytest.raises(source.SourceUnsuitable, match="Git LFS pointer"):
        source.probe(path)


def test_a_file_that_is_not_mp4_at_all_says_so(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"this is not a video file, not even a little bit")
    with pytest.raises(source.SourceUnsuitable, match="ftyp"):
        source.probe(path)


def test_a_missing_source_is_refused_before_anything_else(tmp_path: Path):
    with pytest.raises(source.SourceUnsuitable, match="does not exist"):
        source.probe(tmp_path / "absent.mp4")


def test_a_moov_last_source_is_refused_with_the_command_that_fixes_it(tmp_path: Path):
    """Stage A asks about streaming mode; a transactional file cannot answer it."""
    path = tmp_path / "transactional.mp4"
    path.write_bytes(build_progressive_mp4([300, 300], moov_first=False))
    profile, _index = source.probe(path)
    with pytest.raises(source.SourceUnsuitable) as excinfo:
        _check_stage_a_source(profile)
    assert "+faststart" in str(excinfo.value)
    assert "not about the service" in str(excinfo.value)


def test_a_streamable_source_passes_and_warns_about_its_size(tmp_path: Path):
    path = tmp_path / "small.mp4"
    path.write_bytes(build_progressive_mp4([300, 300, 300]))
    profile, _index = source.probe(path)
    warnings = _check_stage_a_source(profile)
    assert any("1280x720" in w for w in warnings)


def test_a_variable_rate_source_warns_rather_than_blocking(tmp_path: Path):
    """A trailing sample of a different length is ordinary; refusing would block valid runs."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(build_progressive_mp4([300, 300]))
    profile, _index = source.probe(path)
    vfr = source.SourceProfile(**{**profile.__dict__, "nominal_fps": None})
    warnings = _check_stage_a_source(vfr)
    assert any("variable frame rate" in w for w in warnings)
