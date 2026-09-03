"""GazeFix desktop application entry point."""

from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gazefix.config import AppSettings
from gazefix.logging_config import configure_logging
from gazefix.ui.main_window import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GazeFix Milestone 0 camera preview")
    parser.add_argument(
        "--probe-limit",
        type=int,
        default=5,
        help="number of numerical OpenCV camera indexes to validate (default: 5)",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--auto-exit-ms",
        type=int,
        default=0,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = replace(
            AppSettings(),
            camera_probe_limit=args.probe_limit,
            capture_width=args.width,
            capture_height=args.height,
            target_fps=args.fps,
            log_level=args.log_level,
        ).validated()
    except ValueError as exc:
        print(f"Invalid settings: {exc}", file=sys.stderr)
        return 2

    log_path = configure_logging(settings.log_directory, settings.log_level)
    logger = logging.getLogger(__name__)
    logger.info(
        "Application starting",
        extra={
            "event": "application_starting",
            "python": sys.version,
            "platform": sys.platform,
        },
    )

    application = QApplication([sys.argv[0], *(argv or [])])
    application.setApplicationName("GazeFix")
    window = MainWindow(settings, str(log_path))
    window.show()
    if args.auto_exit_ms > 0:
        QTimer.singleShot(args.auto_exit_ms, window.close)
    exit_code = application.exec()
    logger.info(
        "Application exited",
        extra={"event": "application_exited", "exit_code": exit_code},
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

