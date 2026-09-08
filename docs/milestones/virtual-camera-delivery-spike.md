# Pre-M8 virtual-camera delivery spike — governance authorization

**Status: `PRE-M8 VIRTUAL-CAMERA DELIVERY SPIKE AUTHORIZED`**

**PM authorization recorded: 2026-09-08. Disposable feasibility experiment only.**

This document authorizes the bounded scope for a future implementation
assignment. This governance task does not implement or execute the spike.
**Spike execution: NOT TESTED. No spike verdict is assigned by this update.**
The spike is independent of the correction backend and is not M8 implementation.

## Prior research and decision provenance

Prior research verdict: **`CONDITIONAL PASS`**.

Required follow-up: **`IS A PRE-M8 TECHNICAL SPIKE REQUIRED? YES`**.

These are the completed research findings supplied by the Product Manager in
the 2026-09-08 assignment, "GazeFix — Authorize Bounded Pre-M8 Virtual-Camera
Technical Spike". The verified base is
`codex/virtual-camera-feasibility-governance` at
`67e467ee08e958e4a620273272e0c9532e9b62dd`. Its
`docs/milestones/virtual-camera-integration-feasibility.md` records the earlier
desk-research authorization and says the research outcome is not yet assessed;
it is not the completed research report. No completed report is present in
that inspected base. This update records the PM-supplied outcome without
reconstructing a report, inventing citations or runtime evidence, or altering
the earlier research record or any evaluation evidence.

The PM-supplied research establishes the following basis for the spike:

- Windows has credible camera-device mechanisms for the intended GazeFix UX.
- Windows 11 build 22000+ has the native `MFCreateVirtualCamera` /
  `IMFVirtualCamera` route. That route does not cover Windows 10.
- Windows 10 needs a separate candidate path; a minimal DirectShow source is
  the recommended first compatibility probe.
- Zoom explicitly supports virtual-camera software. Google Meet and Microsoft
  Teams expose ordinary camera-device selection.
- Documentation alone does not establish GazeFix-specific enumeration,
  playback, media negotiation, recovery, installation, or multi-consumer
  behavior. These remain UNKNOWN until applicable spike evidence exists.

The PM now authorizes **`PRE-M8 VIRTUAL-CAMERA DELIVERY SPIKE`** to investigate
those unknowns. This is no Product Strategy decision, backend selection,
production acceptance, or change to Windows 10/11 product scope.

## Authorized mechanism and frame-source scope

### Windows 11 leg

The future implementation assignment may build only the minimum code required
for a Windows 11 build 22000+ virtual camera using `MFCreateVirtualCamera`,
`IMFVirtualCamera`, and a minimal custom Media Foundation source where required.

The required source is deterministic synthetic moving frames with a visible
frame counter, timestamp, and asymmetric visual elements for orientation and
mirroring checks. Unmodified physical-webcam frames may optionally be tested
as a second source. Synthetic moving-frame proof remains required.
**No gaze correction may be used.**

### Windows 10 leg

Authorize a separate minimal compatibility probe using a **user-mode
DirectShow capture-source filter as the first candidate**, with the same
synthetic source requirements and optional unmodified webcam passthrough.
Do not treat Windows 11 native API evidence as Windows 10 evidence.

A material Windows 10 failure **stops that leg** and returns the findings to
the Product Manager for a mechanism/scope decision. Do not automatically
implement AVStream, a Frame Server driver route, or a UMDF/KMDF driver route.
No failure or verdict authorizes a substitute mechanism or removes Windows 10
from product scope. The independent Windows 11 leg remains within its bounds.

## Consumer matrix and media proof

Test the following routes explicitly on each OS leg, using current versions
at execution time and recording the actual versions:

| OS / mechanism | Consumer route |
| --- | --- |
| Windows 11 build 22000+ / native Microsoft virtual camera | Zoom Workplace desktop |
| Windows 11 build 22000+ / native Microsoft virtual camera | Google Meet in Chrome |
| Windows 11 build 22000+ / native Microsoft virtual camera | Google Meet in Edge |
| Windows 11 build 22000+ / native Microsoft virtual camera | Microsoft Teams work/school desktop |
| Windows 10 / user-mode DirectShow capture-source filter | Zoom Workplace desktop |
| Windows 10 / user-mode DirectShow capture-source filter | Google Meet in Chrome |
| Windows 10 / user-mode DirectShow capture-source filter | Google Meet in Edge |
| Windows 10 / user-mode DirectShow capture-source filter | Microsoft Teams work/school desktop |

Target **1280×720 at 30 FPS**. Test only the minimum format combinations needed
to establish broad compatibility, beginning with **NV12** and **YUY2** as
supported by the chosen mechanism. Record requested and selected media types;
do not silently substitute a format, resolution, frame rate, mechanism, OS,
browser, or consumer. An unavailable configuration must remain visible in the
matrix with its reason.

Measure where technically available: fresh-frame cadence, source timestamps,
dropped/stale frame behavior, and producer-to-camera delivery delay. Record
measurement method, observation interval, and measurement boundaries so the
result can be interpreted. Unavailable measurements are **NOT MEASURED** with
the reason. Do not infer conferencing-network latency from camera delivery
measurements or infer remote delivery from a local preview.

## Bounded lifecycle and deployment probes

The spike may test:

- Open and close the camera; switch away and back; disable/re-enable video.
- Stop/restart the frame producer; repeated application open/close.
- Physical-webcam unplug/reconnect only when webcam passthrough is tested.
- Short multi-consumer probes, recording the consumer combination and outcome.

Deployment proof is limited to local install/registration, activation as a
normal user after installation, reboot persistence if applicable, and
uninstall/cleanup under normal Windows security settings. Record installation
privileges and the resulting registration/cleanup state separately from
normal-user activation. This does not authorize full installer/product
packaging or production driver qualification.

Do not disable **Secure Boot**, **normal camera permissions**, or **signing
enforcement** to manufacture a PASS. Record a security or permission blocker
as observed rather than bypassing it.

## Prohibited scope

Neither this authorization nor the future bounded spike permits:

- Gaze correction, Maxine integration, any neural model, cloud inference,
  `CorrectionEngine` changes, GazeFix production pipeline integration, or
  product UI integration.
- M4, M5, M6, M7, or M8 production implementation; opening M8; or any automatic
  milestone transition.
- Full installer/product packaging, Windows Store submission, production
  driver qualification, AVStream fallback, Frame Server driver fallback,
  or UMDF/KMDF driver fallback.
- A Zoom plugin, Teams app, browser extension, Meet-specific integration,
  OBS dependency, or external virtual-camera SDK integration.
- PRD changes, architecture changes, ADR creation, frozen-reference changes,
  a Windows 11-only product decision, or removal of Windows 10 support.
- Maxine Phase 1B research or implementation. Its separate future authority
  cannot be inferred from Phase 1A PASS or this provider-neutral experiment.
- Reopening Candidate Admission, model search/substitution/fallback,
  LivePortrait in any role, or altering research reports or evaluation evidence.
- Merging any PR.

This documentation/governance assignment additionally prohibits **all spike
implementation, virtual-camera code, product-code changes, installation,
registration, and runtime probes**. It delivers only the two documents named
below; the authorized experiment belongs to a future implementation assignment.

## Evidence deliverable and basic-delivery criteria

The future spike must produce a **versioned compatibility matrix** tied to the
tested spike commit/build and dated evidence. Keep all eight planned routes
visible, including routes not executed. For each tested configuration record:

- OS edition/build and CPU architecture; application/browser version; test date.
- Mechanism, enumerated camera name, source mode, requested media type, and
  selected media type (resolution, frame rate, pixel format).
- Local and remote visible playback results, advancing frame counter,
  orientation/mirroring and color observations, and evidence references.
- Available media measurements, unavailable measurement reasons, lifecycle
  recovery behavior, deployment/security conditions, and multi-consumer results.
- One route result from the statuses below, with the reason and any limitation.

| Route result | Use |
| --- | --- |
| `PASS` | Applicable basic-delivery criteria are demonstrated by recorded evidence. |
| `FAIL` | A tested route demonstrates failure of an applicable criterion. |
| `NOT TESTED` | The route or probe was not executed; state the evidence gap. |
| `NOT AVAILABLE` | The required environment or configuration was unavailable; state why. |

No silent substitution. Separate route results from overall spike verdicts
and from the PRD verification labels. Runtime and physical-hardware claims
remain NOT VERIFIED without applicable execution/observation evidence;
unavailable metrics remain NOT MEASURED, per `docs/qa-policy.md`.

A **Windows 11 basic-delivery PASS** requires all of the following:

1. The device enumerates normally and the consumer selects it without a
   special plugin.
2. Moving synthetic frames are visible remotely and the frame counter advances
   continuously.
3. Orientation and colors are correct.
4. No mandatory advanced capture override and no security bypass are required.
5. Switch-away/back and producer restart recover acceptably. Record observed
   recovery time, required user actions, and remaining failures so that
   acceptability can be assessed rather than asserted without evidence.

A **Windows 10 basic-delivery PASS** requires the same conditions using the
authorized DirectShow candidate. Optional webcam passthrough cannot replace
synthetic-frame proof. Short multi-consumer and other probes must report their
actual result without implying production robustness from limited execution.

These are disposable spike evidence criteria, **not a new M8 acceptance gate**.

## Spike verdict — select exactly one after execution

| Verdict | Definition |
| --- | --- |
| `PASS` | Basic delivery feasibility is demonstrated across every OS/product route actually required by the unchanged product scope. |
| `CONDITIONAL PASS` | The delivery path is viable, but a material product or mechanism condition remains, especially Windows 10 support. |
| `FAIL` | A load-bearing integration blocker is demonstrated. |
| `INCONCLUSIVE` | The spike was not executed sufficiently to establish a result. |

Identify the supporting matrix rows, material conditions/blockers, and missing
evidence. A subset of passing routes is not overall PASS if required routes
remain unproven. An unavailable Windows 10 environment does not narrow the
product scope. No verdict automatically opens M8, changes the PRD, or authorizes
another mechanism after a Windows 10 failure.

## Relationship to M8, Maxine, and Product Strategy

The original PRD and frozen architecture remain authoritative and unchanged.
The roadmap remains paused at M3 -> M4; **M4 remains BLOCKED** and **M8 remains
UNOPENED**. Existing M8 and MVP acceptance criteria remain unchanged. This
experiment retires delivery uncertainty only and does not adopt a production
mechanism, correction backend, or product strategy.

Maxine Phase 1A's supplied visual-gate PASS remains a bounded visual-feasibility
finding. Phase 1B realtime/streaming feasibility remains a separate track,
requiring its own PM authorization and gate; no Phase 1B work is authorized
here. No gaze correction, Maxine, or cloud processing is used by this spike.

An explicit **Product Strategy Gate** remains required after Phase 1B and
before any PRD revision or resumed milestone implementation where applicable.
Neither research nor spike verdicts substitute for that gate. Subsequent
roadmap work requires explicit PM authority; there is no automatic resumption.
Candidate Admission remains closed, LivePortrait remains rejected, and M3
remains `CHANGE APPROACH` — not PASS.

## Governance lineage and delivery verification

Base: `codex/virtual-camera-feasibility-governance` at
`67e467ee08e958e4a620273272e0c9532e9b62dd`, verified against fetched remote state
before editing. New branch: `codex/virtual-camera-delivery-spike-governance`.
This is the latest fetched appropriate governance lineage, not a base on
`main`. It retains `codex/maxine-phase1a-governance` at
`95678777642d29912d0806a81f02dc4b11ea884b` and the Phase 1A evaluation lineage
through `32836f9df8a222f3847306ca42b2e388e461cd83`.

All eleven frozen references listed in `Current Assignment.md` were verified
against their recorded SHAs before editing and must be checked again at
completion. No frozen reference or retained review/assignment lineage may be
advanced, rewritten, or merged into by this task.

The only changed files are `Current Assignment.md` and
`docs/milestones/virtual-camera-delivery-spike.md`. Verify that every other
tracked file is identical to the base, including the PRD, architecture/ADRs,
research records, evaluation evidence, and product code. Stop after the
documentation audit and delivery commit on the new governance branch; do not
execute the spike or merge any PR.
