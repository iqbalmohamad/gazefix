"""Structured, rotating, local application logging."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_STANDARD_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    """Render one compact JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(log_directory: Path, level: str = "INFO") -> Path:
    """Configure console and rotating JSON-file logging, returning the log path."""

    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "gazefix.jsonl"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    formatter = JsonFormatter()
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    logging.getLogger(__name__).info(
        "Logging configured",
        extra={"event": "logging_configured", "log_path": str(log_path)},
    )
    return log_path

