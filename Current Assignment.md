# GazeFix — Current Engineering Assignment

**Active milestone: M2 — Gaze Estimation**

**M0 status: PASS / CLOSED / FROZEN**

**M1 status: PASS / CLOSED / FROZEN**

**Assignment date: 2026-09-04**

## Authority and roles

`01-GazeFix-Product-Requirements-Document-v1.1.md` remains the unchanged higher-level source of truth for product scope, requirements, constraints, and milestone gates. This document defines the currently authorized engineering work and nothing beyond it. Where the PRD orders milestones, this assignment advances the active milestone after the previous gate closed; it does not change product requirements. If a material conflict appears, escalate it instead of editing the PRD or silently changing scope.

- ChatGPT: Product Manager / Technical Lead; scope, acceptance, and milestone decisions.
- Mohammad Iqbal: Product Owner; final product decisions and target-device (Windows/webcam) verification.
- Claude Code: implementation engineer and self-review.

Workflow for M2: assignment → implementation with self-review → automated verification → Product Owner Windows/webcam smoke test → Product Manager gate decision → authorized merge. There is no automatic progression to M3.

**Independent external AI QA (Kimi, Codex, or any other reviewer) is not part of this assignment.** The M1 multi-reviewer loop is retired for M2. Escalate to the Product Manager only for a specific unresolved or high-risk concern.

## Frozen milestone state

| Item | Value |
| --- | --- |
| Frozen M0 baseline (`milestone-0`) | `3b0a2eee8b0fc207875702250955e78173857957` |
| Frozen M1 baseline (`milestone-1`) | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` (M0 merge; contains no M1 work) |
| M1 merge | PR #4, `claude/m1-face-eye-tracking` → `milestone-1` |

`milestone-0` and `milestone-1` are frozen. Do not advance, rewrite, force-push, or merge into either of them, and do not modify `main`. Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()` bootstrap case documented in `docs/architecture.md`) remains accepted and out of scope; its stated reopening triggers are unchanged. New regressions introduced by M2 are not covered by that exception.

### What M1 already provides (M2 inputs, not M2 deliverables)

`gazefix.tracking` delivers, per captured frame, an immutable `TrackingResult` tied to `capture_sequence`, `captured_at_ns` and `camera_request_id`:

- 478 normalised face landmarks (`landmarks`) in unmirrored-frame coordinates,
- per-eye `EyeLandmarks` with a 16-point eyelid contour, optional 5-point `iris`, `openness`, `width_px`, `valid`, anatomical `side`,
- `iris_available`,
- `HeadPose` (`yaw_deg`, `pitch_deg`, `roll_deg`, `rotation`, `translation`) — **head orientation only**,
- `TrackingQuality` (a documented geometric availability heuristic, explicitly not a model probability, with `backend_thresholds`),
- `TrackingStatus`, `TrackingTiming`, `FrameGeometry`, `mirrored()`, `belongs_to()`.

Conventions are documented in `docs/tracking.md` and `gazefix/tracking/models.py`. M2 consumes this contract; it does not redesign it. Changes to M1 modules are allowed only where M2 genuinely requires them, must be minimal, and must keep every existing M1 test passing.

## M2 goal

Estimate the user's **approximate eye gaze direction** from the tracking information M1 already produces, and expose it through a stable, replaceable interface.

Minimum output per frame (PRD PR-4, M2):

```text
gaze yaw
gaze pitch
confidence
```

The estimator does not need laboratory-grade eye tracking. Its purpose is to estimate **how far the user's eyes are looking away from the camera**. Calibration is explicitly not required in M2.

### The critical semantic distinction

M1 already exposes head pose. **M2 gaze yaw/pitch must represent eye/gaze direction. Renaming, re-exporting, or thinly wrapping head-pose yaw/pitch is not an acceptable M2 deliverable.**

Head pose may be used as an input or reference where technically justified (for example to convert eye-in-head rotation into a camera-relative gaze direction, or to bound validity at extreme head angles), but estimated gaze must remain a distinct semantic output with its own derivation, its own conventions, and its own confidence.

Keep these three concepts clearly separated in code, documentation, overlay, and reporting:

```text
head pose        head orientation relative to the camera            (M1, HeadPose)
eye/iris geometry iris position and eyelid geometry within the eye  (M1, EyeLandmarks)
estimated gaze   where the eyes are looking, relative to the camera (M2, this milestone)
```

A gaze result that is numerically indistinguishable from head pose across eye movement is a failed M2, regardless of test counts.

## In scope

1. **Stable gaze-estimation interface and data structures.** A small, immutable, frame-identified gaze result contract, plus an estimator boundary (a Protocol or equivalent) so M3+ depends on the contract rather than on one specific algorithm. Keep the gaze result tied to the same frame identity M1 uses (`capture_sequence`, `captured_at_ns`, `camera_request_id`) so a gaze result can never be paired with a different frame or camera generation.
2. **Approximate gaze yaw.** Derived from eye/iris geometry, optionally combined with head pose.
3. **Approximate gaze pitch.** Same derivation discipline; eyelid aperture must not be silently mistaken for downward gaze without stating the limitation.
4. **Truthful confidence.** A documented value in `[0, 1]` with stated provenance, computed from measurable inputs (for example iris availability, eye openness, eye validity, M1 tracking quality, landmark in-frame fraction, head-pose plausibility, left/right eye agreement). **Do not fabricate a model probability the implementation cannot justify.** If a factor is a heuristic, label it a heuristic exactly as `TrackingQuality` does.
5. **Use of M1 data as appropriate.** Iris centre relative to eye-socket/corner geometry, eyelid contour, head pose, and tracking quality are all available. Choose the smallest derivation that produces a usable, defensible estimate, and record why.
6. **Graceful unavailable / low-confidence behavior.** Explicit states for: no face, low tracking quality, missing iris landmarks, closed or blinking eyes, one eye unusable, head pose outside the range where the estimate is meaningful, and estimator error. These must be representable and distinguishable.
7. **Temporal behavior only where necessary** to make estimator output usable (for example damping iris jitter into a stable yaw/pitch). Any smoothing must be justified, bounded, reset on face loss / re-acquisition / camera-generation change, and must not add stale-frame latency or hide loss of tracking.
8. **Development/debug visibility.** Extend the existing developer-mode overlay and/or diagnostics to show gaze yaw, pitch, confidence and status, drawn so it is visually distinguishable from the existing head-pose axes and clearly labelled. Overlay off must preserve original frame pixels exactly; shared capture buffers must never be mutated.
9. **Hardware-independent automated tests** (see *Required automated verification*).
10. **A targeted Windows physical-webcam verification plan** the Product Owner can execute in a few minutes (see *Required Product Owner runtime verification*).
11. **Diagnostics/latency measurements relevant to gaze estimation**: gaze-estimation cost, its boundary within the existing processing timing, and its effect on the pipeline.
12. **Documentation** of gaze coordinate and sign conventions, the derivation, the confidence formula and its provenance, and the estimator's limitations. Extend `docs/` (a `docs/gaze.md` alongside `docs/tracking.md` is the expected shape) and add a short ADR if a non-obvious approach or dependency is chosen.

## Explicit non-goals

Do **not** implement, scaffold, or add dependencies for:

- **Gaze correction** — no eye warping, redirection, correction strength, correction masks, blending, or any modification of eye pixels. Drawing the debug overlay is allowed.
- **Eye-region warping** of any kind.
- **Compositing** of corrected or synthesized eye regions.
- **Calibration** — no calibration workflow, states A–D, profiles, per-user camera/screen mapping, or calibration UI. Explicitly not required in M2.
- **Virtual camera** — no output backend, driver, pyvirtualcam, OBS, or conferencing-client integration.
- **Neural gaze-redirection models**, model training, dataset collection, or gaze-regression network adoption.
- **ONNX Runtime** and **DirectML** — do not adopt either in M2.
- **Interview, teleprompter, or LLM features.**
- **Cloud processing**, remote inference, telemetry, or any upload of webcam frames or derived biometric data.
- **M3 or any later milestone work**, including preparatory scaffolding for correction, stabilization systems, performance projects, installers, or productization.
- Unrelated refactoring, and reopening accepted M0 debt outside its stated triggers.
- Editing the PRD. Modifying, committing on, pushing to, or merging into `main`, `milestone-0`, or `milestone-1`.

## Technical and product constraints

**Platform and hardware.** Preserve Python 3.11+ and Windows 10/11 support, local-only processing, and a working CPU path on the target Intel i7 / Iris Xe class laptop. No NVIDIA, CUDA, NPU, Windows Studio Effects, or cloud dependency. Normal runtime must work offline with the existing local model asset present.

**Architecture.** Prefer the smallest architecture that preserves future replaceability.

- Keep the gaze estimator free of MediaPipe, Qt, and OpenCV-GUI imports so it stays testable with plain fixtures, exactly as the M1 non-backend modules are.
- Integrate through the existing processing seam. Capture, inference, and blocking work stay off the Qt UI thread; widgets are touched only by the UI thread.
- Preserve immutable frame ownership, camera-generation filtering, latest-frame behavior, bounded buffers, bounded recovery, and the existing clean-shutdown and camera-release behavior.
- The estimator boundary must be narrow enough that a different gaze algorithm (geometric, model-based, or neural in a later milestone) can replace it without changing consumers.

**Fallback and stream continuity.** Per PRD §13, a failure in gaze processing must never freeze or interrupt video. If gaze cannot be estimated reliably, publish an unavailable or low-confidence gaze result and keep the frame flowing. Stale gaze results must be cleared on face loss and camera change; no gaze value may remain attached to a new face or a new camera generation. Recovery must be bounded — no per-frame error or retry storms.

**Conventions must be explicit.** Document, in code and in `docs/`, the gaze coordinate frame and what positive and negative yaw and pitch mean, in the same style as the M1 head-pose table:

```text
gaze_yaw_deg  > 0 → <state precisely which physical direction, e.g. the subject looks toward their own left>
gaze_pitch_deg > 0 → <state precisely, e.g. the subject looks upward>
```

State the reference direction (camera optical axis = zero), the units (degrees), the mirroring behavior (what `mirrored()` must do to gaze), and how each sign was verified. Where a sign is reasoned rather than physically observed, say so, as M1 did for head pitch.

**Honesty.** No invented confidence, no invented benchmark numbers, no claiming a verification level that was not reached. Unmeasured values are `NOT MEASURED`.

**Dependencies.** Add a dependency only if M2 genuinely needs it, and prefer none. If one is proposed, record source, version, active status, Windows/Python compatibility, CPU support, and code and model licences separately, and escalate material licensing, privacy, hardware, or paid/cloud implications with Problem / Options / Trade-offs / Recommendation. ONNX Runtime and DirectML are out of scope for M2 regardless of justification.

**Performance.** PRD MVP/M7 targets (720p, ≥24 FPS, <100 ms processing latency) remain product targets and are not newly imposed M2 gates. Measure at 1280×720 where supported and flag any regression against the recorded M1 baseline. Do not silently redefine product targets or claim them from a mock benchmark.

## Acceptance criteria

- **AC1 — Gaze output exists and is distinct.** Every processed frame yields a gaze result carrying yaw, pitch, confidence and status, tied to that frame and camera generation. Gaze yaw/pitch are demonstrably derived from eye/iris geometry: with head pose held fixed, changing iris position changes gaze; the output is not a copy or trivial transform of head-pose yaw/pitch. This is demonstrated by test, not asserted.
- **AC2 — Documented conventions.** Gaze coordinate frame, sign conventions, units, zero reference, mirroring behavior, derivation, and known limitations are documented and exercised by tests. Head pose, eye/iris geometry, and estimated gaze are clearly distinguished everywhere they appear.
- **AC3 — Truthful confidence and availability.** Confidence is in `[0, 1]` with a stated formula and provenance, and moves in the documented direction as its inputs degrade (missing iris, closed eye, low tracking quality, one eye unusable, extreme head pose). No fabricated model probability. Unavailable and low-confidence states are explicit and cannot be mistaken for a valid estimate.
- **AC4 — Graceful fallback and continuity.** No face, face exit and re-entry, blink and eye occlusion, missing iris, tracker error, low quality, and camera switching all produce an explicit unavailable/low-confidence result while preview keeps running. Stale gaze never survives a face loss or a camera-generation change. Recovery is bounded.
- **AC5 — Stable, replaceable boundary.** The gaze contract and estimator boundary are small, immutable, frame-identified, and free of backend/UI coupling. A substitute estimator can be plugged in under test without changing consumers.
- **AC6 — Pipeline health preserved.** Gaze estimation adds no unbounded queue, no growing latency, and no regression in latest-frame behavior, UI responsiveness, camera Refresh/selection, clean close, or camera release. Debug overlay off leaves original pixels unchanged; shared buffers are never mutated. Gaze-estimation timing is measured and reported with defined boundaries.
- **AC7 — Evidence and scope.** The full automated suite passes on the tested HEAD, Windows/physical evidence is reported honestly at the correct verification level, and the complete diff respects every M2 non-goal. Unverified required runtime items prevent an unconditional PASS.

## Required automated verification

Tests must be deterministic and hardware-independent: the default suite must not need a webcam, a network, or a model download. Keep explicitly-invoked real-backend/model tests separate from fake-based tests, and mark unavailable integration requirements accurately. Prefer events and fakes over sleep-sensitive timing.

Cover at least:

1. **Derivation and independence** — synthetic landmark/eye fixtures where iris position varies with head pose fixed (gaze must change) and where head pose varies with eye-in-head geometry fixed (gaze must respond in the documented, justified way, and must not simply equal head pose).
2. **Sign and convention tests** — a left-looking fixture yields the documented yaw sign, an up/down-looking fixture the documented pitch sign; mirroring a result flips gaze yaw consistently with the documented convention and leaves pitch unchanged.
3. **Magnitude sanity** — looking at the camera yields yaw and pitch near zero within a stated tolerance; a clearly averted-gaze fixture yields a clearly larger deviation. Ordering and rough scale, not laboratory accuracy.
4. **Confidence behavior** — missing iris, closed/blinking eye, one invalid eye, low `TrackingQuality`, and out-of-range head pose each lower confidence or force unavailable, in the documented direction. Confidence stays within `[0, 1]`.
5. **Unavailable paths** — `NO_FACE`, low-quality, missing-iris, and estimator-exception inputs produce explicit unavailable/low-confidence results and never raise into the pipeline.
6. **Frame identity and staleness** — gaze results carry the correct `capture_sequence` / `camera_request_id`; results from a previous generation are rejected; face loss and camera change clear any temporal state.
7. **Temporal behavior**, if implemented — smoothing converges, resets on loss and generation change, and does not publish a value derived only from stale frames.
8. **Boundary substitutability** — a fake estimator satisfies the contract and drives consumers correctly.
9. **Overlay and ownership** — gaze overlay draws only in developer mode, leaves input pixels unmodified when off, and does not mutate shared buffers.
10. **Regression** — the entire existing M0/M1 suite continues to pass unchanged.

Run focused tests while iterating and the **full suite once on the final HEAD before handoff**. Report the exact commands, environment, versions, and pass/fail/skip counts with reasons for skips. Do not delete or weaken an existing test to hide a regression. The historical M1 suite size is a baseline, not a target number.

## Required Product Owner runtime verification

A short Windows/webcam smoke test on the Product Owner's laptop, targeted at gaze estimation. Provide exact commands and an expected-result checklist. Keep it to a few minutes.

1. Launch in developer mode with the overlay on; confirm startup, responsive GUI, live preview, and a gaze readout appearing alongside the existing tracking overlay.
2. **Look directly at the camera** — gaze yaw and pitch should sit near zero and be reasonably steady; confidence should be high.
3. **Look left, then right, without turning the head** — yaw should move in the documented direction and return toward zero. This is the primary check that gaze is not head pose.
4. **Look up, then down, without moving the head** — pitch should move in the documented direction.
5. **Turn the head while keeping the eyes on the camera** — record what the estimator reports; confirm it matches the documented behavior and does not simply track the head.
6. **Blink, close the eyes, cover one eye, leave the frame and return** — confirm confidence drops or gaze reports unavailable, that the preview never freezes or corrupts, and that stale gaze does not persist after re-entry.
7. **Refresh / switch camera where available, then close** — confirm stale gaze clears, shutdown is clean, and the physical camera is released.
8. Record capture FPS, display FPS, gaze-estimation latency, total processing latency with stated boundaries, resolution, camera/backend, and hardware. Use `NOT MEASURED` where a value was not taken.

Mark each item `VERIFIED` / `NOT VERIFIED` / `FAILED` and state its level: implementation verified, runtime verified, or physical hardware verified. A Windows import is not GUI verification; non-Windows execution is not Windows verification; mock tests are not physical webcam verification. Do not record or transmit webcam frames by default.

## Lean QA policy

This project is a solo/DIY MVP. **QA must be proportional to risk.** Do not design a release-certification process.

Engineering verification is, in order:

1. targeted unit tests,
2. relevant integration tests,
3. the full automated suite once before handoff,
4. a short Product Owner Windows/webcam smoke test.

Explicitly **not** required for M2:

- independent external AI QA,
- bespoke QA harnesses or reusable test infrastructure, unless the implementation itself genuinely requires them (say why if you build one),
- extended forensic, soak, endurance, network, or security testing, unless a concrete M2 risk requires escalation — in which case state the risk first,
- formal sign-off documents, certification matrices, or process artifacts beyond the report below.

Depth belongs in the derivation, the conventions, the confidence honesty, and the fallback behavior — not in process volume.

## Branch and base information

| Item | Value |
| --- | --- |
| Base (frozen M1 HEAD) | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| Implementation branch | `claude/m2-gaze-estimation` |
| Branched from | `milestone-1` at the frozen HEAD above — **not** from `main` |
| M2 integration branch | `milestone-2`, to be created from the frozen M1 HEAD at implementation kickoff |
| Implementation PR target | `milestone-2` — never `main`, `milestone-0`, or `milestone-1` |

Rules:

1. Before implementing, fetch remotes, inspect status, history, and applicable repository instructions, and preserve unrelated work. Never reset or clean another party's working tree.
2. This preparation commit changes only `Current Assignment.md` and contains **no M2 implementation code**.
3. At kickoff, record the assignment commit SHA, create `milestone-2` from `097c4d69b9e7c7e8a2772445315ccb51a263dca7`, and continue implementation on `claude/m2-gaze-estimation`. If a branch already exists, inspect its ancestry and purpose before adopting it; do not overwrite or silently adopt conflicting work.
4. Commit focused work with clear messages. Do not force-push, rewrite existing history, or merge the implementation PR — the Product Manager and Product Owner decide the gate.
5. `main`, `milestone-0`, and `milestone-1` must remain untouched.

## Milestone gate reporting format

At the end of M2, return the following sections, then stop:

1. **Status** — delivery status `READY FOR REVIEW` or `BLOCKED`; milestone recommendation `PASS` / `PASS WITH LIMITATIONS` / `FAIL` using the PRD §25 definitions. The Product Manager makes the decision. Explain any incomplete acceptance item.
2. **Branch and provenance** — frozen M1 SHA, assignment commit SHA, integration branch and starting SHA, implementation branch, tested final HEAD, PR number/link, and target branch.
3. **Implemented gaze behavior** — the derivation in plain terms, the output contract, coordinate and sign conventions, the confidence formula and its provenance, unavailable/low-confidence states, temporal behavior, and the important changed files.
4. **Head pose vs. gaze** — concrete evidence that gaze is a distinct semantic output and not renamed head pose, including which tests demonstrate it.
5. **Architecture and lifecycle** — estimator boundary and why it is replaceable, seam integration, threads, frame ownership and generation filtering, state reset, and fallback/continuity behavior.
6. **Acceptance and verification matrix** — AC1–AC7 mapped to evidence, verification level, and `VERIFIED` / `NOT VERIFIED` / `FAILED`; focused and full-suite commands and results; Windows GUI, physical camera, and release checks reported separately; exact tested HEAD and environment.
7. **Performance and diagnostics** — gaze-estimation latency, total processing latency with boundaries, FPS, frame replacement, and resource observations, with sample conditions and resolution; `NOT MEASURED` where unavailable; comparison against the M1 baseline and any regression.
8. **Self-review** — concurrency, lifecycle, stale-result, coordinate/sign, confidence-honesty, failure-path, dependency, regression, and scope review, with outstanding findings, severity, and evidence. Do not invent independent QA.
9. **Known limitations** — what the estimator cannot do without calibration, accuracy bounds, conditions where it degrades (glasses, lighting, extreme angles, eyes closed, no iris), and what is deferred to later milestones.
10. **Scope confirmation** — no gaze correction, eye warping, compositing, calibration, virtual camera, neural gaze redirection, ONNX Runtime, DirectML, interview/teleprompter/LLM features, cloud processing, or M3+ work; no PRD change; `main`, `milestone-0`, and `milestone-1` untouched.
11. **Merge state** — PR NOT MERGED.
12. **Recommendation and next step** — `PROCEED` / `ITERATE` / `CHANGE APPROACH` with rationale, plus the remaining Product Owner checks required before an authorized merge.

A full-suite failure prevents `READY FOR REVIEW` as a passing delivery; report any environment blocker explicitly rather than hiding omitted tests. Do not merge, declare M2 closed on behalf of the Product Manager, or begin M3.
