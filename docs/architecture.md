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

The main window starts processing and capture workers once. Camera selection writes
a latest-value control request. The capture worker releases the old source on its
own thread, opens the newest request, and resumes publishing. Each frame includes
the request generation, so an in-flight frame from a previous camera is rejected
after a switch. A discovery refresh waits for the capture worker's idle signal
before probing, so it does not race the camera that is being released.

Individual read failures enter a degraded state with a short wait. At the configured
failure threshold, the source is released and reopened after a bounded delay. Open
failures also retry without a high-CPU loop; another selector choice remains usable.

On window close, timers stop, discovery is cancelled and joined, capture and
processing are asked to stop, and both workers are joined. Capture gets a short
grace period so an ordinary read can return and the owning thread can release its
source safely. A best-effort external release is used only if an open/read remains
blocked. Timeouts are logged explicitly rather than silently hiding a stuck camera
driver.

## Backend and discovery policy

On Windows the default preference is Media Foundation (`CAP_MSMF`) followed by
DirectShow (`CAP_DSHOW`). Discovery probes a bounded range of numerical indexes and
requires a successful frame read before exposing a candidate. The backend that
validated a candidate is tried first during capture, while the other remains a
fallback.

This mechanism is intentionally described as validated index probing, not native
Windows device enumeration. It cannot provide stable device IDs or friendly OS
camera names.

## Processing seam

`FrameProcessor.process(frame)` is the only transformation contract in M0, and
`PassthroughProcessor` returns the input unchanged. Later milestones can replace
this object with tracking and gaze pipeline work on the existing processor thread;
camera capture, latest-frame behavior, UI polling, and lifecycle ownership remain
unchanged. The live runtime remains the Milestone 0 passthrough implementation.

## Standalone tracking boundary

Milestone 1 introduces `gazefix.tracking` without changing the capture or worker
lifecycle. `FaceTracker.track` consumes one immutable BGR frame and returns only
application-owned tracking metadata. The MediaPipe adapter converts into private
RGB storage, and provider objects do not cross the package boundary. Debug overlay
rendering is an explicit development-only operation that creates a detached frame.

Runtime wiring into `FrameProcessor` is deliberately deferred until the parallel
Milestone 0 camera-hardening work is reviewed. The intended integration is a
processor implementation that retains the original frame, invokes one initialized
tracker on the existing processor thread, publishes/stores the latest
`TrackingResult`, and returns either the original frame or an opt-in debug-overlay
copy. Tracker loss or exceptions must never stop frame publication.

`gazefix.tracking.offline_validation` is a separate file-only diagnostic seam. It
owns a tracker only for the duration of one still-image or prerecorded-video run,
uses OpenCV only to decode/encode files, and cannot accept a camera index. It does
not alter `PipelineRuntime`, `FrameProcessor`, capture workers, latest-frame
buffers, camera recovery, or application shutdown wiring.

See [tracking.md](tracking.md) for topology, failure semantics, metrics, and the
dependency decision.
