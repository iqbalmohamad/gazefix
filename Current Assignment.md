# GazeFix — Current Engineering Assignment

**Active assignment: LivePortrait feasibility reproduction (model-feasibility
spike, first candidate)**

**Spike SA: `model-feasibility-architecture-v1` @ `d66df8971086f5e0343ad24233aca6afaf505d16` — APPROVED / FROZEN / CANONICAL**

**Candidate: LivePortrait image retargeting via its official horizontal /
vertical eye-gaze controls (`update_delta_new_eyeball_direction`).**

**Timebox: maximum two engineering days.**

**M3 status: `CHANGE APPROACH` — NOT PASS** (`docs/milestones/m3-evaluation.md`).

**M4: NOT AUTHORIZED.** No real-time integration work of any kind.

**Product integration: NOT AUTHORIZED.** No `CorrectionEngine` implementation
for LivePortrait, no change under `gazefix/`, no product dependency.

**M0 / M1 / M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL** — unchanged by the spike (`NO OVERALL ARCHITECTURE CHANGE REQUIRED`).

**M3 Solution Architecture (`m3-architecture-v1.3`): APPROVED / FROZEN / CANONICAL** — the design record of the frozen geometric baseline.

**Updated: 2026-09-07**

This file is an assignment pointer. The design is not repeated here: it lives
in the frozen spike SA and is authoritative there.

## The decision this assignment records

The model-feasibility spike brief (`docs/milestones/model-feasibility-spike.md`)
asked for scouting, screening and comparison of model-based candidates. That
research phase is complete: independent ChatGPT and Kimi research was
synthesized and cross-verified, and the **Product Manager decided
`REPRODUCE CANDIDATE NOW`** with LivePortrait as the first candidate. The PM
knowingly deferred the brief's criterion 3 (research-only or unspecified
licence terms are disqualifying): the reproduction answers the *quality*
question first, and the spike SA §17 names the licensable-engine and
teacher/reference paths a positive answer would open. LivePortrait as shipped
**fails criterion 3 for production** (spike SA §6) and nothing in this
assignment implies commercial clearance.

## Reproduction objective

Answer, with QA-verifiable evidence for a blind Product Owner comparison:

> Can a pretrained learned portrait renderer produce corrected eyes that are
> materially more natural and less distracting than GazeFix's frozen
> geometric baseline?

Reproduce LivePortrait **unmodified**, on **CPU only**, at the pinned code and
model revisions, driving only its official eye-gaze controls; validate that
the gaze-direction path is the one exercised and eye-open-ratio retargeting is
not; calibrate a six-value mapping on the fixed calibration set; render the
held-out Product Owner captures **once** with the frozen mapping; regenerate
the geometric baseline deterministically from `m3-geometric-baseline`; and
hand over the evidence package and report the spike SA §12 and §20 define.

## Baseline and branch

| Item | Value |
| --- | --- |
| **Spike SA** | **`docs/milestones/model-feasibility-architecture.md` at `model-feasibility-architecture-v1` @ `d66df8971086f5e0343ad24233aca6afaf505d16`** |
| Geometric baseline to compare against | branch `m3-geometric-baseline` @ `f3831b54728a4747c38c064351ec9f48419a2efb`, as a separate detached worktree |
| **Spike work branch** | **`codex/liveportrait-spike`**, created from `d66df8971086f5e0343ad24233aca6afaf505d16` — the only branch that receives spike commits |
| Upstream code | `https://github.com/KlingAIResearch/LivePortrait` @ `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` (`KlingTeam/LivePortrait` redirects there) |
| Upstream model | Hugging Face `KlingTeam/LivePortrait` @ `6d116d1066c3539da1cea3189da91c46cb505584`, human weights only |
| Where spike code lives | `spike/liveportrait/` (committed adapters, pins, plan, manifests); the upstream clone, weights and spike venv are git-ignored inside it |
| Where renders live | `experiments/liveportrait/<run-id>/` — git-ignored; no Product Owner pixel is ever committed |
| Deliverable | the evidence package (spike SA §12) and `docs/milestones/model-feasibility-report.md` (spike SA §20) |

## Gates after the reproduction

1. **Independent QA gate** (spike SA §13) — before the Product Owner sees
   anything. Risk level **HIGH**, proposed by the SA under QA policy §3; the
   PM confirms or changes it here. Until the PM records otherwise, treat it
   as HIGH. Reviewer: commissioned by the PM, or none — in which case Codex
   runs the §13 list and reports each item at its true verification level.
2. **Blind Product Owner comparison** (spike SA §14) — prepared, batched,
   PM-authorized; the PM reads the verdict. Engineering never scores visual
   quality.
3. **Spike closure** — the PM records `MODEL FEASIBILITY SPIKE COMPLETE` with
   one recommendation, or `MODEL FEASIBILITY SPIKE BLOCKED`, in
   `docs/milestones/model-feasibility-evaluation.md`.

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
| `model-feasibility-architecture-v1` | `d66df8971086f5e0343ad24233aca6afaf505d16` |

All eleven are frozen: do not advance, rewrite, force-push, or merge into any
of them. `claude/m3-solution-architecture` and PR #7 are the retained M3 SA
review record; `claude/m3-sa-blend-amendment`,
`claude/m3-sa-source-iris-amendment` and `claude/m3-sa-tolerance-amendment`
are the A1/A2/A3 amendment branches; `claude/model-feasibility-architecture`
is the spike SA review record. None is a work branch.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case in `docs/architecture.md`) remains accepted and out of scope.

## Sources of truth, in precedence order

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — product scope,
   constraints, milestone gates; §16 (no training from scratch), §27
   (dependency and licensing policy) and M9 govern this spike.
2. `docs/architecture.md` and the accepted ADRs (`docs/decisions/`) — frozen
   architecture, including the provider-neutral correction boundary.
3. **`docs/milestones/model-feasibility-architecture.md` at
   `model-feasibility-architecture-v1`** — the spike design to execute.
4. `docs/milestones/model-feasibility-spike.md` — the brief the SA narrows.
5. `docs/milestones/m3-evaluation.md` — the gate result that motivates it.
6. `docs/qa-policy.md` — verification depth, stopping rules, Product Owner
   interaction budget.

## Boundaries

- **Execute the frozen spike SA exactly.** Spike SA §19 lists what is fixed
  and what is left to the implementor. Do not redesign upstream, the
  isolation layout, the pins, the mapping rule, the sets, the evidence or the
  gates.
- **No upstream modification.** LivePortrait source is never edited, forked
  or patched; only the instrumentation the SA permits (§8.3).
- **No product change.** Nothing under `gazefix/`, `scripts/`, `tests/`,
  `pyproject.toml` or the constraints file changes; the spike venv never
  installs `gazefix`; `spike/` never imports it.
- **No neural engine, no integration, no M4.** No `CorrectionEngine`
  implementation for LivePortrait, no pipeline wiring, no real-time work,
  no ONNX/OpenVINO conversion, no training or fine-tuning.
- **CPU only.** No CUDA; the pinned CPU-only runtimes; the SA's flags.
- **No cherry-picking.** Calibration on the fixed calibration set only;
  held-out captures rendered once with the frozen, pushed, PM-acknowledged
  mapping; every output kept and reported, failures included.
- **Stop conditions are the SA's §15.** On any of them, stop with the
  report and return to the PM. Do not move to ST-ED or any other candidate.
- **Frozen documents and refs are immutable.** No webcam captures committed.
- **No automatic milestone transition.** A positive result does not
  authorize implementation; the PM issues the next assignment.

## Roles

- ChatGPT — Product Manager / Technical Lead: scope, acceptance, gate
  decisions, risk level, reviewer commissioning, plan acknowledgement, the
  verdict reading and the spike closure.
- Mohammad Iqbal — Product Owner: the blind visual comparison.
- **Codex — LivePortrait reproduction engineer** for this assignment, with
  self-review and the evidence discipline of the spike SA.

## Stop condition

Stop at **`SPIKE EVIDENCE PACKAGE READY FOR QA`** with the evidence package
and the report, or at **`SPIKE BLOCKED — <§15 condition>`** with the report.
Do not declare the brief complete, do not select a production approach, do
not begin an implementation milestone, and do not revisit the M3 verdict.
