# Maxine Eye Contact — Phase 1A visual feasibility spike

**`RESEARCH/EVALUATION ONLY — NOT AUTHORIZED FOR GAZEFIX PRODUCTION`**

Bounded research tooling for the Product Manager's Phase 1A authorization
(`Current Assignment.md`, `docs/milestones/candidate-admission-closure.md`). It
prepares an unbiased, reproducible comparison so the Product Owner can answer
one question:

> Does NVIDIA Maxine Eye Contact produce eye-contact correction that is
> materially more natural than GazeFix's frozen geometric baseline, and good
> enough to want to use in a real video call?

`protocol.md` is the frozen experimental design and the authority on *why* each
step is shaped the way it is. This file is *how to run it*.

## Status of this package

The tooling is complete and tested. **It has not been executed.** Three
preconditions are missing from the engineering environment that built it, and
all three belong to the Product Owner's machine:

| Precondition | State | Why |
| --- | --- | --- |
| Product Owner footage | **absent here** | M3 captures are local and uncommitted by design (`docs/correction.md`: "PO imagery belongs only in ignored local experiment directories"). None exists in this container or in any branch's history. |
| `NVIDIA_API_KEY` | **absent here** | No NVIDIA credential is present, and none may be committed. |
| Network access to NVIDIA | **denied here** | Every `nvidia.com` host is refused by this container's egress policy (403 on CONNECT). Neither the documentation nor the endpoint is reachable. |

`ffmpeg`/`ffprobe`, and the product's own runtime dependencies (`opencv`,
`mediapipe`) needed to regenerate the geometric baseline, are also absent here
but present in the Product Owner's normal checkout.

Run `python research/maxine-eye-contact/run.py preflight` to see the current
state of every precondition on any machine.

## Isolation from the product

Nothing here imports `gazefix`, and nothing in `gazefix` imports this. No
product dependency manifest is touched: the package is standard library only
and shells out to `ffmpeg`/`ffprobe` and to NVIDIA's own client as external
tools. It changes no product code, no frozen behaviour and no frozen reference.

```text
research/maxine-eye-contact/
  README.md                     this file
  protocol.md                   the frozen experimental design
  run.py                        entry script
  eval/                         evaluation-only modules (stdlib only)
  manifests/nvidia-api-spec.json  recorded NVIDIA API evidence
  scoring/rubric.md             the Product Owner's scoring sheet
  tests/                        automated tests for this tooling
```

Run artifacts — footage, derived inputs, model outputs, the blind package — go
to the ignored `experiments/maxine-phase1a/`. Only manifests and hashes are
committed, matching the M3 convention.

## Setup

### 1. Footage

Place existing Product Owner clips in `experiments/inputs/`, using the M3
capture stems (`speaking-smiling.mp4`, `minor-rotation.mp4`,
`blink-wink-squint.mp4`, and any additional clips named for the condition they
show). This is the same directory `scripts/correction_batch.py po` already uses.

Read `protocol.md` §1 first: Maxine is a video model, the M3 set contains only
three clips, and the still-only scenarios will be reported as
`NOT AVAILABLE IN EXISTING SOURCE MATERIAL` unless clips exist for them.
Recording more clips is a Product Owner decision.

### 2. External tools

`ffmpeg` and `ffprobe` on `PATH`. On Windows, `winget install Gyan.FFmpeg` or
an equivalent build.

### 3. NVIDIA's client

Fetch NVIDIA's own Eye Contact client into the run workspace and compile its
protos. GazeFix wraps this client rather than reimplementing the protocol, so
the request sent is by construction the request NVIDIA defines.

```powershell
git clone https://github.com/NVIDIA-Maxine/nim-clients.git `
  experiments/maxine-phase1a/nvidia-client-repo
Copy-Item -Recurse experiments/maxine-phase1a/nvidia-client-repo/eye-contact `
  experiments/maxine-phase1a/nvidia-client
Copy-Item -Recurse experiments/maxine-phase1a/nvidia-client-repo/utils `
  experiments/maxine-phase1a/nvidia-client/utils

cd experiments/maxine-phase1a/nvidia-client
pip install -r requirements.txt          # grpcio, grpcio-tools, tqdm
cd protos/windows; ./compile_protos.bat  # or protos/linux/compile_protos.sh
```

Install NVIDIA's client dependencies into a **separate** virtual environment,
not the GazeFix product environment. They are evaluation tooling, not product
dependencies, and `pyproject.toml` must stay unchanged.

### 4. Credential

```powershell
$env:NVIDIA_API_KEY = "<your NVIDIA API key>"
```

Set it in the shell that runs the `maxine` step and nowhere else. **Never** put
it in a file inside this repository — not in source, config, Markdown, a
manifest, a log or a fixture. The key is passed to NVIDIA's client through the
child process environment, never on a command line, so it cannot appear in a
process listing or in any captured command. `run.py verify` scans every artifact
for credential-shaped content.

## Running

```powershell
python research/maxine-eye-contact/run.py preflight
python research/maxine-eye-contact/run.py plan
#   review experiments/maxine-phase1a/source-plan.json:
#   set trim windows and check the scenario tags, then
python research/maxine-eye-contact/run.py freeze      # the held-out set is now frozen
python research/maxine-eye-contact/run.py prepare
python research/maxine-eye-contact/run.py geometric
python research/maxine-eye-contact/run.py maxine
python research/maxine-eye-contact/run.py package --seed <recorded-seed>
python research/maxine-eye-contact/run.py verify
```

Then hand `experiments/maxine-phase1a/package/presentation/` to the Product
Owner with `scoring/rubric.md`, and keep the answer key closed until scoring is
finished.

`--workspace` and `--inputs` override the defaults and may be given on either
side of the command name.

### Before the `maxine` step: confirm the endpoint yourself

`preflight` reports `hosted-api-availability-confirmed` as `NOT VERIFIED` and
will not clear until a human confirms it. This is deliberate.

NVIDIA's actively maintained client (fetched 2026-09-07, hashes in
`manifests/nvidia-api-spec.json`) still documents the hosted preview API and
contains no deprecation language. Separately, web search reported — consistently
across three queries, but from pages that could not be fetched — that the
`build.nvidia.com` eyecontact model card carries **"This API will be deprecated
on 07/27/2026"**, a date now roughly six weeks past.

That contradiction could not be resolved from the environment that built this
package. **Open <https://build.nvidia.com/nvidia/eyecontact/api> and confirm the
hosted endpoint is live before spending footage on it.** Record what you find in
`manifests/nvidia-api-spec.json` under `hosted_availability`, then pass
`--i-have-confirmed-availability`.

If the hosted API is genuinely retired, the engineering status is
**`MAXINE FEASIBILITY BLOCKED — HOSTED API UNAVAILABLE`** and the path stops
there. Do not substitute a self-hosted NIM deployment or another provider;
neither is authorized.

Also confirm the function id while you are there. `manifests/nvidia-api-spec.json`
records `15c6f1a0-3843-4cde-b5bc-803a4966fbb6` from NVIDIA's client README, but a
different UUID was surfaced by search against a page that could not be fetched.
The value is read from the spec file, so correcting it needs no code change.

## Tests

```powershell
python -m pytest research/maxine-eye-contact/tests -q
```

These cover this tooling only, and require no network, no credential and no
NVIDIA service. They run separately from the product suite because the product
`pyproject.toml` restricts `testpaths` to `tests/`, and that file stays
unchanged.

Remote service availability is not a unit test, and there is no test here that
pretends otherwise.

## What this package will not do

No product runtime integration, no Maxine `CorrectionEngine`, no cloud
correction provider, no realtime streaming, no virtual camera, no M4, no
self-hosted NIM deployment, no GPU provisioning, no training or fine-tuning, no
alternative model or fallback, no vendor outreach, no LivePortrait in any role,
and no modification of frozen geometric behaviour, frozen architecture or any
frozen reference.

A Phase 1A `PASS` authorizes none of the above either. It only lets the Product
Manager consider a separate realtime/cloud feasibility stage.
