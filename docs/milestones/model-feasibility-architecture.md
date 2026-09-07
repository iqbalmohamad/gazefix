# Model-Feasibility Spike — Solution Architecture v1: LivePortrait eye-gaze retargeting reproduction

**Status:** DRAFT for focused adversarial review; freezes as
`model-feasibility-architecture-v1` on approval. Design only. This document
does not authorize integration of any model into GazeFix, does not begin M4,
and does not select a production correction architecture. It authorizes one
bounded, offline, CPU-only feasibility reproduction and defines how its
evidence is produced so that independent QA and the Product Owner can trust
it.

| Freeze record | Value |
| --- | --- |
| Canonical reference | branch `model-feasibility-architecture-v1` — filled at freeze |
| Baseline it compares against | branch `m3-geometric-baseline` @ `f3831b54728a4747c38c064351ec9f48419a2efb` — immutable |
| Governing assignment | `docs/milestones/model-feasibility-spike.md` (spike brief, activated 2026-09-07) |
| M3 gate it responds to | `docs/milestones/m3-evaluation.md` — `CHANGE APPROACH`; M3 is not `PASS`; M4 is not authorized |
| Research decision it implements | `REPRODUCE CANDIDATE NOW` — LivePortrait image retargeting via its official horizontal/vertical eye-gaze controls (ChatGPT + Kimi synthesis, cross-verified) |
| Written | 2026-09-07, Solution Architect / Principal ML Architect |
| Role of this document | invariants, boundaries, provenance, comparison methodology, stopping rules — not pixel-level implementation |

## 0. What this experiment is, in one paragraph

Take a pretrained, publicly released learned portrait renderer (LivePortrait),
run it unmodified on CPU, drive only its official eye-gaze retargeting
controls, and ask whether the corrected eyes it produces are materially more
natural and less distracting than GazeFix's frozen geometric baseline on the
same input images. The engineering deliverable is reproducible evidence; the
product answer comes from a blind Product Owner comparison afterwards. A
clean negative result is as valuable as a positive one, and a positive one
does **not** make LivePortrait the production engine.

## 1. Decisions

| # | Decision | Rationale | Section |
| --- | --- | --- | --- |
| D1 | **No change to `architecture.md` or any ADR.** The spike lives entirely outside `gazefix/`; the `CorrectionEngine` boundary, ADR-0002 and ADR-0003 are untouched | The frozen architecture already schedules "neural model choice … model licensing (ADR then)" for **adoption**, not evaluation; nothing durable is decided here | §3 |
| D2 | The candidate is exercised **through its own official pipeline entry point**, called programmatically; upstream code is never modified, forked or patched | The question is whether the *published* renderer is good enough; a modified renderer answers a different question and is out of timebox | §4, §8 |
| D3 | A separate top-level `spike/` tree holds the committed adapters, pins, plan and manifests; the upstream clone and weights are git-ignored inside it; all rendered pixels of Product Owner captures stay under the ignored `experiments/` tree | Nothing under `gazefix/`, `scripts/` or `tests/` may reference the spike; nothing private is ever committed | §4 |
| D4 | Two virtual environments, two worktrees: the spike venv (Python 3.10, CPU torch) never installs `gazefix`; the geometric baseline is regenerated from a worktree of `m3-geometric-baseline` in the project's own Windows venv | Different Python versions and dependency sets; and forcing data exchange through files makes the mapping auditable | §4, §11 |
| D5 | Every external artifact is pinned by revision **and** by SHA-256 recorded at reproduction time in a committed manifest; the adapter refuses to run if the clone, the weight files or the environment do not match the pins | No floating `main`, no `latest`, no unpinned wheel | §5 |
| D6 | Licensing is recorded as three separate lines — LivePortrait code (MIT, verified), LivePortrait weights (metadata unverified from the authoring environment), InsightFace `buffalo_l` models (non-commercial research only, verified from LivePortrait's own LICENSE) — and the spike is declared **research / internal evaluation only** | PRD §27 requires model licensing separately from code licensing and forbids treating a research-only model as production-ready without flagging it | §6 |
| D7 | CPU only, via the upstream's own `flag_force_cpu` and `flag_use_half_precision=False`; no CUDA, no ONNX/OpenVINO conversion, no `torch.compile` | Both are official configuration fields; anything else is upstream redesign and a stop condition | §5, §7 |
| D8 | Only `eyeball_direction_x` and `eyeball_direction_y` may be non-neutral; every other retargeting control is held at its neutral value and the eye-open/lip-open ratio retargeting is provably **not invoked** | Isolates the gaze-direction manipulation the research selected from the eye-open-ratio retargeting it must not be confused with | §8 |
| D9 | The upstream vertical control's built-in lid ("blink") coupling is used **as published** and recorded per run, not removed | Removing it is an upstream modification (D2); the PO judges eyelid preservation knowing it is there | §2, §8 |
| D10 | **Commanded-correction parity** with the baseline: for every image, LivePortrait attempts the same angular correction the frozen geometric baseline applied to that image (same source gaze from M2, same optical-axis target, same effective strength from the baseline's own policy record); calibration determines only the unit conversion from degrees to LivePortrait slider units — one gain, one sign and one clamp per axis | Fairness: both methods are asked to do the same thing; calibration cannot become per-image tuning because it has exactly six frozen values | §9, §11 |
| D11 | Calibration set = the public-domain astronaut fixture plus at most two Product Owner stills named in the committed plan **before any held-out render**; `lens-no-glasses` and `horizontal-no-glasses` are reserved as held-out anchors because the M3 gate scored exactly those two | Comparability with the M3 scores; separation is enforceable because the plan and the mapping are committed with their hashes before held-out runs | §9, §10 |
| D12 | Held-out images are rendered exactly once with the frozen mapping; every output is kept and reported, failures included; no re-renders, no parameter changes, no manual retouching | The no-cherry-picking guarantee is structural, not a promise | §9, §12 |
| D13 | The baseline comparison uses **deterministic regeneration** from `m3-geometric-baseline` with the PO-mode arguments the M3 gate used; pairing is by SHA-256 of the exact unmirrored input file the baseline consumed, which is also the file LivePortrait receives | The baseline is bit-reproducible (independent QA verified byte-identical determinism); the same bytes go to both methods | §11 |
| D14 | Independent QA verifies the evidence package before the Product Owner sees anything; the PO comparison is blind and randomized between the two methods on the same dimensions used for M3, plus one pairwise primary question | Engineering does not score visual quality; QA policy §9 budgets PO time, so the session is prepared, batched and short | §13, §14 |
| D15 | Maximum **two engineering days**; the stop conditions in §15 end the spike early with a report, never with a redesign | This is a feasibility spike, not a porting project | §15, §16 |

## 2. Verified facts about the candidate

Facts that materially affect the design were verified against the pinned
upstream revision by reading its source in the authoring environment. Items
that could not be verified from here are marked and become Codex's first
recording duty (§5). Verification levels follow PRD §25.

| Fact | Status | Where verified |
| --- | --- | --- |
| Upstream repository `KlingAIResearch/LivePortrait`; `KlingTeam/LivePortrait` resolves to the same commit (organisation rename with redirect) | VERIFIED — `git ls-remote` on both names returns `9b294b3d…` as HEAD | remote refs |
| Research-recommended code revision `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` is the upstream default-branch HEAD at authoring time and is fetchable | VERIFIED | clone + checkout |
| Code licence: MIT (Kuaishou Visual Generation and Interaction Center, 2024) | VERIFIED | `LICENSE` at the pinned revision |
| The same `LICENSE` file states: InsightFace *code* is MIT; InsightFace *models* are "for non-commercial research purposes only"; commercial use of LivePortrait requires removing and replacing InsightFace's detection models | VERIFIED | `LICENSE` at the pinned revision |
| InsightFace code is vendored under `src/utils/dependencies/insightface`; the `buffalo_l` model pack is loaded from `pretrained_weights/insightface` by the human cropper, with a 512×512 detector and its 106-point landmarks as the initial estimate; LivePortrait's own `landmark.onnx` refines them | VERIFIED | `src/utils/cropper.py`, `face_analysis_diy.py`, `src/config/crop_config.py` |
| The still-image gaze path is `GradioPipeline.execute_image_retargeting(...)` in `src/gradio_pipeline.py`; it is **not** exposed by the `inference.py` CLI. `init_retargeting_image(...)` must run first per image: it computes and stores `source_eye_ratio` / `source_lip_ratio` on the pipeline object | VERIFIED | `src/gradio_pipeline.py`, `app.py` wiring |
| `update_delta_new_eyeball_direction(x, y, delta)` edits implicit keypoints 11 and 15 (horizontal: asymmetric gains 0.0007/0.001 by sign; vertical: −0.001), **and adds a coupled lid term** `blink = −y/2` applied to keypoints 11, 13, 15, 16. The vertical gaze control therefore moves the lids by upstream design | VERIFIED | `src/gradio_pipeline.py` |
| Eye-open-ratio retargeting (`retarget_eye`, via `calc_combined_eye_ratio`) runs only when `input_eye_ratio != self.source_eye_ratio`; lip likewise. Passing back the exact values `init_retargeting_image` returned skips both | VERIFIED | `src/gradio_pipeline.py` |
| Official control ranges: horizontal `[−30, 30]`, vertical `[−63, 63]`, default 0, step 0.01; crop scale for image retargeting default **2.5** (range 1.8–3.2); `mov_z` default **1.0** is multiplicative; all other controls default 0 | VERIFIED | `app.py` slider definitions |
| Input handling: `load_img_online(max_dim=1280, n=2)` — a 1280×720 capture passes through unresized; output `out_to_ori_blend` is the full-frame paste-back at the input's size when crop is enabled | VERIFIED | `src/gradio_pipeline.py` |
| CPU: `flag_force_cpu` exists on `InferenceConfig`, `CropConfig` and the CLI `ArgumentConfig`; it selects `device='cpu'` in the wrapper and `CPUExecutionProvider` for the InsightFace and landmark ONNX sessions. Upstream annotates it "force cpu inference, WIP" | VERIFIED | `live_portrait_wrapper.py`, `cropper.py`, `argument_config.py` |
| Half precision: inference runs under `torch.autocast(device_type=device[:4], dtype=float16, enabled=flag_use_half_precision)`; the flag defaults to `True` and is an official field, so CPU runs must set it `False` | VERIFIED | `live_portrait_wrapper.py` |
| Model files the human path loads: `appearance_feature_extractor.pth`, `motion_extractor.pth`, `spade_generator.pth`, `warping_module.pth` (under `pretrained_weights/liveportrait/base_models/`), `stitching_retargeting_module.pth` (under `…/retargeting_models/`), `landmark.onnx` (under `pretrained_weights/liveportrait/`), **plus** the InsightFace `buffalo_l` pack under `pretrained_weights/insightface/models/buffalo_l/` — the research's six-file list omits the last item | VERIFIED | `inference_config.py`, `crop_config.py`, `cropper.py` |
| Upstream download instruction: `huggingface-cli download KlingTeam/LivePortrait --local-dir pretrained_weights …`; Google Drive / Baidu mirrors also offered | VERIFIED | `readme.md` |
| Dependencies: `requirements_base.txt` pins numpy 1.26.4, opencv-python 4.10.0.84, onnx 1.16.1, gradio 5.1.0, tyro 0.8.5 and others; `requirements.txt` adds `onnxruntime-gpu==1.18.0` and `transformers==4.38.0`; torch is installed separately (upstream: CUDA wheels 2.3.0; upstream's macOS file shows the CPU equivalent `torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0` from the CPU wheel index); upstream recommends Python 3.10 | VERIFIED | requirement files, `readme.md` |
| Model repository revision `6d116d1066c3539da1cea3189da91c46cb505584`, its file list, per-file hashes and the weight-licence metadata on the model card | **NOT VERIFIED** — `huggingface.co` is unreachable from the authoring environment (proxy 403). Codex records these at reproduction time (§5) | — |
| CPU inference time and memory on the target-class Windows laptop | **NOT MEASURED** — recorded by the spike | — |

## 3. Relationship to the frozen architecture

**Decision: `NO OVERALL ARCHITECTURE CHANGE REQUIRED`.**

- **PRD §15/§16/M9.** The PRD requires a stable, swappable correction
  interface, forbids training from scratch, and defines M9 as "evaluate
  whether an existing neural gaze-redirection model materially improves
  quality" with four adoption criteria (licence, latency, quality, hardware).
  This spike is M9's evaluation brought forward, as SA v1.3 §14.3 prescribed
  for a `CHANGE APPROACH` verdict; it tests the *quality* criterion first
  and records the other three honestly.
- **`architecture.md`, "Correction-engine replaceability and the neural
  boundary (M9)."** The frozen text already anticipates a neural engine
  behind the same seam, one adapter module as the only runtime importer,
  and "license recorded in an ADR before adoption"; it defers "neural model
  choice, ONNX provider/DirectML strategy, model licensing (ADR then)" to
  M9. Evaluation precedes adoption; nothing here is adoption.
- **ADR-0002.** Item 7 states neural engines plug in behind the
  `CorrectionEngine` protocol. The spike does **not** implement that
  protocol for LivePortrait — deliberately. An "adapter for convenience"
  would be the first step of integration, and integration is unauthorized
  until the visual feasibility gate is passed and the PM decides.
- **ADR-0003.** Concerns the real-time execution model and frame
  ownership. The spike is offline and touches no frame path.
- **Risks R8/R9** in `architecture.md` (neural licensing; ONNX Runtime
  beside MediaPipe under `numpy<2`) are exactly what §6 and §4's two-venv
  rule keep out of the product environment.

**What would change this decision.** If evidence shows the `CorrectionEngine`
contract itself cannot express what a learned renderer needs — for example,
a renderer that must own gaze estimation, or one that cannot return a full
frame with metadata-only results — that is an escalation to the PM with the
evidence, under `ARCHITECTURE ESCALATION REQUIRED`, not a silent edit. The
spike is not expected to produce such evidence, and is forbidden from
producing it by modifying `gazefix/`.

## 4. Repository and isolation strategy

### 4.1 Branches and worktrees

| Purpose | Reference | Rule |
| --- | --- | --- |
| Spike work | branch `codex/liveportrait-spike`, created from the freeze commit of this SA | the only branch that receives spike commits |
| Frozen baseline | `m3-geometric-baseline` @ `f3831b5…`, checked out as a **separate worktree** | never checked out into the spike branch's tree; never modified; regeneration runs from this worktree |
| This SA | `model-feasibility-architecture-v1` | frozen; amend only through a PM-authorized revision |
| All previously frozen refs | `main`, `milestone-0/1/2`, `architecture-v1`, `m3-architecture-v1/.1/.2/.3`, `m3-geometric-baseline` | untouched, verified before and after the spike |

### 4.2 Directory layout

```text
spike/liveportrait/                     committed — the only home of spike code
  README.md                             setup steps, environment, how to run each phase
  pins/
    upstream.json                       repo URL + revision, model repo + revision, expected
                                        file list with SHA-256 (filled at reproduction),
                                        interpreter/wheel pins, CPU flags
    requirements-cpu-windows.txt        the exact spike venv, pinned
  adapters/
    run_retarget.py                     programmatic driver of the upstream pipeline (§8)
    make_sheets.py                      native three-way and enlarged-eye sheets (§12)
    manifest.py                         hashing, environment capture, plan/pin verification
  plan/
    plan.json                           calibration / held-out split, control grid, seeds,
                                        and — after calibration — the frozen mapping
  evidence/
    <run-id>/manifest.json              committed run manifests: hashes, controls, timings,
                                        metadata — never Product Owner pixels
    fixture/                            rendered outputs of the public-domain fixture may be
                                        committed as the one visual example
  upstream/                             GIT-IGNORED: clone of the pinned revision, unmodified
    pretrained_weights/                 GIT-IGNORED: the pinned weights, upstream layout
experiments/liveportrait/<run-id>/      GIT-IGNORED: every rendered Product Owner image,
                                        every sheet, every intermediate
```

The upstream clone keeps its own layout so its hard-coded relative
checkpoint paths work without modification (D2). `spike/liveportrait/upstream/`
is added to `.gitignore` by this SA's freeze commit; `experiments/` is
already ignored.

### 4.3 Committed versus ignored

| Committed | Ignored, local only |
| --- | --- |
| adapters, pins, plan, run manifests, README, fixture renders | upstream clone, weights, spike venv, every Product Owner capture and every render or sheet derived from one, sealed randomization keys until the PO session is scored |

No webcam frame of the Product Owner enters the repository, in any form,
at any resolution — the standing policy since M3 is unchanged.

### 4.4 Contamination rules

- No file under `gazefix/`, `scripts/`, `tests/`, `pyproject.toml` or
  `constraints-windows-py312.txt` changes. The independent QA gate (§13)
  diffs these against the freeze commit.
- `spike/` never imports `gazefix`; the spike venv never installs it. The
  spike consumes the baseline's `report.json` / `frames.jsonl` as **data**
  (source gaze angles, effective strength, input hash).
- Nothing under `gazefix/` imports or references `spike/`.
- The upstream clone is read-only in effect: `git -C upstream status
  --porcelain` must be empty and `git -C upstream rev-parse HEAD` must
  equal the pin before every run; both are recorded in each manifest.
- The spike adds **no runtime dependency** to GazeFix. Everything in
  `requirements-cpu-windows.txt` is spike-local.

## 5. External artifact pinning and provenance

`spike/liveportrait/pins/upstream.json` is the single source of truth and the
adapter refuses to run when reality disagrees with it.

| Item | Pin | How verified at run time |
| --- | --- | --- |
| Code repository | `https://github.com/KlingAIResearch/LivePortrait` (note: `KlingTeam/LivePortrait` redirects to it) | recorded URL |
| Code revision | `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` | `git rev-parse HEAD` == pin; working tree clean |
| Model repository | `KlingTeam/LivePortrait` on Hugging Face | recorded |
| Model revision | `6d116d1066c3539da1cea3189da91c46cb505584` — downloaded with `--revision` set to exactly this | recorded; the download command is recorded verbatim |
| Weight files | the seven items in §2 (six LivePortrait files + the `buffalo_l` pack, every file in it) | SHA-256 of each file computed after download, written to the pin file **once** by the first reproduction, then enforced on every later run |
| Interpreter | CPython 3.10.x, exact patch recorded | `sys.version` recorded |
| Torch stack | `torch==2.3.0`, `torchvision==0.18.0`, `torchaudio==2.3.0` from the CPU wheel index | `torch.__version__`, `torch.version.cuda is None`, `torch.cuda.is_available() is False` recorded |
| ONNX Runtime | `onnxruntime==1.18.0` (CPU package; replaces upstream's `onnxruntime-gpu==1.18.0` at the same version) | `onnxruntime.get_available_providers()` recorded; must not contain CUDA |
| Everything else | `requirements_base.txt` verbatim plus `transformers==4.38.0`, then `pip freeze` captured into the manifest | freeze output recorded |
| CPU configuration | `flag_force_cpu=True`, `flag_use_half_precision=False`, `flag_do_torch_compile=False`, thread count recorded (`torch.get_num_threads()`) | recorded per run |
| Machine | OS build, CPU model, physical/logical cores, RAM, power plan if obtainable, whether the machine is the Product Owner's target laptop | recorded per run |

Rules:

1. No `main`, `latest`, or unpinned wheel anywhere. If a pinned wheel is not
   installable on the target machine, that is a §15 stop, not a reason to
   pick a nearby version silently.
2. The first reproduction **fills** the SHA-256 fields; that commit is the
   pin. If a later download produces different bytes, the run fails and the
   discrepancy is reported.
3. If the pinned model revision is unavailable, or the file list differs
   from §2, stop (§15) and report exactly what was found.
4. Hashes of the input images and of every output image are recorded per
   run (§12); the pin manifest's own SHA-256 is recorded in every run
   manifest, so a manifest can be tied to the exact pins it ran under.

## 6. Licensing boundary

This spike is **research / internal evaluation only**. Nothing in it implies
commercial clearance, and no result of it is shippable.

| Asset | Licence | Status for this spike | Status for any future production use |
| --- | --- | --- | --- |
| LivePortrait code | MIT — **verified** at the pinned revision | usable | compatible in itself; not a decision |
| LivePortrait weights (`.pth`, `landmark.onnx`) | model-card metadata **not verified** from the authoring environment | usable for internal evaluation; Codex records the model card's stated licence verbatim, with the revision, before any render | **unknown until recorded**; treated as unresolved |
| InsightFace `buffalo_l` models (detection + 106-point landmarks) — **exercised** by the human still-image crop path | **non-commercial research only** — verified in LivePortrait's own `LICENSE`, which says commercial use requires removing and replacing them | usable for internal evaluation | **not usable**; a production path would need a replacement detector/landmarker, which is itself a design and validation task |
| InsightFace code (vendored) | MIT — per the same `LICENSE` | usable | compatible |
| Product Owner captures | private; the Product Owner's own | local only | never committed, never shared |
| `tests/assets/astronaut_face.png` | public domain (NASA) — recorded in `tests/assets/README.md` | usable and committable | usable |

PRD §27 checklist, applied to the candidate as of this SA: active project
status — VERIFIED (recent upstream activity at the pinned revision); Windows
compatibility — NOT VERIFIED (upstream ships a Windows installer, but the CPU
path is annotated "WIP" upstream); Python/runtime compatibility — VERIFIED
by reading, NOT VERIFIED by execution; CPU compatibility — NOT VERIFIED,
the spike's first gate; licence — split as above; redistribution
restrictions — NOT VERIFIED for weights; model licensing separately from
code — recorded as above. "No research-only model may be treated as
production-ready without flagging the restriction": flagged.

## 7. Phase A — CPU-only official reproduction gate

The spike does not proceed past this phase until it passes. Nothing here
involves GazeFix.

1. Clone the pinned revision; install the pinned environment; download the
   pinned model revision; fill the SHA-256 pins (§5).
2. Run the upstream's **own** CLI example on the upstream's **own** example
   inputs with `--flag_force_cpu` and half precision disabled, unmodified.
   If the default example's driving clip is impractically slow on CPU, the
   upstream's own motion-template (`.pkl`) example is an acceptable
   official input. What must hold: official code, official inputs, official
   flags, no edits.
3. Record: wall time, peak memory if obtainable, output produced, and that
   `torch.cuda.is_available()` was `False` throughout.
4. Run the programmatic retargeting driver (§8) on an upstream example
   source image with **all controls neutral**; the paste-back output must
   be visually the input (record PSNR and max absolute difference against
   the input — an identity-like reconstruction is expected, not
   bit-equality).
5. Run the same with `eyeball_direction_x = +20` and separately `−20`; a
   visible horizontal gaze change in opposite directions must appear.

**Pass:** all five steps complete on CPU with no CUDA, no ONNX/OpenVINO
conversion, no upstream edit. **Stop (§15):** any step requires editing
upstream, a CUDA-only code path, or an unavailable pinned artifact — report
what blocked and where, and return to the PM. Do not redesign upstream. Do
not switch to another candidate.

## 8. Phase B — gaze-control validation

### 8.1 The neutral-control contract

The driver calls, per image and in this order: `init_retargeting_image(2.5,
…, image)` and then `execute_image_retargeting(...)` with:

| Control | Value | Why |
| --- | --- | --- |
| `input_eye_ratio`, `input_lip_ratio` | **exactly** the two values `init_retargeting_image` returned for this image | equality skips `retarget_eye` / `retarget_lip` (§2) |
| head pitch / yaw / roll variation | 0, 0, 0 | no head-pose editing |
| `mov_x`, `mov_y` | 0, 0 | no translation |
| `mov_z` | **1.0** | multiplicative scale; 0 would be wrong |
| lip variations 0–3, `smile`, `wink`, `eyebrow` | 0 | no expression editing |
| `eyeball_direction_x`, `eyeball_direction_y` | the only free controls, from the plan (§9) | the experiment |
| `retargeting_source_scale` | 2.5, the official image-retargeting default, fixed for the whole spike | not a tuning knob |
| `flag_stitching_retargeting_input` | `True` | upstream stitching intact |
| `flag_do_crop_input_retargeting_image` | `True` | upstream crop and paste-back intact |

Calling `init_retargeting_image` before **every** image is mandatory: the
source ratios are stored on the pipeline object, and a stale value from a
previous image would silently activate eye-open-ratio retargeting.

### 8.2 Required evidence, per run

1. **Direction.** On the astronaut fixture and each calibration still, a
   single-axis sweep (§9.2) must move the visible iris monotonically in the
   expected image direction for both eyes. Measurement is made two ways:
   a simple dark-pixel centroid inside each eye box (spike-local, no GazeFix
   code), and — the measure that matters to the product — GazeFix's own
   frozen M2 estimate of the rendered output, obtained by running the
   baseline harness on the LivePortrait output at strength 0 in the GazeFix
   venv (analysis only, no correction). Both readings are recorded.
2. **Eye-open-ratio retargeting not invoked.** The driver wraps
   `retarget_eye` and `retarget_lip` with counting spies for the duration of
   each run and records the counts, which must be zero, alongside the
   equality `input_eye_ratio == source_eye_ratio` and the ratio values.
3. **Upstream intact.** The manifest records the upstream commit, the clean
   working-tree check, and the two flags of §8.1 as `True`; the driver
   imports upstream modules and calls their public methods only.
4. **The coupled lid term is recorded, not hidden.** For every render the
   manifest records `eyeball_direction_y` and the derived `blink = −y/2`
   that upstream applies. The Product Owner's eyelid-preservation score
   therefore judges the official control as published (D9). If lid motion
   is the reason a result fails, that is a finding about the candidate, and
   any de-coupling experiment is a new PM decision, not a tweak.

## 9. Phase C — calibration versus held-out separation

### 9.1 Sets

| Set | Members | Codex may |
| --- | --- | --- |
| Calibration | `tests/assets/astronaut_face.png` (canvased to 1280×720 exactly as the M3 real-model test does) + at most two Product Owner stills named by stem in `plan.json` **before any held-out render**; `lens-no-glasses` and `horizontal-no-glasses` are ineligible (D11) | render freely, inspect, iterate on the grid and the mapping |
| Held-out | every other eligible still (§10) | render **once** each with the frozen mapping; inspect only after all are rendered; never re-render, retouch or change a control |

### 9.2 Control grid (fixed before calibration begins)

Single-axis sweeps on each calibration image, controls otherwise neutral:

- horizontal: `x ∈ {−20, −15, −10, −5, 0, 5, 10, 15, 20}`, `y = 0`;
- vertical: `y ∈ {−30, −20, −10, 0, 10, 20, 30}`, `x = 0`;
- four combined points `(±10, ±15)`.

These are well inside the official ranges (±30, ±63). Calibration may
**narrow** the usable range (a clamp) where artifacts appear; it may not
extend it or add off-grid points.

### 9.3 The frozen mapping

Commanded correction for an image is taken from the baseline's own record
for that image (D10): source gaze `(yaw_s, pitch_s)` from M2, target the
optical axis, effective strength `e` from the policy record, so the
commanded angular change is `Δyaw = −e·yaw_s`, `Δpitch = −e·pitch_s`
(degrees, camera frame). The mapping is:

```text
x = clamp( sx · gx · Δyaw,   −Xmax, +Xmax )
y = clamp( sy · gy · Δpitch, −Ymax, +Ymax )
```

with exactly six frozen values: two gains `gx, gy` (slider units per
degree), two signs `sx, sy ∈ {−1, +1}` determined from the direction
evidence of §8.2, and two clamps `Xmax ≤ 30`, `Ymax ≤ 63` chosen on the
calibration set. Gains are chosen so that, on the calibration images, M2's
reading of the rendered output moves toward the commanded gaze by an amount
comparable to what the geometric baseline achieved on the same image — the
same yardstick, not a beauty judgment. Once written to `plan.json` with the
plan's SHA-256 recorded, the mapping is frozen; every held-out manifest
records that hash, so QA can prove the held-out renders used the frozen
mapping and nothing else.

If no gain reproduces the commanded correction direction on all
calibration images, that is a §15 stop with evidence, not a reason to
invent per-image values.

### 9.4 What is forbidden after the freeze

Changing any of the six values; re-rendering a held-out image for any
reason other than a reproducibility check (§12, which must produce the same
bytes); choosing which outputs to show; retouching, cropping, colour or
sharpness adjustment of any output; substituting a different input file
for a stem. The randomization key for the PO session (§14) is generated
from a seed recorded in `plan.json` before rendering.

## 10. Inputs — Product Owner capture selection

Use the existing M3 captures wherever suitable; never fabricate coverage.

| Condition required | Source in the existing M3 capture set | If missing |
| --- | --- | --- |
| horizontal gaze offset | `horizontal-no-glasses`, `horizontal-glasses` | record gap |
| vertical gaze offset | `notes-no-glasses`, `notes-glasses` (down), `screen-*` (small) | record gap |
| moderate offset in range | any still whose M2 deviation is 10–20° per the baseline record | record which stills fall outside |
| direct / null case | `lens-no-glasses`, `lens-glasses` | — |
| modest head pose | one or two frames extracted from `minor-rotation.mp4` at recorded timestamps | record gap |
| visible sclera, open eyes | every still; recorded per image from the baseline's per-eye status | — |
| glasses | the four `*-glasses` stems | record gap |
| stress / near-blink | one or two frames from `blink-wink-squint.mp4` at recorded timestamps, eyes partly open | record gap |

Objective rules: an eligible image is one the frozen baseline **corrected**
(both eyes `CORRECTED` in its record) — an image the baseline skipped cannot
be compared and is listed as excluded with the baseline's reason. Frames
extracted from clips are extracted once, by frame index, with the index and
the extracted file's SHA-256 recorded; the extracted still is then treated
like any other input. Target count is 12–16 eligible stills including the
calibration ones; if the existing captures yield fewer, report the number
and the uncovered conditions rather than reusing an image twice. The
Product Owner is asked for new captures only through the PM, batched, and
only if the PM decides the gaps matter.

Mirroring: the baseline consumed each capture unmirrored (with `--unmirror`
if the session was mirrored). LivePortrait receives the baseline run's
`original.png` for that stem — the exact bytes the baseline corrected — so
orientation, size and content are identical on both sides (D13).

## 11. Frozen geometric comparison

**Deterministic regeneration is authoritative.** Existing local M3 renders
are not reused; the baseline is regenerated from a worktree of
`m3-geometric-baseline` @ `f3831b5…` in the project's Windows venv with the
PO-mode invocation the M3 gate used: default variant C, default settings,
policy on, requested strength `.7`, optical-axis target, no smoothing,
`--debug`, `--unmirror` only if the session was mirrored — i.e.
`python -m scripts.correction_batch po --inputs experiments/inputs`. Its
`batch.json` / per-stem `report.json` supply the input SHA-256, the M2
source gaze, the policy's effective strength and the per-eye status that
§9.3 and §10 consume.

Rules: no setting, constant, variant or strength is changed for this
comparison; the baseline branch is never modified; the regeneration's
repository provenance (`head`, `tracked_changes: false`) is recorded in the
spike manifest; pairing is by the SHA-256 of `original.png`, which must
equal the SHA-256 of the file LivePortrait consumed. A mismatch voids the
pair.

## 12. Evidence output

Per evaluated image, under `experiments/liveportrait/<run-id>/<stem>/`:

| Artifact | Content |
| --- | --- |
| `original.png` | the shared input (SHA-256 recorded; equals the baseline's) |
| `geometric.png` | the regenerated baseline output (SHA-256 recorded) |
| `liveportrait.png` | the LivePortrait paste-back output at native size (SHA-256 recorded) |
| `three_way.png` | original / geometric / LivePortrait side by side at **native scale**, labelled only by neutral letters when destined for the PO |
| `eyes_3x.png` | the same three, eye region enlarged 3× with nearest-neighbour or a recorded filter, identical crop box for all three |
| `crop_meta.json` | upstream crop box, `M_c2o`, source landmark count, crop scale 2.5, stitching and paste-back flags |
| `timing.json` | raw model timing per stage (crop + landmarks, motion extraction, warp + decode, paste-back) and total offline wall time for the image, plus per-stage timing of the baseline from its own report |

Per run, `spike/liveportrait/evidence/<run-id>/manifest.json` (committed):
run id; pin-file SHA-256; plan SHA-256 and whether the run was calibration
or held-out; upstream commit and clean-tree check; model file hashes;
environment capture (§5); machine metadata; per image: stem, input hash,
output hashes, control values `(x, y)`, derived `blink`, source ratios and
the zero spy counts, commanded correction `(Δyaw, Δpitch)`, M2 reading of
both outputs, timings, and status (`RENDERED` / `FAILED: <reason>`).

**What the design lets independent QA prove:** no cherry-picking (every
held-out stem in the plan appears exactly once, `FAILED` included, and the
manifest count equals the plan count); calibration/held-out separation (the
plan hash in every held-out manifest predates and equals the frozen plan;
calibration manifests may differ, held-out ones may not); correct upstream
model (commit, clean tree and file hashes match the pins); correct baseline
pairing (input hashes equal on both sides and the baseline provenance is
the frozen SHA); reproducibility (one held-out image re-rendered from the
manifest yields the same output hash, or the recorded deviation).

## 13. Independent QA gate — before the Product Owner sees anything

Risk level: **HIGH** under QA policy §3 (model and licence uncertainty).
The gate is targeted, not a recertification; it verifies, in this order,
and stops when done:

1. contamination (§4.4): the product diff is empty; `spike/` imports no
   `gazefix`; the spike venv has no `gazefix`;
2. pins (§5): upstream commit and clean tree; every weight hash; environment
   capture; `cuda.is_available() is False`; providers contain no CUDA;
3. control isolation (§8): spy counts zero, ratio equality, neutral
   controls, flags `True`, `blink` recorded;
4. separation and completeness (§9, §12): plan hash chain; held-out count;
   no re-render; `FAILED` cases present, not dropped;
5. pairing (§11): input-hash equality per stem; baseline provenance;
6. reproducibility (§12): one held-out re-render;
7. sheet integrity: each `three_way.png` and `eyes_3x.png` decodes back to
   the three recorded images (crops identical, no post-processing).

QA does not score visual quality and does not debug the candidate (QA
policy §7). Outcome vocabulary: `SPIKE EVIDENCE VERIFIED — READY FOR PO
COMPARISON`, `SPIKE EVIDENCE CHANGES REQUIRED`, `SPIKE EVIDENCE BLOCKED`.

## 14. Product Owner comparison design

Engineering does not score visual quality. The comparison is prepared as a
single, short, batched session (QA policy §9); the PM authorizes its length
before it runs.

- **Blind and randomized.** For every held-out image the PO sees the
  original and two corrected results labelled **A** and **B**; which is
  geometric and which is LivePortrait is assigned per image from the
  plan's recorded seed. The key is sealed (kept by the engineer, its
  SHA-256 committed before the session) and revealed only after the PO's
  sheet is returned. Sheets carry no method names, file names or control
  values.
- **Dimensions.** The same scale and dimensions the M3 gate used, per
  result: eye realism, iris realism, eyelid preservation, identity
  preservation, artifact visibility, perceived eye contact, 1–5; blink
  realism N/A on stills; and the key criterion per result — "is this
  correction less distracting than the original lack of eye contact?"
  yes/no.
- **Primary pairwise question**, per image: "Is one result clearly more
  natural and less distracting than the other? A / B / neither."
- **Budget.** Roughly one minute per image; at 12–16 images, 12–20 minutes
  — above the policy's typical 5–10, so the PM authorizes it explicitly.
  One session; no exploratory tuning; no second round without a PM
  decision.
- **Verdict reading.** LivePortrait is "materially more natural" only if
  the PO chooses it on the pairwise question for a clear majority of
  held-out images **and** answers yes to its key criterion on a clear
  majority, with no disqualifying artifact class of its own. Lid motion
  from the coupled term (D9) is scored under eyelid preservation like any
  other effect. No aggregate numeric pass score is computed (PM-ratified
  M3 rule, unchanged).
- **After unblinding**, the results are recorded per image with the
  method revealed, alongside the manifest hashes, in
  `docs/milestones/model-feasibility-evaluation.md`.

## 15. Success, stop and escalation criteria

**Engineering reproduction success is not product success.** Phases A–C
succeeding means the evidence exists; only §14 answers the product
question.

Codex **stops and returns to the PM** — with a written report of what was
established and what blocked — if any of these occurs:

1. the pinned code or model revision is unavailable, or the model file list
   or hashes disagree with what a second download produces;
2. CPU-only inference requires editing upstream, a CUDA-only path, or a
   conversion step (ONNX/OpenVINO/other);
3. any step requires training, fine-tuning, or hidden learned adaptation;
4. the gaze-direction manipulation cannot be reproduced: the neutral run is
   not identity-like, the direction sweep is not monotonic in the expected
   direction for both eyes on the calibration set, or no frozen gain
   reproduces the commanded direction;
5. the existing Product Owner captures are fundamentally incompatible
   (e.g. no face detected by the upstream cropper on most stills, or fewer
   than six eligible stills);
6. deterministic reproduction fails: a re-render of the same manifest
   differs visibly at normal viewing size;
7. the two-engineering-day timebox would be exceeded to complete Phase C.

On a stop, the report states which condition fired, the evidence, and what
it would cost to remove the blocker. Codex does **not** move to ST-ED or any
other candidate, does not modify upstream, and does not widen the timebox;
the PM decides.

## 16. Timebox

**Maximum two engineering days**, counted from environment setup to the
handoff of the QA-ready evidence package. Indicative split: Phase A up to
half a day; Phase B and calibration up to one day; held-out renders,
sheets, manifests and the report the remainder. The Product Owner session
and independent QA are outside the timebox. CPU render time is part of the
budget: if per-image time on the target machine makes the held-out set
infeasible within it, reduce the held-out count (recording which stems were
dropped and why, chosen by the plan's seed, not by inspection) rather than
skip calibration or evidence steps — and if even the minimum of six is
infeasible, stop (§15.7).

## 17. Future architecture implications — documented, not implemented

**If the visual result fails** (§14 not met): LivePortrait is rejected as a
candidate and recorded as such with its evidence; the PM decides whether to
reproduce ST-ED next under a new, equally bounded spike SA. The geometric
baseline remains the reference. Nothing in the architecture changes.

**If the visual result succeeds:** LivePortrait is **not** integrated and M4
is **not** started. The result establishes that a learned renderer can
clear the product bar on stills, which reframes the next architecture
question as one of the following, for the PM to choose between:

1. obtaining a **smaller, licensable, CPU-feasible** learned correction
   engine — the current candidate carries a non-commercial detector
   dependency, a research-grade CPU path, and an unmeasured latency;
2. using LivePortrait as a **teacher or reference** for such an engine, or
   as an offline quality oracle for evaluating one;
3. whether a still-image result transfers to video at all — temporal
   stability, blink behaviour and latency are unmeasured by this spike and
   are M4/M7-class questions.

In every branch the provider-neutral `CorrectionEngine` stays unchanged.
Adoption of any learned engine would follow the frozen `architecture.md`
pattern — one adapter module, manifest and checksum, explicit fetch,
offline runtime, and a licence recorded in an ADR **before** adoption —
with a milestone SA of its own.

## 18. Open items carried into the spike

| Item | Owner | When |
| --- | --- | --- |
| Model-card licence text for the LivePortrait weights at the pinned revision | Codex records verbatim | before any render |
| Weight file hashes (all seven items) | Codex fills the pin file | first reproduction |
| Python 3.10 availability on the Product Owner's machine (the product uses 3.12); spike venv creation | Codex | setup |
| CPU render time and memory on the target-class machine | Codex measures | Phase A/C |
| Whether upstream's "WIP" CPU path runs the still-image retargeting cleanly | Codex — Phase A decides | Phase A |
| Whether the coupled lid term of the vertical control is acceptable | PO judges, PM decides | §14 |

## 19. Handoff — what Codex must not redesign

Fixed by this SA: the isolation layout and contamination rules (§4); the
pin set and the refusal-to-run rule (§5); the licensing statements (§6);
the CPU flags and the no-conversion rule (§7); the neutral-control contract
and the four evidence items (§8); the sets, grid, six-value mapping and
post-freeze prohibitions (§9); the eligibility rules and pairing bytes
(§10–§11); the artifact and manifest contents (§12); the QA gate order and
the blind PO design (§13–§14); the stop list and the timebox (§15–§16).

Left to the implementor: script structure and naming inside `spike/`;
how sheets are laid out beyond the rules given; how spies and hashing are
implemented; the choice of frame indices from the two clips (recorded);
the two calibration stems (recorded before held-out runs); and the
narrowing clamps.
