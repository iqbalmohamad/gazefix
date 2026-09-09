"""The decoder state model, and re-deciding a finished run offline.

Stage A's first real run stalled on a distinction the harness could not draw:
a prefix that a decoder *recognised and walked to EOF without finding a frame*
looked identical, in the summary, to a prefix no decoder had managed to read.
The first is an answer; the second is a missing measurement. These tests pin
the boundary between them, and pin the offline path that lets a completed run
be re-decided without spending GPU time again.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from conftest import build_progressive_mp4

from streamexp import decode, reanalyze


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- the decoder state model --------------------------------------------


def test_recognised_container_with_no_frames_is_EMPTY(metadata_only_prefix: Path):
    """ftyp + moov and nothing else: describable, not decodable."""
    exam = decode.examine(metadata_only_prefix)
    assert exam.status == "EMPTY"
    assert exam.frames_decoded == 0
    assert exam.stream_detected is True
    assert exam.determinate is True
    assert "enumerated 0 frames to EOF" in exam.detail


def test_a_complete_clip_is_VERIFIED(real_clip: Path):
    exam = decode.examine(real_clip)
    assert exam.status == "VERIFIED"
    assert exam.frames_decoded >= 1
    assert exam.stream_detected is True


def test_unrecognisable_input_is_AMBIGUOUS_not_EMPTY(tmp_path: Path):
    """"I cannot read this" must never be recorded as "there is nothing here"."""
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(bytes(range(256)) * 4)
    exam = decode.examine(junk)
    assert exam.status == "AMBIGUOUS"
    assert exam.frames_decoded is None
    assert exam.determinate is False


def test_a_container_shaped_file_with_no_real_bitstream_is_AMBIGUOUS(tmp_path: Path):
    """A synthetic sample table over filler is not evidence of zero frames."""
    path = tmp_path / "synthetic.mp4"
    path.write_bytes(build_progressive_mp4([4000] * 8))
    assert decode.examine(path).status == "AMBIGUOUS"


def test_an_empty_file_is_determinately_EMPTY(tmp_path: Path):
    path = tmp_path / "empty.mp4"
    path.write_bytes(b"")
    exam = decode.examine(path)
    assert (exam.status, exam.frames_decoded) == ("EMPTY", 0)


def test_no_decoder_at_all_is_AMBIGUOUS(real_clip: Path, monkeypatch):
    monkeypatch.setattr(decode, "tool", lambda name: None)
    exam = decode.examine(real_clip)
    assert exam.status == "AMBIGUOUS"
    assert "no independent examination" in exam.detail


def test_ffprobe_that_cannot_execute_is_AMBIGUOUS(real_clip: Path, monkeypatch):
    """A crashing or missing ffprobe must not decide anything."""
    monkeypatch.setattr(decode, "tool", lambda name: "/usr/bin/ffprobe" if name == "ffprobe" else None)
    monkeypatch.setattr(decode, "_run", lambda *a, **k: None)
    exam = decode.examine(real_clip)
    assert exam.status == "AMBIGUOUS"
    assert "could not be executed" in exam.detail


def test_ffprobe_returning_unparsable_output_is_AMBIGUOUS(real_clip: Path, monkeypatch):
    class Result:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(decode, "_run", lambda *a, **k: Result())
    assert decode.examine(real_clip).status == "AMBIGUOUS"


def test_a_recognised_container_with_no_countable_source_is_AMBIGUOUS(
    real_clip: Path, monkeypatch
):
    """ffprobe describes the stream, but nothing can count frames: no answer."""
    monkeypatch.setattr(decode, "_count_via_count_frames", lambda *a, **k: None)
    monkeypatch.setattr(decode, "_count_via_show_frames", lambda *a, **k: None)
    monkeypatch.setattr(
        decode, "tool", lambda name: "/usr/bin/ffprobe" if name == "ffprobe" else None
    )
    exam = decode.examine(real_clip)
    assert exam.status == "AMBIGUOUS"
    assert exam.stream_detected is True, "the container was still recognised"


def test_the_enumeration_rescues_a_prefix_ffprobe_cannot_count(
    metadata_only_prefix: Path, monkeypatch
):
    """-count_frames yields nothing on a truncated file; enumeration still decides."""
    monkeypatch.setattr(decode, "_count_via_count_frames", lambda *a, **k: None)
    exam = decode.examine(metadata_only_prefix)
    assert exam.status == "EMPTY"
    assert exam.frames_decoded == 0


# -- offline re-analysis -------------------------------------------------


def build_run(directory: Path, complete: bytes, head_bytes: int, *,
              eos_ms: float = 8033.911, first_ms: float = 420.866,
              burst_ms: float = 8090.528, parser_frames: int = 586,
              original_determination: str = "NOT MEASURED",
              with_chunks: bool = True) -> Path:
    """A finished Stage A run directory, shaped like the real v2 run."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "corrected.mp4").write_bytes(complete)
    (directory / "pre_eos_corrected.mp4").write_bytes(complete[:head_bytes])
    if with_chunks:
        with (directory / "response_chunks.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["t_ms", "bytes", "cumulative_bytes"])
            writer.writeheader()
            writer.writerow({"t_ms": first_ms, "bytes": head_bytes,
                             "cumulative_bytes": head_bytes})
            writer.writerow({"t_ms": burst_ms, "bytes": len(complete) - head_bytes,
                             "cumulative_bytes": len(complete)})
    (directory / "summary.json").write_text(
        json.dumps(
            {
                "stage": "A",
                "timing_ms_since_rpc_start": {
                    "input_eos_ms": eos_ms, "first_output_bytes_ms": first_ms,
                },
                "determinations": {
                    "usable_output_before_input_eos": original_determination
                },
                "pre_eos_evidence": {
                    "input_eos_ms": eos_ms, "cutoff_time_ms": first_ms,
                    "cumulative_bytes": head_bytes,
                    "decode_status": "AMBIGUOUS", "frames_decoded": "UNKNOWN",
                },
                "full_output_audit": {"parser_frames": parser_frames},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return directory


def test_reanalysis_turns_an_empty_pre_eos_prefix_into_a_stage_a_NO(
    tmp_path: Path, real_clip: Path, metadata_only_prefix: Path
):
    """The whole point: a run that could not decide can now decide, offline."""
    run = build_run(tmp_path / "run", real_clip.read_bytes(),
                    metadata_only_prefix.stat().st_size)
    payload = reanalyze.reanalyze_stage_a(run)

    assert payload["pre_eos_evidence"]["decode_status"] == "EMPTY"
    assert payload["pre_eos_evidence"]["frames_decoded"] == 0
    assert payload["pre_eos_evidence"]["ffprobe_stream_detected"] is True
    assert payload["determination"]["reanalysed"] == "NO"
    assert payload["determination"]["original"] == "NOT MEASURED"
    assert payload["determination"]["changed"] is True


def test_reanalysis_of_a_decodable_prefix_gives_YES(tmp_path: Path, real_clip: Path):
    data = real_clip.read_bytes()
    run = build_run(tmp_path / "run", data, len(data))
    payload = reanalyze.reanalyze_stage_a(run)
    assert payload["pre_eos_evidence"]["decode_status"] == "VERIFIED"
    assert payload["determination"]["reanalysed"] == "YES"


def test_reanalysis_never_recomputes_rpc_timing(
    tmp_path: Path, real_clip: Path, metadata_only_prefix: Path
):
    run = build_run(tmp_path / "run", real_clip.read_bytes(),
                    metadata_only_prefix.stat().st_size)
    original = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    payload = reanalyze.reanalyze_stage_a(run)

    carried = payload["carried_forward_unchanged"]
    assert carried["input_eos_ms"] == 8033.911
    assert carried["timing_ms_since_rpc_start"] == original["timing_ms_since_rpc_start"]
    assert any("carried forward" in note for note in payload["not_recomputed"])


def test_reanalysis_leaves_the_original_summary_untouched(
    tmp_path: Path, real_clip: Path, metadata_only_prefix: Path
):
    run = build_run(tmp_path / "run", real_clip.read_bytes(),
                    metadata_only_prefix.stat().st_size)
    before = sha256(run / "summary.json")
    prefix_before = sha256(run / "pre_eos_corrected.mp4")

    written, payload = reanalyze.write_reanalysis(run)

    assert sha256(run / "summary.json") == before
    assert sha256(run / "pre_eos_corrected.mp4") == prefix_before
    assert written.name == "reanalysis.json"
    assert payload["original_summary"]["sha256"] == before
    assert (run / "pre_eos_corrected.reanalysis.mp4").is_file(), (
        "the rebuilt prefix must go to its own name, never over the evidence"
    )


def test_reanalysis_rederives_the_boundary_from_the_chunk_log(
    tmp_path: Path, real_clip: Path, metadata_only_prefix: Path
):
    head = metadata_only_prefix.stat().st_size
    run = build_run(tmp_path / "run", real_clip.read_bytes(), head)
    boundary = reanalyze.reanalyze_stage_a(run)["recomputed_boundary"]

    assert boundary["source"].startswith("response_chunks.csv")
    assert boundary["cumulative_bytes"] == head
    assert boundary["cutoff_time_ms"] == 420.866
    assert boundary["first_chunk_at_or_after_eos"]["t_ms"] == 8090.528
    assert boundary["agrees_with_original"] is True


def test_reanalysis_without_a_chunk_log_says_so_rather_than_inventing_one(
    tmp_path: Path, real_clip: Path, metadata_only_prefix: Path
):
    head = metadata_only_prefix.stat().st_size
    run = build_run(tmp_path / "run", real_clip.read_bytes(), head, with_chunks=False)
    boundary = reanalyze.reanalyze_stage_a(run)["recomputed_boundary"]
    assert "response_chunks.csv is absent" in boundary["source"]
    assert boundary["cumulative_bytes"] == head


def test_reanalysis_reaudits_the_parser_against_a_decoder(
    tmp_path: Path, real_clip: Path, metadata_only_prefix: Path
):
    run = build_run(tmp_path / "run", real_clip.read_bytes(),
                    metadata_only_prefix.stat().st_size, parser_frames=586)
    audit = reanalyze.reanalyze_stage_a(run)["full_output_audit"]
    assert audit["parser_frames"] == 586
    assert isinstance(audit["decoder_frames"], int) and audit["decoder_frames"] != 586
    assert audit["agreement"] == "DISAGREE"
    assert audit["parser_trusted"] is False


def test_reanalysis_of_an_ambiguous_prefix_stays_NOT_MEASURED(
    tmp_path: Path, real_clip: Path, monkeypatch
):
    """A decoder that cannot examine the prefix must not produce a NO."""
    run = build_run(tmp_path / "run", real_clip.read_bytes(), 200)
    monkeypatch.setattr(
        reanalyze.decode, "examine",
        lambda path: decode.MediaExamination("AMBIGUOUS", False, None, 0, "no tools"),
    )
    payload = reanalyze.reanalyze_stage_a(run)
    assert payload["pre_eos_evidence"]["determination"] == "NOT MEASURED"
    assert "not a NO" in payload["pre_eos_evidence"]["reason"]


def test_reanalysis_refuses_a_directory_that_is_not_a_run(tmp_path: Path):
    with pytest.raises(reanalyze.ReanalysisError, match="summary.json"):
        reanalyze.reanalyze_stage_a(tmp_path)


def test_reanalysis_refuses_a_run_with_no_corrected_output(tmp_path: Path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(reanalyze.ReanalysisError, match="corrected.mp4"):
        reanalyze.reanalyze_stage_a(run)
