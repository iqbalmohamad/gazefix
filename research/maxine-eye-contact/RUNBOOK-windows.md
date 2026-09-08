# Phase 1A runbook — Windows, the three M3 clips

**`RESEARCH/EVALUATION ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

This runs the authorized Phase 1A flow on the Product Owner's machine, against
`speaking-smiling.mp4`, `minor-rotation.mp4` and `blink-wink-squint.mp4`.

It has to run there rather than in an engineering session because all three of
the things it needs live there: the footage, the `NVIDIA_API_KEY`, and a network
route to `grpc.nvcf.nvidia.com`. The remote engineering container has none of
them — its egress policy refuses every `nvidia.com` host outright.

Everything below has been exercised end to end on the tooling, including with a
space in the paths, except the successful NVIDIA response itself.

## Before you start

Read `README.md` §2–§4 for `ffmpeg`, NVIDIA's client, and the credential. Then
one thing that is not optional:

### Confirm the hosted endpoint is alive

Open <https://build.nvidia.com/nvidia/eyecontact/api> and check the model card
for a deprecation notice. Web search reported — from pages unreachable to the
engineering session — that this API carries **"deprecated on 07/27/2026"**,
which is now past. NVIDIA's own maintained client still documents the endpoint
and carries no deprecation language anywhere, so the two sources disagree and
only you can settle it.

If it is retired, stop. The status is
`MAXINE FEASIBILITY BLOCKED — HOSTED API UNAVAILABLE`, and substituting a
self-hosted NIM or another provider is not authorized. Record what you find
under `hosted_availability` in `manifests/nvidia-api-spec.json` either way.

While you are there, confirm the function id matches
`15c6f1a0-3843-4cde-b5bc-803a4966fbb6`. It is read from that JSON file, so a
correction needs no code change.

## The run

```powershell
cd <your gazefix checkout>

$Inputs = "C:\Users\Mohammad Iqbal\Downloads\PO_M3"
$Ws     = "experiments\maxine-phase1a"
$Seed   = "po-m3-2026-09-08"

# 0 - every precondition, at its true status
.venv\Scripts\python research\maxine-eye-contact\run.py preflight `
  --inputs $Inputs --workspace $Ws

# 1 - discover the clips and write an editable plan
.venv\Scripts\python research\maxine-eye-contact\run.py plan `
  --inputs $Inputs --workspace $Ws
```

**Stop and read the plan** at `experiments\maxine-phase1a\source-plan.json`.
It should list exactly three clips, `P1A-01`..`P1A-03`. If it lists anything
else, delete those entries — the assignment is these three clips only. Add a
`trim` window to any clip you want shortened, for example
`"trim": {"start_s": 2.0, "duration_s": 10.0}`. Five to fifteen seconds each is
the target.

```powershell
# 2 - freeze the held-out set. AFTER THIS, NO CLIP MAY BE ADDED OR REMOVED.
.venv\Scripts\python research\maxine-eye-contact\run.py freeze `
  --inputs $Inputs --workspace $Ws --strict-probe

# 3 - one derived input per clip, shared by BOTH conditions
.venv\Scripts\python research\maxine-eye-contact\run.py prepare `
  --inputs $Inputs --workspace $Ws

# 4 - the frozen M3 geometric baseline (GazeFix environment)
.venv\Scripts\python research\maxine-eye-contact\run.py geometric `
  --inputs $Inputs --workspace $Ws

# 5 - the hosted endpoint (SEPARATE environment; see README §3)
$env:NVIDIA_API_KEY = "<your key>"
.venv\Scripts\python research\maxine-eye-contact\run.py maxine `
  --inputs $Inputs --workspace $Ws `
  --python .venv-maxine\Scripts\python `
  --i-have-confirmed-availability

# 6 - the blind package
.venv\Scripts\python research\maxine-eye-contact\run.py package `
  --inputs $Inputs --workspace $Ws --seed $Seed

# 7 - integrity and secret scan
.venv\Scripts\python research\maxine-eye-contact\run.py verify `
  --inputs $Inputs --workspace $Ws
```

`--i-have-confirmed-availability` is your assertion that you did the check
above. It is the only gate the tooling cannot clear on its own.

`$Seed` was checked against these three clip ids and produces no weak blind. Any
seed works provided it is recorded before scoring; `package` refuses a seed that
would put one method under the same label in every clip and suggests another.

## Then score it

Open `experiments\maxine-phase1a\package\presentation\index.html`, score into
`scores.csv` beside it, and follow `scoring\rubric.md`.

**Do not open `package\answer-key\` until scoring is finished.** Nothing in the
presentation names a method; the answer key is the only way back.

## What to expect

**Three clips covering three of eight scenarios** — natural speaking, small head
movement, blink. Near-normal gaze, horizontal deviation, downward/read-like gaze
and glasses will all report `NOT AVAILABLE IN EXISTING SOURCE MATERIAL`, because
the other eight M3 captures are stills and Maxine is a temporal video model. The
manifest records this rather than papering over it. It is a real limit on what
the gate can establish, and it should be stated in whatever milestone record the
verdict goes into.

If a clip fails technically, the tooling logs the failure and will not silently
re-run it. Re-run one only for a genuine technical failure, with `--force`, and
never to fish for a better-looking result.

## If something goes wrong

`preflight` prints every precondition with its true status, and `verify` prints
the four integrity checks. Between them they name what is wrong. Two specifics
worth knowing:

- **NVIDIA's client exits 0 even when the request fails outright.** Measured:
  after a refused connection it returned code 0 and wrote nothing. The wrapper
  therefore ignores the exit code on its own and requires a non-empty output
  file with no error line on the client's output. A clip reported as `FAILED`
  with `no output file was written` is that case, and it is real.
- **`--streaming` is chosen from the file, not from preference.** Preprocessing
  puts every clip in the same faststart state so one frozen invocation mode
  covers them all.
