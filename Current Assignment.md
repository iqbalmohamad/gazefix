# GazeFix — Current Engineering Assignment

**Active assignment: Milestone 3 — Offline Gaze Correction Prototype
(implementation)**

**M3 implementation: ACTIVE — against SA v1.1**

**M0 / M1 / M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL**

**M3 Solution Architecture (`m3-architecture-v1.1`): APPROVED / FROZEN / CANONICAL**

**Updated: 2026-09-05**

This file is an assignment pointer. The design is not repeated here: it lives
in the frozen M3 Solution Architecture and is authoritative there.

## Baseline and branch

| Item | Value |
| --- | --- |
| **Canonical M3 SA** | **`m3-architecture-v1.1` @ `00eed0e893b73dcd490f69af8df852a0609ccbaa`** |
| SA document | `docs/milestones/m3-solution-architecture.md` (frozen at that SHA) |
| Preferred implementation branch | `codex/m3-gaze-correction` |
| Branch from | the frozen SA v1.1 SHA above — mandatory |

The implementation branch must descend from
`00eed0e893b73dcd490f69af8df852a0609ccbaa`. This assignment commit is a
documentation-only commit sitting directly on top of that SHA (branch
`codex/m3-assignment-v1.1`); cutting the implementation branch from either
point satisfies the baseline requirement, and cutting it from this commit also
carries this file — the pattern M1 used (`codex/m1-assignment` →
`claude/m1-face-eye-tracking`).

## SA v1.0 is superseded for implementation

| Reference | SHA | Standing |
| --- | --- | --- |
| `m3-architecture-v1.1` | `00eed0e893b73dcd490f69af8df852a0609ccbaa` | **implement against this** |
| `m3-architecture-v1` | `a459e6be36122bf10ce707731d5f847007847e96` | superseded for implementation; **immutable history**, never moved or rewritten |
| `codex/m3-assignment` | `06c9c5926fde425c49c3776f5bfd110df18a9538` | superseded assignment pointer (named v1.0); retained |

v1.1 is v1.0 plus **Amendment A1** and nothing else. A1 corrects the §8.4
compositing order after M3 implementation found that the frozen §8.4 formula
and the frozen §15.2 no-ghosting test were mathematically incompatible; it was
approved by the Product Manager and is **part of the authoritative design**,
not an optional note. Its evidence, both formulas, rationale, accepted
consequence and the eight required regression tests are recorded in SA §8.7 —
read that section before touching compositing. No new ADR was required.

## Frozen repository state

| Reference | SHA |
| --- | --- |
| `milestone-0` | `3b0a2eee8b0fc207875702250955e78173857957` |
| `milestone-1` | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| `milestone-2` | `81e06118801c23d2337629fc676d6ad8ac13716a` |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` |
| `architecture-v1` | `003180d52d39d30a038333541b1b187824714e87` |
| `m3-architecture-v1` | `a459e6be36122bf10ce707731d5f847007847e96` |
| `m3-architecture-v1.1` | `00eed0e893b73dcd490f69af8df852a0609ccbaa` |

All seven are frozen: do not advance, rewrite, force-push, or merge into any
of them. `claude/m3-solution-architecture` and PR #7 are the retained M3 SA
review record; `claude/m3-sa-blend-amendment` is the A1 amendment branch.
Neither is a work branch.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case in `docs/architecture.md`) remains accepted and out of scope.

## What M3 implements

Build the offline gaze-correction prototype **exactly as frozen SA v1.1
specifies**: the `gazefix/correction/` package (engine protocol, metadata-only
result contract, geometric engine, eye-region geometry, mask/blend library,
correction policy), the offline harness CLI and its `scripts/` wrapper, the
hardware-independent tests, and `docs/correction.md`.

**Implement the frozen SA; do not redesign it.** The engine boundary,
geometric technique, eye-region geometry, gaze-to-deformation mapping, policy,
mask and blending approach (including A1's two-step compositing order and its
binary `iris_alpha` occlusion factors), failure semantics, frame ownership,
harness design and test strategy are settled decisions (SA §22). Ordinary
implementation detail is the engineer's (SA §22, PRD §26). If implementation
evidence contradicts a settled decision, stop and escalate to the Product
Manager with the evidence — that route produced A1 and it is the route to use
again. Do not amend a frozen SA, `docs/architecture.md`, or an accepted ADR,
and do not work around a contradiction silently.

## Sources of truth, in precedence order

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — product scope,
   constraints, milestone gates.
2. `docs/architecture.md` and the accepted ADRs (`docs/decisions/`) — frozen
   architecture.
3. `docs/milestones/m3-solution-architecture.md` **at SA v1.1** — the M3
   design to implement.
4. `docs/qa-policy.md` — verification depth, stopping rules, Product Owner
   interaction budget.

## Boundaries

- **No M4 work**: no live-webcam correction, no staged-processor or pipeline
  integration, no `ProcessedFrame`/`ProcessorOutput` changes, no correction
  metrics in `PipelineMetrics`, no continuity-epoch implementation. M5–M10 are
  likewise out of scope (SA §1.2). **M4 remains unauthorized.**
- **No new runtime dependency** (SA §19). Frozen M0–M2 product code, tests and
  the PRD are not modified; new tests are additive.
- **No automatic milestone transition.** Completing M3 does not authorize M4.
  The Product Manager issues the next assignment.
- **M3 cannot be reported `PASS` before the Product Owner visual-quality gate**
  (SA §14, PRD §25/§28/§29) has been run and its result recorded. Engineering
  completeness is not the gate. Report gate results at their true verification
  level; `CHANGE APPROACH` remains a legitimate M3 outcome.

## Roles

- ChatGPT — Product Manager / Technical Lead: scope, acceptance, gate decisions.
- Mohammad Iqbal — Product Owner: target-device verification and the M3 visual
  quality gate.
- Codex — M3 implementation engineer for this assignment, with self-review and
  automated tests per `docs/qa-policy.md`.

## Next step

Create `codex/m3-gaze-correction` from the frozen SA v1.1 baseline and
implement the frozen SA. Work already done against v1.0 is **preserved and
migrated** — rebased or cherry-picked onto this lineage, not discarded — since
v1.1 differs from v1.0 only by A1. Report at the milestone gate with PRD §25
evidence levels; do not proceed past M3.
