# M3 Product Owner evaluation — gate record

**Gate verdict: `CHANGE APPROACH`** (frozen SA §14.3).
**M3 is NOT `PASS`. M4 is NOT authorized.**

This is the recorded M3 Product Owner visual-quality gate required by
SA §14 and PRD §25/§28/§29. It supersedes the `NOT EVALUATED` status
carried by `m3-po-checklist.md`. Engineering completeness was never the
gate; the gate is this document.

## Session

| Item | Value |
| --- | --- |
| Date | 2026-09-07 |
| Evaluator | Mohammad Iqbal (Product Owner) |
| Evaluated implementation | `codex/m3-gaze-correction` @ `f3831b54728a4747c38c064351ec9f48419a2efb` |
| Preserved as | branch **`m3-geometric-baseline`** @ the same SHA — frozen reference implementation |
| Frozen SA | `m3-architecture-v1.3` @ `d91d393eb6e3e5f93ee2122bc840f776a55872e5` |
| Independent engineering QA | `M3 TARGETED QA PASS — READY FOR PO VISUAL GATE` |
| Session form | **quick visual gate — two representative corrected stills**, not the full eleven-experiment budgeted session of `m3-po-checklist.md` |

Captures and rendered sheets remain local and uncommitted, as required.

## Scores

Scored 1 (unacceptable) to 5 (indistinguishable from a real photo).

| Dimension | `horizontal-no-glasses` | `lens-no-glasses` |
| --- | --- | --- |
| Eye realism | 2 | 2 |
| Iris realism | 4 | 4 |
| Eyelid preservation | 3 | 2 |
| Identity preservation | 4 | 3 |
| Artifact visibility | 1 | 2 |
| Perceived eye contact | 1 | 3 |
| **Key criterion** — correction less distracting than the original lack of eye contact | **NO** | **NO** |

Risks observed on both stills: **obvious artifact**, **lid-edge steps**.

## Not evaluated in this session

Recorded so the evidence is not overstated. The remaining checklist items
carry no score and no inference was made from their absence:
`screen-no-glasses`, `notes-no-glasses`, all four glasses stills, and the
three clips (`speaking-smiling`, `minor-rotation`, `blink-wink-squint`) —
so blink realism and the temporal notes are unrecorded. Per-experiment
measured deviation and effective strength were not transcribed, so
operating-range coverage is not quantified in this record.

## Reading against frozen SA §14.3

The verdict follows the frozen framework rather than overriding it. Three
of the section's `CHANGE APPROACH` conditions are met on the evidence
above:

1. **The key criterion is "no" across the evaluated range** — both stills,
   including the direct `lens` case. §14.3 requires "yes" on a clear
   majority for `PROCEED`.
2. **A disqualifying artifact class is present** — artifact visibility 1
   and 2 with "obvious artifact" and "lid-edge steps" called out. These are
   defects visible at normal viewing size that a viewer would attribute to
   editing, which §14.3 names as disqualifying.
3. **Eyelid preservation is below 4** (3 and 2), which §14.3 requires not
   to be below 4 anywhere for `PROCEED`.

Eye realism of 2 on both stills is the "dead/synthetic look" §14.3 names as
a structural defect of the geometric class. Iris realism of 4 is consistent
with the design: A2's rigidly translated iris layer preserves iris texture,
and the failure is in the surrounding sclera, lid relation and edges, not in
the iris itself. The lid-edge steps correspond to the risk the SA already
registered as **Q12** and accepted deliberately at freeze, subject to this
gate. `ITERATE` was not selected because the defects are not tuning-class
and the key criterion fails at the direct-lens case, not only at the range
edges.

## PM decision

**Accepted.** The layered geometric implementation is technically correct
against its frozen design and independently QA-verified, but it does not
meet the GazeFix product-quality bar.

- The geometric approach is **discontinued as the primary production
  candidate**. No further tuning of it is authorized as production work.
- **M3 is not `PASS`.** No milestone transition is implied.
- **M4 real-time integration remains unauthorized.**
- SA §14.3 anticipated this outcome and prescribes the response: the
  roadmap's **M9 neural model evaluation moves earlier**, as a PM decision
  surfaced at the gate. That is what has happened; see
  `model-feasibility-spike.md`.

## Geometric implementation disposition — retained, not discarded

The implementation at `f3831b5` is preserved verbatim on the frozen
`m3-geometric-baseline` branch and remains valuable as:

1. a **reproducible baseline** — the offline harness renders comparable
   before/after sheets on demand for any candidate comparison;
2. a **fallback / reference implementation** — a working, never-raising,
   CPU-only correction path that exists today;
3. an **architectural contract validation** — it proves the `CorrectionEngine`
   protocol, the metadata-only result contract, frame ownership and the
   atomic fallback are implementable, and that the rest of the application
   does not care which implementation is active (PRD §15);
4. a **quantitative benchmark** — its measured behaviour, timings and this
   gate's scores are the bar any candidate must beat.

Nothing about this verdict invalidates the frozen SA v1.3, the ADRs, or the
provider-neutral boundary. What failed the gate is the *technique* the SA
selected (D4, layered eye-region remap), which the SA itself flagged as
subject to a `CHANGE APPROACH` outcome.

## Remaining limitations of this record

The gate ran as a quick two-still session rather than the budgeted
eleven-experiment matrix. The verdict is directionally unambiguous — the key
criterion failed on both stills including the direct-lens case, with a
disqualifying artifact class on both — but this record does not establish
per-capture operating-range coverage, glasses behaviour, or temporal/blink
behaviour. Should any future decision depend on those specifics rather than
on the overall verdict, they need capturing then; they are not needed to
support `CHANGE APPROACH`.
