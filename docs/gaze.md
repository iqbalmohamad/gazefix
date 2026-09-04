# Milestone 2 — Gaze Estimation

What GazeFix estimates, what the numbers mean, and what they are worth.

This is the reference for signs, units and limitations. The code that
implements it is `gazefix/gaze/` (`models.py`, `estimator.py`,
`smoothing.py`); the contract it consumes is M1's, documented in
[`tracking.md`](tracking.md).

> **This is not eye tracking.** M2 has no calibration, no camera intrinsics
> and no per-user anatomy. It reports an *approximate* direction derived from
> projected geometry, good enough to say roughly how far the eyes are looking
> away from the camera. Treat the degrees as an indication, not a
> measurement, and present them as whole degrees.

## 1. Three different things

The pipeline now carries three signals that are easy to confuse. They are
kept separate in the code, the overlay and this document.

| Signal | Where it comes from | What it means |
| --- | --- | --- |
| **Head pose** (`TrackingResult.pose`) | M1, from the backend's face transform | Which way the head is ORIENTED. Says nothing about the eyes. |
| **Eye/iris geometry** (`TrackingResult.left_eye` / `right_eye`) | M1, landmark positions | Where the eyelids and iris ARE, in the image. Raw measurement, not a direction. |
| **Estimated gaze** (`TrackingResult.gaze`) | M2, this document | Where the eyes are LOOKING, relative to the camera. |

`GazeResult` splits its own answer in two, and the distinction matters:

- `eye_yaw_deg` / `eye_pitch_deg` — the **eye-in-head** rotation: the eye's
  rotation inside its socket. Derived from iris geometry alone. It is
  **exactly zero when the head moves and the eyes stay centred**, at any head
  angle (verified in `tests/test_gaze_estimator.py`).
- `yaw_deg` / `pitch_deg` — the **camera-relative gaze**: the eye-in-head
  rotation composed with the head's orientation. This is the M2 headline
  output.

When the eyes are centred in their sockets, camera-relative gaze equals the
direction the face points. That is not head pose leaking into gaze; it is the
correct answer, because a person with centred eyes is looking where their
face points. What makes gaze a distinct signal is that `eye_yaw_deg` moves
with the iris while the head is still, and does not move at all when only the
head moves.

## 2. Frame and sign conventions

`GazeResult.direction` is a unit vector in the **same right-handed camera
frame `HeadPose` uses**: `x` toward the image's right, `y` up, `z` toward the
viewer. It points FROM the eyes TOWARD what is being looked at, so looking
straight into the camera is `(0, 0, 1)`.

```text
yaw_deg   = degrees(atan2(x, z))
pitch_deg = degrees(asin(y))
```

| Angle | Positive means | Zero means | Verified by |
| --- | --- | --- | --- |
| `yaw_deg` | the eyes look toward the subject's OWN LEFT (toward the image's right in an unmirrored frame) | horizontally on the camera | synthetic scenes with a known iris offset; mirror test flips the sign |
| `pitch_deg` | the eyes look UP | vertically on the camera | synthetic scenes with a known iris offset |
| `eye_yaw_deg`, `eye_pitch_deg` | same senses, but relative to the head instead of the camera | the iris is centred in the palpebral fissure | head-only motion keeps both at 0 within 0.2 deg |

### The pitch trap

**`HeadPose.pitch_deg > 0` means the head is tilted DOWN. `GazeResult.pitch_deg > 0`
means the eyes look UP.** The two use opposite senses.

They are not a mistake or an inconsistency to be "fixed": head-pose pitch
comes from an Euler decomposition of a rotation matrix, while gaze pitch is
the elevation of a direction vector, which is the only natural definition for
a direction. `tests/test_gaze_estimator.py::test_gaze_pitch_and_head_pose_pitch_use_opposite_senses`
asserts the difference on purpose, so nobody silently aligns them.

Because of this, the overlay and the developer UI line always print the hint
`+ = subject's left / up` next to the gaze numbers.

Yaw shares its sense with `HeadPose.yaw_deg`: positive is the subject's left
in both.

### Mirroring

`GazeResult.mirrored()` follows the same rule as `HeadPose.mirrored()`: the
direction's `x` component and both yaw angles flip sign, pitch is unchanged,
and eye sides stay anatomical. `TrackingResult.mirrored()` mirrors the gaze
with everything else, so a mirrored preview stays self-consistent.

### Unavailable

`yaw_deg` and `pitch_deg` are `None` when the status is `UNAVAILABLE`. This is
deliberate: `0.0` would read as "looking straight at the camera", which is the
single most dangerous thing a missing estimate could pretend to be.

## 3. The model

Each eye is treated as a sphere of radius `R` behind a palpebral fissure of
half-width `W`. As the eye rotates, the iris centre moves across the front of
that sphere. Measure the iris-centre displacement from the corner midpoint as
a fraction of the eye's half-width and you get, directly, the horizontal and
vertical components of the eye's gaze direction in the head frame:

```text
u = (iris_centre - corner_midpoint) . ex / half_width      ex = the eye's own axis, toward the subject's left
v = (iris_centre - corner_midpoint) . ey / half_width      ey = perpendicular to ex, pointing up

g_head_x = k * u                                   k = W / R  (GazeSettings.eye_model_ratio, default 1.25)
g_head_y = k * v * cos(head_yaw) / cos(head_pitch)
g_head_z = sqrt(1 - g_head_x^2 - g_head_y^2)

g_camera = head_rotation @ g_head                  (or g_head, if head pose is unavailable)
```

`k = 1.25` comes from an adult palpebral fissure of about 30 mm (half-width
15 mm) and an eyeball radius of about 12 mm.

### Why the axes are measured on the eye itself

`ex` runs corner to corner, so it rotates with the head. Two useful
consequences fall out:

- **Head roll needs no correction at all.** The measured axis rolls with the
  face, so `u` and `v` are already in the eye's frame. Measured residual error
  from roll: 0.000 degrees at +/-30 degrees of roll.
- **Head yaw needs no correction for `u`.** The projected eye width and the
  projected horizontal displacement both shrink by `cos(head_yaw)`, and the
  factor cancels in the ratio. The horizontal signal — the primary and most
  reliable one — therefore uses **no head-pose information whatsoever**.

### Why `v` is the only place head pose enters

`v` is normalised by the *horizontal* half-width, so its two foreshortening
factors do not cancel: head pitch foreshortens the vertical displacement
(divide by `cos(head_pitch)`), and head yaw shrinks the normaliser (multiply
by `cos(head_yaw)`). Both cosines are clamped to `[min_cos, 1]` (default
0.5), so the correction is bounded to a factor between 0.5 and 2 and a large
or noisy head angle cannot amplify the vertical signal without limit.

That bounded scale correction is the *entire* role head pose plays in
producing the eye-in-head direction. It cannot manufacture a signal: with a
centred iris the displacement is zero, and zero times any correction is still
zero.

### Saturation

If `hypot(g_head_x, g_head_y)` exceeds `offset_limit` (0.95) the measurement
is past the eyeball model's range — a real eye cannot rotate that far, so the
landmarks are wrong. The direction is scaled back onto the limit rather than
given an invented depth, and `offset_term` drops to `offset_floor_factor`.

## 4. Confidence

`GazeConfidence.score` is the product of five terms, each in `[0, 1]` and each
exposed on the result so a reader can see which one is responsible:

```text
score = tracking_quality x openness_term x agreement_term x pose_term x offset_term
```

| Term | Computed from | Falls when |
| --- | --- | --- |
| `tracking_quality` | M1 `TrackingQuality.score` | the face is small, or partly outside the frame |
| `openness_term` | the less open of the eyes used; ramp 0 at 0.10 to 1 at 0.20 | the eyelids cover the iris (a blink drives it to 0) |
| `agreement_term` | how far the two eyes' independent estimates differ, beyond a deadband | one eye is mistracked; fixed 0.6 when only one eye is usable |
| `pose_term` | head rotation; 1 up to 25 deg, falling to 0.25 at 60 deg | the head turns away and the projected model degrades; fixed 0.7 when head pose is unavailable |
| `offset_term` | the measured iris offset against the eyeball model | the offset approaches or exceeds what an eye can produce |

**This is a heuristic, not a probability.** It is labelled as such in
`CONFIDENCE_PROVENANCE`, exactly as M1's `TrackingQuality` is. No gaze model
in this milestone reports a probability of its own, and none is invented.
Every term is computed from a quantity the pipeline actually measures.

A score of exactly 0 is reported as `UNAVAILABLE`, not as a zero-confidence
estimate: publishing angles beside a zero would invite a reader to use them.
The message names the term that reached zero.

Below `gaze_min_confidence` (default 0.35) the status is `LOW_CONFIDENCE`: the
angles are carried so a developer can see them, and `GazeResult.available` is
`False` so a consumer cannot treat them as trusted.

### The inter-eye agreement deadband, and why it is 20 degrees

Measured on real MediaPipe output, the two eyes disagree by **12.6 +/- 1.3
degrees** (9 detections of the same face at different scales, offsets and
in-plane rotations; range 10.1 to 14.2). This is structural, not noise:

The reference point is the midpoint of the two eye corners, which sits
**nasal** to the eyeball centre, because the nasal canthus extends further
medially than the globe does. Both irises therefore read as displaced
**temporally**. The bias is mirror-symmetric between the eyes, so it cancels
when the two eyes are averaged — which is why the estimator averages them —
but it still appears as raw disagreement.

The deadband (`agreement_deadband_deg`, 20 degrees) is set above the measured
value with headroom, so ordinary anatomy costs no confidence; past it the term
falls to 0 over `agreement_span_deg` (25 degrees), which still catches a
genuinely mistracked eye. Before this was measured, a 15-degree span rejected
5 of 14 detections of a perfectly good face outright.

`tests/test_real_model_tracking.py::test_real_eyes_disagree_structurally_and_averaging_absorbs_it`
pins the measurement, so the deadband stays justified.

## 5. Accuracy and limitations

Measured on synthetic scenes built from an independent 3-D eyeball and
projected without using the estimator's formula
(`tests/gaze_fakes.py`). Errors are in degrees, on the recovered eye-in-head
angle.

**Horizontal (eye yaw error vs. head yaw):**

| true eye yaw | head 0 | head 15 | head 30 | head 45 |
| --- | --- | --- | --- | --- |
| 10 deg | -0.00 | -0.24 | -0.51 | -0.88 |
| 20 deg | -0.00 | -0.98 | -2.11 | -3.64 |
| 30 deg | -0.00 | -2.35 | -5.00 | -8.53 |

**Vertical (eye pitch error vs. head pitch):**

| true eye pitch | head 0 | head 15 | head 30 | head 45 |
| --- | --- | --- | --- | --- |
| 10 deg | +0.00 | +0.24 | +0.51 | +0.89 |
| 20 deg | +0.00 | +0.99 | +2.14 | +3.72 |

The model is exact on a frontal face and degrades as the head turns, because
the iris sits in front of the corner plane and that depth offset projects into
the image once the head rotates. `pose_term` exists to report this
degradation rather than hide it.

Other error sources, in rough order of size:

- **Uncalibrated per-user anatomy (the largest).** `eye_model_ratio` is a
  population average. Palpebral fissure width varies roughly 26–33 mm across
  adults, so `k` plausibly spans about 1.08–1.38 — worth about **+/-3 degrees
  at a true 20 degrees** (measured: k=1.05 reports 16.7, k=1.45 reports 23.4).
  This is the error a calibration milestone would remove; it is out of scope
  for M2.
- **Angle kappa.** The visual axis differs from the optical axis by roughly
  4–6 degrees, and varies per person and per eye. Nothing here corrects for
  it, so the reported direction is the eye's optical axis, not where the
  person perceives themselves to be looking.
- **Corner-midpoint reference.** The systematic temporal bias described in
  section 4. Averaging the eyes cancels the mirror-symmetric part; any common
  part remains.
- **Eyelid occlusion when looking down.** The upper lid follows the eye, so
  the visible iris is clipped and its estimated centre shifts. Downward gaze
  is less reliable than upward gaze, and `openness_term` only partly reflects
  this.
- **Perspective.** The estimator assumes an orthographic projection. Measured
  against a weak-perspective projection at 50 cm the error is under 0.11
  degrees at 30 degrees of eye rotation — negligible at normal webcam
  distances, growing if the face is very close to the lens.
- **Backend iris quality.** Everything rests on MediaPipe's iris landmarks;
  glasses, reflections, strong side lighting and low resolution degrade them.
  Not characterised here — the Product Owner's smoke test is where this shows
  up.

**Do not** quote these numbers as an accuracy specification for a real user.
They are the model's error on known geometry; the per-user terms above are not
included, and no ground-truth gaze data exists for this project.

## 6. Unavailable and low-confidence behaviour

A failure in gaze estimation must never interrupt video (PRD section 13). The
estimator never raises: `GeometricGazeEstimator.estimate` wraps its own work
and turns any exception into an `UNAVAILABLE` result carrying the message.

| Situation | Result |
| --- | --- |
| face not `TRACKED` (no face, low quality, error, timeout, initialising) | `UNAVAILABLE`, message names the tracking status |
| tracker delivered a 468-point mesh (no iris refinement) | `UNAVAILABLE`, "no iris landmarks" |
| both eyes degenerate (collapsed contour, non-finite geometry) | `UNAVAILABLE`, "no eye had usable iris geometry" |
| eyelids too closed to locate the iris (blink) | `UNAVAILABLE`, names the eyelid term |
| one eye unusable | estimate from the other, `eyes_used = 1`, agreement term fixed at 0.6 |
| head pose unavailable | estimate from eye-in-head angles alone, `head_pose_applied = False`, `pose_term` 0.7 |
| confidence below `gaze_min_confidence` | `LOW_CONFIDENCE`: angles carried, `available` is `False` |
| gaze disabled in settings | `UNAVAILABLE`, "gaze estimation is disabled"; no gaze code runs |

Every result the pipeline publishes carries a `gaze` field — `untracked()`
attaches an explicit `UNAVAILABLE` gaze — so a consumer never has to
distinguish "no gaze object" from "no gaze estimate".

## 7. Threads, ownership and temporal state

Gaze runs **on the tracker thread**, inside `TrackerWorker._analyse`,
immediately after the tracking result is built. Consequences:

- The estimate inherits the tracking result's frame identity (capture
  sequence, capture timestamp, camera generation), so it can never be paired
  with the wrong frame or a stale camera.
- No new thread, no new queue, and no additional wait on the processor
  thread. The gaze cost is inside `tracking_total_ms`, not added to it.
- The estimator's temporal state has exactly one owner.

`GazeSmoother` damps iris jitter with the same velocity-adaptive blend the
landmark stabiliser uses, applied to the **eye-in-head** direction rather than
the camera-relative gaze — so head motion passes through instantly and only
the eye-in-socket signal is filtered. It never holds a frame back: a frame's
output depends on that frame and the previous output only.

It is reset when any of these happens, alongside every other piece of temporal
state the tracker holds:

- the camera generation changes,
- the primary face identity changes,
- the face is lost,
- more than `tracking_reset_gap_s` passes between frames,
- the tracker errors or is rebuilt,
- gaze goes unavailable for any reason on a frame.

## 8. Settings

In `AppSettings` (see `gazefix/config.py`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `gaze_enabled` | `True` | run the estimator at all |
| `gaze_eye_model_ratio` | `1.25` | `k`: palpebral half-width / eyeball radius |
| `gaze_min_confidence` | `0.35` | `ESTIMATED` vs `LOW_CONFIDENCE` |
| `gaze_smoothing` | `0.5` | 0 disables the temporal filter |

The remaining model constants live in `gazefix.gaze.estimator.GazeSettings`
with the defaults documented above; `GazeSettings.validated()` rejects an
inconsistent set.

## 9. Developer visibility

With `developer_mode` on and the overlay enabled:

- a **magenta arrow** from each iris centre along the estimated gaze
  direction, dimmed when the status is `LOW_CONFIDENCE`. Magenta is used by
  nothing else on the overlay, and the arrow cannot be confused with the
  three-coloured head-pose axes drawn at the nose tip.
- a text block giving the approximate angles, the confidence and each of its
  five factors, the eye-in-head component, how many eyes contributed, whether
  head pose was applied, and the sign hint.

The consumer window's Tracking line appends the gaze status, and the developer
detail line carries the full readout plus `gaze <n> ms`.

Angles are printed as **whole degrees with an "approx, uncalibrated" marker**
everywhere they appear. Decimals would imply a precision this estimate does
not have; `tests/test_gaze_overlay.py` asserts that they never appear.

Diagnostics counters: `gaze_estimation_ms` (smoothed, tracker thread),
`gaze_estimated_frames`, `gaze_low_confidence_frames`,
`gaze_unavailable_frames`.

## 10. Verification commands

Deterministic suite (no camera, no network, no model download):

```powershell
python -m pytest -q
python -m pytest -q tests/test_gaze_models.py tests/test_gaze_estimator.py tests/test_gaze_integration.py tests/test_gaze_overlay.py
```

Real-model tests, including gaze on real iris landmarks (opt-in; needs the
verified model bundle):

```powershell
python scripts/fetch_model.py
$env:GAZEFIX_REAL_MODEL_TESTS = "1"
python -m pytest -q tests/test_real_model_tracking.py
```

Developer run with the gaze overlay:

```powershell
python -m gazefix --dev --overlay
```

The same run with the estimator off, to compare against tracking alone:

```powershell
python -m gazefix --dev --overlay --no-gaze
```

## 11. Product Owner smoke test (Windows, physical webcam)

About 5–10 minutes. Every step has one action and one expected observation.
Record each as VERIFIED / NOT VERIFIED / FAILED — a step you cannot perform is
NOT VERIFIED, never a guess.

Setup, once:

```powershell
cd <repo>
.venv\Scripts\python scripts\fetch_model.py     # only if the model is not installed yet
.venv\Scripts\python -m gazefix --dev --overlay
```

The overlay draws a magenta arrow from each iris. The detail line under the
preview carries the numbers. Sit at a normal working distance with the face
well lit and filling a reasonable part of the frame.

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Look straight at the **camera lens**, head still. | Gaze arrows point roughly at you (short, toward the lens). `yaw` and `pitch` both within about +/-10. `conf` above 0.5. Status `estimated`. |
| 2 | **Keep the head still** and look to your **left** (the image's right), then back. | `yaw` goes clearly **positive** (+15 or more) and returns near 0. The arrows swing while the head-pose axes at the nose stay put. |
| 3 | **Keep the head still** and look to your **right**, then back. | `yaw` goes clearly **negative** and returns near 0. |
| 4 | **Keep the head still** and look **up**, then **down**, then back. | `pitch` goes **positive** looking up and **negative** looking down. Downward gaze may be noisier — that is the documented eyelid-occlusion limit. |
| 5 | Steps 2–4 are the milestone's key check: watch the `eye-in-head` numbers in the detail line. | They move with your eyes. This is the evidence that gaze is not head pose. |
| 6 | Now **turn your head** left and right while keeping your **eyes on the lens**. | `yaw` stays near 0-ish while `eye-in-head yaw` moves the opposite way to the head. The two must not move together identically. |
| 7 | **Turn the head with the eyes centred** (look where the face points). | `eye-in-head` stays near 0 and `yaw` follows the head. This is correct, not a bug: centred eyes look where the face points. |
| 8 | **Blink**, then close your eyes for two seconds. | Gaze reports `unavailable` mentioning the eyelids. **The preview keeps running smoothly.** |
| 9 | **Cover one eye** with a hand. | Gaze still reports a direction with `eyes 1` and a lower `conf`. Preview unaffected. |
| 10 | **Leave the frame** entirely, then come back. | Gaze goes `unavailable`, then recovers. No stale arrow is left behind, and the first frame back is not blended with your old eye position. |
| 11 | Look at the printed numbers. | They are **whole degrees** with "approx, uncalibrated" and the hint `+ = subject's left / up`. Nothing claims decimal-degree precision. |
| 12 | Watch **Capture FPS**, **Display FPS**, **Processing** and the `gaze <n> ms` figure for ~30 s of ordinary use. | FPS and processing time are in line with the M1 baseline; `gaze` is well under a millisecond. No visible stutter. |
| 13 | Press **Refresh**, switch camera if a second one exists, then **close the window**. | Camera list refreshes, no stale gaze survives the switch, the window closes cleanly and the camera light goes out. |
| 14 | Optional A/B: rerun with `--dev --overlay --no-gaze`. | Gaze reports `unavailable (disabled)`; tracking and preview are unchanged. |

Record for the report: camera model and backend, resolution, capture and
display FPS, processing ms, `gaze` ms, whether you wear glasses, and the
lighting. Anything not measured is `NOT MEASURED`.

Note on step 1: a small non-zero reading with the eyes on the lens is
expected, not a failure. The estimator is uncalibrated and carries a per-user
anatomy error of roughly +/-3 degrees (section 5), plus the angle-kappa offset.
