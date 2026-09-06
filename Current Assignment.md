# GazeFix — Current Engineering Assignment

**Active assignment: Milestone 3 — Offline Gaze Correction Prototype
(implementation)**

**M3 implementation: ACTIVE — against SA v1.3**

**M0 / M1 / M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL**

**M3 Solution Architecture (`m3-architecture-v1.3`): APPROVED / FROZEN / CANONICAL**

**Updated: 2026-09-07**

This file is an assignment pointer. The design is not repeated here: it lives
in the frozen M3 Solution Architecture and is authoritative there.

## Baseline and branch

| Item | Value |
| --- | --- |
| **Canonical M3 SA** | **`m3-architecture-v1.3` @ `d91d393eb6e3e5f93ee2122bc840f776a55872e5`** |
| SA document | `docs/milestones/m3-solution-architecture.md` (frozen at that SHA) |
| Preferred implementation branch | `codex/m3-gaze-correction` |
| Implementation lineage | preserve existing M3 work and incorporate the frozen SA v1.3 above |

The existing implementation at `dc7817715e703d82a8b178bffc41486a383a8372`
on `codex/m3-gaze-correction` is preserved. This pointer update belongs on
that implementation lineage; no separate assignment branch is created.
Incorporate the frozen v1.3 baseline without discarding passing work.

## Superseded implementation baselines — immutable history

| Reference | SHA | Standing |
| --- | --- | --- |
| `m3-architecture-v1.3` | `d91d393eb6e3e5f93ee2122bc840f776a55872e5` | **implement against this** |
| `m3-architecture-v1.2` | `6a64ab7ae55a4c2c3e71f7084b9ed48b51c91b93` | superseded for implementation; immutable history |
| `m3-architecture-v1.1` | `00eed0e893b73dcd490f69af8df852a0609ccbaa` | superseded for implementation; immutable history |
| `m3-architecture-v1` | `a459e6be36122bf10ce707731d5f847007847e96` | superseded for implementation; immutable history |
| `codex/m3-assignment-v1.1` | `42fc15b3f54f130d7db7cb4078a91ed529281d1c` | superseded assignment pointer; retained |
| `codex/m3-assignment` | `06c9c5926fde425c49c3776f5bfd110df18a9538` | superseded assignment pointer; retained |

v1.3 adds **Amendment A3** to v1.2: test-contract tolerances and the
R-transpose discriminator only. A3.1/A3.2 ratify the shipped centroid bounds;
do not change them. A3.3 tightens the two rotated-head closed-loop rows to
±0.25 degrees and requires an R-for-R-transpose mutant to fail. Production
geometry, A1/A2 compositing, ownership and all architecture boundaries remain.

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
| `m3-architecture-v1.2` | `6a64ab7ae55a4c2c3e71f7084b9ed48b51c91b93` |
| `m3-architecture-v1.3` | `d91d393eb6e3e5f93ee2122bc840f776a55872e5` |

All nine are frozen: do not advance, rewrite, force-push, or merge into any
of them. `claude/m3-solution-architecture` and PR #7 are the retained M3 SA
review record; `claude/m3-sa-blend-amendment` is the A1 amendment branch.
Neither is a work branch.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case in `docs/architecture.md`) remains accepted and out of scope.

## What M3 implements

Build the offline gaze-correction prototype **exactly as frozen SA v1.3
specifies**: the `gazefix/correction/` package (engine protocol, metadata-only
result contract, geometric engine, eye-region geometry, mask/blend library,
correction policy), the offline harness CLI and its `scripts/` wrapper, the
hardware-independent tests, and `docs/correction.md`.

## Engineering authority (Product Owner instruction, 2026-09-05)

Implement the frozen M3 design and preserve passing work. Ordinary
implementation-detail and tuning issues do not require escalation. Codex may
adjust local fill/interpolation/mask details, deterministic helper organization,
experimental constants and test tolerances derived from reproducible evidence.

This authority preserves the CorrectionEngine contract, ADR-0002/0003,
provider neutrality, A1/A2 behavioral invariants, frame ownership and atomic
fallback, M3/M4 separation, CPU-only/no-new-dependency constraints, and the PO
visual-quality gate. Escalate only if evidence requires changing one of those
architecture/product invariants, later-milestone scope, hardware/dependencies,
or weakening a product-quality requirement. Do not request an SA amendment
merely because an implementation heuristic needs iteration. Frozen documents
remain immutable.

## Sources of truth, in precedence order

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — product scope,
   constraints, milestone gates.
2. `docs/architecture.md` and the accepted ADRs (`docs/decisions/`) — frozen
   architecture.
3. `docs/milestones/m3-solution-architecture.md` **at SA v1.3** — the M3
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

## Active post-QA scope (2026-09-07)

Close confirmed QA findings only on the existing implementation branch:

- QA-M3-002: tighten the rotated-head closed-loop rows per A3.3 and prove
  that an R-for-R-transpose mutant fails; do not change production geometry
  unless a real defect is reproduced.
- QA-M3-003: engine-level behavioral anchors for clamp state and magnitude,
  independent displacement recomputation, and target-versus-gaze centroid direction.
- QA-M3-004: engine-output A1 regression and default-linear source/lid-skin tracer.
- QA-M3-005: engine-level chamfer3 coverage with the accepted guard and safety
  assertions; change product behavior only if a defect is reproduced.
- QA-M3-007: count each tracking-error frame once, irrespective of sweep size;
  preserve exit semantics and every experiment record.
- QA-M3-006: informational only; no product change required.

Do not redesign the correction algorithm or discard passing work. After
changes run targeted tests, the full focused M3 suite, full regression and the
real-model M3 test. Verify unchanged correction pixels on deterministic inputs
and verify all frozen refs untouched. Report the final SHA, changed files,
closed findings and verification at their true level.

Stop at **M3 QA HARDENING COMPLETE — READY FOR TARGETED RE-REVIEW** or
**M3 QA HARDENING BLOCKED**. Do not claim M3 PASS. Stop before the PO visual
gate; no M4 or later-milestone work.
