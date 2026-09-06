# M3 post-QA hardening — SA v1.3

**M3 QA HARDENING COMPLETE — READY FOR TARGETED RE-REVIEW**

No M3 PASS is claimed. This work stops before the PO visual gate and adds no
M4 work. QA-M3-006 remains informational; no product change was made for it.

## Repository and scope

- Branch: `codex/m3-gaze-correction`.
- Reviewed implementation preserved: `dc7817715e703d82a8b178bffc41486a383a8372`.
- Frozen SA: `m3-architecture-v1.3 @ d91d393eb6e3e5f93ee2122bc840f776a55872e5`.
- `91a69a5`: first administrative change updates `Current Assignment.md` to
  v1.3 and records v1.2 as superseded for implementation, immutable history.
- `4c40794`: merges the exact canonical v1.3 SA without editing its content.
- Tested hardening commit: `b48c8ccbeb5e1e9edfc6d654c5ab99596ab20ae2`.
- The subsequent report/evidence commit changes no runtime code or tests;
  the final SHA is supplied in the handoff message.

Only harness tracking-error accounting and its SA provenance string changed
at runtime. Correction algorithm, geometry, masks, settings, policy, contracts,
ownership/fallback behavior and dependencies are unchanged. A3.1/A3.2's
currently shipped tolerances remain untouched in `test_correction_warp.py`.

## Confirmed findings closed

| Finding | Change and behavioral evidence |
| --- | --- |
| QA-M3-002 | The two 20° head / 10° target closed-loop rows use ±0.25°, with frontal rows retaining their prior bound. Each negative control changes only the effective Rᵀ operation to R and proves the same closed-loop assertion fails. No production geometry fix was needed. |
| QA-M3-003 | The real engine's yaw-60 output must report `clamped=True` and displacement magnitude exactly half the measured eye half-width. An independent reference derives displacement from raw contour corners, gaze direction, target angles and strength, without correction geometry or reported displacement. A non-clamped, initially right/down-looking scene must move its rendered iris left/up toward the lens; centroid direction comes from target-versus-gaze semantics. |
| QA-M3-004 | Actual engine output equals the translated source iris on a nonempty opaque-iris/partial-lid-alpha intersection for both eyes. Installing the superseded pre-A1 blend in memory makes those same output witnesses fail. The engine skin tracer now runs for both default linear and cubic interpolation, in B and C. |
| QA-M3-005 | A real engine call with chamfer3 and guard 2.5 matches an independently recomputed chamfer field and blend pixel-for-pixel. A precise-distance control produces different pixels, so ignoring the setting fails. Four-tap safety, zero skin leakage, unchanged outside-opening pixels and source ownership are asserted. No chamfer product behavior changed. |
| QA-M3-007 | Tracking-error accounting moves outside the sweep loop. One analyzed error frame counts once for both one and six experiment combinations, while all records and exit 1 remain. A separate regression keeps engine faults counted per experiment. |

Negative controls are scoped in-memory monkeypatches inside tests; they do not
modify production source files or leave a mutated engine installed.

## Verification obtained

| Check | Result |
| --- | --- |
| Targeted confirmed-findings run | **VERIFIED — 20 passed**, 6.36 s |
| Full focused M3 suite | **VERIFIED — 124 passed**, 22.66 s |
| Full repository regression | **VERIFIED — 786 passed, 15 skipped**, 73.72 s; one full run |
| Real-model M3 test | **VERIFIED — 1 passed**, 4.31 s; run separately after regression |
| Static/import checks | **VERIFIED** — compileall, existing AST boundary test and git diff whitespace check |
| Deterministic correction pixels | **VERIFIED — 96/96 identical**, including input/output SHA-256, status, reason, per-eye displacement and clamp metadata |
| Frozen refs and documents | **VERIFIED — all nine canonical remote refs match**, and frozen SA/PRD/architecture/ADRs/QA content is unchanged |

The 15 regression skips are the opt-in real-model tests; the M3 one was then
explicitly enabled and passed. The other 14 existing real-tracking opt-in
tests were not rerun. The M3 real-model run emitted two upstream protobuf
deprecation warnings. No functional failures or new warnings occurred in the
focused or full regression run.

Targeted command, using `.venv-m1-qa-r2/Scripts/python.exe -m pytest`:

```text
tests/test_correction_geometry.py
tests/test_correction_postqa.py
tests/test_correction_safety.py::test_interpolation_keeps_lid_skin_out
tests/test_correction_harness.py::test_tracking_error_count_is_per_frame
tests/test_correction_harness.py::test_engine_error_count_stays_per_experiment
-q
```

The full focused suite includes all `tests/test_correction_*.py` and
`tests/test_geometric_engine.py`. Full regression uses `python -m pytest -q`;
real-model verification uses `GAZEFIX_REAL_MODEL_TESTS=1` and
`tests/test_real_model_correction.py`. JUnit artifacts are in the ignored local
`experiments/m3-v13/{focused,regression,real-model}.xml`, using legacy JUnit
format to retain existing test properties without xunit2 warnings.

## Pixel and frozen-reference evidence

[Verification snapshot](m3-v13-qa-evidence.json) records the two matching
manifest hashes, tested implementation SHA, matrix and all nine frozen SHAs.
The saved pixel manifests are `experiments/m3-v13/pixels-before.json` and
`pixels-after.json`. The before run preceded test/harness changes; only the
assignment and frozen SA had been adopted, with correction sources still
byte-identical to the reviewed implementation.

The matrix is the Cartesian product of two anatomical fixtures, B/C, precise
guard 1.5/chamfer3 guard 2.5, yaw/pitch targets `(10,0)`, `(60,0)`, `(0,15)`,
`(10,10)`, and effective strengths `0`, `.75`, `1`: 96 cases. Each renders
`correction_scene` with `render_eyes`, calls the real engine, hashes complete
input/output bytes and compares non-timing metadata. This is unchanged-output
evidence for those deterministic inputs, not a new visual-quality verdict.

All correction library files and both fixture/centroid-tolerance files named
in the snapshot are byte-identical to the reviewed implementation. Frozen
SA v1.3 and the reviewed implementation are preserved as ancestors. Existing
untracked QA virtual environments remain untouched.

## Changed files against the reviewed implementation

- `Current Assignment.md`
- `docs/correction.md`
- `docs/milestones/m3-solution-architecture.md` — adopted unchanged from the frozen v1.3 branch
- `docs/milestones/m3-v13-qa-hardening-report.md`
- `docs/milestones/m3-v13-qa-evidence.json`
- `gazefix/correction/harness.py`
- `tests/test_correction_geometry.py`
- `tests/test_correction_harness.py`
- `tests/test_correction_postqa.py`
- `tests/test_correction_safety.py`

## Stop condition

The five confirmed findings are closed with targeted behavioral evidence.
Ready for targeted re-review of those findings only. No algorithm redesign,
PO capture/scoring session, automatic milestone PASS, or M4 transition occurred.
