# GazeFix — Current Engineering Assignment

**Active assignment: Repository recovery complete — next authorized activity is
independent COMMERCIAL-FIRST MODEL FEASIBILITY RESEARCH**

**LivePortrait: `REJECTED — COMMERCIAL/PROVENANCE GATE FAILED`** (2026-09-07).
Record: `docs/milestones/liveportrait-retirement.md`.

**No model implementation is authorized. No replacement candidate has
Candidate Admission. M4 remains BLOCKED.**

**M0 / M1 / M2: PASS / CLOSED / FROZEN**

**M3: `CHANGE APPROACH` — NOT PASS** (`docs/milestones/m3-evaluation.md`).
`m3-geometric-baseline @ f3831b54728a4747c38c064351ec9f48419a2efb` remains
frozen as the reference geometric implementation.

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL** — unchanged.

**Updated: 2026-09-07**

## LivePortrait is retired

LivePortrait is rejected for the current development cycle. It is **not** a
production candidate, a feasibility candidate, a benchmark, a visual teacher,
a quality oracle, a fallback, a backup model, or a comparison target.

Do not clone it, download its weights, execute it, reproduce it, port its
algorithm, copy its preprocessing, implement its gaze controls, add its
dependencies, add a `LivePortraitCorrectionEngine`, or use its outputs as a
benchmark.

**`model-feasibility-architecture-v1` @ `d66df8971086f5e0343ad24233aca6afaf505d16`
is superseded as implementation authority.** It and every other LivePortrait
document and commit remain **immutable historical audit evidence** and are
neither modified nor deleted. They carry no forward authority.

**No LivePortrait implementation is authorized.**

## What is authorized next

Independent **commercial-first model feasibility research**, and nothing else.
It is the next activity after this repository recovery; this pointer does not
itself start it, and the Product Manager issues that assignment separately.

**Research does not authorize implementation.** A research result — however
positive — does not select a candidate, does not create design authority, and
does not permit code.

## Rules for any future model selection

- **No replacement model has Candidate Admission.** None is selected.
- Model selection may occur **only through a new Candidate Admission Gate**.
- **Commercial `UNKNOWN` = `FAIL`.** Unresolved rights, licensing or
  provenance for the complete paid offline Windows stack fails the gate;
  an open question is not something to resolve later.
- **No Solution Architecture exists for any replacement candidate.** One may
  be written only after a candidate passes Candidate Admission, and only on a
  PM-authorized assignment.
- **No model implementation is authorized** at any point before both of the
  above have happened.

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
| `model-feasibility-architecture-v1` | `d66df8971086f5e0343ad24233aca6afaf505d16` — **historical evidence only, superseded as authority** |

All eleven are frozen: do not advance, rewrite, force-push, or merge into any
of them. The `claude/*` architecture and amendment branches, and
`claude/model-feasibility-architecture`, are retained review records, not work
branches.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case in `docs/architecture.md`) remains accepted and out of scope.

## Sources of truth, in precedence order

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — product scope,
   constraints, milestone gates; §16 (no training from scratch), §27
   (dependency and licensing policy) and M9 govern model work.
2. `docs/architecture.md` and the accepted ADRs (`docs/decisions/`) — frozen
   architecture, including the provider-neutral correction boundary, which
   remains unchanged.
3. `docs/milestones/liveportrait-retirement.md` — the retirement record.
4. `docs/milestones/m3-evaluation.md` — the M3 gate result.
5. `docs/qa-policy.md` — verification depth, stopping rules, Product Owner
   interaction budget.

`docs/milestones/model-feasibility-architecture.md` and
`docs/milestones/model-feasibility-spike.md` are historical records. Neither
is a source of truth for current work.

## Boundaries

- **No model implementation**, for LivePortrait or any other candidate.
- **No Solution Architecture** for any replacement candidate.
- **No M4 work**: no live-webcam correction, no staged-processor or pipeline
  integration, no `ProcessedFrame`/`ProcessorOutput` changes, no correction
  metrics in `PipelineMetrics`, no continuity-epoch implementation.
- **No new runtime dependency**, no model file, no download or execution of
  any model.
- **No change to product code** (`gazefix/`, `scripts/`, `tests/`,
  `pyproject.toml`, `constraints-windows-py312.txt`).
- **No change to any frozen reference or frozen document**, including the
  superseded LivePortrait Solution Architecture.
- **No webcam captures committed.**
- **No automatic milestone transition.** The Product Manager issues each
  assignment.

## Roles

- ChatGPT — Product Manager / Technical Lead: scope, acceptance, gate
  decisions, Candidate Admission, and the assignment that starts research.
- Mohammad Iqbal — Product Owner: visual quality judgment when a gate calls
  for it.
- Codex / Claude — engineering, on a PM-issued assignment only.
