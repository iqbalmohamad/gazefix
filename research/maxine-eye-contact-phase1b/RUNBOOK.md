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
committed to this repository.

**The clip must contain a clearly visible, roughly front-facing human face for
its whole duration.** Eye Contact is a gaze-redirection model: with no face
there is nothing for it to redirect, and what it does then — error, stall, or
pass the frames through — is unknown and would be indistinguishable from a
streaming failure. A synthetic pattern such as `testsrc2` is valid **only** for
the mock self-test, never for a run against the NIM.

Any other clip works if it is streamable, H.264, constant frame rate, and has a
face:

```bash
ffmpeg -i input.mp4 -c:v libx264 -r 30 -pix_fmt yuv420p -movflags +faststart streamable.mp4
```

Stage A does not need Product Owner footage specifically — it is a transport
measurement, and NVIDIA's own sample answers it without spending private footage
on a third-party service — but it does need a face.

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

---

# Running against the live NIM on the GCP VM

**The NIM is now provisioned** (Eye Contact 1.4.0, L4, gRPC 8001, health
`SERVING`), so the blocker above is cleared. This section is the exact sequence
for that host, and supersedes the generic steps above where they differ.

Run these **on the GCP VM itself**, targeting `localhost:8001`. That is
deliberate: Stages A and B are protocol and streaming-semantics experiments, not
network-latency experiments, and running locally removes internet noise and
avoids exposing the gRPC endpoint. **Local timings from Stage A and B are not
representative Windows-to-cloud latency** and must never be quoted as such —
that is Stage C, which is separately authorized and not run yet.

## 1. Get the harness onto the VM

```bash
git clone --branch claude/maxine-phase-1b-runtime-p6ukkc \
  https://github.com/iqbalmohamad/gazefix.git ~/gazefix
cd ~/gazefix
git log --oneline -1          # confirm you are on the Phase 1B experiment commit
```

Do not create a branch for execution; run from this one.

## 2. Dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3-venv ffmpeg git-lfs

python3 -m venv .venv-maxine1b
.venv-maxine1b/bin/pip install --upgrade pip
.venv-maxine1b/bin/pip install grpcio grpcio-tools
```

`ffmpeg` **and** `ffprobe` are both required and both come from the `ffmpeg`
package. PyAV is **not** needed: it is only for `--muxer inprocess`, which
Stages A and B do not use. Python 3.9+ suffices; 3.11 is what the harness was
developed and tested on.

## 3. NVIDIA's service contract

The harness compiles and imports NVIDIA's own `.proto` rather than restating the
protocol, and refuses to run without it.

```bash
git clone https://github.com/NVIDIA-Maxine/nim-clients.git \
  experiments/maxine-phase1b/nvidia-client
```

Keep the clone intact; protos are compiled automatically on first use.

## 4. The Stage A source

Use **NVIDIA's own sample**. It is their known-good streamable asset for this
exact NIM, it contains a face — which a gaze-redirection model needs, and which
a synthetic test pattern does not have — and it removes the source as a
variable. **Do not substitute a synthetic clip:** with no face there is nothing
to redirect, and whatever the NIM does then would be indistinguishable from a
streaming failure.
It ships as a Git LFS pointer, so it must be fetched:

```bash
cd experiments/maxine-phase1b/nvidia-client
git lfs install
git lfs pull --include="eye-contact/assets/*"
cd ~/gazefix
ls -l experiments/maxine-phase1b/nvidia-client/eye-contact/assets/
# sample_streamable.mp4 should now be ~1.4 MB, not 132 bytes
```

If it is still 132 bytes the harness will say so by name rather than failing
obscurely. Its resolution and frame rate are recorded in the run summary; the
harness warns if they are not 1280x720, which does not invalidate Stage A's
transport question but should be read alongside the result.

## 5. Preflight

```bash
.venv-maxine1b/bin/python research/maxine-eye-contact-phase1b/run.py \
  preflight --target localhost:8001
```

Expect `PREFLIGHT CLEAR` once `--i-have-confirmed-nim-endpoint` is added.
`nim-endpoint-confirmed` never clears on its own — a TCP connect cannot tell a
live NIM from anything else on the port, and the health check you already ran is
the human confirmation it is asking for.

If `target-tcp-reachable` fails, the NIM's port is not published to the host;
that is a Docker networking issue, not a Maxine result.

## 6. Stage A

```bash
.venv-maxine1b/bin/python research/maxine-eye-contact-phase1b/run.py stage-a \
  --target localhost:8001 \
  --source experiments/maxine-phase1b/nvidia-client/eye-contact/assets/sample_streamable.mp4 \
  --i-have-confirmed-nim-endpoint \
  --label stage-a-real-nim
```

Then read `determinations.usable_output_before_input_eos` in
`experiments/maxine-phase1b/stage-a-real-nim/summary.json`.

## 7. Stage B — only if Stage A said YES

```bash
.venv-maxine1b/bin/python research/maxine-eye-contact-phase1b/run.py stage-b \
  --target localhost:8001 \
  --source experiments/maxine-phase1b/nvidia-client/eye-contact/assets/sample_streamable.mp4 \
  --i-have-confirmed-nim-endpoint \
  --label stage-b-real-nim
```

**Stop after Stage B.** Stage C is the representative Windows-to-cloud
experiment and is separately authorized.

## 8. Reading the result before drawing a conclusion

Check `failure_attribution.blame` **first**. It exists so that a verdict lands
on the right thing.

| What the summary says | What it means | What to do |
| --- | --- | --- |
| `blame: NONE`, `before_eos: YES` | Corrected frames were usable while input was still being sent | Stage A passes; run Stage B |
| `blame: NONE`, `before_eos: NO`, `decode_corroboration.status: VERIFIED`, scope `complete output` | The NIM produced valid corrected video but only as a whole file | A genuine streaming FAIL candidate. The correction itself worked — say so |
| `blame: NONE`, `before_eos: NO`, decode `FAILED` | Nothing usable **and** the output does not decode | Not a service verdict. Check the source and the NIM log, then repeat |
| `blame: SERVER — ... status X`, `before_eos: NOT MEASURED` | The call failed; the streaming question was never answered | Read `grpc_details`. `RESOURCE_EXHAUSTED` → retry; `INVALID_ARGUMENT` → the NIM rejected the input |
| `blame: HARNESS — ... deadline` | Our own `--rpc-timeout` fired | Re-run with a larger `--rpc-timeout` |
| `blame: HARNESS PARSER` | Transport worked, our indexer did not | The full output is saved; analyse it offline. Not a service failure |
| `blame: CLIENT/HARNESS` | Our own sender failed before the server answered | Not a service result; read `failure_attribution.sender_error` |
| `blame: OPERATOR` | Interrupted | Not a result |
| `kill_condition_3_whole_file_interface: NOT MEASURED` | This harness could not classify the response container | **Not** a streaming verdict. The full output is saved — analyse it offline |

Two integrity fields decide whether the latency numbers mean anything:

- `frame_age.age_coverage` — how many corrected frames an age could be computed
  for. A p50 over a fraction of the stream is not the stream's p50.
- `determinations.output_input_frame_correspondence` — every age assumes
  corrected frame *n* corrects source frame *n*. If this says `MISMATCH` or
  `BROKEN`, the ages are unreliable and should not be quoted.

## 9. If Stage B's container is rejected

If the NIM answers `INVALID_ARGUMENT` on Stage B, it is rejecting the
progressively-delivered fragmented MP4. Before concluding, try in this order —
each is a different container shape, not a different API:

```bash
# coarser fragmentation: one fragment per keyframe instead of per frame
... run.py stage-b ... --frag-keyframe --label stage-b-fragkey

# a different muxer writing the same fragmented layout (needs: pip install av)
... run.py stage-b ... --muxer inprocess --label stage-b-inprocess
```

Then vary the **bitstream**, which is a different variable from the container:

```bash
# High profile is the default; ultrafast would emit Constrained Baseline
... run.py stage-b ... --x264-preset veryfast --label stage-b-veryfast
```

That fourth attempt matters. Stage A sends NVIDIA's own file, so if Stage B is
refused for a reason to do with the coded stream rather than the container, the
first three attempts would all carry the same bitstream and the refusal would be
recorded against the wrong variable.

If all four are rejected with the same status, that is the Stage B kill
condition. Record the server's status and details verbatim — the harness already
captures both — and stop. Do not invent another NVIDIA API.

**Before recording any Stage B result, check two fields.**
`live_production.frames_captured` must be non-zero — a run that produced no
frames is refused outright now, but if it ever reads zero the answer is about
the source, not the service. And `live_production.frame_source_error` must be
empty; if it is not, ffmpeg could not decode the clip and nothing about the NIM
was measured.

## 10. What to hand back

```bash
tar czf phase1b-real-nim.tgz experiments/maxine-phase1b/stage-*-real-nim
```

Each run directory holds `summary.json`, `timeline.csv`, `frames.csv`,
`backlog.csv` and the corrected output. The corrected `.mp4` need not be shared
if the PO prefers not to; everything load-bearing is in `summary.json`.

Also record what only the VM knows, which every summary currently carries as
`NOT MEASURED`: server GPU, driver, NIM image and digest, and the network path.
