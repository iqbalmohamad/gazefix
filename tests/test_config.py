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
    ],
)
def test_invalid_settings_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        replace(AppSettings(), **{field: value}).validated()

