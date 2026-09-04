# ADR-0001: MediaPipe Face Landmarker as the M1 tracking backend

**Status:** accepted for M1 (2026-09-04). **Decides:** which face/eye landmark
tracker GazeFix integrates in Milestone 1, and the dependency changes it forces.

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
the tested release **1.0.1**) with the official `face_landmarker.task` bundle
(float16, release 1), CPU delegate, video running mode, blendshapes disabled.
The tracker sits behind GazeFix's own `FaceTracker` protocol so that the
contract, overlay, tests and pipeline never import MediaPipe.

## Evidence recorded at adoption

| Item | Verified value |
| --- | --- |
| Package | `mediapipe` 1.0.1 on PyPI, uploaded 2026-08-14; previous 1.0.0 (2026-07-27) and 0.10.35 (2026-04-27) |
| Wheels | `py3-none-win_amd64`, `py3-none-win_arm64`, `py3-none-manylinux_2_28_x86_64`/`aarch64`, `py3-none-macosx_11_0_arm64` |
| Python | classifiers 3.9–3.12; tested here on 3.11.15 |
| Code licence | Apache-2.0 (package metadata and repository `LICENSE`) |
| Model licence | Apache License 2.0, stated on each model card in the bundle: BlazeFace short-range (face detector), Face Mesh V2 (landmarks, iris), Blendshape V2 (present in the bundle, not executed) |
| Model file | size 3,758,596 bytes, SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`, object last modified 2023-05-03 |
| CPU | XNNPACK CPU delegate; 1280×720, one face: ~14 ms median on a 4-core Xeon 2.8 GHz (Linux); no GPU/NPU/network used |
| Windows DLL | `libmediapipe.dll` (x64) imports Windows system DLLs only (kernel32, advapi32, user32, bcrypt, dbghelp, ntdll, wininet, api-ms-win-core-*); no OpenGL/EGL and no separate MSVC runtime DLL; contains the `play.googleapis.com/log` endpoint string (consequence 7) |
| Windows OpenCV | `opencv_contrib_python-4.14.0.94-cp37-abi3-win_amd64` `cv2.pyd` build info: Media Foundation YES, DirectShow YES, DXVA YES; `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS` present; bundles `opencv_videoio_ffmpeg4140_64.dll` — the M0 backends and switch exist in the contrib build |
| Windows resolution | pip resolves (win_amd64, CPython 3.12, 2026-09-04): mediapipe 1.0.1, opencv-contrib-python 4.14.0.94, numpy 2.5.2, PySide6 6.11.2, absl-py 2.5.0, flatbuffers 25.12.19, sounddevice 0.5.6, cffi 2.1.1, matplotlib 3.11.1, pillow 12.3.0 (full list: `constraints-windows-py312.txt`) |
| Linux .so | additionally links `libEGL.so.1` and `libGLESv2.so.2` (system packages) even for CPU inference |
| Project status | actively released (three releases in 2026); classifier still "Development Status :: 3 - Alpha", as it has been for every MediaPipe release |

## Consequences

1. **OpenCV variant.** `mediapipe` requires `opencv-contrib-python` (unpinned;
   the current release resolves to OpenCV 5.0). `opencv-python` and
   `opencv-contrib-python` both install the `cv2` package and cannot coexist.
   The project dependency therefore changes from `opencv-python>=4.10,<5` to
   `opencv-contrib-python>=4.10,<5`: the same upstream build plus the contrib
   modules, same Apache-2.0 licence, kept below OpenCV 5 so the M0-validated
   Media Foundation / DirectShow capture behaviour is unchanged. Verified
   resolution: opencv-contrib-python 4.14.0.94 (abi3 win_amd64 wheel).
2. **Transitive packages.** absl-py, flatbuffers, certifi, sounddevice (+cffi;
   bundles PortAudio, never used by GazeFix), matplotlib (+pillow, fonttools,
   contourpy, kiwisolver, cycler, pyparsing, python-dateutil, six) — imported
   by MediaPipe's drawing utilities at import time (~0.5 s). GazeFix imports
   MediaPipe only on the tracker thread, never on the Qt thread.
3. **Legacy API gone.** `mediapipe.solutions` (the old FaceMesh API) no longer
   exists in 0.10.35/1.0.x; only the Tasks API is used.
4. **No confidence score from the backend.** The Tasks API applies its
   detection/presence/tracking thresholds internally and reports no per-face
   score; GazeFix exposes a documented geometric quality signal instead
   (docs/tracking.md) and never fabricates a model probability.
5. **Model provisioning is explicit.** The bundle is downloaded once by
   `scripts/fetch_model.py`, verified by size and SHA-256, and read offline
   at runtime; the application never downloads.
6. **Pin.** `mediapipe==1.0.1` is a hard pin because it is an alpha-classified
   ctypes binding whose only tested version is this one. Upgrades go through
   a new tested release, not a range.
7. **Network activity inside the library (escalated).** The library contains
   an HTTP logging client and contacts `play.googleapis.com` (Clearcut usage
   logging) on every landmarker `close()`, uploading session/invocation
   statistics and system information — never frames (payload types verified
   from the binary; GazeFix passes only in-memory frames). It is not
   disclosed in the package metadata and has no API switch. The Windows
   build uses WinINet (system proxy settings); Linux uses libcurl. GazeFix
   closes the landmarker at exit and on error-driven rebuilds only (at most
   3 per camera generation), resets state on camera changes instead of
   rebuilding, discloses the behaviour in the README and
   `docs/tracking.md`, and escalates the decision (accept with disclosure,
   block at the firewall, pin 0.10.21 which has no logging client, or
   change backend) to the Product Manager. See the M1 report.
8. **Python range.** `requires-python = ">=3.11,<3.13"`: MediaPipe 1.0.1
   ships `py3-none` wheels without a `Requires-Python` marker, so nothing
   else would stop an untested 3.13/3.14 install.
9. **Environment upgrade.** Installing over an M0 environment leaves
   `opencv-python` and `opencv-contrib-python` both registered over one
   `cv2` directory; recreate the environment (README) — the tracker logs
   `opencv_duplicate_distributions` when it detects this.

## Alternatives considered

- **OpenCV-only (YuNet + Facemark LBF, contrib):** 68 landmarks, no iris, no
  eyelid detail comparable to the 478-point mesh, lower stability; would not
  satisfy PR-3's iris/eyelid needs.
- **dlib 68-point shape predictor:** BSL code licence but the widely used
  model was trained on iBUG 300-W, which restricts commercial use; no iris.
- **InsightFace / research landmark models:** research-only model licences.
- **MediaPipe 0.10.35 instead of 1.0.1:** same API and same measured
  behaviour here; 1.0.x is the currently maintained line.
