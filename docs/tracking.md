# Milestone 1 — Face and Eye Tracking

This document is the reference for what M1 tracking produces, how it is
computed, which threads own what, and how failures are bounded. The result
contract lives in `gazefix/tracking/models.py`; the analysis rules in
`gazefix/tracking/analysis.py`; the threads in `gazefix/tracking/worker.py`
and `gazefix/tracking/processor.py`. Nothing here estimates where the eyes
look: head pose is head orientation only, and eye-direction estimation is a
later milestone.

## 1. Backend

MediaPipe Tasks `FaceLandmarker` (package `mediapipe` 1.0.1, CPU delegate,
video running mode, blendshapes disabled) with the verified
`face_landmarker.task` bundle (see `models/README.md` and
`docs/decisions/ADR-0001-face-tracker-mediapipe.md`). Inference runs
entirely on the local CPU (XNNPACK) with no GPU or NPU; GazeFix's own code
uses no network at runtime, but the library performs a usage-logging upload
when a landmarker is closed (section 13). The backend is hidden behind
`gazefix.tracking.tracker.FaceTracker`; everything else in the package
works on plain arrays and is exercised by fakes.

## 2. Result contract (`TrackingResult`)

Every processed frame published by the pipeline (`ProcessedFrame.tracking`)
carries exactly one `TrackingResult` that names that frame:

| Field | Meaning |
| --- | --- |
| `capture_sequence` | capture-buffer sequence of the frame (unique, increasing, never reset by a camera change; distinct from the output buffer's own `VersionedValue.sequence`) |
| `captured_at_ns` | the frame's capture timestamp |
| `camera_request_id` | the camera generation the frame belongs to |
| `status` | one of the statuses below |
| `geometry` | width/height of the frame the coordinates refer to; `mirrored` is always `False` for tracker output |
| `timing` | `inference_ms`, `total_ms`, `waited_ms` (section 6) |
| `message` | human-readable reason for any non-`TRACKED` status |
| `faces_detected` | how many faces the backend reported (only the primary one is described) |
| `landmarks` | `(478, 3)` read-only float32, normalised (section 3); present for `TRACKED` and `LOW_QUALITY` only |
| `right_eye`, `left_eye` | `EyeLandmarks`: 16-point eyelid contour, iris (5 points) or `None`, `openness`, `width_px`, `valid` (eye geometry only; `TrackingResult.eyes_valid` additionally requires `face_valid`) |
| `iris_available` | `True` when the tracker delivered iris landmarks (the 478-point topology) |
| `pose` | `HeadPose` or `None` |
| `quality` | `TrackingQuality` (section 4) |
| `stabilized` | whether the landmark stabiliser was active for this result |

A consumer must check `belongs_to(capture_sequence, camera_request_id)`
against the frame it displays; the window does, and the runtime's
`consume_latest_output` already drops whole frames of a superseded
generation.

### Statuses

| Status | Landmarks | `face_valid` | Meaning |
| --- | --- | --- | --- |
| `TRACKED` | yes | `True` | primary face with quality ≥ `tracking_min_quality` and both eyes valid |
| `LOW_QUALITY` | yes | `False` | a face was found but the output is partial or unreliable (`message` says why: quality below threshold, an eye outside the frame or narrower than `tracking_min_eye_width_px`) |
| `NO_FACE` | no | `False` | the tracker ran and found no face |
| `INITIALIZING` | no | `False` | the tracker is being created (model load, first attempt or restart) |
| `UNAVAILABLE` | no | `False` | the tracker cannot run; `message` is actionable (missing/corrupt model, import failure, exhausted attempts) |
| `ERROR` | no | `False` | inference raised or returned malformed data for this frame |
| `TIMEOUT` | no | `False` | the frame was published before its own result was ready (slow or stalled tracker) |

With `--no-tracking` the application uses the M0 passthrough processor and
`ProcessedFrame.tracking` is `None`; there is no "disabled" status.

Only `TRACKED` means valid full tracking. Partial data never masquerades as
valid: `LOW_QUALITY` keeps the landmarks for the overlay and diagnostics but
`face_valid` and `eyes_valid` are `False`.

## 3. Coordinates, mirroring, sides, resize

- **Frame.** The tracker receives the full captured frame (no crop, no
  downscale; feeding 640×360 instead of 1280×720 measured no meaningful CPU
  gain). Normalised coordinates therefore map to captured-frame pixels as
  `x_px = x · width`, `y_px = y · height` (`TrackingResult.landmark_pixels`).
  The backend resizes internally (face detector input, 256×256 landmark
  crop); that never changes the mapping.
- **Axes.** `x` grows to the right of the unmirrored image, `y` downwards,
  both nominally in `[0, 1]` (points may leave the range when the face
  touches the frame edge). `z` is the backend's model-relative depth on
  roughly the scale of `x`: smaller (more negative) is closer to the camera;
  it is not metric.
- **Mirroring.** The M0/M1 preview shows the unmirrored camera frame and the
  overlay is drawn in the same frame, so no mirroring is applied anywhere.
  If a mirrored preview is introduced later, `TrackingResult.mirrored()`
  returns the same result with `x → 1 − x`, yaw and roll negated,
  `geometry.mirrored = True`, and unchanged side labels.
- **Sides are anatomical** (the subject's own left and right). In the
  unmirrored frame the subject's right eye appears on the image's left
  (smaller `x`). The backend's topology indices for the right eye
  (33, 133, …, iris 468–472) and left eye (362, 263, …, iris 473–477) are
  fixed in `gazefix/tracking/landmarks.py`, verified against the package's
  own connection tables and empirically on the fixture. A horizontally
  mirrored image is seen by the backend as a different (mirrored) person,
  so the "right eye" indices still land on the image's left; the contract
  therefore keeps coordinates in the unmirrored frame and only ever mirrors
  `x`.
- **Eyelid contour order** (both eyes identical): outer corner, lower lid
  outer→inner (7 points), inner corner, upper lid inner→outer (7 points).
  `EyeLandmarks.openness` is the mean vertical lid separation divided by
  the corner-to-corner distance, both in pixels: roughly 0.25–0.4 open,
  near 0 during a blink. It is an eyelid aperture ratio, not an eye
  direction.

## 4. Quality, confidence, validity

The MediaPipe Tasks API applies its detection, presence and tracking
thresholds internally (`tracking_min_detection_confidence`,
`tracking_min_presence_confidence`, `tracking_min_tracking_confidence`,
all 0.5 by default) and reports no per-face score. GazeFix does not invent
one. `TrackingQuality` is an explicitly labelled geometric availability
signal:

```text
in_frame_fraction    share of the 478 landmarks with 0 ≤ x ≤ 1 and 0 ≤ y ≤ 1
face_height_fraction bounding-box height of the 468 mesh points / frame height
size_term            0 at face_height_fraction ≤ 0.10, 1 at ≥ 0.20, linear between
score                min(in_frame_fraction, size_term)         range [0, 1]
provenance           "heuristic: min(in-frame fraction, face-size term)"
backend_thresholds   the (detection, presence, tracking) minima the backend applied
```

`TRACKED` requires all of: `in_frame_fraction ≥ tracking_min_in_frame_fraction`
(0.9: landmarks outside the frame are model extrapolations, so a face cut
by the frame edge is never reported as valid full tracking), `score ≥
tracking_min_quality` (0.5), and both eyes `valid` (every contour and iris
point inside the frame, corner width ≥ `tracking_min_eye_width_px` = 12
px). At 1280×720 the size term is 1 for a face at least 144 px tall and 0
below 72 px. The thresholds are settings, validated in
`AppSettings.validated()`. `TrackingResult.eyes_valid` is the safe
per-consumer check: it is `True` only on a `TRACKED` result.

## 5. Head pose (orientation, never gaze)

`HeadPose` is derived from the backend's facial transformation matrix
(canonical face → camera, right-handed camera frame: `x` right, `y` up, `z`
toward the viewer; the face sits at negative `z`). Note the two frames: the
landmark frame has `y` down and a model-relative `z` that decreases toward
the camera; the pose frame has `y` up and `z` toward the viewer.
`rotation[:, 2]` is the direction the face points and `rotation[:, 1]` the
direction of the top of the head. Euler decomposition `R = Rz(roll) · Ry(yaw)
· Rx(pitch)`, degrees:

| Angle | Positive means | Verified by |
| --- | --- | --- |
| `yaw_deg` | head turned toward the subject's LEFT (nose toward the image's right in the unmirrored frame) | mirror test (sign flips) |
| `pitch_deg` | head tilted DOWN (forehead toward the camera) | landmark depth ordering (forehead closer than chin ⇔ pitch > 0); a physical nod has not been observed yet |
| `roll_deg` | head rotated counter-clockwise in the unmirrored image (toward the subject's right shoulder) | +10° image rotation raises roll by ≈ 10° |

`translation` is the face position in the backend's canonical-face-model
units (nominally centimetres) and is uncalibrated: no camera intrinsics are
known, so use it for relative motion only. The overlay draws the three
rotation columns as an orthographic sketch at the nose tip (`dx = L·R[0,k]`,
`dy = −L·R[1,k]`, image rows grow downwards) labelled "head pose (not
gaze)".

## 6. Timing boundaries

| Metric | Thread | Boundary |
| --- | --- | --- |
| `timing.inference_ms` | tracker | BGR→RGB conversion + backend call for that frame; `None` on results built without inference (`INITIALIZING`, `UNAVAILABLE`, `TIMEOUT`) |
| `timing.total_ms` | tracker | from the processor handing the frame over until the result was published (includes queueing behind an in-flight inference); `None` as above |
| `timing.waited_ms` | processor | how long the processor actually waited for this frame's result (≤ `tracking_wait_ms`) |
| `processing_ms` (metrics) | processor | whole `process()` call: the wait plus overlay rendering |
| `pipeline_latency_ms` (metrics) | processor | capture timestamp → processed frame published; excludes camera driver latency and preview presentation |

## 7. Threads and ownership

```text
Qt main thread          widgets, timers, overlay toggle (an atomic flag on the
                        processor), reads ProcessedFrame.tracking for labels
capture thread (M0)     unchanged
processor thread (M0)   TrackingProcessor.process(): submit → bounded wait →
                        publish; overlay rendering on a copy
tracker thread (M1)     "gazefix-tracker": the only thread that creates, calls,
                        rebuilds and closes the FaceTracker; primary-face
                        memory and stabiliser live here
(backend internal)      one MediaPipe dispatcher thread per landmarker instance;
                        stopped by close()
```

- Frames are handed to the tracker thread through a **latest-value slot**:
  an unprocessed frame is replaced (counted as `tracking_replaced`), never
  queued, so the tracker sees at most one waiting frame and memory is
  constant.
- The processor waits for the frame's **own** result for at most
  `tracking_wait_ms` (100 ms, about three frame periods at 30 FPS and the
  PRD's end-to-end latency target). A result that arrives later is never
  attached to a newer frame; it is simply not picked up.
- The capture array is read-only and shared; the tracker converts it to a
  fresh RGB array for the backend; the overlay draws on a copy; with the
  overlay off the input array object itself reaches the preview.
- Initialisation (import ≈ 0.5 s, model load ≈ 0.1–3 s) runs on the tracker
  thread, started when the processing worker starts, so it overlaps camera
  discovery; frames pass through as `INITIALIZING` until it completes.
- A **camera generation change** (selection, Refresh) makes the tracker
  thread reset every piece of temporal state before the first frame of the
  new camera: the backend's own face-tracking state (`FaceTracker.reset`,
  which the MediaPipe adapter implements by running one synthetic black
  64×64 frame so the next real frame goes through the face detector first),
  the primary-face memory and the stabiliser. The backend instance is kept:
  a rebuild would cost a model load and, with this backend, a network
  attempt inside `close()` (section 14). The runtime additionally rejects
  frames of a superseded generation, and any result the tracker publishes
  for the old generation is dropped by the processor's `belongs_to` check.
  The same reset runs when consecutive frames are more than
  `tracking_reset_gap_s` (1 s) apart (camera reopen after a failure, a
  stall), because the backend would otherwise continue from a stale face
  region.

## 8. Overload and stalls

This is a stated trade-off, not an accident: results are aligned to the
frame they describe, so while an inference takes less than
`tracking_wait_ms` the display rate follows the tracker (an inference of
50 ms gives 20 FPS with 50 ms of added latency) and every skipped capture
is a replaced frame in the M0 latest-value buffers — latency never grows.
Inference on the target class of CPU measures around 15 ms, well inside
the budget. If an inference exceeds `tracking_wait_ms`, the frame is
published as `TIMEOUT` and, while that same inference is still running,
later frames are published as `TIMEOUT` immediately (no per-frame wait),
so a slow or stalled tracker degrades to the original preview at capture
rate rather than to a crawling one. When a one-off stall ends, the tracker
processes the newest waiting frame and results realign within a frame or
two. The boundary is sharp and worth stating plainly: results are attached
only while an inference finishes inside the budget. A backend that is
*persistently* slower than `tracking_wait_ms` produces `TIMEOUT` on every
frame — each result arrives after the processor has moved on and is never
picked up — so tracking is effectively paused while the tracker keeps
computing discarded results at full CPU; the processor logs
`tracking_budget_exceeded` once after 30 consecutive timeouts and the
`Tracking:` metric shows `timeout`. Raising `tracking_wait_ms` trades
display rate and latency for tracked frames on such a machine.

A timeout cannot cancel the native call: the tracker thread stays inside
it until the backend returns. Nothing else is blocked by that (the
processor and capture threads keep running). A native call that never
returns is not recoverable inside the process: tracking stays `TIMEOUT`,
the preview continues, and the application must be restarted (section 9
covers shutdown with such a thread).

## 9. Failure and recovery (bounded, no storms)

| Condition | Status | Preview | Recovery |
| --- | --- | --- | --- |
| model missing / wrong size / wrong SHA-256, MediaPipe import failure | `UNAVAILABLE` (message names `scripts/fetch_model.py`) | original frames | non-retryable: one attempt per camera generation; a camera change or Refresh re-arms the budget |
| backend creation fails at runtime | `UNAVAILABLE` (message shows the retry schedule) | original frames | exponential backoff from `tracking_init_retry_s` (2 s) to `tracking_init_retry_max_s` (30 s), at most `tracking_init_max_attempts` (5) per generation |
| inference raises / malformed or degenerate landmark arrays / analysis failure | `ERROR` | original frames | all count as one consecutive error; after `tracking_max_consecutive_errors` (3) the tracker is closed and rebuilt through the same bounded path, at most `tracking_max_rebuilds` (3) times per camera generation, after which it stays `UNAVAILABLE` until a camera change; the first error is logged with a traceback, repeats at most every 5 s |
| any other exception on the tracker thread (reset, close, analysis) | `ERROR` for the frame in hand | original frames | logged once with a traceback and handled like an error burst: rebuild through the same bounded path; the thread never exits silently |
| no face, face leaves | `NO_FACE` | original frames | stabiliser and primary-face memory reset after `memory_frames`; re-entry is tracked from a fresh detection |
| face partly outside / too small | `LOW_QUALITY` | original frames (+ dim overlay) | none needed |
| tracker slower than the wait / stalled | `TIMEOUT` | original frames | section 8 |
| camera change | `TRACKED` after one fresh detection | M0 behaviour (preview cleared by the UI) | backend state flushed, temporal state reset, budgets re-armed; stale results rejected by generation |
| stop during init or inference | — | — | bounded join (`tracking_join_timeout_s`, 2 s; validated to fit with `tracking_wait_ms` inside half the runtime's 5 s deadline); a thread still inside a native call is logged (`tracker_shutdown_timeout` by the worker, `tracker_thread_alive_at_close` by the window) and holds no camera. The backend runs its native calls on a non-daemon worker thread that the interpreter joins at exit, so the entry point waits one more `worker_join_timeout_s` and then terminates the process (`forced_exit`) rather than hang |

Logging is per event (`tracker_ready`, `tracker_init_failed`,
`tracker_generation_reset`, `tracker_state_reset`,
`tracker_inference_error`, `tracker_worker_error`,
`tracker_rebuild_exhausted`, `tracker_released`,
`tracker_shutdown_timeout`, `overlay_toggled`, `forced_exit`), never per
frame.

## 10. Primary face

`tracking_max_faces` (2) faces are requested from the backend so that
selection has a second candidate; only the primary is reported.
Deterministic rule (`gazefix/tracking/selection.py`): keep the face nearest
to the previous primary if it moved at most 0.25 normalised units and its
bounding-box area is within a factor of 2 of the remembered face (so a
smaller face behind the user cannot capture the memory while the user is
briefly undetected); otherwise, or when there is no recent primary, take
the largest bounding box, ties broken by distance to the frame centre and
then by backend index. A fall-through is reported as an identity change,
which resets the stabiliser. The memory is forgotten after 15 consecutive face-less results and
on every camera change. Multi-person tracking is not a feature.

## 11. Stabilisation

`tracking_smoothing` (0.5; 0 disables) sets a velocity-adaptive
exponential filter per landmark: the blend weight is `1 − 0.7 · smoothing`
at rest and rises to 1 for a displacement of 2 % of the frame or more, so
jitter is damped while fast motion passes through. The filter uses only the
current frame and the previous output (no queued frames, no added frame
latency) and resets on `NO_FACE`, `ERROR`, identity change, camera change,
and a frame gap longer than `tracking_reset_gap_s`.

## 12. Development overlay

`--dev` shows a "Tracking overlay" checkbox and a detail line; neither
exists in the consumer window. The overlay draws mesh points, the face
oval, eyelid contours (right eye cyan "R", left eye yellow "L"), iris
circles, head-pose axes at the nose tip, and a text panel with status,
quality, timing and the backend description. It is rendered on the
processor thread on a copy of the frame; with the checkbox off the
original array reaches the preview unchanged (`output.frame is frame`).
Widgets are touched only by the Qt thread; the toggle sets a flag read by
the processor thread.

## 13. Backend network activity (disclosure)

The MediaPipe 1.0.1 native library contains an HTTP logging client
(`mediapipe::tasks::core::logging::google_internal::HttpLoggingClient`).
Measured here: every `FaceLandmarker.close()` opens an HTTPS connection to
`play.googleapis.com` (Google's Clearcut logging endpoint) and blocks until
it completes or fails (3 ms with no network route, 15–45 ms when the
connection is refused, 110–380 ms through a working proxy; a black-holed
route was reported to take about 5 s). Creation and inference do not
contact the network. The payload types compiled into the library are usage
statistics — `SolutionSessionStart/End`, `SolutionInvocationCount/Report`,
`SolutionError`, `ClientInfo`, `SystemInfo`, `HostEnvironment`, `Platform`
— with no image type; GazeFix passes only in-memory frames and never a
frame to any logging call, but the upload itself is neither disclosed in the
package metadata nor switchable through the Python API. The Windows build
uses WinINet for it, which follows the system proxy settings and ignores
the `HTTPS_PROXY` environment variables; on Linux (libcurl) a sinkhole
proxy stops it. GazeFix does not work around it silently: the fact is
recorded here, in the README and in ADR-0001; `close()` is called at exit
and on every error-driven rebuild (at most `tracking_max_rebuilds` = 3 per
camera generation; camera changes reset the backend state instead of
rebuilding it); and the decision whether this is acceptable, must be
blocked at the firewall, or requires a different backend/version
(0.10.21, the last pybind-based release, contains no logging client) is
escalated to the Product Manager in the M1 report.

## 14. Verification commands

```powershell
.venv\Scripts\python scripts\fetch_model.py                      # one-time model setup
.venv\Scripts\python -m gazefix --dev                            # GUI with the developer row
.venv\Scripts\python scripts\tracking_test.py --image tests\assets\astronaut_face.png
.venv\Scripts\python scripts\tracking_test.py --camera 0 --duration 10
.venv\Scripts\python -m pytest                                   # deterministic suite (no model needed)
$env:GAZEFIX_REAL_MODEL_TESTS=1; .venv\Scripts\python -m pytest tests\test_real_model_tracking.py
```
