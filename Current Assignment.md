# GazeFix — Current Engineering Assignment

**Active assignment: Model-based gaze-correction feasibility spike
(research / model scouting)**

**Spike: ACTIVE — see `docs/milestones/model-feasibility-spike.md`**

**M3 status: `CHANGE APPROACH` — NOT PASS.** The Product Owner visual gate
ran on 2026-09-07 and its record is `docs/milestones/m3-evaluation.md`.

**M4: NOT AUTHORIZED.** No real-time integration work of any kind.

**M0 / M1 / M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL**

**M3 Solution Architecture (`m3-architecture-v1.3`): APPROVED / FROZEN / CANONICAL**
— frozen and immutable. It remains the correct design record for the
geometric technique; the gate rejected the technique's visual result, not the
document.

**Updated: 2026-09-07**

This file is an assignment pointer. The spike scope is not repeated here: it
lives in `docs/milestones/model-feasibility-spike.md` and is authoritative
there.

## M3 outcome

| Item | Value |
| --- | --- |
| PO gate verdict | **`CHANGE APPROACH`** (frozen SA §14.3) |
| Gate record | `docs/milestones/m3-evaluation.md` |
| Evaluated implementation | `codex/m3-gaze-correction` @ `f3831b54728a4747c38c064351ec9f48419a2efb` |
| Preserved as | branch **`m3-geometric-baseline`** @ the same SHA |
| Engineering QA before the gate | `M3 TARGETED QA PASS` — the implementation is correct against its frozen design |
| M3 milestone result | **not `PASS`** |
| M4 | **not authorized** |

The geometric implementation is **retained, not discarded**. It stands as the
reproducible baseline, the fallback/reference implementation, the proof that
the `CorrectionEngine` contract is implementable, and the benchmark any
future approach must beat. Do not continue tuning it as the primary
production candidate.

## Baseline and branch

| Item | Value |
| --- | --- |
| **Spike brief** | **`docs/milestones/model-feasibility-spike.md`** |
| Baseline to compare against | branch **`m3-geometric-baseline`** @ `f3831b54728a4747c38c064351ec9f48419a2efb` |
| Preferred spike branch | `codex/model-feasibility-spike` |
| Deliverable | one written feasibility report; no model implementation |

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
| `m3-geometric-baseline` | `f3831b54728a4747c38c064351ec9f48419a2efb` |

All ten are frozen: do not advance, rewrite, force-push, or merge into any of
them. `claude/m3-solution-architecture` and PR #7 are the retained M3 SA
review record; `claude/m3-sa-blend-amendment`,
`claude/m3-sa-source-iris-amendment` and `claude/m3-sa-tolerance-amendment`
are the A1/A2/A3 amendment branches. None is a work branch.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case in `docs/architecture.md`) remains accepted and out of scope.

## What the spike investigates

Answer one question: **is there a lightweight model-based gaze-redirection
approach that produces materially more natural results than the geometric M3
baseline while remaining plausibly CPU-deployable on the target Windows
laptop?**

Scout candidates, screen them against availability of source and pretrained
weights, commercially compatible licensing, CPU and Windows feasibility,
dependency burden and eye realism, then compare survivors against the frozen
geometric baseline. Verify licensing and hardware claims against primary
sources. Training a model from scratch is **not** an acceptable answer
(PRD §16). A well-evidenced "no candidate clears the bar" is a valid result.

Full scope, screening criteria, method, deliverable and stop conditions are
in the spike brief.

## Sources of truth, in precedence order

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — product scope,
   constraints, milestone gates. §16 (model strategy) and M9 (neural model
   evaluation) govern this spike.
2. `docs/architecture.md` and the accepted ADRs (`docs/decisions/`) — frozen
   architecture, including the provider-neutral correction boundary.
3. `docs/milestones/model-feasibility-spike.md` — the active spike brief.
4. `docs/milestones/m3-evaluation.md` — the gate result that motivates it.
5. `docs/qa-policy.md` — verification depth, stopping rules, Product Owner
   interaction budget.

`docs/milestones/m3-solution-architecture.md` at v1.3 remains frozen and
authoritative **for the geometric baseline**. It is not the design for
anything the spike proposes.

## Boundaries

- **No neural implementation.** Do not build or integrate a model-based
  correction engine. Do not train a model.
- **No M4 work**: no live-webcam correction, no staged-processor or pipeline
  integration, no `ProcessedFrame`/`ProcessorOutput` changes, no correction
  metrics in `PipelineMetrics`, no continuity-epoch implementation. M5–M10
  remain out of scope as milestones. **M4 remains unauthorized.**
- **No new runtime dependency** for the shipping application. Spike-local
  installs are permitted for investigation and must be recorded as
  spike-local. ONNX Runtime is the PRD's sanctioned neural runtime *if and
  when* neural work is actually authorized — investigating it is in scope,
  shipping it is not.
- **Architecture stays intact.** The `CorrectionEngine` protocol,
  ADR-0002/0003 and provider neutrality are preserved unless later evidence
  proves them unsuitable, which is an escalation with evidence, not a
  unilateral change.
- **Frozen documents and refs are immutable.** Frozen M0–M3 product code,
  tests and the PRD are not modified.
- **No automatic milestone transition.** A positive spike result does not
  authorize implementation; the Product Manager issues the next assignment.
- **No webcam captures committed.** Product Owner captures stay local.

## Roles

- ChatGPT — Product Manager / Technical Lead: scope, acceptance, gate decisions.
- Mohammad Iqbal — Product Owner: target-device verification and visual
  quality judgment.
- **Next role: research / model scouting**, not implementation engineering.
  The deliverable is a report, not code.

## Stop condition

Stop at **MODEL FEASIBILITY SPIKE COMPLETE** with the report, or
**MODEL FEASIBILITY SPIKE BLOCKED** with the reason. Do not select a
production approach, do not begin an implementation milestone, and do not
revisit the M3 verdict.
