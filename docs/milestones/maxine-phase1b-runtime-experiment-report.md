# Maxine Eye Contact Phase 1B — runtime experiment engineering report

**`RESEARCH/EXPERIMENT ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

## Status

**`PHASE 1B RUNTIME EXPERIMENT — INCONCLUSIVE`**

Not a fail. No kill condition was observed, and none could be: the experiment
stopped at the first precondition the engineering environment cannot supply — a
running NVIDIA Maxine Eye Contact NIM. The harness that closes the six unknowns
is complete, its own correctness is measured, and every result it would produce
is one provisioning step away.

Reported honestly rather than favourably: this environment has no NVIDIA GPU, no
route to any NVIDIA host, and no NGC credential. Stage A was **not executed**.
Stages B and C were consequently not executed either.

**Engineering status: `PHASE 1B HARNESS READY — SELF-HOSTED NIM REQUIRED`.**

The Product Manager issues the Phase 1B gate verdict; no verdict is claimed here.

## Governance state verified before any change

| Item | Verified |
| --- | --- |
| Canonical program state | `program-state-v1` @ `22e8dc1490acd38bebc4f19360a7035b91b7e900` — resolved on the remote and read |
| Frozen geometric baseline | `m3-geometric-baseline` @ `f3831b54728a4747c38c064351ec9f48419a2efb` — resolved on the remote |
| All twelve canonical references | re-resolved against the remote immediately before committing; **all twelve match**, none advanced, rewritten or merged into |
| PRD | read, unchanged |
| Phase 1A record and package | read, unchanged, byte-identical to `program-state-v1` |

One discrepancy is recorded rather than repaired: `main`
(`b40d74faef55811d67de258660b6040c7c8dc790`) contains only Milestone 0. The
program's real state lives on `program-state-v1`, exactly as
`docs/milestones/program-state-2026-09-08.md` says. The working branch was
therefore based on `program-state-v1`, not on `main` — see **Repository
changes**.

No Phase 1B desk-research document exists anywhere in the repository or on any
branch. The desk research described in the assignment is external to it. Its
central finding — that `RedirectGaze` is a bidirectional streaming RPC — was
re-established here first-hand rather than taken on trust.

## Environment

### Client (this engineering environment)

| Item | Value |
| --- | --- |
| OS | Linux 6.18.44 (Ubuntu 24.04.4), container |
| CPU | Intel Xeon @ 2.80 GHz, 4 cores, 15 GiB RAM |
| Local NVIDIA GPU | **none** — `nvidia-smi` absent, no `/dev/nvidia*` |
| CUDA | not present, and not required by anything in the harness |
| Python | 3.11.15 |
| grpcio | 1.83.1 |
| PyAV | 18.1.0 (optional low-latency muxer only) |
| ffmpeg / ffprobe | 6.1.1-3ubuntu5 |
| NVIDIA client | `NVIDIA-Maxine/nim-clients` @ `7ada3461f8eec7ccdb5e4670a46aed4867faac00` (committed 2026-07-15), cloned 2026-09-08 |
| `eyecontact.proto` | sha256 `61d473238ec09ff88355809ac47ba692bbb4b4949458bee0a73e1d68d6f32aa7` |

### Server

| Item | Value |
| --- | --- |
| Server GPU | `NOT MEASURED` — no GPU host exists in this environment |
| NIM version | `NOT MEASURED` |
| Container image / tag / digest | `NOT MEASURED` — `nvcr.io` unreachable, so no tag was even observable |
| Driver / CUDA runtime | `NOT MEASURED` |
| Network context | `NOT MEASURED` — no path to any NVIDIA endpoint exists |

### Codecs, resolution, frame rate

H.264 (libx264) in MP4, 1280×720, 30 FPS constant frame rate, no audio — the
format NVIDIA's client documents as required. These are the harness's configured
values and were exercised end to end against the mock; they are **not** Maxine
measurements.

### Network

Every NVIDIA host is refused by this container's egress policy with a gateway
403 on `CONNECT`, closing the connection: `nvcr.io`, `build.nvidia.com`,
`docs.nvidia.com`, `catalog.ngc.nvidia.com`, `api.ngc.nvidia.com`. GitHub is
reachable, which is how NVIDIA's client sources were obtained and read in full.

This mirrors the Phase 1A finding and is a property of where the work ran.

## Results

### Stage A — controlled realtime-throttled stream

**`NOT EXECUTED`**

`DOES USABLE OUTPUT APPEAR BEFORE INPUT EOS?` → **`NOT MEASURED`**

No NIM was reachable, so no `RedirectGaze` RPC was opened against Maxine. The
preflight gate refused the run rather than producing a number:

```console
$ python research/maxine-eye-contact-phase1b/run.py preflight --target 127.0.0.1:8001
PREFLIGHT NOT CLEAR — blocked by: target-tcp-reachable, nim-endpoint-confirmed
```

Every other precondition passed: `grpcio 1.83.1`, NVIDIA's proto compiled from
the real clone, `ffmpeg` and `ffprobe` on `PATH`, and — recorded deliberately —
`no local NVIDIA GPU detected on this client`.

**No kill condition was triggered.** Kill condition 1 (output requires complete
input / EOS) is a statement about Maxine's behaviour, and this environment
observed none of it. Recording a Stage A `FAIL` here would be fabrication.

### Stage B — genuinely live-produced media

**`NOT EXECUTED`** — Stage A did not survive to a determination.

`CAN MAXINE CONSUME GENUINELY LIVE-GENERATED INPUT?` → **`NOT MEASURED`**

### Stage C — representative Windows-to-cloud experiment

**`NOT EXECUTED`.** No Windows client, no webcam, no GPU host. Every Stage C
metric is `NOT MEASURED`: capture timestamp, network RTT, first-response timing,
decode overhead, input/output FPS, p50/p95/p99 frame age, PTS drift, backlog,
dropped frames, stalls, CPU utilisation, server metrics.

### Temporal sanity check

**`NOT EXECUTED`.** Stage C did not run, no corrected frame was produced by
Maxine, and nothing was observed about temporal behaviour. No claim of quality
equivalence with Phase 1A is made or implied.

### What *was* measured: the instrument

A local mock speaking NVIDIA's compiled proto — **not Maxine, and no Maxine
result** — was used to verify the harness in two service behaviours. All twelve
assertions pass. Full record: `research/maxine-eye-contact-phase1b/manifests/harness-verification.json`.

| Mock behaviour | first usable frame | input EOS | usable before EOS | p50 frame age |
| --- | --- | --- | --- | --- |
| Stage A, emits progressively | 7.3 ms | 2967 ms | **YES** | 0.61 ms |
| Stage A, buffers until EOS | 2968 ms | 2967 ms | **NO** | 1509 ms |
| Stage B, live fragmented MP4, ffmpeg muxer | 147 ms | 2979 ms | **YES** | 74.4 ms |
| Stage B, live fragmented MP4, in-process muxer | 156 ms | 2975 ms | **YES** | 7.0 ms |

The second row is the important one. Against a service that will not emit until
it has the whole input, the harness reports `NO` — the Stage A kill signal — and
reports it by measurement, at 2968 ms against an EOS of 2967 ms, rather than by
timing out. Its frame-age slope goes *negative* (−33 ms per frame), the
signature of a batch service where the oldest frame waited longest. That is the
behaviour a real Maxine `FAIL` would produce, and the instrument detects it.

Media for these runs was a synthetic `testsrc2` pattern: engineering
scaffolding, never evaluation material, and evidence about nothing visual.

## Evidence classification

### Verified

| Claim | How |
| --- | --- |
| `RedirectGaze` is `stream RedirectGazeRequest → stream RedirectGazeResponse` in `nvidia.maxine.eyecontact.v1` | NVIDIA's `eyecontact.proto`, read in full, hash recorded |
| The RPC carries **MP4 container bytes**, not frames — both media fields are `video_file_data`, and the reference client reads a file and writes a file with no reframing | `eyecontact.proto`, `eye-contact.py`, `constants.py` |
| NVIDIA chunks the MP4 at 64 KiB | `constants.py`, `DATA_CHUNK_SIZE` |
| **`--streaming` changes client-side validation only and never the wire format** | grep across `eye-contact/scripts` and `interfaces`: the flag appears only in the argument definition, the dataclass field, `__str__` and `validate_eyecontact_config`. `generate_request_for_inference` never reads it |
| NVIDIA's own client already reads responses while still sending | `process_request` hands a generator to `stub.RedirectGaze`; gRPC drains it on its own thread while the caller iterates responses |
| Streaming mode's real precondition is `moov` immediately after `ftyp` | `utils.check_streamable`, read in full |
| A fragmented MP4 satisfies that rule and *can* be produced progressively | built and validated: `ffprobe` reads the harness's live output as H.264 1280×720 30 FPS and `ffmpeg` decodes it without error; 90 captured frames produced exactly 90 muxed frames |
| The reference client can exit 0 after a failed inference | `process_request` swallows every exception; independently reproduced in Phase 1A |
| No NVIDIA host is reachable from this environment | gateway 403 on `CONNECT` for five hosts, recorded verbatim |
| This client has no NVIDIA GPU and needs none | `nvidia-smi` absent, no `/dev/nvidia*`; the harness imports no CUDA and the whole suite runs without one |
| The harness holds no unbounded queue | asserted over a 400-frame progressive stream and a 300-fragment stream; peak retention 0 bytes in the live runs |
| The harness's own client-side floor on this machine | 73.4 ms p50 (ffmpeg muxer) and 5.9 ms p50 (in-process muxer), capture to sendable |

### Inferred

| Claim | Basis, and its limit |
| --- | --- |
| A live capture path must send a **fragmented** MP4 | Follows from two verified facts — the payload is a container, and `moov` must precede the media — plus the structural fact that a faststart `moov` cannot be written before the last sample is known. Not confirmed against a NIM |
| A frame whose container-described bytes have all arrived is decodable | True for in-order H.264; B-frame reordering could delay a picture. The harness corroborates its first usable frame with a real decode rather than relying on the inference |
| One 1:1 output frame per input frame | Consistent with Eye Contact's documented behaviour; not verified against a running NIM. The harness records output frame indices as it observes them |

### Unknown

All six load-bearing unknowns the experiment exists to close remain open,
unchanged:

1. whether one continuously-open `RedirectGaze` RPC can consume media generated
   genuinely incrementally at live webcam rate — **`UNKNOWN`**;
2. whether corrected media becomes usable while capture is still occurring —
   **`UNKNOWN`**;
3. first-output and steady-state frame-age latency — **`UNKNOWN`**;
4. whether latency and backlog stay bounded at ~720p30 — **`UNKNOWN`**;
5. whether temporal continuity survives the streaming path — **`UNKNOWN`**;
6. whether the `<100 ms` end-to-end target is plausible — **`UNKNOWN`**.

Also unknown: whether the NIM's demuxer accepts a *progressively delivered*
fragmented MP4. Satisfying NVIDIA's client-side check is not acceptance by a
server, and this is the single largest technical risk to Stage B.

### Failed

Nothing. No experimental step ran and failed. The absence of a GPU, a
credential, a container and a network route are environment properties, not
experimental outcomes.

## Latency decomposition

| Component | Value |
| --- | --- |
| Encode / preparation | `NOT MEASURED` against Maxine. Harness floor on this machine: **5.9 ms p50 / 9.6 ms p95** (in-process muxer), **73.4 ms p50** (ffmpeg muxer) |
| Network | `NOT MEASURED` — no route to any NIM |
| Server / NIM interval | `NOT MEASURED` |
| Response transport | `NOT MEASURED` |
| Decode | `NOT MEASURED` |
| **Total usable corrected-frame age** | **`NOT MEASURED`** |

Throughput is not substituted for any of these. The harness records output FPS
separately and stamps it with a note saying it is not latency.

One measured result deserves the Product Manager's attention now, because it
shapes what a Stage C number will mean. **ffmpeg's MP4 muxer holds each encoded
frame for about two frame intervals** — 73 ms at 30 FPS — waiting for the next
packet before it will close a fragment. No ffmpeg flag removed it
(`-avioflags direct`, `-frag_duration 1`, `-blocksize`, thread-count variants:
all ~73 ms). Driving libx264 through PyAV and writing the fragments in-process
brought it to 5.9 ms. Had the experiment run on the default path, roughly
three-quarters of the PRD's entire `<100 ms` budget would have been consumed by
the harness before a byte reached the network, and the result would have
described the harness rather than the NIM. Both paths ship; the low-latency one
is required for any number compared against the PRD.

## Temporal observation

None. Nothing was observed.

## Failures and limitations

**Not exercised, explicitly:**

- any call to a real Maxine Eye Contact NIM, self-hosted or hosted;
- the NIM container — never pulled, `nvcr.io` unreachable;
- Windows, in any form; the harness has never run on Windows;
- a physical webcam; `camera_frames` is written and documented but unexercised,
  and the `dshow` device string has never been resolved;
- TLS and mTLS channel modes; only the insecure loopback channel was exercised;
- the hosted developer-preview endpoint, deliberately — it is not the Phase 1B
  route, and a preview measurement would characterise NVIDIA's hosted function,
  not the self-hosted backend under evaluation;
- Product Owner footage, deliberately — Stage A is a transport measurement and
  a synthetic or NVIDIA-supplied clip answers it without sending private footage
  to a third-party service.

**Known limits of the harness itself:**

- Frame-age resolution is one response chunk. Several frames completed by one
  64 KiB write share that write's timestamp.
- Output frames are matched to source frames by index, assuming 1:1 and
  in-order. If a NIM ever returned a different frame count the ages would be
  misaligned; the harness records both counts so the assumption is checkable.
- The in-process muxer occasionally misses capture cadence on this four-core VM
  (9 late frames in 90, max 132 ms), because it encodes on the sender thread.
  That is realistic for a live client and is reported per run, not hidden.
- Only the first video track is indexed; edit lists are ignored. Both are safe
  for the constant-frame-rate single-track H.264 the NIM requires and neither
  moves a timestamp for it.
- The self-test's media is synthetic. It proves transport behaviour and nothing
  visual.

## Repository changes

**Branch:** `claude/maxine-phase-1b-runtime-p6ukkc`, based on
`program-state-v1` @ `22e8dc1490acd38bebc4f19360a7035b91b7e900`.

The designated branch already existed pointing at `main`, which holds only
Milestone 0. Committing there would have produced a tree missing all M1/M2/M3
work and the Phase 1A package — a diff that reads as mass deletion. It was reset
onto the canonical current program-state pointer instead. No new branch name was
created, no remote history was discarded (the branch held no unique commits),
and no frozen reference was touched.

**Created:**

| Path | What |
| --- | --- |
| `research/maxine-eye-contact-phase1b/README.md` | how to run, and the current blocked state |
| `research/maxine-eye-contact-phase1b/protocol.md` | the experimental design and what each stage does and does not establish |
| `research/maxine-eye-contact-phase1b/RUNBOOK.md` | the operator's provisioning steps and run order |
| `research/maxine-eye-contact-phase1b/run.py` | CLI: `preflight`, `stage-a`, `stage-b`, `mock`, `selftest` |
| `streamexp/mp4.py` | ISO-BMFF indexing: layout classification, sample tables, fragments |
| `streamexp/progressive.py` | memory-bounded per-frame usability instants from a growing stream |
| `streamexp/session.py` | one continuously-open `RedirectGaze` RPC, paced send, concurrent read |
| `streamexp/source.py` | Stage A's realtime-throttled feeder |
| `streamexp/livesource.py` | Stage B/C live producers, both muxing paths |
| `streamexp/fmp4.py` | in-process fragmented MP4 writer |
| `streamexp/h264.py` | NAL framing and the `avcC` record |
| `streamexp/clock.py` | realtime pacing, with lateness recorded |
| `streamexp/timing.py` | timeline, percentiles, `NOT MEASURED` discipline |
| `streamexp/decode.py` | decode corroboration of the first usable prefix |
| `streamexp/channel.py` | insecure / TLS / mTLS / preview channels, credential handling |
| `streamexp/proto.py` | compiles and imports NVIDIA's own `.proto` |
| `streamexp/preflight.py` | the blocking precondition gate |
| `streamexp/mockserver.py` | local test double speaking the real proto |
| `streamexp/selftest.py` | the twelve harness assertions |
| `tests/` (8 test modules plus `conftest.py`, 74 tests) | automated tests for the harness |
| `manifests/nvidia-api-contract.json` | first-hand NVIDIA evidence with SHA-256 and retrieval date |
| `manifests/harness-verification.json` | what the self-test measured, and on what machine |
| `docs/milestones/maxine-phase1b-runtime-experiment-report.md` | this report |

**Modified:** `.gitignore` — one comment block ignoring a locally fetched NVIDIA
client under the Phase 1B package, mirroring the Phase 1A entry.

**Not modified:** the PRD, `docs/architecture.md`, any ADR, `docs/qa-policy.md`,
any frozen milestone or architecture reference, `research/maxine-eye-contact/`
(Phase 1A, byte-identical), any product module under `gazefix/`, the product
test suite, `pyproject.toml`, or any evaluation or scoring evidence. Verified by
diff against `program-state-v1`: one changed file, `.gitignore`.

**Not committed:** video, corrected output, timing series and the NVIDIA clone,
all under the already-ignored `experiments/maxine-phase1b/`. NVIDIA's sample
assets are covered by the NVIDIA Maxine Sample Data License and are not
committed; they are Git LFS pointers in a plain clone anyway.

**Credentials:** none present, none committed, none logged. The harness reads
`NVIDIA_API_KEY` from the environment only in preview mode and places it only in
call metadata; a test asserts that no preflight output can contain it.

**Tests:** `python -m pytest research/maxine-eye-contact-phase1b/tests -q` —
**74 passed, 0 failed**. `pyflakes` clean. The product suite was not run and was
not affected; no product file changed.

## Two conclusions, kept apart

**`REALTIME TECHNICAL FEASIBILITY: UNKNOWN`** — unchanged by this work. Nothing
observed here makes Maxine more or less likely to stream at webcam rate. The
desk research's central premise was confirmed first-hand (the RPC really is
bidirectional streaming, and the reference client really does read while
sending), and one new structural fact was established: the payload is a
container, so a live client must build one progressively. That is now a solved
engineering problem on the client side; whether the *server* accepts it is
untested.

**`CURRENT PRD LATENCY COMPLIANCE: NOT MEASURED`** — and unchanged. The PRD
remains exactly as it is: 720p, `>=24` FPS with 30 preferred, `<100 ms`
end-to-end (`<50 ms` preferred), Intel CPU/iGPU client with no NVIDIA or CUDA
requirement, local-only processing. The cloud route this experiment would
exercise intentionally violates local-only; that is a bounded experimental
condition, not a proposal, and nothing here changes the requirement.

## The smallest concrete action required

The experiment is blocked on one thing: **a self-hosted NVIDIA Maxine Eye
Contact NIM the harness can reach.**

1. Provide a host with a supported NVIDIA GPU. It need not be — and should not
   be assumed to be — the GazeFix client machine.
2. On that host, `docker login nvcr.io` with an NGC API key and pull the Eye
   Contact NIM image named on its NGC catalogue page. **Record the exact image,
   tag and digest**; a latency number is not interpretable without it. The
   catalogue page could not be read from here and no tag is guessed.
3. Run the container per NVIDIA's quick start guide and note the gRPC port.
4. Confirm it is serving, then run `preflight`, `stage-a`, and — only if Stage A
   survives — `stage-b`.

`RUNBOOK.md` has the exact commands. The NGC credential belongs to
`docker login` on the GPU host; it is not needed by the harness at call time and
must never enter this repository.

Nothing else is missing. Not substituting a different service, and not
substituting the hosted developer-preview endpoint for the self-hosted route,
are deliberate: neither is authorized, and the harness has no code path to
either.

## Recommendation

**`RETURN TO PM — ADDITIONAL EVIDENCE REQUIRED`**

The evidence required is a running NIM, and only the Product Owner can provision
it. Once it exists, Stage A is a single command and answers the load-bearing
question in about ten seconds of media.

Maxine is not being kept alive because Phase 1A passed visually. It is being
kept alive because the six unknowns are genuinely unclosed in either direction,
and the one route that could close them is one provisioning step away.

Nothing beyond Phase 1B follows from this report. No M4, no virtual-camera work,
no PRD revision, no product architecture, no ADR, and no milestone transition.


---

# Continuation — 2026-09-09: real NIM provisioned, execution still blocked here

**`PHASE 1B RUNTIME EXPERIMENT — INCONCLUSIVE (UNCHANGED)`**

The Product Owner has provisioned a real self-hosted NIM on a GCP VM
(`nvcr.io/nim/nvidia/maxine-eye-contact:1.4.0`, digest
`sha256:96abb52a2e1069cc2ab39f142a9847ab945caaa74b3b2da6490d6deae1726b4b`,
NVIDIA L4, driver 595.91.07, CUDA 13.2, compute-capability 8.9 profile, Triton
model `GazeRedirectionKey68` v1 READY, gRPC on 8001, health `SERVING`).

**Stage A and Stage B were still not executed, because this engineering session
does not run on that VM.** Verified, not assumed:

| Check | Result |
| --- | --- |
| `nvidia-smi`, `/dev/nvidia*` | absent |
| `localhost:8001` | `ConnectionRefusedError` — nothing listening |
| Any listening port at all | none |
| `gcloud`, `gsutil`, SSH keys | absent |
| GCE metadata server (`169.254.169.254`) | unreachable — this is not a GCE instance |

The NIM is deliberately not exposed publicly, so there is no route from here.
The run must be performed on the VM; `research/maxine-eye-contact-phase1b/RUNBOOK.md`
now carries the exact command sequence for it.

## What this session did instead

The harness had never met anything but an echo mock. Before spending a one-shot
run on borrowed GPU time, it was reviewed adversarially and rehearsed against
mocks that behave the way a real NIM plausibly might. **Nine defects were found
and fixed, four of which would have produced a confidently wrong answer.**

Every fix below was verified by rehearsal, not by inspection alone. None of these
rehearsals is a Maxine measurement.

### Would have caused a FALSE FAIL — reporting `NO` when the truth was otherwise

1. **A mid-stream non-OK gRPC status fabricated an `input_eos` event.** The
   sender marked EOS in a bare `finally`, which also runs on the `GeneratorExit`
   gRPC injects when it abandons the call. `output_before_eos()` then compared
   against a moment the client never reached and returned `NO`. A NIM answering
   `RESOURCE_EXHAUSTED` because its single L4 instance was busy would have been
   recorded as "Maxine cannot stream". Now: `input_aborted` is marked instead,
   and the determination is `NOT MEASURED`. Rehearsed against servers aborting
   with `RESOURCE_EXHAUSTED` and `INVALID_ARGUMENT` — both now yield
   `NOT MEASURED` with the status preserved verbatim.

2. **Stage B's determination had the same flaw**, and additionally required the
   *output* to be indexable. A NIM that consumed the live-generated container
   and returned valid corrected bytes in a `moov`-last layout would have been
   recorded as not having consumed it. Stage B now answers from the input side,
   distinguishes a refusal (`INVALID_ARGUMENT`, `FAILED_PRECONDITION`, …) from a
   transient end (`RESOURCE_EXHAUSTED` → `NOT MEASURED`), and reports output
   indexability separately.

3. **Stage B never validated its source at all.** Stage A's guards did not apply
   to it, and `frames_from_video` sent ffmpeg's stderr to `/dev/null`, so an
   unreadable file produced a clean-looking zero-frame run indistinguishable
   from a service that accepted the stream and returned nothing. Both stages now
   share the guards, and the decoder's reason is surfaced.

4. **Pacing broke on any source with B-frames.** `paced_units` assigned each
   byte range the raw per-sample PTS while walking in decode order; with
   B-frames PTS is non-monotonic there, so deadlines were already in the past
   and the realtime schedule Stage A depends on collapsed. Measured on a real
   B-frame clip the delta set was `[-1024, -512, 512, 1024, 1536, 2048]`.
   Release is now the running maximum of PTS — the instant a live encoder could
   actually have produced those bytes. The same bug made `nominal_fps()` report
   ordinary constant-rate material as variable, which would have raised a
   spurious VFR warning about the one thing the NIM refuses; frame rate now
   comes from `stts` decode durations (`30.0` where it previously read `None`).

### Would have produced misleading or missing evidence

5. **A `NO` came with no evidence about what the service returned.** Rehearsed
   with a NIM emitting a `moov`-last output: the harness correctly said `NO` but
   recorded `decode_corroboration: NOT MEASURED` beside 3.8 MB of received
   video, leaving "works but batches" and "returned garbage" indistinguishable.
   The complete output is now decoded and its frame count compared against the
   source, and the reason nothing was usable is stated (`MOOV_LAST` vs a parser
   fault vs no sample completing) rather than assumed.

6. **Frame-age percentiles were computed from a silent subset.** A corrected
   frame recorded before the sender had noted the matching source frame's send
   instant simply lost its age. Rehearsed with a re-encoded output: **21 of 120
   frames were aged while the summary reported 120 output frames.** The race is
   now eliminated at source (the feed instant is recorded before the write, not
   after), ages are reconciled after the run, coverage is reported as
   `age_coverage`, and a negative age — physically impossible — is counted and
   flagged rather than averaged in.

7. **`backlog.csv` was empty exactly when backlog mattered.** Sampling happened
   inside the response loop, so a service that accepted the stream and returned
   nothing produced no rows at all. Sampling is now clock-driven: the same
   rehearsal now records 8 rows showing 3,347,475 bytes outstanding against
   silence.

8. **ffmpeg's stderr was blank exactly when it was the only evidence.** On an
   abnormal end, `live.units()` was never finalised, so the encoder was unreaped
   and its stderr unread — the one artifact separating "the NIM rejected our
   container" from "our encoder produced a broken one". The producer is now
   closed explicitly.

9. **The default Stage B path dropped its last frame.** `-fflags +nobuffer`
   caused ffmpeg to emit N-1 fragments for N frames (measured: 29/30, 89/90),
   which would have shown as a permanent output/input mismatch casting doubt on
   a genuine PASS. It bought nothing on a rawvideo pipe. Removing it fixed the
   frame count **and** cut the ffmpeg path's client-side latency from **73.4 ms
   to 42.2 ms p50**.

### Smaller hardening

- No HTTP/2 keepalive pings on the channel. NVIDIA's client sends none, and a
  gRPC server's default minimum ping interval is five minutes with two strikes
  before `GOAWAY(too_many_pings)` — harmless while the NIM streams, fatal
  precisely when it goes quiet, which is what Stage A must observe.
- `grpc.channel_ready_future` before the RPC: a TCP connect succeeds as soon as
  Triton's socket listens, which can precede the model being READY.
- H.264-only gate on the Stage A source (an HEVC clip remuxed `+faststart`
  passed every previous check), and a Git-LFS-pointer check that names the
  problem instead of failing obscurely.
- A source whose realtime duration would not fit inside the RPC deadline is
  refused, naming the `--rpc-timeout` that would be needed.
- `SourceUnsuitable` reaches the operator as `SOURCE UNSUITABLE — this is a
  statement about the file, not about Maxine` with exit code 3, not a traceback.
- A `failure_attribution.blame` field on every run: `NONE` / `SERVER` /
  `HARNESS` / `HARNESS PARSER` / `OPERATOR`, with `grpc_status` and
  `grpc_details` preserved as structured fields.
- The server's config echo is captured. The summary previously claimed "none
  (NVIDIA defaults)" while an **empty** `RedirectGazeConfig` was in fact sent;
  it now says exactly what went on the wire and offers `--no-config`.
- Retention is capped while the container layout is unclassified, so an
  unfamiliar response cannot become the unbounded queue the experiment forbids.
- **The source must contain a human face.** The documentation previously said
  "any other clip works if it is streamable" and pointed at synthetic material.
  Eye Contact redirects gaze; given no face there is nothing to redirect, and
  whatever it does then would be indistinguishable from a streaming failure.

### A second round, from the completeness critic

The adversarial review completed after the first round of fixes had already
landed. **Forty-four of forty-four verifiers returned "not real"** — almost all
of them because the finding had been fixed while the review was still running
and the verifier was reading the superseded commit. That is not evidence of a
clean harness, and it is not reported as such; it is corroboration that the
first round landed. One finding was refuted on its merits rather than on
staleness: sending an empty `RedirectGazeConfig` was judged harmless, which is
why that default was left alone and documented instead of changed on a guess.

The completeness critic then found seven gaps the six review dimensions had
missed, **four of them created by this session's own fixes**. Two were blockers,
both reproduced before being fixed:

10. **A Stage B run that produced zero frames answered `YES` anyway.** Three
    things interlocked: `_write_frames` swallowed the very `LiveSourceError`
    added earlier in this session, ffmpeg still emits a valid 778-byte init
    segment for a track with no samples and exits 0, and the determination was
    built unconditionally. Reproduced: `maxine_consumed_live_generated_input:
    YES`, `blame: NONE`, `error: ""`, with `frames_muxed_matches_captured: true`
    (0 == 0) actively reassuring the reader. Against the real NIM the mirror
    case is worse — an init segment describing no samples would draw
    `INVALID_ARGUMENT`, which the RUNBOOK reads as the Stage B kill condition.
    A zero-frame run is now refused outright, with the decoder's own reason.

11. **Stage B varied the H.264 profile as well as the container.** Measured with
    the harness's exact flags, `-preset ultrafast` emits **Constrained Baseline**
    while every other preset emits **High**. Stage A sends NVIDIA's file
    unchanged, so Stage B was varying two things at once, and no flag could
    isolate them — the RUNBOOK's three remediation attempts all held the same
    bitstream. A refusal for a bitstream reason would have been recorded as a
    refusal of the progressively-delivered container: a designed path to
    retiring the technology on an unisolated variable. The default is now
    `superfast` (High profile, still no B-frames, no lookahead, latency cost
    within noise), `--x264-preset`/`--x264-tune` are exposed, and RUNBOOK §9
    gains a fourth attempt that varies the bitstream deliberately.

12. **The "cannot classify this container" fallback claimed kill condition 3.**
    The 8 MiB retention cap added earlier this session set `layout = MOOV_LAST`
    purely to stop buffering, and `_determinations` then asserted
    `kill_condition_3_whole_file_interface: OBSERVED — the response placed its
    moov after the media`. Since this parser has never seen a Maxine container,
    an unfamiliar box shape would have been reported as an observed kill
    condition. There is now a distinct `UNCLASSIFIED_BY_THIS_HARNESS` layout
    that reports `NOT MEASURED` and says the limitation is ours.

13. **Stage A returned a hard `NO` when a parser fault was the only reason
    nothing was located**, `_attribution` blamed the **server** for a
    client-side sender failure, a parse fault on our *own* outbound container
    aborted the Stage B RPC, and Stage B lacked Stage A's deadline-versus-
    duration guard. All four fixed.

## Verification of this session's work

| Check | Result |
| --- | --- |
| Automated tests | **108 passed** (was 74), repeated runs, no flakiness |
| `pyflakes` | clean |
| Harness self-test | **PASS**, 12/12 assertions |
| Age coverage, all four self-test runs | `90/90`, correspondence `1:1`, zero impossible ages |
| Harness client-side floor, re-measured | ffmpeg muxer **44.7 ms** p50, in-process **8.5 ms** p50 |
| Stage B bitstream | H.264 **High**, 1280x720 (was Constrained Baseline) |
| Adversarial review | 51 agents, 6 dimensions, 44 verifiers, 1 completeness critic |

`NOT MEASURED` still applies to every Maxine quantity. Nothing in this section
is evidence about Maxine; it is evidence that the instrument will not lie about
Maxine.

## Status and recommendation, unchanged in substance

**`PHASE 1B RUNTIME EXPERIMENT — INCONCLUSIVE`**

`REALTIME TECHNICAL FEASIBILITY: UNKNOWN`.
`CURRENT PRD LATENCY COMPLIANCE: NOT MEASURED`. The PRD is unchanged.

**`RETURN TO PM — ADDITIONAL EVIDENCE REQUIRED`** — the evidence being a Stage A
and Stage B run executed **on the GCP VM**, which this session cannot reach. The
commands are in `RUNBOOK.md`; Stage A answers the load-bearing question in about
ten seconds of media.

Stage C is not run and is not authorized by anything here. No M4, no
virtual-camera work, no PRD revision, no architecture, no ADR.
