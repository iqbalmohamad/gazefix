# Offline gaze correction (M3, SA v1.2)

The A1/A2 implementation is ready for Product Owner visual evaluation.
See `milestones/m3-v12-implementation-report.md` for engineering evidence and
`milestones/m3-po-checklist.md` for the single capture-and-score session.
No M3 PASS or M4 readiness is implied by an individual frame's CORRECTED status.

## Boundary and ownership

`CorrectionEngine.correct(frame, tracking, target, strength)` consumes an
unmirrored BGR uint8 frame, its frozen tracking/gaze metadata, a camera-frame
direction and an already-effective strength. It returns a `CorrectionOutput`
containing a frame and frozen, metadata-only `CorrectionResult`. Source gaze
comes from the existing estimator; the engine does not estimate it.

Frame gates run in the frozen order; right and left eye analytic validation
precedes rasterization and allocation. Strength zero, unavailable gaze and
unsafe geometry return the original object. Closed/negligible eyes permit
the other eye; open-unsafe eyes skip the pair by default. Non-finite
displacement and processing faults fail the whole frame. These distinctions
are metadata, not logs or recovery budgets.

The engine creates one full-frame working copy when correction can proceed,
samples the original iris and a private ROI background, and blends both eyes into that canvas. A
failure after partial rendering discards the entire canvas and returns the
input object. The successful canvas is writable and exclusively caller-owned;
the engine retains no alias. M4 publication/freezing is not implemented here.
`reset()` is a no-op; `close()` latches an idempotent closed state.

## Geometry and rendering

Landmarks use normalized image x-right/y-down. Gaze uses camera x-right,
y-up and z toward the viewer. Positive gaze yaw is toward the subject's
left, and positive pitch is upward. Eye axes follow the contour under roll.

The source and target are interpolated in camera yaw/pitch space. When the
estimator applied usable head pose, the engine transforms the direction
change with `R.T`, then inverts the M2 eye-model ratio and cosine factors.
Without usable applied pose it uses identity rotation and unit cosines.
Displacement is relative to the measured iris center, scaled by eye size,
clamped along its direction, and checked for destination containment. It
does not reposition the iris absolutely from the corner midpoint.

Variant B applies the frozen guarded displacement field through a precise
opening-distance transform on the original pixels. Variant C builds the A2
sclera plate: remove the source iris disc grown by one pixel, inside the
opening only; interpolate nearest visible sclera across image rows. One-sided
rows replicate the available side; rows with no available sample use the
eye-wide median. No sclera anywhere fails the whole frame with
`mask generation failed: no sclera to sample`. Outside the hole is identical
to the source. C remaps this plate and adds a rigid original iris layer. A1 blends the
background with the existing canvas first and then overlays the iris:

```text
base   = alpha * background + (1 - alpha) * canvas
output = iris_alpha * iris_layer + (1 - iris_alpha) * base
```

Both iris occlusion factors are binary: destination opening coverage and
conservative source coverage (all four bilinear taps must be inside the
opening). This prevents source lid skin from entering the eye and preserves
opaque iris pixels even where background alpha is partial. The destination
edge may stair-step by one pixel; this is the accepted A1/Q12 trade-off to
evaluate visually, not a claim of naturalness.

The A2 structural tests reject all non-sclera source remnants outside the
destination iris plus a one-pixel fringe. The only permitted original remnant
is the bounded `(1-alpha)` contribution in the partial-alpha lid ring.
Independent supersampled geometric centroids account for occlusion; actual
raster-specific tolerances and their measured basis are recorded in the
implementation report under the user's implementation/tuning authority.
The old raw-background variant C fails both structural and centroid controls.

The cubic background experiment falls back to linear sampling wherever its
4x4 footprint would cross the opening. The default bilinear guard and iris
source rule are unchanged. Cubic is optional; the gate uses default linear.

## Settings and policy

`GeometricCorrectionSettings` holds engine constants and experiment switches;
defaults match SA section 22. `PolicySettings` is a separate stateless policy:
the deviation multiplier interpolates through `(0,.3), (5,1), (25,1), (35,0)`;
confidence ramps from zero at .35 to one at .60; effective strength is capped
at 1. Policy never enters the engine module. No temporal ramp or continuity
epoch exists in M3.

The harness seeds eye-model ratio and minimum cosine consistently for gaze
and correction. Deliberate per-namespace overrides are reported as mismatches.
The existing gaze confidence remains a six-term heuristic, not a probability
or guarantee of gaze accuracy.

## Local-file CLI

From the repository root, using the existing validated environment:

```powershell
.\.venv-m1-qa-r2\Scripts\python.exe -m gazefix.correction.harness --help
.\.venv-m1-qa-r2\Scripts\python.exe -m gazefix.correction.harness --image tests/assets/astronaut_face.png --canvas 1280x720 --target-pitch 15 --effective-strength .75 --debug --repeat 50 --name fixture-example
```

The console entry point `gazefix-correction-test` and
`scripts/correction_test.py` wrap the same CLI. The new console entry point
becomes available after the project's normal editable install; the commands
above work without reinstalling or adding dependencies.

- Native-size stills and prerecorded videos are read synchronously. There
  is no camera mode, UI or thread. `--max-frames` limits source frames
  decoded (default 300); `--every` chooses every Nth frame. Smoothing is
  video-only and off by default.
- `--strength` uses policy. `--effective-strength` bypasses policy. Target
  yaw/pitch default to the optical axis. This uncalibrated zero is not
  necessarily the physical lens direction for an off-center user.
- Image `--sweep-strength`, `--sweep-target-yaw` and `--sweep-target-pitch`
  accept comma-separated values, generating their Cartesian product and
  a contact sheet. Run clip variants separately; contact sheets are image-only.
- `--variant field|layered` selects B/C. `--set engine.KEY=VALUE`,
  `--set policy.KEY=VALUE`, `--set gaze.KEY=VALUE` are strictly validated
  dataclass overrides. Booleans are `true`/`false`; tuple values are comma
  separated. `--eye-model-ratio` sets both consumers before overrides.
- `--unmirror` flips saved mirrored inputs before tracking. Check readable
  text or another known asymmetry once for a recording session.
- `--debug` produces separate drawings and per-eye geometry details;
  `--debug-layers contour,iris,alpha,roi,warp,text` selects drawing layers.
  Debug data is recomputed and checked against the engine's tiny metadata.
- Output defaults to ignored `experiments/<name>/`. Existing experiment
  directories are refused rather than overwritten. No frames are uploaded.

Images produce original/corrected/side-by-side PNGs with 3x eye crops, optional
debug PNGs, sweep directories/contact sheets, and a report. Clips produce
corrected and side-by-side MP4s plus optional debug video; unavailable writers
fall back to explicit per-stream PNG sequences. `frames.jsonl` records
per-frame metadata. Reports include source hash/dimensions, settings, tracking
quality, full gaze confidence, policy, correction outcomes, timings and
version. Reports contain no pixel arrays or full landmark arrays.
Reports also record the local tested commit, whether tracked files differed,
and the canonical SA pointer. Clip reports retain the final frame's metadata
as a summary; the complete sequence is in `frames.jsonl`.

The maintained batch wrapper runs this same harness, without another pipeline:

```powershell
.\.venv-m1-qa-r2\Scripts\python.exe -m scripts.correction_batch fixture
.\.venv-m1-qa-r2\Scripts\python.exe -m scripts.correction_batch po --inputs experiments/inputs
```

The fixture batch covers all 96 B/C, axis, strength and target combinations.
The PO batch validates all eleven captures before running, then produces eight
sheets and three clip outputs at default C, strength .7 with policy, plus an
HTML index, JSON manifest and blank CSV scores. Both reject existing output
directories. No capture, upload or automatic quality verdict is performed.

Exit codes: 0 means artifacts were written without an engine/tracking error
(expected safe skips are permitted); 1 means an input/backend/rendering/I/O
failure; 2 means invalid arguments. Exit 0 is not a milestone verdict.

## Verification and measurement boundaries

New tests are additive under `tests/test_correction_*`,
`test_geometric_engine.py` and opt-in `test_real_model_correction.py`.
The full repository regression suite runs once before handoff, after focused
tests, per QA policy. Failures are reported without turning them into xfails.

`correction_ms` covers the entire engine call. `compositing_ms` starts when
both eyes' warped layers exist and covers alpha construction and both blends;
it is nested within correction time. Debug timings expose copy/warp/composite
costs. `--repeat` reuses the same analyzed frame and measures correction only.
These offline measurements neither include the live pipeline nor establish
M4 FPS. The licensed astronaut fixture is upscaled and blurry; it is not a
representative webcam-quality sample.

PO imagery belongs only in ignored local experiment directories. The final
quality gate remains the frozen SA's eight-still/three-clip, 45–50 minute
evaluation; no scores or `m3-evaluation.md` gate record are fabricated here.
