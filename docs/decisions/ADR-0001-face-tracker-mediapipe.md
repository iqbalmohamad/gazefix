# ADR-0001: MediaPipe Face Landmarker as the M1 tracking backend

**Status:** accepted for M1 (2026-09-04); **revised 2026-09-04** after QA, to
pin `mediapipe==0.10.21` instead of `1.0.1`. **Decides:** which face/eye
landmark tracker GazeFix integrates in Milestone 1, and the dependency
changes it forces.

## Context

PR-3 needs facial landmarks, left/right eyes with eyelid contours, iris
position where available, face orientation, stable tracking during normal head
movement, and a truthful quality signal, on a CPU-only Windows laptop with
local processing. The PRD names MediaPipe as the preferred (not mandatory)
option. The dependency policy requires verified project status, Windows and
Python compatibility, CPU support, separate code and model licences, and
redistribution terms before adoption.

## Decision

Use the MediaPipe **Tasks** `FaceLandmarker` (package `mediapipe`, pinned to
the tested release **0.10.21**) with the official `face_landmarker.task`
bundle (float16, release 1), CPU delegate, video running mode, blendshapes
disabled. The tracker sits behind GazeFix's own `FaceTracker` protocol so
that the contract, overlay, tests and pipeline never import MediaPipe.

**Why 0.10.21 and not the current 1.0.1.** The 1.0.x line contains an HTTP
usage-logging client that uploads to `play.googleapis.com` on every
landmarker `close()`, with no API switch and no disclosure in the package
metadata. The Product Manager rejected "disclose it and ask the user to
configure a firewall" as the default answer for a product whose stated
principle is local-only processing. 0.10.21 is the last release without
that client, and it was validated to be equivalent for this milestone's
purpose (evidence below). The cost is an older, no-longer-updated release
and a heavier declared dependency set; both are recorded under
Consequences.

## Evidence recorded at adoption

| Item | Verified value |
| --- | --- |
| Package | `mediapipe` 0.10.21 on PyPI, uploaded 2025-02-06 (the last release before the 1.0.x logging client) |
| Wheels | `cp39/cp310/cp311/cp312` × `win_amd64`, `manylinux_2_28_x86_64`, `macosx_11_0` (universal2 and x86_64). No `win_arm64` wheel; the target is x64 |
| Python | classifiers 3.9–3.12, `Requires-Python` unset; tested here on 3.11.15, resolved for 3.12 on Windows |
| Code licence | Apache-2.0 (package metadata and repository `LICENSE`) |
| Model licence | Apache License 2.0, stated on each model card in the bundle: BlazeFace short-range (face detector), Face Mesh V2 (landmarks, iris), Blendshape V2 (present in the bundle, not executed) |
| Model file | size 3,758,596 bytes, SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`, object last modified 2023-05-03 |
| CPU | XNNPACK CPU delegate; 1280×720, one face: 14.3 ms median on a 4-core Xeon 2.8 GHz (Linux), against 12.9 ms for 1.0.1 on the same fixture |
| Output equivalence | Same model file, same 478-landmark topology. Across 13 poses of the licensed fixture the per-landmark difference between 0.10.21 and 1.0.1 is at most **0.006 px** at 1280×720 and the rotation-matrix elements differ by at most 3.8e-05; neither version lost the face |
| Network (Linux, syscall trace) | `strace -f -tt -yy -e trace=%network` over a full lifecycle (import, create, 30 s / 1849 inference frames, 15 s idle, reset, close, rebuild, close, 5 s post-close): **zero network syscalls in every phase**. The same trace of 1.0.1 shows a TLS session to `play.googleapis.com` inside each of its two `close()` calls. A deliberate connection at the end of both runs is a positive control proving the trace captures connects |
| Network (Windows, static) | The 0.10.21 `.pyd` files (`_framework_bindings`, `_pywrap_metadata_version`, `_pywrap_flatbuffers`) import **no** network-capable Windows DLL in their PE import or delay-import tables (no wininet, winhttp, ws2_32, urlmon, secur32). 1.0.1's `libmediapipe.dll` imports `wininet` and contains the `play.googleapis.com/log` endpoint string |
| Threading | A 0.10.21 landmarker creates **no** Python threads; inference runs synchronously on the calling thread. 1.0.1 creates one non-daemon `ThreadPoolExecutor` worker per landmarker (see Consequences 10) |
| Windows OpenCV | `opencv_contrib_python-4.11.0.86-cp37-abi3-win_amd64` `cv2.pyd` build info: Media Foundation YES, DirectShow YES, DXVA YES; `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS` present; bundles `opencv_videoio_ffmpeg4110_64.dll` — the M0 backends and switch exist in the contrib build at the version the backend's `numpy<2` cap selects |
| Windows resolution | pip resolves (win_amd64, CPython 3.12, 2026-09-04): mediapipe 0.10.21, numpy 1.26.4, opencv-contrib-python 4.11.0.86, PySide6 6.11.2, absl-py 2.5.0, flatbuffers 25.12.19, protobuf 4.25.9, jax/jaxlib 0.7.1, scipy 1.17.1, sentencepiece 0.2.2, sounddevice 0.5.6, cffi 2.1.1, matplotlib 3.11.1, pillow 12.3.0 (full list: `constraints-windows-py312.txt`) |
| Linux .so | additionally links `libEGL.so.1` and `libGLESv2.so.2` (system packages) even for CPU inference |
| Project status | 0.10.21 is a February 2025 release and receives no further upstream fixes; the line has moved on to 1.0.x. Classifier "Development Status :: 3 - Alpha", as for every MediaPipe release |

## Consequences

1. **OpenCV and NumPy are capped by the backend.** `mediapipe` requires
   `opencv-contrib-python` (unpinned), and `opencv-python` and
   `opencv-contrib-python` both install the `cv2` package and cannot coexist,
   so the project dependency is `opencv-contrib-python>=4.10,<5` (same
   upstream build plus contrib modules, same Apache-2.0 licence, kept below
   OpenCV 5 so the M0-validated Media Foundation / DirectShow behaviour is
   unchanged). 0.10.21 additionally declares **`numpy<2`**, so pip resolves
   NumPy **1.26.4** and, because opencv-contrib-python 4.12+ require NumPy 2,
   OpenCV **4.11.0.86**. Both were verified from the real package metadata,
   not assumed: `pip install -e ".[dev]"` resolves cleanly (`pip check` clean)
   on Linux and for Windows x64 / CPython 3.12, and the full test suite passes
   on that set. The project keeps `numpy>=1.26,<3`; the effective cap is
   enforced by the backend's own metadata and recorded in
   `constraints-windows-py312.txt`.
2. **Transitive packages are heavier than 1.0.x.** 0.10.21 declares absl-py,
   attrs, flatbuffers, **jax**, **jaxlib**, matplotlib, protobuf (<5),
   **sentencepiece**, sounddevice, and opencv-contrib-python; jaxlib pulls
   scipy and ml_dtypes. Installed size roughly 983 MB against 1.2 GB for the
   1.0.1 set (jaxlib 330 MB, scipy 113 MB, mediapipe 67 MB). Measured at
   runtime, `import mediapipe` does **not** import jax, jaxlib, scipy or
   sentencepiece — they are disk cost, not import or memory cost; import
   takes ~0.58 s, comparable to 1.0.1. GazeFix imports MediaPipe only on the
   tracker thread, never on the Qt thread.
3. **Legacy API present but unused.** 0.10.21 still ships
   `mediapipe.solutions` (the old FaceMesh API) alongside Tasks; GazeFix uses
   only the Tasks API.
4. **No confidence score from the backend.** The Tasks API applies its
   detection/presence/tracking thresholds internally and reports no per-face
   score; GazeFix exposes a documented geometric quality signal instead
   (docs/tracking.md) and never fabricates a model probability.
5. **Model provisioning is explicit.** The bundle is downloaded once by
   `scripts/fetch_model.py`, verified by size and SHA-256, and read offline
   at runtime; the application never downloads.
6. **Pin.** `mediapipe==0.10.21` is a hard pin: it is the last release
   without the usage-logging client, and moving off it must be a deliberate,
   re-validated decision rather than a range that drifts into 1.0.x. It is a
   February 2025 release, so it will not receive upstream security fixes;
   this is the main cost of the decision and is listed as a known limitation
   in the milestone report. Revisit if a CVE affects it, if a later release
   removes the logging client, or before M10/productization.
7. **Network activity: resolved by the version choice, not by disclosure.**
   1.0.1 contacts `play.googleapis.com` on every landmarker `close()`.
   0.10.21 was observed making **no** network syscalls across a full
   lifecycle on Linux, and its Windows binaries link no network-capable
   API (evidence table above). GazeFix therefore performs no network access
   at runtime on the chosen backend; the only network step in the project is
   the explicit `scripts/fetch_model.py` setup command. **Limitation:** the
   syscall observation is Linux-only. Windows runtime behaviour is **NOT
   VERIFIED** — the static import-table check is strong but cannot exclude a
   library loading a networking DLL dynamically at runtime, so a Windows
   confirmation (Resource Monitor or a packet capture during a session)
   remains a Product Owner check.
8. **Python range.** `requires-python = ">=3.11,<3.13"`: MediaPipe 0.10.21
   publishes no `Requires-Python` marker at all (classifiers 3.9–3.12 only),
   so nothing in its metadata would stop an untested 3.13/3.14 install; the
   project's own cap is what does. Its newest ABI-specific wheel is `cp312`,
   so on 3.13 the install would in practice fail to find a wheel rather than
   silently proceed — but the cap is the deliberate statement of what was
   tested, and it stays.
9. **Environment upgrade.** Installing over an M0 environment leaves
   `opencv-python` and `opencv-contrib-python` both registered over one
   `cv2` directory; recreate the environment (README) — the tracker logs
   `opencv_duplicate_distributions` when it detects this.
10. **Shutdown is simpler on this backend.** 1.0.1 ran every native call on a
   non-daemon `ThreadPoolExecutor` thread that CPython joins at interpreter
   exit, so a call that never returned could hang the process; that is why
   the entry point previously ended with a forced `os._exit`. 0.10.21 adds
   no Python threads and runs inference synchronously on the caller's
   thread, which in GazeFix is a daemon. A wedged call therefore cannot hold
   the process open, the forced termination has been removed, and shutdown
   now always runs normal interpreter finalisation. See the M1 report's
   shutdown assessment.
11. **Windows packaging note.** The 0.10.21 Windows wheel bundles its own
   `opencv_world3410.dll` inside `mediapipe/python/` for the library's
   internal C++ use. It has a distinct module name from the `cv2` package's
   OpenCV 4.11 binaries, so the two load side by side; GazeFix's capture
   path uses the `cv2` package only.

## Alternatives considered

- **OpenCV-only (YuNet + Facemark LBF, contrib):** 68 landmarks, no iris, no
  eyelid detail comparable to the 478-point mesh, lower stability; would not
  satisfy PR-3's iris/eyelid needs.
- **dlib 68-point shape predictor:** BSL code licence but the widely used
  model was trained on iBUG 300-W, which restricts commercial use; no iris.
- **InsightFace / research landmark models:** research-only model licences.
- **MediaPipe 1.0.1 (the previously chosen version):** current and
  maintained, and functionally equivalent for this milestone, but it uploads
  usage statistics on every `close()` with no opt-out. Rejected by the
  Product Manager: disclosure plus a manually configured firewall is not an
  acceptable default for a local-only product.
- **MediaPipe 0.10.35:** also contains the logging client (verified: the
  `HttpLoggingClient` symbols are present in its shared library), so it does
  not solve the problem.
