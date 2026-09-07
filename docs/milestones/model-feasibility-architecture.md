# Model-Feasibility Spike — Solution Architecture v1: LivePortrait eye-gaze retargeting reproduction

**Status:** **APPROVED / FROZEN** as `model-feasibility-architecture-v1` after a
focused adversarial review (eight lenses, two refuters per finding, one
completeness critic: 43 lens findings confirmed at 6 MEDIUM / 37 LOW and 8
completeness gaps at 1 HIGH / 6 MEDIUM / 1 LOW, no BLOCKER; a four-way
verification pass on the revision; every item applied, or listed with its
reason in §21). Design only.
This document does not authorize integration of any model into GazeFix, does
not begin M4, and does not select a production correction architecture. It
authorizes one bounded, offline, CPU-only feasibility reproduction and
defines how its evidence is produced so that independent QA and the Product
Owner can trust it.

| Freeze record | Value |
| --- | --- |
| Canonical reference | branch **`model-feasibility-architecture-v1`** — this commit |
| Baseline it compares against | branch `m3-geometric-baseline` @ `f3831b54728a4747c38c064351ec9f48419a2efb` — immutable |
| Governing assignment | `docs/milestones/model-feasibility-spike.md` (spike brief, activated 2026-09-07) |
| M3 gate it responds to | `docs/milestones/m3-evaluation.md` — `CHANGE APPROACH`; M3 is not `PASS`; M4 is not authorized |
| Research decision it implements | `REPRODUCE CANDIDATE NOW` — LivePortrait image retargeting via its official horizontal/vertical eye-gaze controls. The Product Manager made the decision on the synthesis of independent ChatGPT and Kimi research and communicated it in the SA assignment of 2026-09-07, outside the repository. **This freeze record is the repository's record of that decision.** The commit that follows this freeze rewrites `Current Assignment.md` to restate it and to point Codex at this SA, the single branch `codex/liveportrait-spike`, the code-producing `spike/` deliverable and the two-day timebox; until that commit lands, the pointer file still carries the broader scouting brief |
| QA risk level for §13 | **HIGH, proposed by this SA** under QA policy §3 (model and licence uncertainty); the PM confirms or changes it in the assignment pointer, which records the confirmed level. Codex treats the level as HIGH until the pointer says otherwise |
| Independent reviewer for §13 | commissioned by the PM in the assignment pointer, or none — in which case the engineer runs the §13 list and reports each item at its true verification level |
| Brief criterion 3, knowingly deferred | The brief calls research-only or unspecified licence terms disqualifying. The PM proceeds anyway because the spike answers the *quality* question first and §17 names the licensable-engine and teacher/reference paths that a positive answer would open. LivePortrait as shipped **fails criterion 3 for production** (§6) |
| Written / reviewed | 2026-09-07, Solution Architect / Principal ML Architect |
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
| D2 | The candidate is exercised **through its own official pipeline entry points**, called programmatically; upstream source is never modified, forked or patched. The only permitted instrumentation is wrapping public methods on the live pipeline objects (§8.3) | The question is whether the *published* renderer is good enough; a modified renderer answers a different question and is out of timebox | §4, §8 |
| D3 | A separate top-level `spike/` tree holds the committed adapters, pins, plan and manifests; the upstream clone, weights and spike venv are git-ignored inside it; all rendered pixels of Product Owner captures stay under the ignored `experiments/` tree | Nothing under `gazefix/`, `scripts/` or `tests/` may reference the spike; nothing private is ever committed | §4 |
| D4 | Two virtual environments, two worktrees: the spike venv (Python 3.10, CPU torch) never installs `gazefix`; the geometric baseline is regenerated from a worktree of `m3-geometric-baseline` in the project's own Windows venv; data crosses between them as files only | Different Python versions and dependency sets; and forcing data exchange through files makes the mapping auditable | §4, §11 |
| D5 | Every external artifact is pinned by revision **and** by SHA-256, cross-checked against the publisher's own hash where one exists, then sealed in a committed manifest; the adapter refuses to run if the clone, the weight files or the environment do not match the pins | No floating `main`, no `latest`, no unpinned wheel, no hidden download | §5 |
| D6 | Licensing is recorded as separate lines — LivePortrait code (MIT, verified), LivePortrait weights (model-card terms recorded at reproduction), InsightFace `buffalo_l` models (non-commercial research only, verified from LivePortrait's own LICENSE) — and the spike is declared **research / internal evaluation only** | PRD §27 requires model licensing separately from code licensing and forbids treating a research-only model as production-ready without flagging it | §6 |
| D7 | CPU only: the torch stack is routed by the upstream's own `flag_force_cpu` with `flag_use_half_precision=False`; the ONNX sessions land on CPU because the pinned CPU-only ONNX Runtime has no CUDA provider (§2, §7 step 2). No CUDA, no ONNX/OpenVINO conversion, no `torch.compile` | Both flags are official configuration fields; the provider fallback is documented upstream behaviour of the pinned wheel; anything else is upstream redesign and a stop condition | §5, §7 |
| D8 | Only `eyeball_direction_x` and `eyeball_direction_y` may be non-neutral; every other retargeting control is held at its neutral value and the eye-open/lip-open ratio retargeting is provably **not invoked** | Isolates the gaze-direction manipulation the research selected from the eye-open-ratio retargeting it must not be confused with | §8 |
| D9 | The upstream vertical control's built-in lid ("blink") coupling is used **as published** and recorded per run, not removed | Removing it is an upstream modification (D2); the PO judges eyelid preservation knowing it is there | §2, §8 |
| D10 | **Commanded-correction parity** with the baseline: for every image, LivePortrait attempts the same angular correction the frozen geometric baseline applied to that image (same source gaze from M2, same optical-axis target, same effective strength from the baseline's own policy record); calibration determines only the unit conversion from degrees to LivePortrait slider units — one gain, one sign and one clamp per axis — by a fit rule fixed in §9.3 | Fairness: both methods are asked to do the same thing; calibration cannot become per-image tuning because it has exactly six frozen values and a stated fit rule | §9, §11 |
| D11 | Calibration set = the public-domain astronaut fixture (sign and monotonicity evidence only) plus the two Product Owner stills `lens-glasses` and `screen-glasses` (gain fitting), fixed here at freeze; `lens-no-glasses` and `horizontal-no-glasses` are held-out anchors because the M3 gate scored exactly those two, and all four in-range stills stay held-out | Comparability with the M3 scores; the in-range held-out set is preserved; separation is enforceable because the plan is committed and pushed with PM acknowledgement before held-out renders | §9, §10 |
| D12 | Held-out images are rendered exactly once with the frozen mapping in the plan's stratified seed order; every output is kept and reported, failures included; no re-renders, no parameter changes, no manual retouching | Completeness, the frozen pushed mapping, the recomputable controls and the reproducibility check are structural guarantees; the absence of a pre-freeze peek at held-out renders under the ignored `experiments/` tree is attested by the phase log against the PM's acknowledgement, not structurally provable | §9, §12 |
| D13 | The baseline comparison uses **deterministic regeneration** from `m3-geometric-baseline` with the exact invocations of §11; pairing is by SHA-256 of the baseline run's written `original.png`, which is the file LivePortrait receives. Engine determinism is VERIFIED on synthetic fixtures (96/96 in M3 QA); end-to-end harness determinism on real captures is NOT VERIFIED and is established by the spike (each paired stem regenerated twice, both hashes recorded) | The same bytes go to both methods, and the assumption behind regeneration is measured rather than asserted | §11 |
| D14 | The §13 evidence gate — run by the PM-commissioned reviewer, or by the engineer at its true verification level if none is commissioned — precedes the PO session; the PO comparison is label- and position-blind, randomized per image, on the same dimensions used for M3, plus one pairwise primary question; the PM reads the verdict | Engineering does not score visual quality; QA policy §1/§3 reserve commissioning and the risk level to the PM; QA policy §9 budgets PO time, so the session is prepared, batched and authorized in advance | §13, §14 |
| D15 | Maximum **two engineering days**; the stop conditions in §15 end the spike early with a report, never with a redesign | This is a feasibility spike, not a porting project | §15, §16 |

## 2. Verified facts about the candidate

Facts that materially affect the design were verified against the pinned
upstream revision by reading its source in the authoring environment; two
were corrected by the adversarial review. Items that could not be verified
from here are marked and become Codex's first recording duty (§5).
Verification levels follow PRD §25.

| Fact | Status | Where verified |
| --- | --- | --- |
| Upstream repository `KlingAIResearch/LivePortrait`; `KlingTeam/LivePortrait` resolves to the same commit (organisation rename with redirect) | VERIFIED — `git ls-remote` on both names returns `9b294b3d…` as HEAD | remote refs |
| Code revision `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` is fetchable and is the default-branch HEAD at authoring time | VERIFIED | clone + checkout |
| Code licence: MIT (Kuaishou Visual Generation and Interaction Center, 2024). The same `LICENSE` states InsightFace *code* is MIT, InsightFace *models* are "for non-commercial research purposes only", and commercial use of LivePortrait requires removing and replacing them | VERIFIED | `LICENSE` |
| **No statement about the licence of LivePortrait's own weights exists anywhere in the code repository** (`LICENSE`, `readme.md`, `assets/docs/` searched); the model card on Hugging Face is the only candidate primary source | VERIFIED (negative) | repository search |
| InsightFace code is vendored under `src/utils/dependencies/insightface`; the human cropper builds `FaceAnalysisDIY(name="buffalo_l", root=pretrained_weights/insightface)` with `allowed_modules=None`, which loads **every** `*.onnx` in `models/buffalo_l/` and runs every non-detection model per detected face; the 106-point landmarks seed LivePortrait's own `landmark.onnx` refinement. Upstream's `assets/docs/directory-structure.md` lists exactly `det_10g.onnx` and `2d106det.onnx` for the pack | VERIFIED | `cropper.py`, `face_analysis_diy.py`, vendored `app/face_analysis.py`, `directory-structure.md` |
| **If `models/buffalo_l/` is absent, the vendored `FaceAnalysis` silently downloads `buffalo_l.zip` from a GitHub release URL** (`utils/storage.py: ensure_available → download`), unpinned and unhashed, printing `download_path:` | VERIFIED | vendored `utils/storage.py` |
| The still-image gaze path is `GradioPipeline.execute_image_retargeting(...)`; it is **not** exposed by the `inference.py` CLI. `init_retargeting_image(...)` must run first per image: it stores `source_eye_ratio` / `source_lip_ratio` on the pipeline object. Both methods call `cropper.update_config(self.args.__dict__)`, copying every `ArgumentConfig` field the crop config shares | VERIFIED | `src/gradio_pipeline.py`, `app.py` wiring |
| `update_delta_new_eyeball_direction(x, y, delta)` edits implicit keypoints 11 and 15 (horizontal: gains 0.0007/0.001 by sign; vertical: −0.001) **and adds a coupled lid term** `blink = −y/2` on keypoints 11, 13, 15, 16. The vertical control therefore moves the lids by upstream design | VERIFIED | `src/gradio_pipeline.py` |
| Eye-open-ratio retargeting (`retarget_eye`) runs only when `input_eye_ratio != self.source_eye_ratio`; lip likewise. Passing back exactly the values `init_retargeting_image` returned skips both | VERIFIED | `src/gradio_pipeline.py` |
| Official control ranges: horizontal `[−30, 30]`, vertical `[−63, 63]`, default 0; image crop scale default **2.5**; `mov_z` default **1.0** is multiplicative; all other controls default 0. Detector threshold: `ArgumentConfig.det_thresh = 0.15` (what `app.py` and `inference.py` build from) versus `CropConfig.det_thresh = 0.1` (bare dataclass default) | VERIFIED | `app.py`, `argument_config.py`, `crop_config.py` |
| Input handling: `init_retargeting_image` loads with `load_img_online(max_dim=1280, n=16)` and `prepare_retargeting_image` with `n=2`; an image whose sides are multiples of 16 and ≤ 1280 (1280×720 is) passes through both unchanged. Output `out_to_ori_blend` is the full-frame paste-back at the input's size; `paste_back` changes only the masked crop region | VERIFIED | `src/utils/io.py`, `src/utils/crop.py` |
| CPU, torch half: `InferenceConfig.flag_force_cpu` selects `device='cpu'` in `LivePortraitWrapper`; inference runs under `torch.autocast(device_type=device[:4], dtype=float16, enabled=flag_use_half_precision)`, so CPU runs must set the flag `False` | VERIFIED | `live_portrait_wrapper.py` |
| CPU, ONNX half — **corrected by review:** `Cropper` reads `flag_force_cpu` only from a constructor kwarg, and `LivePortraitPipeline.__init__` (inherited by `GradioPipeline`, used by `inference.py` and `app.py`) constructs `Cropper(crop_cfg=crop_cfg)` without it, so `CropConfig.flag_force_cpu` is dead at this revision and the cropper's CPU branch is unreachable through the official pipeline. On a non-MPS machine the InsightFace sessions and `landmark.onnx` request `CUDAExecutionProvider`; on the pinned CPU-only `onnxruntime==1.18.0` ORT emits a `UserWarning` and builds CPU sessions (`get_providers() == ['CPUExecutionProvider']`, default intra-op threads rather than the CPU branch's 4) | VERIFIED — the refuters reproduced the warning-and-fallback behaviour in a scratch venv with the pinned wheel | `cropper.py`, `live_portrait_pipeline.py`, `human_landmark_runner.py` |
| Model files the human path loads: `appearance_feature_extractor.pth`, `motion_extractor.pth`, `spade_generator.pth`, `warping_module.pth` (`pretrained_weights/liveportrait/base_models/`), `stitching_retargeting_module.pth` (`…/retargeting_models/`), `landmark.onnx` (`pretrained_weights/liveportrait/`), **plus** `pretrained_weights/insightface/models/buffalo_l/` — the research's six-file list omits the last item. The animal weights (`liveportrait_animals/`, incl. `xpose.pth`) are never loaded by the human pipeline | VERIFIED | config files, `cropper.py`, `directory-structure.md` |
| `inference.py` refuses to start unless an `ffmpeg` executable is found (`fast_check_ffmpeg`), and the video path shells out to `ffmpeg`/`ffprobe`; upstream ships `assets/docs/how-to-install-ffmpeg.md`. The still-image retargeting path does not need ffmpeg | VERIFIED | `inference.py`, `src/utils/video.py` |
| Dependencies: `requirements_base.txt` pins most packages but leaves `pillow>=10.2.0` floating; `requirements.txt` adds `onnxruntime-gpu==1.18.0` and `transformers==4.38.0`; torch is installed separately (upstream's macOS file shows the CPU equivalent `torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0` from the CPU wheel index); upstream recommends Python 3.10 | VERIFIED | requirement files, `readme.md` |
| Model repository revision `6d116d1066c3539da1cea3189da91c46cb505584`, its file list, per-file hashes and the model card's licence text | **NOT VERIFIED** — `huggingface.co` is unreachable from the authoring environment (proxy 403). Codex records these at reproduction time (§5, §7) | — |
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
| Spike work | branch **`codex/liveportrait-spike`**, created from the freeze commit of this SA | the only branch that receives spike commits |
| Frozen baseline | `m3-geometric-baseline` @ `f3831b5…`, checked out as a **separate worktree**, detached at that SHA | never checked out into the spike branch's tree; never modified; every regeneration runs from this worktree's root in the product venv |
| This SA | `model-feasibility-architecture-v1` | frozen; amend only through a PM-authorized revision |
| All previously frozen refs | `main`, `milestone-0/1/2`, `architecture-v1`, `m3-architecture-v1/.1/.2/.3`, `m3-geometric-baseline` | untouched, verified before and after the spike |

### 4.2 Directory layout

```text
spike/liveportrait/                     committed — the only home of spike code
  README.md                             setup steps, environment, how to run each phase
  pins/
    upstream.json                       repo URL + revision, model repo + revision, the
                                        expected file list with publisher hash and computed
                                        SHA-256 (filled once, §5), interpreter and CPU flags
    requirements-cpu-windows.txt        the full pip freeze of the first successful venv —
                                        the environment pin (§5)
  adapters/
    run_retarget.py                     programmatic driver of the upstream pipeline (§8)
    make_sheets.py                      QA three-way, PO sheet and enlarged-eye sheets (§12)
    manifest.py                         hashing, environment capture, plan/pin verification
  plan/
    plan.json                           sets, seed-ordered held-out list, control grid,
                                        thresholds, unmirror source, seed, and — after
                                        calibration — the frozen mapping (§9)
  evidence/
    <run-id>/manifest.json              committed run manifests: hashes, controls, timings,
                                        metadata — never Product Owner pixels
    <run-id>/po-key.json                the unsealed randomization key, committed only
                                        after the PO session (§14)
  .venv/                                GIT-IGNORED (matched by the existing `.venv/` rule)
  upstream/                             GIT-IGNORED: clone of the pinned revision, unmodified
    pretrained_weights/                 GIT-IGNORED: the pinned weights, upstream layout
experiments/liveportrait/<run-id>/      GIT-IGNORED: every rendered Product Owner image,
                                        every sheet, every intermediate, the sealed key
```

The upstream clone keeps its own layout so its relative checkpoint paths
work without modification (D2). The rule `spike/liveportrait/upstream/` is
already present in `.gitignore` (added by the review draft commit
`d664c7c`); the freeze commit verifies it, and §13's contamination diff
expects `.gitignore` to differ from the baseline by that rule only. All
paths under `spike/` and `experiments/` must be ASCII.

### 4.3 Committed versus ignored

| Committed | Ignored, local only |
| --- | --- |
| adapters, pins, plan, run manifests, the unsealed PO key after the session, README | upstream clone, weights, the spike venv and any wheel cache, every Product Owner capture and every render or sheet derived from one, the sealed key until the session is scored |

Renders of the public-domain astronaut fixture stay under `experiments/`
by default; they may be committed under `spike/liveportrait/evidence/fixture/`
**only if** the weight licence recorded under §7 step 1b permits
redistribution of outputs. No webcam frame of the Product Owner enters the
repository, in any form, at any resolution.

### 4.4 Contamination rules

- No file under `gazefix/`, `scripts/`, `tests/`, `pyproject.toml` or
  `constraints-windows-py312.txt` changes. The independent QA gate (§13)
  diffs these against the freeze commit.
- `spike/` never imports `gazefix`; the spike venv never installs it. The
  spike consumes the baseline's `report.json` / `frames.jsonl` as **data**
  (§11 names the fields).
- Nothing under `gazefix/` imports or references `spike/`. No venv, wheel
  cache or `site-packages` tree exists anywhere under `spike/` other than
  the ignored `.venv/`.
- The upstream clone is unmodified: before every run the driver records
  `git -C upstream rev-parse HEAD` (must equal the pin) and the full
  `git -C upstream status --porcelain` output verbatim; the check passes
  only if no tracked entry is modified or deleted and every untracked
  entry lies under `pretrained_weights/`.
- The spike adds **no runtime dependency** to GazeFix. Everything in
  `requirements-cpu-windows.txt` is spike-local.

## 5. External artifact pinning and provenance

`spike/liveportrait/pins/upstream.json` and
`spike/liveportrait/pins/requirements-cpu-windows.txt` are the single source
of truth; `manifest.py` refuses to run a phase when reality disagrees with
them.

| Item | Pin | How verified at run time |
| --- | --- | --- |
| Code repository | `https://github.com/KlingAIResearch/LivePortrait` (`KlingTeam/LivePortrait` redirects to it) | recorded URL |
| Code revision | `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` | `rev-parse HEAD` == pin; clean-tree check of §4.4 |
| Model repository and revision | `KlingTeam/LivePortrait` on Hugging Face at `6d116d1066c3539da1cea3189da91c46cb505584` | the download command, recorded verbatim, is `huggingface-cli download KlingTeam/LivePortrait --revision 6d116d1066c3539da1cea3189da91c46cb505584 --local-dir spike/liveportrait/upstream/pretrained_weights --include "liveportrait/*" "insightface/*"` — human weights only; `liveportrait_animals/` is excluded and must not be present |
| Weight files | the six LivePortrait files of §2 plus every file the pinned revision places under `insightface/models/buffalo_l/` (upstream documents exactly `det_10g.onnx` and `2d106det.onnx`; whatever the download places there is recorded by name) | for each file: the publisher's LFS SHA-256 and byte size at the pinned revision, obtained from the Hugging Face file metadata and recorded verbatim; the locally computed SHA-256 must equal it **before** the pin is sealed; a mismatch or unavailable metadata is a §15.1 stop. Sealed once by the first reproduction; enforced on every later run |
| Model card | `README.md` (and any `LICENSE*`) of the model repository at the pinned revision — excluded by the weights download, so fetched separately (§7 step 1b) | SHA-256 recorded; the `license:` front-matter field and any licence prose recorded verbatim in `spike/liveportrait/evidence/model-card-licence.md` |
| InsightFace pack integrity | `models/buffalo_l/` must exist with exactly the recorded files before any upstream import or pipeline construction; `buffalo_l.zip` must not exist; upstream stdout is captured and the run fails if a `download_path:` line appears | `manifest.py` pre-check; captured stdout in the manifest |
| Interpreter | CPython 3.10.x, exact patch recorded | `sys.version` recorded |
| Torch stack | `torch==2.3.0`, `torchvision==0.18.0`, `torchaudio==2.3.0` from `https://download.pytorch.org/whl/cpu` | `torch.__version__`, `torch.version.cuda is None`, `torch.cuda.is_available() is False`, `torch.__config__.show()` and `parallel_info()` recorded |
| ONNX Runtime | `onnxruntime==1.18.0` (CPU package; replaces upstream's `onnxruntime-gpu==1.18.0` at the same version) | `onnxruntime.get_build_info()`, `get_available_providers()` (no CUDA) and, per live session, `get_providers()` and `get_session_options().intra_op_num_threads` recorded (§8.3) |
| Download tooling | `huggingface_hub` pinned to the exact version used, recorded | `pip freeze` |
| Everything else | `requirements_base.txt` verbatim plus `transformers==4.38.0` and an explicit `pillow` pin for the first install; the resulting **full `pip freeze --all`** becomes `requirements-cpu-windows.txt`, sealed with the hashes; every later install uses it with `--no-deps` | freeze output diffed against the pin file at run time |
| ffmpeg (Phase A only) | an `ffmpeg`/`ffprobe` build on PATH, per upstream's `how-to-install-ffmpeg.md`; source URL, version string from `ffmpeg -version` and SHA-256 of the binary recorded in the Phase A manifest | Phase A manifest; Phases B–C have no ffmpeg dependency, so its absence is a setup task, never a §15 stop |
| CPU configuration | `flag_force_cpu=True`, `flag_use_half_precision=False`, `flag_do_torch_compile=False`; `torch.set_num_threads(N)`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` set by the driver to values written in `plan.json` before any render | recorded per run, with `torch.get_num_threads()` and the environment variables |
| Machine | OS build, CPU model and instruction-set flags, physical/logical cores, RAM, power plan if obtainable, whether the machine is the Product Owner's target laptop | recorded per run |

Rules:

1. No `main`, `latest`, or unpinned wheel anywhere. If a pinned wheel is not
   installable on the target machine, that is a §15 stop, not a reason to
   pick a nearby version silently.
2. The first reproduction **fills** the hash and freeze fields after the
   publisher cross-check; that commit is the pin. A later download that
   produces different bytes fails the run and is reported.
3. If the pinned model revision is unavailable, or the human file list
   differs from §2, stop (§15) and report exactly what was found.
4. The pin file's own SHA-256 and the plan's SHA-256 are recorded in every
   run manifest, so a manifest can be tied to the exact pins and plan it ran
   under.

## 6. Licensing boundary

This spike is **research / internal evaluation only**. Nothing in it implies
commercial clearance, and no result of it is shippable.

| Asset | Licence | Status for this spike | Status for any future production use |
| --- | --- | --- | --- |
| LivePortrait code | MIT — **verified** at the pinned revision | usable | compatible in itself; not a decision |
| LivePortrait weights (`.pth`, `landmark.onnx`) | not stated anywhere in the code repository (verified negative); the model card is the only candidate source and is **recorded at reproduction** as `STATED: <verbatim text, revision, hash>` or `UNSPECIFIED` | usable for internal evaluation only if the recorded terms do not exclude it — otherwise §15.8 | **unresolved until recorded**; `UNSPECIFIED` is disqualifying under the brief |
| InsightFace `buffalo_l` models — **exercised** by the human still-image crop path; every `.onnx` present in the pack is loaded and run (§2) | **non-commercial research only** — verified in LivePortrait's own `LICENSE`, which says commercial use requires removing and replacing them | usable for internal evaluation; the manifest records `list(cropper.face_analysis_wrapper.models)` per run as the exercised set | **not usable**; a production path would need a replacement detector/landmarker, itself a design and validation task |
| InsightFace code (vendored) | MIT — per the same `LICENSE` | usable | compatible |
| LivePortrait animal weights / XPose | not downloaded (§5), never loaded by the human pipeline | out of scope | out of scope |
| Product Owner captures | private; the Product Owner's own | local only | never committed, never shared |
| `tests/assets/astronaut_face.png` | public domain (NASA) — `tests/assets/README.md` | usable | usable |

**Screening verdict against the brief's criterion 3: FAILS for production as
shipped** — the InsightFace models are non-commercial and the weight terms
are unknown until recorded. The reproduction proceeds as a quality-evidence
experiment under the PM's `REPRODUCE CANDIDATE NOW` decision (freeze
record), not as a licensing clearance.

PRD §27 checklist as of this SA: active project status — VERIFIED (the
pinned revision is the current upstream HEAD); Windows compatibility — NOT
VERIFIED (upstream ships a Windows installer, but its CPU path is annotated
"WIP"); Python/runtime compatibility — VERIFIED by reading, NOT VERIFIED by
execution; CPU compatibility — NOT VERIFIED, the spike's first gate; licence
— split as above; redistribution restrictions — NOT VERIFIED for weights;
model licensing separately from code — recorded as above. "No research-only
model may be treated as production-ready without flagging the restriction":
flagged.

## 7. Phase A — CPU-only official reproduction gate

The spike does not proceed past this phase until it passes. Steps 1–3
involve no GazeFix code; steps 4–5 use the product venv only to read M2 as
§8.2 defines, so the baseline worktree and product venv are set up in step 1
as well.

1. Clone the pinned revision; create the spike venv and install the pinned
   environment; download the pinned human weights with the recorded command;
   cross-check and seal the hashes (§5); verify the InsightFace pack
   pre-check (§5) before any upstream import. Create the detached baseline
   worktree (§4.1) and regenerate the astronaut fixture's baseline record
   (§11), whose written `original.png` — the canvased 1280×720 fixture — is
   the input for steps 4–5.
   - **1b.** Fetch the model repository's `README.md` and any `LICENSE*` at
     the pinned revision with a recorded command; record their SHA-256 and
     the licence terms verbatim (§6). If the recorded terms exclude
     non-commercial internal evaluation, stop (§15.8) before any render.
2. Run the upstream's **own** CLI example on the upstream's **own** example
   inputs with `--flag_force_cpu` and half precision disabled, unmodified.
   If the default example's driving clip is impractically slow on CPU, the
   upstream's own motion-template (`.pkl`) example is an acceptable official
   input. What must hold: official code, official inputs, official flags, no
   edits. **The ONNX-provider `UserWarning` described in §2 is expected on
   this run and is not a §15.2 stop.**
3. Record, for that CLI subprocess: wall time, peak memory if obtainable,
   the output produced, its captured stdout and stderr including the
   expected ONNX-provider `UserWarning`, and — from the same venv —
   `onnxruntime.get_available_providers()` (no CUDA) and
   `torch.cuda.is_available()` (`False`). Per-session providers and thread
   counts cannot be observed inside an unmodified subprocess; they are
   recorded from step 4 onward through §8.3.
4. Run the programmatic retargeting driver (§8) on the fixture input of
   step 1 with **all controls neutral**, three times (its SHA-256 in the
   Phase A manifest). Identity criterion, pre-declared in `plan.json` with
   these defaults: in-mask PSNR (`mask_ori > 0`) between output and input
   ≥ 30 dB, and the M2 reading (§8.2) of the output within 1.0° of the
   input's on each axis. The **M2 noise floor** is `max(floor_min,
   max over the three renders and both axes of |M2(output) − M2(input)|)`
   with `floor_min = 0.5°` pre-declared; it is the reference for every
   direction test. (The three renders are expected to be byte-identical;
   their mutual agreement is a determinism check, not the floor.)
5. Run the same with `eyeball_direction_x = +20` and separately `−20`; the
   two outputs must move the M2 yaw reading in opposite directions, each by
   more than `floor_factor × floor` with `floor_factor = 3` pre-declared.

**Pass:** all steps complete on CPU with no CUDA, no ONNX/OpenVINO
conversion, no upstream edit. **Stop (§15):** any step requires editing
upstream, a CUDA-only code path, or an unavailable pinned artifact — report
what blocked and where, and return to the PM. Do not redesign upstream. Do
not switch to another candidate. Thresholds may be changed only in
`plan.json` before Phase A runs, with a recorded reason.

## 8. Phase B — gaze-control validation

### 8.1 Construction and the neutral-control contract

The driver builds the pipeline **exactly as `app.py` does**: one
`ArgumentConfig` with only `flag_force_cpu=True`,
`flag_use_half_precision=False` and `flag_do_torch_compile=False`
overridden, turned into `InferenceConfig` and `CropConfig` by a spike-local
copy of upstream's one-line `partial_fields`, then
`GradioPipeline(inference_cfg, crop_cfg, args)`. The driver never imports
`app` (which launches the server). The effective detector threshold is
therefore the official `0.15`, and the live `inference_cfg`, `crop_cfg` and
`args` objects are recorded in the manifest after construction.

Per image, in this order: `init_retargeting_image(2.5, …, path)` and then
`execute_image_retargeting(...)`, where `path` is the **string path** of the
paired `original.png` for both calls — never an in-memory array, which the
first call rejects — so the bytes hashed as the pairing key are exactly the
bytes upstream decodes. The remaining arguments:

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
previous image would silently activate eye-open-ratio retargeting. Inputs
must have both sides divisible by 16 and no side above 1280 (true of 1280×720)
so that both upstream loads see identical arrays; the post-load size is
recorded. The driver catches any exception per image into
`FAILED: <exception text>` and continues the batch; an output whose size
differs from the input's is recorded as `FAILED: size mismatch` and the pair
is void.

### 8.2 Required evidence, per run

1. **Direction.** On each calibration image, the single-axis sweeps of
   §9.2 must move the M2 reading monotonically in the expected direction:
   Spearman rank correlation between control value and M2 delta ≥ 0.9 with
   the expected sign, on each axis, and the endpoint-to-endpoint M2
   difference greater than `floor_factor × floor` from §7. "M2 reading"
   means the fused camera-relative `yaw_deg` / `pitch_deg` that GazeFix's
   frozen estimator reports when the baseline harness analyses the rendered
   output at strength 0 in the product venv (analysis only, no correction;
   §11 gives the invocation). A spike-local dark-pixel centroid inside each
   eye box is recorded alongside as a second, GazeFix-independent reading.
2. **Eye-open-ratio retargeting not invoked.** The driver wraps
   `retarget_eye` and `retarget_lip` on the live wrapper with counting spies
   for the duration of each run and records the counts, which must be zero,
   alongside the equality `input_eye_ratio == source_eye_ratio` and the
   ratio values.
3. **Upstream intact.** The manifest records the upstream commit, the
   clean-tree output, the two flags of §8.1 as `True`, and the construction
   path of §8.1; the driver imports upstream modules and calls their public
   methods only.
4. **The coupled lid term is recorded, not hidden.** For every render the
   manifest records `eyeball_direction_y` and the derived `blink = −y/2`
   that upstream applies. The Product Owner's eyelid-preservation score
   therefore judges the official control as published (D9). If lid motion
   is the reason a result fails, that is a finding about the candidate, and
   any de-coupling experiment is a new PM decision, not a tweak.

### 8.3 Permitted instrumentation

The only instrumentation permitted is wrapping public methods on the live
objects by instance attribute: `cropper.crop_source_image`,
`live_portrait_wrapper.get_kp_info`, `extract_feature_3d`, `stitching`,
`warp_decode`, `retarget_eye`, `retarget_lip`. Per-stage timings come from
those wrappers; paste-back time is reported as total minus the wrapped
stages; crop metadata (§12) is taken from the second `crop_source_image`
call of each image (the one `execute_image_retargeting` makes). No module
attribute of upstream is replaced. The per-session ONNX providers and
thread settings are read from `cropper.human_landmark_runner.session` and
each `cropper.face_analysis_wrapper.models[*].session`, and the ORT
`UserWarning` text is captured, so §13 step 2 reads what each session
actually used rather than what was available.

## 9. Phase C — calibration versus held-out separation

### 9.1 Sets

| Set | Members | Codex may |
| --- | --- | --- |
| Calibration | `tests/assets/astronaut_face.png` canvased to 1280×720 by the harness (`--canvas 1280x720`, default face scale) — used for sign and monotonicity evidence only, not gain fitting, because its upscaled 107 px face gives low-resolution M2 readings; plus the Product Owner stills **`lens-glasses`** and **`screen-glasses`**, used for gain fitting. Fixed here at freeze | render freely, inspect, iterate within the grid |
| Held-out | `horizontal-no-glasses`, `horizontal-glasses`, `notes-no-glasses`, `notes-glasses`, `lens-no-glasses`, `screen-no-glasses`, and the clip frames of §10 — in the **stratified seed order** written to `plan.json`: the in-range paired stems first, then everything else, seed order within each stratum (§10, §16) | render **once** each with the frozen mapping; inspect only after all are rendered; never re-render, retouch or change a control |

If a calibration still fails detection it is recorded and the remaining
members are used; the fixture alone suffices for signs and monotonicity, and
a gain fitted on one still is recorded as such.

### 9.2 Control grid (fixed before calibration begins)

Single-axis sweeps on each calibration image, controls otherwise neutral:

- horizontal: `x ∈ {−20, −15, −10, −5, 0, 5, 10, 15, 20}`, `y = 0`;
- vertical: `y ∈ {−30, −20, −10, 0, 10, 20, 30}`, `x = 0`;
- four combined points `(±10, ±15)`.

These are well inside the official ranges (±30, ±63). The clamps default to
the grid endpoints, `Xmax = 20` and `Ymax = 30`. Calibration may **narrow**
them to a smaller grid value where artifacts appear, naming the image and
grid point as evidence; it may not extend the range or add off-grid points.

### 9.3 The frozen mapping and its fit rule

Commanded correction for an image is taken from the baseline's own record
for that image (D10): source gaze `(yaw_s, pitch_s)` from M2, target the
optical axis, effective strength `e` from the policy record, so the
commanded angular change is `Δyaw = −e·yaw_s`, `Δpitch = −e·pitch_s`
(degrees, camera frame). The mapping is:

```text
x = clamp( sx · gx · Δyaw,   −Xmax, +Xmax )
y = clamp( sy · gy · Δpitch, −Ymax, +Ymax )
```

with exactly six frozen values. The **fit rule**: on each gain-fitting
calibration image and axis, the §9.2 sweep gives the M2 response (delta of
the fused `yaw_deg` or `pitch_deg` between rendered output and original)
against the control value; a least-squares line through those points gives
that image's **signed** slope in degrees per slider unit. With `m` the
median of those signed slopes across the gain-fitting images: `gx = 1/|m|`,
`sx = sign(m)` (resp. `gy`, `sy`), so that `sx·gx·Δyaw` moves the response
in the commanded direction; `Xmax`, `Ymax` are grid values (§9.2). The
signed per-image slopes, `m`, and the residuals are written to `plan.json`
beside the six values, so QA can recompute all six from the sweep data. One
verification render of each calibration image at its own mapped `(x, y)`
is permitted and recorded. The gain is a unit conversion measured on
controlled perturbations; it does not look at held-out images and does not
look at the baseline's output.

The plan freeze is a commit on `codex/liveportrait-spike`, **pushed to
origin and acknowledged by the PM before any held-out render**. The
acknowledgement artifact is `spike/liveportrait/evidence/plan-freeze.json`:
the pushed commit SHA, the plan's SHA-256, and the PM's acknowledgement
quoted verbatim with its timestamp. Every held-out manifest records that
commit's SHA, the branch HEAD at render time and the plan's SHA-256, and the
phase log carries `plan pushed` and `PM acknowledged` entries, so QA checks
origin ancestry **and** that every held-out render timestamp follows the
acknowledgement. The wait for the acknowledgement is outside the two-day
count (§16).

If no gain reproduces the commanded direction on the calibration set, that
is a §15.4 stop with evidence, not a reason to invent per-image values.

### 9.4 What is forbidden after the freeze

Changing any of the six values; re-rendering a held-out image for any
reason other than the §12 reproducibility check; choosing which outputs to
show; retouching, cropping, colour or sharpness adjustment of any output;
substituting a different input file for a stem. The randomization seed for
the PO session (§14) is written to `plan.json` at the plan freeze.

## 10. Inputs — Product Owner capture selection

Use the existing M3 captures wherever suitable; never fabricate coverage.

| Condition required | Source in the existing M3 capture set | If missing |
| --- | --- | --- |
| horizontal gaze offset | `horizontal-no-glasses`, `horizontal-glasses` | record gap |
| vertical gaze offset | `notes-no-glasses`, `notes-glasses` (down), `screen-no-glasses` (small) | record gap |
| moderate offset in range | any held-out still whose baseline `policy.deviation_deg` is ≥ 10° (values above 20° are noted, not excluded) | record which stills fall outside |
| direct / null case | `lens-no-glasses` (held-out), `lens-glasses` (calibration) | — |
| modest head pose | one or two frames from `minor-rotation.mp4` | record gap |
| visible sclera, open eyes | every still; recorded per image from the baseline's per-eye status | — |
| glasses | `horizontal-glasses`, `notes-glasses` held-out; the two calibration stills | record gap |
| stress / near-blink | one or two frames from `blink-wink-squint.mp4` with both eyes partly open | record gap |

Rules:

- **Clip frames** are extracted once, in the product venv, with
  `cv2.VideoCapture` from the raw clip (before any unmirroring) at frame
  indices chosen and recorded in `plan.json` before calibration; each
  extracted PNG's SHA-256 is recorded and the frame is then treated like any
  other still, with `--unmirror` applied by the harness (§11).
- **Three classes, fixed in `plan.json` from the baseline records before
  any held-out render.** *Paired*: the baseline record shows frame status
  `CORRECTED` with **both** eyes `CORRECTED`. *Baseline-declined*: the
  policy record has `effective_strength > 0` but at least one eye is not
  `CORRECTED` (a frame-level skip, or the pair rule's one-eye outcome); such
  a stem is rendered once with the frozen mapping and shown to the PO as
  original-versus-LivePortrait on the key criterion only, reported
  separately and never counted in the pairwise majority. *Excluded*:
  `effective_strength == 0` — neither method is asked to do anything.
  Pairing conditions the comparison on the baseline's own success and is
  stated as a known bias: the geometric class fails structurally exactly
  where it skips, and the baseline-declined answers are the evidence about
  that region. A near-blink frame is paired only if
  `experiments[0].eye_geometry.<side>.aperture` is at least 0.18 for both
  eyes in the baseline record (the engine's own `min_aperture` gate);
  otherwise it is baseline-declined.
- **In range** means the baseline's `policy.deviation_deg ≥ 10°` (above 20°
  noted, not excluded). The §14 majorities and the floor below are defined
  on **one set: in-range paired stems**, fixed in `plan.json`, so the
  denominator is never chosen after unblinding.
- **Realistic arithmetic**: the existing set yields at most ten held-out
  images (six stills plus up to four clip frames); only the four
  `horizontal-*` / `notes-*` stills can be in range, so the floor below has
  one image of slack at best. Fewer than **three** in-range paired stems
  makes the outcome `INCONCLUSIVE` before the PO session (§14); fewer than
  **six** held-out stems in the paired and baseline-declined classes
  together is a §15.5 stop.
- **Mirroring**: `plan.json` records the `unmirror` value and its source —
  the M3 gate batch's `report.json["arguments"]["unmirror"]` (reading a flag
  is not reusing a render) or the PO's answer relayed by the PM — before
  regeneration; every regenerated `report.json` must carry the same value.
  LivePortrait then receives the baseline run's `original.png` — the exact
  bytes the baseline corrected — so orientation, size and content are
  identical on both sides (D13).

## 11. Frozen geometric comparison

**Deterministic regeneration is authoritative.** Existing local M3 renders
are not reused. All invocations run from the root of the
`m3-geometric-baseline` worktree in the product's Windows venv; `--inputs`,
`--image` and `--out` take **absolute paths** into the primary checkout's
ignored `experiments/` tree (a fresh worktree has none), and the argument
list is recorded verbatim per stem in the spike manifest. QA compares it,
modulo those absolute paths, against `batch.json["experiments"][stem]
["arguments"]` for batch stems and against the parsed keys of
`report.json["arguments"]` (`image`, `strength`, `debug`, `unmirror`,
`canvas`, `variant`) for every stem. `--unmirror` applies to PO captures —
stills and extracted clip frames — and **never** to the astronaut fixture:

| Input class | Invocation |
| --- | --- |
| the eight PO stills (and the three clips, whose runs are not used for pairing) | `python -m scripts.correction_batch po --inputs experiments/inputs [--unmirror]` — the M3 gate's PO mode: default variant C, default settings, policy on, requested strength `.7`, optical-axis target, no smoothing, `--debug`. The batch requires all eleven named files to be present |
| an extracted clip frame | `python -m gazefix.correction.harness --image <frame.png> --strength .7 --debug [--unmirror] --out <batch-root> --name <stem>` — the image-mode run, not the clip run, is the paired baseline |
| the astronaut fixture | the same, with `--image tests/assets/astronaut_face.png --canvas 1280x720` and without `--unmirror` |
| M2 reading of any rendered output (§8.2) | `python -m gazefix.correction.harness --image <render.png> --strength 0 --debug --out <spike-run> --name <stem>-<method>` — strength 0 analyses and returns the frame unchanged |

Each paired stem is regenerated **twice**; both `corrected.png` hashes are
recorded, the first run is authoritative, and any difference is reported to
QA and the PM as a finding about harness determinism (not a stop).

Fields the spike reads from each baseline `report.json`, as data: the
regeneration provenance `repository.head` (must be `f3831b5…`) and
`repository.tracked_changes` (must be `false`); `source.name`,
`source.sha256` (the raw capture file, provenance only) and
`source.unmirror`; and from `experiments[0]`: `gaze.yaw_deg`,
`gaze.pitch_deg`, `policy.effective_strength`, `policy.deviation_deg`,
`correction.status`, `correction.message`, per eye
`correction.eyes[i].status`, `.reason`, `.clamped`, `.displacement_px`, and
`eye_geometry.<side>.aperture` (present because every run uses `--debug`).

**Pairing key**: the SHA-256 of the baseline run's written `original.png`,
computed by `manifest.py` when the spike copies that file and recomputed by
QA. It must equal the hash of the file LivePortrait consumed; the raw
capture hash is recorded beside it for provenance and is **not** the pairing
key. The manifest also records the batch directory name and the SHA-256 of
`report.json` itself. A mismatch voids the pair.

Rules: no setting, constant, variant or strength is changed for this
comparison; the baseline branch is never modified.

## 12. Evidence output

Per evaluated image, under `experiments/liveportrait/<run-id>/<stem>/`:

| Artifact | Content |
| --- | --- |
| `original.png` | the shared input, byte-identical to the baseline run's `original.png` (pairing key) |
| `geometric.png` | the regenerated baseline `corrected.png` (SHA-256 recorded) |
| `liveportrait.png` | the LivePortrait paste-back output at native size (SHA-256 recorded) |
| `three_way.png` | QA sheet: original / geometric / LivePortrait side by side at native scale, in that fixed order, labelled by method — **never shown to the PO** |
| `po_sheet.png` | PO sheet: original in the fixed first position, then the two corrected results in the two result positions in **A, B order, where the position draw is per image** (§14); labels are the letters only; no method names, file names, control values or crop boundaries visible |
| `eyes_3x.png` | the same three panels as `po_sheet.png`, eye region enlarged 3× with nearest-neighbour or a recorded filter, identical crop box for all three; the crop box and filter are recorded per stem in the manifest so QA can re-derive the sheet |
| `crop_meta.json` | upstream crop box, `M_c2o`, source landmark count, crop scale 2.5, `det_thresh`, `dsize`, `vx_ratio`, `vy_ratio`, `flag_do_rot`, post-load image size, stitching and paste-back flags |
| `timing.json` | per-stage timing from the §8.3 wrappers, paste-back as remainder, total offline wall time; the baseline's own stage timings from its report |

Per run, `spike/liveportrait/evidence/<run-id>/manifest.json` (committed):
run id; kind (`phase-a`, `calibration`, `held-out`, `baseline-declined`);
pin-file SHA-256, plan SHA-256, plan-freeze commit SHA and branch HEAD;
upstream commit and clean-tree output; model file names and hashes; the
InsightFace pre-check result and the exercised model list; environment and
machine capture (§5); per-session ONNX providers, thread settings and the
captured warning; the timestamped phase log (setup start, Phase A/B/C start
and end, handoff); per image: stem, pairing-key hash, raw-capture hash and
`unmirror`, batch directory and `report.json` hash, baseline provenance and
the §11 fields, output hashes (both baseline regenerations), control values
`(x, y)`, clamp engagement per axis, derived `blink`, source ratios and the
zero spy counts, commanded correction `(Δyaw, Δpitch)`, M2 readings of the
original and both outputs and the achieved-delta ratio
LivePortrait/baseline (reported, not a gate), timings, in-range flag, and
status (`RENDERED` / `FAILED: <reason>`).

**Reproducibility check**: one held-out image, chosen by the seed, is
re-rendered from its manifest. Expected: identical `liveportrait.png` hash.
Otherwise the max absolute difference and in-mask PSNR are recorded against
a tolerance pre-declared in `plan.json`; exceeding it is the §15.6 stop.

**What the design lets independent QA prove:** no cherry-picking (the
held-out manifests contain every stem of the frozen stratified list up to
the recorded truncation index, exactly once, `FAILED` included); no
per-image tuning (for every held-out and baseline-declined stem, `(x, y)`
recomputed from the manifest's `(Δyaw, Δpitch)` and the plan's six values,
clamps included, equals the recorded controls); separation (every held-out
manifest names a plan-freeze commit that is an ancestor on origin, carries
its plan hash, and has a render timestamp after the PM's acknowledgement in
`plan-freeze.json`); correct upstream model (commit, clean tree,
publisher-checked hashes, pack pre-check); correct baseline pairing
(pairing-key equality per stem, baseline provenance, `unmirror` equal to the
plan for PO captures); reproducibility (the check above).

## 13. Independent QA gate — before the Product Owner sees anything

Proposed risk level **HIGH** under QA policy §3 (model and licence
uncertainty) — the PM confirms the level and commissions the reviewer at
freeze; if none is commissioned, the engineer runs this list and reports
each item at its true verification level before the PO session. The gate
runs on the machine that holds `experiments/`, the spike venv and the
product venv; items that need artifacts unavailable to the reviewer are
reported `NOT VERIFIED`, not skipped silently. It is targeted, not a
recertification; it verifies, in this order, and stops when done:

1. contamination (§4.4): `git diff <freeze-commit> -- gazefix scripts tests
   pyproject.toml constraints-windows-py312.txt` is empty; `.gitignore`
   differs from the baseline only by the spike rule; `grep -r gazefix
   spike/` is empty; `pip show gazefix` fails in the spike venv; no venv or
   `site-packages` under `spike/` except `.venv/`;
2. pins (§5): upstream commit and clean-tree output; every weight hash
   against the sealed publisher-checked values; the pack pre-check; the
   environment freeze diff; `cuda.is_available() is False`; **per-session**
   providers and threads;
3. control isolation (§8): spy counts zero, ratio equality, neutral
   controls, flags `True`, construction path, `blink` recorded;
4. separation, completeness and no tuning (§9, §12): plan-freeze commit
   ancestry on origin and render timestamps after the acknowledgement in
   `plan-freeze.json`; plan hash in every held-out manifest; held-out count
   equals the truncation rule; no re-render; `FAILED` cases present; the six
   mapping values recomputed from the recorded sweep slopes; `(x, y)`
   recomputed per stem from `(Δyaw, Δpitch)` and the six values, clamps
   included, equal to the recorded controls;
5. pairing and parity (§11, §12): pairing-key equality per stem; both
   baseline regeneration hashes; `repository.head` and `tracked_changes`;
   `unmirror` equal to the plan for PO captures; argument lists equal to §11
   modulo absolute paths; the achieved-delta ratio and both clamp states
   present per stem and recomputable from the recorded M2 readings;
6. reproducibility (§12): the one re-render;
7. sheet integrity: each `three_way.png` and `po_sheet.png` decodes back to
   the three recorded images with no post-processing, and each `eyes_3x.png`
   equals the recorded crop box of those images enlarged with the recorded
   filter; QA records the per-stem letter → output-hash map it derives while
   decoding, for the post-session check of §14.

QA does not score visual quality and does not debug the candidate (QA
policy §7). Outcome vocabulary: `SPIKE EVIDENCE VERIFIED — READY FOR PO
COMPARISON`, `SPIKE EVIDENCE CHANGES REQUIRED`, `SPIKE EVIDENCE BLOCKED`.

## 14. Product Owner comparison design

Engineering does not score visual quality. The comparison is one prepared,
batched session (QA policy §9); the PM authorizes its length before it runs.

- **Label- and position-blind, randomized per image.** For every held-out
  image the PO sees `po_sheet.png` and `eyes_3x.png`: the original, then
  results **A** and **B**. Position is drawn per image by a fixed rule
  recorded in `plan.json` — the geometric result takes position A iff the
  first bit of `sha256(seed ‖ stem)` is 0 — so QA can recompute the key
  from the committed seed. The key file is sealed during the session (SHA-256
  committed before it); after the PO's sheet is returned it is committed as
  `po-key.json` and QA verifies, per stem, that the revealed letter → method
  map equals both the seed rule and the letter → hash map it recorded at
  step 7. **Blinding is partial and recorded as such**: the PO scored the
  geometric result on the two anchor stills at M3 and knows the vertical
  control moves lids (D9); randomization controls position and order bias,
  not method recognition.
- **FAILED held-out stems** are shown with a blank result panel in the
  failed method's position; they count in every denominator as not chosen
  and as key-criterion "no" for the failed method.
- **Baseline-declined stems** (§10) are shown as original-versus-LivePortrait
  on the key criterion only, after the paired set, and reported separately.
- **Dimensions**, per result: eye realism, iris realism, eyelid
  preservation, identity preservation, artifact visibility, perceived eye
  contact, 1–5 (blink realism N/A on stills); and the key criterion — "is
  this correction less distracting than the original lack of eye contact?"
  yes/no. **Primary pairwise question**, per image: "Is one result clearly
  more natural and less distracting than the other? A / B / neither."
- **Budget.** Two results per image at the M3-ratified 2–3 minutes per
  result: about 4–6 minutes per image, **40–60 minutes** for up to ten
  held-out images. This exceeds the policy's typical session, so the PM
  authorizes it explicitly, or decides to reduce per-result scoring to eye
  realism, iris realism, eyelid preservation, artifact visibility and the
  key criterion (about half the time); either choice is recorded before the
  session. One session; no exploratory tuning; no second round without a PM
  decision.
- **Verdict reading — applied by the PM to the unblinded sheet; engineering
  records scores and hashes only.** Majorities are taken over the in-range
  held-out images fixed in `plan.json` (§10); out-of-range, null and clip
  frames are blind no-harm checks whose answers are recorded and reported
  but not counted, except that a disqualifying artifact class on any of
  them still fails the candidate. As judgment aids, never objective pass
  scores (the PM-ratified M3 rule, unchanged): LivePortrait is
  **`MATERIALLY MORE NATURAL`** only if the PO chooses it on the pairwise
  question for a clear majority of in-range images, answers yes to its key
  criterion on a clear majority, scores it clearly better than the geometric
  result on eye realism, artifact visibility and eyelid preservation on a
  clear majority, **and its iris-realism score is not below the geometric
  result's on the same image on a clear majority** — the brief's
  non-regression guard; lid motion from the coupled term is scored under
  eyelid preservation like any other effect. **`NOT MATERIALLY MORE
  NATURAL`** if the pairwise or key-criterion majority goes to the geometric
  result or to "neither". **`INCONCLUSIVE`** if fewer than three in-range
  paired stems exist (§10), or the answers split without a clear majority
  either way; the record then states what is missing and what it would cost.
- **After unblinding**, the results are recorded per image with the method
  revealed — beside each image's achieved-delta ratio, LivePortrait's clamp
  state per axis and the baseline's per-eye `clamped`, so the PM can see an
  under- or over-correction next to the PO's answers — alongside the
  manifest hashes and the PM's reading, in
  `docs/milestones/model-feasibility-evaluation.md`. The PM closes the spike
  there with **`MODEL FEASIBILITY SPIKE COMPLETE`** and the single
  recommendation the brief asks for, or with **`MODEL FEASIBILITY SPIKE
  BLOCKED`** on a §15 stop.

## 15. Success, stop and escalation criteria

**Engineering reproduction success is not product success.** Phases A–C
succeeding means the evidence exists; only §14 answers the product
question.

Codex **stops and returns to the PM** — with the report of §20 stating what
was established and what blocked — if any of these occurs:

1. the pinned code or model revision is unavailable, the human file list
   differs from §2, or a computed hash disagrees with the publisher's;
2. CPU-only inference requires editing upstream, a CUDA-only path, or a
   conversion step (ONNX/OpenVINO/other) — the expected ONNX-provider
   warning of §2 is **not** this condition;
3. any step requires training, fine-tuning, or hidden learned adaptation;
4. the gaze-direction manipulation cannot be reproduced under the §7 and
   §8.2 criteria, or no gain reproduces the commanded direction on the
   calibration set;
5. the existing Product Owner captures are fundamentally incompatible: the
   upstream cropper detects no face on most stills, or fewer than six
   eligible held-out images exist;
6. the §12 reproducibility check exceeds the pre-declared tolerance;
7. the two-engineering-day timebox would be exceeded to complete Phase C
   even after the §16 prefix reduction;
8. the recorded weight-licence terms exclude non-commercial internal
   evaluation.

On a stop, the report states which condition fired, the evidence, and what
it would cost to remove the blocker. Codex does **not** move to ST-ED or any
other candidate, does not modify upstream, and does not widen the timebox;
the PM decides.

## 16. Timebox

**Maximum two engineering days**, counted from environment setup to the
handoff of the QA-ready evidence package, with the phase log of §12 as the
record. Indicative split: Phase A up to half a day; Phase B and calibration
up to one day; held-out renders, sheets, manifests and the report the
remainder. The Product Owner session and independent QA are outside the
timebox. CPU render time is part of the budget: if per-image time on the
target machine makes the full held-out list infeasible, render a **prefix**
of the stratified list frozen in `plan.json` — in-range paired stems come
first, so a prefix can never omit one while an out-of-range stem is
rendered — recording the truncation index and the measured per-image time;
the three-stem minimum of §10 and the six-stem minimum of §15.5 still apply,
and the §12 completeness proof counts against the recorded index.
Calibration and evidence steps are never skipped to save time; if even the
minima are infeasible, stop (§15.7). Waiting for the PM's plan
acknowledgement is outside the count; rework after `SPIKE EVIDENCE CHANGES
REQUIRED` is outside the count too but is logged as its own phase and needs
the PM's authorization if it exceeds half a day.

## 17. Future architecture implications — documented, not implemented

Three outcomes, all legitimate, each read by the PM on the report and the
unblinded record:

**`NOT MATERIALLY MORE NATURAL`:** engineering records the evidence; the
**PM** decides whether LivePortrait is rejected as a candidate and whether
to reproduce ST-ED next under a new, equally bounded spike SA. The verdict
is measured on stems the baseline itself corrected, so the PM reads the
baseline-declined answers before treating the geometric baseline as adequate
where it skips. The geometric baseline remains the reference. Nothing in
the architecture changes.

**`INCONCLUSIVE`:** engineering records what is missing (in-range coverage,
detections, a split result) and what it would cost to resolve; the PM
chooses between a bounded second session, another candidate, or stopping.

**`MATERIALLY MORE NATURAL`:** LivePortrait is **not** integrated and M4 is
**not** started. The result establishes that a learned renderer can clear
the product bar on stills, which reframes the next architecture question as
one of the following, for the PM to choose between:

1. obtaining a **smaller, licensable, CPU-feasible** learned correction
   engine — the current candidate carries a non-commercial detector
   dependency, a research-grade CPU path, and a latency measured here only
   offline;
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
| Model-card licence text for the LivePortrait weights at the pinned revision | Codex records verbatim | Phase A step 1b, before any render |
| Publisher hashes and the human file list at the pinned revision; the exact contents of the `buffalo_l` pack | Codex records and seals | first reproduction |
| Python 3.10 availability on the Product Owner's machine (the product uses 3.12); spike venv creation; ffmpeg for Phase A | Codex | setup |
| CPU render time and memory on the target-class machine | Codex measures | Phase A/C |
| Whether upstream's "WIP" CPU path runs the still-image retargeting cleanly on the provider-fallback path | Codex — Phase A decides | Phase A |
| End-to-end harness determinism on real captures | Codex measures (§11 double regeneration) | Phase C |
| Whether the coupled lid term of the vertical control is acceptable | PO judges, PM reads | §14 |
| Risk level and reviewer commissioning for §13 | PM | at freeze |

## 19. Handoff — what Codex must not redesign

Fixed by this SA: the isolation layout and contamination rules (§4); the
pin set, the publisher cross-check, the pack pre-check and the
refusal-to-run rule (§5); the licensing statements and the screening
verdict (§6); the CPU flags, the no-conversion rule and the Phase A
criteria (§7); the construction path, the neutral-control contract, the
four evidence items and the instrumentation limits (§8); the sets, grid,
six-value mapping, fit rule, plan-freeze and acknowledgement rule and
post-freeze prohibitions (§9); the eligibility rules, the baseline-declined class, the arithmetic
minima and the pairing bytes (§10–§11); the artifact and manifest contents
(§12); the QA gate order and the PO design including the position rule and
verdict vocabulary (§13–§14); the stop list, the timebox and the prefix
rule (§15–§16); the report of §20.

Left to the implementor: script structure and naming inside `spike/`; sheet
layout beyond the rules given; how spies, hashing and the phase log are
implemented; the frame indices from the two clips (recorded in the plan);
the narrowing clamps (grid values, with evidence); and the thresholds of §7
and §12 within the rule that they are declared in `plan.json` before the
phase that uses them.

## 20. Engineering report — the deliverable

`docs/milestones/model-feasibility-report.md`, written by Codex at handoff,
satisfies the brief's per-candidate deliverable and the stop vocabulary:

1. **Status line**, exactly one of `SPIKE EVIDENCE PACKAGE READY FOR QA`
   (evidence package produced; the §13 gate and the §14 session follow) or
   `SPIKE BLOCKED — <§15 condition>`. The brief's terminal words belong to
   the PM: `MODEL FEASIBILITY SPIKE COMPLETE` is declared in
   `model-feasibility-evaluation.md` after §14, `MODEL FEASIBILITY SPIKE
   BLOCKED` on a stop. The product verdict is not in this report.
2. **Candidate record**: source and weights availability with links and
   revisions; the code licence and the recorded weight licence verbatim
   with source; the exercised InsightFace models; hardware and runtime
   actually used; dependency burden (the freeze, in numbers).
3. **Phase results**, each claim at its PRD §25 level (implementation /
   runtime / physical-hardware; VERIFIED / NOT VERIFIED / NOT MEASURED /
   FAILED): Phase A pass with timings and provider evidence; Phase B
   direction and isolation evidence; calibration slopes, residuals and the
   six frozen values with the plan-freeze commit; held-out count, in-range
   count, truncation index if any, `FAILED` and baseline-declined stems;
   the reproducibility check; both baseline regeneration hashes per stem.
4. **Timings**: per-stage and total offline time per image, machine
   metadata; stated as offline measurements, never as a real-time claim.
5. **Phase log** against the two-day timebox.
6. **Evidence pointers**: run ids, manifest paths, the sealed-key hash.
7. **Screening verdict and engineering recommendation**: the brief's
   criterion-3 verdict with its specific blocker (§6, restated on the
   recorded weight terms), and Codex's engineering recommendation on
   reproducibility and cost — never a visual-quality judgment.
8. **Gaps**: what could not be verified and what it would cost.

## 21. Review dispositions — fixes not taken, and why

| Proposed by the review | Disposition |
| --- | --- |
| Reach the cropper's real CPU branch through a spike-local subclass passing `Cropper(crop_cfg, flag_force_cpu=True)` | **Not taken.** D2 forbids reproducing upstream constructors; the pinned CPU-only runtime's provider fallback is documented upstream behaviour, is recorded per session (§8.3), and is declared not a stop (§7 step 2, §15.2) |
| Gate the §14 verdict on an achieved-delta ratio band (e.g. 0.7–1.3) | **Not taken.** The brief defines "materially more natural" perceptually and the PM-ratified M3 rule forbids objective pass scores; the ratio and clamp states are recorded, verified by QA and placed beside the PO's answers for the PM (§12–§14) |
| Lower the in-range floor to three versus keeping four | **Taken at three** (§10, §14): only four stills can be in range, so four had no slack; three keeps one |
| Fetch the model card through the weights download by dropping upstream's `--exclude` | **Not taken** as written; the card is fetched by a separate recorded command (§7 step 1b) so the weights download stays exactly the upstream form plus `--revision` and the human-only `--include` |
| Commit fixture renders as the one visual example | **Conditional** (§4.3): only if the recorded weight terms permit redistribution of outputs |
| Name a PM-authored empty commit as the plan acknowledgement | **Not taken**; the PM's reply is quoted with its timestamp in `plan-freeze.json` and checked against the phase log (§9.3, §13 step 4), which needs no PM git action |
