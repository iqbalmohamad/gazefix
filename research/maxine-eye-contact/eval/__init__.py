"""GazeFix Maxine Eye Contact Phase 1A — evaluation-only tooling.

RESEARCH/EVALUATION ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION.

This package is a bounded research spike. It is deliberately isolated from the
GazeFix product runtime: nothing here imports ``gazefix``, nothing here is
imported by ``gazefix``, and nothing here adds a product dependency. It is
standard library only so that it runs in the checkout's existing environment.

External binaries (``ffprobe``/``ffmpeg``) are invoked as subprocesses for
media inspection and deterministic remuxing. They are tools, not dependencies
of the product.
"""

__all__ = ["EVALUATION_NOTICE"]

EVALUATION_NOTICE = "RESEARCH/EVALUATION ONLY - NOT AUTHORIZED FOR GAZEFIX PRODUCTION"
