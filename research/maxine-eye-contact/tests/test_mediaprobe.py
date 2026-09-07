"""Media probing and diagnostic normalisation."""

import pytest

from eval import mediaprobe

PAYLOAD = {
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "profile": "High",
         "width": 1280, "height": 720, "pix_fmt": "yuv420p",
         "avg_frame_rate": "30000/1001", "r_frame_rate": "30/1",
         "duration": "8.5083", "nb_frames": "255"},
        {"codec_type": "audio", "codec_name": "aac"},
    ],
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "8.51"},
}


def test_summarise_extracts_the_manifest_fields():
    out = mediaprobe.summarise(PAYLOAD)
    assert out["codec"] == "h264"
    assert (out["width"], out["height"]) == (1280, 720)
    assert out["duration_s"] == 8.508
    assert out["frame_count"] == 255
    assert out["audio_streams"] == 1
    assert out["audio_codecs"] == ["aac"]


def test_rational_frame_rates_are_parsed():
    out = mediaprobe.summarise(PAYLOAD)
    assert round(out["fps_avg"], 3) == 29.97
    assert out["fps_r"] == 30.0


@pytest.mark.parametrize("rate", ["0/0", "N/A", "", None, "1/0", "junk"])
def test_unusable_frame_rates_become_none(rate):
    payload = {"streams": [dict(PAYLOAD["streams"][0], avg_frame_rate=rate)],
               "format": {}}
    assert mediaprobe.summarise(payload)["fps_avg"] is None


def test_missing_video_stream_is_an_error():
    with pytest.raises(RuntimeError, match="no video stream"):
        mediaprobe.summarise({"streams": [{"codec_type": "audio"}], "format": {}})


def test_unparseable_duration_becomes_none():
    payload = {"streams": [dict(PAYLOAD["streams"][0], duration="N/A")],
               "format": {"duration": "N/A"}}
    assert mediaprobe.summarise(payload)["duration_s"] is None


def test_diagnostics_drop_the_aslr_pointer():
    first = mediaprobe.stable_diagnostic(
        "[mov,mp4,m4a @ 0x55ddee6536c0] moov atom not found")
    second = mediaprobe.stable_diagnostic(
        "[mov,mp4,m4a @ 0x5635c3a486c0] moov atom not found")
    assert first == second
    assert "0x<addr>" in first
    assert "moov atom not found" in first


def test_diagnostics_collapse_whitespace_and_are_bounded():
    assert mediaprobe.stable_diagnostic("  a\n\n  b  ") == "a b"
    assert len(mediaprobe.stable_diagnostic("x" * 900)) == 400
    assert mediaprobe.stable_diagnostic(None) == ""


def test_unmeasured_record_states_its_status():
    out = mediaprobe.unmeasured()
    assert out["codec"] == mediaprobe.NOT_MEASURED
    assert out["probe_status"] == mediaprobe.NOT_MEASURED
    assert out["width"] is None


def test_probe_reports_a_missing_ffprobe(monkeypatch):
    monkeypatch.setattr(mediaprobe, "tool_path", lambda name: None)
    with pytest.raises(mediaprobe.ProbeUnavailable):
        mediaprobe.probe("x.mp4")
