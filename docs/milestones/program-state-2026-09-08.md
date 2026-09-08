# GazeFix program state — 2026-09-08 closeout before repository cleanup

**Status: `PROGRAM STATE CONSOLIDATED`**

**This document is the canonical current program-state record.** It is the
closeout checkpoint taken before the repository branch cleanup, and it
supersedes earlier governance branches as the place to read the program's
current state. It changes no product code, no dependency, no PRD text, no
frozen architecture, no frozen milestone reference, and no evaluation or
scoring evidence.

**Canonical current program-state pointer: branch `program-state-v1`.**

**Recorded: 2026-09-08. Documentation-only consolidation.**

**`ACTIVE ENGINEERING ASSIGNMENT: NONE`.** No engineering implementation,
research, or technical spike is active or authorized by this record.

Base: `codex/virtual-camera-delivery-spike-governance` at
`57b5a825945144e39d577b82f9571ec26419b0ff`, verified before editing. No
history is discarded; this branch is not based on `main`. Earlier governance
records are retained unchanged and are not rewritten to restate their past
state — the new state is recorded prospectively, here.

---

## A. Current product and program state

| Item | State | Notes |
| --- | --- | --- |
| **M0 — Technical foundation** | `PASS / CLOSED / FROZEN` | Frozen at `milestone-0`. Accepted debt (`PreparedCameraCloser` ambiguous `Thread.start()` bootstrap case) remains accepted and out of scope. |
| **M1 — Face and eye tracking** | `PASS / CLOSED / FROZEN` | Frozen at `milestone-1`. |
| **M2 — Gaze estimation** | `PASS / CLOSED / FROZEN` | Frozen at `milestone-2`. |
| **M3 — Geometric gaze correction** | Engineering-valid baseline; Product Owner visual verdict **`CHANGE APPROACH`** — **NOT PASS** | The implementation is correct against frozen SA v1.3 and passed independent engineering QA; its visual result does not meet the product-quality bar. Gate record: `docs/milestones/m3-evaluation.md`. The exact evaluated implementation remains frozen at `m3-geometric-baseline`. |
| **Candidate Admission (commercial pretrained)** | `CLOSED / FAIL` — `NO COMMERCIALLY ADMISSIBLE PRETRAINED PATH FOUND` | Decision date 2026-09-07. Record: `docs/milestones/candidate-admission-closure.md`. Reopening requires a new Candidate Admission Gate, where commercial `UNKNOWN` counts as `FAIL`. |
| **LivePortrait** | `RETIRED — REJECTED / COMMERCIAL-PROVENANCE GATE FAILED` | Not an implementation authority, candidate, benchmark, teacher, quality oracle, fallback, or comparison target. Record: `docs/milestones/liveportrait-retirement.md`. |
| **Maxine Phase 1A — visual feasibility** | **`MAXINE PHASE 1A VISUAL GATE: PASS`** | Bounded interpretation in §A.1 below. Evidence limitations preserved unchanged. |
| **Maxine Phase 1B — realtime / streaming feasibility** | **`MAXINE PHASE 1B: NOT YET AUTHORIZED`** | Not started. Requires a separate future Product Manager authorization and its own gate. No Phase 1B assignment is created by this record. |
| **Windows virtual-camera / conferencing integration feasibility** | **`CONDITIONAL PASS`** | Research evidence only. Required follow-up: **`IS A PRE-M8 TECHNICAL SPIKE REQUIRED? YES`**. See §A.3. |
| **Pre-M8 virtual-camera delivery spike** | **`AUTHORIZED BUT DEFERRED / NOT ACTIVE`** | The authorization is parked, not withdrawn. See §A.4. |
| **M4** | **`BLOCKED`** | The primary roadmap remains paused at the M3 → M4 boundary. Nothing in this record unblocks it. |
| **M8** | **`UNOPENED`** | Existing M8/MVP acceptance requirements are unchanged. No verdict or research outcome recorded here opens M8. |
| **PRD (`01-GazeFix-Product-Requirements-Document-v1.1.md`)** | **`UNCHANGED`** | Remains authoritative, including Windows 10/11 product scope, §16 (no training from scratch), and §27 (dependency and licensing policy). |
| **Canonical architecture baseline** | `architecture-v1` — `APPROVED / FROZEN / CANONICAL` | Unchanged, together with ADR-0002 and ADR-0003 and the provider-neutral `CorrectionEngine` boundary. |
| **Active engineering assignment** | **`NONE`** | See §A.5. |

A **Product Strategy Gate** remains required before any roadmap transition
that would change the original product requirements. No verdict recorded
here — Phase 1A `PASS` included — substitutes for that decision.

### A.1 Maxine Phase 1A — formal record and bounded interpretation

**`MAXINE PHASE 1A VISUAL GATE: PASS`**

This is the Product Owner's visual verdict, recorded as the final canonical
program state. The PASS means only that **NVIDIA Maxine Eye Contact has
demonstrated sufficient visual feasibility to justify continued bounded
investigation.**

It does **not** establish, imply, or authorize any of the following:

- realtime feasibility;
- streaming feasibility;
- production adoption of Maxine;
- product integration of any kind;
- cloud architecture approval;
- commercial deployment approval;
- M4 authorization;
- M8 authorization.

**Evidence limitations are preserved and unchanged.** The verdict's
provenance and its evidence limits remain recorded in
`docs/milestones/virtual-camera-integration-feasibility.md`, which states
that the verdict was supplied by the Product Manager and that the record does
not independently reproduce the evaluation or invent experimental details,
clip coverage, measurements, scores, or output hashes.

`docs/milestones/maxine-phase1a-engineering-report.md` and
`research/maxine-eye-contact/` remain **unchanged** and continue to describe
their original verification state, including that the remote Maxine call is
`NOT VERIFIED`, that the credential, Product Owner footage and network egress
were all absent from the engineering environment, and that of the eleven M3
captures only three are clips usable by a temporal video model. **No scoring
evidence is altered by this consolidation.**

### A.2 Maxine Phase 1B

**`MAXINE PHASE 1B: NOT YET AUTHORIZED`**

Phase 1B has not started. It requires a separate Product Manager
authorization and its own gate. Neither its research nor its implementation
is authorized here, and **no Phase 1B assignment is created by this
operation**. Phase 1A's `PASS` grants Phase 1B nothing.

### A.3 Windows virtual-camera / conferencing integration feasibility

**`WINDOWS VIRTUAL-CAMERA / CONFERENCING INTEGRATION FEASIBILITY: CONDITIONAL PASS`**

**`IS A PRE-M8 TECHNICAL SPIKE REQUIRED? YES`**

The research established a credible delivery path and concluded that a
pre-M8 technical spike is required. **This is research evidence only.** It is
not a product decision, a backend selection, a production acceptance, an M8
start, or a change to the Windows 10/11 product scope. The basis and its
stated unknowns remain recorded in
`docs/milestones/virtual-camera-delivery-spike.md`; documentation alone does
not establish GazeFix-specific enumeration, playback, media negotiation,
recovery, installation, or multi-consumer behaviour, and those remain
`UNKNOWN` until applicable spike evidence exists.

### A.4 Pre-M8 virtual-camera delivery spike

**`PRE-M8 VIRTUAL-CAMERA DELIVERY SPIKE: AUTHORIZED BUT DEFERRED / NOT ACTIVE`**

The prior governance authorization of 2026-09-08 **remains historically
valid** and is not withdrawn; its bounded scope, prohibitions, evidence
requirements and verdict definitions remain recorded in
`docs/milestones/virtual-camera-delivery-spike.md`, unchanged. Execution
priority has changed: **the authorization is parked.**

The spike **must not be executed** until a later Product Manager decision
explicitly reactivates it. **No technical-spike implementation is active, and
none exists in the repository.** Spike execution remains `NOT TESTED` and no
spike verdict is assigned.

### A.5 Active engineering assignment

**`ACTIVE ENGINEERING ASSIGNMENT: NONE`**

No engineering implementation should be active. Specifically not authorized:
Maxine Phase 1B, the virtual-camera delivery spike, M4–M7 work, M8
implementation, any correction backend adoption, any model
search/substitution/fallback, any reopening of Candidate Admission, and any
change to the PRD, frozen architecture, ADRs, frozen milestone references,
research records or evaluation evidence.

---

## B. Canonical and frozen reference table

All eleven previously frozen references were verified against the remote
immediately before this commit and **all eleven match**. No frozen reference
is changed, advanced, rewritten, force-pushed, or merged into by this
operation.

| Reference | SHA | Role |
| --- | --- | --- |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` | Repository default; frozen |
| `milestone-0` | `3b0a2eee8b0fc207875702250955e78173857957` | Frozen M0 |
| `milestone-1` | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` | Frozen M1 |
| `milestone-2` | `81e06118801c23d2337629fc676d6ad8ac13716a` | Frozen M2 |
| `architecture-v1` | `003180d52d39d30a038333541b1b187824714e87` | Canonical post-M2 architecture baseline; intended branch point for future milestone work |
| `m3-architecture-v1` | `a459e6be36122bf10ce707731d5f847007847e96` | Original frozen M3 Solution Architecture |
| `m3-architecture-v1.1` | `00eed0e893b73dcd490f69af8df852a0609ccbaa` | Superseded canonical (A1) |
| `m3-architecture-v1.2` | `6a64ab7ae55a4c2c3e71f7084b9ed48b51c91b93` | Superseded canonical (A1+A2) |
| `m3-architecture-v1.3` | `d91d393eb6e3e5f93ee2122bc840f776a55872e5` | **Canonical frozen M3 Solution Architecture** (A1+A2+A3) |
| `m3-geometric-baseline` | `f3831b54728a4747c38c064351ec9f48419a2efb` | Frozen geometric reference implementation |
| `model-feasibility-architecture-v1` | `d66df8971086f5e0343ad24233aca6afaf505d16` | Immutable historical audit evidence only; no forward authority |

### `program-state-v1`

**`CANONICAL CURRENT PROGRAM-STATE POINTER`**

`program-state-v1` is the branch to read for the program's **current** state.
It is **not** a replacement for the historical milestone, architecture, or
baseline frozen references above, and it carries no product, architectural,
or acceptance authority of its own. Those eleven references remain the
authorities for what they each freeze; `program-state-v1` records only where
the program currently stands.

It is advanced only by a later documentation-only program-state
consolidation, never by implementation work.

---

## C. Historical and audit branch retention

The following branches are **explicitly retained** as named historical/audit
references. They are not work branches, not deletion candidates, and not
subject to the cleanup classes in §E. This restates, by name, retention
promises previously spread across several superseded assignment revisions.

| Branch | Retained because |
| --- | --- |
| `claude/architecture-pass` | The architecture review branch. Governance: "retained as the review branch; PR #6 is the review record and is **not** to be merged into `milestone-2`." |
| `claude/m3-solution-architecture` | The retained M3 Solution Architecture review record, together with PR #7. Cited as the review record in the SA freeze header. |
| `claude/m3-sa-blend-amendment` | Amendment A1 branch. "None is a work branch." |
| `claude/m3-sa-source-iris-amendment` | Amendment A2 branch. "None is a work branch." |
| `claude/m3-sa-tolerance-amendment` | Amendment A3 branch. "None is a work branch." Also the head of open PR #8. |
| `claude/model-feasibility-architecture` | The model-feasibility spike SA review record, together with PR #10. |
| `codex/m1-tracking-foundation` | Pre-restart M1 tracking work, named in governance as "historical work outside this new baseline". It is the **sole holder** of commits `de1101fa4890345cede7468eee3c59149b0bc0e6` and `9d235db`; deleting it would destroy an entire alternate M1 implementation lineage. |
| `codex/m3-assignment` | See below. |

**`codex/m3-assignment` — retention rationale.** Its unique commit
`06c9c5926fde425c49c3776f5bfd110df18a9538` contains the **original,
superseded M3 implementation assignment** and is **not reachable from any
other retained reference.** The branch that superseded it,
`codex/m3-assignment-v1.1`, was created from `m3-architecture-v1` rather than
from `codex/m3-assignment`, so the original assignment commit was left
stranded rather than absorbed. Deleting the branch would make that commit
unreachable and would break the project's own stated convention that
"superseded assignment text is preserved in Git history rather than in this
file." **Do not delete or rewrite it.**

The five closed and retained review records are the deliberate exception to
mechanical de-duplication: `claude/architecture-pass`,
`claude/m3-solution-architecture` and the three amendment branches each point
at exactly the same SHA as a canonical alias, yet each is retained because a
governance statement names it. **Identical-SHA reachability alone never
authorizes deleting a branch a governance document names as retained.**

Pull requests **#6** and **#7** are closed-unmerged **review records, not
abandoned work.** They must not be reopened, merged, or treated as cleanup
debt, and their head branches must not be deleted.

---

## D. Audit discrepancy — recorded, not repaired

The frozen M3 implementation reports
`docs/milestones/m3-v11-implementation-report.md` and
`docs/milestones/m3-v12-implementation-report.md` state that the original
pre-rebase M3 implementation commit is "also retained by `codex/m3-pre-v1.1`".

**That branch is not present locally or on the remote.**

Recorded explicitly:

- **This is not frozen-reference drift.** `codex/m3-pre-v1.1` has never been
  a member of the frozen reference table in §B. All eleven frozen references
  verify as matching.
- **No frozen document is edited to correct it.** Both reports are frozen at
  `m3-geometric-baseline`; correcting the citation would require amending
  frozen milestone evidence, which is not authorized and is not done.
- **The discrepancy is retained as an audit note** in this record, so that a
  future reader of those reports finds the reference explained rather than
  silently broken.

---

## E. Cleanup authorization classes

Intended future cleanup classes, recorded for a later, separate branch-deletion
assignment. **No branch is deleted by this operation, and this record is not a
deletion authorization** — a future PM-issued cleanup assignment is required.

### Class 1 — SAFE TO DELETE NOW, after this program-state checkpoint is verified

Each is a merged or fully-contained implementation branch whose every commit
is reachable from a frozen reference, named by no retention statement, and
touched by no open pull request.

| Branch | Preserved by |
| --- | --- |
| `claude/m0-camera-hardening` | Strict ancestor of frozen `milestone-0`; PR #2 merged |
| `claude/m0-followup-hardening` | Strict ancestor of frozen `milestone-0`; PR #3 merged |
| `claude/m1-face-eye-tracking` | Strict ancestor of frozen `milestone-1`; PR #4 merged |
| `claude/m2-gaze-estimation` | Strict ancestor of frozen `milestone-2`; PR #5 merged |
| `codex/m3-assignment-v1.1` | Strict ancestor of frozen `m3-geometric-baseline`; no pull request |

### Class 2 — SAFE TO DELETE AFTER RELEVANT PR CLOSURE / CONSOLIDATION

| Branch | Precondition | Preserved by |
| --- | --- | --- |
| `claude/m3-closeout-and-spike` | PR #9 and PR #10 closed | Commit `a22b86c` reachable from `model-feasibility-architecture-v1` and `program-state-v1` |
| `codex/m3-gaze-correction` | PR #9 closed | HEAD identical to frozen `m3-geometric-baseline`; the evaluation record designates that alias as the preservation vehicle |
| `codex/commercial-first-research-recovery` | PR #11 closed | Strict ancestor of `program-state-v1` |
| `codex/maxine-phase1a-governance` | PR #12 dispositioned | Strict ancestor of `program-state-v1` |
| `codex/m1-assignment` | PR #12 dispositioned | Strict ancestor of `program-state-v1` |
| `codex/virtual-camera-feasibility-governance` | This checkpoint verified | Strict ancestor of `program-state-v1` |
| `codex/virtual-camera-delivery-spike-governance` | This checkpoint verified | Strict ancestor of `program-state-v1` — see below |

**`codex/virtual-camera-delivery-spike-governance` is intentionally included
in Class 2.** It was the canonical current-state pointer until this
checkpoint. `program-state-v1` is a direct descendant of it, so every commit
it holds is reachable from `program-state-v1`; once this checkpoint is
verified it is historical stepping-stone state and **no longer the canonical
current-state pointer.** Its governance content, including the spike
authorization document it introduced, is carried forward in this branch
unchanged.

**Deletion ordering constraint.** GitHub closes a pull request when its head
**or** base branch is deleted. Every Class 2 branch except the two
virtual-camera governance branches is bound to an open pull request. Close
PRs #9, #10 and #11 and disposition PR #12 **before** any Class 2 deletion,
with "delete branch on close" disabled, so each pull-request record closes
deliberately rather than as a side effect.

**Nothing in this record authorizes merging any pull request.**

---

## F. Branch retention policy going forward

Recommended repository policy:

1. **Canonical frozen milestone, architecture and program-state references
   are retained.** A frozen branch survives supersession by design;
   "superseded" is never on its own a deletion reason.
2. **Explicitly designated audit branches are retained** — the set named in
   §C, and any branch a future governance document names in the same way.
3. **Worker and implementation branches are disposable** once their state is
   preserved by a canonical reference.
4. **Governance stepping-stone branches are disposable** once a later
   canonical program-state checkpoint subsumes them.
5. **Do not retain both a worker branch and its canonical alias merely
   because both exist**, unless historical governance explicitly requires
   both — as it does for the five review records in §C.
6. **Branch deletion must never rewrite frozen history.** No rebase, amend,
   force-push, or merge into a frozen reference, at any point in a cleanup.
7. **Future cleanup should be intentional rather than accumulated
   indefinitely** — a bounded, PM-authorized cleanup assignment, with a
   verified program-state checkpoint taken first, rather than deletion as a
   side effect of closing pull requests.

---

## G. Repository cleanup audit disposition

A **dry-run repository cleanup audit completed on 2026-09-08**. It made no
repository change: no file modified, no branch created or deleted, no
reference moved, no pull request changed, no commit created, no push, no
worktree removed.

Findings recorded here:

- **31 remote branches**, 0 tags, 100 commits, 1 clean worktree.
- **No frozen-reference drift** — all eleven references in §B verified
  matching.
- Maxine Phase 1A `PASS` was **not yet represented as the final canonical
  program state** — resolved by §A.1.
- The then-current assignment **incorrectly left the pre-M8 virtual-camera
  delivery spike active** — resolved by §A.4 and by the rewritten
  `Current Assignment.md`.
- Maxine Phase 1B **had not been authorized** — restated in §A.2.
- Active engineering assignment **should be `NONE`** — set in §A.5.
- One documented-but-absent branch reference, `codex/m3-pre-v1.1` — recorded
  in §D.

Earlier governance documents are **not** altered to rewrite their past state.
This record is prospective.

---

## H. Sources of truth

In precedence order. Unchanged by this consolidation except for the addition
of this document at position 7.

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
7. **This document** — the canonical current program state, at branch
   `program-state-v1`.

The model-feasibility architecture and spike records, and other retired
records, remain historical evidence with no forward authority.

## Roles

- ChatGPT — Product Manager / Technical Lead: scope, acceptance, gate
  decisions, and any subsequent authorization.
- Mohammad Iqbal — Product Owner: visual-quality judgment.
- Codex / Claude — engineering within the bounded PM-issued assignment.
