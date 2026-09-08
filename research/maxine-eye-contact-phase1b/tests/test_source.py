"""Stage A's delivery schedule: a byte is not sent before its frame exists."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import build_progressive_mp4

from streamexp import mp4, source


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(build_progressive_mp4([400, 380, 420, 360, 390]))
    return path


def test_probe_reports_what_the_container_says(clip: Path):
    profile, index = source.probe(clip)
    assert profile.streamable and not profile.fragmented
    assert profile.frame_count == 5
    assert profile.nominal_fps == pytest.approx(30)
    assert profile.duration_seconds == pytest.approx(5 / 30)
    assert profile.size_bytes == clip.stat().st_size
    assert len(profile.sha256) == 64
    assert index.frame_count() == 5


def test_every_byte_of_the_file_is_delivered_exactly_once(clip: Path):
    _profile, index = source.probe(clip)
    units = list(source.paced_units(clip, index, chunk_size=64))
    assert b"".join(unit.payload for unit in units) == clip.read_bytes()


def test_no_write_exceeds_the_chunk_size(clip: Path):
    _profile, index = source.probe(clip)
    units = list(source.paced_units(clip, index, chunk_size=64))
    assert units and all(len(unit.payload) <= 64 for unit in units)


def test_the_header_goes_out_immediately_and_media_follows_its_timestamps(clip: Path):
    """ftyp+moov is a live stream's init segment: available at t=0."""
    _profile, index = source.probe(clip)
    units = list(source.paced_units(clip, index, chunk_size=4096))
    mdat = next(a for a in mp4.iter_atoms(clip.read_bytes()) if a.type == "mdat")

    header_bytes = 0
    for unit in units:
        if unit.media_time != 0.0:
            break
        header_bytes += len(unit.payload)
    assert header_bytes >= mdat.body_offset - 4096

    media_times = [unit.media_time for unit in units]
    assert media_times == sorted(media_times), "delivery must never move backwards"
    assert max(media_times) == pytest.approx(4 / 30)


def test_each_frame_index_is_announced_exactly_once_and_in_order(clip: Path):
    _profile, index = source.probe(clip)
    announced = [i for unit in source.paced_units(clip, index, 64) for i in unit.frame_indices]
    assert announced == [0, 1, 2, 3, 4]


def test_a_frame_index_is_attached_to_the_write_that_completes_it(clip: Path):
    _profile, index = source.probe(clip)
    ends = {sample.index: sample.end for sample in index.samples}
    position = 0
    for unit in source.paced_units(clip, index, chunk_size=64):
        position += len(unit.payload)
        for frame_index in unit.frame_indices:
            assert position == ends[frame_index]


def test_a_file_with_no_video_samples_is_refused(tmp_path: Path):
    path = tmp_path / "empty.mp4"
    path.write_bytes(build_progressive_mp4([100]))
    _profile, index = source.probe(path)
    index.samples.clear()
    with pytest.raises(ValueError):
        list(source.paced_units(path, index, 64))
