"""Milestone 1 face and eye tracking.

The package is organised so that nothing outside ``mediapipe_tracker`` imports
MediaPipe: the result contract (``models``), landmark topology (``landmarks``),
asset verification (``assets``), primary-face selection (``selection``),
stabilisation (``stabilizer``), the processor integration (``processor`` and
``worker``) and the development overlay (``overlay``) depend only on NumPy and
OpenCV, so they are testable with fakes and importable without the model.
"""
