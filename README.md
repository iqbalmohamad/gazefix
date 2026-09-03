# GazeFix — Milestone 0 with standalone Milestone 1 tracking

GazeFix Milestone 0 is a local Windows desktop prototype that discovers validated
OpenCV camera candidates, lets the user select and switch cameras, and displays a
responsive live preview. The repository also contains an isolated Milestone 1
face/eye/iris tracking foundation, which is not yet wired into the live preview.
It contains no gaze estimation, gaze correction, calibration, virtual-camera
output, or cloud inference.

## Requirements

- Windows 10 or 11
- Python 3.11 or 3.12 (64-bit)
- A webcam allowed by **Windows Settings → Privacy & security → Camera**

The M0 runtime uses PySide6, OpenCV, and NumPy. Milestone 1 adds the pinned
MediaPipe Face Landmarker package. pytest is installed only by the `dev` optional
dependency.

| Dependency | Declared range | Purpose | Package license metadata |
| --- | --- | --- | --- |
| PySide6 | `>=6.7,<7` | Windows desktop UI and thread-safe signals | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| opencv-contrib-python | `>=4.10,<5` | Webcam capture and development overlay drawing; selected as the single OpenCV distribution required by MediaPipe | Apache-2.0 |
| NumPy | `>=1.26,<3` | Typed frame-array representation | BSD-3-Clause and bundled component licenses |
| MediaPipe | `==0.10.35` | CPU face, eye, and iris landmark inference | Apache-2.0 |
| pytest (development only) | `>=8,<10` | Hardware-independent automated tests | MIT |

## Environment setup

From PowerShell in the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[dev]"
```

Python 3.11 can be substituted for 3.12. The application intentionally caps
Python below 3.13 to match the MediaPipe package versions verified for this
milestone.

## Run the application

```powershell
.venv\Scripts\python -m gazefix
```

Optional capture settings:

```powershell
.venv\Scripts\python -m gazefix --width 1280 --height 720 --fps 30 --probe-limit 5
```

The UI first validates bounded numerical OpenCV indexes, then selects the first
candidate that both opens and returns a frame. Use the selector to switch without
restarting, or **Refresh** after connecting a camera or changing privacy settings.

## Run tests

```powershell
.venv\Scripts\python -m pytest
```

The automated suite uses fake camera sources and does not require webcam hardware.

## Standalone face tracking foundation

`gazefix.tracking` provides provider-neutral immutable results, an injectable
`FaceTracker` protocol, a CPU MediaPipe adapter, deterministic primary-face
selection, tracking diagnostics, and an opt-in debug overlay. The tracker accepts
BGR `uint8` frames and returns metadata without modifying the frame.

The MediaPipe model is intentionally not committed. Obtain the versioned official
model and verify its digest before local experiments. The tracking validator can
perform this explicit, integrity-checked provisioning step:

```powershell
.venv\Scripts\gazefix-tracking-validate.exe portrait.jpg --download-model
```

To provision it manually instead:

```powershell
New-Item -ItemType Directory -Force .models | Out-Null
Invoke-WebRequest `
  -Uri "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" `
  -OutFile ".models\face_landmarker.task"
Get-FileHash -Algorithm SHA256 ".models\face_landmarker.task"
```

Expected SHA-256:

```text
64184E229B263107BC2B804C6625DB1341FF2BB731874B0BCC2FE6544E0BC9FF
```

Run the real tracker without opening a webcam:

```powershell
.venv\Scripts\gazefix-tracking-validate.exe portrait.jpg
.venv\Scripts\gazefix-tracking-validate.exe recording.mp4 `
  --input-kind video `
  --overlay-output .tracking-output\recording-overlay.mp4
```

The JSON report separates tracking latency from file-processing throughput.
Offline throughput includes file decode and any requested overlay/write work; it
must not be reported as live webcam FPS.

See [docs/tracking.md](docs/tracking.md) for the API, coordinate semantics,
failure states, model provenance, offline validator, and deferred integration
contract. See [docs/m1-physical-verification.md](docs/m1-physical-verification.md)
for the checklist to execute after live pipeline integration exists.

## Run camera diagnostics

After the editable install above:

```powershell
.venv\Scripts\python scripts\camera_test.py
```

To shorten the probe or sample interval:

```powershell
.venv\Scripts\python scripts\camera_test.py --max-index 1 --duration 1
```

The tool reports one JSON object per index/backend combination, including whether
it opened, requested and reported backend, negotiated size/FPS, observed sample
FPS, successful reads, and failed reads. It releases every camera before exiting.

## Windows camera behavior

GazeFix prefers OpenCV Media Foundation (`MSMF`) and falls back to DirectShow
(`DSHOW`). A backend that worked during discovery is tried first when selected.
This ordering is a prototype policy and should be revisited with a representative
Windows hardware matrix.

OpenCV numerical index probing is **not authoritative Windows device enumeration**.
Labels such as `Camera index 0` are validated candidates for the current run, not
stable device names or IDs. Availability and index assignment can change after a
reboot, reconnect, driver update, or use by another application.

## Diagnostics and privacy

The UI defines metrics as follows:

- **Capture FPS:** successful camera reads per second over a rolling window.
- **Display FPS:** new frames actually presented by the Qt preview per second.
- **Processing:** measured time inside the current passthrough processing stage;
  it excludes buffer wait time and UI presentation.
- **Replaced frames:** unread values overwritten in the capture and preview buffers.

Structured JSON-line logs rotate locally at:

```text
%LOCALAPPDATA%\GazeFix\logs\gazefix.jsonl
```

Logs contain lifecycle and diagnostic metadata, never raw frames. GazeFix code
passes frames only to local OpenCV/MediaPipe APIs and contains no frame-upload or
cloud-inference path.

See [docs/architecture.md](docs/architecture.md) for the pipeline and shutdown
details.
