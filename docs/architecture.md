# Milestone 0 Architecture

## Data flow

```text
OpenCV camera source (capture worker)
                 ↓
       latest-captured-frame buffer
                 ↓
      passthrough processor worker
                 ↓
       latest-output-frame buffer
                 ↓
        Qt timer-driven preview
```

Both buffers contain at most one value. Publishing replaces an unread value and
increments a replacement counter; producers never wait for consumers and old
frames cannot accumulate. The UI polls for a newer output sequence instead of
receiving one queued Qt event per frame. If display is slower than capture or
processing, it therefore presents the freshest available output.

## Frame ownership

OpenCV supplies a distinct NumPy array for each successful `read`. The capture
worker marks that array read-only before publishing it. Milestone 0's passthrough
processor shares the same immutable array without copying. A future processor that
mutates pixels must create its own output array. The preview builds a detached
`QImage.copy()` before the NumPy reference can be replaced, so Qt owns the displayed
pixels safely.

## Threads and lifecycle

- The Qt main thread owns widgets, timers, pixmap creation, and display metrics.
- The camera-discovery thread performs potentially blocking index validation.
- The long-lived capture thread owns camera open/read/release and automatic retry.
- The processor thread waits for and processes only the latest captured frame.

Capture state explicitly moves through idle, starting, running, degraded, retrying,
error, stopping, and stopped states. Status changes cross into Qt using signals;
workers never touch widgets.

### Camera requests are generations

The main window starts processing and capture workers once. Camera selection writes
a latest-value control request and receives a generation id. Everything the capture
worker produces for that request carries the id:

- Each frame includes the generation, so an in-flight frame from a previous camera
  is dropped by the worker before publishing and, as a second line of defence,
  rejected by `PipelineRuntime.consume_latest_output`.
- Each `CaptureStatus` includes the generation. Statuses of different generations
  are therefore never de-duplicated against each other, and the UI ignores a status
  whose generation is older than its latest request. A Refresh pressed while the
  worker is already idle still receives the idle status it waits for.
- A request that arrives while the worker is blocked inside `source.open()`
  interrupts that open. The worker checks for supersession before and after every
  open, and a superseded open ends silently: no ERROR, RUNNING, or retry delay is
  produced for a camera the user has already left.

The worker releases the old source on its own thread, opens the newest request, and
resumes publishing. Applying a request also consumes the wake-up event that
carried it, so a request that landed during a read cannot shorten a later retry
wait. A discovery refresh waits for the capture worker's idle signal before
probing, so it does not race the camera that is being released; the UI reports
"releasing camera" until probing actually starts. The refresh remembers the
camera that was selected: discovery keeps that index open when it validates, and
the selection returns to it instead of always falling back to the first entry.

### Warm handoff from discovery

Discovery opens and validates every probed index. The first validated camera is
not released: it travels to the UI inside `DiscoveryResult.prepared` as a
`PreparedCamera`, a one-shot ownership token. When the UI auto-selects that
candidate it passes the token to `select_camera`, and the capture worker adopts the
already-open source instead of opening the camera a second time. Ownership rules:

- `claim()` hands the source to exactly one caller; later claims return nothing.
- The capture worker closes, on its own thread, any prepared camera whose request
  was superseded before it was applied, and any prepared camera for a device other
  than the one requested.
- The discovery service closes an unclaimed prepared camera when it stops or when
  the next discovery run starts, so a token nobody adopted can never leak.

The OpenCV source object is created on the discovery thread and read on the
capture thread, never concurrently; that is the same ownership pattern as creating
a `VideoCapture` on a main thread and reading it on a worker.

### Failure handling

Individual read failures enter a degraded state with a short wait. At the configured
failure threshold, the source is released and reopened after a bounded delay; each
freshly opened source gets the full transient allowance again. A failed read that
took at least `stalled_read_s` is a stall, not a dropped frame (a Media Foundation
read waits 10 s internally before it fails), and triggers the reopen at once rather
than after five such waits. Open failures retry with exponential backoff from
`reconnect_delay_s` up to `reconnect_delay_max_s`, keep the error text on screen
instead of flickering through "Opening" on every attempt, and never spin; another
selector choice remains usable. An exception raised by `read()` counts as a failed
read and an exception raised by `close()` is logged and ignored; neither ends the
capture thread, so every camera failure stays recoverable from the selector.

`OpenCVCameraSource.open` succeeds only after the backend has also delivered a
frame, within `discovery_validation_reads` reads and `open_validation_timeout_s`
of wall clock. A backend that opens but never streams (a known Media Foundation
failure mode) is treated as an open failure and the next backend is tried. The
worker remembers which backend actually delivered frames and starts the next
reopen from it; after a stall or repeated read failures it demotes that backend so
the reopen tries the other one first. Backend fallback therefore works from the
steady-state read loop as well as inside a single open, and a fallback is never
permanent: every open starts from the current preference and the platform order.

### Shutdown

On window close, timers stop, discovery is told to stop, capture and processing are
asked to stop, and all workers are joined against a single deadline
(`worker_join_timeout_s`) rather than one timeout per worker in sequence. Capture
gets a short grace period so an ordinary read can return and the owning thread can
release its source safely.

What can and cannot be cancelled:

- A request or stop that arrives while the worker is inside `open()` sets an
  interrupt flag. `open()` checks it between backend attempts and validation reads
  and gives up at the next checkpoint.
- The blocking driver call inside `cv2.VideoCapture.open` itself cannot be cancelled
  from another thread. OpenCV attaches the backend object only after that call
  returns, so releasing the `VideoCapture` from elsewhere does nothing to the call
  and would only race its completion. The opening thread discards the capture as
  soon as control comes back.
- No thread other than the owner ever releases a `VideoCapture`. Releasing under a
  running `read` or `set` destroys the Media Foundation source reader and its
  callback beneath the call (`cap_msmf.cpp`, `close()`), which is a crash rather
  than a cancellation. A read that ignores the stop request therefore returns on
  the backend's own timeout (10 s Media Foundation, 1 s DirectShow) and the
  worker releases the camera itself immediately afterwards.
- The window hides itself before the joins, so a stuck driver delays process exit
  but never shows a frozen window. `stop()` reports `False` when a worker is
  abandoned inside a driver call; the daemon thread then ends with the process.

Timeouts are logged explicitly rather than silently hiding a stuck camera driver.

## Backend and discovery policy

On Windows the default preference is Media Foundation (`CAP_MSMF`) followed by
DirectShow (`CAP_DSHOW`). Discovery probes a bounded range of numerical indexes and
requires a successful frame read before exposing a candidate. The backend that
validated a candidate is tried first during capture, while the other remains a
fallback; a fallback to DirectShow lasts only until the next open, when MSMF is
tried first again.

This mechanism is intentionally described as validated index probing, not native
Windows device enumeration. It cannot provide stable device IDs or friendly OS
camera names.

### Camera open cost on Windows

Opening a camera through OpenCV's Media Foundation backend is the slow operation in
this pipeline, and Milestone 0 is designed to perform it as rarely as possible:

- With OpenCV's default settings, Media Foundation negotiates hardware transforms
  while the source reader is created inside `VideoCapture.open`. This is the
  documented cause of multi-second (up to minutes) MSMF opens on some machines.
  GazeFix exports `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0` at process start
  (`msmf_hw_transforms` setting, `--msmf-hw-transforms` flag) from a module that
  does not import `cv2`, and both entry points import OpenCV only afterwards: an
  OpenCV build with a statically linked C runtime snapshots the environment when
  it loads, so the variable must exist before the import. OpenCV itself reads it
  on every open without caching (`system.cpp`, `getConfigurationParameterBool`).
- Every `set()` of width, height, or FPS after an MSMF open renegotiates the stream
  format even when the value is unchanged. The source now reads each property first
  and sets only those that differ from the request, so a camera whose default
  format already matches costs no renegotiation. DirectShow instead rebuilds its
  capture graph on every such `set`, so it receives the format as open parameters
  and builds the graph once.
- A backend that opens but never streams costs one bounded validation instead of
  three full backend waits before the next backend is tried.
- The warm handoff above removes the second open of the selected camera at startup
  and on every Refresh.
- A superseded open no longer costs a further retry delay.

Every open, release, and probe logs its duration (`open_ms`, `configure_ms`,
`first_frame_ms`, `release_ms`, `probe_ms`, `discovery_ms`) together with the
backend requested and reported and the value of the hardware-transform switch, so a
run on physical hardware shows where the time goes without extra tooling. The
diagnostic tool reports the same timings per index and backend and accepts
`--msmf-hw-transforms 0|1` for an A/B comparison on the same machine.

## Processing seam

`FrameProcessor.process(frame)` is the only transformation contract in M0, and
`PassthroughProcessor` returns the input unchanged. Later milestones can replace
this object with tracking and gaze pipeline work on the existing processor thread;
camera capture, latest-frame behavior, UI polling, and lifecycle ownership remain
unchanged. No future-milestone algorithm or dependency is included now.
