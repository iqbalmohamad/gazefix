"""Maxine Eye Contact Phase 1B — realtime streaming feasibility harness.

RESEARCH/EXPERIMENT ONLY. Nothing here is GazeFix product code, and nothing in
``gazefix`` imports this package.

The package exists to answer one question and no other:

    Can one continuously-open ``RedirectGaze`` RPC consume H.264 media
    generated incrementally at webcam rate, return decodable corrected frames
    while capture is still occurring, and maintain bounded frame age without
    queue growth?

It measures. It does not conclude on Maxine's behalf, and it contains no
fallback path to any other service.
"""

__all__ = ["VERSION"]

VERSION = "0.1.0"
