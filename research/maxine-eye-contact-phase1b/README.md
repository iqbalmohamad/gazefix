# Maxine Eye Contact — Phase 1B realtime streaming experiment

**`RESEARCH/EXPERIMENT ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

Bounded harness for the Product Manager's `MAXINE PHASE 1B RUNTIME EXPERIMENT`
authorization. It answers one question:

> Can one continuously-open `RedirectGaze` RPC consume H.264 media generated
> incrementally at webcam rate, return decodable corrected frames while capture
> is still occurring, and maintain bounded frame age without queue growth?

`protocol.md` is the frozen design and the authority on *why*. `RUNBOOK.md` is
what has to be provisioned before anything can run. This file is *how to run it*.

Phase 1A (`research/maxine-eye-contact/`) is a **separate, unchanged package**.
Nothing here modifies it, its evidence, or any frozen reference.

## Status of this package

**The experiment has not been executed against a Maxine NIM.** The harness is
complete and its own correctness is verified; the service is not present.

| Precondition | State in the engineering environment |
| --- | --- |
| NVIDIA GPU for the NIM | **absent** — no `nvidia-smi`, no `/dev/nvidia*` |
| Eye Contact NIM container | **unobtainable** — `nvcr.io` refused, 403 on CONNECT |
| NGC / NVIDIA credential | **absent** — no credential is present and none may be committed |
| Network route to NVIDIA | **denied** — every `nvidia.com` host and `nvcr.io` return a gateway 403 |
| `grpcio`, `ffmpeg`, `ffprobe`, NVIDIA's proto | present, and the harness self-test passes |

All four missing preconditions belong to a machine with a supported GPU and NGC
access. `RUNBOOK.md` lists the smallest concrete steps.

```console
$ python research/maxine-eye-contact-phase1b/run.py preflight
PREFLIGHT NOT CLEAR — blocked by: target-tcp-reachable, nim-endpoint-confirmed
```

## Isolation from the product

Nothing here imports `gazefix`, and nothing in `gazefix` imports this. No
product dependency manifest is touched. Run artifacts — sources, corrected
output, timing series — go to the already-ignored `experiments/maxine-phase1b/`;
only the harness, its tests, small manifests and this documentation are
committed, matching the Phase 1A and M3 convention.

```text
research/maxine-eye-contact-phase1b/
  README.md                            this file
  protocol.md                          the experimental design
  RUNBOOK.md                           what an operator must provision, and the run order
  run.py                               entry script
  streamexp/                           the harness (standard library, plus grpcio)
  manifests/nvidia-api-contract.json   first-hand NVIDIA API evidence, with hashes
  manifests/harness-verification.json  what the self-test measured, and on what machine
  tests/                               automated tests for this harness
```

## Setup

### 1. Python packages

```powershell
py -3.11 -m venv .venv-maxine1b
.venv-maxine1b\Scripts\python -m pip install grpcio grpcio-tools pytest
.venv-maxine1b\Scripts\python -m pip install av      # only for --muxer inprocess
```

Use a **separate** virtual environment, as Phase 1A does. NVIDIA's
`grpcio-tools` pulls a `protobuf` that pip flags as incompatible with
`mediapipe 0.10.21`, and the GazeFix environment must stay exactly as the frozen
baseline expects.

### 2. ffmpeg

`ffmpeg` and `ffprobe` on `PATH`. On Windows, `winget install Gyan.FFmpeg` or an
equivalent build. The harness shells out to them; it does not vendor them.

### 3. NVIDIA's service contract

The harness compiles and imports NVIDIA's own `.proto` rather than restating the
protocol, so the messages it sends are by construction the messages NVIDIA
defines. It will not run without it.

```powershell
git clone https://github.com/NVIDIA-Maxine/nim-clients.git `
  experiments\maxine-phase1b\nvidia-client
```

Keep the clone intact — NVIDIA's client imports `utils.utils` from the clone
root. `run.py` compiles the protos on first use; no manual `protoc` step is
needed.

### 4. A serving NIM

See `RUNBOOK.md`. This is the step that cannot be automated from here.

## Running

```powershell
python research/maxine-eye-contact-phase1b/run.py preflight --target <host:port>

python research/maxine-eye-contact-phase1b/run.py stage-a `
  --target <host:port> --source <streamable.mp4> --i-have-confirmed-nim-endpoint

python research/maxine-eye-contact-phase1b/run.py stage-b `
  --target <host:port> --source <clip.mp4> --i-have-confirmed-nim-endpoint

# Stage C: the same stage-b command with a camera and the low-latency muxer
python research/maxine-eye-contact-phase1b/run.py stage-b `
  --target <host:port> --frame-source camera --camera-backend dshow `
  --camera-device "video=<Your Camera Name>" --muxer inprocess `
  --width 1280 --height 720 --fps 30 --label stage-c `
  --i-have-confirmed-nim-endpoint
```

Each run writes `summary.json`, `timeline.csv`, `frames.csv`, `backlog.csv` and
the corrected output under `experiments/maxine-phase1b/<label>/`.

**Stop after Stage A if it reports `usable_output_before_input_eos: NO`.** That
is the kill condition, and Stage B is not run.

### Choosing the muxer for Stage B and C

`--muxer ffmpeg` (default) uses the widely-deployed muxer and is the right
choice for establishing that the NIM accepts the container at all. It cost
~73 ms per frame of client-side latency on the verification machine, because it
holds each frame until it has seen the next one.

`--muxer inprocess` drives libx264 through PyAV and writes each fragment
immediately — ~6 ms on the same machine. Use it for any latency number that will
be compared against the PRD. It needs `pip install av`, and the harness refuses
rather than silently falling back, since swapping in a path with twelve times
the latency would corrupt the result.

### Verifying the harness before trusting it

```powershell
python research/maxine-eye-contact-phase1b/run.py selftest
```

Runs both stages against a local mock that speaks NVIDIA's compiled proto in two
behaviours — emit-progressively and buffer-until-EOS — and checks that the
harness paces its input, reads while sending, indexes frames, detects the
buffer-until-EOS case rather than waiting it out, retains a bounded number of
bytes, and muxes exactly one fragment per captured frame. It also records this
machine's client-side latency floor.

**A `PASS` here is a statement about the harness and about nothing else.** It is
not a Maxine measurement and must never be reported as one.

## Tests

```powershell
python -m pytest research/maxine-eye-contact-phase1b/tests -q
```

74 tests, no network, no credential and no NVIDIA service. Tests that need
NVIDIA's cloned proto or `ffmpeg` skip when those are absent rather than
pretending. They run separately from the product suite because the product
`pyproject.toml` restricts `testpaths` to `tests/`, and that file stays
unchanged.

## Credentials

A self-hosted NIM needs no NVIDIA API key at call time; the NGC credential is
for pulling the container and belongs to `docker login`, not to this repository.
`--mode preview` exists only so the hosted developer-preview function can be
called deliberately, reads `NVIDIA_API_KEY` from the environment, places it in
call metadata only, and never writes it to a file, a log or a command line.

**Preview mode is not the Phase 1B route.** A preview measurement characterises
NVIDIA's hosted function, not the self-hosted backend under evaluation, and the
preflight says so on every such run.

## What this package will not do

No product runtime integration, no `CorrectionEngine`, no correction backend
adoption, no virtual camera, no Zoom/Meet/Teams integration, no M4, no M8, no
PRD change, no solution architecture, no ADR, no model search or substitution,
no fallback to another service when Maxine is unavailable, no LivePortrait in
any role, no training or fine-tuning, no vendor outreach, and no modification of
any frozen milestone, architecture or evidence reference.

A Phase 1B result — in either direction — authorizes none of the above on its
own. The Product Manager issues the Phase 1B gate verdict.
