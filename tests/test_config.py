from dataclasses import replace

import pytest

from gazefix.config import AppSettings


def test_default_settings_are_valid() -> None:
    settings = AppSettings().validated()

    assert settings.capture_width == 1280
    assert settings.capture_height == 720
    assert settings.target_fps == 30.0
    assert settings.log_level == "INFO"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capture_width", 0),
        ("capture_height", -1),
        ("target_fps", 0),
        ("camera_probe_limit", 0),
        ("camera_probe_limit", 33),
        ("transient_read_failures", 0),
        ("discovery_validation_reads", 0),
        ("stalled_read_s", 0),
        ("open_validation_timeout_s", 0),
        ("reconnect_delay_max_s", 0.5),
        ("tracking_wait_ms", 0),
        ("tracking_max_faces", 5),
        ("tracking_min_quality", 1.5),
        ("tracking_min_in_frame_fraction", -0.1),
        ("tracking_smoothing", 2.0),
        ("tracking_init_retry_max_s", 0.5),
        ("tracking_init_max_attempts", 0),
        ("tracking_max_rebuilds", 0),
        ("tracking_reset_gap_s", 0),
        ("tracking_join_timeout_s", 0),
        ("tracking_join_timeout_s", 3.0),  # 3.0 s + 0.1 s exceeds half of the 5 s worker deadline
    ],
)
def test_invalid_settings_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        replace(AppSettings(), **{field: value}).validated()

