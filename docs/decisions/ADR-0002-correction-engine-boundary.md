# ADR-0002: Correction is a separate engine stage; gaze estimation stays with tracking

**Status:** proposed at the overall architecture pass (2026-09-04), awaiting
Product Manager architecture review. **Decides:** the boundary of the gaze
*correction* engine for M3 onward, how it relates to the gaze *estimation*
stage that M2 already shipped, and who owns compositing.

## Context

PRD §15 requires a stable model interface so GazeFix is never permanently
tied to one gaze-correction implementation, and sketches — explicitly
"conceptually" — one `GazeCorrectionEngine` class bundling `initialize`,
`estimate_gaze(frame, landmarks)`, `correct(frame, landmarks, source_gaze,
target_gaze, strength)`, and `shutdown`.

The frozen M2 system already ships gaze estimation as its own stage: the
`GazeEstimator` protocol (`estimate(TrackingResult) -> GazeResult`,
`reset()`, `description`) is implemented by `GeometricGazeEstimator`, owned
and called by tracking's `TrackerWorker` on the tracker thread, with its
result embedded in `TrackingResult.gaze` carrying the frame's identity, its
temporal state reset with the tracker's own, and its failures contained by a
budget deliberately separate from the tracker's rebuild budget (the
ARCH-01/ARCH-02 fixes). Adopting the PRD sketch literally would either
duplicate that shipped stage inside a correction engine or leave
`estimate_gaze` a dead method — and a single engine object would span two
threads' ownership rules, because correction will run on the processing
worker while estimation runs on the tracker thread.

M3 (offline correction prototype) needs the engine interface fixed now, so
the prototype is the production engine exercised offline rather than a
throwaway.

## Decision

1. **Gaze estimation stays owned by tracking.** The `GazeEstimator` seam and
   `TrackingResult.gaze` are unchanged. PRD §15's intent — a stable,
   swappable model interface covering estimation and correction — is
   satisfied by the *pair* of seams (`GazeEstimator` + `CorrectionEngine`),
   not by one bundled class.

2. **A `CorrectionEngine` protocol** is created in M3 under
   `gazefix/correction/`, following the proven `FaceTracker`/`GazeEstimator`
   pattern:

   ```text
   description                      one line naming the engine, for logs/overlay/UI
   correct(frame, tracking, target, strength) -> CorrectionResult
   reset()                          drop temporal state (face/camera change)
   close()                          release resources; idempotent
   ```

   plus a factory (`CorrectionEngineFactory`) invoked on the owning thread.
   Inputs: the immutable captured frame, the frame's `TrackingResult`
   (which already carries landmarks, eyes, iris, head pose and the source
   gaze), the target gaze as a unit direction in the `GazeResult` camera
   frame (default `(0, 0, 1)`, the camera), and the **effective** strength
   in `[0, 1]`. Output: a `CorrectionResult` — status `CORRECTED` /
   `SKIPPED(reason)` / `FAILED(reason)`, the output frame (the engine's own
   working copy when corrected, otherwise the input reference), applied
   strength, `correction_ms`, optional debug metadata. Strength `0` is a
   guaranteed no-op passthrough; interpolation is required (PRD §9),
   binary correction is not acceptable.

3. **Policy sits outside engines.** The deviation-dependent strength curve
   (PRD §10), confidence gating, and fade ramps are a policy layer in the
   staged processor that turns requested strength into effective strength.
   Engines implement geometry, not product behavior, so the curve stays
   tunable without touching any engine.

4. **The engine owns masks and compositing** and returns a complete
   corrected frame. Mask/blending helpers are shared library code inside
   `gazefix/correction/`; a separate compositor *stage* is not created.

5. **Failure semantics repeat the M2 lesson.** The protocol documents
   never-raise (unusable input becomes a `SKIPPED`/`FAILED` result with a
   reason), and the caller contains a raising engine anyway: correction has
   its own consecutive-error budget and retirement (until camera-generation
   change or the user toggles correction), and its failures never spend the
   tracker's or the gaze stage's budgets. The original frame always passes
   through.

6. **Thread ownership.** The engine is created, called, `reset` and
   `close`d on the processing worker (M4). In M3 the same engine runs
   synchronously in an offline harness; the engine itself is
   thread-agnostic, single-threaded-by-contract like `FaceTracker`.

7. **Neural engines (M9) plug in behind this same protocol.** One adapter
   module is the only importer of ONNX Runtime (the `mediapipe_tracker.py`
   pattern); tensors and providers never cross the protocol. A neural model
   that estimates gaze internally does not displace `TrackingResult.gaze`;
   if M9 evidence shows a compelling model that genuinely requires its own
   estimation path, that is a new ADR then.

## Consequences

- M3 builds the production engine module and an offline harness around it;
  M4 wires the identical engine into the live processor. No rewrite between
  the two milestones.
- The correction engine never sees Qt, the pipeline, the camera layer, or
  backend types; it consumes frozen contracts (`TrackingResult`,
  `GazeResult`) plus NumPy, so it is testable exactly like the estimator.
- `estimate_gaze` does not exist on the engine; a reviewer comparing to PRD
  §15 must read this ADR for why (the PRD marks its interface conceptual,
  and the PM review of this pass is the approval gate for the deviation).
- Engines cannot influence *whether* they run (policy decides), which keeps
  degraded states (low confidence, fade-out) consistent across engines.
- The compositor decision (engine-internal) means engine implementations
  carry blending quality; if M9 shows multiple engines duplicating
  substantial blending logic, promoting the shared helpers into a stage is
  a contained refactor behind `CorrectionResult`.

## Alternatives considered

- **Literal PRD §15 interface (bundled estimate + correct):** duplicates
  the shipped, tested M2 estimation stage or leaves a dead method; spans
  the tracker and processor threads' ownership rules; couples the
  estimator's confidence/status contract (which the UI and policy already
  consume) to engine choice. Rejected.
- **Separate compositor stage with a patches+masks contract:** a second
  abstraction with a single caller and a speculative contract; constrains
  engine internals prematurely (a warp that blends progressively does not
  emit clean patches). Rejected for now; helpers stay shared library code.
- **Correction on the tracker thread (beside gaze):** keeps one hand-off
  but adds unbounded-relative-to-budget work to the thread whose freshness
  bounds tracking latency; entangles correction failures with the
  inference-error budget; makes the tracker thread's abandon-at-shutdown
  story worse. Rejected.
- **Correction as a second `FrameProcessor` in a generic processor-chain
  mechanism:** the seam is one-frame-in/one-out per worker; a chain
  abstraction is machinery no current stage needs — composition inside one
  staged processor achieves the same with less. Rejected as speculative.
