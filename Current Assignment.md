# GazeFix — Current Engineering Assignment

**Active assignment: Windows virtual-camera / conferencing integration feasibility — desk research only**

**`MAXINE PHASE 1A VISUAL GATE: PASS`** — Product Owner verdict supplied by
the Product Manager's 2026-09-08 authorization. The governance record and its
evidence limits are in `docs/milestones/virtual-camera-integration-feasibility.md`.

**Maxine Phase 1B realtime/streaming feasibility requires separate future PM
authorization; neither its research nor implementation is authorized here.**

**The original PRD remains authoritative and unchanged. The primary roadmap
remains paused at the M3 -> M4 boundary. M8 has not begun.**

**Candidate Admission: FAIL — NO COMMERCIALLY ADMISSIBLE PRETRAINED PATH FOUND**
The previous commercial-first local/offline pretrained Candidate Admission
cycle is **CLOSED** (PM decision: 2026-09-07). See
`docs/milestones/candidate-admission-closure.md`.

**M4 remains BLOCKED.**

**LivePortrait remains REJECTED — COMMERCIAL/PROVENANCE GATE FAILED.**
See `docs/milestones/liveportrait-retirement.md`.

**M0 / M1 / M2: PASS / CLOSED / FROZEN.**

**M3: `CHANGE APPROACH` — NOT PASS** (`docs/milestones/m3-evaluation.md`).
`m3-geometric-baseline @ f3831b54728a4747c38c064351ec9f48419a2efb` remains
the frozen reference geometric implementation.

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL** — unchanged.

**Updated: 2026-09-08.**

## PM authorization and bounded research question

The Product Manager has authorized one additional parallel track:
**`WINDOWS VIRTUAL-CAMERA / CONFERENCING INTEGRATION FEASIBILITY RESEARCH`**.

> Can GazeFix eventually expose a production-quality Windows camera source
> that Zoom, Google Meet, and Microsoft Teams can consume as a normal webcam,
> under the supported Windows product scope?

This authorization covers **desk research only**, independent of the
correction backend. It must not assume Maxine becomes the product backend.
The scope, prohibitions, evidence standard, and research outcomes are defined
in `docs/milestones/virtual-camera-integration-feasibility.md`.

Research may examine Windows virtual-camera mechanisms, Windows 10 versus
Windows 11 support, Media Foundation and relevant Microsoft camera APIs,
installation/registration, user-mode versus driver implications, signing,
installer implications, permissions, enumeration, resolution/frame-rate/
pixel-format compatibility, Zoom/Meet/Teams compatibility, in-call camera
switching, failure/disconnect behavior, materially relevant multi-consumer
constraints, product risks/blockers, and a future implementation recommendation.
Primary Microsoft, Zoom, Google, and Teams documentation is required where
available. Unknowns must remain explicit; desk research is not runtime proof.

## Gate state and authorization boundaries

The Phase 1A visual PASS means only that NVIDIA Maxine Eye Contact has
demonstrated sufficient visual feasibility to justify further bounded
investigation. It does not authorize product adoption of Maxine, production
integration, M4, cloud architecture, virtual-camera implementation, PRD
changes, commercial acceptance, or realtime acceptance. Existing Phase 1A
evaluation evidence remains unchanged; this assignment does not rerun or
extend it. The earlier cloud exception was limited to Phase 1A and supplies
no authority for this provider-neutral track.

The authorization does **not** permit any product or virtual-camera code,
driver code, technical spike (including an `MFCreateVirtualCamera`
proof-of-concept), OBS or external virtual-camera SDK integration, Zoom
plugins, Teams apps, Chrome extensions, Meet-specific code, Maxine
integration, webcam-to-cloud-to-virtual-camera pipelines, realtime correction,
M4 or M8 implementation, installer changes, product dependencies, PRD or
architecture edits, ADR creation, commercial vendor outreach, training,
fine-tuning, or LivePortrait in any role. Maxine Phase 1B research and
implementation are not authorized. Frozen references and all existing
evaluation evidence must remain unchanged. Candidate Admission remains
closed; no model search, substitution, fallback, or replacement Solution
Architecture is authorized.

**No automatic transition follows a Phase 1A visual PASS or a virtual-camera
research PASS (including CONDITIONAL PASS).** Any technical spike needs a
later, explicit Product Manager assignment. Maxine Phase 1B needs its own
authorization and gate. After Phase 1B there must still be an explicit
**Product Strategy Gate** before any PRD revision or resumed milestone
implementation. Research outcomes do not change supported OS scope, adopt a
backend, reopen M4, begin M8, or grant milestone/product acceptance.

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
authority. The retirement decision is unchanged; this Maxine authorization
does not authorize LivePortrait reconsideration.

## Sources of truth

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — product scope,
   constraints, licensing/dependency policy, and milestone gates. Production
   constraints and Windows 10/11 scope remain unchanged.
2. `docs/architecture.md`, accepted ADRs in `docs/decisions/`, and
   `docs/milestones/m3-solution-architecture.md` at `m3-architecture-v1.3`
   — frozen architecture and provider-neutral correction boundary.
3. `docs/milestones/m3-evaluation.md` — M3 `CHANGE APPROACH` gate result.
4. `docs/milestones/liveportrait-retirement.md` — unchanged retirement record.
5. `docs/milestones/candidate-admission-closure.md` — completed Candidate
   Admission decision and historical Phase 1A authorization.
6. `docs/qa-policy.md` — verification depth, truthful reporting, stopping
   rules, and Product Owner interaction budget.
7. `docs/milestones/virtual-camera-integration-feasibility.md` — current PM
   desk-research authorization, supplied Phase 1A PASS record, and gate limits.

`docs/milestones/model-feasibility-architecture.md` and
`docs/milestones/model-feasibility-spike.md` are historical records, not
current work authority. Historical references to a fallback or future model
work do not override the current prohibitions above.

## Governance checkpoint and delivery scope

This docs-only update starts from the fetched `origin/codex/m1-assignment`
at `32836f9df8a222f3847306ca42b2e388e461cd83`, on
`codex/virtual-camera-feasibility-governance`. That base descends from
`codex/maxine-phase1a-governance` at
`95678777642d29912d0806a81f02dc4b11ea884b` and preserves the subsequent Phase 1A
evaluation commits. It is not based on `main`.

This governance update changes only `Current Assignment.md` and
`docs/milestones/virtual-camera-integration-feasibility.md`. Delivery stops
after documentation audit, commit, and push of this new branch; no PR may
be merged. The desk research is authorized for subsequent work, not executed
by this governance task. No research outcome is assigned by this update.

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
