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
`docs/decisions/ADR-0001-face-tracker-mediapipe.md`). It runs entirely
on the local CPU (XNNPACK); no GPU, NPU, or network is used. The backend is
hidden behind `gazefix.tracking.tracker.FaceTracker`; everything else in
the package works on plain arrays and is exercised by fakes.

## 2. Result contract (`TrackingResult`)

Every processed frame published by the pipeline (`ProcessedFrame.tracking`)
carries exactly one `TrackingResult` that names that frame:

| Field | Meaning |
| --- | --- |
| `sequence` | capture-buffer sequence of the frame (unique, increasing, never reset by a camera change) |
| `captured_at_ns` | the frame's capture timestamp |
| `camera_request_id` | the camera generation the frame belongs to |
| `status` | one of the statuses below |
| `geometry` | width/height of the frame the coordinates refer to; `mirrored` is always `False` for tracker output |
| `timing` | `inference_ms`, `total_ms`, `waited_ms` (section 6) |
| `message` | human-readable reason for any non-`TRACKED` status |
| `faces_detected` | how many faces the backend reported (only the primary one is described) |
| `landmarks` | `(478, 3)` read-only float32, normalised (section 3); present for `TRACKED` and `LOW_QUALITY` only |
| `right_eye`, `left_eye` | `EyeLandmarks`: 16-point eyelid contour, iris (5 points) or `None`, `openness`, `width_px`, `valid` |
| `iris_available` | `True` when the tracker delivered iris landmarks (the 478-point topology) |
| `pose` | `HeadPose` or `None` |
| `quality` | `TrackingQuality` (section 4) |
| `stabilized` | whether the landmark stabiliser was active for this result |

A consumer must check `belongs_to(sequence, camera_request_id)` against the
frame it displays; the window does, and the runtime's
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
| `DISABLED` | no | `False` | reserved for a processor with tracking switched off (the application uses the passthrough processor instead) |

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

`TRACKED` requires `score ≥ tracking_min_quality` (0.5) and both eyes
`valid` (every contour and iris point inside the frame, corner width ≥
`tracking_min_eye_width_px` = 12 px). At 1280×720 the size term is 1 for a
face at least 144 px tall and 0 below 72 px. The thresholds are settings,
validated in `AppSettings.validated()`.

## 5. Head pose (orientation, never gaze)

`HeadPose` is derived from the backend's facial transformation matrix
(canonical face → camera, right-handed camera frame: `x` right, `y` up, `z`
toward the viewer; the face sits at negative `z`). Euler decomposition
`R = Rz(roll) · Ry(yaw) · Rx(pitch)`, degrees:

| Angle | Positive means | Verified by |
| --- | --- | --- |
| `yaw_deg` | head turned toward the subject's LEFT (nose toward the image's right in the unmirrored frame) | mirror test (sign flips) |
| `pitch_deg` | head tilted DOWN (forehead toward the camera) | landmark depth ordering (forehead closer than chin ⇔ pitch > 0); a physical nod has not been observed yet |
| `roll_deg` | head rotated counter-clockwise in the unmirrored image (toward the subject's right shoulder) | +10° image rotation raises roll by ≈ 10° |

`translation_cm` is the backend's canonical-face metric estimate and is
approximate. The overlay labels the axes "head pose (not gaze)".

## 6. Timing boundaries

| Metric | Thread | Boundary |
| --- | --- | --- |
| `timing.inference_ms` | tracker | BGR→RGB conversion + backend call for that frame |
| `timing.total_ms` | tracker | from the processor handing the frame over until the result was published (includes queueing behind an in-flight inference) |
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
  `tracking_wait_ms` (200 ms). A result that arrives later is never
  attached to a newer frame; it is simply not picked up.
- The capture array is read-only and shared; the tracker converts it to a
  fresh RGB array for the backend; the overlay draws on a copy; with the
  overlay off the input array object itself reaches the preview.
- Initialisation (import ≈ 0.5 s, model load ≈ 0.1–3 s) runs on the tracker
  thread, started when the processing worker starts, so it overlaps camera
  discovery; frames pass through as `INITIALIZING` until it completes.
- A **camera generation change** (selection, Refresh) makes the tracker
  thread close the tracker, reset the primary-face memory and stabiliser,
  and build a fresh tracker, so no state from one camera can attach to
  another; the runtime additionally rejects frames of a superseded
  generation. The first generation ever seen adopts the tracker built at
  start-up without a rebuild.

## 8. Overload and stalls

If tracking is slower than capture, the preview runs at the tracker's rate
with results aligned to their frames (each `process()` waits at most
`tracking_wait_ms`), and every skipped capture is a replaced frame in the
M0 latest-value buffers — latency does not grow. If an inference exceeds
`tracking_wait_ms`, the frame is published as `TIMEOUT` and, while that
same inference is still running, later frames are published as `TIMEOUT`
immediately (no per-frame wait), so a stalled tracker degrades to the
original preview at capture rate. When the stalled call returns, the
tracker processes the newest waiting frame and results realign within a
frame or two.

A timeout cannot cancel the native call: the tracker thread stays inside
it until the backend returns. Nothing else is blocked by that (the
processor and capture threads keep running), and at shutdown the thread is
abandoned as a daemon after a bounded join (below).

## 9. Failure and recovery (bounded, no storms)

| Condition | Status | Preview | Recovery |
| --- | --- | --- | --- |
| model missing / wrong size / wrong SHA-256, MediaPipe import failure | `UNAVAILABLE` (message names `scripts/fetch_model.py`) | original frames | non-retryable: one attempt per camera generation; a camera change or Refresh re-arms the budget |
| backend creation fails at runtime | `UNAVAILABLE` (message shows the retry schedule) | original frames | exponential backoff from `tracking_init_retry_s` (2 s) to `tracking_init_retry_max_s` (30 s), at most `tracking_init_max_attempts` (5) per generation |
| inference raises / malformed landmarks | `ERROR` | original frames | after `tracking_max_consecutive_errors` (3) the tracker is closed and rebuilt through the same bounded path; the first error is logged with a traceback, repeats at most every 5 s |
| no face, face leaves | `NO_FACE` | original frames | stabiliser and primary-face memory reset after `memory_frames`; re-entry is tracked from a fresh detection |
| face partly outside / too small | `LOW_QUALITY` | original frames (+ dim overlay) | none needed |
| tracker slower than the wait / stalled | `TIMEOUT` | original frames | section 8 |
| camera change | `INITIALIZING` → `TRACKED` | M0 behaviour (preview cleared by the UI) | tracker rebuilt; stale results rejected by generation |
| stop during init or inference | — | — | bounded join (`tracking_join_timeout_s`, 1 s, inside the runtime's deadline); a thread still inside a native call is logged (`tracker_shutdown_timeout`) and ends with the process; it releases the tracker itself when the call returns; it holds no camera |

Logging is per event (`tracker_ready`, `tracker_init_failed`,
`tracker_generation_reset`, `tracker_inference_error`, `tracker_released`,
`tracker_shutdown_timeout`, `overlay_toggled`), never per frame.

## 10. Primary face

`tracking_max_faces` (2) faces are requested from the backend so that
selection has a second candidate; only the primary is reported.
Deterministic rule (`gazefix/tracking/selection.py`): keep the face nearest
to the previous primary if it moved at most 0.25 normalised units;
otherwise, or when there is no recent primary, take the largest bounding
box, ties broken by distance to the frame centre and then by backend
index. The memory is forgotten after 15 consecutive face-less results and
on every camera change. Multi-person tracking is not a feature.

## 11. Stabilisation

`tracking_smoothing` (0.5; 0 disables) sets a velocity-adaptive
exponential filter per landmark: the blend weight is `1 − 0.7 · smoothing`
at rest and rises to 1 for a displacement of 2 % of the frame or more, so
jitter is damped while fast motion passes through. The filter uses only the
current frame and the previous output (no queued frames, no added frame
latency) and resets on `NO_FACE`, `ERROR`, identity change, and camera
change.

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

## 13. Verification commands

```powershell
.venv\Scripts\python scripts\fetch_model.py                      # one-time model setup
.venv\Scripts\python -m gazefix --dev                            # GUI with the developer row
.venv\Scripts\python scripts\tracking_test.py --image tests\assets\astronaut_face.png
.venv\Scripts\python scripts\tracking_test.py --camera 0 --duration 10
.venv\Scripts\python -m pytest                                   # deterministic suite (no model needed)
$env:GAZEFIX_REAL_MODEL_TESTS=1; .venv\Scripts\python -m pytest tests\test_real_model_tracking.py
```
