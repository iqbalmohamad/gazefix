# Model-based gaze-correction feasibility spike

**Status: ACTIVE (activated 2026-09-07).**
This is a **feasibility investigation**. It is **not M4**, not production
implementation, and not authorization to build or train anything.

## Why this exists

The M3 Product Owner gate returned **`CHANGE APPROACH`**
(`m3-evaluation.md`). Frozen SA §14.3 prescribes the response directly:
when structural defects of the geometric class persist, "the roadmap's M9
neural evaluation moves earlier — a PM decision, surfaced at the gate".
This spike is that decision taken. It brings **PRD M9 — Neural Model
Evaluation** forward, using M9's own acceptance criteria, without
redesigning the roadmap.

## The question to answer

> Is there a lightweight model-based gaze-redirection approach that produces
> materially more natural results than the geometric M3 baseline while
> remaining plausibly CPU-deployable on the target Windows laptop?

Three outcomes are all legitimate, and a well-evidenced "no" is as valuable
as a "yes":

- **a candidate is worth prototyping** — name it, with evidence;
- **no candidate clears the constraints** — say so, with the specific
  blocker per candidate;
- **the evidence is inconclusive** — say what is missing and what it would
  cost to resolve.

## Baseline to beat

| Item | Value |
| --- | --- |
| Frozen geometric baseline | branch **`m3-geometric-baseline`** @ `f3831b54728a4747c38c064351ec9f48419a2efb` |
| Its gate result | `CHANGE APPROACH` — eye realism 2/5, artifact visibility 1–2/5, eyelid preservation 2–3/5, key criterion NO on both stills |
| Its measured cost | 720p correction ≈ 9.4 ms median / 12.4 ms p90 on the target-class CPU, per `m3-v12-performance.json` |
| How to reproduce comparisons | the existing offline harness (`docs/correction.md`); it renders before/after sheets on any still or clip |

"Materially more natural" means a Product Owner would score it clearly
better on the dimensions that failed — eye realism, artifact visibility,
eyelid preservation — and would answer **yes** to the key criterion. The
geometric baseline's iris realism of 4/5 is the one dimension a candidate
must not regress.

## Target constraints (from the PRD, not negotiable in this spike)

The application must work on Windows 10/11, an Intel Core i7-class CPU and
Intel Iris Xe integrated graphics. Screening criteria, in priority order:

1. **Available source code** — inspectable, not a paper alone.
2. **Available pretrained weights** — strongly preferred. **Training from
   scratch is out of scope** (PRD §16 forbids it for this phase); a
   candidate that only works after training is not a candidate here.
3. **Licence compatible with eventual commercial use** — for both code and
   weights, which often differ. Research-only, non-commercial or
   unspecified terms are a disqualifying finding, not a detail to resolve
   later. Record the licence verbatim with its source.
4. **CPU inference feasibility** — no mandatory NVIDIA GPU, no mandatory
   NPU, no CUDA. ONNX Runtime is the PRD's sanctioned neural runtime when
   evaluation begins; exportability to ONNX counts in a candidate's favour.
5. **Windows feasibility** — no Linux-only build steps, no unavailable
   toolchains.
6. **Modest dependency burden** — a candidate dragging in a large training
   stack is worse than one that runs from a single exported graph.
7. **Acceptable eye realism** — the reason the spike exists.

Candidate classes to investigate, as starting points rather than a closed
list: ECC-Net and ECC-Net-like gaze redirection; lightweight pretrained
gaze-redirection networks; eye-region neural warping or synthesis; and any
other credible model-based eye-contact correction technique found during
scouting.

## Method

1. **Scout** the candidate space. Breadth first. Record what exists, not
   what should exist.
2. **Screen** each candidate against the seven criteria above. Most will
   fail early — that is the point, and an early failure is a cheap result.
   Verify licence, weights availability and hardware requirements against
   **primary sources** (the repository, its licence file, the model card),
   never from a summary or from memory.
3. **Compare** survivors against the geometric baseline on the same inputs
   wherever a runnable artifact exists. Where a candidate cannot be run
   within the spike's budget, say so explicitly rather than estimating its
   quality.
4. **Report** with per-candidate evidence and a single recommendation.

## Deliverable

One written report recording, per candidate: what it is, source and weights
availability with links, the exact licence for code and weights, hardware
and runtime requirements, dependency burden, whether it ran and on what, any
comparison against the geometric baseline, and a screening verdict with the
specific blocker where it failed. Then one overall recommendation and the
evidence gaps that remain.

Claims must be reported at their true verification level. "Documented as
CPU-capable" and "observed running on CPU" are different statements and must
read differently.

## Boundaries

- **Do not implement a neural correction engine.** No production model
  integration, no new engine in `gazefix/correction/`.
- **Do not train a model** from scratch or otherwise.
- **Do not begin M4.** Real-time integration remains unauthorized.
- **Do not modify the frozen geometric baseline**, the frozen M3 SA, the
  ADRs, the PRD, or any frozen reference.
- **Do not add a runtime dependency** to the shipping application. Anything
  installed for the spike is spike-local and must be recorded as such.
- **Keep the architecture intact.** The `CorrectionEngine` protocol,
  ADR-0002/0003 and the provider-neutral boundary stay as they are. They
  were designed so the correction implementation can be replaced without an
  application rewrite, and the M3 result validates rather than undermines
  them. Propose changing them only if a candidate's evidence proves them
  unsuitable — with that evidence, as an escalation, not as a side effect.
- **No webcam captures committed**, per standing repository policy.

## Stop condition

Stop at **MODEL FEASIBILITY SPIKE COMPLETE** with the report, or at
**MODEL FEASIBILITY SPIKE BLOCKED** with the reason. Do not select a
production approach, do not start an implementation milestone, and do not
declare M3 `PASS` — the gate has already returned `CHANGE APPROACH`.
