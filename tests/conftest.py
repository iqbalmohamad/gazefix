"""Session-wide guards for the deterministic suite.

The default model directory derives from ``LOCALAPPDATA``; pointing it at
an empty temporary directory before ``gazefix`` is imported guarantees that
no test can load a real model that happens to be installed on the machine
(an accidental default-settings ``MainWindow`` fails fast with
``model_missing`` instead). The real-model tests read ``GAZEFIX_MODEL_DIR``,
which is pre-set here to the machine's original default model directory
unless the caller already exported it.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


_ORIGINAL_LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA")
_original_default = (
    Path(_ORIGINAL_LOCAL_APP_DATA) if _ORIGINAL_LOCAL_APP_DATA else Path.home() / ".local" / "state"
) / "GazeFix" / "models"
os.environ.setdefault("GAZEFIX_MODEL_DIR", str(_original_default))
_GUARD_DIR = tempfile.mkdtemp(prefix="gazefix-tests-")
os.environ["LOCALAPPDATA"] = _GUARD_DIR
