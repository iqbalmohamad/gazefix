# GazeFix — Current Engineering Assignment

**Active assignment: Milestone 3 — Solution Architecture (design only)**

**M0 status: PASS / CLOSED / FROZEN**

**M1 status: PASS / CLOSED / FROZEN**

**M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL**

**M3 implementation: NOT STARTED — not authorized by this file**

**Updated: 2026-09-05**

The only authorized work is the **Milestone 3 Solution Architecture**: a
milestone-specific design document derived from the frozen architecture
baseline, describing how the offline gaze-correction prototype (PRD §24, M3)
will be built. This assignment produces documentation only. It does **not**
authorize product code, tests, dependency changes, an M3 implementation
branch, or any M4 work. Implementation is assigned separately by the Product
Manager after the SA is reviewed; no implementation work is assigned to Codex
or to any other engineer by this file.

## Frozen repository state

| Item | Value |
| --- | --- |
| Frozen M0 baseline (`milestone-0`) | `3b0a2eee8b0fc207875702250955e78173857957` |
| Frozen M1 baseline (`milestone-1`) | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| Frozen M2 baseline (`milestone-2`) | `81e06118801c23d2337629fc676d6ad8ac13716a` |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` (M0 merge) |
| Canonical architecture baseline (`architecture-v1`) | `003180d52d39d30a038333541b1b187824714e87` |

`main`, `milestone-0`, `milestone-1`, `milestone-2` and `architecture-v1`
are frozen. Do not advance, rewrite, force-push, or merge into any of them.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case documented in `docs/architecture.md`) remains accepted and out
of scope; its stated reopening triggers are unchanged.

## Architecture baseline

`architecture-v1` is the canonical, frozen post-M2 architecture baseline and
the branch point for milestone work. Its content lives in:

- `docs/architecture.md` — Part I, the frozen M0/M1/M2 system; Part II, the
  accepted architecture baseline for M3–M10.
- `docs/decisions/ADR-0002-correction-engine-boundary.md` — accepted, frozen.
- `docs/decisions/ADR-0003-execution-model-and-frame-ownership.md` — accepted,
  frozen.

Milestone work extends the architecture only through milestone-specific
Solution Architecture documents, or through a deliberate architecture
amendment / new ADR when evidence requires one. The frozen baseline is not
edited during milestone work.

## Milestone 3 Solution Architecture

| Item | Value |
| --- | --- |
| Deliverable | `docs/milestones/m3-solution-architecture.md` |
| Lineage | `milestone-2` @ `81e0611` → `architecture-v1` @ `003180d` [frozen] → M3 SA |
| Branch | `claude/m3-solution-architecture`, created from `architecture-v1` |
| Scope | design of the M3 offline correction prototype: engine contract, geometric technique, eye-region geometry, gaze-to-deformation mapping, policy, masks/blending, failure semantics, frame ownership, offline harness, test strategy, quality gate |
| Changes allowed | this file; the SA document; a new ADR only if genuinely justified (none was) |
| Changes forbidden | product code, tests, dependencies, the PRD, frozen architecture documents, ADR-0002/0003, any frozen branch |
| Outcome | the SA is reviewed by the Product Manager; M3 implementation is a separate, later assignment |

M3 is the PRD's major quality gate. The SA is written so that
`FAIL / CHANGE APPROACH` is a legitimate M3 outcome; nothing in it assumes
M3 must pass.

## Historical assignments

Superseded assignment text is preserved in Git history rather than in this
file:

| Assignment | Commit |
| --- | --- |
| M2 — Gaze Estimation | `81e06118801c23d2337629fc676d6ad8ac13716a` (this file at frozen M2) |
| Overall Architecture Pass | `8e80dd32ed121590c9e5c99e55f304b1b6cde151` |
| No active assignment (post-freeze idle state) | `003180d52d39d30a038333541b1b187824714e87` (this file at `architecture-v1`) |

## Authority and roles

`01-GazeFix-Product-Requirements-Document-v1.1.md` remains the unchanged
higher-level source of truth for product scope, requirements, constraints, and
milestone gates. This file records the currently authorized engineering work
and nothing beyond it. If a material conflict appears, escalate it instead of
editing the PRD or silently changing scope.

- ChatGPT: Product Manager / Technical Lead; scope, acceptance, and milestone
  decisions.
- Mohammad Iqbal: Product Owner; final product decisions and target-device
  (Windows/webcam) verification.
- Claude Code: Solution Architect for this assignment; implementation
  engineer and self-review when implementation is assigned.

`docs/qa-policy.md` is the repository-level QA policy from M2 onward and
governs verification depth, independent review, stopping rules, and Product
Owner interaction.

## Next step

The Product Manager reviews the M3 Solution Architecture. If approved, the
PM issues the **Milestone 3 — Offline Gaze Correction Prototype**
implementation assignment, on a new implementation branch created from the
approved SA lineage. Neither the implementation nor its branch is authorized
by this file.
