# Milestone 1 physical verification checklist

This is a preparation checklist for the later live integration. None of these
items is verified by the standalone/offline M1 work. Execute it only after the
hardened M0 runtime owns and shuts down one tracker on the processor thread and
can expose the development overlay and tracking metrics without disrupting frame
publication.

## Test record

Record the date, Windows/Python/MediaPipe versions, CPU, camera make/model and
backend, capture resolution/rate, lighting, model SHA-256, whether glasses were
used, and the commit SHA. Obtain consent before retaining any image or video; the
default evidence should be numeric results and observations rather than frames.

## Functional checks

- [ ] With one frontal, well-lit face, `tracked` is stable and all 478 face
  landmarks are present.
- [ ] The left-eye and right-eye subsets each contain 16 actual provider points
  and visually follow the corresponding eyelid contours.
- [ ] The left and right iris subsets each contain five actual provider points
  and the overlay centers/contours align with both irises.
- [ ] During ordinary yaw, pitch, roll, small translations, and distance changes,
  landmarks remain attached without swaps, obvious jumps, or fabricated points.
- [ ] While the person looks left, right, up, and down, eye/iris landmarks remain
  observable where not occluded. Record continuity only; do not interpret these
  checks as gaze yaw/pitch accuracy.
- [ ] During natural and deliberate blinks, temporary eyelid occlusion does not
  crash tracking and recovery is prompt.
- [ ] When the person leaves the frame, results transition through the configured
  temporary-loss grace window to `no_face` with empty landmarks.
- [ ] When the person re-enters, tracking recovers without restarting the camera,
  runtime, or application; repeated leave/re-enter cycles behave consistently.
- [ ] If two faces are tested, the visible primary selection matches the documented
  largest/central/deterministic policy and does not flicker under a geometric tie.
- [ ] The development overlay matches the source frame dimensions and orientation,
  labels state/confidence correctly, and never appears in production mode.
- [ ] Repeat the frontal, head-movement, directional-look, blink, and recovery
  checks with glasses if a consenting tester and glasses are available. Note glare,
  tint, reflections, and any landmark loss.

## Performance and resilience

- [ ] After a documented warm-up, record at least 300 consecutive real-face
  tracking samples: mean, median, and p95 adapter latency.
- [ ] Record effective tracking rate separately from capture FPS and display FPS.
  State the sampling window and whether overlay rendering is enabled.
- [ ] Confirm tracker error, invalid-frame, low-confidence, temporary-loss, and
  recovery counters match observed events and do not contain image data.
- [ ] Confirm tracking loss or an injected tracker exception does not stop capture,
  latest-frame publication, camera switching, or the responsive UI.
- [ ] Close the application during active tracking and during a loss/recovery
  interval. Confirm tracker resources close once, worker joins complete, the
  camera is released by its owning lifecycle, and no process/thread remains.
- [ ] Reopen the application after shutdown and confirm the camera and tracker can
  initialize normally without a stale device or model handle.

## Pass criteria

Mark physical webcam tracking verified only when every applicable item above has
dated evidence on the integrated commit. Clearly mark unavailable glasses or
multi-face tests as not verified rather than silently passing them. Offline file
throughput and synthetic/mock tests cannot substitute for this checklist.
