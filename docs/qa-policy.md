# GazeFix QA Policy (M2 onward)

This document is the repository-level source of truth for how GazeFix verifies
work from Milestone 2 onward. It defines the default engineering workflow, when
independent review is worth paying for, and where verification stops.

It does not change the product requirements.
`01-GazeFix-Product-Requirements-Document-v1.1.md` remains the higher-level
source of truth for scope, constraints, milestone gate semantics (PRD §25), and
privacy. Nothing here lowers the PRD's truthful-reporting bar. Where this
document and the PRD appear to conflict, the PRD wins and the conflict is
escalated to the Product Manager rather than resolved locally.

Per-milestone assignments (`Current Assignment.md`) may narrow this policy for a
specific milestone. They must not silently widen it.

## 1. Default engineering workflow

```text
ChatGPT (Product Manager / Tech Lead)
    scope, acceptance criteria, risk classification
        ↓
Claude (primary implementor)
    implementation, self-review, implementation tests, engineering report
        ↓
Automated tests
    primary engineering QA safety net
        ↓
Product Owner
    short Windows / physical-hardware / visual acceptance for behavior that
    cannot be verified reliably in the engineering environment
        ↓
Independent AI reviewer
    optional, risk-triggered, NOT part of the default flow
```

| Role | Owns |
| --- | --- |
| ChatGPT — Product Manager / Tech Lead | Scope, acceptance criteria, risk level, gate decisions, authorizing any QA expansion. |
| Claude — primary implementor | Implementation, self-review, implementation and regression tests, the engineering report, deeper debugging and fixes. |
| Automated tests | The standing safety net. Regression coverage is part of the implementation, not a separate QA phase. |
| Mohammad Iqbal — Product Owner | Short, batched Windows / webcam / visual acceptance for what the engineering environment cannot exercise. |
| Independent AI reviewer (Kimi, Codex, or other) | Targeted review of a named risk, when the PM triggers it. |

**An independent reviewer is not required for every milestone or every
iteration.** Absence of independent review is a normal outcome, not a gap to be
apologized for in a milestone report. Independent review is commissioned by the
Product Manager against a specific risk, using the rules in section 4.

## 2. QA philosophy

GazeFix is a solo/DIY MVP project. QA is a cost centre with a real budget in
dollars, wall-clock time, and Product Owner attention. Verification effort must
be proportional to:

- severity of failure if the change is wrong,
- reversibility of the change,
- architectural impact,
- platform and hardware risk,
- cost of discovering the issue later rather than now.

Prefer **sufficient evidence to proceed safely** over exhaustive proof. The
question is never "has every condition been audited?" but "is there enough
verified evidence that continuing is safe, and are the gaps stated honestly?"

This never licenses overstated verification. The PRD verification levels and
statuses remain mandatory and are used exactly as defined in PRD §25:

```text
Implementation verified     code, automated tests, static checks, isolated behavior
Runtime verified            actually executed in a capable runtime
Physical hardware verified  actually observed on the target physical device
```

```text
VERIFIED
NOT VERIFIED
NOT MEASURED   (unavailable measurement — never inferred, never fabricated)
FAILED
```

Reducing QA scope means doing less verification and saying so. It never means
reporting unverified work as verified. `NOT VERIFIED` is a cheap, honest, fully
acceptable outcome; a fabricated or inflated verification level is not.

## 3. Risk-based QA levels

The Product Manager assigns a risk level with the assignment. The level sets the
default verification depth.

### LOW

Localized implementation, strong existing automated coverage, cheap to fix
later, no architectural or platform risk.

Default: Claude self-review + automated tests.

### MEDIUM

Integration change, meaningful behavior change, moderate regression risk.

Default: Claude self-review + automated tests + PM review, plus a short Product
Owner smoke test where the behavior is user-visible or hardware-dependent.

### HIGH

Any of:

- concurrency or lifecycle changes,
- low-level Windows integration,
- major dependency migration,
- performance-critical architecture,
- privacy- or security-relevant behavior,
- virtual-camera integration,
- significant model or license uncertainty.

Default: everything in MEDIUM, plus targeted runtime verification. A targeted
independent AI review is *possible* here, scoped to the identified risk only —
not to the milestone.

### CRITICAL / RELEASE-SENSITIVE

Use only when genuinely justified — typically an irreversible architectural
decision or a release users depend on. Independent review and stronger
runtime/manual verification may be appropriate.

**Ordinary milestone work is not HIGH by default.** Implementing a planned
milestone deliverable with tests is LOW or MEDIUM unless it touches one of the
HIGH triggers above. Inflating the risk level to feel safer is the failure mode
this policy exists to prevent.

## 4. Independent AI reviewer rules

Independent review is targeted. It answers a specific question that the PM
cannot answer from the engineering report.

Every independent review brief must state:

- the exact commit range or HEAD to review,
- the exact findings, risks, or questions to inspect,
- the affected files or areas,
- explicit stop conditions — what "done" looks like, and what to leave alone.

The reviewer must **not** default to:

- full-repository audit,
- milestone recertification,
- broad hunts for unrelated findings,
- repeated environment rebuilds,
- bespoke temporary QA infrastructure,
- indefinite root-cause research.

A review that returns "the named risk is sound, here is the evidence" in a
short pass is a successful review, not a shallow one.

## 5. Re-review policy

A re-review is **not** a fresh audit.

A re-review should:

- verify only the previous findings and the fixes made for them,
- inspect surrounding code only where the fixes directly affect it,
- run targeted tests for those areas,
- run the full automated suite at most once, if warranted,
- stop once the requested findings are dispositioned.

New findings expand the re-review's scope automatically only when they are:

- BLOCKER or HIGH severity,
- directly caused by the fixes under review,
- or a clear indication of a serious regression.

Unrelated Medium and Low findings are **documented and handed back**, not used
to open a new QA cycle. The Product Manager decides whether they become work.

## 6. Test execution limits

- Run targeted tests first, against the areas actually changed.
- Run the full automated suite **once** before engineering handoff.
- Do not re-run the full suite repeatedly to gather pass/fail statistics unless
  a genuine blocker requires it.
- If an intermittent non-blocking failure has been reproduced enough to describe
  it — the test, the symptom, the conditions, roughly how often — report it and
  stop. Do not chase it to a root cause on QA time.

Engineering reality sometimes requires more runs than planned; this policy sets
no fixed numeric ceiling. It does require the stopping decision to be explicit:
say what was run, what was found, and why the runs stopped where they did.

## 7. Root-cause investigation boundary

| QA reviewer | Primary engineer |
| --- | --- |
| Detect the issue. | Perform deeper debugging. |
| Reproduce enough to establish evidence. | Determine root cause. |
| Classify severity. | Implement and verify the fix. |
| Recommend the next action. | Add regression coverage. |

Independent QA must not silently become the debugging engineer, the
test-infrastructure engineer, or the forensic analyst. That expansion requires
explicit PM / Tech Lead authorization, because it is a different job with a
different cost.

For Medium and Low findings, **root cause may remain unknown**. Enough evidence
to report the issue safely and let the engineer pick it up is a complete result.

## 8. Custom QA tooling

Do not build bespoke QA harnesses or temporary testing frameworks during
independent review by default. Use:

- the existing automated tests,
- the existing diagnostics and developer mode,
- small targeted commands.

Custom test infrastructure is justified only when:

- it has clear reusable value to the project (in which case it belongs in the
  repository, reviewed like any other code), **or**
- a high-risk blocker genuinely cannot be verified any other way.

If a check requires Product Owner interaction and the Product Owner is not
available, mark it `NOT VERIFIED`. Do not build a temporary GUI harness to
automate around the Product Owner — an unverifiable check reported honestly is
cheaper and more truthful than a throwaway harness whose own correctness is
unverified.

## 9. Product Owner interaction budget

Product Owner time is the scarcest resource in this project. Manual verification
must be:

- **explicit** — a written checklist prepared in advance,
- **batched** — one session, not a trickle of requests,
- **short** — each step has a clear action and a clear expected observation,
- **deterministic** — no exploratory "try things and see".

Avoid long standby sessions where the Product Owner waits while an agent decides
whether interaction is needed. Prepare the checklist first, then ask once.

A typical milestone smoke test should aim for roughly **5–10 minutes** where
practical. If substantially longer interaction is genuinely required, the PM /
Tech Lead justifies it before execution rather than discovering it mid-session.

## 10. Cost awareness

QA prompts and plans optimize for **signal per dollar** and **signal per
minute**.

Cheap model pricing does not make a workflow cheap. Long contexts, repeated
full-suite runs, and large raw output dumps multiply into real cost regardless
of per-token price.

Practical rules:

- Do not ingest large context or produce large output when concise filtered
  evidence answers the question.
- Filter and summarize shell and log output (`grep`, `tail`, a summary line)
  instead of pasting large raw outputs into model context repeatedly.
- Quote the specific failing lines, not the whole run.
- Prefer one well-scoped pass over several broad ones.

## 11. Parallel reviewer policy

If two independent reviewers are used simultaneously, they must have
**non-overlapping** responsibilities. Do not ask both for broad full QA — that
buys duplicated cost, not coverage.

Recommended split when dual review is justified:

| Kimi | Codex |
| --- | --- |
| Code correctness | Architecture and integration |
| Algorithm and math semantics | Concurrency and lifecycle |
| Regression-test quality | Pipeline continuity |
| Confidence and unavailable-state logic | Performance and latency risk |
| Documentation consistency | Windows / platform integration |
| | Virtual-camera and system behavior |

The PM / Tech Lead reconciles the findings. Duplicate findings from both
reviewers increase confidence in a real issue. A single Medium or Low finding
from one reviewer does **not** automatically justify another long iteration.

## 12. Escalation triggers

Paid or independent QA **may be** justified for:

- native or thread lifecycle uncertainty,
- repeated unexplained crashes or hangs,
- meaningful performance regression,
- major Windows integration work,
- virtual camera,
- privacy or network behavior,
- major dependency or model migration,
- unclear model or license terms,
- an irreversible architectural decision.

It is usually **not** justified for:

- naming or refactoring,
- small localized logic changes,
- ordinary documentation,
- behavior already well covered by unit tests,
- cheap, reversible implementation details.

## 13. Milestone gate

The PRD §25 gate semantics are unchanged.

```text
PASS
PASS WITH LIMITATIONS
FAIL
```

```text
PROCEED
ITERATE
CHANGE APPROACH
```

`PASS` does **not** mean "every imaginable condition has been exhaustively
audited". It means the required milestone acceptance criteria have sufficient
verified evidence in environments capable of exercising them, with remaining
gaps reported honestly at their correct verification level.

Criteria that could not be runtime- or hardware-verified because of
execution-environment limits produce `PASS WITH LIMITATIONS` — that is the
designed outcome for this project's environment, not a failure of process. A
known-failing or materially incomplete acceptance criterion produces `FAIL`.

The Product Manager makes the gate decision. Frozen milestone branches stay
frozen.

## 14. M1 retrospective

This policy exists because M1's verification process, though it produced useful
evidence, cost more than the project can sustain. This is a process
retrospective; no model or person is at fault.

What happened:

- The re-review scope was effectively exhaustive. A targeted re-review expanded
  into something closer to milestone recertification, and one re-review ran for
  over two hours with very large token volume and long Product Owner standby.
- Repeated full-suite runs were used to characterize an intermittent
  non-blocking failure, with diminishing returns after the first reproductions.
- Multiple temporary bespoke GUI QA harnesses were built and iterated on,
  consuming substantial effort on infrastructure that was never intended to
  survive the review.
- Forensic network verification was genuinely valuable once, as a one-time
  privacy confirmation, but is not warranted as routine per-milestone work.
- No explicit stopping rules existed, so there was no defined point at which a
  finding was "sufficiently established" and the review could end.
- Non-blocking findings were debugged toward root cause inside QA rather than
  being reported and handed to the implementing engineer.

The lessons are encoded above as: targeted briefs with stop conditions
(section 4), re-review that verifies fixes rather than re-auditing (section 5),
one full-suite run before handoff (section 6), a detect-and-report boundary for
QA (section 7), no throwaway harnesses (section 8), and a bounded Product Owner
budget (section 9).
