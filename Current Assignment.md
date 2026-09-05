# GazeFix — Current Engineering Assignment

**Active assignment: NONE — awaiting the Product Manager's Milestone 3
implementation assignment**

**M0 status: PASS / CLOSED / FROZEN**

**M1 status: PASS / CLOSED / FROZEN**

**M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL**

**M3 Solution Architecture (`m3-architecture-v1`): APPROVED / FROZEN / CANONICAL**

**M3 implementation: NOT STARTED — NOT YET AUTHORIZED**

**Updated: 2026-09-05**

There is no authorized engineering work in progress. The Milestone 3
Solution Architecture has been approved by the Product Manager and frozen;
Milestone 3 **implementation** has not been assigned, no correction code
exists, and no implementation branch has been created. Do not begin M3
implementation, create an M3 implementation branch, or start M4 work on the
strength of this file or of the approved SA. Wait for a Product Manager
assignment. No implementation work is assigned to Codex, to Claude, or to
any other engineer by this file.

## Frozen repository state

| Item | Value |
| --- | --- |
| Frozen M0 baseline (`milestone-0`) | `3b0a2eee8b0fc207875702250955e78173857957` |
| Frozen M1 baseline (`milestone-1`) | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| Frozen M2 baseline (`milestone-2`) | `81e06118801c23d2337629fc676d6ad8ac13716a` |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` (M0 merge) |
| Canonical architecture baseline (`architecture-v1`) | `003180d52d39d30a038333541b1b187824714e87` |
| Reviewed M3 SA content | `28dac348749e956acbeb709e3abb4ff3654451d5` |
| Canonical M3 Solution Architecture (`m3-architecture-v1`) | this commit; it adds status/admin metadata only on top of the reviewed SA content |

`main`, `milestone-0`, `milestone-1`, `milestone-2`, `architecture-v1` and
`m3-architecture-v1` are frozen. Do not advance, rewrite, force-push, or
merge into any of them.

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

## Milestone 3 Solution Architecture — approved and frozen

| Item | Value |
| --- | --- |
| Document | `docs/milestones/m3-solution-architecture.md` |
| Canonical reference | `m3-architecture-v1` (this commit) |
| Reviewed SA content | `28dac348749e956acbeb709e3abb4ff3654451d5` |
| Historical review branch | `claude/m3-solution-architecture` (retained) |
| Review record | PR #7 against `architecture-v1` — closed, **not merged** |
| Lineage | `milestone-2` @ `81e0611` → `architecture-v1` @ `003180d` [frozen] → M3 SA [frozen] |
| Approved | 2026-09-05, by the Product Manager |
| New ADR required | none |

The approved SA is the design authority for M3 implementation: the engine
contract, geometric technique, eye-region geometry, gaze-to-deformation
mapping, correction policy, mask and blending approach, failure behaviour,
frame ownership, offline harness, test strategy and visual quality gate are
settled there and are not to be redesigned by the implementor. It changes no
product code, test, dependency, PRD text, frozen architecture document or
accepted ADR.

The Product Manager's approval explicitly ratifies the 10–20° operating and
evaluation range; effective strength ≈ 0.5–0.8 as the main visual-quality
evaluation range; the `PROCEED / ITERATE / CHANGE APPROACH` gate framework;
a qualitative Product Owner visual gate with no fabricated aggregate numeric
pass score; the ~45–50 minute PO evaluation budget; the layered eye-region
remap as the approved M3 default geometric approach; the default
pair-correction behaviour as provisional, tunable implementation policy
rather than architecture law; and the gaze-to-deformation mapping as an
approved hypothesis to be validated during implementation rather than proof
of physical accuracy.

M3 remains the PRD's major quality gate. The SA is written so that
`FAIL / CHANGE APPROACH` is a legitimate M3 outcome; neither the SA nor its
approval assumes M3 must pass.

## Historical assignments

Superseded assignment text is preserved in Git history rather than in this
file:

| Assignment | Commit |
| --- | --- |
| M2 — Gaze Estimation | `81e06118801c23d2337629fc676d6ad8ac13716a` (this file at frozen M2) |
| Overall Architecture Pass | `8e80dd32ed121590c9e5c99e55f304b1b6cde151` |
| No active assignment (post-architecture-freeze idle state) | `003180d52d39d30a038333541b1b187824714e87` (this file at `architecture-v1`) |
| M3 — Solution Architecture (design only) | `28dac348749e956acbeb709e3abb4ff3654451d5` (this file at the reviewed SA HEAD) |

## Authority and roles

`01-GazeFix-Product-Requirements-Document-v1.1.md` remains the unchanged
higher-level source of truth for product scope, requirements, constraints, and
milestone gates. This file records the currently authorized engineering work
and nothing beyond it. If a material conflict appears, escalate it instead of
editing the PRD or silently changing scope.

- ChatGPT: Product Manager / Technical Lead; scope, acceptance, and milestone
  decisions.
- Mohammad Iqbal: Product Owner; final product decisions, target-device
  (Windows/webcam) verification, and the M3 visual quality gate.
- Claude Code: implementation engineer and self-review when implementation is
  assigned; Solution Architect when an architecture pass is assigned.

`docs/qa-policy.md` is the repository-level QA policy from M2 onward and
governs verification depth, independent review, stopping rules, and Product
Owner interaction.

## Next step

The Product Manager issues the **Milestone 3 — Offline Gaze Correction
Prototype** implementation assignment, naming its own implementation branch
created from the frozen `m3-architecture-v1` reference. Until that
assignment exists, no implementation work is authorized: this file activates
nothing.
