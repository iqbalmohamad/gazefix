"""Explicit one-time model setup command (``scripts/fetch_model.py``).

Downloads the pinned face landmarker bundle from its documented source into
the model directory, verifies size and SHA-256, and prints one JSON object.
This is the only code path in GazeFix that uses the network, and it runs only
when a person invokes it. Exit codes: 0 verified (downloaded or already
present), 1 failure, 2 bad arguments.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

from gazefix.config import default_model_directory
from gazefix.tracking.assets import FACE_LANDMARKER, ModelAssetError, provision_model, verify_model


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and verify the GazeFix face landmarker model (explicit setup step)"
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help=f"directory for {FACE_LANDMARKER.filename} (default: {default_model_directory()})",
    )
    parser.add_argument("--verify-only", action="store_true", help="never download; report the current state")
    parser.add_argument("--force", action="store_true", help="download even if a verified copy exists")
    parser.add_argument("--timeout", type=float, default=60.0, help="network timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.timeout > 0 or math.isnan(args.timeout):
        parser.error("--timeout must be positive")
    directory = args.model_dir or default_model_directory()
    target = FACE_LANDMARKER.path_in(directory)
    report: dict[str, object] = {
        "model": asdict(FACE_LANDMARKER),
        "path": str(target),
    }
    try:
        if args.verify_only:
            verified = verify_model(target)
            report.update({"verified": True, "downloaded": False, "sha256": verified.sha256, "size_bytes": verified.size_bytes})
        else:
            result = provision_model(directory, timeout_s=args.timeout, force=args.force)
            report.update(
                {
                    "verified": True,
                    "downloaded": result.downloaded,
                    "download_ms": result.download_ms,
                    "sha256": result.verified.sha256,
                    "size_bytes": result.verified.size_bytes,
                }
            )
        exit_code = 0
    except ModelAssetError as exc:
        report.update({"verified": False, "error_kind": exc.kind, "error": str(exc)})
        exit_code = 1
    print(json.dumps(report, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
