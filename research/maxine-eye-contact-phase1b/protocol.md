# Phase 1B — experimental design

**`RESEARCH/EXPERIMENT ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

This document is the design and the authority on *why* each step is shaped the
way it is. `README.md` is how to run it. `RUNBOOK.md` is what an operator has to
provision first.

## The one question

> Can one continuously-open NVIDIA Maxine Eye Contact `RedirectGaze` RPC consume
> H.264 media generated incrementally at webcam rate, return decodable corrected
> frames while capture is still occurring, and maintain bounded frame age
> without queue growth?

Everything here exists to close that. Nothing here is a realtime GazeFix
pipeline, M4, webcam product integration, a virtual camera, a conferencing
integration, or a production cloud architecture.

## What Phase 1A did and did not leave behind

Phase 1A closed as `PASS` on **visual feasibility only**. It establishes no
realtime feasibility, no streaming feasibility, and no adoption. Its measured
turnaround was explicitly labelled `HOSTED BATCH/API TURNAROUND — NOT REALTIME
LATENCY`, and this experiment never reuses that number for anything.

Three inference rules are therefore treated as errors throughout:

- realtime latency is never inferred from whole-request turnaround;
- per-frame latency is never inferred from aggregate FPS;
- webcam support is never inferred from the existence of a gRPC streaming RPC.

## The thing that shapes every design decision

`RedirectGaze` carries **MP4 container bytes**, not frames
(`manifests/nvidia-api-contract.json`, finding F1). There is no frame-level
message in the contract and none is invented here. Two consequences run through
the whole design.

**A per-frame latency question has to be answered from a byte stream.** So the
harness indexes the container as it arrives: a coded frame is *usable* when the
container has described it and every one of its bytes has been received
(`streamexp/progressive.py`). That is a container fact, and it is corroborated
by decoding the exact prefix the client held at that instant
(`streamexp/decode.py`) rather than asserted to be equivalent to a decode.

**A live client has to manufacture a container progressively.** A conventional
faststart MP4 cannot be: its `moov` describes every sample, so it can only be
written once the last sample is known. A fragmented MP4 can — `ftyp`, a `moov`
carrying `mvex` and empty sample tables, then one `moof`/`mdat` per frame — and
it satisfies exactly the condition NVIDIA's own `check_streamable` tests for
(finding F4). Whether the NIM's demuxer *accepts* one delivered progressively is
finding F9: `UNKNOWN`, and precisely what Stage B asks.

## Stage A — controlled realtime-throttled stream

**Proves or disproves:** that the service returns usable corrected output before
it has the whole input.

A known-good streamable MP4 — H.264, constant frame rate, `moov` before the
media, and **containing a clearly visible human face** — is fed through one
`RedirectGaze` invocation at the cadence of its own presentation timestamps.
The face is not optional: Eye Contact redirects gaze, so given a synthetic
pattern there is nothing to redirect, and whatever the service does then could
not be distinguished from a streaming failure. Synthetic media belongs to the
mock self-test only. The bytes of the frame shown at
t = 1.4 s are not handed to the RPC before 1.4 s of feeding has elapsed, because
a camera could not have produced them earlier. `ftyp` and `moov` are the one
exception and go out immediately: in a live fragmented stream the initialisation
segment genuinely is available at t = 0.

Sending the file as fast as the disk allows would answer a batch-throughput
question. That is the failure mode this stage exists to avoid, and the harness
self-test asserts against it: a three-second source must take about three
seconds to feed.

**Determination:** `DOES USABLE OUTPUT APPEAR BEFORE INPUT EOS? YES / NO`.

**Kill condition.** `NO`, under the supported streaming mode, is
`STOP — PHASE 1B FAIL CANDIDATE`. Stage B is not run.

A `moov`-last response is a stronger form of the same result and is reported
separately: it means no corrected frame could be *located* until the whole
output had arrived, which is kill condition 3 rather than a slow server.

## Stage B — genuinely live-produced media

**Proves or disproves:** that the NIM will consume media that did not exist when
the call opened.

Requirements this stage holds itself to:

- the media is produced while the RPC is active;
- **no completed input MP4 exists before the RPC starts** — the harness never
  writes one, and the run record states so as a measured property;
- the bytes go to the *same* continuously-open `RedirectGaze` invocation;
- responses are consumed concurrently.

Frames enter an encoder at capture cadence and leave as `moof`/`mdat` pairs that
are forwarded immediately. Prerecorded frames replayed at capture cadence are
sufficient here: the property under test is that the container is built live,
not that a camera is physically present.

Two muxing paths exist because they answer different halves of the stage:

| Path | Use it for | Measured client-side cost |
| --- | --- | --- |
| `--muxer ffmpeg` (default) | *Will the NIM accept this container at all?* Uses the muxer that writes most of the world's fragmented MP4. | ~73 ms per frame on the verification machine |
| `--muxer inprocess` | *What is the latency?* PyAV packets muxed by `streamexp/fmp4.py`. | ~6 ms per frame on the same machine |

The gap is not incidental. ffmpeg's MP4 muxer will not close a fragment until it
has seen the next packet, which costs about two frame intervals — most of the
PRD's whole `<100 ms` budget, spent before a byte reaches the network. A Stage C
number taken on the default path would describe the harness more than the NIM.
Both are offered, both are measured, and neither is silently substituted for the
other.

**Determination:** `CAN MAXINE CONSUME GENUINELY LIVE-GENERATED INPUT? YES / NO`.

**Kill condition.** If the service fundamentally requires a completed or
prebuilt MP4 structure that cannot be generated progressively, that is
`STOP — PHASE 1B FAIL CANDIDATE`. No alternative interface is invented.

## Stage C — representative Windows-to-cloud experiment

Only after A and B survive. Client: Windows 11, Intel Core i7-1165G7 / Iris Xe
where available, no NVIDIA GPU and no CUDA, 1280×720, ~30 FPS. Server: a
supported NVIDIA GPU running the Eye Contact NIM, self-hosted.

```text
camera or realtime frame source
  → incremental H.264 preparation
  → persistent gRPC RedirectGaze
  → Maxine NIM
  → incremental response
  → client decode
```

No virtual camera. No Zoom, Meet or Teams.

**The key metric is not throughput.** It is the **age of a corrected frame when
it becomes usable on the client** — measured from the instant the source frame
existed, reported as p50, p95, p99 and a maximum, with the raw per-frame series
written beside it. Aggregate FPS is recorded for completeness and carries a note
saying it is not latency.

Also recorded: encode/preparation cost, first-output timing, backlog and queue
growth over the run, schedule lateness, dropped frames, and the slope of frame
age against frame number — a persistently positive slope is kill condition 4,
latency growing with stream duration.

**The harness's own floor must be subtracted before judging any number against
the PRD.** It is measured on the machine that ran the experiment and recorded in
`manifests/harness-verification.json`, not assumed to be negligible.

### Temporal sanity check

If Stage C runs, a small qualitative look only: normal gaze movement, a blink,
an upward and a downward glance, minor head motion. The question is whether the
streaming path introduces *obvious* temporal degradation relative to the already
approved Phase 1A behaviour. This is not a repeat of the Phase 1A scoring
exercise, and no claim of quality equivalence follows from it.

## Two conclusions, kept apart

`REALTIME TECHNICAL FEASIBILITY` and `CURRENT PRD LATENCY COMPLIANCE` are
reported separately. The PRD's `<100 ms` end-to-end target, `>=24 FPS` (30
preferred), Intel client with no NVIDIA/CUDA requirement, and **local-only
processing** are unchanged by this experiment. The cloud route intentionally
violates local-only; that is a bounded experimental condition, not a proposal.
A technically usable cloud route that exceeds `<100 ms` does not change the PRD.

## Evidence discipline

Every load-bearing claim carries one of `VERIFIED`, `INFERRED`, `UNKNOWN` or
`FAILED`. An unavailable measurement is `NOT MEASURED` — the harness emits that
string rather than a zero, and its statistics helpers return it for an empty
series instead of inventing a percentile. No benchmark value is fabricated.

The preflight gate refuses to run when a precondition is missing, because a
number produced without a real NIM behind it would look like a Maxine result
and would not be one. Two of its checks can only be cleared by a human:
confirming a self-hosted NIM is genuinely serving the target, and recording
whether the client machine has an NVIDIA GPU — so that a run on a machine that
happens to have one is never read as evidence about a client that does not.

## Prohibitions this package holds itself to

No product runtime integration; nothing imports `gazefix` and nothing in
`gazefix` imports this. No `CorrectionEngine`, no correction backend adoption,
no virtual camera, no conferencing integration, no M4, no M8, no PRD change, no
architecture or ADR, no model search or substitution, no fallback to another
service when Maxine is unavailable, no LivePortrait in any role, no training or
fine-tuning, no vendor outreach, and no modification of any frozen reference.
