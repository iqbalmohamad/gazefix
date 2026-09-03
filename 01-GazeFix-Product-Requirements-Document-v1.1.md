# GazeFix — Product Requirements Document v1.1

**Version:** 1.1  
**Updated:** 2026-09-03  
**Revision scope:** Clarifies real-time pipeline principles, Milestone 0 acceptance criteria, dependency timing, camera discovery expectations, milestone verification semantics, and virtual-camera compatibility gates. Product vision and MVP scope are unchanged.

## 1. Product Summary

**Product name:** GazeFix  
**Platform:** Windows 10/11  
**Product type:** Real-time virtual camera / gaze-redirection application  
**Primary user:** Individual professionals using Zoom, Google Meet, Microsoft Teams, and similar video-call applications.

### Product statement

GazeFix is a Windows desktop application that makes a user's gaze appear closer to the webcam during live video calls even when the user is naturally looking at another person, notes, or content displayed on their monitor.

The application processes webcam video locally, redirects the user's eye gaze toward the camera in real time, and exposes the corrected video as a camera source usable by standard video-conferencing applications.

---

# 2. Problem

During video calls, there is an unavoidable conflict between:

1. looking at the person on screen, and
2. looking into the webcam.

When a user looks at the other participant's face on screen, their eyes appear to look downward or sideways from the camera's perspective.

This creates weaker perceived eye contact.

The problem becomes more noticeable when:

- reading notes,
- interviewing,
- presenting,
- answering technical questions,
- using a large monitor,
- or positioning the webcam significantly above the content being viewed.

Existing solutions are limited:

- NVIDIA Broadcast requires compatible NVIDIA hardware.
- Windows Studio Effects requires supported NPU hardware.
- Enterprise products may not be available to individuals.
- Post-processing tools do not work for live video calls.
- Most interview copilots help with content but do not correct gaze.

GazeFix should solve this locally on a normal Windows laptop without requiring an NVIDIA GPU.

---

# 3. Product Vision

The ideal experience is:

```text
Integrated Webcam
        │
        ▼
     GazeFix
        │
        ▼
Natural gaze redirection
        │
        ▼
GazeFix Virtual Camera
        │
   ┌────┼─────┐
   ▼    ▼     ▼
 Zoom  Meet  Teams
```

The user should be able to continue looking naturally at the screen.

The other participant should perceive the user's gaze as closer to camera-facing eye contact.

The resulting video should not look synthetic or uncanny.

---

# 4. Product Principles

The primary product principle is:

> Natural eye contact is more important than perfect eye contact.

GazeFix must therefore prefer subtle correction over aggressive redirection.

The application should never attempt to force the user's eyes toward the camera under every condition.

The second product principle is:

> Continuity of video is more important than gaze correction.

If tracking, gaze estimation, correction, or compositing fails or becomes unreliable, GazeFix must preserve a usable video stream by reducing correction, disabling correction, or falling back to the original frame.

The application must not freeze the video stream merely to preserve correction.

---

# 5. Primary User Scenario

A user is participating in a remote job interview.

Their laptop webcam is positioned above the screen.

The interviewer appears near the center of the display.

The user naturally looks at:

- the interviewer,
- diagrams,
- notes,
- or other content on the screen.

Without GazeFix, their eyes visibly point below the webcam.

With GazeFix enabled, their gaze is partially redirected so that they appear to maintain more natural eye contact.

The user's head position, blinking, facial expression, lighting, and identity should remain unchanged.

---

# 6. Core User Journey

## First launch

User opens GazeFix.

GazeFix discovers or validates available camera sources.

User selects:

```text
Integrated Camera
```

The live camera preview appears.

---

## Calibration

User clicks:

```text
Calibrate
```

The application guides the user through a short calibration process.

The user looks:

1. directly at the webcam,
2. at the center of the screen,
3. slightly downward,
4. slightly left/right.

GazeFix creates a local calibration profile.

---

## Normal usage

User enables:

```text
Eye Contact Correction
```

The live preview displays the corrected result.

User adjusts:

```text
Correction Strength
```

The user starts the virtual camera.

Inside Zoom, Meet, or Teams, the user selects:

```text
GazeFix Camera
```

or the virtual-camera backend being used by the MVP.

---

# 7. MVP Success Criteria

The MVP succeeds when all of the following are true:

### Functional

- Webcam can be selected.
- Live webcam preview works.
- Face and eye landmarks can be tracked.
- User gaze can be estimated.
- Gaze can be redirected toward a target.
- Correction strength can be adjusted.
- Correction is temporally stable.
- Calibration works.
- Corrected frames can be routed to a virtual camera.
- Zoom can consume the output.
- Google Meet can consume the output.
- Microsoft Teams can consume the output.

### Performance

Minimum target:

```text
Resolution: 1280 × 720
Frame rate: >= 24 FPS
Preferred frame rate: 30 FPS
End-to-end processing latency: < 100 ms
```

Preferred target:

```text
Processing latency: < 50 ms
```

### Hardware

The application must work on:

```text
Windows 10/11
Intel Core i7-class CPU
Intel Iris Xe integrated graphics
```

It must not require:

```text
CUDA
RTX
NVIDIA GPU
Copilot+ NPU
```

### Privacy

All video processing must occur locally.

No webcam frame may be transmitted to a remote server.

---

# 8. Non-Goals for MVP

The following are explicitly outside MVP scope:

- interview-answer generation,
- LLM integration,
- meeting transcription,
- teleprompter,
- face beautification,
- skin smoothing,
- background replacement,
- avatar generation,
- voice modification,
- cloud inference,
- user accounts,
- payments,
- subscription management,
- mobile support,
- macOS support.

These features must not be implemented unless explicitly approved by the Product Manager.

---

# 9. Product Requirements

## PR-1 — Camera Discovery

The application must discover or enumerate camera sources sufficiently for a user to select an available camera without modifying source code.

For the technical prototype, numerical OpenCV index probing is acceptable when reliable Windows device enumeration is unavailable. If used, it must validate candidate sources and document that index probing is not authoritative operating-system-level device enumeration.

Camera selection must not require modifying source code or configuration files by hand.

The architecture must not assume that camera index `0` is the only source.

On Windows, the capture implementation must evaluate appropriate OpenCV backends, including Media Foundation (`CAP_MSMF`) and DirectShow (`CAP_DSHOW`). It must choose and document a sensible default plus recoverable fallback behavior based on observed reliability; the product architecture must not be permanently coupled to one backend.

---

## PR-2 — Live Preview

The application must display live webcam video.

The preview UI must remain responsive.

Camera processing must not block the main UI thread.

---

## PR-3 — Face and Eye Tracking

The application must identify:

- facial landmarks,
- left eye,
- right eye,
- iris position where available,
- eyelid contour,
- face orientation.

Tracking must remain stable during normal head movement.

---

## PR-4 — Gaze Estimation

The system must estimate a user's approximate gaze direction.

At minimum:

```text
yaw
pitch
confidence
```

Optional:

```text
roll
```

The system does not need laboratory-grade gaze tracking.

The purpose is to determine how far the user's eyes are pointing away from the camera.

---

## PR-5 — Gaze Correction

The system must alter the eye region so that gaze appears closer to a configurable target.

Correction must support a strength parameter:

```text
0.0 → no correction

1.0 → maximum requested correction
```

Default target:

```text
camera direction
```

Correction must be interpolated rather than binary.

Conceptually:

```text
corrected_gaze =
source_gaze
+
strength × (target_gaze - source_gaze)
```

---

# 10. Correction Behavior

Correction strength must depend on gaze deviation.

Initial behavioral target:

```text
Deviation 0–5°
Very light correction

Deviation 5–15°
Normal correction

Deviation 15–25°
Stronger correction

Deviation 25–35°
Gradually reduce confidence/correction

Deviation >35°
Disable correction
```

Exact thresholds may change after testing.

The system should not attempt extreme gaze redirection.

---

# 11. Eye Region Constraints

For the MVP, changes should be limited primarily to the eye regions.

Do not modify the entire face unless a future model requires it and the Product Manager approves the change.

Preserve:

- eyebrows,
- skin,
- nose,
- mouth,
- face shape,
- facial expression,
- lighting,
- blink behavior.

Corrected regions must blend naturally with the original frame.

Hard rectangular masks are unacceptable.

---

# 12. Temporal Stability

The output must avoid:

- iris jitter,
- eye shaking,
- mask flickering,
- correction oscillation,
- sudden transitions.

The implementation should use temporal smoothing where appropriate.

Example:

```text
smoothed =
alpha × current
+
(1 - alpha) × previous
```

The exact smoothing strategy is an engineering decision.

---

# 13. Tracking Failure Behavior

If face or eye tracking temporarily fails:

1. Do not generate corrupted eyes.
2. Prefer the original camera frame.
3. Correction may fade out smoothly.
4. The call must continue.

The product must fail gracefully.

A failure in gaze processing must never freeze the webcam output.

This fallback behavior applies to all downstream processing stages:

```text
tracking confidence low
→ reduce or disable correction

gaze estimation unreliable
→ reduce or disable correction

correction or compositing error
→ output the original frame

processing overload
→ discard stale frames and preserve stream continuity
```

---

# 14. Calibration

Calibration should require less than approximately 30 seconds.

Minimum calibration states:

### State A
Look directly at the webcam.

### State B
Look at the center of the monitor.

### State C
Look slightly downward.

### State D
Look slightly horizontally away from the camera.

The calibration should estimate the relationship between:

```text
camera-facing gaze
screen-facing gaze
user eye geometry
camera position
```

Profiles must be stored locally.

---

# 15. Model Strategy

GazeFix must not be architecturally tied to one gaze-correction implementation.

Define a stable model interface.

Conceptually:

```python
class GazeCorrectionEngine:

    def initialize(self):
        ...

    def estimate_gaze(self, frame, landmarks):
        ...

    def correct(
        self,
        frame,
        landmarks,
        source_gaze,
        target_gaze,
        strength
    ):
        ...

    def shutdown(self):
        ...
```

Potential implementations:

```text
GeometricGazeEngine
NeuralGazeEngine
```

The rest of the application should not care which implementation is active.

---

# 16. Model Development Strategy

Do not train a neural network from scratch during the first implementation phase.

The engineering priority is:

1. establish the complete video pipeline,
2. prove gaze estimation,
3. prove visible gaze redirection,
4. establish performance,
5. evaluate existing neural models,
6. replace the correction engine later if visual quality requires it.

Model quality should improve incrementally without requiring application rewrites.

---

# 17. Inference Strategy

Initial inference target:

```text
CPU
```

Preferred technology:

```text
ONNX Runtime
```

Future acceleration may use:

```text
DirectML
```

The application must automatically fall back to CPU when acceleration is unavailable.

CUDA must not be assumed.

---

# 18. Video Processing Architecture

The application should use a low-latency asynchronous pipeline.

Conceptually:

```text
Camera Capture
      │
      ▼
Latest Frame Buffer
      │
      ▼
Face / Eye Tracking
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
      ├────────► UI Preview
      │
      ▼
Virtual Camera
```

Do not create an unbounded processing queue.

If processing becomes slower than capture:

> Drop old frames rather than increasing latency.

Real-time freshness is more important than processing every frame.

This is a product-level technical constraint:

> GazeFix must prefer the newest available frame over guaranteed processing of every captured frame.

No pipeline stage may introduce an unbounded video-frame queue.

The architecture should maintain a simple conceptual separation:

```text
Frame Source
      │
      ▼
Latest-Frame Buffer
      │
      ▼
Frame Processor
      │
      ▼
Frame Consumers
```

Camera capture must not be tightly coupled to the PySide UI. Later milestones must be able to replace a passthrough processor with tracking, gaze estimation, correction, and compositing without rewriting camera capture or UI lifecycle management.

An overwrite buffer, bounded queue of size one, or equivalent latest-frame mechanism is acceptable. Each implementation must document:

- what happens when a consumer is slower than capture,
- how stale frames are discarded,
- how frame ownership or copying remains thread-safe,
- and how the application shuts down without leaving workers active.

---

# 19. Virtual Camera

The architecture must abstract virtual-camera output.

Example interface:

```python
class VirtualCameraBackend:

    def start(self, width, height, fps):
        ...

    def send_frame(self, frame):
        ...

    def stop(self):
        ...
```

Possible implementations:

- OBS Virtual Camera,
- pyvirtualcam-compatible backend,
- DirectShow virtual camera,
- Windows Media Foundation virtual camera.

The MVP should use whichever solution provides the fastest reliable proof of concept.

A custom GazeFix Windows virtual-camera driver is not required for the first MVP.

---

# 20. UI Requirements

The MVP UI should remain minimal.

Example:

```text
┌────────────────────────────────────────┐
│ GazeFix                                │
├────────────────────────────────────────┤
│                                        │
│           Live Preview                 │
│                                        │
│                                        │
├────────────────────────────────────────┤
│ Camera                                 │
│ [ Integrated Camera ▼ ]                │
│                                        │
│ Eye Contact                            │
│ [ ON ]                                 │
│                                        │
│ Correction Strength                    │
│ [──────────●────────] 60%               │
│                                        │
│ [ Calibrate ]                          │
│                                        │
│ Output                                 │
│ [ Start Virtual Camera ]               │
│                                        │
│ 29 FPS   |   43 ms                     │
└────────────────────────────────────────┘
```

The UI should expose only controls useful to the user.

Engineering/debug controls should be hidden behind a development mode.

---

# 21. Diagnostics

Development builds must expose:

```text
Capture FPS
Output FPS
Capture latency
Tracking latency
Gaze-estimation latency
Correction latency
Compositing latency
Total processing latency
Dropped frames
CPU usage
Memory usage
Inference provider
```

This information does not need to appear in the final consumer UI.

---

# 22. Technology Preferences

The initial preferred stack is:

```text
Python 3.11+
PySide6
OpenCV
MediaPipe
ONNX Runtime
NumPy
pyvirtualcam / OBS integration
pytest
```

This is a preference, not an absolute requirement.

Preferred dependencies must be introduced only in the milestone that requires them. In particular:

```text
M0 foundation
PySide6, OpenCV, NumPy, pytest
Optional: psutil for lightweight local diagnostics

Tracking milestone
MediaPipe or another approved tracking implementation

Neural inference milestone
ONNX Runtime when neural evaluation actually begins

Virtual-camera milestone
pyvirtualcam and/or OBS integration when output integration begins
```

Milestone 0 must not install MediaPipe, ONNX Runtime, pyvirtualcam, or other future-milestone dependencies unless a concrete M0 requirement makes them necessary.

Claude may propose alternatives when there is a clear technical reason.

Any significant stack change must be explained before implementation.

---

# 23. Proposed Repository Structure

```text
gazefix/
│
├── README.md
├── pyproject.toml
├── requirements.txt
│
├── app/
│   ├── main.py
│   │
│   ├── camera/
│   │   ├── capture.py
│   │   └── devices.py
│   │
│   ├── tracking/
│   │   ├── face_tracker.py
│   │   ├── eye_landmarks.py
│   │   └── gaze_estimator.py
│   │
│   ├── correction/
│   │   ├── engine.py
│   │   ├── geometric.py
│   │   ├── neural.py
│   │   ├── masks.py
│   │   └── compositor.py
│   │
│   ├── calibration/
│   │   ├── controller.py
│   │   └── profile.py
│   │
│   ├── pipeline/
│   │   ├── processor.py
│   │   └── frame_buffer.py
│   │
│   ├── output/
│   │   ├── virtual_camera.py
│   │   └── obs_backend.py
│   │
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── preview.py
│   │   └── calibration_dialog.py
│   │
│   ├── diagnostics/
│   │   ├── metrics.py
│   │   └── logging.py
│   │
│   └── config/
│       └── settings.py
│
├── models/
│   └── README.md
│
├── tests/
│
├── scripts/
│   ├── camera_test.py
│   ├── pipeline_benchmark.py
│   └── model_benchmark.py
│
└── docs/
    ├── architecture.md
    ├── decisions/
    └── experiments/
```

Claude may adjust this structure when justified.

Major architectural changes should be documented through short ADRs under:

```text
docs/decisions/
```

---

# 24. Development Milestones

## M0 — Technical Foundation

Outcome:

A stable Windows desktop application capable of capturing and displaying webcam video.

Deliverables:

- clean Python 3.11+ project structure,
- Windows 10/11-compatible dependency setup,
- camera-source discovery or validated candidate probing,
- camera selection without source-code edits,
- safe camera switching without restarting the application,
- responsive live preview,
- camera capture outside the Qt UI thread,
- latest-frame buffering with no unbounded frame queue,
- a lightweight passthrough processing-stage seam,
- capture FPS measurement,
- display/output FPS measurement,
- frame-processing latency measurement,
- graceful handling of camera open, read, disconnect, and switching failures,
- clean worker and application shutdown,
- structured local logging,
- central settings/configuration abstraction,
- meaningful hardware-independent pytest coverage,
- command-line camera diagnostic tool,
- README instructions for setup, execution, testing, and diagnostics.

No AI functionality.

Acceptance criteria:

- the UI remains responsive during capture,
- blocking webcam reads do not occur on the Qt UI thread,
- producers cannot accumulate stale frames indefinitely when consumers are slower,
- camera failures leave the application in a recoverable state,
- automated tests do not require physical webcam hardware,
- and the implementation does not assume NVIDIA, CUDA, an NPU, Windows Studio Effects, or cloud services.

M0 verification must distinguish implementation evidence from actual Windows GUI and physical-webcam execution. Lack of target hardware in the engineering environment may produce `PASS WITH LIMITATIONS`; it must not be reported as physical verification.

---

## M1 — Face and Eye Tracking

Outcome:

Stable facial and eye landmark tracking.

Deliverables:

- face detection,
- eye landmarks,
- iris landmarks if available,
- head-pose information where useful,
- tracking confidence,
- debug overlay.

---

## M2 — Gaze Estimation

Outcome:

The system estimates approximate eye direction.

Deliverables:

```text
yaw
pitch
confidence
```

Calibration is not required yet.

---

## M3 — Offline Gaze Correction Prototype

Outcome:

Prove that gaze can be visually redirected.

Input may initially be:

- still image,
- recorded frame,
- prerecorded short video.

The purpose is visual experimentation without real-time constraints.

Deliverables:

- geometric correction prototype,
- configurable correction strength,
- soft blending,
- before/after output.

This milestone is a major quality gate.

---

## M4 — Real-Time Gaze Correction

Outcome:

Integrate correction with live webcam frames.

Acceptance target:

```text
>= 20 FPS development prototype
```

The product does not yet need virtual-camera output.

---

## M5 — Temporal Stabilization

Outcome:

Real-time output appears stable during:

- blinking,
- speaking,
- minor head motion,
- normal eye motion.

---

## M6 — Calibration

Outcome:

User-specific correction improves based on camera/screen geometry.

---

## M7 — Performance Optimization

Outcome:

Target:

```text
720p
>= 24 FPS
< 100 ms processing latency
```

Test CPU first.

Then evaluate DirectML if beneficial.

---

## M8 — Virtual Camera Integration

Outcome:

Corrected frames can be emitted through a virtual-camera path and selected by at least one supported conferencing client.

M8 technical acceptance requires verified output in at least one of:

- Zoom,
- Google Meet,
- Microsoft Teams.

Full MVP acceptance still requires compatibility verification with all three clients. A client-specific issue may therefore result in M8 `PASS WITH LIMITATIONS` while remaining an open requirement for M10/productization and the MVP gate.

---

## M9 — Neural Model Evaluation

Outcome:

Evaluate whether an existing neural gaze-redirection model materially improves quality.

A neural model should only replace the geometric implementation if:

1. license permits usage,
2. latency is acceptable,
3. quality improvement is obvious,
4. hardware requirements remain acceptable.

---

## M10 — Productization

Potential work:

- installer,
- system tray,
- saved settings,
- auto-start,
- error recovery,
- production logging,
- optional custom virtual camera.

Not part of the initial technical proof.

---

# 25. Milestone Gate Rules

Claude must not automatically proceed across major milestone boundaries.

At the end of each milestone, provide the Product Manager with:

### Status

```text
PASS
PASS WITH LIMITATIONS
FAIL
```

Use these definitions:

```text
PASS
All milestone acceptance criteria have been verified in an environment
capable of exercising them.

PASS WITH LIMITATIONS
The implementation and all available verification pass, but one or more
acceptance criteria could not be runtime- or hardware-verified because of
execution-environment limitations or a clearly documented compatibility gap.

FAIL
One or more required acceptance criteria are known to fail, or the
implementation is materially incomplete.
```

### Evidence

- functionality completed,
- test results,
- screenshots or recordings when useful,
- benchmark results,
- known limitations.

Evidence must separate the following verification levels:

```text
Implementation verified
Code structure, automated tests, static checks, or isolated behavior support
the claim.

Runtime verified
The relevant application behavior was actually executed in a capable runtime.

Physical hardware verified
The behavior was actually observed using the target physical device or hardware.
```

These levels are not interchangeable. For example:

- a unit test of a frame buffer does not verify physical webcam capture,
- a successful import does not verify GUI launch,
- a GUI launch outside Windows does not verify Windows runtime behavior,
- mock camera tests do not verify a physical webcam,
- and a virtual-camera implementation does not verify Zoom, Meet, or Teams compatibility unless the relevant client was actually exercised.

Every milestone report must mark relevant runtime items as:

```text
VERIFIED
NOT VERIFIED
FAILED
```

Unavailable measurements must be reported as `NOT MEASURED`. Engineers must not infer successful verification or fabricate benchmark values.

### Recommendation

Claude should recommend:

```text
PROCEED
ITERATE
CHANGE APPROACH
```

The Product Manager decides whether to continue.

---

# 26. Engineering Decision Policy

Claude owns normal implementation decisions.

Claude should not request approval for trivial choices such as:

- variable names,
- helper functions,
- module boundaries,
- ordinary refactoring.

Claude must escalate decisions that materially affect:

- product scope,
- hardware requirements,
- privacy,
- licensing,
- architecture,
- user experience,
- paid dependencies,
- cloud dependencies,
- removal of acceptance criteria.

When escalating, present:

```text
Problem
Options
Trade-offs
Recommendation
```

Do not simply ask an open-ended question.

---

# 27. Dependency and Licensing Policy

Before adopting a major dependency or pretrained model, verify:

- active project status,
- Windows compatibility,
- Python/runtime compatibility,
- CPU compatibility,
- license,
- redistribution restrictions,
- model licensing separately from code licensing.

No dependency requiring a commercial license may be silently introduced.

No research-only model may be treated as production-ready without flagging the restriction.

Dependencies should be added only when the active milestone needs them. A package's presence in the preferred technology stack is not, by itself, a reason to install or ship it early.

---

# 28. Product Quality Test Matrix

Eventually test the gaze engine against:

### Gaze deviation

```text
5°
10°
15°
20°
25°
30°
```

### Conditions

```text
normal lighting
low lighting
bright lighting
glasses
no glasses
blinking
speaking
smiling
minor head rotation
moderate head rotation
```

### Visual scoring

Rate 1–5:

```text
eye realism
iris realism
blink realism
eyelid preservation
identity preservation
temporal stability
artifact visibility
perceived eye contact
```

---

# 29. MVP Definition of Done

The MVP is complete when the following workflow works reliably:

```text
Launch GazeFix
      ↓
Select webcam
      ↓
See live preview
      ↓
Complete calibration
      ↓
Enable eye-contact correction
      ↓
Look at content on screen
      ↓
Preview shows natural partial gaze redirection
      ↓
Start virtual camera
      ↓
Select GazeFix output in Zoom/Meet/Teams
      ↓
Remote participant sees corrected video
```

Required:

```text
Windows
Intel i7
Intel Iris Xe
720p
>= 24 FPS
< 100 ms processing latency
local-only processing
no NVIDIA dependency
```

The most important acceptance criterion is:

> The corrected eyes look natural enough that the correction itself is less distracting than the original lack of eye contact.

---

# 30. Roles

## Product Manager — ChatGPT

The Product Manager owns:

- product scope,
- priorities,
- acceptance criteria,
- UX decisions,
- milestone approval,
- product trade-offs,
- interpretation of user needs.

## Software Engineer — Claude

Claude owns:

- implementation,
- technical design within product constraints,
- coding,
- tests,
- debugging,
- profiling,
- technical documentation,
- technical recommendations.

When product intent is ambiguous, Claude should describe the ambiguity and provide a recommended interpretation rather than silently changing scope.

---

# 31. Current Product Priority

The immediate priority is NOT to build the entire application.

The immediate priority is:

> Prove that the foundational real-time Windows camera pipeline is stable enough to support later computer-vision processing.

Therefore the first engineering assignment is Milestone 0 only.
