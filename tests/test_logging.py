import json
import logging

from gazefix.logging_config import JsonFormatter


def test_json_formatter_includes_structured_context() -> None:
    record = logging.LogRecord(
        "gazefix.test",
        logging.INFO,
        __file__,
        1,
        "camera ready",
        (),
        None,
    )
    record.event = "camera_ready"
    record.camera_index = 2

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "camera ready"
    assert payload["event"] == "camera_ready"
    assert payload["camera_index"] == 2
