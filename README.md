# GazeFix — Milestones 0, 1 and 2

GazeFix is a local Windows desktop prototype that discovers validated OpenCV
camera candidates, lets the user select and switch cameras, displays a
responsive live preview (Milestone 0), and tracks the face of one person in
that preview: 478 facial landmarks, anatomically labelled left/right eyes with
eyelid contours, iris landmarks, head orientation, and a truthful quality
signal (Milestone 1). From that tracking it estimates an **approximate,
uncalibrated gaze direction** — yaw, pitch and a heuristic confidence —
derived from iris geometry rather than head pose (Milestone 2). Everything
runs on the CPU and entirely on the local machine. GazeFix's own code contains
no gaze correction, calibration, virtual-camera output, telemetry, or cloud
processing, and it makes no network connection at runtime (see "Diagnostics
and privacy").

The gaze estimate is **not eye tracking**: it has no calibration, no camera
intrinsics and no per-user anatomy, so treat its degrees as an indication of
how far the eyes are looking away from the camera, not as a measurement. See
[docs/gaze.md](docs/gaze.md) for the sign conventions, the model and its
measured limitations.

## Requirements

- Windows 10 or 11
- Python 3.11 or 3.12 (64-bit). The application declares `>=3.11,<3.13`
  because MediaPipe 0.10.21 is classified for Python 3.9–3.12 only.
- A webcam allowed by **Windows Settings → Privacy & security → Camera**
- The face landmarker model file, installed once by an explicit command (below)

Runtime dependencies are PySide6, OpenCV (contrib variant), NumPy, and
MediaPipe. pytest is installed only by the `dev` optional dependency.

| Dependency | Declared range | Purpose | Package license metadata |
| --- | --- | --- | --- |
| PySide6 | `>=6.7,<7` | Windows desktop UI and thread-safe signals | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| opencv-contrib-python | `>=4.10,<5` (resolves to 4.11.x) | Webcam capture, Windows backend access, colour conversion, overlay drawing. Replaces `opencv-python` because MediaPipe requires the contrib distribution and both provide `cv2` | Apache-2.0 |
| NumPy | `>=1.26,<3` (resolves to 1.26.x) | Typed frame-array representation | BSD-3-Clause and bundled component licenses |
| mediapipe | `==0.10.21` (tested release) | Face landmark tracking (Tasks `FaceLandmarker`, CPU) | Apache-2.0 |
| pytest (development only) | `>=8,<10` | Hardware-independent automated tests | MIT |

MediaPipe declares absl-py, attrs, flatbuffers, jax, jaxlib, matplotlib,
protobuf, sentencepiece and sounddevice; none is used by GazeFix directly and
jax, jaxlib, scipy and sentencepiece are never even imported at runtime (they
cost disk space, about 470 MB, not start-up time). MediaPipe 0.10.21 requires
`numpy<2`, which is why NumPy resolves to 1.26.x and OpenCV to 4.11.x. The
model file has its own Apache-2.0 licence; see `models/README.md` and
`docs/decisions/ADR-0001-face-tracker-mediapipe.md` for the full dependency
and model record, including why this version is pinned.

## Environment setup

From PowerShell in the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python scripts\fetch_model.py
```

Python 3.11 can be substituted for 3.12; the project declares `>=3.11,<3.13`
because MediaPipe 0.10.21 is classified for Python 3.9–3.12 only. **Upgrading an
existing M0 environment:** create a fresh `.venv` (recommended) or run
`pip uninstall -y opencv-python` first. pip does not notice that
`opencv-python` and `opencv-contrib-python` install the same `cv2` package;
installing one over the other leaves both registered and a later uninstall
of either breaks `cv2`. The tracker logs a warning
(`opencv_duplicate_distributions`) when it finds more than one.
`constraints-windows-py312.txt` lists the exact versions pip resolved for
Windows x64 / Python 3.12 on 2026-09-04; pass it with `-c` for a
reproducible install. The last command downloads the
face landmarker model (3.7 MB) from its documented official source into
`%LOCALAPPDATA%\GazeFix\models`, verifies its size and SHA-256, and prints a
JSON report; it is the only step in GazeFix's own code that uses the network
and it is never run by the application itself (the MediaPipe library's own
upload at close is described under "Diagnostics and privacy"). `--verify-only` checks an existing file without
downloading; `--model-dir` chooses another directory (then pass the same
`--model-dir` to the application).

## Run the application

```powershell
.venv\Scripts\python -m gazefix
```

Optional capture settings:

```powershell
.venv\Scripts\python -m gazefix --width 1280 --height 720 --fps 30 --probe-limit 5
```

The UI first validates bounded numerical OpenCV indexes, then selects the first
candidate that both opens and returns a frame. The camera that validated first is
kept open and handed to the capture worker, so it is not opened a second time.
Use the selector to switch without restarting, or **Refresh** after connecting a
camera or changing privacy settings.

If Media Foundation camera opens are slow on a machine, compare both settings of
the hardware-transform switch (GazeFix defaults to `0`, OpenCV's own default is
`1`):

```powershell
.venv\Scripts\python -m gazefix --msmf-hw-transforms 0
.venv\Scripts\python -m gazefix --msmf-hw-transforms 1
```

### Tracking, gaze and development mode

Tracking starts automatically. The consumer window shows only a
`Tracking:` metric (inference time and status word). Development mode adds
the debug controls:

```powershell
.venv\Scripts\python -m gazefix --dev            # overlay checkbox + tracking detail line
.venv\Scripts\python -m gazefix --dev --overlay  # start with the overlay on
.venv\Scripts\python -m gazefix --no-tracking    # M0 passthrough preview, no model loaded
.venv\Scripts\python -m gazefix --no-gaze       # track the face but do not estimate gaze
.venv\Scripts\python -m gazefix --model-dir D:\models
```

With the overlay off the preview shows the original camera pixels; with it
on, landmarks, eyelid contours (right eye cyan `R`, left eye yellow `L`,
anatomical sides), iris circles, head-pose axes ("head pose (not gaze)"), a
magenta gaze arrow from each iris and a status panel are drawn on a copy of
the frame. If the model file is missing or invalid the preview keeps running
and the `Tracking:` cell shows the reason and what to do
(`python scripts/fetch_model.py`), as do the detail line (`--dev`) and the
log. See `docs/tracking.md` for the tracking contract, coordinate
conventions, quality semantics and failure policy, and `docs/gaze.md` for the
gaze conventions and confidence.

Gaze angles are printed as whole degrees with an "approx, uncalibrated"
marker and the hint `+ = subject's left / up`. Note that gaze pitch is
positive UP while head-pose pitch is positive DOWN; the two are different
signals with different conventions and the overlay labels both.

## Run tests

```powershell
.venv\Scripts\python -m pytest
```

The automated suite uses fake camera sources and fake trackers; it needs no
webcam, no network and no model file (the real-model tests are skipped). To
run the real MediaPipe face landmarker on the licensed fixture image
(`tests/assets/astronaut_face.png`, public domain; see `tests/assets/README.md`)
after `scripts/fetch_model.py` has installed the model:

```powershell
$env:GAZEFIX_REAL_MODEL_TESTS = "1"
.venv\Scripts\python -m pytest tests\test_real_model_tracking.py
```

Set `GAZEFIX_MODEL_DIR` if the model lives outside the default directory.

## Run tracking diagnostics

After the model setup above, run the real tracker on the fixture image or on
a physical camera and get one JSON object with detection counts, validity,
head-pose and inference-time statistics:

```powershell
.venv\Scripts\python scripts\tracking_test.py --image tests\assets\astronaut_face.png
.venv\Scripts\python scripts\tracking_test.py --camera 0 --duration 10
```

The tool runs inference synchronously on its own thread (no bounded wait, no
stabilisation, no primary-face memory), so `inference_ms` is the pure backend
cost per frame; the application's `Tracking:` metric and the `runtime_metrics`
log line at close report the same inference time plus the processor wait,
`processing_ms`, and `pipeline_latency_ms` (capture timestamp to processed
frame). Exit code 0 means at least one frame was tracked.

## Run camera diagnostics

After the editable install above:

```powershell
.venv\Scripts\python scripts\camera_test.py
```

To shorten the probe or sample interval:

```powershell
.venv\Scripts\python scripts\camera_test.py --max-index 1 --duration 1
```

To measure the Media Foundation open cost with and without hardware transforms:

```powershell
.venv\Scripts\python scripts\camera_test.py --max-index 0 --duration 1 --msmf-hw-transforms 0
.venv\Scripts\python scripts\camera_test.py --max-index 0 --duration 1 --msmf-hw-transforms 1
```

The tool reports one JSON object per index/backend combination, including whether
it opened and validated, requested and reported backend, negotiated size/FPS,
observed sample FPS, successful reads, failed reads, and the measured `open_ms`,
`configure_ms` (the property reads that decide what to set, the sets that
follow, and the buffer hint; `format_sets_applied` counts the sets),
`first_frame_ms` (with `validation_reads`), and `release_ms`. It releases every camera before exiting,
also when interrupted with Ctrl+C (exit code 130). Exit code 0 means at least one
index/backend combination validated, 1 means none did, 2 means bad arguments.

Each probe opens, configures, and first-frame validates the camera through the
same code path and settings the application uses (`open_validated_backend` in
`gazefix/camera/source.py`), so `open_ms`, `configure_ms`, and `first_frame_ms`
have the same meaning as the `camera_opened` log fields written at runtime:
DirectShow receives the requested size as open parameters, width/height/FPS are
set only where the camera reports a different value, and FPS is never set on a
backend that does not report one. `--width`, `--height`, `--fps`, and
`--msmf-hw-transforms` feed the same settings object the application would use.

What the diagnostic intentionally does differently from the running application,
and what that means when reading the numbers:

- It probes every backend on its own and never falls back to the other one, so
  MSMF and DirectShow can be compared side by side. At runtime a backend that
  fails is followed by the next one, so a runtime open that falls back costs the
  failed attempt(s) plus the successful one.
- A backend that opens but delivers no validation frame is reported with
  `validated: false` and released without sampling, which is exactly what the
  application does with it.
- Sampling (`sample_seconds`, `successful_reads`, `failed_reads`, `observed_fps`)
  is a plain read loop that exists only in the tool; the application's capture
  worker adds degraded/retry handling on top of the same reads.
- `release_ms` is measured on the tool's thread; at runtime the capture worker
  thread releases. The application can also adopt the camera that discovery
  already validated instead of opening it again, so an application start may
  cost one open less than the sum of the probes.

## Windows camera behavior

GazeFix prefers OpenCV Media Foundation (`MSMF`) and falls back to DirectShow
(`DSHOW`). A backend that worked during discovery is tried first when selected, a
backend that opens but never delivers a frame counts as failed so the other one is
tried, and a backend that stops delivering frames while running is demoted for the
next reopen. The fallback is never permanent: MSMF is preferred again at the next
open. This ordering is a prototype policy and should be revisited with a
representative Windows hardware matrix.

Opening a camera through MSMF is the slow operation in this application. GazeFix
sets `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0` at startup because hardware
transform negotiation during open is the documented cause of very slow MSMF opens
(OpenCV issue 17687); `--msmf-hw-transforms 1` restores OpenCV's default for
comparison. Every camera open, release, and probe is logged with its duration
(`open_ms`, `configure_ms`, `first_frame_ms`, `release_ms`, `probe_ms`,
`discovery_ms`) so slow hardware can be diagnosed from the log alone.

OpenCV numerical index probing is **not authoritative Windows device enumeration**.
Labels such as `Camera index 0` are validated candidates for the current run, not
stable device names or IDs. Availability and index assignment can change after a
reboot, reconnect, driver update, or use by another application.

## Diagnostics and privacy

The UI defines metrics as follows:

- **Capture FPS:** successful camera reads per second over a rolling window.
- **Display FPS:** new frames actually presented by the Qt preview per second.
- **Processing:** measured time inside the processing stage: for M1 the bounded
  wait for the frame's own tracking result plus overlay rendering; it excludes
  buffer wait time and UI presentation.
- **Replaced frames:** unread values overwritten in the capture and preview buffers.
- **Tracking:** smoothed tracker inference time (colour conversion plus the
  backend call on the tracker thread) and the status of the displayed frame's
  result, followed by the gaze status; `--dev` adds the total and waited
  times, the gaze estimation time, the pipeline latency (capture timestamp to
  processed frame), and timeout/error/replaced counters.
- **Gaze:** smoothed time inside the gaze estimator, measured on the tracker
  thread and already included in the tracking total. `--dev` also reports the
  approximate gaze angles, the confidence and each of its six factors, and
  the eye-in-head component that shows the estimate is not head pose.

Structured JSON-line logs rotate locally at:

```text
%LOCALAPPDATA%\GazeFix\logs\gazefix.jsonl
```

Logs contain lifecycle and diagnostic metadata, never raw frames. Webcam frames
remain in local process memory and are never transmitted; the tracker receives
an in-memory copy of each frame and the model file is read from disk. The only
network access in GazeFix's own code is the explicit `scripts/fetch_model.py`
command.

**No runtime network access.** GazeFix needs no network connection after
`scripts/fetch_model.py` has installed the model, and neither does its
tracking backend. This was checked rather than assumed: a full-lifecycle
syscall trace of MediaPipe 0.10.21 (import, model load, 30 s of continuous
inference, idle, state reset, close, rebuild, close) recorded **no network
syscalls at all**, with a deliberate connection at the end of the same trace
proving the measurement would have caught one. The MediaPipe 1.0.x line does
upload usage statistics when a landmarker is closed, which is the reason this
project pins 0.10.21; see `docs/tracking.md` section 13 and
`docs/decisions/ADR-0001-face-tracker-mediapipe.md`. The trace was taken on
Linux, so Windows runtime behaviour is not verified by it; the Windows
binaries link no networking API, but confirming that on the target machine is
a Product Owner check.

Closing the window waits at most `worker_join_timeout_s` in total. A camera
release is a driver call with no upper bound, so the window never performs one:
the capture worker releases its own camera on its thread, and a validated camera
that was never adopted is released by a small cleanup thread. Cleanup is
owner-scoped: the pipeline runtime owns one cleanup thread (its lifecycle state
reflects only its own work) and the window owns a second one for camera
discovery, and the window joins both within the same single deadline. If a
driver does not return in time the log says which owner still has work, and the
daemon thread ends with the process.

See [docs/architecture.md](docs/architecture.md) for the pipeline and shutdown
details, [docs/tracking.md](docs/tracking.md) for the tracking contract,
threads, overload policy and failure handling, and
[docs/gaze.md](docs/gaze.md) for the gaze model, sign conventions, confidence
heuristic and measured limitations.
