# Phase 1B runbook — what has to exist before the experiment can run

**`RESEARCH/EXPERIMENT ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

The harness is finished and self-verified. It stopped at the first thing it
cannot provide for itself: **a running NVIDIA Maxine Eye Contact NIM.** This
document is the smallest concrete set of actions that unblocks it, and nothing
beyond that.

## Why it stopped here

The engineering environment has no NVIDIA GPU, no route to any NVIDIA host, and
no NGC credential. Those are properties of *where this ran*, not of the
experiment's design.

```console
$ curl -sS -o /dev/null -w '%{http_code}' https://nvcr.io/v2/
000        # CONNECT tunnel failed, gateway answered 403
$ nvidia-smi
nvidia-smi: command not found
$ ls /dev/nvidia*
No such file or directory
```

Substituting a different service is not authorized and the harness has no code
path that would do it.

## Step 1 — a host with a supported NVIDIA GPU

Any machine or cloud instance whose GPU the Eye Contact NIM supports. It does
**not** have to be the GazeFix client machine, and it must not be assumed to be:
the PRD forbids requiring NVIDIA or CUDA hardware on the client, and the
experiment is specifically arranged so the client needs neither.

Record, for the report: GPU model, driver version, CUDA runtime version, and how
the host is reached from the client (same LAN, VPN, public internet, region).

## Step 2 — NGC access and the container

1. Sign in at <https://ngc.nvidia.com> and generate an API key.
2. On the GPU host:

   ```bash
   docker login nvcr.io          # username: $oauthtoken, password: the NGC API key
   docker pull <the Eye Contact NIM image from its NGC catalogue entry>
   ```

   The exact image path and tag come from the NIM's own catalogue page. This
   record deliberately does not guess one: no NVIDIA page was reachable from the
   environment that wrote it, and an invented tag would be worse than an absent
   one.

3. Run the container following NVIDIA's quick start guide
   (<https://docs.nvidia.com/nim/maxine/eye-contact/latest/index.html>), and note
   the gRPC port it serves.

**Record the exact image name, tag and digest.** The report has a field for it
and it is currently `NOT MEASURED`; a latency result is not interpretable
without knowing which build produced it.

The NGC key belongs to `docker login` on the GPU host. It is not needed by the
harness at call time and must never be written into this repository.

## Step 3 — confirm the endpoint, deliberately

```powershell
python research/maxine-eye-contact-phase1b/run.py preflight --target <host:port>
```

Everything else clears automatically. `nim-endpoint-confirmed` will not: a TCP
connect cannot tell a live NIM from anything else listening on a port, and a
Phase 1B number produced against the wrong thing would be worse than no number.
Once you have seen the NIM serving, pass `--i-have-confirmed-nim-endpoint`.

## Step 4 — a Stage A source

A short H.264 MP4, 1280×720, ~30 FPS, constant frame rate, `moov` before `mdat`.
Variable frame rate is unsupported by the NIM.

NVIDIA ships a known-good one, but it is a Git LFS pointer in a plain clone:

```bash
git lfs install
git -C experiments/maxine-phase1b/nvidia-client lfs pull
# eye-contact/assets/sample_streamable.mp4  (~1.4 MB)
```

That asset is covered by the NVIDIA Maxine Sample Data License and is **not**
committed to this repository. Any other clip works if it is streamable:

```bash
ffmpeg -i input.mp4 -c:v libx264 -r 30 -movflags +faststart streamable.mp4
```

Stage A does not need Product Owner footage. It is a transport measurement, and
a synthetic or NVIDIA-supplied clip answers it without spending private footage
on a third-party service.

## Step 5 — run the stages in order

```powershell
python research/maxine-eye-contact-phase1b/run.py stage-a `
  --target <host:port> --source streamable.mp4 --i-have-confirmed-nim-endpoint
```

Read `determinations.usable_output_before_input_eos` in the printed summary.

- **`NO`** → `STOP — PHASE 1B FAIL CANDIDATE`. Do not run Stage B. Return the
  run directory to the Product Manager.
- **`YES`** → continue.

```powershell
python research/maxine-eye-contact-phase1b/run.py stage-b `
  --target <host:port> --source streamable.mp4 --i-have-confirmed-nim-endpoint
```

Read `determinations.maxine_consumed_live_generated_input`. If the NIM rejects
the progressively fragmented container, that is the Stage B kill condition:
record the server's error verbatim and stop. Do not invent another interface.

If both survive, Stage C is the same command against a camera, with the
low-latency muxer:

```powershell
python research/maxine-eye-contact-phase1b/run.py stage-b `
  --target <host:port> --frame-source camera --camera-backend dshow `
  --camera-device "video=<Your Camera Name>" --muxer inprocess `
  --width 1280 --height 720 --fps 30 --label stage-c `
  --i-have-confirmed-nim-endpoint
```

`ffmpeg -list_devices true -f dshow -i dummy` prints the exact device name.
Run Stage C on the target client — Windows 11, Intel i7-1165G7 / Iris Xe, no
NVIDIA GPU — so that "the client needs no NVIDIA hardware" is a measurement
rather than an assumption. The preflight records which it was.

## Step 6 — what to hand back

The whole `experiments/maxine-phase1b/<label>/` directory for each stage:
`summary.json`, `timeline.csv`, `frames.csv`, `backlog.csv`. Plus the values
this environment could not know — server GPU, driver, NIM image and tag, and the
network path — which appear in every summary as `NOT MEASURED` until someone
fills them in.

Corrected output video stays local unless the Product Owner decides otherwise;
the repository policy is that footage and model output are not committed.

## Two things worth deciding before spending time

**Privacy.** Stage C with a real camera sends live webcam frames to a
GazeFix-hosted NIM. That is a bounded experimental condition and it is exactly
the assumption the PRD's local-only requirement rules out for the product. The
PRD is not changed by this experiment; the conflict is reported, not resolved
here.

**Where the client-side floor sits.** The harness's own capture-to-sendable cost
was measured at ~6 ms per frame on the low-latency path and ~73 ms on the ffmpeg
path, on a four-core Linux VM. Measure it again on the real client — the
self-test prints it — before reading any frame age against the PRD's `<100 ms`.
