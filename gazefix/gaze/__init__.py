"""Milestone 2 gaze estimation.

The package is deliberately independent of the tracking backend and of Qt:
``models`` is a plain data contract (NumPy only, and it imports nothing from
``gazefix.tracking``), ``estimator`` derives an approximate gaze direction from
the M1 ``TrackingResult``, and ``smoothing`` holds the small temporal filter.
``gazefix.tracking.models`` imports ``gazefix.gaze.models`` (one direction
only) so a tracking result can carry the gaze estimated for its own frame.

Read ``docs/gaze.md`` before changing signs, units or the confidence formula.
"""
