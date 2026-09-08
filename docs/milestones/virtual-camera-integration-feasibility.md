# Windows virtual-camera / conferencing integration feasibility

**Status: `PARALLEL VIRTUAL-CAMERA FEASIBILITY RESEARCH AUTHORIZED`**

**PM authorization recorded: 2026-09-08. Desk research only.**

**Research outcome: not yet assessed.** This document defines the assignment;
it does not contain completed research or claim technical compatibility.

## Governance context and Phase 1A verdict provenance

**`MAXINE PHASE 1A VISUAL GATE: PASS`**

This is the Product Owner's verdict as supplied by the Product Manager in
the 2026-09-08 assignment, "GazeFix — Authorize Parallel Virtual-Camera
Integration Feasibility Research". The inspected base,
`origin/codex/m1-assignment @ 32836f9df8a222f3847306ca42b2e388e461cd83`,
does not yet record that visual PASS. This new governance record therefore
records the supplied decision; it does not independently reproduce the
evaluation or invent experimental details, clip coverage, measurements,
scores, or output hashes. Existing Phase 1A evidence, including
`docs/milestones/maxine-phase1a-engineering-report.md` and
`research/maxine-eye-contact/`, remains unchanged and describes its original
verification state.

The PASS means only that NVIDIA Maxine Eye Contact has demonstrated
sufficient visual feasibility to justify further bounded investigation.
It does not authorize production integration, M4, cloud architecture,
virtual-camera implementation, product adoption of Maxine, PRD changes,
commercial acceptance, or realtime acceptance. Maxine Phase 1B
realtime/streaming feasibility will require a separate future PM
authorization and gate. Neither Phase 1B research nor implementation begins
under this assignment.

The original PRD remains authoritative and unchanged. The primary roadmap
remains paused at the M3 -> M4 boundary after M3's geometric visual gate
result of `CHANGE APPROACH` — not PASS. **M4 remains BLOCKED.** Candidate
Admission remains closed and LivePortrait remains rejected. Frozen
architecture, milestone references, and evaluation evidence retain their
existing status.

## Bounded research question and why it precedes M8

> Can GazeFix eventually expose a production-quality Windows camera source
> that Zoom, Google Meet, and Microsoft Teams can consume as a normal webcam,
> under the supported Windows product scope?

The current PRD scope is Windows 10/11. Research must evaluate both explicitly
without silently narrowing support. This track is independent of correction
technology and must not assume Maxine becomes the product backend.

The PM is pulling forward one parallel desk-research track to retire
downstream delivery risk early: a virtual-camera delivery blocker could make
the product infeasible or materially affect supported-OS strategy regardless
of correction quality. This is not a roadmap replacement, an M8 start, or a
production design decision.

## Authorized scope

Only desk research into the following is authorized:

- Windows virtual-camera mechanisms, Windows 10 versus Windows 11 support,
  Media Foundation, and relevant Microsoft camera APIs.
- Installation and registration models, user-mode versus driver implications,
  code signing, installer/distribution implications, and permissions.
- Camera device enumeration and resolution, frame-rate, and pixel-format
  compatibility.
- Compatibility with Zoom, Google Meet, and Microsoft Teams as normal webcam
  consumers, distinguishing documented client/browser/platform versions.
- Camera switching during calls, failure/disconnect behavior relevant to a
  future virtual camera, and multi-consumer implications where material.
- Product risks and blockers, and an evidence-backed recommendation for a
  future implementation path, including explicit constraints and unresolved
  questions for PM decision.

Reading API documentation or published sample descriptions is permitted;
building, running, installing, registering, or integrating a sample is not.
Any condition that needs a technical spike must be reported as such and
await a later PM assignment.

## Prohibited scope

This authorization does not permit:

- Any virtual-camera code, Windows driver code, or technical spike, including
  an `MFCreateVirtualCamera` proof-of-concept.
- OBS integration or external virtual-camera SDK integration.
- Zoom plugin development, Teams app development, Chrome extension work,
  or Meet-specific code.
- Maxine integration, webcam-to-cloud-to-virtual-camera pipelines, realtime
  correction code, or Phase 1B research or implementation.
- Product code, M4 or M8 implementation, installer changes, or adding/changing
  product dependencies.
- PRD edits, architecture edits, ADR creation, or modification of frozen
  architecture or frozen milestone/reference state.
- Modification of Maxine Phase 1A or any existing evaluation evidence.
- Commercial vendor outreach, training, fine-tuning, or LivePortrait in any
  role. No model search, backend selection, or candidate substitution follows
  from this research authorization.
- Merging any PR.

## Evidence standard and research deliverable

Require primary sources wherever available: Microsoft documentation for
Windows, Media Foundation, camera APIs, registration, permissions, and
signing; Zoom documentation for Zoom; Google documentation for Meet and
relevant browser behavior; Microsoft Teams documentation for Teams.

The subsequent research report must:

1. Map each load-bearing claim to a direct source URL, document title,
   relevant section, access date, and applicable OS/build/client/browser
   version or other documented limit. Distinguish documented support,
   researcher inference, conflicting evidence, and missing evidence.
2. Compare Windows 10 and Windows 11 routes explicitly, including API
   availability versus OS lifecycle/support limitations. Map each route to
   install/registration, signing/distribution, permissions, enumeration,
   media formats, and consumer constraints.
3. Cover Zoom, Meet, and Teams separately. Generic webcam selection support
   alone is not proof that a particular virtual-camera route works in that
   client. Do not generalize from one client, browser, OS version, format, or
   camera mechanism to all supported configurations.
4. Record in-call switching, failure/disconnect and materially relevant
   multi-consumer behavior at the actual evidence level. Identify remaining
   runtime/hardware checks without performing them. Apply `docs/qa-policy.md`
   truthful reporting: runtime and physical-hardware behavior remain
   `NOT VERIFIED` without applicable execution evidence; unavailable
   measurements remain `NOT MEASURED`.
5. Use secondary sources only as clearly labeled supporting evidence or
   leads when primary sources are unavailable or incomplete. Record that
   limitation; absence of documentation is not proof of compatibility.
6. Provide a concise evidence matrix, material risks/blockers and conditions,
   unresolved questions, a future-path recommendation, and one proposed
   research outcome from the definitions below for PM review. A recommendation
   does not select an architecture, change OS scope, or authorize integration.

Stop after a bounded documentary assessment. Do not resolve evidence gaps
by coding, installing software, testing calls, contacting vendors, or
starting another research track. If an unanswered question is load-bearing,
return `UNKNOWN` or state the material condition supported by evidence;
do not convert uncertainty into a claim of support.

## Research decision outcomes

These are research outcomes only, not PRD milestone gate statuses.

| Outcome | Definition |
| --- | --- |
| `PASS` | The core Windows virtual-camera delivery path is well-supported for the intended product scope, with no known blocker preventing Zoom/Meet/Teams use. |
| `CONDITIONAL PASS` | A viable route exists, but a material condition must be decided later, such as Windows 11-only support, signing/distribution complexity, or another explicit constraint. |
| `FAIL` | A load-bearing blocker makes the intended integration path infeasible or incompatible with the required product scope. |
| `UNKNOWN` | Insufficient evidence. Do not convert UNKNOWN into PASS. |

A `PASS` requires evidence addressing the intended Windows scope and all
three clients; it is still only a documentary feasibility conclusion, not
runtime or production acceptance. A Windows 11-only viable route cannot be
an unconditional PASS against the unchanged Windows 10/11 scope. For
`CONDITIONAL PASS`, identify the viable route, the exact condition, its
impact, and the later PM decision required; it cannot conceal an unsupported
load-bearing assumption. For `FAIL`, identify the blocker and affected
requirement. For `UNKNOWN`, identify the missing evidence and whether a
separately authorized spike would be needed to resolve it.

## Relationship to M8 and the Product Strategy Gate

M8 remains a future implementation milestone under the unchanged PRD. Its
existing technical acceptance requires verified output in at least one
supported conferencing client; full MVP acceptance requires compatibility
verification with Zoom, Meet, and Teams. This early research asks about all
three to expose downstream risks, without changing either acceptance bar.

No automatic transition follows **any** research outcome, including `PASS`
or `CONDITIONAL PASS`. The PM must separately authorize any later technical
spike. Research does not unblock M4, begin M8, approve production use,
authorize a dependency, change the supported OS scope, or adopt Maxine.

Maxine Phase 1B remains a separately authorized future feasibility gate.
After Phase 1B, an explicit **Product Strategy Gate** must still occur before
any PRD revision or resumed milestone implementation. Its PM decision must
consider the feasibility findings and unresolved conditions; neither this
research nor Phase 1A PASS substitutes for that decision. The original
roadmap remains paused until explicit subsequent authority is given.

## Governance delivery and frozen references

This authorization is delivered on
`codex/virtual-camera-feasibility-governance`, based on
`origin/codex/m1-assignment @ 32836f9df8a222f3847306ca42b2e388e461cd83`.
That lineage includes `codex/maxine-phase1a-governance` at
`95678777642d29912d0806a81f02dc4b11ea884b` and the subsequent Phase 1A evidence
commits. This task is not based on `main`; the governance history is preserved.

Remote state was fetched before editing. All eleven frozen remote references
listed in `Current Assignment.md` were verified against their recorded SHAs
before this change. They must also be verified at completion; none may be
advanced, rewritten, force-pushed, or merged into. The retired
`model-feasibility-architecture-v1` remains historical evidence only.

This governance delivery changes only `Current Assignment.md` and this
document. It records authorization and the supplied Phase 1A verdict, and
does not execute the newly authorized desk research.
