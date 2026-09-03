You are the software engineer responsible for implementing **GazeFix**.

The Product Manager is ChatGPT.

I am the product owner/user.

The attached **GazeFix Product Requirements Document v1.1** is the source of truth for product requirements, product scope, constraints, milestone definitions, and acceptance criteria.

Your responsibility is **engineering execution**.

Do not redesign the product unless a technical issue materially conflicts with the PRD. If that happens, escalate it instead of silently changing product behavior.

# Current Assignment

Implement **Milestone 0 — Technical Foundation** only.

The objective of Milestone 0 is:

> Prove that the foundational real-time Windows camera pipeline is stable enough to support later computer-vision processing.

Do **not** implement:

- face detection,
- face tracking,
- eye tracking,
- iris tracking,
- gaze estimation,
- gaze correction,
- calibration,
- machine-learning inference,
- ONNX inference,
- MediaPipe tracking,
- virtual-camera output,
- OBS integration,
- neural models.

Do not install dependencies for those future milestones unless Milestone 0 genuinely requires them.

Stop after Milestone 0.

---

# Repository / Git Rules

You are working inside an existing Git repository.

Before modifying anything:

1. inspect the repository structure,
2. inspect `git status`,
3. inspect the current branch,
4. inspect recent relevant git history if useful,
5. inspect existing configuration and documentation,
6. identify existing implementation that should be preserved,
7. identify Python/runtime constraints available in your environment.

Do not overwrite unrelated existing work.

Do not delete existing files merely because you prefer another structure.

Prefer incremental changes over unnecessary repository restructuring.

Do not:

- push to a remote,
- merge branches,
- force-reset the repository,
- rewrite git history,
- open a pull request,

unless explicitly instructed by the product owner.

Do not create commits unless explicitly requested.

If the working tree already contains unrelated modifications, preserve them.

---

# Required Deliverables

Implement:

1. Clean Python project/repository structure.
2. Python 3.11+ compatibility.
3. Windows 10/11 compatibility.
4. PySide6 desktop UI.
5. Webcam device discovery.
6. Camera-selection control.
7. Live webcam preview.
8. Camera capture outside the Qt UI thread.
9. Capture FPS measurement.
10. Display/output FPS measurement.
11. Basic frame-processing latency measurement.
12. Graceful handling of camera disconnect/failure.
13. Clean application shutdown.
14. Structured logging.
15. Central configuration/settings abstraction.
16. pytest test infrastructure.
17. Small command-line camera diagnostic tool.
18. README instructions for installation, execution, testing, and diagnostics.

CPU and memory metrics may also be included if they can be added without complicating the architecture.

---

# Architectural Requirement

Milestone 0 must establish the foundation for this eventual pipeline:

```text
Camera Capture
      │
      ▼
Latest Frame
      │
      ▼
Tracking
      │
      ▼
Gaze Estimation
      │
      ▼
Gaze Correction
      │
      ▼
Compositing
      │
      ├────────► Preview
      │
      ▼
Virtual Camera
```

Milestone 0 implements only the foundation required before `Tracking`.

The architecture must allow later processing stages to be inserted without rewriting camera capture or UI lifecycle management.

A reasonable conceptual separation is:

```text
Frame Source
    ↓
Latest-Frame Buffer
    ↓
Frame Processor
    ↓
Frame Consumers
```

where future processing can later become:

```text
Capture
  ↓
Tracking
  ↓
Gaze
  ↓
Correction
  ↓
Compositing
```

This is a conceptual requirement, not permission to build an unnecessary framework.

Prefer simple, focused interfaces.

Avoid premature abstraction.

---

# Real-Time / Buffering Requirement

Freshness is more important than processing every frame.

Future gaze processing may occasionally take longer than the camera frame interval.

The application must therefore avoid accumulating stale frames.

Prefer:

```text
latest frame wins
```

rather than:

```text
capture → queue → queue → queue → process every frame
```

Do not use an unbounded frame queue.

A bounded queue of size one, overwrite buffer, or equivalent latest-frame mechanism is acceptable.

Document:

- how frames move from capture to consumer,
- what happens if the consumer is slower than capture,
- how stale frames are discarded,
- whether frame ownership/copying is required for thread safety.

---

# Threading Requirement

Qt's main/UI thread must not perform blocking webcam reads.

Camera capture must occur outside the Qt UI thread.

The implementation must make lifecycle behavior explicit for:

```text
start
running
temporary capture failure
camera change
disconnect
stop
application shutdown
```

Do not leave worker threads running after the application exits.

Avoid unsafe cross-thread UI access.

Use Qt signals/slots or another safe mechanism for communicating with the UI.

---

# Hardware Constraint

Target development hardware is approximately:

```text
Windows laptop
Intel Core i7
Intel Iris Xe
No NVIDIA GPU
```

The implementation must not require:

- CUDA,
- NVIDIA libraries,
- RTX hardware,
- Windows Studio Effects,
- Copilot+ hardware,
- an NPU,
- cloud services.

All webcam data must remain local.

---

# Dependencies

Expected Milestone 0 dependencies are approximately:

```text
PySide6
OpenCV
NumPy
pytest
```

`psutil` may be added for diagnostics if useful.

Do not install future-milestone dependencies such as MediaPipe, ONNX Runtime, or pyvirtualcam merely because they appear in the full PRD.

Before adding a significant dependency:

1. verify Windows support,
2. verify Python 3.11+ compatibility,
3. prefer mature and actively maintained packages,
4. avoid unnecessary dependencies,
5. record its purpose,
6. record its license if material.

If proposing a significant technology change, first document:

```text
Problem
Alternative
Trade-off
Recommendation
```

and only make the change when it does not conflict with the PRD.

---

# Windows Camera Backend

Investigate the appropriate OpenCV camera backend for Windows.

At minimum consider:

```text
cv2.CAP_MSMF
cv2.CAP_DSHOW
```

Choose a sensible Windows default and implement documented fallback behavior when appropriate.

Do not hard-code the architecture around camera index `0`.

Camera selection must be represented independently from source-code edits.

Be careful when describing camera discovery.

OpenCV probing of numerical indexes does not necessarily provide authoritative Windows device enumeration.

If the implementation uses index probing, document that limitation accurately rather than claiming true OS-level enumeration.

Do not claim a camera exists unless opening/validation supports that conclusion.

---

# UI

The Milestone 0 UI should be intentionally simple.

Minimum conceptual layout:

```text
┌─────────────────────────────────────┐
│ GazeFix                             │
├─────────────────────────────────────┤
│                                     │
│            Camera Preview           │
│                                     │
├─────────────────────────────────────┤
│ Camera: [ device selector ▼ ]       │
│                                     │
│ Capture FPS: xx.x                   │
│ Display FPS: xx.x                   │
│ Processing: xx.x ms                 │
│                                     │
│ Status: Running                     │
└─────────────────────────────────────┘
```

UI responsiveness is more important than visual polish.

Do not implement future product controls such as:

- correction strength,
- calibration,
- Eye Contact ON/OFF,
- virtual-camera controls.

Those belong to later milestones.

---

# Camera Switching

Changing the selected camera must not require restarting the application.

The lifecycle should safely:

```text
stop old capture
release old camera
open selected camera
resume capture
update status
```

Failures should leave the application in a recoverable state rather than crashing.

---

# Error Handling

Handle at least:

- no camera available,
- invalid camera selection,
- selected camera cannot be opened,
- camera disconnects,
- individual frame read temporarily fails,
- repeated frame-read failure,
- application closes while capture is active,
- camera changes while capture is active.

Do not allow camera failures to terminate the process without a useful error message.

Temporary capture failure should not immediately destroy the application state.

Avoid infinite high-CPU retry loops.

---

# Instrumentation

At minimum measure:

```text
capture FPS
display FPS
frame-processing time
```

If practical, also expose:

```text
CPU usage
memory usage
dropped/replaced frames
```

Clearly define what each metric measures.

For example:

```text
capture FPS
= successfully captured frames per second

display FPS
= frames actually presented to the UI per second

processing latency
= time spent in the current processing stage,
  excluding arbitrary queue wait time
```

Do not report theoretical values as measured performance.

No telemetry may leave the machine.

---

# Processing Stage

Milestone 0 has no actual computer-vision processing.

However, create a lightweight place in the pipeline where later processing can be inserted.

For Milestone 0, the processor may effectively behave like:

```python
output_frame = input_frame
```

Do not create placeholder implementations for gaze algorithms.

The purpose is only to verify data flow and measure basic pipeline overhead.

---

# Testing

Create meaningful automated tests for components that do not require webcam hardware.

Good candidates include:

- configuration,
- latest-frame buffering behavior,
- lifecycle/state logic where separated from hardware,
- metric calculations,
- utility functions.

Test the important real-time invariant:

> When producers outrun consumers, old frames do not accumulate indefinitely.

Do not create fake or trivial tests merely to increase test count.

Hardware-dependent functionality belongs in:

- the diagnostic script,
- documented manual verification,
- runtime verification.

Tests must not fail simply because CI has no webcam.

---

# Camera Diagnostic Tool

Provide:

```text
python scripts/camera_test.py
```

or an equivalent documented command.

It should help diagnose, where technically possible:

- candidate camera indexes/devices,
- whether each candidate opens,
- backend requested,
- backend actually reported by OpenCV,
- negotiated width,
- negotiated height,
- negotiated FPS,
- observed FPS over a short capture sample,
- frame-read failures.

If true Windows camera names cannot be reliably retrieved using the chosen mechanism, report candidates accurately instead of inventing device names.

The tool should exit cleanly and release cameras.

---

# Logging

Use standard structured/local logging appropriate for a desktop prototype.

Logs should include enough context to diagnose:

- camera open/close,
- backend selection,
- camera switch,
- capture failure,
- worker lifecycle,
- shutdown errors.

Do not log raw webcam frames.

Do not introduce cloud logging.

---

# Configuration

Create a central settings/configuration abstraction.

It should be suitable for future settings such as:

```text
camera
resolution
FPS target
processing options
development diagnostics
```

Do not build a complex configuration framework.

Milestone 0 only needs enough structure to avoid scattering magic constants throughout the code.

---

# Repository Quality

Keep modules focused.

Do not place the entire application in `main.py`.

Use type hints where they improve clarity.

Use docstrings where behavior is non-obvious.

Keep platform-specific behavior localized where practical.

Avoid:

- enterprise architecture,
- unnecessary dependency injection frameworks,
- generic plugin frameworks,
- speculative abstractions for future ML models.

We need clean seams for future CV stages, not maximum abstraction.

---

# Documentation

Update `README.md` with exact instructions for:

```text
environment setup
dependency installation
running the application
running tests
running camera diagnostics
```

Document any Windows-specific notes.

If architectural behavior is non-obvious, add a concise architecture document under:

```text
docs/
```

Short ADRs may be added under:

```text
docs/decisions/
```

for decisions that materially affect future milestones.

Do not create ADRs for trivial implementation choices.

---

# Execution Procedure

Work directly in the repository.

Follow this sequence:

1. inspect repository and git state,
2. inspect existing code/configuration,
3. identify available Python version,
4. identify execution-platform limitations,
5. identify missing dependencies,
6. implement Milestone 0,
7. run automated tests,
8. run static/import validation where useful,
9. launch the application where the environment permits,
10. run camera diagnostics where the environment permits,
11. fix defects discovered during verification,
12. inspect the final diff,
13. verify no unrelated files were unintentionally modified,
14. produce the engineering report.

Do not stop after proposing code if you have repository/file access.

Actually modify the repository and execute verification commands.

---

# Verification Policy

Distinguish carefully between:

```text
CODE VERIFIED
```

and:

```text
RUNTIME VERIFIED
```

and:

```text
PHYSICAL HARDWARE VERIFIED
```

Examples:

A unit test proving latest-frame-buffer behavior does **not** verify webcam capture.

Successful module import does **not** verify the GUI launches.

Successful GUI launch on Linux does **not** verify Windows behavior.

Mock camera tests do **not** verify a physical webcam.

Do not infer verification.

If your environment cannot access:

- Windows,
- a graphical desktop,
- or physical webcam hardware,

state that limitation explicitly.

A limitation of your execution environment does not automatically mean the implementation failed.

---

# Completion Gate

Milestone 0 may be marked **PASS** only when sufficient evidence exists that:

- the application launches,
- UI remains responsive,
- camera capture is asynchronous,
- camera selection does not require source-code changes,
- live preview works with physical webcam hardware,
- application shutdown is clean,
- automated tests pass,
- architecture does not assume NVIDIA hardware.

If physical webcam or Windows GUI verification cannot actually be performed, use:

```text
PASS WITH LIMITATIONS
```

when the implementation and non-hardware verification are otherwise satisfactory.

Do not mark:

```text
Physical webcam capture: VERIFIED
```

unless you actually observed frames from physical webcam hardware.

Do not fabricate benchmark results.

---

# Final Engineering Report

When Milestone 0 work is complete, stop and return exactly the following report structure.

## Milestone Status

PASS / PASS WITH LIMITATIONS / FAIL

## What Was Implemented

Concise summary.

## Repository Changes

List important files/modules created or modified.

## Architecture

Explain:

- camera capture lifecycle,
- thread model,
- frame buffering strategy,
- processing-stage seam,
- UI update path,
- camera-switch behavior.

## Dependencies

For each important dependency:

```text
name
version/range
purpose
license if material
```

## How to Run

Exact setup and execution commands.

## Tests

Report:

```text
tests executed
tests passed
tests failed
```

Include relevant failure details.

## Runtime Verification

Report separately:

```text
Application launch:
Camera discovery:
Physical webcam capture:
Preview:
Camera switching:
Clean shutdown:
```

For each use:

```text
VERIFIED
NOT VERIFIED
FAILED
```

Do not infer successful verification.

## Performance

Report only measurements actually observed:

```text
resolution
capture FPS
display FPS
frame processing latency
CPU usage
memory usage
```

Use:

```text
NOT MEASURED
```

for unavailable metrics.

Do not fabricate values.

## Known Limitations

List real limitations.

## Technical Risks for Milestone 1

Identify anything that may affect face/eye tracking.

Pay particular attention to:

- frame format,
- frame ownership/copying,
- camera backend behavior,
- resolution stability,
- threading,
- performance headroom.

## Recommendation

Choose exactly one:

```text
PROCEED TO MILESTONE 1
ITERATE ON MILESTONE 0
CHANGE TECHNICAL APPROACH
```

Explain why in a few sentences.

Then stop.

Do not begin Milestone 1 until the Product Manager provides the next assignment.