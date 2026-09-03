# Milestone 1 standalone tracking foundation

## Scope and integration status

This package implements face, eye, and iris landmark tracking metadata without
gaze estimation or image correction. It is standalone and hardware-independent:
no camera discovery, camera source, capture worker, camera switching, retry, or
shutdown implementation was modified.

`FrameProcessor` integration is deferred while Milestone 0 camera hardening is in
parallel review. The current application therefore continues to show the M0
passthrough preview.

## Dependency decision

GazeFix pins `mediapipe==0.10.35` and runs its Face Landmarker with the CPU
delegate. This version was selected because:

- PyPI publishes Windows AMD64 and ARM64 wheels and Python 3.9–3.12 classifiers.
- Installation and import were verified on Windows 11 AMD64 with Python 3.12.10.
- The Face Landmarker returns 478 normalized 3D landmarks, including ten iris
  points, and supports video-mode temporal tracking.
- MediaPipe and the face detector/mesh model cards use Apache License 2.0.
- It does not introduce ONNX Runtime, CUDA, or an NPU requirement.

The newer PyPI `1.0.1` artifact was investigated but not selected: on 2026-09-03
the downloaded Windows AMD64 wheel did not match the SHA-256 published by PyPI,
and pip rejected it. The pin must not be advanced until package integrity, API
compatibility, privacy behavior, and test coverage are re-verified.

MediaPipe requires `opencv-contrib-python`. GazeFix therefore replaces
`opencv-python` with `opencv-contrib-python>=4.10,<5`; both distributions provide
the same `cv2` namespace and must not coexist in one environment. The full camera
regression suite passes with the contrib distribution.

For redistribution, include the Apache 2.0 license and required attribution or
NOTICE material for both code and bundled models, record any modifications, and
audit all transitive package licenses. A `.task` model is not included
automatically by PyInstaller, so a release build must explicitly bundle it and
resolve its installed path. GazeFix does not commit the model bundle in this
foundation branch.

Primary references:

- <https://pypi.org/project/mediapipe/0.10.35/>
- <https://developers.google.com/edge/mediapipe/solutions/setup_python>
- <https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python>
- <https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker>
- <https://github.com/google-ai-edge/mediapipe/blob/v0.10.35/LICENSE>

## Public tracking API

`FaceTracker` is a structural protocol with four operations:

```python
tracker.initialize()
result = tracker.track(frame, frame_sequence=sequence, timestamp_ns=captured_at_ns)
metrics = tracker.metrics_snapshot()
tracker.shutdown()
```

`MediaPipeFaceTracker` also supports a context manager. `initialize` and
`shutdown` are idempotent while initialization after shutdown is rejected.
Tracking before initialization or after shutdown returns an explicit result state
instead of raising into the video pipeline.

The default MediaPipe adapter expects a BGR `numpy.uint8` array shaped
`(height, width, 3)`. It converts BGR to a private contiguous RGB array, calls the
provider, and returns metadata. It never modifies or returns the source image.

## Result and coordinate semantics

`TrackingResult` contains:

- source frame sequence and monotonic timestamp in nanoseconds,
- source frame width and height,
- all detected `TrackedFace` values,
- a deterministic primary-face index,
- result state and `TrackingReliability`,
- measured adapter processing time,
- an error message for invalid/lifecycle/provider failures.

Landmarks are immutable `NormalizedLandmark` values. `x` and `y` are normalized
by frame width and height and may be outside `[0, 1]` when the inferred feature is
beyond the image boundary. `z` is provider-relative depth using approximately the
same scale as normalized `x`; it is not metric depth or gaze direction.
`to_pixel(width, height)` performs explicit clipped conversion for rendering.

Each primary face exposes the full landmark set plus these subsets:

- left-eye contour: 16 points,
- right-eye contour: 16 points,
- left iris: center plus four contour points (indices 473–477),
- right iris: center plus four contour points (indices 468–472).

If a future backend returns fewer than 478 landmarks, iris subsets remain empty;
the adapter never fabricates missing points.

## Reliability and failure semantics

MediaPipe applies configured detection, presence, and tracking thresholds but its
Face Landmarker Tasks result does not expose per-face confidence. Such results are
marked `accepted` with `confidence=None` instead of inventing a number. An
injectable backend that provides a real score is compared to the application
threshold and can produce `low_confidence` while retaining the actual landmarks.

| State | Meaning | Landmarks |
| --- | --- | --- |
| `tracked` | Backend accepted a primary face | Actual provider output |
| `low_confidence` | A supplied score is below the application threshold | Actual provider output |
| `no_face` | No face is currently established | Empty |
| `temporarily_lost` | A recently tracked face was missed within the configured grace window | Empty |
| `invalid_frame` | Input type, dtype, shape, dimensions, sequence, or timestamp is invalid | Empty |
| `tracker_error` | Provider inference raised an exception | Empty |
| `not_initialized` | `track` was called before initialization | Empty |
| `shutdown` | `track` was called after shutdown | Empty |

These states are metadata only. They do not imply capture or video-pipeline
failure, and callers should continue publishing the original frame.

## Primary-face policy

The default configuration tracks one face so MediaPipe can apply landmark
smoothing. When `max_faces` is deliberately set above one, the primary face is
selected by:

1. largest normalized landmark bounding-box area,
2. shortest bounding-box-center distance from image center,
3. stable geometric coordinates and source index as deterministic tie-breakers.

Float geometry is normalized to twelve decimal places for ranking so insignificant
provider representation noise does not defeat area or center ties.

## Debug overlay

`DebugOverlayRenderer` is development-only. It draws face points, eye contours,
iris contours/centers, state, and confidence onto a detached BGR copy. It is not
used by the application runtime and cannot mutate the capture frame.

## Diagnostics

`TrackingMetricsSnapshot` reports frames seen, tracked frames, detected faces,
no-face frames, temporary losses, low-confidence frames, invalid frames, tracker
errors, an exponentially weighted mean processing time, and the last state. It
contains no image data.

## Verification boundaries

Automated tests use injected backends and NumPy frames, not a webcam. The real
MediaPipe CPU adapter was additionally initialized with the official versioned
model and exercised against synthetic black 640×480 frames. This verifies provider
initialization and no-face behavior but is not physical-webcam or real-face
tracking verification.
