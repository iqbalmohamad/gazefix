"""Workspace layout for a Phase 1A run.

Everything a run produces lives under an ignored local directory. Source
footage and rendered outputs are never committed; manifests and hashes are the
committed record, exactly as the M3 evaluation convention requires ("PO imagery
belongs only in ignored local experiment directories", docs/correction.md).
"""

from __future__ import annotations

from pathlib import Path

#: Default ignored workspace, alongside the M3 harness's ``experiments/``.
DEFAULT_WORKSPACE = Path("experiments/maxine-phase1a")
DEFAULT_INPUTS = Path("experiments/inputs")


class Workspace:
    """Resolved directories for one Phase 1A run."""

    def __init__(self, root):
        self.root = Path(root)

    @property
    def plan_file(self):
        return self.root / "source-plan.json"

    @property
    def manifest_file(self):
        return self.root / "source-manifest.json"

    @property
    def derived(self):
        return self.root / "derived"

    @property
    def derived_manifest(self):
        return self.root / "derived-manifest.json"

    @property
    def geometric(self):
        return self.root / "geometric"

    @property
    def geometric_manifest(self):
        return self.root / "geometric-manifest.json"

    @property
    def maxine(self):
        return self.root / "maxine"

    @property
    def maxine_manifest(self):
        return self.root / "maxine-manifest.json"

    @property
    def package(self):
        return self.root / "package"

    @property
    def presentation(self):
        return self.package / "presentation"

    @property
    def answer_key(self):
        return self.package / "answer-key" / "answer-key.json"

    @property
    def client(self):
        return self.root / "nvidia-client"

    @property
    def launcher(self):
        return self.root / "nvidia-client" / "_gazefix_launcher.py"

    @property
    def preflight(self):
        return self.root / "preflight.json"

    @property
    def integrity(self):
        return self.root / "integrity.json"

    def ensure(self):
        self.root.mkdir(parents=True, exist_ok=True)
        return self
