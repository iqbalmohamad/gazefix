# GazeFix — Current Engineering Assignment

**Active assignment: Milestone 3 — Offline Gaze Correction Prototype
(implementation)**

**M3 implementation: ACTIVE**

**M0 / M1 / M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL**

**M3 Solution Architecture (`m3-architecture-v1`): APPROVED / FROZEN / CANONICAL**

**Updated: 2026-09-05**

This file is an assignment pointer. The design is not repeated here: it lives
in the frozen M3 Solution Architecture and is authoritative there.

## Baseline and branch

| Item | Value |
| --- | --- |
| Canonical M3 SA | `m3-architecture-v1` @ `a459e6be36122bf10ce707731d5f847007847e96` |
| SA document | `docs/milestones/m3-solution-architecture.md` (frozen at that SHA) |
| Preferred implementation branch | `codex/m3-gaze-correction` |
| Branch from | the frozen M3 SA SHA above — mandatory |

The implementation branch must descend from
`a459e6be36122bf10ce707731d5f847007847e96`. This assignment commit is a
documentation-only commit sitting directly on top of that SHA (branch
`codex/m3-assignment`); cutting the implementation branch from either point
satisfies the baseline requirement, and cutting it from this commit also
carries this file — the pattern M1 used (`codex/m1-assignment` →
`claude/m1-face-eye-tracking`).

## Frozen repository state

| Reference | SHA |
| --- | --- |
| `milestone-0` | `3b0a2eee8b0fc207875702250955e78173857957` |
| `milestone-1` | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| `milestone-2` | `81e06118801c23d2337629fc676d6ad8ac13716a` |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` |
| `architecture-v1` | `003180d52d39d30a038333541b1b187824714e87` |
| `m3-architecture-v1` | `a459e6be36122bf10ce707731d5f847007847e96` |

All six are frozen: do not advance, rewrite, force-push, or merge into any of
them. `claude/m3-solution-architecture` and PR #7 are the retained M3 SA
review record and are not a work branch.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case in `docs/architecture.md`) remains accepted and out of scope.

## What M3 implements

Build the offline gaze-correction prototype **exactly as the frozen M3 SA
specifies**: the `gazefix/correction/` package (engine protocol, metadata-only
result contract, geometric engine, eye-region geometry, mask/blend library,
correction policy), the offline harness CLI and its `scripts/` wrapper, the
hardware-independent tests, and `docs/correction.md`.

**Implement the frozen SA; do not redesign it.** The engine boundary,
geometric technique, eye-region geometry, gaze-to-deformation mapping, policy,
mask and blending approach, failure semantics, frame ownership, harness design
and test strategy are settled decisions (SA §22). Ordinary implementation
detail is the engineer's (SA §22, PRD §26). If implementation evidence
contradicts a settled decision, stop and escalate to the Product Manager with
the evidence — do not amend the frozen SA, `docs/architecture.md`, or an
accepted ADR, and do not work around it silently.

## Sources of truth, in precedence order

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — product scope,
   constraints, milestone gates.
2. `docs/architecture.md` and the accepted ADRs (`docs/decisions/`) — frozen
   architecture.
3. `docs/milestones/m3-solution-architecture.md` — the M3 design to implement.
4. `docs/qa-policy.md` — verification depth, stopping rules, Product Owner
   interaction budget.

## Boundaries

- **No M4 work**: no live-webcam correction, no staged-processor or pipeline
  integration, no `ProcessedFrame`/`ProcessorOutput` changes, no correction
  metrics in `PipelineMetrics`, no continuity-epoch implementation. M5–M10 are
  likewise out of scope (SA §1.2).
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

Create `codex/m3-gaze-correction` from the frozen M3 SA baseline and implement
the frozen M3 SA. Report at the milestone gate with PRD §25 evidence levels;
do not proceed past M3.
