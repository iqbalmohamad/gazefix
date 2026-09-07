# Phase 1A protocol — NVIDIA Maxine Eye Contact visual feasibility

**`RESEARCH/EVALUATION ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

This is the frozen experimental design for the bounded research spike
authorized in `Current Assignment.md` and
`docs/milestones/candidate-admission-closure.md`. It exists so the experiment
is reproducible and so that nobody — including the engineer who runs it — can
tilt the result after seeing an output.

The single question is:

> Does NVIDIA Maxine Eye Contact produce eye-contact correction that is
> materially more natural than GazeFix's frozen geometric baseline, and good
> enough for the Product Owner to want to use in a real video call?

The Product Owner answers it. This document never does.

## 0. Ordering is the point

The steps below run in order and each refuses to run out of order. The value of
the experiment comes almost entirely from two facts:

1. the held-out set is frozen **before** the first Maxine inference, and
2. the Maxine configuration is frozen **before** any held-out output is seen.

Everything else is bookkeeping in service of those two.

| Step | Command | Produces |
| --- | --- | --- |
| 0 | `preflight` | `preflight.json` — every precondition, at its true status |
| 1 | `plan` | `source-plan.json` — editable clip plan |
| 2 | `freeze` | `source-manifest.json` — **the frozen held-out set** |
| 3 | `prepare` | `derived/` + `derived-manifest.json` — one shared input per clip |
| 4 | `geometric` | `geometric/` + `geometric-manifest.json` |
| 5 | `maxine` | `maxine/` + `maxine-manifest.json` |
| 6 | `package` | `package/presentation/` and the separate `package/answer-key/` |
| 7 | `verify` | `integrity.json` — integrity and secret scan |

Steps 4 and 5 may run in either order; both consume the same derived input.

## 1. Source material

The experiment uses **existing Product Owner footage only**. Benchmark video
downloaded from the internet and synthetic subjects are both forbidden: this is
a judgement about whether the Product Owner would use the result on their own
face, so it has to be their face.

Footage lives in the ignored `experiments/inputs/` directory, which is where the
frozen M3 batch driver (`scripts/correction_batch.py`) already expects it, under
the same capture stems. Reusing that vocabulary keeps every Phase 1A clip
traceable to the M3 capture it came from.

`eval/scenarios.py` maps the assignment's eight required scenarios onto those
stems:

| Required scenario | M3 capture stems |
| --- | --- |
| near-normal gaze | `lens-no-glasses`, `lens-glasses` |
| horizontal gaze deviation | `horizontal-no-glasses`, `horizontal-glasses` |
| downward / read-like gaze | `screen-*`, `notes-*` |
| natural speaking | `speaking-smiling` |
| blink | `blink-wink-squint` |
| small head movement | `minor-rotation` |
| glasses | `*-glasses` |
| no-glasses | `*-no-glasses` |

A scenario with no source material is recorded as
`NOT AVAILABLE IN EXISTING SOURCE MATERIAL`. It is never back-filled with
unrelated footage, and the tooling has no code path that would let it be.

**A structural limitation to be explicit about.** Maxine Eye Contact is a
temporal video model, so a still is not a usable input for it. Of the eleven M3
captures, eight are stills and only three are clips (`speaking-smiling`,
`minor-rotation`, `blink-wink-squint`). If the only available footage is the M3
set, the held-out set is three clips covering three of the eight scenarios, well
below the 6–10 clip target, and the still-only scenarios will be reported as not
available. That is a real and reportable limitation of the evidence, not a
reason to manufacture footage. Recording a handful of additional short clips of
the same subject in the missing conditions is the legitimate remedy, and it is a
Product Owner decision, not an engineering one.

Target: roughly **6–10 clips**, **5–15 seconds** each. Deliberately bounded.

## 2. Freezing the held-out set (mandatory, before any inference)

`freeze` records, per clip: immutable clip id, source path and name, source
SHA-256, byte size, probed duration / resolution / FPS / codec / container,
scenario tags, the clip's role in the recorded M3 evaluation, any deterministic
trim window, and the preprocessing to be applied. The manifest carries its own
SHA-256 as a freeze token.

After the freeze:

- **no clip may be added**, and
- **no clip may be removed.**

A clip that turns out to be technically invalid stays in the manifest with an
explicit exclusion reason (`eval.sourceset.exclude`). It is not run and not
presented, but it remains visible in the record. Dropping a clip because its
output looked bad is exactly the cherry-picking this step exists to prevent, and
`eval.sourceset.diff_membership` makes any post-hoc change detectable.

`freeze` refuses to overwrite an existing manifest without `--force`.

If `ffprobe` is unavailable the media fields record `NOT MEASURED` rather than a
guess, per `docs/qa-policy.md`.

## 3. Preprocessing (minimal, deterministic, symmetric)

Each clip is prepared **once**, and the single derived file is the input to
**both** conditions. This is the guarantee that neither method was handed a
more favourable source.

Permitted, and all that the tooling can do:

- deterministic trim to the recorded window,
- remux/transcode to MP4 / H.264 / `yuv420p` / constant frame rate,
- drop audio,
- relocate the `moov` atom to the front (`+faststart`).

These follow NVIDIA's stated input requirements: MP4 with H.264, audio optional,
variable frame rate not supported. `+faststart` is applied to every clip so all
clips share one streamability state and therefore one frozen client invocation
mode, rather than the mode varying per clip.

Forbidden, and absent from the command: sharpening, denoising, beautification,
retouching, colour changes, per-subject cropping, any gaze alteration, and any
per-clip variation. `eval/preprocess.py` builds one constant argument list; a
test asserts no filter flag can appear in it.

Both source and derived SHA-256, and the exact command, are recorded.

Both this step and the geometric step were measured to be byte-reproducible:
running each twice on identical input produced identical output hashes
(`manifests/tooling-verification.json`). The offline correction path contains
no RNG, no threading, and derives frame timestamps from the frame index rather
than the wall clock, so its pixel output is deterministic by construction.
Container bytes additionally depend on the local encoder build, so a different
platform should re-measure rather than assume.

## 4. Frozen Maxine configuration (before any held-out output is seen)

**Profile `nvidia-client-defaults`.** NVIDIA's own published Eye Contact client
is invoked with **no behaviour and no encoding parameter at all**, so every
applied value is NVIDIA's own default.

This is the choice the assignment's "use official/default behaviour" rule
prescribes, and it is the only configuration that cannot be argued to have been
tuned in Maxine's favour. Notably `--lossless` is *not* used: it would give
Maxine an encoding-quality advantage over the frozen geometric harness, which
writes `mp4v`.

Every default value, with its documented range and its primary source, is
recorded in `manifests/nvidia-api-spec.json`. Parameters are **not** tuned per
clip. If a future authorization introduces calibration, it must run on a
separately identified calibration clip and be frozen before any held-out output
is inspected.

GazeFix wraps NVIDIA's client rather than reimplementing the gRPC protocol. The
assignment forbids relying on a remembered API schema or inventing a request
format; wrapping the vendor's own client means the request sent is by
construction the request NVIDIA defines.

## 5. Remote execution

Each frozen clip is submitted **exactly once** under the frozen configuration.

- A clip is re-run only for a genuine technical failure, and the failure and the
  retry are both logged. Parameters never change between attempts.
- Re-running a clip hoping for a nicer stochastic result is forbidden. `maxine`
  refuses to overwrite an existing output without `--force`.
- Ugly outputs are kept. Every output, every error, every timestamp and every
  output SHA-256 is recorded.
- If the service turns out to be nondeterministic in a way that requires
  repeated sampling to understand, **stop and escalate** rather than quietly
  picking the best output.

**Timing.** Turnaround is recorded and labelled
`HOSTED BATCH/API TURNAROUND — NOT REALTIME LATENCY`. It must not be read as
glass-to-glass latency, GPU inference time, concurrency, capacity or cost. Those
belong to a later stage that only exists if the visual gate passes.

## 6. Geometric baseline comparison

The comparison uses the frozen M3 implementation at
`m3-geometric-baseline @ f3831b54728a4747c38c064351ec9f48419a2efb`, unmodified.

Frozen settings are those the M3 `po` batch used for clips, restated as data in
`eval/geometric.py`: `--strength .7 --debug --max-frames 1200`, with harness
defaults variant C (`layered`), optical-axis target (yaw 0 / pitch 0), no
stabiliser, no gaze smoothing. `eval/geometric.py` **refuses** any argument that
would retune the baseline; a test covers every such flag.

The presented output is `corrected.mp4`, the clean corrected video.
`side_by_side.mp4` carries burned-in "Original | Corrected" text and `debug.mp4`
carries drawn overlays, so neither may ever be presented.

Reusing existing canonical geometric output is valid only when its
`report.json` records a source SHA-256 identical to the frozen manifest's
(`eval.geometric.baseline_matches_source`). Otherwise it is regenerated from the
same derived input. M3 is not patched for this experiment.

## 7. Blind comparison package

Three conditions per clip where available: `ORIGINAL`, `GEOMETRIC`, `MAXINE`,
presented under neutral labels `A` / `B` / `C`.

- Assignment is deterministic from a **recorded seed**, derived per clip so
  that excluding a clip cannot silently re-roll the others.
- `ORIGINAL` joins the shuffle, so its label is not a constant that would give
  the other two away by elimination.
- A seed that places any condition under the same label in **every** clip is
  **refused** as a weak blind, and an alternative seed is suggested. Choosing
  the seed happens before any output is scored, so re-rolling on that signal
  biases nothing.
- Files are copied verbatim. No re-encode, no overlay, no watermark, and
  nothing whatsoever drawn near the eye region.
- The answer key is written to a **separate directory**, outside the
  presentation tree, marked "do not open before scoring".
- `eval.package.audit_presentation` fails the package if any scorer-visible
  filename or file content contains `GEOMETRIC`, `MAXINE`, `NVIDIA`, `NVCF`,
  `BASELINE` or `M3-`. The subject of the gate is deliberately not a secret; the
  rubric legitimately contains a `perceived_eye_contact` column.

A clip missing a condition is presented with the conditions it has, and the
omission is recorded in the answer key rather than hidden.

## 8. Scoring

`scoring/rubric.md` holds the Product Owner's sheet. Nine dimensions scored 1–5,
plus the two closing questions, plus free-text notes. The wording matches the M3
gate record where the two overlap so Phase 1A scores are directly comparable
with the scores the geometric baseline already received.

The implementing engineer does **not** assign the Product Owner's visual
verdict. `eval/rubric.py` deliberately contains no function that decides one.

## 9. Verdict

The Product Owner returns exactly one of `PASS`, `ITERATE` or
`CHANGE APPROACH`, as defined in the assignment.

A `PASS` authorizes nothing by itself. It lets the Product Manager *consider* a
future realtime/cloud feasibility stage. It is not Candidate Admission, not
production integration authority, and not M4 authority.

A `CHANGE APPROACH` stops the Maxine cloud path. No realtime latency work, no
cloud hosting, no NIM deployment, no cost optimization follows it.

## 10. Trial and commercial boundary

Use of NVIDIA's hosted evaluation endpoint under its current terms establishes
**no** production entitlement, **no** redistribution right, **no** commercial
GazeFix deployment right, **no** production pricing and **no** accepted privacy
architecture. Every Maxine output is marked
`RESEARCH/EVALUATION ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION` and none is
shipped as product functionality.

Submitting Product Owner footage to a third-party hosted service is a real
privacy step that the PRD's production constraints would not permit. It is
authorized here only as a bounded research exception, for this experiment, on
existing evaluation footage.

## 11. What this protocol does not do

No product runtime integration. No Maxine `CorrectionEngine`. No cloud
correction provider. No realtime streaming. No virtual camera. No M4. No
self-hosted NIM deployment. No GPU provisioning. No training or fine-tuning. No
alternative model, substitution or fallback. No vendor outreach. No LivePortrait
in any role. No modification of frozen behaviour, frozen architecture or any
frozen reference.
