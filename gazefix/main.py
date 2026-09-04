"""GazeFix desktop application entry point."""

from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import os
from pathlib import Path

from gazefix.camera.environment import apply_capture_environment
from gazefix.config import AppSettings, default_model_directory
from gazefix.logging_config import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GazeFix camera preview with face and eye tracking")
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
        "--msmf-hw-transforms",
        type=int,
        choices=(0, 1),
        default=None,
        help=(
            "Windows only: 1 lets OpenCV's Media Foundation backend negotiate "
            "hardware transforms during camera open (OpenCV's own default), 0 "
            "skips them (GazeFix default; avoids multi-second MSMF opens)"
        ),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="development mode: show the tracking overlay toggle and tracking details",
    )
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="start with the tracking overlay enabled (development mode only)",
    )
    parser.add_argument(
        "--no-tracking",
        action="store_true",
        help="run the M0 passthrough preview without loading the face tracker",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help=f"directory containing face_landmarker.task (default: {default_model_directory()})",
    )
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
            msmf_hw_transforms=(
                AppSettings().msmf_hw_transforms
                if args.msmf_hw_transforms is None
                else bool(args.msmf_hw_transforms)
            ),
            developer_mode=args.dev,
            overlay_enabled=args.dev and args.overlay,
            tracking_enabled=not args.no_tracking,
            model_directory=args.model_dir or default_model_directory(),
        ).validated()
    except ValueError as exc:
        print(f"Invalid settings: {exc}", file=sys.stderr)
        return 2
    if args.overlay and not args.dev:
        print("--overlay requires --dev", file=sys.stderr)
        return 2

    log_path = configure_logging(settings.log_directory, settings.log_level)
    logger = logging.getLogger(__name__)
    # Must precede the OpenCV import below: a statically linked OpenCV runtime
    # snapshots the environment when it loads.
    exported = apply_capture_environment(settings)
    if exported:
        logger.info(
            "Capture environment applied",
            extra={"event": "capture_environment", **exported},
        )
    from gazefix.ui.main_window import MainWindow  # noqa: E402  (after env)

    logger.info(
        "Application starting",
        extra={
            "event": "application_starting",
            "python": sys.version,
            "platform": sys.platform,
            "tracking_enabled": settings.tracking_enabled,
            "developer_mode": settings.developer_mode,
            "model_directory": str(settings.model_directory),
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
    if window.tracker_thread_alive:
        # The tracking backend runs its native calls on a non-daemon worker
        # thread that the interpreter joins at exit; a call that never
        # returns would therefore hang the process after the window is gone.
        # Give it one more bounded grace period, then end the process.
        grace_s = settings.worker_join_timeout_s
        deadline = time.perf_counter() + grace_s
        while window.tracker_thread_alive and time.perf_counter() < deadline:
            time.sleep(0.05)
        if window.tracker_thread_alive:
            logger.error(
                "Tracker thread still inside a native call after the grace period; "
                "terminating the process",
                extra={"event": "forced_exit", "grace_s": grace_s, "exit_code": exit_code},
            )
            logging.shutdown()
            os._exit(exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

