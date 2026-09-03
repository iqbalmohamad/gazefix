# GazeFix — Milestone 0

GazeFix Milestone 0 is a local Windows desktop prototype that discovers validated
OpenCV camera candidates, lets the user select and switch cameras, and displays a
responsive live preview. It contains no gaze correction, tracking, ML inference,
virtual-camera output, telemetry, or cloud processing.

## Requirements

- Windows 10 or 11
- Python 3.11 or newer (64-bit recommended)
- A webcam allowed by **Windows Settings → Privacy & security → Camera**

The M0 runtime dependencies are PySide6, OpenCV, and NumPy. pytest is installed
only by the `dev` optional dependency.

| Dependency | Declared range | M0 purpose | Package license metadata |
| --- | --- | --- | --- |
| PySide6 | `>=6.7,<7` | Windows desktop UI and thread-safe signals | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| opencv-python | `>=4.10,<5` | Webcam capture and Windows backend access | Apache-2.0 |
| NumPy | `>=1.26,<3` | Typed frame-array representation | BSD-3-Clause and bundled component licenses |
| pytest (development only) | `>=8,<10` | Hardware-independent automated tests | MIT |

## Environment setup

From PowerShell in the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[dev]"
```

Python 3.11 can be substituted for 3.12. The application declares compatibility
with Python `>=3.11`.

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

## Run tests

```powershell
.venv\Scripts\python -m pytest
```

The automated suite uses fake camera sources and does not require webcam hardware.

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
- **Processing:** measured time inside the current passthrough processing stage;
  it excludes buffer wait time and UI presentation.
- **Replaced frames:** unread values overwritten in the capture and preview buffers.

Structured JSON-line logs rotate locally at:

```text
%LOCALAPPDATA%\GazeFix\logs\gazefix.jsonl
```

Logs contain lifecycle and diagnostic metadata, never raw frames. Webcam frames
remain in local process memory and are never transmitted.

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
details.
