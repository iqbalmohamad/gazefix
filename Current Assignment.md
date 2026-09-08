# GazeFix — Current Engineering Assignment

**`ACTIVE ENGINEERING ASSIGNMENT: NONE`**

No engineering implementation, research track, or technical spike is active.
Nothing in this file authorizes work to begin. Any new work requires a
separate, explicit Product Manager assignment.

**Canonical current program state:
[`docs/milestones/program-state-2026-09-08.md`](docs/milestones/program-state-2026-09-08.md)
at branch `program-state-v1`.** Read that document for the authoritative
current state, the verified frozen-reference table, the retained
historical/audit branches, and the recorded repository-cleanup classes.

**Updated: 2026-09-08.** This update is documentation-only.

## Current gate state

| Item | State |
| --- | --- |
| M0 / M1 / M2 | `PASS / CLOSED / FROZEN` |
| M3 geometric | engineering-valid baseline; Product Owner visual verdict `CHANGE APPROACH` — **NOT PASS** |
| Candidate Admission (commercial pretrained) | `CLOSED / FAIL` — no commercially admissible pretrained path found |
| LivePortrait | `RETIRED` as implementation authority |
| **Maxine Phase 1A** | **`MAXINE PHASE 1A VISUAL GATE: PASS`** |
| **Maxine Phase 1B** | **`MAXINE PHASE 1B: NOT YET AUTHORIZED`** |
| Windows virtual-camera / conferencing feasibility | `CONDITIONAL PASS` — research evidence only; `IS A PRE-M8 TECHNICAL SPIKE REQUIRED? YES` |
| **Pre-M8 virtual-camera delivery spike** | **`PRE-M8 VIRTUAL-CAMERA DELIVERY SPIKE: AUTHORIZED BUT DEFERRED / NOT ACTIVE`** |
| M4 | `BLOCKED` |
| M8 | `UNOPENED` |
| PRD | `UNCHANGED` |
| Canonical architecture baseline | `architecture-v1` — `APPROVED / FROZEN / CANONICAL` |
| **Active engineering assignment** | **`NONE`** |

## What each of the three current decisions means

**`MAXINE PHASE 1A VISUAL GATE: PASS`.** NVIDIA Maxine Eye Contact
demonstrated sufficient visual feasibility to justify continued bounded
investigation — and nothing further. It establishes no realtime feasibility,
no streaming feasibility, no production adoption, no product integration, no
cloud architecture approval, no commercial deployment approval, no M4
authorization, and no M8 authorization. The verdict's provenance and its
evidence limitations are preserved unchanged in
`docs/milestones/virtual-camera-integration-feasibility.md`;
`docs/milestones/maxine-phase1a-engineering-report.md` and
`research/maxine-eye-contact/` are unchanged and continue to describe their
original verification state. No scoring evidence has been altered.

**`MAXINE PHASE 1B: NOT YET AUTHORIZED`.** Phase 1B has not started. It
requires a separate Product Manager authorization and its own gate. Neither
its research nor its implementation is authorized, and no Phase 1B assignment
exists.

**`PRE-M8 VIRTUAL-CAMERA DELIVERY SPIKE: AUTHORIZED BUT DEFERRED / NOT
ACTIVE`.** The prior governance authorization of 2026-09-08 remains
historically valid and is **not withdrawn** — it is **parked**. Its bounded
scope, prohibitions, evidence requirements and verdict definitions remain
recorded unchanged in `docs/milestones/virtual-camera-delivery-spike.md`.
**The spike must not be executed** until a later Product Manager decision
explicitly reactivates it. No technical-spike implementation is active and
none exists in the repository; spike execution remains `NOT TESTED` and no
spike verdict is assigned.

## Prohibited scope while no assignment is active

Do not implement or execute the virtual-camera delivery spike, begin Maxine
Phase 1B, write virtual-camera or gaze-correction product code, install or
register a camera, integrate Maxine, adopt a correction backend, add a neural
model or cloud inference, change `CorrectionEngine` or the production
pipeline or product UI, start M4–M7 work, or open M8.

Do not modify the PRD, `docs/architecture.md`, the accepted ADRs, any frozen
milestone reference, any research record, or any evaluation or scoring
evidence. Do not create an ADR, make a Windows 11-only product decision,
remove Windows 10 support, search for or substitute a model, or reopen
Candidate Admission.

Do not merge any pull request. Do not delete any branch outside a separate,
PM-authorized cleanup assignment.

A **Product Strategy Gate** remains required before any roadmap transition
that would change the original product requirements. Phase 1A's `PASS`, the
prior research, and the parked spike authorization each substitute for it in
no way.

## LivePortrait remains retired

LivePortrait remains permanently rejected for this development cycle:
**`REJECTED — COMMERCIAL/PROVENANCE GATE FAILED`**. It is not a candidate,
benchmark, teacher, quality oracle, fallback, backup model, comparison
target, or implementation dependency. Do not clone it, download its weights,
execute it, reproduce it, port its algorithm, copy its preprocessing,
implement its gaze controls, add its dependencies, add a
`LivePortraitCorrectionEngine`, or use its outputs as a benchmark.

`model-feasibility-architecture-v1` and all LivePortrait documents and commits
remain **immutable historical audit evidence only**, with no forward
authority.

## Frozen repository state

The canonical frozen-reference table, with every SHA verified at this
checkpoint, is in
[`docs/milestones/program-state-2026-09-08.md`](docs/milestones/program-state-2026-09-08.md)
§B. Eleven references are frozen — `main`, `milestone-0`, `milestone-1`,
`milestone-2`, `architecture-v1`, `m3-architecture-v1`, `m3-architecture-v1.1`,
`m3-architecture-v1.2`, `m3-architecture-v1.3`, `m3-geometric-baseline` and
`model-feasibility-architecture-v1` — and all eleven verified as matching when
this checkpoint was taken. Do not advance, rewrite, force-push, or merge into
any of them.

`program-state-v1` is the **`CANONICAL CURRENT PROGRAM-STATE POINTER`**. It is
not a replacement for the historical milestone, architecture, or baseline
frozen references, and it carries no product, architectural, or acceptance
authority of its own. It is advanced only by a later documentation-only
program-state consolidation, never by implementation work.

Architecture and amendment review branches, and the other named historical and
audit branches, are retained review records rather than work branches; they
are listed individually in §C of the program-state document. Accepted M0 debt
(`PreparedCameraCloser`'s ambiguous `Thread.start()` bootstrap case in
`docs/architecture.md`) remains accepted and out of scope.

## Sources of truth

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — unchanged product
   scope, constraints, licensing/dependency policy, and milestone gates,
   including Windows 10/11 support.
2. `docs/architecture.md`, the accepted ADRs in `docs/decisions/`, and
   `docs/milestones/m3-solution-architecture.md` at `m3-architecture-v1.3` —
   frozen architecture and the provider-neutral correction boundary.
3. `docs/milestones/m3-evaluation.md` — the M3 `CHANGE APPROACH` gate result.
4. `docs/milestones/liveportrait-retirement.md` and
   `docs/milestones/candidate-admission-closure.md` — unchanged decisions.
5. `docs/qa-policy.md` — truthful verification, proportional checks, stopping
   rules, and Product Owner interaction budget.
6. `docs/milestones/virtual-camera-integration-feasibility.md` and
   `docs/milestones/virtual-camera-delivery-spike.md` — the retained research
   authorization, the Phase 1A verdict provenance and its evidence limits, and
   the parked spike's bounded scope.
7. `docs/milestones/program-state-2026-09-08.md` — **the canonical current
   program state.**

The model-feasibility architecture and spike records, and other retired
records, remain historical evidence with no forward authority.

## Roles

- ChatGPT — Product Manager / Technical Lead: scope, acceptance, gate
  decisions, and any subsequent authorization.
- Mohammad Iqbal — Product Owner: visual-quality judgment.
- Codex / Claude — engineering within the bounded PM-issued assignment.
