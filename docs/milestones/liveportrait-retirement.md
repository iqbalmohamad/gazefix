# LivePortrait retirement — governance record

**Decision: `REJECTED — COMMERCIAL/PROVENANCE GATE FAILED`.**
**Date: 2026-09-07.** Recorded by the repository governance engineer on the
Product Manager's decision.

This is a governance record, not a research or engineering report. It removes
implementation authority; it does not rewrite history.

## What is retired

| Item | Value |
| --- | --- |
| Previous authority (Solution Architecture) | `model-feasibility-architecture-v1` @ `d66df8971086f5e0343ad24233aca6afaf505d16` |
| Previous active assignment lineage | `claude/model-feasibility-architecture` @ `531b5f3ac2632170cb5dc3c9073281cc3641013d` |
| Candidate | LivePortrait image retargeting via its official eye-gaze controls |
| Standing before this record | authorized for one bounded, offline, CPU-only feasibility reproduction |
| Standing after this record | **no authority of any kind for the current development cycle** |

## Reason

Commercially defensible rights and provenance for the **complete paid offline
Windows stack** were not established. This is a stronger conclusion than the
earlier due-diligence finding: the previous Solution Architecture already
recorded that LivePortrait as shipped fails the commercial criterion and
proceeded only as a quality-evidence experiment under an explicit deferral.
The Product Manager has now withdrawn that deferral. The candidate is
rejected outright rather than carried forward with an open licensing
question.

## What this decision removes

For the current development cycle, LivePortrait is **not** a production
candidate, a feasibility candidate, a benchmark, a visual teacher, a quality
oracle, a fallback, a backup model, or a comparison target.

No work may clone it, download its weights, execute it, reproduce it, port
its algorithm, copy its preprocessing, implement its gaze controls, add its
dependencies, add a `LivePortraitCorrectionEngine`, or use its outputs as a
benchmark.

**No implementation authority remains.** The previous Solution Architecture
is superseded as implementation authority on the date above.

## What this decision does not do

- It does **not** modify, retract or delete any frozen historical record.
  `model-feasibility-architecture-v1` @ `d66df8971086f5e0343ad24233aca6afaf505d16`
  remains immutable and remains an accurate record of a design that was
  genuinely reviewed and approved at the time. It stands as **historical
  audit evidence only**, with no forward authority.
- It does **not** change product code, dependencies, or any frozen milestone
  or architecture reference.
- It does **not** select or admit a replacement candidate.

## Standing state after retirement

- **M4 remains blocked.** No real-time integration is authorized.
- **`m3-geometric-baseline` @ `f3831b54728a4747c38c064351ec9f48419a2efb`
  remains frozen** as the reference geometric implementation. M3 remains
  `CHANGE APPROACH`, not `PASS`.
- **No replacement model holds Candidate Admission.** No Solution
  Architecture exists for any replacement candidate, and no model
  implementation is authorized.
- Replacement selection requires a **fresh Candidate Admission Gate** in
  which **commercial `UNKNOWN` counts as `FAIL`**.

## Future reconsideration

LivePortrait may be reconsidered only through a completely new,
PM-authorized commercial evaluation that establishes defensible rights and
provenance for the full paid offline Windows stack. Nothing in this record,
and nothing in the superseded Solution Architecture, constitutes such an
authorization.

## Contamination check at retirement

Verified before this record was written: no `codex/liveportrait-spike`
branch on any remote; no `spike/` or `experiments/` path tracked on any ref;
no LivePortrait, InsightFace or `buffalo_l` file tracked anywhere; no model
or weight file in the repository; `gazefix/`, `scripts/`, `tests/`,
`pyproject.toml` and `constraints-windows-py312.txt` byte-identical to
`m3-geometric-baseline`; no `torch`, `onnxruntime` or `gradio` in any
dependency manifest; no `LivePortraitCorrectionEngine`; the only asset-fetch
code is the frozen M1 MediaPipe explicit-fetch path. The reproduction was
never started.

One inert leftover is recorded rather than removed: `.gitignore` carries the
line `spike/liveportrait/upstream/`, an ignore rule added when the
superseded Solution Architecture was drafted. It names a path that has never
existed, grants no authority and affects no code. It is left in place because
this record does not clean up silently; the Product Manager may have it
removed at any time.
