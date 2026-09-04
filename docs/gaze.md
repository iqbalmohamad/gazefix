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
  rotation inside its socket. The iris drives it; head pose only perturbs it,
  in two bounded ways set out in §3 and measured in §5. On the idealised
  geometry the tests use it is *exactly* zero when the head moves and the
  eyes stay centred, at any head angle; on a real face a residual of a few
  degrees leaks in at large head rotations. It is nowhere near a restatement
  of head pose: an eye sweep moves it by 40°, a 30° head turn by about 5°.
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
with everything else, so a mirrored preview stays self-consistent and the
overlay arrow points the right way.

**Mirroring is a display transform applied AFTER estimation, and the two are
not interchangeable.** `mirrored()` re-expresses the angles in the mirrored
image's frame, so yaw flips. The estimator's eye axis, by contrast, is defined
anatomically (toward the subject's left) and follows the mirrored geometry, so
running the estimator on mirrored landmarks would return the *unflipped* sign
and a different composition with the mirrored head pose. To make that trap
impossible, `GeometricGazeEstimator.estimate` refuses a result whose
`geometry.mirrored` is set and returns `UNAVAILABLE` saying so. The pipeline
never hits this: the worker estimates on the captured frame, and any mirroring
happens downstream of it.

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
15 mm) over a lever arm of about 12 mm.

Be careful about what that lever arm is. It is the distance from the eye's
**centre of rotation to the iris centre as imaged**, not the eyeball radius:
the centre of rotation sits roughly 13.5 mm behind the corneal apex and the
entrance pupil roughly 3 mm behind it, so the true arm is nearer 10.5 mm than
12 mm, which would put `k` nearer 1.4. The default is left at the conservative
end, which under-reports the magnitude of large deflections rather than
over-reporting them. Combined with the 26–33 mm spread of fissure width across
adults, the defensible range for `k` is roughly **1.1 to 1.45**, and §5
measures what that costs. In practice `k` is best understood as an empirical
gain: MediaPipe's iris centre is a learned landmark, not a modelled optical
feature, so no anatomical figure pins it exactly. It is the one constant a
calibration milestone would replace.

### Why the axes are measured on the eye itself

`ex` runs corner to corner, so it rotates with the head. Two useful
consequences fall out:

- **Head roll needs no correction at all.** The measured axis rolls with the
  face, so `u` and `v` are already in the eye's frame. Measured residual error
  from roll: 0.000 degrees at +/-30 degrees of roll.
- **Head yaw needs no correction for `u`.** The projected eye width and the
  projected horizontal displacement both shrink by `cos(head_yaw)`, so the
  factor cancels in the ratio and the horizontal signal — the primary and most
  reliable one — uses no head-pose information in its arithmetic.

  **That cancellation is exact only if the iris centre and the corner midpoint
  are at the same depth**, which they are not on a real face: the canthi sit
  behind the plane a centred iris reaches. The residual leaks head yaw into
  `u` in proportion to `tan(head_yaw)`, and it is measured in §5. It is a
  bounded perturbation, not the signal — but the earlier drafts of this
  document claimed `u` was head-pose-free full stop, and that was too strong.

There is one more approximation in the axes: `ey` is the image-perpendicular
of `ex`, whereas the head's projected up-axis is only perpendicular to its
projected right-axis when head yaw and pitch are not both non-zero. **Combined
yaw and pitch therefore leak vertical eye rotation into the horizontal
reading**, and §5 tabulates how much. It is not negligible: an earlier draft of
this document called it "under a degree", which was wrong.

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

`GazeConfidence.score` is the product of six terms, each in `[0, 1]` and each
exposed on the result so a reader can see which one is responsible:

```text
score = tracking_quality x openness_term x agreement_term x pose_term
        x offset_term x resolution_term
```

| Term | Computed from | Falls when | Thresholds |
| --- | --- | --- | --- |
| `tracking_quality` | M1 `TrackingQuality.score` | the face is small, or partly outside the frame | inherited from M1 |
| `openness_term` | the less open of the eyes used, measured on the eye's own axis; ramp 0 at 0.10 to 1 at 0.20 | the eyelids cover the iris (a blink drives it to 0) | CHOSEN, against M1's observed 0.25–0.4 for an open eye |
| `agreement_term` | how far the two eyes' estimates differ, beyond a deadband | one eye is mistracked; fixed 0.6 when only one eye is usable | deadband MEASURED (below); span and single-eye factor CHOSEN |
| `pose_term` | how far the face's forward axis is off the camera axis (not `max(|yaw|,|pitch|)`, which under-charges a head rotated in both); 1 up to 25 deg, falling to 0.25 at 60 | the head turns away and the projected model degrades | CHOSEN, informed by the §5 error tables |
| `offset_term` | the measured iris offset against the eyeball model | the offset approaches or exceeds what an eye can produce | CHOSEN |
| `resolution_term` | the smaller eye's half-width in pixels; ramp 0.2 at 5 px to 1 at 20 px | the face is far away, so one pixel of iris noise is worth several degrees | CHOSEN |

Only the agreement deadband is set from measurement; `tracking_quality` is
inherited from M1. **Every other threshold in the table is a chosen
engineering default**, not a measured one, and this document says so rather
than dressing them up.

Two things the confidence does *not* cover, stated plainly:

- `agreement_term` compares the two eyes, so it is **blind to any error common
  to both** — which includes the largest ones: the per-user `k`, angle kappa,
  and the head-yaw depth leak of §5. It detects a per-eye tracking failure,
  not an inaccurate estimate.
- There is no term for the accuracy of the zero reference. An uncalibrated
  estimator cannot know where "looking at the camera" is for this person to
  better than a few degrees, and no confidence number will tell you.

**This is a heuristic, not a probability.** It is labelled as such in
`CONFIDENCE_PROVENANCE`, exactly as M1's `TrackingQuality` is. No gaze model
in this milestone reports a probability of its own, and none is invented.
Every term is computed from a quantity the pipeline actually measures.

A negligible score (at or below 1e-6) is reported as `UNAVAILABLE`, not as a
near-zero-confidence estimate: publishing angles beside it would invite a
reader to use them. The threshold is not exactly zero because a ramp crossing
its floor yields values like 7e-08. The message names the term responsible.

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

**Provenance caveat, stated plainly:** those 9 detections are 9 placements of
**one** face — the public-domain fixture in `tests/assets/`. The mechanism
(nasal canthus past the globe) is anatomical and should generalise, and the
deadband is set well above the measured value precisely because one subject is
thin evidence, but the number itself is n=1 and must not be quoted as a
population figure. The Product Owner's smoke test is the first time a second
face sees this code.

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

**The depth leak, and how big it actually is.** The horizontal cancellation
above is exact only when the iris centre and the corner midpoint sit at the
same depth. They do not. MediaPipe's own model-relative landmark `z` measures
the gap on the licensed fixture face: the canthal midpoint sits behind the
iris centre by about 0.2 of the lever arm — a depth ratio of **0.755 (right
eye) and 0.808 (left)**, which is 9.4 mm in the fixture's millimetres. That
measurement is pinned by
`tests/test_real_model_tracking.py::test_real_canthal_depth_matches_the_documented_ratio`,
so the figures below stay honest.

The case that matters for the milestone is a **fixating subject**: someone
keeping their eyes on the lens while turning their head. Their true
camera-relative gaze is 0 at every head angle, so anything the estimator
reports is error — and if gaze were a rescaled head pose, it would track the
head exactly. Reported gaze yaw, in degrees:

| canthus depth | head 10 | head 20 | head 30 | head 40 |
| --- | --- | --- | --- | --- |
| 12 mm (coplanar) | -0.16 | -1.34 | -5.26 | -17.05 |
| 10 mm | +1.55 | +2.34 | +1.24 | -4.37 |
| **9.4 mm (measured)** | ~+2 | ~+3 | ~+3 | ~-1 |
| 8 mm | +3.25 | +5.96 | +7.36 | +5.99 |

At the measured depth the residual stays within a few degrees while the head
moves through 40 — comparable to the per-user terms below and far smaller than
the head rotation it would have to reproduce to be "head pose rescaled".

**Head-only motion with the eyes centred.** Apparent eye-in-head yaw, in
degrees, as the corners move behind the depth a centred iris reaches. 12 mm is
coplanar — the idealisation most tests use — and each row below is shallower:

| canthus depth | head yaw 15 | head yaw 30 | head yaw 45 |
| --- | --- | --- | --- |
| 12 mm (coplanar) | 0.00 | 0.00 | 0.00 |
| 10 mm | +2.56 | +5.52 | +9.59 |
| 8 mm | +5.12 | +11.10 | +19.47 |
| 6 mm | +7.70 | +16.78 | +30.00 |

Head pitch produces the same magnitudes with the opposite sign on
`eye_pitch_deg`. This is why `pose_term` falls with head rotation, and why the
claim in §1 is "the iris moves it far more than the head does" rather than
"the head does not move it".

A parallax correction for this term is possible — subtract the depth residual
using a measured protrusion constant — and it is deliberately **not** in M2.
At the measured depth the leak is a few degrees, which is the same size as the
per-user `k` uncertainty and smaller than angle kappa, so correcting it would
not make the estimate meaningfully better while adding a second uncalibrated
constant that can overshoot (the 12 mm row above shows how easily an assumed
depth errs the other way). It is recorded here as the natural first
improvement for a calibration milestone.

**Cross-talk under combined head rotation.** Spurious eye *yaw*, in degrees,
reported for an eye looking purely UP by 20 degrees (true eye yaw 0), at the
measured canthal depth. Two effects compound here: the `ey` skew above and the
depth leak.

| head yaw | pitch 0 | pitch 10 | pitch 20 | pitch 30 |
| --- | --- | --- | --- | --- |
| 10 | +1.68 | +2.27 | +2.78 | +3.20 |
| 20 | +3.47 | +4.69 | +5.75 | +6.62 |
| 30 | +5.51 | +7.46 | +9.15 | +10.53 |
| 40 | +8.03 | +10.87 | +13.36 | +15.41 |

On the coplanar idealisation the same sweep peaks at +6.18 degrees, so roughly
half of the above is the `ey` skew and half the depth leak. This is why
`pose_term` measures the face's true off-axis angle rather than
`max(|yaw|, |pitch|)`: a head at (20, 20) is 28 degrees off-axis and one at
(25, 25) is 35, and charging them as 20 and 25 would report full confidence on
a five-to-nine-degree error.

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
- **Head-pose range.** `pose_term` now derives the off-axis angle from the
  rotation matrix rather than the Euler angles, so it is not limited to the
  +/-90 degrees `HeadPose.yaw_deg` can express. What actually stops a
  profile view is the eye geometry: at 89 degrees of synthetic head yaw the
  projected eye is too foreshortened for either eye to pass its own validity
  check, and gaze reports `UNAVAILABLE` with "no eye had usable iris
  geometry". Note that M1 may still report `TRACKED` for that frame — the
  gaze gate is per-eye, not the tracking status.
- **The M1 landmark stabiliser is per-point.** `LandmarkStabilizer` gives each
  landmark its own velocity-adaptive gain, so a fast-moving iris and slower
  eye corners can be smoothed by different amounts for a frame or two. Because
  `u` and `v` are a ratio between them, that differential lag shows up as a
  brief phantom offset during rapid eye movement. Set `tracking_smoothing=0`
  to remove it; the gaze smoother then still damps iris jitter downstream, in
  the right units.
- **The zero reference is the camera's OPTICAL AXIS, not the camera.**
  `yaw_deg = 0` means the gaze is parallel to the optical axis, so a user
  sitting well off to one side reads a large yaw while looking straight at the
  lens. With no camera intrinsics there is nothing to correct this with. It is
  the same assumption as the orthographic projection, and it is why the smoke
  test asks the Product Owner to sit roughly in front of the camera.
- **A shut eye is dropped, and the transition is not monotonic.** M1's
  `EyeLandmarks.valid` is in-frame-and-wide-enough and never looks at the
  aperture, so a fully closed eye keeps its corner-to-corner width and stays
  valid. The estimator therefore drops any eye whose own aperture is below
  `openness_floor` rather than averaging it in. One consequence is worth
  knowing before it surprises anyone: as an eye closes, confidence *falls*
  while it is still above the floor and dragging the openness term (0.20 at an
  aperture of 0.12), then *rises* the moment it drops below and the estimate
  falls back to the one good eye (0.60). Two regimes, not a bug — a half-open
  eye is a bad measurement being averaged in, and one clean eye is better than
  that.
- **Eyelid aperture is re-measured for gaze, and M1's is not usable here.**
  M1's `EyeLandmarks.openness` is an image-space vertical lid separation over
  the corner distance, so it shrinks with head roll even though the eye has not
  closed: on the real fixture a 37-degree roll took one eye from 0.234 to
  0.146 and dragged the confidence below the threshold, blaming the eyelids.
  `EyeGaze.openness` is the same ratio on the same scale, measured along the
  eye's own up axis, and is flat to within 0.03 across +/-45 degrees of roll.
  `openness_term` uses that one. Head *pitch* still foreshortens the aperture
  and is not corrected.
- **The eyelid clips the iris in almost every frame.** At M1's observed
  openness of 0.25–0.4 on a ~30 mm fissure the aperture is roughly 8–12 mm
  against an ~11.7 mm iris, so the visible iris is cut top and bottom and its
  estimated centre is pulled by whichever lid cuts more. Nothing models this;
  it is part of why downward gaze is the least reliable direction.
- **No hysteresis on availability.** An eyelid hovering at the `openness_floor`
  makes the status alternate between estimated and unavailable, resetting the
  smoother each time, so the signal is unfiltered exactly where it is noisiest.
  Accepted for M2: the frames concerned are blink boundaries, which are the
  least trustworthy frames anyway.
- **No iris-plausibility check.** Nothing verifies that the iris centre lies
  inside its own eye contour. A badly mistracked iris is caught only when it
  leaves the frame (M1) or exceeds the eyeball model (`offset_term`).
- **Backend iris quality.** Everything rests on MediaPipe's iris landmarks;
  glasses, reflections, contact lenses, heavy makeup, motion blur, exposure and
  strong side lighting all degrade them. **None of this is characterised** —
  the Product Owner's smoke test is the first time any of it is exercised.

### The combined budget

**Do not** quote the tables above as an accuracy specification for a real user.
They are the model's error on known geometry. Adding the per-user terms — `k`
(about +/-3 degrees at a true 20), angle kappa (4–6), the head-pose depth
residual (a few degrees at a large head turn) and iris pixel noise (about 4
degrees per pixel of noise at a 40 px eye width, 8 at 20 px) — **a realistic
per-user error budget is on the order of +/-10 degrees.** No ground-truth gaze
data exists for this project, so even that is an estimate of an estimate.

This is why the readout prints whole degrees with an "approx, uncalibrated"
marker and why `docs` and code alike call the output an indication of how far
the eyes are looking away from the camera, rather than an angle.

### Saturation is a contract property, not a bug

Past the joint offset limit (`hypot(g_x, g_y) > 0.95`, about 72 degrees of
eye-in-head rotation) the direction is clamped and further iris movement
changes nothing. `offset_term` drops to its floor to report it. Real eyes do
not rotate that far in their sockets, so reaching saturation means the
landmarks are wrong, not that the person is looking very far away.

## 6. Unavailable and low-confidence behaviour

A failure in gaze estimation must never interrupt video (PRD section 13), and
must never cost tracking either. Two layers enforce that:

1. `GeometricGazeEstimator.estimate` wraps its own work and turns any
   exception into an `UNAVAILABLE` result carrying the message.
2. **The worker does not rely on that.** `GazeEstimator` is a protocol built
   for substitution, so `TrackerWorker` contains a raising implementation
   itself: a failing `estimate` never reaches the tracker's inference-error
   path (it would otherwise spend the consecutive-error budget and rebuild a
   healthy tracker), and a failing `reset` cannot end the tracker thread. Both
   are caught, logged rate-limited, and reported as an unavailable gaze on a
   frame that keeps its landmarks. After ten consecutive failures the
   estimator is retired until the camera generation changes, so a broken
   implementation cannot be called on every frame forever.

Verified by driving a deliberately raising substitute through the real
pipeline: tracking stays `ready` with every frame `TRACKED` and no tracker
rebuild, in both cases.

| Situation | Result |
| --- | --- |
| the frame carries no landmarks (no face, error, timeout, initialising, unavailable) | `UNAVAILABLE`, message names the tracking status |
| the frame is `LOW_QUALITY` but its eyes are individually usable | estimated, with M1's low quality carried straight into the confidence |
| tracker delivered a 468-point mesh (no iris refinement) | `UNAVAILABLE`, "no iris landmarks" |
| both eyes degenerate (collapsed contour, non-finite geometry) | `UNAVAILABLE`, "no eye had usable iris geometry" |
| eyelids too closed to locate the iris (blink) | `UNAVAILABLE`, names the eyelid term |
| one eye unusable — M1 marks it invalid, or it has no iris | estimate from the other, `eyes_used = 1`, agreement term fixed at 0.6 |
| one eye shut (winking, squinting, covered by a hand) | that eye is **dropped**, not merged; the other carries the estimate at `eyes_used = 1` |
| both eyes shut (a blink) | `UNAVAILABLE`, "both eyelids are too closed to locate the iris" |
| head pose present but non-finite | treated as no head pose at all, not as a zero angle |
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
| 1 | Look straight at the **camera lens**, head still, sitting roughly **in front of** it. | Gaze arrows point roughly at you (short, toward the lens). `yaw` and `pitch` both within about +/-10. `conf` above 0.5. Status `estimated`. Sitting well off to one side legitimately reads a large yaw: zero means "parallel to the camera's optical axis", not "aimed at the camera". |
| 2 | **Keep the head still** and look to your **left** (the image's right), then back. | `yaw` goes clearly **positive** (+15 or more) and returns near 0. The arrows swing while the head-pose axes at the nose stay put. |
| 3 | **Keep the head still** and look to your **right**, then back. | `yaw` goes clearly **negative** and returns near 0. |
| 4 | **Keep the head still** and look **up**, then **down**, then back. | `pitch` goes **positive** looking up and **negative** looking down. Downward gaze may be noisier — that is the documented eyelid-occlusion limit. |
| 5 | Steps 2–4 are the milestone's key check: watch the `eye-in-head` numbers in the detail line. | They move with your eyes. This is the evidence that gaze is not head pose. |
| 6 | Now **turn your head** left and right while keeping your **eyes on the lens**. | `yaw` stays near 0-ish while `eye-in-head yaw` moves the opposite way to the head. The two must not move together identically. |
| 7 | **Turn the head with the eyes centred** (look where the face points). | `eye-in-head` stays near 0 and `yaw` follows the head. This is correct, not a bug: centred eyes look where the face points. |
| 8 | **Blink**, then close your eyes for two seconds. | Gaze reports `unavailable` mentioning the eyelids. **The preview keeps running smoothly.** |
| 9 | **Cover one eye** with a hand. | Gaze keeps reporting a direction, now with `eyes 1` and a clearly lower `conf`. Tracking itself drops to `low_quality` — that is expected, and gaze deliberately keeps going rather than vanishing. Preview unaffected. |
| 10 | **Leave the frame** entirely, then come back. | Gaze goes `unavailable`, then recovers. No stale arrow is left behind, and the first frame back is not blended with your old eye position. |
| 11 | Look at the printed numbers. | They are **whole degrees** with "approx, uncalibrated" and the hint `+ = subject's left / up`. Nothing claims decimal-degree precision. |
| 12 | Watch **Capture FPS**, **Display FPS**, **Processing** and the `gaze <n> ms` figure for ~30 s of ordinary use. | FPS and processing time are in line with the M1 baseline; `gaze` is well under a millisecond. No visible stutter. |
| 13 | Press **Refresh**, switch camera if a second one exists, then **close the window**. | Camera list refreshes, no stale gaze survives the switch, the window closes cleanly and the camera light goes out. |
| 14 | Optional A/B: rerun with `--dev --overlay --no-gaze`. | Gaze reports `unavailable (disabled)`; tracking and preview are unchanged. |

Record for the report: camera model and backend, resolution, capture and
display FPS, processing ms, `gaze` ms, whether you wear glasses, and the
lighting. Anything not measured is `NOT MEASURED`.

Note on step 1: a small non-zero reading with the eyes on the lens is
expected, not a failure. Adding up section 5's terms — per-user `k` (about
+/-3 degrees at a true 20), angle kappa (4-6), the head-pose depth residual (a
few degrees at a large head turn) and pixel noise — **a realistic per-user
error budget is on the order of +/-10 degrees**, not the whole degree the
readout prints. The readout is a magnitude and a direction, not a measurement.
