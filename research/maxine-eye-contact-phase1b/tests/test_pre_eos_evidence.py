"""Stage A's answer must come from a decoder, at full time resolution.

The first real run left a ~31.8 ms window between the last observed output byte
and input EOS in which output could not be ruled out, because the only byte
series was sampled on a 500 ms clock. It also reported 586 corrected frames for
an output independently proven to contain 240. These tests pin the repair for
both.
"""

from __future__ import annotations

from pathlib import Path

from conftest import build_progressive_mp4

from streamexp import decode, stages
from streamexp.channel import ChannelSpec
from streamexp.progressive import ProgressiveMp4Reader
from streamexp.session import SessionResult
from streamexp.stages import (
    RunOptions,
    _full_output_evidence,
    _pre_eos_evidence,
    _quarantine_parser_metrics,
)
from streamexp.timing import Timeline

EOS_MS = 8033.873


def result_with(chunks: list[tuple[float, int]], output: Path | None = None,
                eos_ms: float | None = EOS_MS) -> SessionResult:
    """A SessionResult carrying ``(t_ms, size)`` media chunks and an EOS mark."""
    timeline = Timeline()
    result = SessionResult(timeline=timeline, reader=ProgressiveMp4Reader())
    if eos_ms is not None:
        timeline.mark("input_eos", at=timeline.started_monotonic + eos_ms / 1000)
    cumulative = 0
    for t_ms, size in chunks:
        cumulative += size
        result.response_chunks.append(
            {"t_ms": t_ms, "bytes": size, "cumulative_bytes": cumulative}
        )
    result.bytes_received = cumulative
    result.output_path = output
    return result


def options_for(tmp_path: Path) -> RunOptions:
    return RunOptions(
        channel=ChannelSpec(target="127.0.0.1:1"),
        clone_dir=tmp_path,
        workspace=tmp_path,
        label="run",
    )


# -- boundary selection --------------------------------------------------


def test_a_chunk_inside_the_last_half_second_is_not_lost():
    """The 500 ms sampler could not see this; the per-chunk log must."""
    result = result_with([(100.0, 1367), (7900.0, 40_000)])
    cumulative, arrival = result.bytes_strictly_before(EOS_MS)
    assert arrival == 7900.0
    assert cumulative == 41_367, "a chunk 133 ms before EOS was dropped"


def test_a_chunk_after_eos_is_excluded_and_reported_separately():
    """The real run's burst landed 1.5 ms after EOS; it must not count."""
    result = result_with([(1968.5, 1367), (8035.4, 65_536)])
    cumulative, arrival = result.bytes_strictly_before(EOS_MS)
    assert (cumulative, arrival) == (1367, 1968.5)
    following = result.first_chunk_at_or_after(EOS_MS)
    assert following is not None and following["t_ms"] == 8035.4
    assert following["cumulative_bytes"] == 66_903


def test_a_chunk_exactly_at_eos_does_not_count_as_before_it():
    result = result_with([(EOS_MS, 5000)])
    assert result.bytes_strictly_before(EOS_MS) == (0, None)
    assert result.first_chunk_at_or_after(EOS_MS)["bytes"] == 5000


def test_no_media_before_eos_selects_nothing():
    result = result_with([(9000.0, 5000)])
    assert result.bytes_strictly_before(EOS_MS) == (0, None)


def test_the_boundary_is_the_last_of_many_chunks():
    chunks = [(float(i * 100), 1000) for i in range(1, 60)]
    result = result_with(chunks)
    cumulative, arrival = result.bytes_strictly_before(EOS_MS)
    assert arrival == 5900.0 and cumulative == 59_000


# -- the decoder-backed determination ------------------------------------


def test_zero_decodable_frames_before_eos_is_NO(tmp_path: Path, ffmpeg):
    """A prefix that carries stream metadata but no complete frame."""
    complete = tmp_path / "corrected.mp4"
    complete.write_bytes(build_progressive_mp4([4000] * 20))
    result = result_with([(1968.5, 1367), (8035.4, 60_000)], output=complete)

    evidence = _pre_eos_evidence(options_for(tmp_path), result, tmp_path)
    assert evidence["cumulative_bytes"] == 1367
    assert evidence["frames_decoded"] == 0
    assert evidence["decode_status"] == "EMPTY"
    assert evidence["determination"] == "NO"
    assert Path(evidence["artifact"]).stat().st_size == 1367


def test_at_least_one_decodable_frame_before_eos_is_YES(tmp_path: Path, ffmpeg):
    """A real, decodable clip delivered in full before EOS."""
    import subprocess

    complete = tmp_path / "corrected.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=128x96:rate=30", "-t", "1", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(complete)],
        check=True, capture_output=True, timeout=120,
    )
    size = complete.stat().st_size
    result = result_with([(1000.0, size)], output=complete)

    evidence = _pre_eos_evidence(options_for(tmp_path), result, tmp_path)
    assert evidence["cumulative_bytes"] == size
    assert evidence["decode_status"] == "VERIFIED"
    assert evidence["frames_decoded"] >= 1
    assert evidence["determination"] == "YES"


def test_a_decoder_that_cannot_examine_is_NOT_MEASURED(tmp_path: Path, monkeypatch):
    """A tool failure must never become a NO."""
    complete = tmp_path / "corrected.mp4"
    complete.write_bytes(build_progressive_mp4([4000] * 5))
    result = result_with([(1000.0, 2000)], output=complete)

    monkeypatch.setattr(
        decode, "examine",
        lambda path: decode.MediaExamination(
            "AMBIGUOUS", False, None, 0, "ffprobe not on PATH"
        ),
    )
    evidence = _pre_eos_evidence(options_for(tmp_path), result, tmp_path)
    assert evidence["determination"] == "NOT MEASURED"
    assert "not a NO" in evidence["reason"]


def test_no_bytes_at_all_before_eos_is_NO_without_a_decoder(tmp_path: Path):
    result = result_with([(9000.0, 5000)], output=None)
    evidence = _pre_eos_evidence(options_for(tmp_path), result, tmp_path)
    assert evidence["determination"] == "NO"
    assert evidence["decode_status"].startswith("NOT ATTEMPTED")


def test_an_input_that_never_reached_eos_is_NOT_MEASURED(tmp_path: Path):
    result = result_with([(1000.0, 5000)], eos_ms=None)
    evidence = _pre_eos_evidence(options_for(tmp_path), result, tmp_path)
    assert evidence["determination"] == "NOT MEASURED"


def test_the_boundary_never_comes_from_the_backlog_sampler(tmp_path: Path, ffmpeg):
    """Backlog rows are on a 500 ms grid and must not decide the cutoff."""
    complete = tmp_path / "corrected.mp4"
    complete.write_bytes(build_progressive_mp4([4000] * 20))
    result = result_with([(1968.5, 1367), (8035.4, 60_000)], output=complete)
    result.backlog_samples = [
        {"t_s": 7.5020, "bytes_received": 1367},
        {"t_s": 8.0021, "bytes_received": 1367},
        {"t_s": 8.5023, "bytes_received": 2_000_367},
    ]
    evidence = _pre_eos_evidence(options_for(tmp_path), result, tmp_path)
    assert evidence["cumulative_bytes"] == 1367
    assert "not the 500 ms backlog sampler" in evidence["boundary_source"]


# -- the parser quarantine -----------------------------------------------


def test_a_parser_decoder_disagreement_withdraws_the_parser_numbers():
    """586 parser frames against 240 decoded is not a measurement."""
    audit = {"parser_trusted": False, "agreement": "DISAGREE",
             "note": "parser counted 586 where a decoder counted 240"}
    frame_age = {
        "p50_frame_age_ms": 41.0, "p95_frame_age_ms": 88.0, "p99_frame_age_ms": 92.0,
        "max_frame_age_ms": 99.0, "age_growth_ms_per_frame": 0.1,
        "correspondence_intact": True,
    }
    determinations = {"output_input_frame_correspondence": "1:1 — 586 for 586"}

    _quarantine_parser_metrics(frame_age, determinations, audit)

    assert frame_age["parser_quarantined"] is True
    for key in ("p50_frame_age_ms", "p95_frame_age_ms", "p99_frame_age_ms",
                "max_frame_age_ms", "age_growth_ms_per_frame"):
        assert frame_age[key] == "INVALID — parser quarantined"
    assert frame_age["correspondence_intact"] == "NOT MEASURED"
    assert determinations["output_input_frame_correspondence"].startswith("NOT MEASURED")
    assert "586" in frame_age["quarantine_reason"]


def test_agreement_leaves_the_parser_numbers_alone():
    audit = {"parser_trusted": True, "agreement": "AGREE", "note": "match"}
    frame_age = {"p50_frame_age_ms": 41.0, "correspondence_intact": True}
    determinations = {"output_input_frame_correspondence": "1:1 — 240 for 240"}
    _quarantine_parser_metrics(frame_age, determinations, audit)
    assert frame_age["p50_frame_age_ms"] == 41.0
    assert "parser_quarantined" not in frame_age


def test_the_audit_counts_the_complete_output_with_a_decoder(tmp_path: Path, ffmpeg):
    complete = tmp_path / "corrected.mp4"
    complete.write_bytes(build_progressive_mp4([4000] * 12))
    result = result_with([(1000.0, complete.stat().st_size)], output=complete)
    result.frames = []  # the parser located nothing; the decoder is the authority
    audit = _full_output_evidence(result)
    assert audit["parser_frames"] == 0
    assert audit["agreement"] in ("AGREE", "DISAGREE")
    if audit["agreement"] == "DISAGREE":
        assert audit["parser_trusted"] is False


def test_an_unauditable_output_never_counts_as_agreement(tmp_path: Path, monkeypatch):
    complete = tmp_path / "corrected.mp4"
    complete.write_bytes(build_progressive_mp4([4000] * 5))
    result = result_with([(1000.0, 100)], output=complete)
    monkeypatch.setattr(
        stages.decode, "examine",
        lambda path: decode.MediaExamination("AMBIGUOUS", False, None, 0, "no tools"),
    )
    audit = _full_output_evidence(result)
    assert audit["parser_trusted"] is False
    assert audit["agreement"] == "NOT MEASURED"


def test_a_missing_output_file_is_not_an_audit_pass(tmp_path: Path):
    result = result_with([(1000.0, 100)], output=None)
    audit = _full_output_evidence(result)
    assert audit["parser_trusted"] is False
    assert audit["decoder_frames"] == "NOT MEASURED"
