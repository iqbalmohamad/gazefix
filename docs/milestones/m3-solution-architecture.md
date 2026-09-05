# Milestone 3 — Solution Architecture: Offline Gaze Correction Prototype

**Status:** **APPROVED / FROZEN — amended (A1)** — approved by the Product
Manager on 2026-09-05, frozen as the canonical M3 Solution Architecture, and
amended twice since, narrowly, under PM approval: **A1** corrects the §8.4
compositing order (§8.7); **A2** stops the variant-C background from
retaining a competing source iris (§8.8). Design only:
no M3 code exists, and this document does not authorize M3 implementation
(the Product Manager issues that assignment separately). Amend only through a
deliberate, PM-authorized revision of this document or a new ADR — never by
silent edits during implementation, the rule ADR-0002 and ADR-0003 already
carry.

| Freeze record | Value |
| --- | --- |
| Reviewed SA content | `28dac348749e956acbeb709e3abb4ff3654451d5` (the HEAD the Product Manager reviewed) |
| Original frozen reference | branch `m3-architecture-v1` @ `a459e6be36122bf10ce707731d5f847007847e96` — unchanged and still immutable; superseded as the implementation baseline by A1 |
| **Canonical frozen reference** | branch **`m3-architecture-v1.2`** — this commit: `m3-architecture-v1` plus Amendments A1 (§8.7) and A2 (§8.8), and nothing else |
| Superseded canonical | `m3-architecture-v1.1` @ `00eed0e893b73dcd490f69af8df852a0609ccbaa` — unchanged and still immutable |
| Amendments | **A1** (2026-09-05, PM-approved): §8.4 compositing order — §8.7. **A2** (2026-09-05, PM-approved): the variant-C background becomes a sclera plate that carries no iris — §8.8. Each record holds its evidence, the before/after, the rationale and the required regression coverage |
| Review record | PR #7 against `architecture-v1`; closed, not merged |
| Written / corrected | 2026-09-05, after an eight-lens adversarial review of the first draft (50 confirmed findings applied) |
| Role | Solution Architect / Principal Engineer |

**Product Manager ratification (2026-09-05).** The approval explicitly
ratifies: the 10–20° gaze-deviation range as the primary M3
operating/evaluation range; effective strength ≈ 0.5–0.8 as the main
visual-quality evaluation range; the `PROCEED / ITERATE / CHANGE APPROACH`
gate framework (§14.3); a qualitative Product Owner visual gate with **no**
fabricated aggregate numeric pass score; the ~45–50 minute PO evaluation
budget (§14.4); the layered eye-region remap (§4.2) as the approved M3
default geometric approach; the default pair-correction behaviour (§5.6) as
**provisional, tunable implementation policy — not an immutable architecture
law**; the gaze-to-deformation mapping (§6) as the approved M3 mapping
**hypothesis, to be validated during implementation and not treated as proof
of physical accuracy**; and that **no new M3 ADR is required** (§21).

**Baseline this design descends from:** `architecture-v1` at
`003180d52d39d30a038333541b1b187824714e87` (frozen, canonical), itself on the
frozen M2 baseline `milestone-2` at `81e06118801c23d2337629fc676d6ad8ac13716a`.
This document is a **delta** on that baseline: it decides only what
`docs/architecture.md` Part II ("M3 — offline correction architecture" and
"Deferred to M3 SA") and ADR-0002 §2 leave to M3. It does not restate or amend
the frozen architecture; where a frozen decision applies it is referenced, not
copied. **No new M3 ADR is required** (§21).

**Reading order for the implementor:** PRD §4, §9 (PR-5), §10, §11, §13, §24
(M3), §25, §28 → `docs/architecture.md` Part II → ADR-0002 → ADR-0003 →
`docs/tracking.md` §2–§4 → `docs/gaze.md` §2–§6 → this document. The
implementor should not need to redesign anything listed in §22.

---

## 0. Decision register

| # | Decision | Stability | Where |
| --- | --- | --- | --- |
| D1 | M3 implements the production `CorrectionEngine` (ADR-0002) plus an offline CLI harness; nothing else | stable (baseline) | §1, §3 |
| D2 | M3 consumes the frozen `TrackingResult`/`GazeResult` contracts unchanged; **no compatible metadata extension is required** | stable | §2 |
| D3 | Engine contract: `correct(frame, tracking, target, strength) -> CorrectionOutput(frame, CorrectionResult)`, never raises, metadata-only result | stable (ADR-0002 made concrete) | §3 |
| D4 | Technique: **layered eye-region remap** — rigid iris translation over a smoothly stretched sclera, occluded by the fixed eyelid opening, blended through an eye-shaped mask; the field-only variant is the built-in simplification for A/B | PM-ratified M3 default (the gate may still return CHANGE APPROACH) | §4 |
| D5 | Gaze→displacement: exact inverse of the frozen M2 eye model, applied as a **relative** iris displacement in each eye's own axis frame; one experimental gain | PM-ratified as the M3 mapping **hypothesis**, to be validated in implementation, not proof of physical accuracy; constants provisional | §6 |
| D6 | Policy: a small pure function in `gazefix/correction/policy.py` (PRD §10 curve × confidence gate), runtime-constants tier; the harness can bypass it | stable (shape), provisional (constants) | §7 |
| D7 | Eyes are corrected as a **pair by default**: an open eye that cannot be corrected safely skips both; a closed/occluded eye lets the other proceed | PM-ratified as provisional, tunable implementation policy — not architecture law (switchable) | §5, §10 |
| D8 | Validate-then-commit: the single working copy is allocated only after every eye passes its checks; no partial frame is ever returned | stable | §10, §11 |
| D9 | Engine keeps no temporal state in M3; `reset()` is a protocol no-op; no continuity-epoch machinery | stable | §20 |
| D10 | No new runtime dependency | stable | §19 |
| D11 | Gate verdict is the Product Owner's qualitative judgment on the PRD §28 dimensions applicable to offline stills/clips, over a fixed, budgeted experiment matrix; `CHANGE APPROACH` is a legitimate outcome | PM-ratified (framework, qualitative gate, operating range, budget); per-dimension thresholds stay judgment aids, never objective pass scores | §14 |

"Provisional" means: expected to be tuned or replaced by M3 experiment
evidence *without* changing the engine contract or the frozen baseline.

---

## 1. Scope and non-goals

### 1.1 M3 implements

1. **`gazefix/correction/`** — the `CorrectionEngine` protocol, its factory
   type, the metadata-only result contract, a **geometric engine**
   (eye-region warp + mask + blend, engine-internal compositing per
   ADR-0002 §4), and the provider-neutral eye-geometry / mask library the
   engine uses. This is the production engine, exercised offline (baseline
   "M3 — offline correction architecture").
2. **A minimal correction policy function** deriving effective strength from
   requested strength, deviation and confidence (PRD §10), stateless.
3. **An offline experimentation harness CLI** (still image; prerecorded short
   video frame-by-frame) that runs the real tracker, analysis and gaze
   estimator synchronously, calls the engine, and writes before/after,
   side-by-side, sweep and debug artifacts plus a JSON report.
4. **Hardware-independent tests** for every contract and safety property in
   §15, plus an opt-in real-model test on the licensed fixture.
5. **`docs/correction.md`** (implementation reference, written with the code,
   the `tracking.md`/`gaze.md` pattern) and the PO evaluation sheet (§14).

### 1.2 Explicit non-goals (M3 must not build these)

| Excluded | Owner |
| --- | --- |
| live webcam correction; wiring the engine into `TrackingProcessor`/`ProcessingWorker`; any staged processor | M4 |
| realtime threading changes; a correction worker; buffer changes; `ProcessedFrame`/`ProcessorOutput` extension | M4 (ADR-0003) |
| the tracking continuity epoch field and epoch-driven resets | M4 |
| correction-parameter ramps, fades, slew limits, hysteresis, any temporal state beyond per-frame safety gating | M4/M5 |
| image/output stabilization | M5 |
| calibration, `CalibrationProfile`, target resolution from a profile, per-user `k` | M6 |
| performance optimization, buffer pooling, the split-worker trigger | M7 |
| virtual camera | M8 |
| neural models, ONNX Runtime, DirectML, model assets | M9 |
| product UI, settings persistence, `AppSettings` correction controls, packaging | M4/M6/M10 |
| cloud inference; CUDA/NVIDIA/NPU assumptions | never |

The harness is developer tooling. It must not grow a GUI, a live camera mode
that mimics M4, or threads. If a harness feature would only make sense with
a live camera, it belongs to M4.

---

## 2. Existing M2 contract assessment

Inspected at `milestone-2` / `architecture-v1` (`gazefix/tracking/models.py`,
`gazefix/gaze/models.py`, `gazefix/tracking/analysis.py`,
`gazefix/tracking/landmarks.py`, `gazefix/gaze/estimator.py`,
`gazefix/tracking/worker.py`, `gazefix/tracking/validate.py`). Everything
below is available today and is provider-neutral; nothing imports MediaPipe
outside `mediapipe_tracker.py`, and `gazefix.tracking.landmarks` is plain
constants (cross-checked against MediaPipe only inside a test).

### 2.1 What the engine consumes

| Field | Type / convention | M3 use |
| --- | --- | --- |
| `TrackingResult.status` | `TrackingStatus`; `has_landmarks` for `TRACKED`/`LOW_QUALITY` | gate: landmarks must exist. The engine does **not** require `TRACKED` (M2 estimates on `LOW_QUALITY` on purpose; per-eye validity decides, see §5) |
| `TrackingResult.geometry` | `FrameGeometry(width, height, mirrored)` | pixel mapping `x_px = x·width`, `y_px = y·height`; **`mirrored` must be `False`** (refused otherwise, like the estimator) |
| `TrackingResult.left_eye` / `right_eye` | `EyeLandmarks`: `contour (16,3)` normalised (order: outer corner, lower lid outer→inner ×7, inner corner, upper lid inner→outer ×7), `iris (5,3)` or `None` (centre then 4 contour points), `openness`, `width_px`, `valid` | eye-opening polygon, iris circle, eye axis, size, per-eye validity |
| `TrackingResult.iris_available` | bool | gate: no iris → nothing to move |
| `TrackingResult.pose` | `HeadPose`; `rotation` (3×3) canonical-face→camera, right-handed camera frame x right, y up, z toward viewer; `yaw_deg`/`pitch_deg` | head-frame conversion (`rotation`) and the M2 foreshortening factors (`|cos(yaw_deg)|`, `|cos(pitch_deg)|`) in §6 |
| `TrackingResult.gaze` | `GazeResult`: `status`, `direction` (unit, camera frame, from eyes toward target; camera = `(0,0,1)`), `yaw_deg`/`pitch_deg`, `eye_yaw_deg`/`eye_pitch_deg`, `confidence.score`, `confidence.head_pose_applied`, `per_eye` (`EyeGaze` per contributing eye: `half_width_px`, `openness`, `offset_u/v`) | source gaze; gate `status is ESTIMATED`; deviation for policy |
| identity: `capture_sequence`, `captured_at_ns`, `camera_request_id` | ints | not read by the engine; the `CorrectionResult` inherits identity by riding beside the `TrackingResult` it answers (baseline contract table) |

Helpers reused from the contracts (no new vision data model):
`gazefix.gaze.models.direction_from_angles`, `angles_from_direction`;
`gazefix.tracking.landmarks` positions (`CONTOUR_*_POSITION(S)`);
`gazefix.tracking.models.readonly`, `in_frame`.

### 2.2 Coordinate conventions the engine must honour

- Landmarks: normalised, unmirrored frame, x right, y **down**. Anatomical
  sides: the subject's right eye is on the image's left.
- Gaze/pose: camera frame, y **up**. Image-space vertical components are
  therefore negated when drawn or applied (the overlay's `dy = -y·L` rule).
- Per-eye axis (from `GeometricGazeEstimator._measure_eye`, re-derived in
  `correction.geometry`, not imported): `ex` runs corner to corner **toward
  the subject's left** for both eyes (`inner − outer` for the right eye,
  `outer − inner` for the left), `ey = (ex[1], −ex[0])` points **up in the
  image**. `half_width_px = |inner − outer| / 2`.
- Sign senses: gaze `yaw > 0` = subject's left = image right; gaze
  `pitch > 0` = up. `HeadPose.pitch_deg > 0` = head DOWN (the documented
  pitch trap). The engine uses `pose.rotation` for the head-frame
  conversion and reads the Euler `yaw_deg`/`pitch_deg` **only inside
  `|cos(·)|`** for the M2 foreshortening factors (§6.3), exactly as the
  estimator's `_foreshortening` does; `|cos|` is even, so the pitch sign
  cannot bite.

### 2.3 Confidence and validity semantics relevant to correction

- `GazeStatus.ESTIMATED` is the only trusted state; `LOW_CONFIDENCE` carries
  angles a consumer must not act on; `UNAVAILABLE` carries `None` angles.
  Policy treats anything but `ESTIMATED` as effective strength 0.
- `EyeLandmarks.valid` is in-frame-and-wide-enough only; it never looks at
  aperture. `EyeLandmarks.openness` is measured along image y and shrinks
  under head roll (`docs/gaze.md` §5). The engine therefore recomputes a
  **roll-invariant aperture** from the contour along `ey` (the M2 formula,
  §5.1) in `correction.geometry`; this is a local helper, not a contract
  change.
- `GazeResult.per_eye` lists only the eyes that contributed; a shut eye is
  dropped (M2 rule). The engine does not rely on `per_eye` to decide
  per-eye correction — it re-derives geometry from `EyeLandmarks`, so a
  substitute estimator without `per_eye` still works.
- `GazeConfidence.score` is a heuristic product; ±10° is the documented
  realistic error budget. §6 is designed so that error acts as a **gain
  error on a relative displacement**, never as an absolute repositioning.
- A usable pose is what the estimator's `_usable_pose` accepts: present,
  with finite Euler angles and a finite rotation. Anything else is "no
  pose" for the engine too (§6.1).

### 2.4 Frame identity offline

The harness synthesises `capture_sequence` (frame index), `captured_at_ns`
(monotonic) and `camera_request_id = 1` when it assembles each
`TrackingResult`, in the shape `tests/tracking_fakes.tracked_result` already
uses. (`validate.py` synthesises only the tracker's `timestamp_ms`; it never
assembles a `TrackingResult`.) `CorrectionResult` carries no identity
fields of its own.

### 2.5 Required extensions

**None.** M3 needs no new field on `TrackingResult`, `EyeLandmarks` or
`GazeResult`. The reserved continuity epoch is M4's. Two observations are
recorded for later, not acted on now: a roll-invariant `openness` on
`EyeLandmarks` would remove a duplicated formula (M4 tidy-up candidate); and
the M3 harness will be the first *offline* site to assemble a full
`TrackingResult` with the worker's status rule (mirroring
`worker.py._analyse`, as `tests/tracking_fakes.tracked_result` does), which
strengthens the case for a later `analysis.build_result(...)` helper
(§12.3, Q10) — not an M3 change to frozen tracking code.

---

## 3. CorrectionEngine contract

Concrete form of ADR-0002 §2, in `gazefix/correction/engine.py` and
`gazefix/correction/models.py`. Everything here is the **stable** surface M4
wires in unchanged.

### 3.1 Protocol

```text
CorrectionEngine (Protocol)
  description: str                       one line, e.g. "geometric layered eye-region remap (k=1.25, gain=1.00)"
  correct(frame, tracking, target, strength) -> CorrectionOutput
  reset() -> None                        drop temporal state (none in M3; no-op)
  close() -> None                        release resources; idempotent (nothing to release in M3)

CorrectionEngineFactory = Callable[[], CorrectionEngine]   invoked on the owning thread
```

**Inputs**

| Parameter | Type | Semantics |
| --- | --- | --- |
| `frame` | `NDArray[uint8]`, shape `(H, W, 3)` BGR | the captured frame; **never written**. It may or may not be flagged read-only (harness frames from `cv2.imread` are writable); immutability is a rule the engine keeps, not a flag it relies on |
| `tracking` | `TrackingResult` | the frame's own result, carrying eyes, pose and the **source gaze** (`tracking.gaze`) |
| `target` | `NDArray[float32]`, shape `(3,)` | **resolved target gaze**: unit direction in the `GazeResult` camera frame. Default supplied by the caller: `(0, 0, 1)`, the optical axis (`docs/gaze.md` §5 off-axis caveat stands; M6 addresses it). Non-unit vectors are normalised; a zero/non-finite vector is `SKIPPED` |
| `strength` | `float` in `[0, 1]` | **effective** strength already resolved by policy (§7). Values outside `[0, 1]` or non-finite are `SKIPPED("invalid strength")`, never clamped silently |

**Output** — `CorrectionOutput` (frozen dataclass mirroring `ProcessorOutput`):

| Field | Semantics |
| --- | --- |
| `frame` | the **input array object itself** when nothing was corrected (`SKIPPED`/`FAILED`/strength 0 → bit-identical, zero-copy), otherwise the engine's own fresh working copy carrying both eyes' corrections. The engine keeps no reference to it after return |
| `result` | `CorrectionResult`, metadata only (§3.2) |

### 3.2 `CorrectionResult` (metadata only, small by design)

```text
CorrectionStatus      CORRECTED | SKIPPED | FAILED
CorrectionResult      status, message (reason; "" when CORRECTED),
                      strength (the effective strength received when valid, else 0.0),
                      correction_ms, compositing_ms | None,
                      eyes: tuple[EyeCorrection, ...]   () when a frame-level gate stopped the call;
                                                        exactly two entries (right, left) once per-eye evaluation ran,
                      debug: CorrectionDebug | None      None unless the engine was built with debug=True
EyeCorrection         side, status (CORRECTED | SKIPPED | FAILED), reason,
                      displacement_px: (dx, dy) image pixels as applied ((0, 0) unless CORRECTED),
                      clamped: bool
CorrectionDebug       development only: per-eye roi (x0, y0, x1, y1) and mask bounds, plus an optional
                      stage_ms mapping (copy, warp per eye, composite) for the harness report
```

Rules:

- `SKIPPED` means the input was not correctable (expected, frequent:
  strength 0, no gaze, eyes closed, unsafe geometry). `FAILED` means the
  engine's own processing broke (a fault in mask/warp/compositing, a
  non-finite displacement, an unexpected exception). The distinction exists
  so that M4's consecutive-error budget can key on engine faults (`FAILED`,
  and a raising engine contained by the caller) and never on expected
  `SKIPPED` outcomes; the exact counting rule is M4's to fix.
- `message` is a short stable vocabulary (the complete list is §10.3) so
  tests, the harness report and M4 metrics can key on it; free text may
  follow a colon.
- `correction_ms` is measured inside `correct()` around the whole body with an
  injectable clock (the estimator pattern). `compositing_ms` is **one**
  boundary, used identically in §8.4 and §16: the time from the moment both
  eyes' warped layers exist to the moment the canvas is blended — blend-alpha
  and iris-alpha construction plus the §8.4 blend; the opening mask, distance
  field, maps and remaps are warp-side. It is nested within `correction_ms`;
  the geometric engine has that boundary and reports it; `None` means not
  measured (ADR-0002 §4).
- `debug` exists because ADR-0002/the baseline allow "optional debug
  metadata (e.g. mask bounds)". It stays typed, tiny, `None` in production,
  and is enabled by `GeometricCorrectionSettings.debug` (§22). Warp fields,
  mask images and contour drawings are **not** on the result: the harness
  recomputes them through the library (§13). Development-only stage timings
  ride on `CorrectionDebug.stage_ms` and nowhere else.
- The per-eye `eyes` tuple is a small metadata-only addition beyond the
  fields ADR-0002 §2 and the baseline contract table enumerate (status,
  applied strength, `correction_ms`, optional `compositing_ms`, optional
  debug metadata). It is kept because the pair rule (§5.6) makes per-eye
  outcomes part of the engine's observable behaviour; it contains no arrays
  and changes nothing in ADR-0002 (flagged in §21).
- No `requested_strength` on the result: the engine never sees it; the
  policy's `PolicyDecision` (§7) carries requested/effective/deviation.
- Frozen dataclass, `slots=True`, no arrays except small tuples.

### 3.3 Ownership, error and lifecycle semantics

- **Never raise.** Every path returns a `CorrectionOutput`; an unexpected
  exception anywhere inside `correct()` becomes `FAILED("engine exception:
  <Type>: <msg>")` with the input frame. The caller (harness in M3, staged
  processor in M4) contains a raising engine anyway (ADR-0002 §5) — the
  protocol documents it; the caller does not depend on it.
- **Zero-copy passthrough** whenever no eye is corrected. **Exactly one**
  writable full-frame copy when at least one eye is corrected (ADR-0003 §5),
  allocated only after validation (§10.1). Both eyes blend into that one
  copy. The returned copy is writable and exclusively the caller's; the
  caller re-freezes before publication (M4), or writes it to disk (M3).
- **Per-eye behaviour** is explicit in `eyes`; the pair rule (§5.6) decides
  when one eye's problem stops the other.
- **Thread-agnostic, single-threaded by contract** (like `FaceTracker`): the
  harness calls it synchronously; M4 calls it on the processing worker.
- **`reset()`/`close()`** are protocol obligations. The geometric engine
  holds no *temporal* state (nothing carries from one frame to the next) and
  no resources, so `reset()` is a no-op and `close()` only latches a
  lifecycle flag: `correct()` after `close()` returns `SKIPPED("engine
  closed")`. `reset()` is where M4's epoch-driven reset lands (§20).
- **Deferred:** temporal state and ramps (M4/M5), retirement/budgets (M4,
  caller-side), any `CorrectionRequest` object (baseline: deliberately
  none), neural inputs/outputs (M9, same protocol).

---

## 4. Geometric technique selection

Evaluation frame: Python, OpenCV, NumPy, CPU, eye-region-only, soft blend,
reusable unchanged in M4, correction magnitudes of **1–10 px** at 720p
(§6.5 — this number drives everything: the iris moves a few pixels, so
sub-pixel sampling and edge behaviour matter more than algorithmic power).

### 4.1 Candidates

| Candidate | Visual quality (expected) | Eyelid preservation | Iris preservation | Artifact risk | Complexity | CPU | Strength control | M4 reuse |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A. Iris patch cut-and-paste + fill** (translate the iris disc; fill the vacated sclera by inpainting/clone) | medium; seams at the disc edge, fill texture | good if clipped by the lid | exact | **high** (disc seam, fill texture, lid slivers) | medium (inpaint is fiddly) | low–medium (`cv2.inpaint` is not cheap) | linear | yes |
| **B. Field-only eye-region remap** (one smooth displacement field: ≈ 1 over the iris interior wherever it is farther than the falloff width from the contour, 0 at the eyelid contour; `cv2.remap` on the eye ROI) | medium–good horizontally; **iris compresses against a lid** on vertical moves | exact (field is 0 on the contour) | rigid except within the falloff band | medium (iris flattening near lids at larger vertical moves; sclera stretch) | **low** | very low (ROI ≈ 100×60 px) | linear | yes |
| **C. Layered eye-region remap** (a **sclera-plate** background — B's field applied to the eye with the source iris removed and filled with sclera, A2 §8.8 — plus a rigidly translated iris layer clipped by the eye-opening mask, which is then the frame's only iris) | good; iris keeps its shape and slides **under** the lid, sclera fills behind it | exact | rigid, occluded correctly | medium–low (catchlight moves with the iris; lid does not follow upward gaze) | low–medium (B + one translated layer + two masks) | very low | linear | yes |
| **D. Piecewise-affine / Delaunay mesh warp** (contour + iris landmarks as vertices) | similar to B, with C0 creases across triangles in the sclera; 5 iris points give a coarse disc | good | approximate | medium (creases) | medium–high | low | linear | yes |
| **E. Thin-plate spline / moving-least-squares field** from control points | equivalent to C's background with a smoother field; no structural gain | good | approximate | low–medium | medium–high (solve per eye per frame) | low–medium | linear | yes |
| F. Face-wide 3-D re-rendering / neural redirection | — | — | — | — | — | — | — | out of scope (M9) |

### 4.2 Recommendation: **C, the layered eye-region remap**, with B as its built-in simplification

C is B plus one rigidly translated iris layer. It is chosen over the strictly
simpler B because of the PRD's **primary scenario**: the webcam sits above
the screen, so the dominant correction is **upward pitch**, where B's
weakness (the iris top compressing against the fixed upper lid) is exactly
the visible defect. C lets the iris slide under the lid the way a real eye
does, at the cost of one more sampling pass on a ~100×60 px region.

B is not discarded: it is the same engine with the iris layer switched off
(`GeometricCorrectionSettings.iris_layer = False`). The implementor builds B
first (background field + mask + blend), gets the pipeline of masks and the
harness working, then adds the iris layer. The harness exposes the switch so
the *engineer* can produce B-vs-C comparison sheets for an ITERATE round
without code changes (§12, §14.4). If the gate shows B is already good
enough, the switch stays and the default flips.

Rejected/deferred:

- **A** — inpainting the vacated sclera is the artifact-prone part of the
  problem and adds cost; C fills the vacated region by stretching real
  sclera texture instead. Rejected.
- **D** — nothing it offers that C lacks, and triangle creases in a
  low-texture sclera are visible. Rejected.
- **E** — the natural *escalation* if C's analytic field shows visible
  sclera artifacts at the gate; contained inside the engine (same contract,
  same masks). Deferred to an ITERATE round, not chosen by default.
- **F** — M9.

**Known structural limitation of every geometric candidate, stated up
front:** none moves the eyelids. A real upward gaze raises the upper lid; a
warped one leaves the lid where it was, so a corrected upward gaze reads as
"same lid, iris higher" — slightly heavier-lidded than reality. At the
magnitudes the policy allows (§7) this is expected to be subtle; the gate
(§14) scores exactly this. If it is not subtle, that is the
`CHANGE APPROACH` signal, and the honest answer is that the geometric class
is insufficient — not a reason to add lid warping to M3.

**Stated assumptions of the mapping:** orthographic projection (the M2
model's own assumption; `docs/gaze.md` §5 measures the error as negligible
at webcam distances) and a head within the range where M2 reports
`ESTIMATED` (policy gates on confidence, whose `pose_term` falls with head
rotation).

---

## 5. Eye-region geometry

All geometry lives in `gazefix/correction/geometry.py` as pure NumPy
functions of `EyeLandmarks`, `FrameGeometry` and a displacement — **polygon
math only**, no OpenCV, no rasterisation (masks are §8 and are built in
phase 3, §10.1). Each eye is processed **independently** through the same
code; the only cross-eye logic is the pair rule (§5.6) and the disjointness
check (§5.4).

### 5.1 Per-eye derived geometry (pixel units, image coordinates)

| Quantity | Definition | Used for |
| --- | --- | --- |
| `outer`, `inner` | contour positions 0 and 8 × `(width, height)` | axis, size |
| `half_width_px` | `|inner − outer| / 2` | scale of everything |
| `ex`, `ey` | eye axis toward the subject's left (§2.2), image-up perpendicular | displacement direction (§6), aperture |
| `aperture` | pair the 7 lower-lid points (positions 1–7, outer→inner) with the 7 upper-lid points (positions 9–15, **reversed** so they also run outer→inner); `mean(|(upper − lower) · ey|) / (2·half_width_px)` — the M2 roll-invariant formula | blink/closed gate |
| `opening` | the 16-point eyelid polygon | analytic checks (§5.3); rasterised later for masks (§8) |
| `iris_center`, `iris_radius` | `iris[0]`; mean distance of `iris[1:5]` to the centre | plateau of the warp, iris layer, plausibility |
| `roi` | axis-aligned box around `opening` grown by `padding_px = max(padding_fraction·(2·half_width_px), |d| + edge_px + 2)`. **Not clipped**: a box that would leave the image fails the border check (§5.3) | the only region the engine touches |

### 5.2 Which geometry drives what

| Concern | Geometry |
| --- | --- |
| **warp control** | `iris_center`, `iris_radius`, displacement `d` (§6), and — in phase 3 — the rasterised distance-to-contour field of `opening` (§8.1) |
| **safety checks** (phase 2, analytic) | `aperture`, `half_width_px`, `iris_radius/half_width_px`, shoelace polygon area, point-in-polygon and point-to-nearest-edge distance for `iris_center` and `iris_center + d`, `roi` bounds |
| **mask construction** (phase 3) | `opening` only (§8), anti-aliased at its edge, never widened onto lid skin; the iris circle for the iris-layer alpha |

### 5.3 Per-eye safety checks (in this order; first failure wins and names the reason)

All checks are analytic on the 16-point polygon (shoelace area, ray-casting
point-in-polygon, point-to-segment distance); none needs a mask. Defaults are
experimental constants in `GeometricCorrectionSettings` (§22).

| # | Check | Rule | Outcome |
| --- | --- | --- | --- |
| 1 | landmarks present | `eye is not None`, `contour` finite, `iris is not None` and finite | SKIPPED `no iris` (open or unknown → pair rule) |
| 2 | eyelid aperture | `aperture ≥ min_aperture` (default **0.18**; M2's `openness_floor` 0.10 is where the iris centre becomes untrustworthy, 0.20 is "full"; open eyes measure 0.25–0.4). Evaluated **before** polygon sanity on purpose: a blink or wink drives the lid landmarks onto or across each other, and that must read as a closed eye (other eye may proceed), never as a degenerate contour (both skipped) | SKIPPED `eye closed` (**closed → other eye may proceed**) |
| 3 | polygon sanity | shoelace area of `opening` ≥ `min_polygon_area_px` (default **30**) and the polygon is simple (no self-intersection) — with a normal aperture, a failure here is mistracking, not a blink | SKIPPED `degenerate contour` (open or unknown → pair rule) |
| 4 | M1 validity | `eye.valid` (all points in frame, `width_px ≥ tracking_min_eye_width_px`) | SKIPPED `eye invalid` (open or unknown → pair rule) |
| 5 | minimum size | `half_width_px ≥ min_half_width_px` (default **8**; below this a 1–3 px displacement is interpolation blur, not correction) | SKIPPED `eye too small` (pair rule) |
| 6 | iris plausibility | `0.2 ≤ iris_radius/half_width_px ≤ 0.6` (anatomy ≈ 0.39: 11.7 mm iris over a 30 mm fissure); `iris_center` inside `opening` (the plausibility check `docs/gaze.md` §5 notes M2 lacks) | SKIPPED `iris implausible` (pair rule) |
| 7 | displacement finite | `d` (§6; needs only gaze, pose, `half_width_px`, `ex`, `ey`) finite | **FAILED** `displacement not finite` — an engine fault: the whole frame is FAILED regardless of the other eye or `pair_coupling` (§10.1). Defensive: unreachable with contract-valid inputs |
| 8 | displacement clamp | §6.4 | applied, `clamped=True` |
| 9 | negligible displacement | `|d| < min_displacement_px` (default **0.25**) after the clamp | SKIPPED `negligible displacement` (treated like a closed eye: the other eye may proceed; in practice both eyes are negligible together) |
| 10 | destination containment | `iris_center + d` inside `opening` **and** at least `iris_margin_px = max(iris_margin_fraction·iris_radius, edge_px)` (default fraction **0.15**) from the nearest polygon edge | SKIPPED `iris would leave the eye` (pair rule) |
| 11 | border | the `roi` box (§5.1, grown by `padding_px`, which depends on `|d|` — hence after the clamp) lies entirely inside the image | SKIPPED `eye at image border` (pair rule) |

**Why the containment margin is small.** With iris radius `r ≈ 0.39·hw`,
open-eye aperture 0.25–0.30 (centre height ≈ 1.4 × the mean lid separation
for a lens-shaped opening, so the half-height at the centre is ≈ 0.35–0.42
`hw`) and `R_px = 0.8·hw`, a margin of `0.5·r ≈ 0.195·hw` would admit only
≈ 11–16° of upward travel for a centred iris — it would refuse most of the
10–20° operating range, and nothing at all once the centre half-height
drops to the margin (aperture ≈ 0.14). The default `0.15·r ≈
0.06·hw` admits ≈ 21–27°, leaving the hard clamp (§6.4, ≈ 39°) and the
policy (§7) to bound the rest. The margin is a knob the gate may move
(Q11); an area-based alternative ("the destination disc keeps ≥ X % of its
area inside the opening") is the ITERATE option if point containment proves
too coarse.

### 5.4 Two-eye checks

- **Disjointness:** the two `opening` polygons' bounding boxes must not
  intersect; if they do the geometry is degenerate (a face this small or
  this rotated is not correctable) → SKIPPED `eyes overlap`, both.
- ROI boxes *may* overlap (padding); this is harmless because each eye
  samples from the **original** frame and blends with its own eye-shaped
  alpha **into the canvas** (§8.4) — with disjoint alphas the two blends
  commute, whatever the ROI overlap.

### 5.5 Insufficient landmarks

A 468-point result (`iris_available=False`) has nothing to move: SKIPPED
`no iris` at frame level, zero-copy. This is the same rule M2 applies.

### 5.6 One-eye-only validity — the pair rule (D7)

Correcting one eye and not the other manufactures a vergence error (the eyes
point in different directions), which is more uncanny than the deviation
being corrected (PRD §4: natural beats perfect). Therefore:

- If an eye is **closed or occluded** (aperture below threshold) or its
  displacement is **negligible**, it has no visible iris to disagree with:
  it is SKIPPED with its reason and the **other eye may be corrected** (a
  wink, a hand over one eye).
- If an eye is **open but cannot be corrected safely** (no iris, degenerate
  contour, invalid, too small, implausible iris, would leave the eye, at the
  border, eyes overlap), **both eyes are skipped** — the healthy eye gets
  `pair skipped: <other side> <reason>` — and the frame passes through.
- A per-eye **FAILED** is an engine fault and is never subject to pairing:
  the frame is FAILED (§10.1).
- `GeometricCorrectionSettings.pair_coupling` (default `True`) switches the
  second bullet off. It is an experiment switch for an ITERATE round (the
  engineer prepares a with/without sheet if the PM asks), not a gate step.

---

## 6. Gaze-to-image displacement mapping

The semantic request `source gaze → target gaze → effective strength` becomes
per-eye pixel displacement by **inverting the frozen M2 eye model** exactly.
No new model, no calibration; one experimental gain.

### 6.1 Conventions

- Angles in degrees; directions are unit vectors in the M2 camera frame
  (x right, y up, z toward viewer). Positive yaw = subject's left = image
  right; positive pitch = up.
- Image displacement `d = (dx, dy)` in pixels, image coordinates (y down).
- **Pose branch.** If `gaze.confidence.head_pose_applied` is `True` **and**
  `tracking.pose` is usable (§2.3), `R = pose.rotation` and the cosines of
  §6.3 come from the Euler angles. Otherwise (a substitute estimator
  publishing `ESTIMATED` without a pose; a `None` or non-finite pose):
  `R = I` and `c_yaw = c_pitch = 1` — the estimator's own no-pose values.
  The engine never dereferences an absent pose.
- `k = eye_model_ratio` (default 1.25) and `min_cos` (default 0.5) — **both
  must equal the estimator's** (§6.6).

### 6.2 From gaze to a head-frame direction change (once per frame)

```text
(yaw_s, pitch_s) = angles_from_direction(gaze.direction)        # source, camera frame
(yaw_t, pitch_t) = angles_from_direction(target)
yaw_c   = yaw_s   + s · (yaw_t   − yaw_s)                          # PRD PR-5, interpolated in yaw/pitch space
pitch_c = pitch_s + s · (pitch_t − pitch_s)                        #   (baseline: "expressed in yaw/pitch space")
g_cam_c = direction_from_angles(yaw_c, pitch_c)

g_head_s = Rᵀ · gaze.direction                                     # source eye-in-head direction (M2 composed g_cam = R·g_head)
g_head_c = Rᵀ · g_cam_c                                            # corrected eye-in-head direction
Δ = (Δx, Δy) = (g_head_c − g_head_s)[0:2]                           # planar change, head frame (x subject's left, y up)
```

`s = 0` gives `Δ = 0` exactly. The transpose matters: for a head turned 20°
toward the subject's left with the eyes on the camera, `Rᵀ·(0,0,1)` is an
eye-in-head direction 20° to the subject's right — the eyes must be rotated
in the head to hold the camera, and the displacement must be computed in
the head's frame because the eye axis `ex` is measured on the (rotated)
face. §15.2 contains a test that fails if `R` is used in place of `Rᵀ`.

### 6.3 From head-frame change to per-eye pixels (per eye)

The M2 forward model per eye (`docs/gaze.md` §3):
`g_x = k·u`, `g_y = k·v·cos(head_yaw)/cos(head_pitch)`, with
`u = (iris − corner_midpoint)·ex / half_width_px`, likewise `v` along `ey`,
and both cosines clamped to `[min_cos, 1]`. Inverting:

```text
c_yaw   = clamp(|cos(pose.yaw_deg)|,   min_cos, 1)     c_pitch = clamp(|cos(pose.pitch_deg)|, min_cos, 1)   (or 1, 1: §6.1)
Δu = Δx / k
Δv = Δy · c_pitch / (k · c_yaw)
d  = gain · half_width_px · (Δu · ex + Δv · ey)         # image pixels; ey already points image-up, so no sign flip is needed
```

Equivalently `d = gain · R_px · (Δx·ex + Δy'·ey)` with `R_px = half_width_px / k`
the eyeball radius in pixels (`0.8·half_width_px` at `k = 1.25`) — the
displacement is the eyeball radius times the change in the eye-in-head
direction, which is what rotating a sphere does.

**Relative, not absolute.** `d` is added to the iris's *current* pixel
position. The engine never computes "where the iris should be" from the
corner midpoint, so the structural nasal bias of that reference (12.6° of
raw inter-eye disagreement, `docs/gaze.md` §4), angle kappa and the
per-user `k` do not move the iris to a wrong absolute place; they only scale
`d` (a gain error, tolerable and tunable).

### 6.4 Normalisation, clamping, extremes

- **Eye-size scaling** is intrinsic: `d ∝ half_width_px`. Resolution
  independence follows; the harness verifies it by rescaling inputs (§17).
- **Hard clamp:** `|d| ≤ max_displacement_fraction · half_width_px`, default
  **0.5** (≈ 0.625·R_px, an eye-in-head change of ≈ 39° at `k = 1.25`). The
  clamp shortens `d` along its direction, never redirects it, and sets
  `clamped=True`. Policy (§7) keeps ordinary operation far below this; the
  clamp is the engine's own safety net against a mis-set policy or a wild
  estimate.
- **Destination containment** (§5.3 #10) is the second, geometric limit.
- **Extreme deviation** (> 35°) is a policy decision (effective strength 0
  → SKIPPED `strength 0`); the engine does not read the deviation curve.
- **Gain:** `displacement_gain` default **1.0**, experimental (tuned by the
  engineer through the harness; §14.4). It is *not* a user/calibration
  parameter; if the gate shows a systematic gain error, that is evidence for
  M6's calibration design, recorded in the report, not a new setting tier.

### 6.5 Derived magnitudes (from the model, **not measured**)

For a frontal head, per degree of eye-in-head rotation near centre:
`|d| ≈ sin(1°)·R_px ≈ 0.014 · half_width_px`.

| eye width (px) | half-width | R_px | 5° | 10° | 15° | 20° | 25° | 30° |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | 20 | 16 | 1.4 | 2.8 | 4.1 | 5.5 | 6.8 | 8.0 |
| 50 | 25 | 20 | 1.7 | 3.5 | 5.2 | 6.8 | 8.5 | 10.0 |
| 70 | 35 | 28 | 2.4 | 4.9 | 7.2 | 9.6 | 11.8 | 14.0 |

Two consequences for the implementor: (1) sampling must be **sub-pixel**
(float32 maps, bilinear or bicubic interpolation; integer shifts would
quantise a 10° correction to whole pixels); (2) at webcam eye sizes the
whole effect is a few pixels, which is why "prove visible redirection" is a
real question and not a formality.

### 6.6 The shared constants `k` and `min_cos`

The inverse is exact only if the engine's `eye_model_ratio` **and**
`min_cos` equal the estimator's. In M3 the harness passes both from one
source to `GazeSettings` and to `GeometricCorrectionSettings`
(`--eye-model-ratio` writes both; a `--set` on one side alone is a
deliberate mismatch and the report says so); at M4 the composition root
passes `AppSettings.gaze_eye_model_ratio` (and the `GazeSettings` default
`min_cos`) to both. This coupling is recorded here so M6 (which may replace
`k`) knows both consumers exist. A mismatch is a gain error, not a failure.

---

## 7. Correction policy (outside the engine)

### 7.1 Decision: a small reusable pure function, plus a harness bypass

`gazefix/correction/policy.py` provides:

```text
PolicySettings   deviation curve breakpoints, confidence gate, max_effective_strength
PolicyDecision   requested_strength, effective_strength, deviation_deg, confidence, reason
resolve_effective_strength(requested: float, gaze: GazeResult | None, target: Array, settings) -> PolicyDecision
```

Stateless and deterministic; imports `gazefix.gaze.models` and NumPy only;
does not import the engine, and the engine does not import it. M4 hosts it
inside the staged processor (baseline: "policy layer in the staged
processor") and wraps it with the stateful ramps/slew limits of M4/M5 —
the pure function stays the core. Placing the function in the correction
*package* rather than the pipeline package is a module-boundary choice
(PRD §26), not a change to ADR-0002 §3: engines still cannot influence
whether they run.

**Configuration tier.** `PolicySettings` belongs to the baseline's
*runtime constants* tier: code defaults, overridable through the harness
`--set policy.*` in M3, and at M4 seeded from `AppSettings` fields the way
`GazeSettings` is seeded from the `gaze_*` fields today. Requested strength
itself stays a *product/user* setting (baseline table). `conf_floor` is
seeded from the same value the estimator receives as `min_confidence`.

The harness applies the policy by default and reports the decision; it can
bypass it (`--effective-strength`) so the engine can be exercised at any
strength directly. That gives M4 the reusable core without building the
realtime policy system now.

### 7.2 The M3 curve (behavioural starting targets, all in `PolicySettings`)

```text
deviation_deg  = angle between gaze.direction and target        (acos of the dot product; combines yaw and pitch)

m_dev(deviation):  piecewise linear through
                   (0°, light_factor=0.3) → (5°, 1.0) → (25°, 1.0) → (35°, 0.0);  0 beyond 35°
m_conf(score):     0 below conf_floor (0.35 = estimator min_confidence), 1 at/above conf_full (0.60), linear between
effective          = clamp(requested · m_dev · m_conf, 0, max_effective_strength=1.0)
```

How this reads PRD §10's bands — an engineering interpretation carried by
the approved SA, not a restatement of the PRD and not among the freeze's
enumerated ratifications; the breakpoints stay tunable from M3 evidence, as
PRD §10 itself allows ("Exact thresholds may change after testing"):
0–5° "very light" → the multiplier ramps from 0.3 to 1; 5–15° "normal" → 1; 15–25° "stronger" → 1, because the interpolation itself
already moves the iris further as the deviation grows (`s·Δ`), so no
multiplier above 1 is introduced; 25–35° "reduce" → ramp to 0; > 35°
"disable" → 0. A deadband near 0° (the ±10° error budget makes a 2°
"deviation" mostly noise) is deliberately left to M5, where its temporal
effect can be judged.

Reasons: `gaze not estimated` (status ≠ ESTIMATED → 0), `low confidence`
(`m_conf == 0` on an ESTIMATED gaze), `deviation above disable threshold`,
`requested strength 0`, `ok`.

---

## 8. Mask construction and blending (engine-internal)

`gazefix/correction/masks.py` holds the helpers; the engine composites. No
compositor component exists (ADR-0002 §4). Everything here runs in phase 3
(§10.1), after every analytic check has passed.

### 8.1 Per-eye fields on the ROI (float32)

| Field | Construction | Purpose |
| --- | --- | --- |
| `opening_mask` | `cv2.fillPoly` of the 16-point eyelid polygon (optionally with sub-pixel `shift` bits or a Catmull-Rom-smoothed contour — implementor's choice); values `{0, 1}` | occlusion, distance field, blend region |
| `distance` | `cv2.distanceTransform(opening_mask, DIST_L2, DIST_MASK_PRECISE)` — the exact Euclidean distance, for each inside pixel, to the nearest **zero pixel**; 0 outside. The precise mask is the default because the §8.2 bound and its test rely on it; a chamfer approximation (3×3/5×5, up to ≈ 4 % over-estimate) is allowed only together with `field_guard_px ≥ 2.5` | warp falloff (§8.2) and blend alpha — **not** containment, which is analytic (§5.3) |
| `sclera_plate` (variant C only, **A2**) | `roi_src` with the **iris hole** — the source iris disc grown by 1 px, intersected with `opening_mask` — replaced by sclera: for each scan-line along the eye axis `ex`, linearly interpolate between the nearest non-hole pixels inside the opening on either side; replicate the one available side if the hole reaches the opening edge on the other; and if a line has no non-hole interior pixel at all, use the median colour of the eye's non-hole interior pixels. Pixels outside the hole are copied unchanged, so nothing outside the opening is touched. Deterministic, ROI-local, ~35×35 px of work | the image the **background** field samples in variant C (§8.2), so the background carries no iris. Variant B does **not** use it — its whole mechanism is warping the real iris |
| `alpha` (blend) | `clip(distance / edge_px, 0, 1) · opening_mask` (default `edge_px` **1.5**, range 1–3), or a `shift`-bit anti-aliased `fillPoly` multiplied by `opening_mask`. A Gaussian blur is **not** an allowed construction (it never reaches exactly 1 near the edge, §15.2). Exactly 0 outside the opening; exactly 1 at every interior pixel with `distance ≥ edge_px` | eye-shaped blend that never writes on lid skin; see §8.4 for why it is *not* a wide feather |
| `iris_alpha` (variant C) | soft disc at the **destination** iris centre, radius `iris_layer_radius_scale·iris_radius` (default 1.05), 1–1.5 px edge; multiplied by two **binary** occlusion factors — `opening_mask` at the **destination** (occlusion by the lid), and `opening_mask` at the **source** position `p − d`, the latter *conservative* in the sense §8.2 already uses for the background: it is 1 only when **all four bilinear taps** of `p − d` have `opening_mask == 1`, and 0 otherwise. Both factors stay binary deliberately. A fractional source factor would not deliver the guarantee it looks like it delivers: `iris_layer` is itself the bilinear sample at `p − d` (§8.3), so a straddling footprint has already baked lid-skin taps into the sample, and merely attenuating it by the coverage `c` still leaves `c·(1 − c)` — up to **25 %** of the pixel — as skin colour inside the opening. Only excluding straddling footprints keeps "lid skin that clipped the iris in the source is never carried into the eye" literally true | iris layer compositing. **Since A1 (§8.7) this mask alone keeps the iris layer off lid skin**: `iris_alpha == 0` wherever `opening_mask == 0` is a mandatory invariant, separately tested (§15.2), because the outer `alpha` multiply no longer wraps the iris layer. `iris_alpha ∈ [0, 1]` and finite is likewise mandatory: A1 makes it the outermost weight of the composite, so nothing else bounds it |

### 8.2 Warp field (variant B/C background)

**What the field samples (A2, §8.8).** The field below is unchanged, and so
is its lid-safety bound; only the *image* it samples differs by variant:
variant C samples the `sclera_plate` (§8.1) so the background is sclera and
never a second iris, while variant B samples `roi_src`, because warping the
real iris is variant B's entire mechanism. Call that image `roi_bg`.

For each output pixel `p` in the ROI:

```text
D(p) = d · w(p),      w(p) = min(1, max(0, distance(p) − m) / f),      m = field_guard_px (1.5 px with the precise transform),      f = max(|d|, f_min)
f_min = falloff_fraction · half_width_px        (default falloff_fraction 0.15)
```

Because `f ≥ |d|`, `|D(p)| ≤ distance(p) − m` wherever `w > 0`: the sampled
location `p − D(p)` and its 2×2 bilinear footprint stay inside
`opening_mask`: `distance` is measured centre-to-centre to the nearest zero
pixel, and every tap of the bilinear footprint lies less than √2 px from
the sample, so a guard `m ≥ √2` (default **1.5 px**) keeps every tap on a
pixel with `opening_mask == 1`; an approximate chamfer transform (up to
≈ 4 % over-estimate) needs `m ≥ 2.5`. Lid skin therefore cannot be sampled
into the eye. This is a discrete bound on the rasterised
mask and becomes a test (§15.2); it is not claimed for the continuous
polygon.
Far from the contour (the iris interior and the sclera middle) `w = 1`:
rigid translation. Within `f + m` of the contour the content
compresses/stretches smoothly; the boundary ring (`distance ≤ m`) does not
move at all; the vacated region behind a moving iris is filled with real,
stretched sclera.

Sampling: `cv2.remap(roi_bg, map_x, map_y, INTER_LINEAR, BORDER_REPLICATE)`
with `map = grid − D` (`roi_bg` = `sclera_plate` in C, `roi_src` in B); `INTER_CUBIC` is an experimental alternative for a
sharper iris. Maps are ROI-local float32.

### 8.3 Iris layer (variant C only)

`iris_layer(p) = roi_src(p − d)` for `p` in the destination disc — a pure
translation, sampled bilinearly (a second small `remap` or an equivalent
`warpAffine`) — sampled from `roi_src`, never from the plate, so it carries
real iris texture. After A2 it is the **only** iris in a variant-C frame.
Composited with `iris_alpha` over the alpha-blended base of §8.4 (A1; before that amendment it was composited over the background alone).
Where the iris layer has no valid source (lid-clipped in the source),
`iris_alpha` falls to 0 and that base shows through, so variant C degrades
gracefully to B locally. That cut-off is sharp by construction (§8.1): a
partially covered source footprint counts as no valid source. The trade is
deliberate — a one-pixel transition between moved-iris and warped-background
content, both of which are eye content, in exchange for never admitting lid
skin into the eye.

### 8.4 Compositing into the canvas

Two steps, in this order (**Amendment A1**, §8.7 — the pre-A1 single-step
form is superseded):

```text
base         = alpha · background + (1 − alpha) · canvas[roi]     opening alpha blends the warped background into the canvas
                                                                  (`background` = the warped sclera plate in C, A2 §8.8)
canvas[roi]  = iris_alpha · iris_layer + (1 − iris_alpha) · base  the translated iris is composited over that base
                                                                  (variant B: iris_alpha ≡ 0, so canvas[roi] = base)
```

float32 math, rounded back to uint8 once. Expanded, the output is
`iris_alpha·iris_layer + (1−iris_alpha)·alpha·background +
(1−iris_alpha)·(1−alpha)·canvas` — three weights that sum to exactly 1 for
every `(alpha, iris_alpha)`, so the composite is convex and can neither
overshoot nor lose energy. Two consequences are the point of A1: an **opaque
iris contribution is never diluted** by the unmoved original
(`iris_alpha == 1` ⟹ output `== iris_layer`, at any `alpha`), and **variant B
is bit-identical to the pre-A1 behaviour** (`iris_alpha ≡ 0` ⟹ output
`== base`, the original background alpha blend).

Each eye **samples** only `frame` (the immutable input) and **blends into
the canvas** (a fresh copy of `frame`, so the result is identical to
blending against `frame` for non-overlapping eyes, and the first eye's
pixels survive where the ROIs overlap: outside its own opening both `alpha`
and `iris_alpha` are 0, so the canvas passes through untouched). Order of
eyes is irrelevant (§5.4), whose disjoint-opening requirement makes both
alphas disjoint too, since `iris_alpha ⊆ opening_mask` and
`support(alpha) == support(opening_mask)`. `compositing_ms` (§3.2) covers
`alpha`/`iris_alpha` construction and this blend, unchanged by A1.

**Where the softness comes from — and why `alpha` is nearly hard.** The
eyelid line is a real occlusion edge: skin on one side, eye on the other,
sharp in every photograph. Softness therefore must not come from a wide
alpha feather along that line: on a narrow opening (aperture 0.18 × 50 px
≈ 9 px tall) a 3–4 px feather would dilute the corrected sclera against the
unmoved original through much of the eye, and soften the lid line itself.
(Before A1 a wide feather also ghosted the *iris*; A1 removes that failure
mode — an opaque iris now survives any `alpha` — so the reason to keep
`edge_px` small is the background/sclera one, and the anti-ghosting
guarantee is carried by the compositing order itself.) Softness comes
instead from three places that are correct for this geometry: (1) the warp field `D(p)` goes continuously to zero at the
contour (§8.2), so corrected content converges to the original along the
lid — continuity in *content*, which is what "blends naturally" (PRD §11)
means here; (2) the iris layer's disc edge is soft (`iris_alpha`), so the
iris/sclera transition is smooth in the direction of motion; (3) the
opening mask edge is anti-aliased over about a pixel (`edge_px`) — which
after A1 governs the *background* transition at the lid, while the iris
layer's own transition there is governed by `iris_alpha` (see the aliasing
note in §8.7 and its verification in §15.2). A hard rectangular mask never
appears anywhere — the ROI is a working window, never a blend region.
`edge_px` remains a harness knob so the engineer can demonstrate the
sclera dilution a wide feather causes if the PM asks.

### 8.5 What qualifies as acceptable soft blending for M3

- No visible boundary between corrected and original pixels at 100 % zoom
  on the PO's stills, in particular no halo, no double lid line and no
  ghosted second iris edge along the eyelid contour.
- Lid skin, lashes, eyebrows and everything outside `opening` bit-identical
  to the input (testable: pixels where `alpha == 0` are unchanged).
- Sclera fill behind the iris without a visible seam or obvious smear at
  strength ≤ 0.8 on 10–20° deviations.
- The iris/sclera boundary stays sharp in the direction of motion (a soft
  disc edge of 1–1.5 px, not a wide feather).
- **Exactly one iris is visible (A2).** No remnant of the iris at its
  original position, in particular no darkened band retained against either
  eyelid, and no double or smeared iris edge between the two positions.
- **Where the opaque part of the moved iris meets the eyelid contour (A1),
  the iris/lid edge shows no stair-stepping a viewer would notice at 100 %
  zoom, and no bright or dark fringe.** This is the edge A1 moved from the
  anti-aliased `alpha` onto `iris_alpha`'s destination factor; §15.2 bounds
  it and §24 Q12 tracks it.
- Hard rectangular regions never appear (the ROI is never the blend region).

### 8.6 Edge cases

Eye at the image border → SKIPPED (§5.3). ROI overlap → harmless (§5.4,
§8.4). Extreme head roll → axes rotate with the eye; masks follow the
contour. Glasses frames crossing the eye opening: the mask is
landmark-shaped, so a frame edge inside the opening will be warped with the
sclera — an expected artifact class for the glasses condition in §14, not a
pre-emptive M3 fix. An empty or non-finite mask **after** the analytic
checks passed (area ≥ 30 px is guaranteed by §5.3 #3) can only be an engine
fault and is `FAILED` (§10.3).

### 8.7 Amendment A1 — compositing order (2026-09-05, PM-approved)

**Scope.** Milestone-local correction of one formula and the wording that
depends on it. Two further edits are in scope because the new order forces
them, and there are no others: §8.1 states the two `iris_alpha` occlusion
factors explicitly as **binary**, with the source factor conservative (all
four bilinear taps inside), because A1 makes `iris_alpha` the sole guarantor
of a guarantee the outer `alpha` used to provide; and §11 gains one invariant
row saying so. ADR-0002's boundary is untouched — the engine still owns masks
and compositing, still creates no compositor stage, and still returns one
complete corrected frame with a metadata-only result — so **no new ADR is
required**. The M3/M4 scope boundary, the engine contract (§3), the geometry
and mapping (§5, §6), the policy (§7), the failure semantics (§10) and the
frame-ownership *copy budget* (§11) are unchanged.

**Implementation evidence that triggered it.** M3 implementation reported
that the frozen §8.4 formula and the frozen §15.2 "no ghosting near the lid"
test cannot both be satisfied. Expanding the superseded formula gives
`alpha·iris_alpha·iris_layer + alpha·(1−iris_alpha)·background +
(1−alpha)·canvas`; at a pixel with `iris_alpha == 1` and `0.5 < alpha < 1`
that reduces to `alpha·iris_layer + (1−alpha)·canvas`, so the moved iris is
mixed with the unmoved original by a factor of `1 − alpha` — up to half the
pixel — while the test requires the output to equal `frame(p − d)`. The
requirements were mathematically incompatible; the contradiction is real and
was confirmed independently, not a test-authoring slip.

**Superseded formula (frozen `m3-architecture-v1` §8.4):**

```text
composed     = iris_alpha · iris_layer + (1 − iris_alpha) · background
canvas[roi]  = alpha · composed + (1 − alpha) · canvas[roi]
```

**Corrected formula (this amendment, §8.4):**

```text
base         = alpha · background + (1 − alpha) · canvas[roi]
canvas[roi]  = iris_alpha · iris_layer + (1 − iris_alpha) · base
```

**Rationale.** The opening alpha exists to blend the *warped background* —
the stretched sclera — into the canvas at the lid; the iris layer is a
separate, physically opaque object that sits in front of it. Applying the
opening alpha to the iris layer as well conflated the two and re-introduced
the unmoved original into the one place the correction is most visible.
Compositing the iris **over** the alpha-blended base keeps each alpha doing
its own job: `alpha` governs the background/lid transition, `iris_alpha`
governs the iris's own soft edge and its source/destination occlusion. The
composite stays convex (weights sum to 1), variant B is bit-identical to
before, and the resolution was chosen over weakening the test because the
test encodes a genuine product requirement — PRD §11's "corrected regions
must blend naturally", with no ghosted second iris edge.

**Known consequence, accepted and to be verified, not designed around.**
Before A1 the outer `alpha` multiply also anti-aliased the *iris*'s edge
against lid skin. It no longer does, so where the **opaque core** of the
moved disc crosses the eyelid contour, the iris-to-skin transition is now as
hard as the binary destination `opening_mask`, and can stair-step by up to
one pixel along the lid. It is bounded: it can only appear when the iris is
partly occluded (the upward-gaze case), never on a fully visible iris, and
never outside the opening. Making `iris_alpha`'s destination factor the
anti-aliased `alpha` would smooth it, but would also force `iris_alpha == 1`
to imply `alpha == 1` and make the no-ghosting test's precondition
unsatisfiable — a silent weakening of the test, which the amendment
deliberately refuses. The aliasing is therefore verified (§15.2), scored at
the gate (§8.5, §14.2 artifact visibility), and tracked as §24 Q12; if the
Product Owner sees it, the fix is an ITERATE-round decision with evidence,
not a pre-emptive redesign here.

**Required regression coverage** (all in §15.2, marked *A1*):

1. no ghosting near the lid — an opaque iris (`iris_alpha ≥ 1 − 1e-6`) in
   the partial-alpha band equals `frame(p − d)`, with the **superseded
   formula** as the negative control (the old `edge_px = 4` control is void
   under A1: a wide feather no longer dilutes an opaque iris). The selected
   pixel set must be asserted non-empty and the control must deviate on at
   least one of them, so the test cannot pass vacuously;
2. the outside-the-opening invariant asserted at the mask level
   (`iris_alpha == 0` wherever `opening_mask == 0`), because A1 makes that
   invariant rest on `iris_alpha` alone;
3. convexity — the three composite weights sum to 1 for representative
   `(alpha, iris_alpha)`, catching a transcription error directly, together
   with its precondition `0 ≤ iris_alpha ≤ 1` and finite (non-negativity of
   the weights, not just their sum, is what makes the composite convex, and
   A1 leaves nothing else to bound the outermost weight);
4. variant B equivalence — with the iris layer off, the output equals the
   pre-A1 formula exactly;
5. lid-edge aliasing — the opaque disc crossing the lid, bounding the hard
   step to the contour ring and recording its magnitude as the Q12
   measurement;
6. partial source coverage — a straddling source footprint gives
   `iris_alpha == 0` under §8.1's conservative all-taps rule, so the output
   is `base` and **no** lid-skin colour appears inside the opening, with a
   plain bilinear (fractional) source factor as the negative control;
7. eye-order independence with overlapping ROIs, re-checked under the new
   order, asserted on the §8.4 blend helper (the engine's own order is fixed
   right-then-left by §10.1);
8. the sclera-dilution control — `edge_px = 4` measurably dilutes the
   *background* correction — which is the replacement coverage for the
   `edge_px = 4` negative control A1 voids in item 1.

### 8.8 Amendment A2 — the variant-C background is a sclera plate (2026-09-05, PM-approved)

**Scope.** Milestone-local. It changes *which image the background field
samples* in variant C, and nothing else about the field, the masks, the
compositing order or any contract. The `CorrectionEngine` contract (§3),
provider-neutral boundaries (§18), the gaze-to-displacement mapping (§6), the
policy boundary (§7), frame ownership (§11), **A1's compositing order (§8.4,
§8.7)**, the harness architecture (§12) and the M3/M4 boundary (§23) are all
unchanged, so **no new ADR is required**.

**Implementation evidence.** On the required realistic-anatomy upward case
the implementation reproduced the frozen v1.1 equations pixel-for-pixel and
measured: commanded displacement **9.317 px**, frozen minimum visible
centroid movement **5.590 px**, actual visible movement **1.278 px**. All
seven suite failures were visible-iris-movement assertions; A1, engine,
mapping, policy, real-model, ownership/fallback, boundary and M3/M4
separation tests passed. An independent geometric simulation of the frozen
equations on the same fixture reproduces the failure at **1.14 px**,
confirming the mechanism rather than an implementation slip.

**Root cause.** The background was `roi_src(p − D(p))` — the *unmodified*
source. `D(p) = d · w(p)` and `w` is pinned to 0 within `f + m` of the
eyelid contour so the warp can never sample lid skin (§8.2). On a realistic
eye the iris is **taller than the palpebral opening** (`docs/gaze.md` §5: an
≈ 11.7 mm iris behind an 8–12 mm aperture; on the realistic fixture a 17.55 px
iris radius behind a 15.7 px opening half-height), so the pixels adjacent to
both lids *are* iris. The background therefore reproduced the source iris
exactly in the pinned band, while the translated layer was additionally
masked off wherever the destination left the opening or the source coverage
was incomplete. Output held an old iris against the lids and a new iris in
the middle; the visible centroid barely moved. The defect is inherent to
sampling the unmodified source for a layer that is supposed to be
background-only, and it is worst exactly where the product needs it most —
upward correction, the PRD's primary scenario.

**Correction.** Variant C's background samples a **sclera plate** (§8.1):
`roi_src` with the source iris hole filled by sclera. The iris then exists
only in the translated layer. The displacement field, its guard, `alpha`,
`iris_alpha`, the compositing order and every mask are untouched; variant B
keeps sampling `roi_src`.

**Why this one.** Rejected alternatives are recorded in §8.8's companion
list: filling only the vacated crescent (leaves the retained iris wherever
the layer is clipped — the failing case); forcing `w = 1` over the iris
(breaks the §8.2 lid-safety bound and pulls lid skin into the eye);
`cv2.inpaint` (the §4.1 candidate-A cost and artifact risk, plus
build-dependent output in a deterministic suite); reverting to variant B
(the compression defect C exists to avoid). The plate is the only option
that removes the competing content at its source while leaving every safety
invariant and A1 untouched.

**Measured effect** (same simulation, realistic fixture, ratio to the
geometric ideal — the visible centroid a perfect renderer would produce):

| case | v1.1 | A2 | geometric ideal | A2 / ideal |
| --- | --- | --- | --- | --- |
| vertical 15° | 1.14 px | 5.19 px | 4.76 px | 1.09 |
| vertical 10° | 0.96 px | 3.67 px | 3.22 px | 1.14 |
| horizontal 15° | 6.84 px | 8.99 px | 8.97 px | 1.00 |
| horizontal 10° | 4.95 px | 6.10 px | 6.07 px | 1.00 |

**Why the default fixture never caught this.** The same simulation, swept
across apertures 0.20–0.30 and iris ratios 0.32–0.45, shows the defect exists
**only when the iris is clipped by the lids**: with an unclipped iris the v1.1
equations score 1.00 of the geometric ideal, because the source iris then sits
inside the field's `w = 1` region and travels with the background. That is
exactly why the default (unclipped) fixture passed while the realistic
(clipped) one failed, and why the realistic-anatomy fixture A1 introduced is
what exposed it.

**A threshold that was not achievable, and its replacement.** The same
simulation shows the frozen `0.6·|d|` floor exceeds what *any* correct
implementation can reach on the clipped fixture for vertical moves: the
geometric ideal is 4.76 px against a 5.59 px floor at 15°, and 3.22 px
against 3.75 px at 10°. A clipped iris cannot move its *visible* centroid by
`0.6·|d|` — the upper lid cuts the leading edge as fast as the trailing edge
rises. The floor is therefore replaced by a comparison against the geometric
ideal computed from the fixture's own landmarks (§15.1). This is a
**strengthening, not a relaxation**: the ideal band rejects the v1.1
behaviour on the horizontal rows too (0.76 and 0.82 of ideal), which the
`0.6·|d|` floor passed.

**What the band is and is not.** It is calibrated for the two named fixtures
and is asserted only there. The sweep shows the ratio is anatomy-dependent by
construction: on a tight aperture with a large iris, A1's conservative
source-coverage rule removes so much of the moved disc that a correct
implementation legitimately reaches 1.4–4.2 × the ideal, and for *horizontal*
moves on a barely-clipped eye the retained source iris overlaps the moved one
so the centroid barely notices it (v1.1 scores up to 0.98 of ideal there).
Two consequences for the test design: the band is fixture-bound, not a
general acceptance criterion; and the **primary, threshold-free discriminator
of this defect is the "exactly one iris" structural assertion**, with the
centroid band as the quantitative check beside it.

**Known consequences, recorded rather than designed around.** (1) The
sclera fill is synthetic where the iris used to be; it is low-texture and
sits behind the iris layer, but it can read flat next to real sclera — §24
Q13, scored at the gate. (2) A1's conservative source-coverage rule removes
a thin crescent (≈ 1.9 px on the fixture) from the bottom of an
upward-moved iris, because that content was under the lower lid in the
source and does not exist; the visible iris can therefore show a slightly
flattened trailing edge, and the measured centroid sits marginally *above*
the ideal — §24 Q14.

**Required regression coverage** (in §15.2, marked *A2*):

1. the background carries no iris — the plate has no iris-tone pixel inside
   the iris hole;
2. **primary:** exactly one iris in the output — inside the opening, every
   iris-tone pixel lies within the destination disc dilated by 1 px. This is
   the threshold-free assertion that pins the defect on every clipped case;
3. visible-centroid movement inside the geometric-ideal band on the
   realistic fixture, with the v1.1 background as the negative control —
   quantitative support for item 2, fixture-bound (see above);
4. variant B is untouched by A2 — its output is bit-identical with the plate
   code path present;
5. the plate never writes outside the opening, and the §8.2 lid-safety bound
   still holds when sampling the plate;
6. the fill's degenerate fallbacks (one-sided, and no interior sclera on a
   line) are exercised deterministically.

---

## 9. Blink / closed-eye handling (per frame, no temporal state)

Principle: **preserve the original eye rather than force correction**. No
blink prediction, no stale gaze. Messages follow the fixed gate order of
§10.1.

| Condition | Detection | Behaviour |
| --- | --- | --- |
| both eyelids closed / blink | M2 returns `UNAVAILABLE` ("both eyelids are too closed"); policy → 0 | SKIPPED `strength 0` when the caller applied policy (the normal path); `no gaze: unavailable` only when the harness bypass feeds a non-zero strength; zero-copy either way |
| one eye closed (wink), gaze `ESTIMATED` from the other | that eye's `aperture < min_aperture` | that eye SKIPPED `eye closed`; the other corrected (pair rule §5.6) |
| squint / aperture under threshold on an eye M2 still used | engine `aperture < min_aperture` (0.18 > M2's 0.10 floor: the engine is stricter than the estimator because it needs a visible iris to move, not just a centre to measure) | SKIPPED `eye closed` for that eye; pair rule |
| iris landmarks unavailable/implausible | §5.3 #1/#6 | SKIPPED; pair rule (open eye → both) |
| eye geometry collapses with a normal aperture (self-intersecting or tiny polygon, eyes overlap) | §5.3 #3, §5.4 | SKIPPED both |
| lid landmarks collapsed onto each other (a shut eye seen by the tracker) | §5.3 #2 fires first (aperture ≈ 0) | SKIPPED `eye closed`; the other eye may proceed |
| warp unsafe (destination leaves the eye after clamp; at the border) | §5.3 #10/#11 | SKIPPED; pair rule |
| non-finite displacement | §5.3 #7 | frame FAILED (engine fault) |

Hysteresis around `min_aperture` (the eyelid hovering at the threshold
flickers correction on/off) is a **temporal** concern and belongs to M5; on
stills it does not exist; on the harness's clips it is observed and
reported, not fixed.

---

## 10. Failure and fallback semantics

### 10.1 Validate-then-commit (D8) and the fixed gate order

`correct()` runs in three phases.

**Phase 1 — frame-level gates**, evaluated in exactly this order; the first
failure names the message and returns the input:
`engine closed` → `unsupported frame` → `geometry mismatch` →
`mirrored coordinates` → `invalid strength` → `strength 0` →
`invalid target` → `no gaze: <status>` → `no landmarks` / `no iris`.

**Phase 2 — per-eye analytic checks** (§5.3, right eye then left), the
disjointness check (§5.4) and the pair rule (§5.6) — **no pixel is written
yet**. Any per-eye FAILED here makes the frame FAILED at once.

**Phase 3 — commit**, only if at least one eye is CORRECTED-eligible, in
this order: allocate the working copy; for the right eye then the left,
build the opening mask, distance field and warped layers (background remap
and, in variant C, the iris-layer remap) into ROI-sized buffers; then
composite both eyes into the canvas (alpha/iris-alpha construction and the
§8.4 blend, right then left) — `compositing_ms` spans exactly this last
step. Any exception in phase 3 discards the canvas and returns the input
with `FAILED`. A half-corrected frame is
therefore impossible, and skipping costs no copy.

### 10.2 Per-eye fallback before whole-frame fallback?

Yes for **closed/occluded/negligible** eyes (correct the other), no for
**open but unsafe** eyes (skip both) — the pair rule, §5.6. Whole-frame
fallback is always the input array, never a modified frame.

### 10.3 Outcome table — the complete message vocabulary

| Situation | `status` | `message` | `eyes` | frame |
| --- | --- | --- | --- | --- |
| `close()` was called | SKIPPED | `engine closed` | () | input |
| frame not `(H,W,3) uint8` | SKIPPED | `unsupported frame` | () | input |
| `frame.shape[:2] ≠ (geometry.height, geometry.width)` | SKIPPED | `geometry mismatch` | () | input |
| `geometry.mirrored` | SKIPPED | `mirrored coordinates` | () | input |
| strength non-finite / outside `[0,1]` | SKIPPED | `invalid strength` (`strength` field 0.0) | () | input |
| `strength == 0` | SKIPPED | `strength 0` | () | input (bit-identical) |
| target zero/non-finite | SKIPPED | `invalid target` | () | input |
| `tracking.gaze is None` or status ≠ `ESTIMATED` | SKIPPED | `no gaze: <gaze status or "missing">` | () | input |
| `status.has_landmarks` False / `iris_available` False | SKIPPED | `no landmarks` / `no iris` | () | input |
| per-eye SKIPPED reasons (§5.3): `no iris`, `degenerate contour`, `eye invalid`, `eye too small`, `eye closed`, `iris implausible`, `negligible displacement`, `iris would leave the eye`, `eye at image border`; two-eye: `eyes overlap`; pairing: `pair skipped: <side> <reason>` | — | (per-eye `reason`) | 2 | — |
| one eye SKIPPED (closed/negligible; any reason when `pair_coupling=False`), other corrected | CORRECTED | `` | 2 | canvas |
| one eye open-unsafe (pair rule) | SKIPPED | `both eyes skipped: right <reason>; left <reason>` | 2 | input |
| both eyes SKIPPED for any reasons | SKIPPED | `both eyes skipped: right <reason>; left <reason>` | 2 | input |
| per-eye `displacement not finite` (§5.3 #7) | FAILED | `<side> displacement not finite` | 2 | input |
| mask generation raised or produced an empty/non-finite mask | FAILED | `mask generation failed: …` | 2 | input |
| remap/compositing raised | FAILED | `compositing failed: …` | 2 | input |
| any other exception, in any phase | FAILED | `engine exception: <Type>: <msg>` | () or 2 | input |

Low confidence is a **policy** outcome (effective strength 0 → `strength 0`);
the engine does not read confidence. Never emit a corrupted result because
correction was requested: every non-CORRECTED row returns the untouched
input.

### 10.4 Logging

The engine logs nothing per frame. The harness logs one line per experiment
and per FAILED frame; M4 adds rate-limited structured events (its concern).

---

## 11. Frame ownership and copy budget

Applies ADR-0003 §5 and the baseline "Frame ownership and copying" section.

| Rule | M3 behaviour |
| --- | --- |
| input immutability | never written; tests assert bitwise equality after `correct()`, on writable inputs too, including after a phase-3 exception raised once the first eye has already been blended into the canvas |
| working copy | **one** `np.array(frame, copy=True, order="C")` per corrected frame, allocated after validation (§10.1); both eyes blend into it via ROI views; ROI-sized scratch buffers (maps, masks, layers) are engine-private and released per call (pooling is M7) |
| zero-copy passthrough | every SKIPPED/FAILED outcome and strength 0 returns the input object (`output.frame is frame`) |
| publication immutability | not the engine's job: the caller re-freezes (`setflags(write=False)`) before publication (M4) — the engine returns a writable canvas so the M4 overlay helper can draw into it **without another full-frame copy**, exactly the baseline's draw-into-owned-canvas plan |
| writable aliases | the engine keeps no reference to the canvas or to ROI views after return; nothing else can alias it |
| nothing outside the opening is written (A1) | after Amendment A1 (§8.7) the iris layer is not wrapped by the outer `alpha`, so this invariant rests on `iris_alpha == 0` wherever `opening_mask == 0`; that is mandatory and separately tested (§15.2), not incidental |
| frozen M2 overlay | untouched; the harness's debug drawing (§13) works on its **own** copy of the corrected frame, so no debug artifact ever shares the engine's canvas |

Per corrected 720p frame: one ≈ 2.8 MB copy plus ROI-scale scratch (tens of
KB). Uncorrected frames: zero copies.

---

## 12. Offline experimentation harness

`gazefix/correction/harness.py`, console script `gazefix-correction-test`,
wrapper `scripts/correction_test.py` — the `validate.py`/`tracking_test.py`
pattern (argparse; lazy imports of OpenCV and the tracker factory inside
`main`; JSON report; exit codes 0/1/2). Development tool only. It reads
files, never a camera, so it does **not** import `gazefix.camera` or export
the capture environment (`--msmf-hw-transforms` is meaningless here and is
not offered). Its `main(argv, tracker_factory=None)` accepts an injected
factory so the CLI is testable with the existing fakes (§15.2).

### 12.1 Inputs

| Flag | Meaning |
| --- | --- |
| `--image PATH` | a still (PNG/JPG). Native size by default; `--canvas WxH [--face-scale F]` embeds it in a canvas like `validate.py` (needed for the small licensed fixture) |
| `--video PATH` | prerecorded short clip, processed **frame by frame, synchronously** (`cv2.VideoCapture` on a file). Justified because the PRD's primary scenario (eyes on the screen below the webcam) can only be captured by the PO on a real webcam, and a 5–10 s clip is the cheapest carrier; it adds one loop and a writer, no threads. `--max-frames`, `--every N` bound the work |
| `--unmirror` | horizontally flip every input frame before tracking. Consumer camera apps often save a *mirrored* preview; the contracts assume the unmirrored camera frame (anatomical sides, yaw sign), so a mirrored recording must be flipped back or every correction goes the wrong way. The PO checks a known asymmetry (readable text, a marked hand) once per capture session |
| `--strength S` | requested strength → policy → effective (default 0.7) |
| `--effective-strength S` | bypass policy; feed the engine directly |
| `--target-yaw DEG --target-pitch DEG` | target direction (default 0, 0 = optical axis). Also the way to **sweep redirection magnitude on any still**: with a near-frontal fixture, `--target-pitch 15` exercises a 15° redirection even though no real deviation exists |
| `--sweep-strength a,b,c` / `--sweep-target-pitch …` / `--sweep-target-yaw …` | produce one output per value plus a labelled contact sheet (`sweep.png`) |
| `--variant layered\|field` | `iris_layer` on/off (§4.2) |
| `--set engine.KEY=V` / `--set policy.KEY=V` / `--set gaze.KEY=V` (repeatable) | override one field of `GeometricCorrectionSettings`, `PolicySettings` or `GazeSettings` by namespaced name (dataclass `replace`, validated). The namespace is required because `GazeSettings` and `GeometricCorrectionSettings` share field names (`eye_model_ratio`, `min_cos`, `min_half_width_px`). Technique/tuning comparison without code changes |
| `--eye-model-ratio K` | **new to this harness** (not a `validate.py` flag); default `AppSettings.gaze_eye_model_ratio` (1.25); written to **both** `GazeSettings` and `GeometricCorrectionSettings` (§6.6) |
| `--stabilizer S` / `--gaze-smoothing S` | video only; default **0/off** for reproducibility (baseline recommendation); when on, the harness owns and resets them at start |
| `--debug` / `--debug-layers L,…` | write `debug.png` / `debug.mp4` (§13), optionally selecting layers, and dump `CorrectionDebug` into the report |
| `--repeat N` | re-run `correct()` N times on the same frame for timing percentiles (§17) |
| `--out DIR --name NAME --label TEXT` | output root (default `experiments/`, git-ignored), experiment name (default `<input-stem>_<timestamp>`), free-text label |
| `--model-dir` | as in `validate.py` |

### 12.2 Outputs (`<out>/<name>/`)

`original.png`, `corrected.png`, `side_by_side.png` (original | corrected,
plus a 3× eye-region crop strip underneath so a 3 px change is visible),
`sweep.png` (when sweeping), `debug.png` (when `--debug`), `report.json`.
Video: `corrected.mp4`, `side_by_side.mp4` (fallback: PNG sequence when no
codec is available on the machine — recorded in the report), `frames.jsonl`
(one line per frame: tracking status, gaze, policy decision,
`CorrectionResult`).

`report.json` records: harness arguments; the **source file name, SHA-256
and dimensions** (so a scored experiment is traceable to its input) and
whether `--unmirror` was applied; all three settings dataclasses as applied
and any `k`/`min_cos` mismatch; tracker description and `init_ms`; frame
geometry; tracking status/quality/eye validity; gaze (status, yaw/pitch,
eye-in-head, confidence and its six terms, `eyes_used`);
`PolicyDecision`; `CorrectionResult` (per eye: status, reason,
displacement, clamped); timings (`correction_ms`, `compositing_ms`,
`CorrectionDebug.stage_ms` when `--debug`, percentiles when `--repeat`);
`gazefix` version; the label. Never frames. Nothing is transmitted
anywhere; PO images stay under the ignored `experiments/` directory (the
repository stores no webcam frames — `tests/assets/README.md` rule).

### 12.3 Tracking/gaze path

Synchronous, on the calling thread: `create_mediapipe_tracker(settings)`
(reached only through the frozen adapter factory; the harness never imports
`mediapipe`) → `tracker.detect(frame, ts)` → largest face →
`validate_landmarks`, `compute_quality`, `extract_eye` ×2,
`head_pose_from_matrix` → assemble a `TrackingResult` with **the worker's
rule** (`worker.py._analyse`): `LOW_QUALITY` if
`quality.in_frame_fraction < tracking_min_in_frame_fraction` (0.9), or
`quality.score < tracking_min_quality` (0.5), or either eye is not `valid`;
otherwise `TRACKED`; `message` carries the joined reasons;
`AnalysisSettings` built from those three `AppSettings` fields → then
`GeometricGazeEstimator(GazeSettings(eye_model_ratio, min_confidence,
smoothing, min_cos)).estimate(result)` → `replace(result, gaze=…)`. This is
the baseline's stated harness shape ("extended to construct and run the
gaze estimator directly"). It duplicates the analysis calls that
`validate.py` also makes and the ~20-line assembly that `worker.py` and
`tests/tracking_fakes.tracked_result` already share; the harness follows
that precedent rather than modifying frozen tracking code (an extraction
helper is an M4 tidy-up candidate, §2.5). The harness imports the engine;
the engine knows nothing of the harness.

### 12.4 Repeatability

One experiment = one directory with its complete `report.json`; the same
arguments on the same input reproduce the same pixels (smoothing off,
deterministic engine — a test asserts it, §15.2). The PO's scoring sheet
(§14) references experiment names.

---

## 13. Visual debug artifacts (development only)

`gazefix/correction/debug.py` (imports cv2; imported only by the harness)
draws onto **its own copy** of the corrected frame, using the library
functions of `geometry.py`/`masks.py` recomputed from the `TrackingResult`
and the `EyeCorrection.displacement_px` — so nothing visualisation-only is
added to the stable contract (the optional `CorrectionDebug` roi/mask
bounds, when present, are cross-checked against the recomputation and
written to the report):

- eyelid contour (cyan R / yellow L, the overlay's anatomical colours);
- source iris circle (white) and destination iris circle (magenta) with the
  displacement arrow;
- blend-alpha iso-lines at 0.1/0.5/0.9 and the ROI rectangle (thin grey);
- sparse warp vectors on a grid inside the opening (from `D(p)`);
- a text panel: per-eye status/reason, displacement px, clamped, aperture,
  half-width, `k`, gain, variant, policy decision, timings.

Optional `--debug-layers` selects layers. These images are for the engineer;
the PO scores `side_by_side.png`, not `debug.png`.

---

## 14. Visual quality gate

M3 is the PRD's major quality gate (§24). The verdict is the **Product
Owner's qualitative judgment**, structured so it is repeatable, budgeted and
honest; no objective pass score is fabricated.

### 14.1 Experiment matrix

Two input classes:

1. **Fixture** (`tests/assets/astronaut_face.png`, public domain, near-frontal,
   small): automated sanity and the engineer's smoke; redirection sweeps by
   target (`--sweep-target-pitch 5,10,15,20,25,30` and yaw likewise) at
   strengths `0.25, 0.5, 0.75, 1.0`, both variants. Its face is only
   ≈ 107 px tall at native size (eyes on the order of 15–20 px wide, at or
   below the engine's minimum), so the harness's canvas mode (face ≈ 190 px,
   eyes ≈ 30 px, the configuration the real-model tests already use) is the
   practical fixture setting — a small, upscaled, blurry case, not a
   representative webcam frame.
2. **PO captures** (local only, never committed), recorded with an
   **external tool** (the Windows Camera app or equivalent) at native 720p —
   the harness has no camera mode — and checked once for mirroring
   (`--unmirror` if needed, §12.1). The fixed set is defined in §14.4: the
   PO looking at (a) the lens, (b) the screen centre, (c) notes at the
   screen's lower edge, (d) horizontally away by a hand's width, under
   **normal lighting**, **with and without glasses**; clips with **minor
   head rotation**, while **speaking/smiling**, and with **blinks/winks/
   closed eyes**. The measured deviations (from `report.json`) are expected
   to land roughly in the 5–30° bands the PRD lists; real deviations are
   scored where they occur and the fixture sweep covers the rest of the
   5°–30° ladder synthetically.

Conditions deferred: low/bright lighting and moderate head rotation are
M4/M5 material unless the PO's captures already show them.

### 14.2 Scoring sheet (per experiment; 1 = unacceptable … 5 = indistinguishable from a real photo)

The PRD §28 dimensions applicable to offline stills and clips, plus the
PRD §29 key criterion:

| Dimension (PRD §28) | Question the PO answers looking at `side_by_side.png` at 100 % and the 3× strip |
| --- | --- |
| eye realism | do the eyes look like eyes, or like edited eyes? |
| iris realism | round, sharp iris/sclera edge, no smear, no double edge? |
| blink realism | on blink/wink/squint/closed frames (stills or clip frames): is the closed eye and its lid untouched, does correction switch off cleanly, and does a one-eye-corrected wink look natural rather than cross-eyed? (feeds Q8: `min_aperture`, `pair_coupling`) |
| eyelid preservation | lids, lashes, lid line unchanged; iris correctly occluded by the lid? |
| identity preservation | still the same person; expression unchanged? |
| artifact visibility | seams, halos, texture smear, moved catchlight, skin bleed, or a stair-stepped or hard iris edge where the iris meets the eyelid line (A1, §8.5)? |
| perceived eye contact | does the corrected image make more eye contact than the original? |
| **key criterion** (PRD §29) | is the correction **less distracting** than the original lack of eye contact? yes / no |

**Temporal stability** (the eighth PRD §28 dimension) is recorded only for
clips, as a free-text note (flicker, oscillation), not as a scored gate
dimension: PRD §12 temporal behaviour is M5's, and the M3 engine has no
temporal state to evaluate. Scores, experiment names, settings and the SHA
under test go into `docs/milestones/m3-evaluation.md`. Fixture-derived
`side_by_side.png` and sweep contact sheets (public-domain source, small)
may be attached there as PRD §25 evidence so the PM can see the effect;
PO-capture renders are never committed and are shown to the PM only at the
PO's discretion, out of band.

### 14.3 Verdict (framework PM-ratified; the per-dimension thresholds below are judgment aids, never objective pass scores)

Evaluate at the **operating range** — measured or synthetic deviations of
10–20° at effective strength 0.5–0.8 — across the PO captures with the
default variant and default settings:

- **`PROCEED`** — the key criterion is "yes" on the clear majority of
  operating-range experiments; no dimension has a *disqualifying* class of
  artifact (a defect visible at normal viewing size that a viewer would
  attribute to editing); eyelid preservation, blink realism and identity are
  not below 4 anywhere. Remaining defects are tuning-class (gain, edge
  width, falloff, clamp, margin, thresholds).
- **`ITERATE`** — the key criterion is "yes" on part of the range or only
  with non-default settings; defects are tuning-class or addressed by a
  designed variant (B↔C, or the deferred TPS field of §4.1 E); the PM sets a
  bounded iteration (one or two harness rounds, sheets prepared by the
  engineer), still within this SA.
- **`CHANGE APPROACH`** — structural defects of the geometric class persist
  at ≥ 10° after both variants and tuning: iris distortion or dead/synthetic
  look, unnatural iris–lid relation for upward correction, or the key
  criterion is "no" across the range. The honest reading is then that
  eye-only warping cannot deliver PRD §29's criterion and the roadmap's M9
  neural evaluation moves earlier — a PM decision, surfaced at the gate,
  never engineered around.

**Two verdicts, per PRD §25.** The M3 engineering report carries both the
*milestone status* — `PASS` / `PASS WITH LIMITATIONS` / `FAIL` for the M3
deliverables (engine, harness, tests built and verified at their stated
levels) — and the *quality-gate recommendation* above. The assignment's
"`FAIL / CHANGE APPROACH`" is the pairing where the deliverables exist but
the geometric class does not meet PRD §29. Verification levels: engine
behaviour is *implementation verified* by the tests; harness runs on the
fixture are *runtime verified*; PO captures are *physical hardware
verified* **for the correction of frames captured by the target device's
webcam, processed offline** — not for the live pipeline, which is M4's.
Anything the PO could not perform is `NOT VERIFIED`.

### 14.4 Product Owner budget (PM-ratified; exceeds qa-policy §9's norm deliberately)

The PO's role is to **capture and score**; the engineer runs the harness
and prepares every sheet.

| Step | What the PO does | Time |
| --- | --- | --- |
| capture | 8 stills — conditions (a)–(d) of §14.1, each with and without glasses — plus 3 clips of 5–10 s: screen centre while speaking/smiling; screen centre with minor head rotation; a blink/wink/squint sequence. Recorded with the Camera app at 720p; one mirroring check | ≈ 10 min |
| hand-off | files placed in the local `experiments/inputs/` (never committed); the engineer runs one documented batch invocation at default settings, producing 8 `side_by_side.png` sheets and 3 corrected clips with reports | 0 (engineer) |
| score | 8 sheets at 100 % with the 3× strip (≈ 2–3 min each) and 3 clips (≈ 5 min each) on the §14.2 sheet | ≈ 35–40 min |
| total | | **≈ 45–50 min**, in one batched session |

This exceeds the 5–10 minute smoke-test norm of `docs/qa-policy.md` §9
because M3 is the PRD's major quality gate; the Product Manager ratified the
budget on that basis at the freeze, so it is planned work rather than a
surprise discovered mid-session.
B-vs-C comparison (`--variant`), `--set` tuning and `pair_coupling`
demonstrations are **not** part of the gate pass: they are ITERATE-round activities the PM
authorises, prepared by the engineer as additional sheets. The step-by-step
checklist (one action, one expected observation per line, the `gaze.md`
§11 style) is written with the implementation, not here.

---

## 15. Automated test strategy (hardware-independent)

Deterministic suite, no model, no camera, no network (the `conftest.py`
guard applies). Fixtures come from **synthetic geometry plus a synthetic
eye renderer**, not image assets.

### 15.1 Fixture strategy — `tests/correction_fakes.py`

- Reuse `gaze_fakes.gaze_scene(...)` / `tracking_fakes.tracked_result(...)`
  for landmark-bearing `TrackingResult`s with known eye-in-head angles and
  head pose; attach a gaze by running the real `GeometricGazeEstimator`
  (smoothing 0) so `gaze` is genuine, not fabricated. Default fixture scale:
  half-width 45 px, iris radius 10.8 px (ratio 0.24), aperture 0.30.
- **Realistic-anatomy variant:** `gaze_scene` hard-codes the iris ring at
  0.12 × eye width, so `correction_fakes` rescales the four iris contour
  landmarks about the centre to `iris_radius ≈ 0.39·half_width` and builds
  the scene with `eye_openness ≈ 0.25`, applied consistently to the
  landmarks and the renderer. This is the fixture on which the containment
  margin, lid-clipped irises and the B-vs-C occlusion behaviour are actually
  reachable.
- `render_eyes(result, geometry) -> frame`: paints a flat skin-tone canvas,
  fills each `opening` polygon with an off-white sclera, draws the iris disc
  (from the iris landmarks) in a dark colour with a black pupil and a small
  fixed catchlight. Deterministic, a few lines of OpenCV. Its value: the
  **iris centroid is measurable** (dark-pixel centroid inside the opening),
  so tests can assert *where the iris actually moved*.
- **Geometric-ideal reference (*A2*).** `visible_centroid_ideal(result, d)`
  computes, from the fixture's own landmarks and with no engine code, the
  area-weighted centroid of `(iris disc + d) ∩ eyelid polygon` — the visible
  iris a perfect renderer would show. Centroid assertions on the clipped
  realistic fixture are made against it, because a lid-clipped iris cannot
  move its visible centroid by the commanded `|d|` (§8.8).
- Golden images are **not** used (brittle across OpenCV builds) — and no
  checksum of the renderer either, for the same reason; the renderer is
  verified by geometric properties (the rendered iris centroid lies at the
  iris landmark centre within 0.5 px).

### 15.2 Test matrix

Tolerances below were derived on the fixtures named above and are stated
per case rather than as one number.

| Area | Test (module) | Asserts |
| --- | --- | --- |
| contract | strength `0.0` passthrough (`test_geometric_engine`) | `output.frame is frame`; `SKIPPED "strength 0"`; `eyes == ()` |
| contract | input not mutated | bitwise equal before/after on a **writable** input, CORRECTED case |
| contract | shape and dtype preserved | `(H,W,3) uint8` out; corrected frame is a distinct array |
| contract | frame-level gates in order | the §10.3 phase-1 rows, each with the input returned and `eyes == ()`; a frame with two faults reports the earlier gate's message |
| contract | `CorrectionResult` semantics (`test_correction_models`) | frozen; `compositing_ms ≤ correction_ms`; messages from the §10.3 vocabulary; `eyes` has exactly two entries (right, left) once per-eye evaluation ran; `strength` echoes valid input and is 0.0 on `invalid strength` |
| contract | repeatability | the same frame and result twice → bitwise identical outputs and equal results |
| mapping | closed-loop, frontal head (`test_correction_geometry`) | scene at eye yaw 15°, target 0, `s=1`: shift the scene's iris landmarks by the engine's `d`, re-run the estimator (smoothing 0) → recovered eye yaw within ~1° of 0; likewise pitch; `s=0.5` → half |
| mapping | closed-loop **under head rotation** (the `Rᵀ` discriminator) | `gaze_scene(head_yaw_deg=20)` and separately `head_pitch_deg=20`, eyes fixating the camera, target = camera-frame yaw +10° (resp. pitch +10°), `s=1`: shift the iris landmarks by `d`, re-estimate → recovered camera-frame gaze within ~1.5° of the target. Using `R` instead of `Rᵀ` rotates the head-frame Δ by ~40° and fails by several degrees. (A Δ≈0 sanity case may be kept with a tolerance derived from the estimator's documented ~1.3° fixating-subject residual — ≈ 1 px at half-width 45 — and is *not* the transpose test) |
| mapping | sign conventions | looking subject's-left (image right) → `dx < 0`; looking down → `dy < 0` (image up); frontal head |
| mapping | eye-size scaling | same scene at `pixels_per_mm` 2 and 4 → `|d|` doubles |
| mapping | clamp | absurd target (`s` forced, 60° away): the geometry helper returns `|d| == max_fraction·half_width` with `clamped=True` (asserted on the helper's return value, since a containment skip that follows would zero `displacement_px` on the result) |
| mapping | no-pose branch | hand-built `ESTIMATED` gaze with `head_pose_applied=False` on `gaze_scene(...).result(with_pose=False)` → `d` equals the frontal-head value, status not FAILED |
| geometry | aperture gate | `left_eye_openness=0.05` → left SKIPPED `eye closed`, right CORRECTED |
| geometry | pair rule | right eye made invalid (contour point outside frame) → both SKIPPED, message `both eyes skipped: right eye invalid; left pair skipped: right eye invalid`; with `pair_coupling=False` → left CORRECTED |
| geometry | containment at realistic anatomy | realistic fixture (§15.1): 10° and 15° upward at `s=1` → CORRECTED (the default `iris_margin_fraction` admits the operating range); a forced **upward** displacement of `0.5·half_width` (the clamp value) → `iris would leave the eye` (a horizontal move of the same size stays clear of the corners and is CORRECTED) |
| geometry | degenerate contour | swap two lid points so the polygon self-intersects while the aperture stays normal → SKIPPED `degenerate contour` on that eye, pair rule → both skipped; collapse the 16 points onto a line → `eye closed` (aperture 0; the other eye may proceed — the accepted reading, §5.3 #2); 468-point result → frame `no iris`; `eyes overlap` on a face shrunk until the polygons' boxes intersect; eye at the image border → `eye at image border` |
| geometry | negligible displacement | `s` tiny → both eyes `negligible displacement`, frame SKIPPED, `output.frame is frame` |
| masks | alpha validity (`test_correction_masks`) | `0 ≤ alpha ≤ 1`, finite; (*A1*) `0 ≤ iris_alpha ≤ 1`, finite — the precondition the §8.4 convexity claim rests on, since A1 makes `iris_alpha` the outermost weight; `alpha == 0` wherever `opening_mask == 0`; `alpha == 1` (within 1e-6) at every interior pixel with `distance ≥ edge_px`; zero-area polygon rejected |
| masks | pixels outside the opening unchanged | for CORRECTED output, (*A1*) `frame[opening_mask == 0] == canvas[opening_mask == 0]` — the invariant §11 actually names, and the selector that stays correct under either permitted `alpha` construction; repeated with a face small enough that the two ROI boxes overlap |
| warp | eye order does not matter (*A1*) | the §8.4 blend helper applied to the two eyes in either order, into copies of the same canvas, gives bit-identical results (asserted at the helper level: the engine's own order is fixed right-then-left by §10.1 and is not a setting) |
| warp | sampling stays inside the opening | with the default precise distance transform and `field_guard_px = 1.5`: for every `p` with `w(p) > 0`, the four pixels of the bilinear footprint of `p − D(p)` have `opening_mask == 1` (§8.2 discrete bound); repeated with a 3×3 chamfer mask and `field_guard_px = 2.5` |
| warp | **exactly one iris (*A2*, primary)** | in the corrected output, every iris-tone pixel inside the opening lies within the destination disc dilated by 1 px — no remnant at the source position. Threshold-free and the primary discriminator of the A2 defect: the v1.1 background fails it on every clipped case, including the horizontal ones where the centroid is insensitive. Run on the realistic fixture, vertical and horizontal, 10° and 15° |
| warp | the iris actually moves — variant C (*A2*) | **default** fixture (unclipped), vertical and horizontal 10° and 15°: visible centroid moves by `d ± 0.5 px` (there the geometric ideal equals `d`). **Realistic** fixture (lid-clipped), same angles: movement is in the right direction and within **[0.85, 1.25] × the geometric ideal** of §15.1. Negative control: the v1.1 background (sampling `roi_src` instead of the plate) scores 0.18–0.29 of ideal on the vertical cases and 0.70–0.81 on the horizontal ones, and must fail every one. The band is **calibrated for these two fixtures only** — §8.8 explains why the ratio is anatomy-dependent — so it is a fixture-bound regression check, not a general acceptance criterion, and the structural row above is what actually pins the defect |
| warp | background carries no iris (*A2*) | the `sclera_plate` contains no iris-tone pixel inside the iris hole (colour test against the renderer's iris tone), and is bit-identical to `roi_src` everywhere outside the hole |
| warp | variant B untouched by A2 (*A2*) | with `iris_layer = False` the output is bit-identical whether or not the plate code path is present: variant B samples `roi_src` |
| warp | plate safety (*A2*) | the plate writes no pixel outside `opening_mask`, and the §8.2 footprint bound still holds when the field samples the plate |
| warp | fill fallbacks (*A2*) | a scan-line whose hole reaches the opening edge on one side replicates the other side; a line with no non-hole interior pixel uses the median interior colour; both exercised deterministically |
| warp | the iris actually moves — variant B | default fixture, horizontal 10°/15° and vertical 10°: `d ± 1 px`; realistic fixture, vertical 15°: correct direction only — variant B compresses the iris against the lid by design (§4.1), so no centroid floor is asserted for it |
| warp | B vs C occlusion | vertical 15° on the realistic fixture: C's visible-centroid displacement exceeds B's by a clear margin, and C keeps iris texture where B compresses |
| warp | iris layer opaque at centre | at the destination iris centre and its 3×3 neighbourhood, output equals `frame(p − d)` within interpolation tolerance (variant C) |
| warp | no ghosting near the lid (*A1*) | vertical move bringing the moved iris under the upper lid: at pixels inside the moved disc (`iris_alpha ≥ 1 − 1e-6`; assert the set is **non-empty** so the row cannot pass vacuously) that lie in the partial-alpha band along the lid (`0.5 < alpha < 1`), output equals `frame(p − d)` within tolerance — the moved iris is not mixed with the unmoved original. **Negative control: the superseded pre-A1 order** (`alpha·(iris_alpha·iris_layer + (1−iris_alpha)·background) + (1−alpha)·canvas`), computed inline in the test, must violate it on at least one selected pixel. (The old `edge_px = 4` control is void under A1 — a wide feather no longer dilutes an opaque iris; `edge_px` is still exercised by the sclera-dilution check below) |
| masks | iris alpha never reaches lid skin (*A1*) | `iris_alpha == 0` at every pixel where `opening_mask == 0`, on both the default and realistic fixtures and for a displacement large enough to push the disc across the contour — the invariant §11 now rests on |
| warp | composite is convex (*A1*) | for a grid of representative `(alpha, iris_alpha)` pairs including the corners, the three weights `iris_alpha`, `(1−iris_alpha)·alpha`, `(1−iris_alpha)·(1−alpha)` sum to 1 within 1e-6 and the output stays within the range of its three inputs (no overshoot, no uint8 clipping) |
| warp | variant B is unchanged by A1 (*A1*) | with `iris_layer = False`, the output equals the pre-A1 formula `alpha·background + (1−alpha)·canvas` bit-for-bit |
| warp | lid-edge aliasing is bounded (*A1*) | opaque disc driven across the upper-lid contour: inside the opening, the largest absolute 4-neighbour difference of the output occurs **only** on the `opening_mask` boundary ring — assert no jump of that magnitude appears more than one pixel inside the ring, and that no pixel outside the opening changes. The test **records** the maximum jump (in the renderer's skin-versus-iris contrast units) as the Q12 measurement; it does not assert a beauty threshold, which is the Product Owner's call |
| warp | partial source coverage (*A1*) | destination pixels whose source footprint `p − d` straddles the source lid contour: `iris_alpha == 0` there by §8.1's conservative all-taps rule, the output equals `base`, and a colour test against the renderer's skin tone finds **no** lid-skin contribution anywhere inside the opening; the cut-off is confined to the source-coverage ring. Negative control: a fractional (plain bilinear) source factor admits up to 25 % skin at a straddling pixel and fails the colour test |
| warp | sclera dilution control (*A1*) | inside the opening, outside the disc, in the partial-alpha band: `edge_px = 4` measurably reduces the background correction against `edge_px = 1.5` — the reason `edge_px` stays small after A1 (§8.4) |
| warp | lid-clipped source iris | source iris partly under the upper lid, horizontal move: no lid-skin pixels appear inside the opening (colour test against the renderer's skin tone) |
| failure | exception fallback, phase 3 | monkeypatch the mask helper to raise → `FAILED "mask generation failed…"`; `cv2.remap` raising → `FAILED "compositing failed…"`; input returned, no exception escapes, `correction_ms` populated |
| failure | exception fallback, phases 1–2 | a geometry/mapping helper raising → `FAILED "engine exception: …"`, `output.frame is frame` |
| failure | failure after the first eye blended | the blend helper raising on its second invocation (the right eye is already composited into the canvas) → `FAILED "compositing failed…"`, `output.frame is frame`, input bitwise unchanged (D8); likewise the left eye's background remap raising after the right eye's layers exist |
| failure | per-eye FAILED | monkeypatch the displacement helper to return NaN → frame `FAILED "<side> displacement not finite"`, both eyes recorded, `pair_coupling` irrelevant |
| policy | curve (`test_correction_policy`) | 0° → 0.3·s, 5–25° → s, 30° → 0.5·s, ≥35° → 0 with `deviation above disable threshold`; confidence ramp; `LOW_CONFIDENCE` → 0 `gaze not estimated`; `m_conf == 0` → `low confidence`; `max_effective_strength` cap |
| boundary | provider-neutral dependency enforcement (`test_correction_boundary`) | walking the **engine and library modules** (`__init__.py`, `models.py`, `engine.py`, `geometry.py`, `masks.py`, `geometric.py`, `policy.py`): no `mediapipe`, no `gazefix.tracking.mediapipe_tracker`, no `PySide6`/`Qt`, no `gazefix.pipeline`, no `gazefix.camera`, no `gazefix.ui`, no `harness`, no `debug`; `engine.py`/`geometric.py` do not import `policy.py`; `models.py` imports contracts + NumPy only; `geometry.py` imports no `cv2`. **`harness.py` and `debug.py`** are the named development-tooling exceptions: they may import `gazefix.tracking.mediapipe_tracker` (factory only), `gazefix.tracking.analysis`, `gazefix.gaze.estimator`, `gazefix.config` and perform file I/O, and are still checked for no `mediapipe`, no Qt, no `gazefix.pipeline`, no `gazefix.camera`, no `gazefix.ui` |
| lifecycle | `reset()` no-op; `close()` idempotent; `correct()` after `close()` → SKIPPED `engine closed`; factory returns a fresh engine | |
| harness | CLI (`test_correction_harness`) with a fake tracker factory injected through `main(argv, tracker_factory=…)` | arguments validated (exit 2), report keys present including source SHA-256, `original.png`/`corrected.png` written, sweep produces N outputs + contact sheet, `--effective-strength` bypasses policy, namespaced `--set` overrides validated, `--unmirror` flips |
| real model (opt-in) | `test_real_model_correction` (`GAZEFIX_REAL_MODEL_TESTS=1`) | fixture in canvas mode → real tracker → estimator → engine → CORRECTED both eyes; iris centroid moves in the requested direction; timings recorded, not asserted |

Determinism: engine math is pure NumPy/OpenCV with no randomness; tests
avoid asserting exact pixel values except through the centroid/unchanged-
region properties above. One full-suite run before handoff (QA policy §6).

---

## 16. Diagnostics

Stable (on `CorrectionResult`, consumed by M4 metrics): `status`, `message`,
`strength` (effective), `correction_ms`, `compositing_ms` (one definition,
§3.2), per-eye `status`/`reason`/`displacement_px`/`clamped`.

Policy (on `PolicyDecision`, harness report now, M4 metrics later):
`requested_strength`, `effective_strength`, `deviation_deg`, `confidence`,
`reason`.

Development-only (harness report / debug image, never on the stable
fields): `CorrectionDebug` (roi, mask bounds, `stage_ms`: copy, warp per
eye, composite) when `debug=True`; harness-computed mask area, ROI size,
aperture, half-width, `R_px`, `k`, gain, variant, percentiles.

M4 extends `PipelineMetrics` in place with `correction_ms` (EMA),
corrected/skipped/failed counters and applied strength (baseline
diagnostics roadmap); M3 adds nothing to `PipelineMetrics`.

---

## 17. Performance considerations

M3 measures; it does not claim.

| Measure | How (harness, `--repeat 50`, medians and p90) | Why |
| --- | --- | --- |
| `correction_ms` total | inside the engine | the number M4 will budget against |
| per-eye warp cost, copy cost, plate build (*A2*) | `CorrectionDebug.stage_ms` with `--debug` | where the time goes; the copy-once budget's actual price at 720p |
| `compositing_ms` | nested, one definition (§3.2) | PRD §21 visibility |
| resolution sensitivity | same still at 640×360, 1280×720, 1920×1080 (`--canvas`) | eye-region work should scale with eye size, the copy with frame size |
| variant B vs C | `--variant` | the price of the iris layer |

Expectation (derived, **not measured**): two `remap`s and a few mask
operations on ≈ 100×60 px ROIs plus one 2.8 MB copy should sit well inside
the baseline's derived 19–27 ms correction budget — but that budget and any
24/30 FPS statement are M4's to verify on the target machine with the live
pipeline; M7 optimises. Offline numbers from the development machine are
reported as such.

---

## 18. Repository structure (smallest that works)

```text
gazefix/correction/__init__.py      package marker; re-exports the protocol, factory type, models (small)
gazefix/correction/models.py        CorrectionStatus, EyeCorrection, CorrectionDebug, CorrectionResult, CorrectionOutput — contracts only
gazefix/correction/engine.py        CorrectionEngine protocol, CorrectionEngineFactory
gazefix/correction/geometry.py      per-eye geometry from EyeLandmarks (axes, aperture, iris circle, ROI), analytic safety checks, gaze→displacement mapping (§5, §6); NumPy only, no cv2
gazefix/correction/masks.py         opening mask, distance field, anti-aliased blend alpha, iris alpha, warp maps, blend helper (§8); cv2 + NumPy
gazefix/correction/geometric.py     GeometricCorrectionSettings (+validated), GeometricCorrectionEngine (validate-then-commit, never-raise, timing), geometric_engine_factory
gazefix/correction/policy.py        PolicySettings, PolicyDecision, resolve_effective_strength (§7)
gazefix/correction/harness.py       offline CLI (§12); development tooling — the only correction module that reaches the tracker factory and estimator construction
gazefix/correction/debug.py         development drawing for the harness (§13)
scripts/correction_test.py          thin wrapper (the existing scripts pattern)
tests/correction_fakes.py           synthetic eye renderer, realistic-anatomy scene variant, result builders (§15.1)
tests/test_correction_models.py     tests/test_correction_geometry.py   tests/test_correction_masks.py
tests/test_geometric_engine.py      tests/test_correction_policy.py     tests/test_correction_boundary.py
tests/test_correction_harness.py    tests/test_real_model_correction.py (opt-in)
docs/correction.md                  implementation reference, written with the code
docs/milestones/m3-evaluation.md    PO scores and gate record (created at evaluation time)
pyproject.toml                      + console script `gazefix-correction-test` (no dependency change)
.gitignore                          + `experiments/`
```

Not created: `correction/neural*`, `output/`, `calibration/`, a compositor
module, a `CorrectionRequest`, a plugin registry. Engine selection by name
is an M4 composition-root concern; M3 exposes one factory.

Dependency direction (baseline diagram): `correction.models →
tracking.models, gaze.models`; `geometry`, `masks`, `geometric` → `models`
+ contracts + NumPy (`masks`/`geometric` also cv2); `policy → gaze.models`;
`harness → everything above + tracking.mediapipe_tracker (factory) +
tracking.analysis + tracking.stabilizer + gaze.estimator + config`; `debug →
geometry, masks, models + cv2`. **Import rules:** nothing imports `harness`; nothing but
`harness.py` imports `debug`; the engine and library modules import neither
and import no backend, camera, pipeline, UI or Qt code. The baseline's
sentence that the correction module "imports no Qt, no pipeline, no camera
code, and performs no I/O" is satisfied by the engine and library modules;
the harness sits inside the package because the baseline's own
repository-structure entry places the "offline harness CLI" there. Tracking
never imports correction.

---

## 19. Dependency decision

**No new runtime dependency.** Everything required exists in the pinned
stack: `cv2.remap`, `fillPoly`, `distanceTransform`, `warpAffine`,
`VideoCapture`/`VideoWriter`, `imread`/`imwrite`, `flip`; NumPy for the
rest (polygon math, blending). Video writing depends on the OpenCV build's
codecs on the PO's Windows machine; the harness falls back to a PNG
sequence and says so in the report — no `imageio`/`ffmpeg` binding is added
for a convenience. No dev dependency is added either (pytest suffices).
Nothing is installed or modified by this SA.

---

## 20. Continuity epoch relevance

The M3 engine carries no temporal state: every `correct()` depends only on
its arguments (the `close()` latch is lifecycle state, not temporal state).
It therefore needs **no awareness** of the reserved tracking continuity
epoch and adds **no temporal-reset machinery**. `reset()` exists on the
protocol (ADR-0002) and is a no-op here; M4's staged processor calls it on
epoch change and on the other reset triggers, which is exactly where a
future stateful engine (or M5 state) would hook in. Nothing in this
contract prevents that: the epoch is read by the caller, not passed to the
engine, so the signature does not change when M4 implements it. The
harness, when smoothing is enabled for a clip, owns and resets the
stabiliser and the estimator itself at start of run.

---

## 21. ADR decision

**No new M3 ADR required.** Every decision above is M3-local (warp
primitive, field definition, mask edge, blend, clamp and margin constants,
the pair rule, policy constants, harness format, debug format, test
fixtures) or a concrete instantiation of ADR-0002/ADR-0003
(`CorrectionOutput` shape, `CorrectionResult` fields, copy-once,
never-raise, no temporal state). Nothing here changes the frozen baseline,
constrains M4–M9 beyond what the baseline already fixes, or resolves a
cross-milestone issue the two ADRs leave open.

Four items are flagged to the PM as *observations*, not amendments:

1. The correction policy function is placed in `gazefix/correction/policy.py`
   (runtime-constants tier) and hosted by the staged processor at M4
   (baseline wording: "policy layer in the staged processor"). Module
   placement only; the engine/policy separation of ADR-0002 §3 is preserved
   and enforced by a boundary test.
2. `eye_model_ratio` and `min_cos` become shared constants between estimator
   and engine (§6.6) — relevant to M6's calibration design.
3. The PRD's primary scenario needs **upward** correction, the direction
   fixed-eyelid warping serves least well (§4.2). This is the substance of
   risks R1/R2 and the reason the gate may say `CHANGE APPROACH`; it is not
   an architecture change.
4. `CorrectionResult.eyes` (per-eye status/reason/displacement/clamped) is a
   small metadata-only addition beyond the fields ADR-0002 §2 enumerates,
   kept because the pair rule makes per-eye outcomes observable behaviour
   (§3.2). No arrays, no change to ADR-0002.

---

## 22. Implementation handoff — what the implementor must not redesign

| Fixed by this SA | Section |
| --- | --- |
| engine boundary, signature, output pair, result fields, never-raise, zero-copy/one-copy rules, gate order | §3, §10, §11 |
| technique: layered eye-region remap with the field-only switch; build order B then C | §4, §8 |
| eye-region geometry, derived quantities, analytic check list and order, pair rule, disjointness, containment margin rationale | §5 |
| gaze → head-frame Δ → per-eye pixel displacement, pose branch, relative application, clamp, gain, shared constants | §6 |
| policy function shape, tier, curve breakpoints as defaults, reasons, harness bypass | §7 |
| mask construction, discrete warp-field bound, iris layer alphas, the two-step blend-into-canvas order (A1), the sclera-plate background and what each variant samples (A2), acceptable-blend definition | §8, §8.7, §8.8 |
| blink/closed-eye rules, no temporal state | §9 |
| failure vocabulary and outcomes | §10.3 |
| harness inputs/outputs/report contents, no camera, unmirror, video justification and limits, injectable factory | §12 |
| debug artifacts recomputed by the harness, `CorrectionDebug` as the only dev carrier | §13, §16 |
| gate matrix, scoring sheet, verdicts, PO budget | §14 |
| test matrix and fixture strategy | §15 |
| module layout and import rules | §18 |

Left to the implementor (ordinary engineering): helper and field names
(the names below are indicative, not binding); polygon smoothing or
`shift`-bit rasterisation; distance-transform mask size; `INTER_LINEAR` vs
`INTER_CUBIC` default after trying both; validation messages; how ROI
scratch buffers are organised; contact-sheet layout; JSON key names; the
choice between `remap` and `warpAffine` for the iris layer; where the
harness draws the 3× crop strip; the point-in-polygon algorithm.

Settings defaults collected (all experimental, `GeometricCorrectionSettings`
— model/engine-constants tier — unless noted): `eye_model_ratio 1.25`,
`min_cos 0.5`, `displacement_gain 1.0`, `max_displacement_fraction 0.5`,
`min_displacement_px 0.25`, `iris_margin_fraction 0.15` (floored at
`edge_px`), `min_half_width_px 8`, `min_aperture 0.18`,
`iris_radius_bounds (0.2, 0.6)`, `min_polygon_area_px 30`,
`padding_fraction 0.25`, `edge_px 1.5`, `falloff_fraction 0.15`,
`distance_transform precise` (`DIST_MASK_PRECISE`; a chamfer mask requires
`field_guard_px ≥ 2.5`), `field_guard_px 1.5`, `iris_layer True`,
`iris_layer_radius_scale 1.05`,
`pair_coupling True`, `interpolation linear`, `debug False`;
`PolicySettings` (runtime-constants tier): `light_factor 0.3`, breakpoints
`(5, 25, 35)°`, `conf_floor 0.35` (seeded from the estimator's
`min_confidence`), `conf_full 0.60`, `max_effective_strength 1.0`.

---

## 23. M4 reuse path

Carried into M4 **unchanged**: `gazefix/correction/{models,engine,geometry,
masks,geometric,policy}.py` and their tests. M4 adds, outside these files:
the staged `FrameProcessor` composition; the `ProcessorOutput`/
`ProcessedFrame.correction` fields; calling `resolve_effective_strength`
then `engine.correct` per frame; `reset()` on continuity-epoch change; the
consecutive-error budget keyed on engine faults (`FAILED` and contained
raises) and its retirement rule; `PipelineMetrics` recorders; the overlay
draw-into-canvas helper; session controls seeded from `AppSettings`
(including `PolicySettings` seeding); factory selection at the composition
root. The harness and `debug.py` remain development tooling and may gain a
`--camera` mode only in M4.

---

## 24. Risks and unresolved questions (need implementation evidence)

| # | Risk / question | Why it is uncertain | Where it is resolved |
| --- | --- | --- | --- |
| Q1 | **Upward correction realism with a fixed upper lid** (the primary scenario) | no geometric candidate moves lids; subtlety at 10–20° is expected, not shown | gate §14 (operating range, variant C vs B) |
| Q2 | **Visibility at webcam eye sizes**: 3–7 px moves at 720p; interpolation blur of a 25-px-wide eye | derived from the model; may look like nothing, or like blur | fixture sweeps + PO captures; `INTER_CUBIC` trial |
| Q3 | **Mis-targeting from the ±10° gaze error** and the optical-axis zero reference | relative displacement tolerates gain error, but the *direction* of `Δ` inherits the estimate's error; a corrected eye may look past the lens | PO "perceived eye contact" score; informs M6 |
| Q4 | **Catchlight moves with the iris** (variant C) | real corneal reflections stay near the light; a moved highlight may read as "glassy" | gate; a highlight-preserving background layer is a possible ITERATE variant |
| Q5 | **Sclera stretch texture** near corners at yaw correction; blood vessels/pink canthus smear | analytic field may compress visibly at 20–30° | gate; escalation to TPS field (E) if needed |
| Q6 | **Glasses**: frame edges inside the opening are warped; reflections degrade iris landmarks | uncharacterised (M2 note) | PO glasses condition |
| Q7 | **Iris landmark accuracy when clipped by the lid** (MediaPipe predicts the full circle) | plausibility bounds may reject valid eyes or accept poor ones | fixture + PO captures; threshold tuning |
| Q8 | `min_aperture 0.18` and the pair-coupling default | chosen, not measured | blink-realism score on wink/squint frames; ITERATE sheets |
| Q9 | Video writer codec availability on the PO's Windows OpenCV | build-dependent | harness fallback to PNG sequence |
| Q10 | Whether the result assembly the harness repeats from `worker.py` should become a tracking helper | touches frozen M2 code | M4 tidy-up candidate; not M3 |
| Q11 | `iris_margin_fraction 0.15` (and the point-containment form of the check) at real fissure heights | sized by arithmetic (§5.3), not by captures; too large excludes the upward range, too small lets the iris centre reach the lid line | realistic-anatomy tests + PO captures; area-based check as ITERATE option |
| Q13 | **synthetic sclera where the iris used to be (A2, §8.8)**: the plate's fill is interpolated, not real sclera, so it can read flat or slightly banded beside genuine sclera, most visibly on a large correction that uncovers much of it | the fill is cheap and deterministic by design; whether it is convincing on a real eye at 720p is unmeasured | §15.2 plate tests bound its extent; scored under iris/eye realism and artifact visibility at the gate (§14.2); a textured or inpainted fill is an ITERATE option with evidence |
| Q14 | **flattened trailing edge of an upward-moved iris (A2 + A1)**: the conservative source-coverage rule drops a thin crescent (≈ 1.9 px on the fixture) whose source lay under the lower lid, so the moved iris can show a slightly flat bottom and the measured centroid sits just above the geometric ideal | the missing content genuinely does not exist in the source; synthesising it would be invention | the §15.2 ideal band's upper bound keeps it honest; PO scores it under iris realism |
| Q12 | **lid-edge aliasing of the opaque iris after Amendment A1** (§8.7): the iris-to-skin transition at the eyelid contour is now governed by the binary destination mask, so it can stair-step by one pixel where the opaque disc crosses the lid | the trade was taken deliberately — smoothing it with the anti-aliased `alpha` would make the no-ghosting test vacuous; whether one pixel of step is visible at 720p on a real face is unmeasured | bounded by the §15.2 aliasing test; scored under artifact visibility at the gate (§14.2); an ITERATE-round fix with evidence if the PO sees it |

None of these is an architecture blocker. The frozen baseline created no
M3 blocker in this analysis.

---

## 25. Self-review against the assignment

| Check | Result |
| --- | --- |
| satisfies PRD M3 outcome (visible redirection, configurable strength, soft blending, before/after; major gate) | yes — §4, §6, §8, §12, §14 |
| conforms to `architecture-v1` (Part II M3 section, contracts, ownership, failure domains, dependency direction, structure, configuration tiers) | yes — referenced throughout; no restatement |
| does not amend ADR-0002/0003 silently | yes — §21 lists four observations; the protocol, output pair, policy-outside-engine, engine-owned compositing, copy-once and never-raise are instantiated, not changed |
| no MediaPipe in correction | yes — the engine and library modules import no backend (boundary test §15.2); the harness reaches the tracker only through the frozen adapter factory and never imports `mediapipe`; landmark topology comes from `gazefix.tracking.landmarks` constants |
| remains offline | yes — harness is synchronous, file-based, no camera; §1.2, §12 |
| no M4 realtime integration, no M5 stabilization, no M6 calibration, no M8 backend, no M9 model/runtime | yes — §1.2, §9, §19, §20 |
| no unnecessary dependencies | yes — §19 |
| not over-engineered for a DIY prototype | one engine, two switchable variants, ~8 small modules, a CLI; no compositor, registry, plugin system or pooling |
| credible reuse path into M4 | yes — §23 |
| frozen architecture blocker? | none found; four observations flagged in §21 |
