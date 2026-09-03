# GazeFix — Current Engineering Assignment

You are the primary Software Engineer for **GazeFix**.

ChatGPT is the Product Manager. The user is the Product Owner.

The attached **GazeFix Product Requirements Document v1.1** remains the unchanged source of truth for product requirements, product scope, constraints, milestone definitions, and acceptance criteria. This file is the source of truth for the engineering work that is currently active.

Do not edit the PRD as part of this assignment. If this assignment materially conflicts with the PRD, stop and escalate the conflict instead of silently changing product behavior.

# Active Assignment

Complete **M0 Follow-up Hardening** only.

Milestone 0 has already passed, and PR #2 was merged into `milestone-0` at merge commit:

```text
a636d890284dd9c36231c45727990c06af77f6f1
```

Before Milestone 1 begins, resolve both remaining M0 carry-forward issues:

1. Truthful shutdown-state bookkeeping.
2. Diagnostic-versus-production camera timing fidelity.

This is a focused M0 hardening assignment. It does not reopen the completed Milestone 0 feature scope and does not authorize Milestone 1 work.

---

# Repository and Git Rules

Start from the latest remote `milestone-0`.

Before modifying code:

1. Fetch the latest remote state.
2. Confirm that `origin/milestone-0` contains merge commit `a636d890284dd9c36231c45727990c06af77f6f1` or a later expected commit.
3. Inspect the repository structure, current status, relevant history, affected implementation, and existing tests.
4. Preserve unrelated work and do not rewrite history.

Create and work only on:

```text
claude/m0-followup-hardening
```

Create the branch from the latest:

```text
origin/milestone-0
```

The pull request target must be:

```text
milestone-0
```

Do not modify, merge into, or push to `main`.

Commit and push the completed work to `claude/m0-followup-hardening`, then open a pull request into `milestone-0`.

Do **not** merge the pull request. It must remain available for independent review.

---

# Scope Boundaries

Do not begin Milestone 1.

Do not implement or introduce:

- face detection or tracking,
- eye or iris tracking,
- head-pose estimation,
- gaze estimation or correction,
- calibration,
- ML, ONNX, or MediaPipe inference,
- compositing changes for future gaze correction,
- virtual-camera output or OBS integration,
- future product controls,
- unrelated architecture or repository restructuring.

Also:

- add no new major dependency,
- add no cloud functionality,
- preserve Python 3.11+ and Windows 10/11 compatibility,
- preserve the no-CUDA/no-NVIDIA/no-NPU requirement,
- keep all waits bounded,
- keep camera and worker ownership explicit,
- preserve latest-frame semantics,
- keep changes focused on the affected lifecycle and camera-opening/diagnostic areas.

---

# Issue 1 — Truthful Shutdown-State Bookkeeping

## Problem

`gazefix/pipeline/runtime.py` currently clears `_started` after `stop()` even when the shutdown deadline expires and one or more workers may still be alive.

That can make the runtime claim it is stopped when it is not. A later `stop()` can then take the early-success path even though the earlier shutdown did not fully terminate the runtime.

Logging the timeout is not sufficient; the internal lifecycle state and subsequent behavior must remain truthful.

## Required Behavior

Review the actual runtime, capture-worker, processing-worker, and UI shutdown lifecycle. Implement a robust state model such that:

1. A shutdown timeout never causes the runtime to represent live workers as fully stopped.
2. The boolean result of `stop()` accurately reflects whether every owned worker has terminated.
3. Repeated `stop()` calls after a timeout continue to report and act on the real worker state; they must not return success solely because an earlier call cleared a bookkeeping flag.
4. If a worker remains alive after a timeout, subsequent lifecycle operations are deterministic and safe.
5. If the worker later terminates, a later `stop()` can observe and finalize the stopped state without leaking resources.
6. A successful shutdown leaves the runtime fully stopped and preserves any currently supported restart/reuse behavior. Do not invent restart support if the architecture does not support it.
7. Joins and waits remain bounded by explicit deadlines. Do not add an unbounded join or block the Qt UI thread indefinitely.
8. Existing ownership rules remain intact: a blocked OpenCV call is not made unsafe by releasing its capture concurrently from another thread.
9. Pending prepared-camera resources are closed safely and exactly as lifecycle ownership requires.
10. Existing clean-shutdown, camera-switch, interrupt, and latest-frame behavior is preserved.
11. Timeout and recovery paths emit useful, truthful local logging without hiding failure state.

## Required Regression Tests

Add meaningful hardware-independent tests covering at least:

- successful shutdown,
- shutdown timeout while a worker remains alive,
- repeated `stop()` after that timeout,
- eventual worker termination and truthful finalization, where applicable to the implemented state model,
- preservation of bounded waits,
- no false stopped/success state while any owned worker is still alive.

Prefer deterministic fakes/events over wall-clock-sensitive tests. Use the architecture already present rather than adding an unnecessary lifecycle framework.

## Acceptance Criteria

This issue is accepted only when all of the following are true:

- Runtime lifecycle state agrees with actual worker liveness after every `stop()` outcome.
- A timed-out shutdown cannot be converted into a false success by calling `stop()` again.
- A later call can safely recognize eventual termination if a timed-out worker subsequently exits.
- No unbounded wait, unsafe cross-thread camera release, race-prone cleanup, or UI-thread deadlock is introduced.
- Existing normal shutdown behavior remains passing.
- Focused regression tests demonstrate the timeout and repeated-stop cases.

---

# Issue 2 — Diagnostic-versus-Production Timing Fidelity

## Problem

`gazefix/camera/diagnostics.py` currently opens and configures cameras differently from the production path in `gazefix/camera/source.py`.

The diagnostic currently constructs `cv2.VideoCapture(index, backend)`, then unconditionally sets width, height, FPS, and buffer size. Production uses different DirectShow open parameters, conditional format application, fallback/validation behavior, and shared application settings. As a result, the diagnostic timings are useful for A/B comparison but are not necessarily representative of production startup behavior.

## Required Behavior

Review the production open/configure flow and diagnostic probe flow. Refactor at the appropriate lower-level seam so the diagnostic shares or faithfully exercises the production camera-opening and configuration behavior needed for meaningful timing data.

The result must satisfy all of the following:

1. Requested backend behavior is explicit and consistent between diagnostic and production use where equivalence is intended.
2. MSMF and DirectShow opening/configuration semantics match production behavior, including DirectShow open parameters and conditional width/height/FPS application.
3. Hardware-transform behavior remains configurable and testable for MSMF A/B runs.
4. Timing fields remain correctly defined and useful. At minimum, preserve meaningful measurements for open, configure, first-frame validation/read, sampling, and release where technically possible.
5. Reported backend, negotiated width, negotiated height, negotiated FPS, observed FPS, successful reads, failed reads, and errors remain accurate.
6. Every opened or partially opened camera resource is released on success, failure, interruption, and exception paths.
7. The diagnostic remains CLI-friendly, local-only, and safe to run against physical hardware.
8. The diagnostic is not coupled to PySide6 or the Qt UI.
9. Production code does not depend on the diagnostic module.
10. Duplicated camera-open/configuration logic is removed or reduced where it can be shared safely.
11. The existing diagnostic CLI remains compatible unless a small backward-compatible extension is needed.
12. Any remaining intentional difference from production is documented precisely, including its effect on interpreting timing results.

Do not claim exact production equivalence unless the code path and measurement boundaries justify that claim.

## Required Regression Tests

Add or update hardware-independent tests covering at least:

- reuse of the intended production opening/configuration primitives,
- backend-specific behavior for MSMF and DirectShow,
- width/height/FPS configuration semantics,
- timing-field meaning at the chosen measurement boundaries,
- first-frame validation/read behavior,
- release on success and all relevant failure paths,
- hardware-transform configuration propagation,
- any documented intentional distinction from production.

Physical-camera verification may supplement these tests but must not replace them.

## Acceptance Criteria

This issue is accepted only when all of the following are true:

- Diagnostic results are generated through the production-equivalent open/configuration behavior claimed by the implementation.
- Backend selection, requested format behavior, first-frame behavior, and hardware-transform settings are consistent where intended.
- Timing labels accurately describe what is measured and are not presented as production timings if a material distinction remains.
- Camera ownership and release are correct on every path.
- The CLI remains usable without a Qt dependency.
- Production runtime does not depend on diagnostic code.
- Focused hardware-independent regression tests demonstrate the shared behavior.

---

# Required Engineering Workflow

1. Fetch and branch from the latest `origin/milestone-0`.
2. Inspect the current lifecycle, camera source, diagnostic code, configuration, and relevant tests before editing.
3. Implement both carry-forward fixes without expanding scope.
4. Add focused regression tests for both issues.
5. Run the focused tests while iterating.
6. Run the complete automated test suite.
7. Run static, import, or CLI-help validation where useful.
8. If the environment permits, run the diagnostic safely; distinguish code verification from Windows/physical-camera verification.
9. Self-review the complete diff, including surrounding code, for:
   - concurrency and race conditions,
   - worker lifecycle truthfulness,
   - bounded shutdown behavior,
   - camera ownership and release,
   - production/diagnostic equivalence,
   - timing-definition accuracy,
   - backward compatibility,
   - test quality,
   - scope compliance.
10. Fix issues found during self-review.
11. Confirm no unrelated files or future-milestone functionality were introduced.
12. Commit and push the branch.
13. Open a pull request from `claude/m0-followup-hardening` into `milestone-0`.
14. Do not merge the pull request.

Do not stop after proposing code when repository access is available. Complete the implementation, verification, self-review, commit, push, and PR creation unless a genuine blocker prevents them.

---

# Verification Policy

Report evidence precisely and distinguish:

```text
CODE VERIFIED
RUNTIME VERIFIED
PHYSICAL HARDWARE VERIFIED
```

Automated tests with fakes do not verify a physical webcam. Import or CLI-help success does not verify real camera timing. If Windows GUI or physical-camera verification is unavailable, state `NOT VERIFIED`; do not infer or fabricate a result.

The complete test suite must pass before reporting `READY FOR REVIEW`. If an unrelated environmental limitation prevents a test from running, report it explicitly with the evidence gathered; do not silently omit it.

---

# Pull Request Requirements

The pull request must:

- use source branch `claude/m0-followup-hardening`,
- target `milestone-0`,
- contain both fixes and their tests,
- describe the previous failure modes and the implemented behavior,
- state focused and full-suite test results,
- identify any Windows or physical-hardware items not verified,
- confirm that no M1 functionality was introduced,
- remain unmerged for independent Codex review.

Do not modify or merge into `main`.

---

# Required Final Engineering Report

When the work is complete, return exactly this report structure, then stop.

## Status

Choose exactly one:

```text
READY FOR REVIEW
BLOCKED
```

## Branch

Report:

- base branch and starting SHA,
- working branch,
- final HEAD SHA,
- pull request number and link.

## Shutdown-State Fix

Explain:

- the previous failure mode,
- the new lifecycle/state behavior,
- how timeout, repeated `stop()`, and eventual termination behave,
- regression tests added.

## Diagnostic Fidelity Fix

Explain:

- the previous difference from production,
- which production primitives or behavior are now shared,
- the exact timing boundaries,
- any remaining intentional distinction,
- regression tests added.

## Repository Changes

List the important files modified and why.

## Verification

Report:

- focused test commands and results,
- complete test-suite command and result,
- static/import/CLI checks run,
- Windows runtime status,
- physical-camera status,
- any failures or limitations.

Use `NOT VERIFIED` for unavailable runtime or hardware checks.

## Self-Review

Summarize the concurrency, lifecycle, ownership, timing-fidelity, regression, and scope review. List any remaining meaningful risks or non-blocking notes.

## Scope Confirmation

Confirm all of the following:

- no Milestone 1 functionality,
- no face/eye/iris tracking,
- no gaze estimation or correction,
- no calibration, ML inference, or virtual-camera work,
- no new major dependencies,
- no changes pushed or merged to `main`.

## Merge State

State exactly:

```text
PR NOT MERGED
```

## Next Step

State exactly:

```text
Ready for independent Codex review.
```

Do not begin Milestone 1. Do not merge the pull request.
