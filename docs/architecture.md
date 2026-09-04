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
- A request for the camera that is already open, or whose open is in flight, does
  not reopen it. The worker keeps the source and moves it to the new generation;
  an interrupt raised by an intermediate request is withdrawn (`reinstate`) when
  the newest request returns to the same camera, so flipping away and back during
  a slow open costs one driver open, not two.
- Publishing a request, waking the worker, and interrupting an in-flight open
  happen under one lock, the interrupt is bound to the generation that owns the
  open, and the worker consumes a request with its wake-up under the same lock.
  A wake-up therefore never goes stale and an interrupt never hits the open that
  serves the request being published.
- The terminal `STOPPING` and `STOPPED` statuses are both emitted by the worker
  thread, so consumers always see them in order.

The worker releases the old source on its own thread, opens the newest request, and
resumes publishing. Applying a request also consumes the wake-up event that
carried it, so a request that landed during a read cannot shorten a later retry
wait. A discovery refresh waits for the capture worker's idle signal before
probing, so it does not race the camera that is being released; the UI reports
"releasing camera" until probing actually starts. The discovery service counts as
running only until it has delivered its result, so a Refresh that lands while the
previous discovery thread is still exiting is honoured rather than dropped. The
refresh remembers the camera that was selected: discovery keeps the first
validated candidate open provisionally, replaces it with the remembered index when
that validates, and the selection returns to whichever was kept.

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
a `VideoCapture` on a main thread and reading it on a worker. Only Media
Foundation captures are handed over: OpenCV's DirectShow capture pairs
`CoInitialize` and `CoUninitialize` on the thread that creates and destroys it, so
a DirectShow-validated candidate is released by discovery and reopened by the
capture worker (a fast open on that backend).

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
asked to stop, and all workers and the prepared-camera cleanup thread are joined
against a single deadline (`worker_join_timeout_s`) rather than one timeout per
worker in sequence. Capture gets a short grace period so an ordinary read can
return and the owning thread can release its source safely.

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

### Runtime state is derived from what the runtime owns

`PipelineRuntime` records two facts of its own: that `stop()` (or a `start()`
that failed part-way) has been requested, and, once shutdown completed, that it
is final. Everything else is read from the things it owns when it is asked for
(`PipelineRuntime.state`): whether a worker thread has been started
(`Thread.ident`), whether one is alive, and whether a runtime-owned
prepared-camera release is still outstanding.

Cleanup is owner-scoped. The runtime creates its own cleanup thread in its
constructor and nothing else can submit work to it through the runtime's API;
discovery's cleanup lives on a separate closer owned by the window. Work owned
by discovery therefore cannot appear in, or mutate, the runtime's lifecycle.

```text
NEW       no worker thread started, stop() not requested
RUNNING   a worker thread started, stop() not requested
STOPPING  stop() requested; a worker thread is alive or a runtime-owned
          release is still outstanding
STOPPED   stop() requested; nothing runtime-owned is alive or outstanding.
          A latch: entered once, under the lifecycle lock, and never left.
```

`STOPPED` is monotonic by construction: it is reported only after the latch is
set, the latch is set only under the lifecycle lock when no owned worker is
alive and no runtime-owned release is outstanding, and it is never cleared.

Runtime-owned cleanup is counted along the whole chain a prepared camera
travels at shutdown, so the latch decision can never miss one in transfer:

```text
capture-worker slots        pending_prepared_count(): unclaimed tokens still
                            held in the worker's request/orphan slots
hand-off                    a counter raised, under the lifecycle lock, before
                            any token leaves the slots and lowered when the
                            transfer attempt ends, however it ends
runtime-retained storage    tokens extracted from the worker but not yet
                            accepted by the cleanup thread, held durably by
                            the runtime across failed attempts
cleanup thread              queued tokens plus the release in flight
```

Every step of the transfer is exception-safe. Extraction is transactional per
token: the worker appends a token to the runtime's retained storage first and
clears its slot only afterwards, so a failure mid-extraction leaves the
remainder worker-owned and everything already moved runtime-retained.
Registration is resumable: a token leaves retained storage only after the
cleanup thread accepted it, so a failure leaves the failed token and the
unsubmitted remainder retained, and the next `stop()` or `join_cleanup()`
(which re-attempts registration before waiting) picks up exactly where the
failed attempt stopped. A retry that re-submits a token the closer already
holds is a no-op thanks to the claim-once handover. An exception in the
transfer is logged (`prepared_handoff_error`) and never moves a token out of
ownership; interruption exceptions propagate normally with ownership intact.

At every instant a token accepted before finalization is in at least one of
the counts (transitions overlap conservatively rather than gap), and the
finalization check sums all of them under the lifecycle lock. The sum,
exposed as `cleanup_outstanding`, is an activity indicator rather than an
exact camera count: a token moving between categories is briefly counted in
two of them, so nonzero means "cleanup work remains" and zero means "none". Worker
threads only move from alive to exited, and the two ways runtime-owned
cleanup is registered are serialized with the latch: the shutdown path raises
the hand-off counter under the lifecycle lock before touching the worker's
slots, and a refused `select_camera` submits under the lifecycle lock itself.
A pre-existing token therefore always denies the latch until its release has
returned; only a token registered after the latch (a genuinely new refused
request) becomes a detached disposal: the cleanup thread still releases it
(never on the caller's thread, never leaked, the claim-once handover still
rules out a double close), it is visible to application-level accounting
through `cleanup_outstanding`, but it is no longer lifecycle work and the
latched `STOPPED` holds. `STOPPED` can never transition back to `STOPPING`,
and `stop() == True` can never race with runtime-owned cleanup appearing
afterwards. A `stop()` called after the latch returns `True` immediately.

The cleanup thread itself is private to the runtime; the public surface is
`cleanup_outstanding` (the summed count above) and `join_cleanup(timeout)`
(a bounded drain wait for application shutdown), so no caller can submit
work into the runtime's accounting.

**Transactional start.** `start()` launches the processing worker and then the
capture worker. If the second launch raises, the runtime marks itself spent,
signals the worker that did start, joins it against one bounded deadline, hands
any pending prepared camera to the cleanup thread, and re-raises the original
error. A caller never inherits a live thread from a failed `start()`; if the
started worker outlives that deadline, `state` reads `STOPPING` (never `NEW`)
and `stop()` keeps tracking it. Joining a worker that never started is a no-op.

**Truthful stop.** `stop()` signals both workers, hands the prepared cameras the
worker can no longer adopt to the runtime's cleanup thread at once (so their
release overlaps the joins rather than starting after them), joins the workers
against one deadline (`worker_join_timeout_s`), sweeps once more for a token the
worker orphaned while winding down, and waits, still within the same deadline,
for those releases. Then it reconciles under the lifecycle lock: it reads
whether either worker thread is alive and whether any runtime-owned release is
outstanding, latches `STOPPED` when nothing is left, and that final check is
both the return value and what `state` reports. Two things are deliberately kept apart: whether the deadline ran out
during the call (`deadline_exhausted` in the log) and whether owned work is
alive at the moment of return. A join that timed out but whose thread exited
before the final check yields `True` and `STOPPED`; a thread still inside an
uncancellable driver call yields `False` and `STOPPING`, logged as
`pipeline_shutdown_timeout` with which worker or release survived. Calling
`stop()` again joins whatever survived against a fresh, equally bounded deadline
and returns `True` only once nothing owned is left; there is no flag a repeated
call can clear to manufacture a success. The terminal `pipeline_stopped` line is
written exactly once, on the call that first observes everything gone.

After `stop()` has been requested the runtime accepts no further camera
requests: `select_camera` publishes nothing, returns the current generation, and
hands a prepared camera it was given to the runtime's cleanup thread, under the
lifecycle lock as described above (the capture worker enforces the same
never-leak rule for requests that reach it directly after its stop event is
set; within the runtime that path is unreachable because `select_camera`
refuses first). A runtime is single-use because Python threads cannot be
restarted; `start()` after `stop()` raises instead of pretending, and a fresh
`PipelineRuntime` is the restart path.

### Prepared-camera cleanup is owner-scoped work, off the UI thread

Releasing a camera is a driver call with no upper bound, so no thread that must
stay responsive performs one. The capture worker releases the camera it reads on
its own thread, and only there. Prepared cameras that nobody adopted are handed
to a `PreparedCameraCloser`, a daemon thread with a condition-guarded queue,
and every closer has exactly one owner:

- The **runtime's closer** is created inside `PipelineRuntime`, is not
  injectable, and is not exposed (the runtime offers only `cleanup_outstanding`
  and `join_cleanup`), so only the runtime ever submits to it: the tokens
  `stop()` takes from the capture worker, and the token of a `select_camera`
  refused after shutdown began. Its `outstanding` count is therefore
  runtime-owned work by construction (or, after the `STOPPED` latch, detached
  disposals).
- The **discovery closer** is created by the window and given to the
  discovery service, which hands it the unadopted token its `join` would
  otherwise release on the calling thread. Its work is discovery-owned and
  never touches the runtime's lifecycle.

Shared mechanics of every closer:

- `submit` transfers the duty to close a token and returns at once. Queue
  insertion is the single acceptance point: a normal return means the closer
  owns the token, an exception means it does not and the caller still owns
  it. A cleanup-thread launch failure after acceptance is logged, never
  raised, and re-submitting an accepted token is a structural no-op, so
  repeated launch failures can never duplicate a queue entry. A token that
  was already claimed is dropped on the spot, so a no-op is never counted as
  outstanding work.
- The token's claim-once handover makes the closer safe against every other
  party that still holds a reference (the capture worker's own cleanup, the UI
  adopting a discovery result, another closer): whichever side claims first
  releases, the other finds nothing to do, so a token is never released twice
  or by two threads at once. Nobody reads an unclaimed source, so a release
  never overlaps a read.
- A release counts as outstanding until the driver call returns; `join` waits
  at most the time it is given, and a failed worker launch is retried on the
  next `submit` or `join` with the token still counted.
- At most one worker ever drains a closer, enforced by a launch state machine:
  the worker reference is assigned before `start()` is attempted, so a
  `start()` that raises leaves the attempt UNCERTAIN (in CPython the native
  thread is created before `start()` waits on its bootstrap, so the worker may
  exist despite the exception) and no rival is launched until the attempt is
  resolved — the worker announces itself on entry (running), or its bootstrap
  provably ran and the thread terminated (restartable), or a dedicated wait
  inside `join` passes with the bootstrap never begun (never launched). As
  defense in depth, the drain loop admits exactly one active drainer: a
  duplicate thread that materializes late retires on entry without touching
  the queue or the in-flight slot, so overlapping drainers are structurally
  impossible whatever a launch heuristic concludes.
- A release that never returns keeps the daemon thread alive until process
  exit, exactly like a capture worker abandoned inside a driver call, and the
  tokens queued behind it stay counted rather than forgotten.

**Application shutdown aggregates the owners.** `closeEvent` performs no
release at all: against one deadline (`worker_join_timeout_s`) it signals
discovery, calls `runtime.stop()` (which bounds its own joins by the same
duration), joins the discovery thread, then joins the runtime's closer and the
discovery closer with whatever remains of the deadline. Runtime success is the
runtime's own verdict; overall shutdown success is the conjunction, and each
shortfall is attributed to its owner: `pipeline_shutdown_timeout` for the
runtime's workers or cleanup, `discovery_shutdown_timeout` for the discovery
thread, and `prepared_cleanup_timeout` with separate
`runtime_cleanup_outstanding` and `discovery_cleanup_outstanding` counts for
the closers. The Qt thread never waits past the one deadline.

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
  capture graph on every such `set`; it honours width and height (not FPS) as
  open parameters, so it receives the size up front and pays at most one rebuild
  for FPS, and none when the camera does not report a rate.
- A backend that opens but never streams costs one bounded validation instead of
  three full backend waits before the next backend is tried.
- The warm handoff above removes the second open of the selected camera at startup
  and on every Refresh.
- A superseded open no longer costs a further retry delay.

Every open, release, and probe logs its duration (`open_ms`, `configure_ms`,
`first_frame_ms`, `release_ms`, `probe_ms`, `discovery_ms`) together with the
backend requested and reported and the value of the hardware-transform switch, so a
run on physical hardware shows where the time goes without extra tooling.

### One open path for production and the diagnostic

`open_validated_backend` in `gazefix/camera/source.py` is the only code that
opens, configures, and first-frame validates a `VideoCapture` on one backend. It
returns a `BackendOpenOutcome` whose timing boundaries are fixed there:

```text
open_ms         VideoCapture.open alone (DirectShow gets width/height as open
                parameters and builds its graph inside this call)
configure_ms    the width/height/FPS property reads that decide what to set,
                the set calls for the values that differ, and the buffer hint;
                format_sets_applied counts the sets that actually ran
first_frame_ms  the bounded validation reads including the retry delays between
                them; validation_reads counts the attempts
```

`OpenCVCameraSource` runs it per backend and owns the fallback decision and the
release; the capture worker never sees a capture that did not validate. The
command-line diagnostic (`gazefix/camera/diagnostics.py`) runs the same function
per index and backend with the same `AppSettings`, so its `open_ms`,
`configure_ms`, and `first_frame_ms` mean exactly what the `camera_opened` log
event means, and `--msmf-hw-transforms 0|1` exports the same environment switch
before OpenCV loads for an A/B comparison on the same machine. The diagnostic
imports the source module; nothing in production imports the diagnostic, and the
diagnostic does not import Qt.

The diagnostic still differs from the running application on purpose, and the
differences are documented in its module docstring and the README: it probes each
backend alone without fallback, it does not sample a backend that failed
validation, its sampling loop is not the capture worker's read loop, and it
releases on its own thread. Its numbers are therefore per-backend production open
costs, not a prediction of application start-up time.

## Processing seam

`FrameProcessor.process(frame)` is the only transformation contract in M0, and
`PassthroughProcessor` returns the input unchanged. Later milestones can replace
this object with tracking and gaze pipeline work on the existing processor thread;
camera capture, latest-frame behavior, UI polling, and lifecycle ownership remain
unchanged. No future-milestone algorithm or dependency is included now.
