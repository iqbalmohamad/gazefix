#!/usr/bin/env python3
"""Entry script for the GazeFix Maxine Phase 1A evaluation driver.

RESEARCH/EVALUATION ONLY - NOT AUTHORIZED FOR GAZEFIX PRODUCTION.

The package directory contains a hyphen and so cannot be imported by name;
this script puts it on the path and hands over to ``eval.cli``.

    python research/maxine-eye-contact/run.py --help
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
