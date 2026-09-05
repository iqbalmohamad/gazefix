# GazeFix — Current Engineering Assignment

**Active assignment: Milestone 3 — Offline Gaze Correction Prototype
(implementation)**

**M3 implementation: ACTIVE — against SA v1.2**

**M0 / M1 / M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL**

**M3 Solution Architecture (`m3-architecture-v1.2`): APPROVED / FROZEN / CANONICAL**

**Updated: 2026-09-05**

This file is an assignment pointer. The design is not repeated here: it lives
in the frozen M3 Solution Architecture and is authoritative there.

## Baseline and branch

| Item | Value |
| --- | --- |
| **Canonical M3 SA** | **`m3-architecture-v1.2` @ `6a64ab7ae55a4c2c3e71f7084b9ed48b51c91b93`** |
| SA document | `docs/milestones/m3-solution-architecture.md` (frozen at that SHA) |
| Preferred implementation branch | `codex/m3-gaze-correction` |
| Implementation lineage | preserve existing M3 work and incorporate the frozen SA v1.2 above |

The existing implementation at `bf6f24c02a36060b901e71debce3547026e07613`
on `codex/m3-gaze-correction` is preserved. This pointer update belongs on
that implementation lineage; no separate assignment branch is created.
Incorporate the frozen v1.2 baseline without discarding passing work.

## Superseded implementation baselines — immutable history

| Reference | SHA | Standing |
| --- | --- | --- |
| `m3-architecture-v1.2` | `6a64ab7ae55a4c2c3e71f7084b9ed48b51c91b93` | **implement against this** |
| `m3-architecture-v1.1` | `00eed0e893b73dcd490f69af8df852a0609ccbaa` | superseded for implementation; immutable history |
| `m3-architecture-v1` | `a459e6be36122bf10ce707731d5f847007847e96` | superseded for implementation; immutable history |
| `codex/m3-assignment-v1.1` | `42fc15b3f54f130d7db7cb4078a91ed529281d1c` | superseded assignment pointer; retained |
| `codex/m3-assignment` | `06c9c5926fde425c49c3776f5bfd110df18a9538` | superseded assignment pointer; retained |

v1.2 adds **Amendment A2** to v1.1. Implement the specified sclera-background
representation in variant C so its background does not retain competing
source-iris texture; variant B stays unchanged. Preserve A1 compositing,
binary source/destination occlusion, lid safety, ownership and atomic
fallback. Read SA §8.8 and use its frozen visible-centroid ideal and A2
regression coverage. No new ADR or dependency is required.

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

All eight are frozen: do not advance, rewrite, force-push, or merge into any
of them. `claude/m3-solution-architecture` and PR #7 are the retained M3 SA
review record; `claude/m3-sa-blend-amendment` is the A1 amendment branch.
Neither is a work branch.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case in `docs/architecture.md`) remains accepted and out of scope.

## What M3 implements

Build the offline gaze-correction prototype **exactly as frozen SA v1.2
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
3. `docs/milestones/m3-solution-architecture.md` **at SA v1.2** — the M3
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

Resume on `codex/m3-gaze-correction`: implement A2, run focused tests, fix
ordinary implementation issues autonomously, complete the M3 test matrix,
run the full regression suite per QA policy, and prepare the complete offline
visual-evaluation batch. Stop when M3 is ready for PO evaluation or a genuine
architecture/product blocker remains. Do not report PASS before the PO gate.
Do not begin M4.
