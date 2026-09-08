# GazeFix — Current Engineering Assignment

**Active assignment: `PRE-M8 VIRTUAL-CAMERA DELIVERY SPIKE` — authorized for a
future bounded implementation assignment. This update is governance only.**

**Status: `PRE-M8 VIRTUAL-CAMERA DELIVERY SPIKE AUTHORIZED`**

**Prior research: `CONDITIONAL PASS`.**
**`IS A PRE-M8 TECHNICAL SPIKE REQUIRED? YES`**

**Spike execution: NOT TESTED. No spike verdict is assigned here.**

**The original PRD remains authoritative and unchanged. The primary roadmap
remains paused at the M3 -> M4 boundary. M4 remains BLOCKED. M8 remains UNOPENED.**

**`MAXINE PHASE 1A VISUAL GATE: PASS`** — previously supplied PO verdict;
its provenance and evidence limits remain recorded in
`docs/milestones/virtual-camera-integration-feasibility.md`.

**Maxine Phase 1B remains a separate track requiring its own future PM
authorization and gate. Neither its research nor implementation is authorized here.**

**Candidate Admission: FAIL — NO COMMERCIALLY ADMISSIBLE PRETRAINED PATH FOUND.**
The prior local/offline pretrained Candidate Admission cycle remains CLOSED;
see `docs/milestones/candidate-admission-closure.md`.

**LivePortrait remains REJECTED — COMMERCIAL/PROVENANCE GATE FAILED.**

**M0 / M1 / M2: PASS / CLOSED / FROZEN.**

**M3: `CHANGE APPROACH` — NOT PASS** (`docs/milestones/m3-evaluation.md`).
`m3-geometric-baseline @ f3831b54728a4747c38c064351ec9f48419a2efb` remains
frozen. **Overall architecture (`architecture-v1`): APPROVED / FROZEN /
CANONICAL**, unchanged.

**Updated: 2026-09-08.**

## PM authorization and current delivery boundary

The Product Manager authorizes **`PRE-M8 VIRTUAL-CAMERA DELIVERY SPIKE`**:
a disposable feasibility experiment independent of the correction backend.
The authoritative bounded scope, prohibitions, evidence requirements, and
verdict definitions are in
[`docs/milestones/virtual-camera-delivery-spike.md`](docs/milestones/virtual-camera-delivery-spike.md).

This repository assignment is **documentation/governance only**. Do not
implement or execute the spike, write virtual-camera or product code,
install/register a camera, begin M8, implement Maxine Phase 1B, modify the
PRD/architecture/frozen references, alter research or evaluation evidence,
or merge any PR. The minimal experiment below belongs to a future
implementation assignment; it is not production implementation authority.

The prior research completed with `CONDITIONAL PASS` and requires a pre-M8
technical spike, as supplied by the PM's 2026-09-08 request. The inspected
base contains the earlier research authorization, not a completed report.
The new spike document records that provenance explicitly. The earlier
research record remains untouched; no runtime finding is invented here.

## Authorized future spike at a glance

- **Windows 11 build 22000+:** minimal `MFCreateVirtualCamera` /
  `IMFVirtualCamera` route and minimal custom Media Foundation source where
  required.
- **Windows 10:** separate user-mode DirectShow capture-source filter as the
  first compatibility candidate. A material failure stops that leg and
  returns to the PM for a mechanism/scope decision. No automatic AVStream,
  Frame Server, or UMDF/KMDF fallback.
- **Source:** deterministic moving synthetic frames with visible counter,
  timestamp, and asymmetric orientation/mirroring markers; optionally
  unmodified webcam frames. No gaze correction.
- **Consumers on both OS legs:** current Zoom Workplace desktop, Google Meet
  in current Chrome, Google Meet in current Edge, and current Microsoft Teams
  work/school desktop. Record actual OS/build, CPU architecture, client/browser
  version, test date, camera name, selected media type, and visible playback.
- **Media:** target 1280×720 at 30 FPS; minimum compatibility formats beginning
  with NV12 and YUY2 as supported. Measure available fresh-frame cadence,
  source timestamps, dropped/stale frames, and producer-to-camera delivery
  delay. Do not infer conferencing-network latency.
- **Lifecycle:** camera open/close, switch-away/back, video disable/re-enable,
  producer stop/restart, repeated application open/close, short multi-consumer
  probes, and webcam unplug/reconnect only for optional passthrough.
- **Deployment:** local installation/registration, normal-user activation
  after installation, reboot persistence if applicable, uninstall/cleanup,
  and normal Windows security settings. No Secure Boot, camera-permission,
  or signing-enforcement bypass to manufacture PASS.

The future spike must deliver a versioned compatibility matrix using `PASS`,
`FAIL`, `NOT TESTED`, or `NOT AVAILABLE` for each route, with no silent
substitution. Basic-delivery PASS requires normal enumeration and selection,
remotely visible moving synthetic frames with a continuously advancing
counter, correct orientation/colors, no mandatory advanced capture override,
no security bypass, and acceptable switch-away/back and producer-restart
recovery, as detailed in the spike document.

Select exactly one overall verdict after execution: `PASS` (all required
OS/product routes demonstrate basic delivery), `CONDITIONAL PASS` (viable
path with a material product/mechanism condition), `FAIL` (demonstrated
load-bearing integration blocker), or `INCONCLUSIVE` (insufficient execution).
These are spike verdicts, not new M8 acceptance gates.

## Gate state and prohibited scope

No gaze correction, Maxine integration, neural model, cloud inference,
`CorrectionEngine` changes, production pipeline or product UI integration,
M4–M7 work, or M8 production implementation is authorized. No full installer
or product packaging, Store submission, production driver qualification,
AVStream/Frame Server/UMDF/KMDF fallback, Zoom plugin, Teams app, browser
extension, Meet-specific integration, OBS dependency, or external
virtual-camera SDK integration is authorized.

The PRD, architecture, ADRs, frozen milestone references, research reports,
and all evaluation evidence remain unchanged. No ADR creation, Windows
11-only product decision, removal of Windows 10 support, backend adoption,
model search/substitution/fallback, or reopening Candidate Admission follows.

**No verdict automatically opens M8, changes the PRD, or authorizes another
mechanism after Windows 10 failure. M4 remains BLOCKED. M8 remains UNOPENED.**
Existing M8/MVP acceptance requirements are unchanged. This is no Product
Strategy decision and no roadmap resumption.

Maxine Phase 1B requires separate PM authorization and its own gate. After
Phase 1B, an explicit **Product Strategy Gate** remains required before any
PRD revision or resumed milestone implementation where applicable. Neither
Phase 1A PASS, prior research, nor this spike substitutes for that decision.
The Phase 1A cloud exception grants no authority for this spike.

## LivePortrait is retired

LivePortrait remains permanently rejected for this development cycle:
**`REJECTED — COMMERCIAL/PROVENANCE GATE FAILED`**. It is not a candidate,
benchmark, teacher, quality oracle, fallback, backup model, comparison target,
or implementation dependency.

Do not clone it, download its weights, execute it, reproduce it, port its
algorithm, copy its preprocessing, implement its gaze controls, add its
dependencies, add a `LivePortraitCorrectionEngine`, or use its outputs as a
benchmark.

`model-feasibility-architecture-v1` and all LivePortrait documents and commits
remain **immutable historical audit evidence only**, with no forward
authority. The retirement decision is unchanged; this spike authorization
does not authorize LivePortrait reconsideration.

## Sources of truth

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — unchanged product scope,
   constraints, licensing/dependency policy, and milestone gates, including
   Windows 10/11 support.
2. `docs/architecture.md`, accepted ADRs in `docs/decisions/`, and
   `docs/milestones/m3-solution-architecture.md` at `m3-architecture-v1.3`
   — frozen architecture and provider-neutral correction boundary.
3. `docs/milestones/m3-evaluation.md` — M3 `CHANGE APPROACH` gate result.
4. `docs/milestones/liveportrait-retirement.md` and
   `docs/milestones/candidate-admission-closure.md` — unchanged decisions.
5. `docs/qa-policy.md` — truthful verification, proportional checks, stopping
   rules, and Product Owner interaction budget.
6. `docs/milestones/virtual-camera-integration-feasibility.md` — retained prior
   research authorization and supplied Phase 1A PASS record, not the current
   scope pointer or a completed research report.
7. `docs/milestones/virtual-camera-delivery-spike.md` — current PM spike
   authorization, PM-supplied prior research outcome, and all scope/gate limits.

The model-feasibility architecture/spike and other retired records remain
historical evidence, not forward authority. The present PM authorization
supersedes the earlier research-only restriction solely for the future
bounded spike; all unrelated prohibitions and frozen decisions remain.

## Governance checkpoint and delivery scope

Base: fetched `origin/codex/virtual-camera-feasibility-governance` at
`67e467ee08e958e4a620273272e0c9532e9b62dd`, the latest appropriate governance
lineage verified before editing. New branch:
`codex/virtual-camera-delivery-spike-governance`.

The base retains `codex/maxine-phase1a-governance` at
`95678777642d29912d0806a81f02dc4b11ea884b` and Phase 1A evaluation lineage
through `32836f9df8a222f3847306ca42b2e388e461cd83`. No history is discarded;
this branch is not based on `main`. The unrelated original checkout remains
untouched in its own worktree.

Change only `Current Assignment.md` and
`docs/milestones/virtual-camera-delivery-spike.md`. Verify frozen references
before editing and at completion, audit the documentation and exact file
scope, and commit the docs-only governance update. Do not run the technical
spike or merge any PR. Product/runtime tests are not applicable to this
strictly documentation-only change; no runtime or hardware result is claimed.

## Frozen repository state

| Reference | SHA |
| --- | --- |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` |
| `milestone-0` | `3b0a2eee8b0fc207875702250955e78173857957` |
| `milestone-1` | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| `milestone-2` | `81e06118801c23d2337629fc676d6ad8ac13716a` |
| `architecture-v1` | `003180d52d39d30a038333541b1b187824714e87` |
| `m3-architecture-v1` | `a459e6be36122bf10ce707731d5f847007847e96` |
| `m3-architecture-v1.1` | `00eed0e893b73dcd490f69af8df852a0609ccbaa` |
| `m3-architecture-v1.2` | `6a64ab7ae55a4c2c3e71f7084b9ed48b51c91b93` |
| `m3-architecture-v1.3` | `d91d393eb6e3e5f93ee2122bc840f776a55872e5` |
| `m3-geometric-baseline` | `f3831b54728a4747c38c064351ec9f48419a2efb` |
| `model-feasibility-architecture-v1` | `d66df8971086f5e0343ad24233aca6afaf505d16` — historical evidence only |

All eleven are frozen: do not advance, rewrite, force-push, or merge into
them. Architecture and amendment review branches are retained review
records, not work branches. Accepted M0 debt (`PreparedCameraCloser`'s
ambiguous `Thread.start()` bootstrap case in `docs/architecture.md`) remains
accepted and out of scope.

## Roles

- ChatGPT — Product Manager / Technical Lead: scope, acceptance, gate
  decisions, and any subsequent authorization.
- Mohammad Iqbal — Product Owner: visual-quality judgment.
- Codex / Claude — engineering within the bounded PM-issued assignment.
