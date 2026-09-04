# GazeFix — Current Engineering Assignment

**Active milestone: M1 — Face and Eye Tracking**

**M0 status: PASS / CLOSED / FROZEN**

**Assignment date: 2026-09-04**

## Authority and roles

The repository `01-GazeFix-Product-Requirements-Document-v1.1.md` remains the unchanged higher-level source of truth for product scope, requirements, constraints, and milestone gates. This assignment defines the currently authorized engineering work. The PRD's original M0-first starting priority is historical; this assignment advances the active milestone after its gate has closed, without changing the product requirements. If a material conflict exists, escalate it rather than editing the PRD or silently changing scope.

- ChatGPT: Product Manager / Technical Lead; scope, acceptance, and milestone decisions.
- Product Owner: final product decisions and target-device verification.
- Claude Code with Fable 5.1 Ultracode: primary implementation engineer and self-review.
- Kimi via Claude Code CLI: primary independent QA/reviewer.
- Codex: selective escalation or high-risk review only; not the default reviewer on every iteration.

Workflow: ChatGPT assignment → Claude implementation/self-review → Kimi QA → Claude fixes → Kimi re-review → Codex only if escalation/high-risk review is needed → Product Owner physical/runtime verification where applicable → authorized merge. No automatic progression to M2.

## M0 closure and frozen baseline

PR #3, `claude/m0-followup-hardening` → `milestone-0`, is merged:
https://github.com/iqbalmohamad/gazefix/pull/3

- Reviewed and tested source HEAD: `527ed2936bf5b288de1e2e46e934b155ba96c4e3`.
- Merge commit / frozen M0 baseline: `3b0a2eee8b0fc207875702250955e78173857957`.
- GitHub merge time: 2026-09-04 01:53:36 UTC.
- Verification: GitHub reports merged with the exact expected source HEAD and target; fetched Git history confirms the source HEAD is an ancestor of the merge. The merge tree equals the reviewed source tree.

Prior Product Owner verification on Windows 11 / Python 3.12.10: full automated suite **157 passed**; interactive GUI, physical webcam preview, Refresh, clean close, camera release after close, and physical-camera diagnostic all **PASS**. Reported startup approximately 1.x seconds; capture approximately 29.7 FPS; display approximately 28.5 FPS; 1280×720; MSMF validated. These are historical M0 results, not a new test run or evidence that M1 works. The merge commit records the completed Windows smoke test; the PR body's older "NOT VERIFIED / Draft" text predates that verification.

The remaining `PreparedCameraCloser` ambiguous `Thread.start()` bootstrap case is an accepted, non-blocking M0/MVP-foundation known limitation and production-hardening debt, as documented in `docs/architecture.md`. Do not reopen M0 for the same synthetic edge case. Revisit on new real Windows shutdown hangs, lingering camera locks, observable cleanup-thread leaks, or before M10/productization. New regressions introduced by M1 are not covered by this exception.

M0 is officially PASS/CLOSED and frozen. Do not advance, rewrite, or merge M1 into `milestone-0`. Preserve its baseline without requiring a new tag or branch-protection change.

## Objective

Integrate stable facial and eye landmark tracking into the existing local Windows live-preview pipeline. Produce usable tracking metadata and a development overlay while preserving responsive video, frame freshness, camera lifecycle behavior, and bounded resource cleanup. M1 proves tracking only; it does not estimate where the eyes are looking.

## Scope

1. Detect a face and track facial landmarks, anatomical left/right eyes and eyelid contours during normal head movement.
2. Expose iris landmarks when the selected tracker provides them. Represent unavailable iris data explicitly; document and justify any limitation.
3. Provide face orientation required by PR-3; expose head-pose information where useful. Document coordinate conventions and validity. Any head yaw/pitch/roll describes head orientation only, never eye gaze.
4. Expose truthful tracking confidence/quality and validity. Define the meaning, range, thresholds, and provenance of scores. If the backend does not expose a probability, use an explicitly described quality/availability signal; do not fabricate a model confidence.
5. Define a small tracking-result contract tied to frame sequence/timestamp and camera generation. Include face/eye validity, coordinates, optional iris/pose, confidence/quality, and processing timing. Document mirroring, left/right naming, resize/crop mapping, and coordinate units.
6. Integrate through the existing processor seam. Keep capture, tracking/model initialization, and blocking work off the Qt UI thread. Keep tracking logic independent of widgets; preserve immutable input ownership and generation filtering. Document tracker ownership, initialization, reset, and shutdown.
7. Add a development-mode overlay showing landmarks, optional iris/pose, tracking status/confidence, and useful tracking timing. Keep debug controls out of the normal consumer UI. Overlay off must preserve the original frame pixels; rendering must not mutate shared capture buffers.
8. Handle no face, low confidence, missing/partial landmarks, tracker/model initialization failure, runtime exceptions, face loss/re-entry, and camera changes. Preserve usable original-frame preview and clear invalid/stale tracking output. Recovery must be bounded and avoid per-frame error/retry storms.
9. Default to one primary face. Document a deterministic selection policy for multiple faces, avoiding arbitrary identity jumps. Multi-person tracking is not required.
10. Add only focused setup, architecture, diagnostic, and test documentation necessary to reproduce M1. Simple landmark stabilization is allowed where justified; it must reset on loss/source change and not add stale-frame latency.

## Non-goals and hard boundaries

- **No M2 or later milestone implementation**, scaffolding for future features, or automatic continuation after M1.
- **No gaze estimation**: no eye-direction yaw/pitch, gaze vectors, gaze target, camera/screen gaze mapping, or eye-contact score.
- **No gaze correction**: no eye warping, redirection, correction strength, correction masks/blending, or correction compositing. Drawing the debug overlay is allowed.
- **No calibration**: no calibration workflow, profiles, user-specific camera/screen mapping, or calibration controls.
- **No virtual camera**: no output backend, driver, pyvirtualcam, OBS integration, or conferencing-client integration.
- No neural gaze-redirection inference, ONNX Runtime adoption, model training, dataset collection, cloud inference, or frame upload. Local inference used solely by the approved face/landmark tracker is within M1.
- No M5 stabilization system, M7 optimization project, installer/productization work, unrelated refactoring, or reopening accepted M0 debt without its stated trigger.
- Do not edit the PRD. Do not modify, commit on, push to, or merge into `main`.

## Repository and branch strategy

Before implementation, fetch remotes, inspect status/history and applicable repository instructions, and preserve unrelated work. Use an isolated checkout when needed; never reset or clean someone else's working tree.

1. The assignment-only branch is `codex/m1-assignment`, based directly on frozen M0 merge `3b0a2eee8b0fc207875702250955e78173857957`. Its assignment commit changes only this file and does not implement M1.
2. At M1 kickoff, record the exact assignment commit SHA. If `milestone-1` does not exist, create the M1 integration branch from that assignment commit and publish it. If it already exists, inspect its ancestry and assignment before using it; do not overwrite or silently adopt conflicting work.
3. Create `claude/m1-face-eye-tracking` from the verified `milestone-1` baseline. If the implementation branch exists, inspect it and safely continue only if it belongs to this assignment.
4. Commit and push focused implementation work to `claude/m1-face-eye-tracking`. Open a reviewable PR targeting **`milestone-1`**, never `milestone-0` or `main`.
5. Existing `codex/m1-tracking-foundation` is historical work outside this new baseline. Do not merge or cherry-pick it wholesale, assume it passed review, or replace the hardened M0 foundation with it. Any reused idea must be independently checked against this assignment and tested in the new implementation.
6. Do not force-push, rewrite existing history, or merge the implementation PR. Leave it for Kimi review and Product Manager/Product Owner gate decisions.

The present assignment-writing task authorizes only this document update and its commit; implementation and creation of the M1 implementation/integration branches occur at the later engineering kickoff.

## Dependency and model policy

Preserve Python 3.11+ and Windows 10/11 compatibility, local-only processing, and a working CPU path on the target Intel i7 / Iris Xe class laptop. No NVIDIA, CUDA, NPU, Windows Studio Effects, or cloud-service requirement.

MediaPipe is the PRD's preferred tracking option, not a mandatory choice. Before adopting a major package or pretrained model, verify and record authoritative sources, version/date, active project status, Windows/Python compatibility, CPU support, code license, model license separately, and redistribution restrictions. Explain significant stack/architecture changes before implementation; escalate material licensing, privacy, hardware, product, or paid/cloud changes with Problem / Options / Trade-offs / Recommendation. Ordinary implementation choices remain Claude's responsibility.

Add dependencies only when needed for M1. Specify tested versions or compatible bounds and inspect transitive conflicts, especially NumPy, OpenCV variants, and Qt. Do not install future-milestone packages merely because they appear in the preferred stack. Never silently introduce commercially licensed or research-only assets as production-ready.

If a model file is needed, document its official source, exact version and checksum, license/redistribution terms, local location, and reproducible setup. Any setup download must be explicit; normal runtime must work offline with the asset present. Missing/corrupt/incompatible assets must yield an actionable local error and usable original preview. Do not silently download on launch or store/upload webcam images. Test fixtures must be synthetic or appropriately licensed and documented.

## Acceptance criteria

- **AC1 — Live tracking:** On the target Windows webcam, one visible face has aligned facial landmarks, distinct left/right eye and eyelid landmarks, and face orientation. Iris information is provided where supported or explicitly reported unavailable with justification. Landmarks remain visually attached during ordinary movement, blinking, and speaking.
- **AC2 — Truthful results:** Validity/confidence semantics and coordinate transforms are documented and exercised. Partial/invalid output never masquerades as valid full tracking; pose cannot be confused with gaze. Metadata belongs to the displayed frame and camera generation.
- **AC3 — Failure/recovery:** No face, face exit/re-entry, occlusion/low confidence, model failure, tracker exception, and camera switching clear stale results and preserve recoverable original-frame preview. No old landmarks remain attached to a new face or camera. Bounded recovery and shutdown behavior are demonstrated.
- **AC4 — Overlay and ownership:** A development-only overlay can be toggled; original pixels remain unchanged with overlay off. Overlays align under the implemented mirror/resize policy. Shared input frames are never mutated, and widgets are accessed only by the UI thread.
- **AC5 — Pipeline continuity:** Slow tracking cannot create an unbounded frame queue or continuously growing latency. Latest-frame behavior, responsiveness, camera Refresh/selection, clean close, and camera release remain intact. Document how overload or a stalled tracker is handled without claiming that a timeout can cancel an uninterruptible native call.
- **AC6 — Reproducible CPU setup:** Supported Windows/Python setup and the selected local model run on CPU without mandatory special hardware or network access during normal use. Dependencies and model licensing are documented.
- **AC7 — Evidence and scope:** Meaningful automated tests pass, Windows/physical evidence is reported honestly, and the full diff respects all M1 boundaries. Unverified required runtime items prevent unconditional PASS.

PRD MVP/M7 targets remain 720p, >=24 FPS, and <100 ms processing latency; they are not newly imposed M1 performance gates. Measure M1 at 1280×720 where supported, report any internal inference resolution and trade-offs, and flag regressions against the historical M0 baseline. Do not silently redefine product performance targets or claim them from a mock benchmark.

## Test expectations

Use deterministic, hardware-independent tests in the default suite; normal tests must not need a webcam, internet, or an external model download. Separate explicitly invoked real-backend/model tests from fakes and mark unavailable integration requirements accurately.

Cover behavior, including:

- Valid face/eye output, optional iris/pose absence, malformed/partial landmarks, confidence thresholds, and no-face results.
- Anatomical left/right, mirroring/resize mapping, overlay on/off, immutable input buffers, and result/frame identity.
- Loss/reacquisition and camera-generation changes clearing tracker state; stale in-flight results rejected.
- Initialization failure, missing/corrupt asset, inference exception, bounded retry/fallback, and tracker resource release.
- Slow processing/latest-frame replacement, UI responsiveness seams, and stop during initialization/in-flight processing.
- Existing M0 camera lifecycle, ownership, shutdown-state, diagnostic timing, and buffer regressions.

Prefer events/barriers and fakes over sleep-sensitive concurrency tests. Keep the existing full suite passing; do not delete or weaken a test to hide a regression. Run focused tests while iterating, the full suite on final HEAD, and useful import/CLI checks. Provide commands, versions, pass/fail/skip counts, and reasons for skipped tests. Historical "157 passed" is a baseline, not the expected new count or a substitute for executing tests.

## Runtime and physical verification

Run the real tracker/model on documented, licensed local inputs when available; mock tests cannot establish landmark quality. Then verify on the Product Owner's Windows laptop or an equivalent capable target:

1. Startup, responsive GUI, physical webcam preview, CPU tracker initialization, and actionable behavior when the model is unavailable.
2. At least 60 seconds of ordinary use: steady face, minor head motion, blinking, speaking; inspect landmark attachment and confidence. Exercise glasses and lighting variation when available and record limits.
3. Face leaves/re-enters, brief eye/face occlusion, no-face scene, and multiple-face selection policy where feasible; confirm stale overlays disappear and recovery works.
4. Overlay toggle, Refresh, switching cameras when available, disconnect/recovery where feasible, clean close, and physical camera release. Unavailable second-device scenarios must be marked NOT VERIFIED.
5. Record capture/display FPS, tracking latency, total processing latency with defined boundaries, dropped/replaced frames, and useful CPU/memory observations. State warm-up/sample duration, resolution, camera/backend, model/runtime versions, and hardware. Use NOT MEASURED for missing data.

Report each relevant item as VERIFIED / NOT VERIFIED / FAILED and identify its level: implementation verified, runtime verified, or physical hardware verified. Windows imports alone are not GUI verification; non-Windows execution is not Windows verification. Screenshots/short recordings may support review when useful and approved by the Product Owner; do not record or transmit webcam frames by default.

A known acceptance failure or materially incomplete implementation is FAIL. Passing implementation with unavailable required runtime/hardware evidence is PASS WITH LIMITATIONS, not PASS. PASS requires all applicable acceptance criteria verified in a capable environment. Optional iris/pose details and unavailable ancillary scenarios require explicit rationale; they cannot silently waive required face/eye/orientation behavior.

## Required engineering report

Return the following sections, then stop:

1. **Status:** Delivery status READY FOR REVIEW or BLOCKED; milestone recommendation PASS / PASS WITH LIMITATIONS / FAIL using the PRD definitions. The Product Manager makes the milestone decision. Explain any incomplete acceptance item.
2. **Branch and provenance:** Frozen M0 SHA, assignment commit SHA, integration branch and starting SHA, implementation branch, tested final HEAD, PR number/link, and target milestone-1.
3. **Implemented behavior:** Face/eye/iris/orientation capabilities, confidence contract, coordinates, primary-face policy, overlay behavior, fallback/recovery, and important changed files.
4. **Architecture and lifecycle:** Processor integration, threads, frame ownership/generation filtering, bounded buffers, tracker reset/cleanup, overload policy, and any native-call cancellation limitations.
5. **Dependencies and models:** Added/changed packages and tested versions; official compatibility/license sources; model provenance/checksum/setup; CPU and offline behavior; decisions escalated.
6. **Acceptance and verification matrix:** AC1–AC7 mapped to evidence, verification level, and VERIFIED / NOT VERIFIED / FAILED; focused/full-suite commands and results; real-model, Windows GUI, physical camera, and release checks separately; exact tested HEAD and environment.
7. **Performance:** Measured FPS/latencies/frame replacement and resource observations with boundaries, sample conditions, resolution, and comparison limits; NOT MEASURED where unavailable.
8. **Self-review and QA:** Concurrency, lifecycle, stale-result, coordinate, failure, dependency, regression, and scope review; outstanding findings with severity and evidence; Kimi findings/fixes/re-review status if already available. Do not invent independent QA.
9. **Known limitations and decisions:** Distinguish accepted M0 debt, M1 defects, environment gaps, and future work; list concrete remaining Product Owner checks.
10. **Scope confirmation:** No M2, gaze estimation, correction, calibration, neural gaze redirection, virtual camera, future-milestone dependencies, PRD change, main change, or modification of frozen milestone-0.
11. **Merge state:** PR NOT MERGED.
12. **Recommendation and next step:** PROCEED / ITERATE / CHANGE APPROACH with rationale. Initial handoff: Ready for independent Kimi QA. After fixes: Ready for Kimi re-review. Escalate to Codex only for a specific unresolved/high-risk concern. List required Product Owner verification before an authorized merge.

A full-suite failure prevents READY FOR REVIEW as a passing delivery; report any environment blocker explicitly rather than hiding omitted tests. Commit/push completed work and open the PR when access permits; otherwise report the exact blocker and local commit. Do not merge, declare M1 closed on behalf of the Product Manager, or begin M2.
