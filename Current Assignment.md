# GazeFix — Current Engineering Assignment

**Active assignment: NVIDIA Maxine Eye Contact hosted-cloud visual feasibility — Phase 1A**

**Candidate Admission: FAIL — NO COMMERCIALLY ADMISSIBLE PRETRAINED PATH FOUND**
The previous commercial-first local/offline pretrained Candidate Admission
cycle is **CLOSED** (PM decision: 2026-09-07). See
`docs/milestones/candidate-admission-closure.md`.

**M4 remains BLOCKED.**

**LivePortrait remains REJECTED — COMMERCIAL/PROVENANCE GATE FAILED.**
See `docs/milestones/liveportrait-retirement.md`.

**M0 / M1 / M2: PASS / CLOSED / FROZEN.**

**M3: `CHANGE APPROACH` — NOT PASS** (`docs/milestones/m3-evaluation.md`).
`m3-geometric-baseline @ f3831b54728a4747c38c064351ec9f48419a2efb` remains
the frozen reference geometric implementation.

**Overall architecture baseline (`architecture-v1`): APPROVED / FROZEN / CANONICAL** — unchanged.

**Updated: 2026-09-08.**

## PM authorization and sole Phase 1A question

The Product Manager has authorized
**`NVIDIA MAXINE EYE CONTACT HOSTED CLOUD VISUAL FEASIBILITY — PHASE 1A`**.

Cloud inference is permitted **for this bounded research feasibility
evaluation only**, using NVIDIA's official hosted Maxine Eye Contact
evaluation/trial API. This is an explicit PM exception to the local/offline
constraint for the experiment. It does not change the PRD's production
requirements, production privacy constraints, or frozen architecture, and
does not authorize cloud productization.

> Does NVIDIA Maxine Eye Contact produce correction that is materially more
> natural than GazeFix's frozen geometric baseline and good enough for the
> Product Owner to consider using in a real video call?

This is research/evaluation execution authority only. It does not admit a
local/offline replacement candidate or reopen the failed Candidate Admission
cycle. No replacement Solution Architecture or model implementation from
that cycle is authorized; no fallback candidate is authorized.

## Authorized Phase 1A work

- Evaluation-only scripts and tools outside normal product runtime paths.
- Deterministic preparation of existing Product Owner evaluation footage.
- Bounded upload and remote submission of existing PO evaluation clips to
  the official NVIDIA Maxine Eye Contact hosted evaluation/trial API for
  research/evaluation.
- Retrieval and local storage of generated evaluation outputs outside
  normal product runtime paths; footage and rendered outputs remain
  uncommitted.
- Comparison against the frozen geometric baseline, preserving its behavior.
- Blind comparison tooling and blind PO visual-gate preparation.
- Scoring manifests, hashes, and audit metadata.

No Phase 1A result is recorded yet. Report evaluation evidence at its true
verification level under `docs/qa-policy.md`; do not infer visual acceptance
from successful API execution or engineering completeness.

## Phase 1A boundaries

The authorization does **not** permit:

- Maxine product integration, a Maxine `CorrectionEngine`, or a cloud
  correction provider implementation.
- Realtime streaming, live-webcam correction, or production cloud
  architecture.
- Self-hosted NVIDIA NIM deployment or GPU infrastructure provisioning for
  production.
- Virtual camera work, M4, or later-milestone implementation; no
  staged-processor or pipeline integration, `ProcessedFrame`/
  `ProcessorOutput` changes, correction metrics in `PipelineMetrics`, or
  continuity-epoch implementation.
- Training, fine-tuning, or synthetic training-data development.
- Another model search, candidate substitution, alternative model, or
  fallback model.
- Vendor/OEM outreach, Effects SDK investigation, Casablanca investigation,
  or Eyesmatch investigation.
- LivePortrait in any role.
- Modification or tuning of frozen geometric behavior, frozen architecture,
  or any frozen reference or document.
- Speculative production pricing or latency work.
- Changes to product code or product dependencies. Evaluation tooling stays
  separate from `gazefix/` and the frozen product `scripts/` and `tests/`;
  product dependency manifests remain unchanged.
- Committing API credentials, model assets, webcam footage, or rendered PO
  outputs.

**No automatic transition follows a Phase 1A visual PASS.** The Product
Manager must make a separate decision before any realtime/cloud feasibility
stage. A visual PASS does not grant Candidate Admission, production
integration authority, or M4 authority.

## LivePortrait is retired

LivePortrait remains permanently rejected for this development cycle:
**`REJECTED — COMMERCIAL/PROVENANCE GATE FAILED`**. It is not a candidate,
benchmark, teacher, quality oracle, fallback, backup model, comparison target,
or implementation dependency.

Do not clone it, download its weights, execute it, reproduce it, port its
algorithm, copy its preprocessing, implement its gaze controls, add its
dependencies, add a `LivePortraitCorrectionEngine`, or use its outputs as a
benchmark.

`model-feasibility-architecture-v1` and all LivePortrait documents and commits
remain **immutable historical audit evidence only**, with no forward
authority. The retirement decision is unchanged; this Maxine authorization
does not authorize LivePortrait reconsideration.

## Sources of truth

1. `01-GazeFix-Product-Requirements-Document-v1.1.md` — product scope,
   constraints, licensing/dependency policy, and milestone gates. The PM's
   research-only cloud exception is recorded explicitly above and in the
   closure record; production constraints remain unchanged.
2. `docs/architecture.md`, accepted ADRs in `docs/decisions/`, and
   `docs/milestones/m3-solution-architecture.md` at `m3-architecture-v1.3`
   — frozen architecture and provider-neutral correction boundary.
3. `docs/milestones/m3-evaluation.md` — M3 `CHANGE APPROACH` gate result.
4. `docs/milestones/liveportrait-retirement.md` — unchanged retirement record.
5. `docs/milestones/candidate-admission-closure.md` — completed Candidate
   Admission decision and the bounded follow-up PM authorization.
6. `docs/qa-policy.md` — verification depth, truthful reporting, stopping
   rules, and Product Owner interaction budget.

`docs/milestones/model-feasibility-architecture.md` and
`docs/milestones/model-feasibility-spike.md` are historical records, not
current work authority. Historical references to a fallback or future model
work do not override the current prohibitions above.

## Governance checkpoint and delivery scope

This update descends from `codex/commercial-first-research-recovery` at
`9fa8530ae4549c63d2293c8e5cebf15791fb2833`, on the governance branch
`codex/maxine-phase1a-governance`, preserving the active governance lineage.
The published governance commit is the assignment checkpoint; do not merge
it into a frozen branch.

This governance update changes only `Current Assignment.md` and
`docs/milestones/candidate-admission-closure.md`. Its delivery stops after
documentation audit, commit, and push. The Phase 1A authorization above is
for subsequent evaluation work: this governance task must not implement
evaluation tools, execute models, or call NVIDIA's API.

## Frozen repository state

| Reference | SHA |
| --- | --- |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` |
| `milestone-0` | `3b0a2eee8b0fc207875702250955e78173857957` |
| `milestone-1` | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| `milestone-2` | `81e06118801c23d2337629fc676d6ad8ac13716a` |
| `architecture-v1` | `003180d52d39d30a038333541b1b187824714e87` |
| `m3-architecture-v1` | `a459e6be36122bf10ce707731d5f847007847e96` |
| `m3-architecture-v1.1` | `00eed0e893b73dcd490f69af8df852a0609ccbaa` |
| `m3-architecture-v1.2` | `6a64ab7ae55a4c2c3e71f7084b9ed48b51c91b93` |
| `m3-architecture-v1.3` | `d91d393eb6e3e5f93ee2122bc840f776a55872e5` |
| `m3-geometric-baseline` | `f3831b54728a4747c38c064351ec9f48419a2efb` |
| `model-feasibility-architecture-v1` | `d66df8971086f5e0343ad24233aca6afaf505d16` — historical evidence only |

All eleven are frozen: do not advance, rewrite, force-push, or merge into
them. Architecture and amendment review branches are retained review
records, not work branches. Accepted M0 debt (`PreparedCameraCloser`'s
ambiguous `Thread.start()` bootstrap case in `docs/architecture.md`) remains
accepted and out of scope.

## Roles

- ChatGPT — Product Manager / Technical Lead: scope, acceptance, gate
  decisions, and any subsequent authorization.
- Mohammad Iqbal — Product Owner: visual-quality judgment.
- Codex / Claude — engineering within the bounded PM-issued assignment.
