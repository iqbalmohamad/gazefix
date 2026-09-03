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

## Approved model asset and provenance

The approved M1 bundle is identified by all of the following values. Its generic
filename alone is not an identity check.

| Property | Approved value |
| --- | --- |
| Upstream | Google MediaPipe Face Landmarker model repository |
| Model identity | `face_landmarker/float16/1` |
| Versioned source | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` |
| Development location | `.models/face_landmarker.task` from repository root |
| Size | 3,758,596 bytes |
| SHA-256 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| License | Apache-2.0 |

`gazefix.tracking.model_asset` owns this manifest. The real MediaPipe backend
verifies the SHA-256 and size before importing or initializing MediaPipe. A
mismatch fails initialization with `TrackerInitializationError`; it is never
silently accepted as another model. Changing the source, model identity, or
digest requires an intentional code/documentation update plus repeat accuracy,
compatibility, privacy, license, and performance verification.

The model is ignored by Git and must be provisioned explicitly. Either pass
`--download-model` to the offline validator or use the manual download and
`Get-FileHash` commands in the repository README. Provisioning downloads to a
temporary sibling, verifies it, and only then atomically replaces the target. A
failed download or integrity check leaves an existing target untouched.

For a packaged release, place the exact verified bundle in an application-owned
resource directory and resolve that path explicitly; `.models` is a development
location, not a production search strategy. Preserve the MediaPipe and model
Apache-2.0 license text, applicable copyright/NOTICE material, and notices for
modifications. Audit the final distribution's transitive dependencies and model
contents rather than treating this manifest as a complete release license audit.

Model references:

- <https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker>
- <https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazeFace%20Short%20Range.pdf>
- <https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf>

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

## Offline real-adapter validator

The installed `gazefix-tracking-validate` command exercises the concrete
`MediaPipeFaceTracker` against a still image or prerecorded video file. It never
opens a webcam and does not import any GazeFix camera or pipeline module.

```powershell
.venv\Scripts\gazefix-tracking-validate.exe portrait.jpg --download-model
.venv\Scripts\gazefix-tracking-validate.exe recording.avi `
  --input-kind video `
  --model .models\face_landmarker.task `
  --overlay-output .tracking-output\recording-overlay.avi `
  --max-frames 300
```

Input type is normally inferred by attempting image decode first; use
`--input-kind image` or `video` to make it explicit. Image overlays use the
output extension supported by OpenCV. Video overlay output uses MJPG for `.avi`
and `mp4v` otherwise. The tool refuses to overwrite its source file and always
shuts the tracker down after initialization succeeds or file processing fails.

The JSON report includes total frames, frames with and without detected
landmarks, raw `no_face` outcomes, temporary-loss frames and contiguous events,
recoveries, low-confidence/invalid/error outcomes, and mean/median/p95 adapter
latency. `frames_with_no_face` means every processed frame whose result contains
no face, including temporary-loss and failure outcomes; the narrower state
counters explain why. For video, `effective_processing_throughput_frames_per_second`
is wall-clock file throughput across decode, tracking, and requested overlay/write
work. It is deliberately not named or presented as live webcam FPS.

### Recorded offline verification

On 2026-09-03, Windows 11 AMD64 and Python 3.12.10 were used with
`mediapipe==0.10.35`, its CPU/XNNPACK path, and the approved model above.
MediaPipe's Apache-2.0 `portrait.jpg` test asset was fetched from its own
test-data manifest and independently matched SHA-256
`a6f11efaa834706db23f275b6115058fa87fc7f14362681e6abe14e82749de3e`.
The test image is not committed to GazeFix.

- Still image: one face detected, 478 face landmarks, 16 points per eye and five
  per iris, zero invalid/error outcomes, and a visually inspected detached
  overlay. The cold single-frame adapter latency was 30.37 ms.
- Prerecorded transition sequence: 90 MJPG frames at 820×1024 and nominal 30
  frames/s, built from that portrait with two eight-frame blank intervals. The
  run produced 74 face frames, 16 frames without a face, two temporary-loss
  events, two recoveries, six terminal `no_face` outcomes, and zero invalid or
  tracker-error outcomes. Adapter latency was 24.02 ms mean, 17.62 ms median,
  and 46.11 ms p95. End-to-end offline file throughput was 30.81 frames/s with
  overlay output disabled.

These numbers characterize one local offline run and include warm-up/content
effects. They are not a live webcam result, a hardware performance guarantee, or
gaze accuracy evidence.

## Verification boundaries

Automated tests use injected backends and NumPy frames, not a webcam. The real
MediaPipe CPU adapter was additionally initialized with the official versioned
model and exercised against synthetic no-face frames, an official real-face test
image, and a prerecorded loss/recovery sequence. This verifies the standalone
provider path, landmark extraction, overlay, and offline diagnostics. It is not
physical-webcam tracking, live pipeline integration, or gaze estimation.

The future physical verification procedure is in
[m1-physical-verification.md](m1-physical-verification.md). Its items remain
unchecked until the M0 integration boundary is reopened.
