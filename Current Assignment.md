# GazeFix — Current Engineering Assignment

**Active assignment: NONE — awaiting the next Product Manager assignment**

**M0 status: PASS / CLOSED / FROZEN**

**M1 status: PASS / CLOSED / FROZEN**

**M2 status: PASS / CLOSED / FROZEN**

**Overall architecture baseline: APPROVED / FROZEN / CANONICAL**

**Updated: 2026-09-05**

There is no authorized engineering work in progress. Milestone 3 has **not**
been assigned, its Solution Architecture has **not** been written, and no
correction code exists. Do not begin M3, draft M3 SA, or create a milestone
branch on the strength of this file. Wait for a Product Manager assignment.

## Frozen repository state

| Item | Value |
| --- | --- |
| Frozen M0 baseline (`milestone-0`) | `3b0a2eee8b0fc207875702250955e78173857957` |
| Frozen M1 baseline (`milestone-1`) | `097c4d69b9e7c7e8a2772445315ccb51a263dca7` |
| Frozen M2 baseline (`milestone-2`) | `81e06118801c23d2337629fc676d6ad8ac13716a` |
| `main` | `b40d74faef55811d67de258660b6040c7c8dc790` (M0 merge) |
| Reviewed architecture content | `9beac0f015a1e53ef42b6e70d556749409da5903` |
| Canonical architecture baseline | `architecture-v1` (this commit; adds only ADR/status metadata on top of the reviewed content) |

`main`, `milestone-0`, `milestone-1`, and `milestone-2` are frozen. Do not
advance, rewrite, force-push, or merge into any of them.

Accepted M0 debt (the `PreparedCameraCloser` ambiguous `Thread.start()`
bootstrap case documented in `docs/architecture.md`) remains accepted and out
of scope; its stated reopening triggers are unchanged.

## Architecture baseline

The overall architecture pass ran on the frozen M2 baseline, was independently
reviewed, received targeted corrections, and was approved by the Product
Manager. It is now the canonical post-M2 architecture baseline and is frozen.

Its content lives in:

- `docs/architecture.md` — Part I, the frozen M0/M1/M2 system as it actually
  exists; Part II, the accepted architecture baseline for M3–M10.
- `docs/decisions/ADR-0002-correction-engine-boundary.md` — accepted, frozen.
- `docs/decisions/ADR-0003-execution-model-and-frame-ownership.md` — accepted,
  frozen.

`architecture-v1` is the canonical reference and the intended branch point for
future milestone work. `claude/architecture-pass` is retained as the review
branch; PR #6 is the review record and is **not** to be merged into
`milestone-2`.

Future work may extend the architecture only through milestone-specific
Solution Architecture, or through a deliberate architecture amendment / new
ADR when evidence requires one. Do not silently edit the frozen architecture
baseline during implementation work.

## Historical assignments

Superseded assignment text is preserved in Git history rather than in this
file:

| Assignment | Commit |
| --- | --- |
| M2 — Gaze Estimation | `81e06118801c23d2337629fc676d6ad8ac13716a` (this file at frozen M2) |
| Overall Architecture Pass | `8e80dd32ed121590c9e5c99e55f304b1b6cde151` |

## Authority and roles

`01-GazeFix-Product-Requirements-Document-v1.1.md` remains the unchanged
higher-level source of truth for product scope, requirements, constraints, and
milestone gates. This file records the currently authorized engineering work
and nothing beyond it. If a material conflict appears, escalate it instead of
editing the PRD or silently changing scope.

- ChatGPT: Product Manager / Technical Lead; scope, acceptance, and milestone
  decisions.
- Mohammad Iqbal: Product Owner; final product decisions and target-device
  (Windows/webcam) verification.
- Claude Code: implementation engineer and self-review.

`docs/qa-policy.md` is the repository-level QA policy from M2 onward and
governs verification depth, independent review, stopping rules, and Product
Owner interaction.

## Next step

The Product Manager issues the next assignment. Per the PRD roadmap the
expected next step is **Milestone 3 — Offline Gaze Correction Prototype**,
preceded by its own Solution Architecture, derived from the frozen
architecture baseline. Neither is authorized by this file.
