# Maxine Eye Contact Phase 1A — engineering report

**`RESEARCH/EVALUATION ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

## Engineering status

**`MAXINE EVALUATION PACKAGE READY — NVIDIA CREDENTIAL REQUIRED`**

Reported with one qualification that must not be lost: the NVIDIA credential is
**not** the only missing dependency. Existing Product Owner footage is also
absent from the engineering environment, and every `nvidia.com` host is denied
by this container's egress policy. All three are properties of *where this work
ran*, not of the experiment's design, and all three are resolved on the Product
Owner's own machine, which already holds the footage and a working checkout.

No visual verdict is assigned here. `PASS` / `ITERATE` / `CHANGE APPROACH` are
the Product Owner's to give, after scoring.

## Repository state

| Item | Value |
| --- | --- |
| Branch | `codex/m1-assignment` |
| Base SHA | `95678777642d29912d0806a81f02dc4b11ea884b` (`codex/maxine-phase1a-governance`) |
| Frozen geometric baseline | `f3831b54728a4747c38c064351ec9f48419a2efb` — unchanged |

The working branch was fast-forwarded to the authorized governance checkpoint;
it was a strict ancestor of it, so no history was discarded.

### Files changed

| Path | Change |
| --- | --- |
| `.gitignore` | one comment block ignoring the locally fetched NVIDIA client |
| `docs/milestones/maxine-phase1a-engineering-report.md` | this report |
| `research/maxine-eye-contact/**` | new, self-contained evaluation package |

No product code, no product test, no product dependency manifest, no frozen
document and no frozen reference was modified.

### Frozen references verified unchanged

All eleven references recorded in `Current Assignment.md` were re-resolved and
match: `main`, `milestone-0`, `milestone-1`, `milestone-2`, `architecture-v1`,
`m3-architecture-v1`, `v1.1`, `v1.2`, `v1.3`, `m3-geometric-baseline`,
`model-feasibility-architecture-v1`. No governance contradiction was found, so
the run proceeded rather than stopping.

## NVIDIA API evidence

Full record with hashes and retrieval dates:
`research/maxine-eye-contact/manifests/nvidia-api-spec.json`.

### What could and could not be inspected

Every `nvidia.com` host is refused by this container's organisation egress
policy — `build.nvidia.com`, `docs.nvidia.com`, `developer.nvidia.com`,
`integrate.api.nvidia.com`, `ai.api.nvidia.com`, `api.nvcf.nvidia.com`,
`www.nvidia.com`, all returning a gateway 403 on CONNECT. So
`docs.nvidia.com` and `build.nvidia.com` were **not** read first-hand.

NVIDIA's own published client sources, on NVIDIA's GitHub organisation, *were*
reachable and were read in full. Everything below comes from those files, each
recorded with its SHA-256 and retrieval date (2026-09-07):

- `NVIDIA-Maxine/nim-clients` — root `README.md`, `eye-contact/README.md`,
  `eye-contact/scripts/eye-contact.py`, `eye-contact/scripts/config.py`,
  `eye-contact/scripts/constants.py`, `utils/utils.py`,
  `eye-contact/protos/proto/nvidia/maxine/eyecontact/v1/eyecontact.proto`,
  `eye-contact/requirements.txt`, `eye-contact/protos/linux/compile_protos.sh`.

Nothing in this report is reconstructed from a remembered API schema, and no
endpoint or request format was invented. Where a fact could only be had from an
unreachable page, it is marked `NOT VERIFIED` rather than filled in.

### API and model identity

| Item | Value |
| --- | --- |
| Service | NVIDIA Maxine Eye Contact NIM, hosted NVCF preview ("Try API") |
| Transport | gRPC over TLS |
| Target | `grpc.nvcf.nvidia.com:443` |
| Function id | `15c6f1a0-3843-4cde-b5bc-803a4966fbb6` — **confirm before use** |
| Proto package | `nvidia.maxine.eyecontact.v1` |
| Service / method | `MaxineEyeContactService` / `RedirectGaze`, bidirectional streaming |
| Messages | `RedirectGazeRequest` (`config` or `video_file_data`), `RedirectGazeResponse` (`config`, `video_file_data`, `keepalive`) |
| Chunking | 64 KiB |

Search against `docs.nvidia.com` surfaced a *different* function id
(`7d09dd81-…`), from a page that could not be fetched, and the search summaries
themselves disagreed on whether it was NVIDIA's hosted function or a
self-deployment placeholder. The value used comes from a file that was actually
read, and it is loaded from the spec JSON so it can be corrected without a code
change.

### Authentication

gRPC call metadata, exactly as NVIDIA's `utils/utils.py` constructs it:

```text
("authorization", "Bearer <NGC API key>")
("function-id",   "<NVCF function id>")
```

GazeFix reads the key from the **`NVIDIA_API_KEY`** environment variable. NVIDIA's
client takes it as `--api-key`, which would place a live credential in the
process table and in any captured command string; the wrapper therefore passes
it to the child through its environment and a small launcher supplies the
argument in-process. No credential reaches a command line, a manifest or a log.

### Input requirements

MP4 with H.264; audio optional; **variable frame rate is not supported**.
`--streaming` is required for a faststart MP4 (`moov` before `mdat`) and must be
omitted otherwise. Hosted size and duration limits could not be verified from a
primary source in this environment and are recorded as such.

### Parameters used

**Profile `nvidia-client-defaults`: no behaviour or encoding parameter is sent
at all**, so every applied value is NVIDIA's own default. That is the
"official/default behaviour" the assignment prescribes, and the only setting
that cannot be argued to favour Maxine. `--lossless` is deliberately *not* used:
it would hand Maxine an encoding-quality advantage over the frozen geometric
harness, which writes `mp4v`.

Defaults, ranges and sources for all fifteen behaviour parameters and four
encoding parameters are in the spec JSON. Two discrepancies inside NVIDIA's own
material are recorded there rather than silently resolved: `constants.py` sends
`lookaway_interval_min=3` / `lookaway_interval_range=8` where the proto and
README document `100` / `250` (inert, since lookaway is off by default), and the
proto's head-threshold comments disagree with the client's defaults.

### Trial / evaluation limitations

Use of the hosted evaluation endpoint establishes **no** production
entitlement, redistribution right, commercial deployment right, production
pricing, or accepted privacy architecture. The NVIDIA terms and data-handling
pages could not be reached from this environment, so that boundary is recorded
as `NOT VERIFIED` and must be read and recorded before the first request.

### Hosted availability — the material open risk

**Status: `NOT VERIFIED`.** The evidence is genuinely mixed:

- *For.* NVIDIA's actively maintained client (SPDX headers dated 2025–2026,
  fetched 2026-09-07) still documents "Usage for Preview API request" against
  `grpc.nvcf.nvidia.com:443` with a concrete function id, and points at
  `build.nvidia.com/nvidia/eyecontact/api`. A grep across every fetched NVIDIA
  client source found **no** deprecation, end-of-life, sunset or retirement
  language.
- *Against.* Three independently worded web searches consistently reported the
  `build.nvidia.com` eyecontact model card carrying **"This API will be
  deprecated on 07/27/2026 … will no longer be supported after that date"**.
  That date is roughly six weeks **before** today. The page could not be
  fetched, its exact wording and scope are unconfirmed, and `build.nvidia.com`
  uses that banner generically.

This could not be resolved here. The tooling therefore treats confirming the
endpoint as a **blocking preflight gate** that only a human can clear. If the
hosted API is genuinely retired, the correct status becomes
**`MAXINE FEASIBILITY BLOCKED — HOSTED API UNAVAILABLE`**, and the path stops
there: substituting a self-hosted NIM or another provider is not authorized.

## Frozen evaluation set

**No clip could be frozen, because no Product Owner footage exists in this
environment.**

A forensic search found no video anywhere: not in the working tree, not in any
branch's history, not anywhere on the container's filesystem. This is by design,
not loss — `docs/correction.md` records that "PO imagery belongs only in ignored
local experiment directories", `experiments/` is gitignored, and
`docs/milestones/m3-evaluation.md` states that the M3 captures "remain local and
uncommitted". The footage is on the Product Owner's machine.

| Clip ID | Scenario | Source SHA-256 | Duration | Resolution/FPS | Preprocessing | Geometric available? | Maxine run? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — | — | — |

`NO PRODUCT OWNER FOOTAGE PRESENT IN THIS ENVIRONMENT` — the table is
deliberately empty rather than populated with substitutes. Downloading benchmark
video or generating synthetic subjects is forbidden, and the tooling has no code
path that would do either.

### Scenario coverage, once footage is present

`research/maxine-eye-contact/eval/scenarios.py` maps the eight required
scenarios onto the M3 capture vocabulary that
`scripts/correction_batch.py` already established, so each Phase 1A clip stays
traceable to the M3 capture it came from. Any scenario with no material is
reported as `NOT AVAILABLE IN EXISTING SOURCE MATERIAL`.

**A limitation the Product Manager should see now.** Maxine Eye Contact is a
temporal video model, so a still is not a usable input. Of the eleven M3
captures, eight are stills and only three are clips (`speaking-smiling`,
`minor-rotation`, `blink-wink-squint`). If only the M3 material exists, the
held-out set will be **three clips covering three of eight scenarios** — below
the 6–10 target — and near-normal gaze, horizontal deviation, downward/read-like
gaze and glasses will all report as not available. Recording a few additional
short clips of the same subject in the missing conditions is the legitimate
remedy and is a Product Owner decision, not an engineering one.

## Maxine execution

**Not executed.** No clip was submitted, so there is no per-clip success,
failure, output hash or API metadata to report, and none is invented.

Three independent blockers: no footage, no `NVIDIA_API_KEY`, and no network
route to NVIDIA. The `maxine` command refuses to run while preflight is not
clear.

Request construction, credential handling, streaming-mode selection, turnaround
recording and failure detection are covered by automated tests against a mocked
transport. The remote call itself is `NOT VERIFIED`.

**Timing.** When it runs, turnaround is recorded and labelled
`HOSTED BATCH/API TURNAROUND — NOT REALTIME LATENCY`. Nothing infers
glass-to-glass latency, GPU inference time, concurrency, capacity or cost.

### A defect found in NVIDIA's client, and mitigated

NVIDIA's `eye-contact.py` wraps its whole request in
`except Exception as e: print(...)`, so a failed inference can leave a truncated
or empty output while the process still exits 0. The wrapper therefore treats a
run as successful only when the process exits 0, **and** the output exists and
is non-empty, **and** no `An error occurred:` line appears on stdout or stderr.
A test covers the exit-0-but-failed case.

## Comparison package

Built and runtime-verified end to end, minus the Maxine condition.

| Item | Value |
| --- | --- |
| Labels | `A` / `B` / `C`, neutral, shuffled per clip |
| Randomisation | deterministic from a recorded seed, derived per clip |
| Answer key | `<workspace>/package/answer-key/answer-key.json`, outside the presentation tree |
| Scoring sheet | `<workspace>/package/presentation/scores.csv`; rubric at `research/maxine-eye-contact/scoring/rubric.md` |
| Seed | chosen at run time and recorded; no seed is fixed here because no run occurred |

`ORIGINAL` joins the shuffle so its label is not a constant that would reveal
the other two by elimination. A seed that would place any condition under the
same label in *every* clip is **refused** as a weak blind, and an alternative is
suggested — a real defect the tests caught in a seed of my own choosing. Files
are copied verbatim: no re-encode, no overlay, no watermark, nothing drawn near
the eye region. `audit_presentation` fails the package if any scorer-visible
name or file content contains `GEOMETRIC`, `MAXINE`, `NVIDIA`, `NVCF`,
`BASELINE` or `M3-`.

The presented geometric condition is `corrected.mp4`, the clean corrected video
— verified by hash **not** to be `side_by_side.mp4` or `debug.mp4`, both of
which carry burned-in text or drawn overlays.

No method label appears anywhere in the Product Owner-facing package.

## Tests

| Suite | Command | Result |
| --- | --- | --- |
| Evaluation tooling | `python -m pytest research/maxine-eye-contact/tests -q` | **190 passed** |
| Product regression | `QT_QPA_PLATFORM=offscreen python -m pytest tests -q` | **786 passed, 15 skipped, 0 failed** |
| Static check | `python -m pyflakes research/maxine-eye-contact/` | clean |

The product suite is unaffected. Its 15 skips are the opt-in real-model tests.
Running it required installing `numpy`, `opencv-contrib-python`, `mediapipe`,
`PySide6` and Qt system libraries into this container; `pyproject.toml` was not
modified.

### Runtime verification of the tooling

Recorded in `research/maxine-eye-contact/manifests/tooling-verification.json`.
Every step except the remote call was exercised for real, using a synthetic clip
built from the repository's licensed `tests/assets/astronaut_face.png` fixture —
the same fixture `scripts/correction_batch.py fixture` uses. That clip is
engineering scaffolding, never evaluation material, and it establishes nothing
about visual quality.

- `plan`, `freeze` (with `--strict-probe` and real `ffprobe` measurement),
  `prepare` (real `ffmpeg`), `package`, `verify`: **VERIFIED**.
- `geometric`: **VERIFIED** — the frozen M3 harness ran through this tooling,
  exit 0, 90 frames decoded, 0 engine failures, at the frozen settings
  (`--strength .7`, variant `layered`), and its `report.json` recorded a source
  SHA-256 identical to the derived manifest's, so the hash chain is intact.
- `maxine`: **NOT VERIFIED**.

**Reproducibility, measured.** Both deterministic stages were run twice on
identical input and produced byte-identical output: the derived input
(`ffmpeg`, frozen profile) and the geometric `corrected.mp4` and its first
frame. So the SHA-256 recorded for a derived input or a geometric output is a
real audit token, not merely a record of one particular file. The offline
correction path contains no RNG, no threading, and derives frame timestamps
from the frame index rather than the wall clock, so pixel output is
deterministic by construction; container bytes additionally depend on the local
encoder build, so a different platform should re-measure rather than assume.
Report timings are wall-clock dependent and are metadata only.

### Integrity and secret scanning

`run.py verify` passed all four checks on the runtime-verified workspace: frozen
sources unchanged, frozen references unchanged, no method leak in the blind
package, and no credential-shaped content in any artifact or in the committed
package. The scanner exempts only lines carrying an explicit, greppable
allowlist marker, and a test proves the exemption is per line.

### Three defects the tests caught, and fixed

1. A fractional score such as `2.5` was silently truncated to `2`, misstating
   what the Product Owner wrote. Now rejected.
2. `package.json` and `answer-key.json` were written *without* the digest field
   their in-memory counterparts carried, so a reader could not check them.
3. `ffprobe` embeds an ASLR memory address in its error text, which made a
   manifest's SHA-256 differ between two freezes of the same input — destroying
   the freeze token's whole purpose. Diagnostics are now normalised.

## Scope audit

Confirmed, explicitly:

- **No product runtime integration.** Nothing imports `gazefix`; nothing in
  `gazefix` imports this. No `CorrectionEngine`, no cloud correction provider.
- **No realtime streaming.** No live-webcam path, no pipeline or staged-processor
  change, no `ProcessedFrame` / `ProcessorOutput` change, no correction metrics
  in `PipelineMetrics`.
- **No self-hosted NIM deployment.** No container pulled, no GPU provisioned.
- **No virtual camera.**
- **No M4.** No milestone transition claimed or implied.
- **No training or fine-tuning.** No synthetic training data.
- **No vendor outreach.** No contact with NVIDIA or anyone else.
- **No LivePortrait** in any role.
- **No model substitution.** No alternative model, no fallback, no other
  gaze-correction service. The only service named is NVIDIA Maxine Eye Contact.
- **No frozen-ref modifications.** All eleven verified unchanged; the frozen
  geometric baseline is invoked, never edited, and the runner refuses every
  argument that would retune it.
- **No product dependency change.** `pyproject.toml` untouched; the package is
  standard library only.

## What the Product Manager needs to decide

1. **Confirm the hosted endpoint is alive** before footage is spent on it. This
   is the one blocking unknown, and it is a five-minute check by someone who can
   reach `build.nvidia.com`.
2. **Provide the NVIDIA credential** in the shell that runs the `maxine` step —
   never in a repository file.
3. **Decide the footage question.** The three existing M3 clips cover three of
   eight scenarios. Either accept a three-clip gate with that limitation stated
   in the record, or have the Product Owner record a few more short clips in the
   missing conditions.
4. **Accept the privacy step explicitly.** Running this uploads Product Owner
   footage to a third-party hosted service. That is authorized for this bounded
   experiment and would not be acceptable in production.

Nothing beyond Phase 1A follows from this report, and a Phase 1A `PASS` would
still authorize nothing on its own.
