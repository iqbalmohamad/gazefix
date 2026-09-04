# GazeFix — Overall Architecture Pass

**Active assignment: Overall Architecture Pass — architecture-only**

**M0 status: PASS / CLOSED / FROZEN**

**M1 status: PASS / CLOSED / FROZEN**

**M2 status: PASS / CLOSED / FROZEN**

**Assignment date: 2026-09-04**

You are acting as the Software Architect / Senior Technical Lead for GazeFix.

This is an architecture-only assignment.

- Do **NOT** implement product features.
- Do **NOT** begin M3 implementation.

Your goal is to inspect the actual frozen repository through Milestone 2, reconcile it with the product roadmap, and produce a practical architecture baseline that can guide M3 and later milestones without requiring repeated large architectural reasoning during implementation.

## Project state

| Milestone | Status |
| --- | --- |
| Milestone 0 — Technical Foundation | FROZEN |
| Milestone 1 — Face and Eye Tracking | FROZEN |
| Milestone 2 — Gaze Estimation | FROZEN |

Frozen M2 HEAD:

```text
81e06118801c23d2337629fc676d6ad8ac13716a
```

The accepted M2 implementation candidate before merge was:

```text
7f818f806db0af8e9c0281d1050ae6e838c488af
```

PR #5 has been merged into `milestone-2`. The merged M2 tree is byte-identical to the accepted candidate.

Do not modify any frozen milestone branch.

## Working branch

Create/use:

```text
claude/architecture-pass
```

Base it directly on `milestone-2` at frozen HEAD `81e06118801c23d2337629fc676d6ad8ac13716a`.

Before making changes:

1. fetch latest remote state,
2. verify `milestone-2` points to the frozen M2 HEAD,
3. verify the architecture branch descends directly from that baseline,
4. verify `milestone-0`, `milestone-1`, `milestone-2`, and `main` remain untouched,
5. stop and report `BLOCKED` if repository state materially conflicts with these expectations.

Do not merge anything as part of this assignment.

## Sources of truth

Read before designing:

1. repository PRD
2. `Current Assignment.md`
3. `docs/qa-policy.md`
4. existing architecture documentation
5. existing ADRs / decision records
6. actual source code through frozen M2
7. relevant tests where needed to understand real contracts and lifecycle

Use them as follows:

- PRD → product requirements, roadmap, hardware constraints, milestone boundaries
- actual frozen code → current implementation reality
- architecture docs / ADRs → previously intended architecture
- tests → behavioral contracts where implementation intent is not obvious
- QA policy → verification philosophy, not product architecture

If documentation and code disagree, explicitly document the discrepancy. Do not silently redesign working frozen components merely because an alternative architecture might look cleaner.

## Assignment objective

Produce an overall architecture baseline for GazeFix from frozen M2 through the remaining MVP roadmap.

The architecture should answer:

> Given what GazeFix actually is after M2, how should M3–M10 fit together so that future milestones can be implemented incrementally without rewriting the application core?

This should be practical architecture for a solo/DIY MVP. Do not design an enterprise platform.

Prefer:

- clear contracts,
- explicit ownership,
- bounded state,
- simple dependency direction,
- incremental replaceability,
- failure isolation,
- low-latency behavior,
- easy testing,
- minimal speculative abstraction.

## Important architectural principles already established

Preserve unless a concrete architectural reason requires change.

**Real-time freshness.** GazeFix prefers the newest frame over processing every captured frame. No unbounded frame queue.

**Stream continuity.** Correction, gaze, tracking, or downstream processing failure must not unnecessarily stop usable video.

**UI separation.** Blocking camera/computer-vision work must remain off the Qt UI thread.

**Local processing.** Webcam frames remain local. No cloud inference.

**Hardware target.** Windows 10/11, CPU-first, Intel i7-class CPU, Intel Iris Xe compatible. No required:

- NVIDIA GPU
- CUDA
- RTX
- Copilot+ NPU

**Incremental milestones.** Do not architect M3 as if M8 must already exist. Architecture should create clean seams for later work without implementing future features prematurely.

## Current frozen system

Inspect and document the architecture that actually exists through M2. At minimum identify:

- application/UI layer
- camera discovery/capture
- latest-frame / processor boundaries
- tracking worker
- MediaPipe backend
- tracking result contracts
- gaze estimation
- gaze smoothing / temporal state
- diagnostics
- error/recovery boundaries
- thread ownership
- frame ownership/copy semantics
- configuration/settings
- development overlay
- lifecycle/reset behavior

Do not rely only on existing documentation. Confirm architecture against code.

## Required architecture work

### 1. Current-state architecture

Produce a concise but concrete diagram and explanation of the frozen M2 architecture. Show at least:

```text
Camera
  ↓
Frame transport / latest-frame mechanism
  ↓
Tracking
  ↓
Gaze estimation
  ↓
Current consumers / UI
```

Include actual thread/process ownership. Explicitly identify:

- which component owns each mutable state,
- where queues/buffers exist,
- which objects cross thread boundaries,
- where failures are contained,
- which lifecycle events reset temporal state.

This should describe reality, not an aspirational rewrite.

### 2. Target MVP architecture

Design the conceptual target architecture needed to reach M10/MVP. At minimum account for future:

- offline correction experimentation
- real-time correction
- compositing
- temporal stabilization
- calibration
- performance optimization
- virtual-camera output
- optional neural model evaluation
- productization

Show how these fit into the real-time pipeline. A conceptual target may resemble:

```text
Frame Source
    ↓
Latest Frame
    ↓
Tracking
    ↓
Gaze Estimation
    ↓
Calibration / Target Resolution
    ↓
Correction Engine
    ↓
Compositor
    ↓
Temporal Output Stabilization
    ↓
Processed Frame
    ├── Preview
    └── Virtual Camera
```

But do not adopt this blindly. Derive the appropriate architecture from the actual repository.

### 3. Processing-stage boundaries

Define the recommended stable boundaries/contracts for:

- tracking
- gaze estimation
- correction
- compositing
- calibration
- output/virtual camera

Clarify what data each stage consumes and emits. Do not create giant "god result" objects unless justified.

Determine which contracts should:

- remain immutable,
- carry frame/generation identity,
- represent unavailable/degraded states,
- expose latency/diagnostic metadata,
- hold image data vs metadata only.

### 4. Frame ownership and copying

This is important for future correction performance. Document:

- who owns raw capture frames,
- when frames are copied today,
- where future mutation/correction may safely occur,
- how debug overlay avoids modifying production source frames,
- whether correction should operate in-place or on owned working copies,
- how preview and virtual-camera consumers should share or copy corrected frames.

Recommend a strategy that avoids:

- accidental cross-thread mutation,
- excessive 720p copies,
- stale-frame buildup.

Do not prematurely optimize with exotic shared-memory architecture unless necessary.

### 5. Threading and execution model

Describe current threading. Then recommend the intended execution model for M3–M8. Answer specifically:

- Should tracking + gaze + correction remain one processing worker initially?
- At what point, if any, would splitting correction into another worker become justified?
- How should backpressure work?
- What happens if correction is slower than capture?
- How do preview and virtual-camera consumers receive processed frames?
- Which stages may be skipped when unavailable?
- Which failures should degrade locally versus restart a larger subsystem?

Prefer simple bounded/latest-frame behavior. Do not introduce concurrency merely because future workloads might become heavier.

### 6. M3 offline correction architecture

Define how M3 should experiment with gaze correction without coupling the experimental correction algorithm to the live pipeline.

M3 is **Milestone 3 — Offline Gaze Correction Prototype**. Outcome: prove visible eye-gaze redirection.

Input may be:

- still image
- recorded frame
- short prerecorded video

Architecture should allow M3 correction code to later plug into the live processor without rewriting it. Define:

- correction engine interface,
- input/output contracts,
- target gaze representation,
- strength semantics,
- masks/compositing responsibility,
- error/fallback behavior.

Do **NOT** design the actual correction algorithm in detail. That belongs in M3 SA/implementation work.

### 7. Real-time correction integration

Describe the intended M4 integration path. Clarify:

- where correction enters the existing processor,
- what happens when gaze is unavailable,
- what happens when correction fails,
- how original-frame fallback works,
- where correction latency is measured,
- how stale correction results are prevented.

### 8. Temporal stabilization

Clarify separation between:

- tracking smoothing,
- gaze smoothing,
- correction-parameter smoothing,
- image/output stabilization.

Avoid one generic smoothing subsystem for unrelated signals unless justified.

Explain which temporal state resets on:

- face loss,
- camera generation,
- Refresh,
- camera switch,
- correction disable,
- calibration profile change.

### 9. Calibration architecture

M6 will add calibration. Define only the architecture seam now. Clarify:

- calibration profile ownership,
- persistence boundary,
- how calibration transforms uncalibrated gaze into user/session-specific behavior,
- relationship between calibration and target gaze,
- what invalidates a profile,
- what must remain independent from correction-engine implementation.

Do not implement calibration.

### 10. Correction-engine replaceability

The PRD requires GazeFix not to be tied permanently to one gaze-correction implementation. Define a practical abstraction for:

- geometric correction,
- future neural correction.

Avoid over-generalizing. Clarify where engine initialization/shutdown belongs and what the rest of the app should know about engine type.

### 11. Neural-model boundary

M9 is neural-model evaluation, not a prerequisite for M3–M8. Document how a future neural engine could plug in without infecting the rest of the application with:

- ONNX Runtime types,
- provider-specific objects,
- DirectML assumptions,
- model-specific tensors.

Do not add ONNX Runtime now.

### 12. Virtual-camera architecture

M8 adds virtual-camera output. Define the boundary now without implementing it. Clarify:

- processed-frame ownership,
- output backend abstraction,
- format expectations,
- output FPS behavior,
- what happens when output consumer is slower,
- start/stop lifecycle,
- error isolation.

A virtual-camera failure must not necessarily kill preview/capture.

### 13. Diagnostics architecture

Review existing diagnostics and recommend the target set for later milestones:

- capture FPS
- output/display FPS
- tracking latency
- gaze latency
- correction latency
- compositing latency
- total processing latency
- dropped/stale frame counters
- virtual-camera send latency
- CPU/memory
- inference provider where relevant

Avoid designing an observability platform. Keep diagnostics local and lightweight.

### 14. Error-domain architecture

Explicitly identify failure domains. For example:

```text
camera failure
tracking failure
gaze failure
correction failure
compositor failure
virtual-camera failure
```

For each, define expected containment and recovery ownership.

Preserve the M2 lesson: a downstream gaze failure must not incorrectly consume tracking recovery budget. Apply the same principle to future stages. Avoid one shared global "processing error" mechanism if it causes unrelated subsystem recovery.

### 15. Configuration ownership

Review configuration/settings architecture. Recommend where future settings belong:

- correction enabled
- correction strength
- selected correction engine
- calibration profile
- virtual-camera settings
- development diagnostics

Separate:

- product/user settings,
- internal constants,
- measured model parameters,
- developer/debug configuration.

### 16. Data contracts

Recommend concrete data contracts for future work. Examples may include:

- `TrackingResult`
- `GazeEstimate`
- `CorrectionRequest`
- `CorrectionResult`
- `ProcessedFrame`
- `CalibrationProfile`

Names are not mandated. For each recommended contract state:

- purpose,
- owner/producer,
- consumers,
- mutable vs immutable,
- required identity/timestamp/generation fields,
- unavailable/failure semantics.

Do not implement them.

### 17. Dependency direction

Define desired module dependency direction. Prevent future circular coupling such as:

- UI knowing MediaPipe internals,
- correction importing Qt,
- calibration depending on virtual camera,
- tracking importing correction,
- model contracts importing implementation backends.

Show a simple dependency diagram.

### 18. Repository/module structure

Review the actual repository structure. Recommend only necessary changes for future milestones. Do **NOT** rearrange the repository solely to match the PRD's example structure.

Distinguish:

- structure that is already good,
- structure that should evolve naturally,
- refactors that should wait until a milestone actually needs them.

### 19. Architectural risks

Create a concise risk register for the remaining MVP. Focus on actual technical risks such as:

- correction quality,
- eye-region compositing artifacts,
- temporal instability,
- processing latency,
- CPU budget,
- camera/virtual-camera coexistence,
- Windows backend behavior,
- frame-copy overhead,
- model licensing,
- neural dependency complexity.

For each risk include:

- impact,
- likely milestone where it becomes relevant,
- mitigation or decision gate.

Do not classify ordinary implementation choices as major risks.

### 20. Decision points / ADR candidates

Identify decisions that deserve ADRs before implementation. Examples only if actually justified:

- correction engine contract
- processed-frame ownership
- virtual-camera backend choice
- neural runtime/provider strategy

Do not create dozens of ADRs. Use ADRs for decisions with meaningful future cost.

## Architecture vs milestone SA

This overall pass must remain architecture-level. Do **NOT** turn it into detailed System Analysis for M3.

The output should establish:

- stable system boundaries,
- ownership,
- integration strategy,
- dependency direction,
- failure domains,
- roadmap implications.

Detailed M3 algorithm choices, eye-warping math, masks, prototype experiments, and exact implementation tasks belong in a separate M3 SA after this architecture is accepted.

At the end, explicitly list:

- **Architecture decisions that are now stable**, and
- **Questions intentionally deferred to M3 SA**.

This distinction is important.

## Avoid overengineering

GazeFix is a solo/DIY MVP. Do not propose by default:

- microservices,
- multiprocessing,
- distributed systems,
- message brokers,
- plugin frameworks,
- dependency injection frameworks,
- complex event buses,
- generic workflow engines,
- elaborate state machines,
- GPU abstraction layers before needed,
- production telemetry services,
- custom Windows driver architecture before M8 demands it.

Every new abstraction must answer: **what concrete future milestone problem does this solve?** If the answer is only "it might be useful later," defer it.

## Expected documentation changes

Prefer updating `docs/architecture.md` and, if justified, a small number of ADRs under `docs/decisions/`.

- Do not modify the PRD.
- Do not modify product code.
- Do not modify tests unless absolutely required to correct architecture documentation evidence; normally no test changes should be necessary.
- Do not change `Current Assignment.md` to activate M3. This task ends before M3 assignment preparation.

## Verification

Because this is documentation/architecture work:

- inspect the actual code sufficiently to validate claims,
- use small targeted commands where useful,
- do not run broad QA,
- do not run physical webcam tests,
- do not create test harnesses,
- do not modify product behavior.

Verify that documentation references real modules/contracts accurately.

## Final report

Return the following sections.

**Status.** Choose:

- `ARCHITECTURE PASS COMPLETE`
- `BLOCKED`

**Repository state.**

- architecture branch
- base frozen M2 SHA
- final HEAD
- files changed
- confirmation frozen branches remain untouched

**Current architecture.** Concise summary of frozen M2 reality.

**Target architecture.** Concise summary of recommended MVP architecture.

**Stable architecture decisions.** List decisions that should now guide future milestones.

**Deferred decisions.** List what intentionally remains for:

- M3 SA
- later milestone SA
- runtime/PO experimentation

**Architectural risks.** Top remaining risks and associated milestone gates.

**ADRs.** List any ADRs created and why.

**Repository consistency findings.** List any meaningful differences between:

- PRD architecture examples,
- existing docs,
- frozen implementation.

Do not "fix" discrepancies silently.

**Scope confirmation.** Confirm:

- no product code changed,
- no tests changed unless explicitly justified,
- no M3 implementation begun,
- no frozen branch changed.

**Recommendation.** Choose:

- `READY FOR PM ARCHITECTURE REVIEW`
- `CHANGE APPROACH`

Stop there. Do not prepare or implement M3 unless separately authorized.
