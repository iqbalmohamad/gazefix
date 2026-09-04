# GazeFix architecture

This document has two parts. **Part I** describes the system that actually
exists at the frozen Milestone 2 baseline (`milestone-2` at
`81e06118801c23d2337629fc676d6ad8ac13716a`) — it describes reality, verified
against the code, not an aspiration. **Part II** is the architecture baseline
proposed at the overall architecture pass (2026-09-04, awaiting Product
Manager architecture review) for Milestones 3–10: the
stage boundaries, contracts, ownership and failure domains that future
milestones implement incrementally, without rewriting the application core.

Detailed per-milestone contracts stay in their own documents and are not
duplicated here: `docs/tracking.md` owns the M1 tracking contract, coordinate
conventions and failure budgets; `docs/gaze.md` owns the M2 gaze model, sign
conventions and confidence semantics; `docs/decisions/` holds the decision
records (ADR-0001 backend choice; ADR-0002 correction-engine boundary;
ADR-0003 execution model and frame ownership); `docs/qa-policy.md` owns
verification process, not architecture.

# Part I — The frozen system (M0 foundation, M1 tracking, M2 gaze)

## The system at a glance

```text
                                Qt main thread
                (widgets, timers, poll-and-present, metrics labels)
                                      ▲  poll: consume_latest_output
                                      │  (generation-filtered)
 capture thread                       │
 "gazefix-camera-capture"             │
 OpenCV read loop ──▶ latest-frame ──▶ processing worker ──▶ latest-output
 (camera generations,  buffer          "gazefix-processor"    buffer
  MSMF→DSHOW fallback) (1 slot,        TrackingProcessor      (1 slot,
                        newest wins)     │submit    ▲bounded   newest wins)
                                         ▼          │wait ≤ tracking_wait_ms
                                     tracker thread "gazefix-tracker"
                                     MediaPipe FaceLandmarker (CPU)
                                     → analysis → gaze estimation
                                     (1-slot submission in, 1-slot result out)

 side threads: "gazefix-camera-discovery" (index probing),
               two PreparedCameraCloser daemons (camera-release cleanup)
```

Every hand-off on the frame path is a one-slot, newest-wins buffer; no frame
queue exists anywhere (the only queues in the process are the closers'
bounded-by-workload camera-release token queues and Qt's signal delivery). The details of each mechanism follow in this part; this
section is the inventory an architect needs in one place.

**Threads and the mutable state each one owns:**

| Thread | Owns (mutable state / resources) | Stops by |
| --- | --- | --- |
| Qt main | widgets, both timers, last-QImage/last-tracking caches, discovery service, the discovery-owned closer | `closeEvent`, one deadline (`worker_join_timeout_s`) |
| `gazefix-camera-capture` | the open `VideoCapture` (sole releaser), capture state machine, generation application | stop event + flag-only interrupt; bounded join |
| `gazefix-processor` | the `FrameProcessor` lifecycle (`start`/`process`/`close`) | stop event + buffer wake; bounded join |
| `gazefix-tracker` | `FaceTracker` instance, primary-face selector, landmark stabiliser, gaze estimator and its smoother, all error/rebuild budgets | stop event; join ≤ `tracking_join_timeout_s`; abandoned as daemon if wedged in a native call |
| `gazefix-camera-discovery` | probe loop, provisional prepared camera | `request_stop` + bounded join |
| two `PreparedCameraCloser` daemons | queued camera-release tokens (runtime-owned and discovery-owned, never shared) | drain; bounded join |

**Failure domains and their budgets (M2 state):**

| Domain | Contained where | Budget and recovery |
| --- | --- | --- |
| camera | capture worker | degraded on read failures; stall/threshold → release + reopen with backoff; backend demotion; no camera or driver failure ends the capture thread (an unexpected internal error ends it once, with an ERROR status — the loop has no in-loop supervisor like the tracker's) |
| tracking | `TrackerWorker` | init: 5 attempts with backoff per camera generation; inference: rebuild after 3 consecutive errors, at most 3 rebuilds per generation, then UNAVAILABLE until the camera changes |
| gaze | `TrackerWorker`, separate budget | raising `estimate` contained (never spends the tracker's budget); retired after 10 consecutive failures, or at once when its `reset` fails; revived only on generation change |
| processor seam | `ProcessingWorker` | any `process()` exception publishes the original frame; the preview never freezes |

**Temporal-state reset matrix (M2 state):**

| Event | Backend tracking state | Primary-face memory | Landmark stabiliser | Gaze smoother | Budgets re-armed |
| --- | --- | --- | --- | --- | --- |
| camera generation change | reset | reset | reset | reset (and a retired estimator revived) | init attempts + rebuilds; the consecutive-error counters (inference, gaze) clear only on success or revival |
| frame gap > `tracking_reset_gap_s` | reset | reset | reset | reset | no |
| face lost / identity change | — | per policy | reset | reset | no |
| gaze unavailable on a frame | — | — | — | reset | no |
| inference failure | — | reset | reset | reset | no |

**Substitution seams, all proven by fakes in the test suite:** the
`CameraSource` protocol and `source_factory` parameters; the `FrameProcessor`
protocol (`start`/`process`/`close`); the `FaceTracker` protocol and
`TrackerFactory` (the only MediaPipe boundary); the `GazeEstimator` protocol
(the only gaze-algorithm boundary); injectable clocks. These seams are the
system's substitution surface: Part II extends the same pattern to correction,
calibration and virtual-camera output instead of inventing a new one.

**Configuration (M2 state):** every runtime setting lives on the frozen
`AppSettings` dataclass (`gazefix/config.py`), validated at startup and set
only through CLI flags; gaze-model constants that are not product-facing live
in `gazefix.gaze.estimator.GazeSettings`. There is no settings persistence of
any kind yet — Part II, "Configuration ownership", defines where future
settings belong.

**Diagnostics (M2 state):** `PipelineMetrics` (`gazefix/diagnostics/metrics.py`)
collects capture/display FPS (rolling 2 s windows), EMA-smoothed
processing/pipeline-latency/tracking/gaze durations, and per-status counters.
Its writers are the capture thread, the processor thread (which also records
the tracking and gaze timings that were *measured* on the tracker thread, when
it consumes each result) and the Qt thread (display FPS on each presented
frame); the Qt metrics timer snapshots. The consumer UI shows a small subset,
`--dev` shows a detail line, and a metrics snapshot is logged at shutdown
(every field but the `tracking_unavailable` counter today). The development overlay is
drawn by the tracking processor on a copy of the frame, gated by
`--dev`/`--overlay`, and is never part of the consumer UI.

## Data flow

```text
OpenCV camera source (capture worker)
                 ↓
       latest-captured-frame buffer
                 ↓
   processor worker: TrackingProcessor ──submit──▶ tracker thread (MediaPipe, CPU)
        (M0: PassthroughProcessor)     ◀─result──   latest-value slot in, latest result out
                 ↓
       latest-output-frame buffer  (frame + TrackingResult for that frame)
                 ↓
        Qt timer-driven preview
```

Both M0 buffers contain at most one value. Publishing replaces an unread value
and increments a replacement counter; producers never wait for consumers and
old frames cannot accumulate. The UI polls for a newer output sequence instead
of receiving one queued Qt event per frame. If display is slower than capture
or processing, it therefore presents the freshest available output. The M1
hand-off between the processor thread and the tracker thread uses the same
latest-value principle (one waiting frame, one latest result), so tracking can
never grow a queue either; `docs/tracking.md` describes it in full.

## Frame ownership

OpenCV supplies a distinct NumPy array for each successful `read`. The capture
worker marks that array read-only before publishing it. The passthrough
processor shares the same immutable array without copying, and so does the
tracking processor with the overlay off: the tracker converts the frame into
its own RGB array for inference and never writes to the capture array. With
the overlay on, the processor draws on a copy and publishes the copy. The
preview builds a detached `QImage.copy()` before the NumPy reference can be
replaced, so Qt owns the displayed pixels safely.

## Threads and lifecycle

- The Qt main thread owns widgets, timers, pixmap creation, and display metrics.
- The camera-discovery thread performs potentially blocking index validation.
- The long-lived capture thread owns camera open/read/release and automatic retry.
- The processor thread waits for and processes only the latest captured frame.
- The tracker thread (M1, owned by the tracking processor) creates, calls,
  resets, rebuilds after repeated errors, and closes the face tracker; the
  processor thread hands it frames and waits a bounded time for each frame's
  own result.

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

#### Known limitation: ambiguous `Thread.start()` failures in the cleanup worker

The launch state machine above has one accepted gap. `PreparedCameraCloser`
cannot definitively distinguish every ambiguous `Thread.start()` failure: in
CPython the native thread is created before `start()` waits on the
interpreter bootstrap, so when `start()` raises inside that window, native
thread creation may already have occurred while the bootstrap state is not
yet observable from outside. Under fault injection in exactly that window, a
stale native cleanup worker may remain alive but untracked by lifecycle
accounting, and a replacement worker may later be launched and run beside
it. The single-drainer guard still holds — the rival retires on entry
without touching the queue or the in-flight slot, so queue and in-flight
state are never mutated concurrently — and camera cleanup still completes.
The consequence is confined to bookkeeping: runtime lifecycle accounting may
report `STOPPED` while the stale worker thread is still alive.

This behaviour has been reproduced only through injected thread-bootstrap
failures (test doubles that make `Thread.start()` raise after the native
thread exists). It has not been observed during normal runtime or
physical-camera use.

Classification:

- Known limitation, recorded here rather than worked around in code.
- Non-blocking for M0 / the MVP foundation.
- Production-hardening backlog item.

Revisit if real shutdown hangs appear on Windows, if camera locks linger
after application close, or if cleanup-thread leaks become observable — and
in any case before M10 / production packaging and hardening.

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

`FrameProcessor` is the only transformation contract:

```text
start(metrics)             once, on the processor thread, before the first frame
process(frame, context) -> ProcessorOutput(frame, tracking)
close()                    once, on the processor thread, when the worker exits
```

`FrameContext` tells the processor which frame it holds (capture sequence,
capture timestamp, camera generation) so the metadata it returns is tied to
exactly that frame; `ProcessedFrame` carries the sequence and the
`TrackingResult` to the consumer. `PassthroughProcessor` (M0) returns the
input unchanged with no metadata. `TrackingProcessor` (M1,
`gazefix/tracking/processor.py`) is the first real stage: it starts its
tracker thread from `start()` so model loading — and the one-time warm-up
of OpenCV's drawing primitives, which would otherwise be paid inside the
first overlay render — overlaps camera discovery, never blocks a frame for
longer than `tracking_wait_ms`, and releases the tracker from `close()`
within a bounded join. Camera capture, latest-frame behaviour, UI polling
and the M0 lifecycle ownership are unchanged. The
window chooses the processor (`--no-tracking` selects the passthrough) and
hands it to `PipelineRuntime`.

### M2 gaze rides on the tracking result

Gaze estimation (`gazefix/gaze/`) adds no stage, thread or queue. It runs on
the tracker thread inside `TrackerWorker._analyse`, immediately after the
`TrackingResult` is built, and its output is attached to that same result as
`TrackingResult.gaze`. Three consequences follow. The estimate inherits the
result's frame identity, so it can never be paired with the wrong frame or a
stale camera generation. Its cost sits inside `tracking_total_ms` rather than
being added to the processor thread's bounded wait. And its temporal state
(the gaze smoother) has exactly one owner and is reset by
`_reset_temporal_state` alongside the primary-face selector and the landmark
stabiliser.

The estimator itself is reached only through the `GazeEstimator` protocol
(`gazefix/gaze/estimator.py`), which the worker accepts by injection, so no
consumer depends on one gaze algorithm. `gazefix.gaze.models` imports nothing
from `gazefix.tracking`, and `gazefix.tracking.models` imports it — one
direction only, no cycle.

A gaze failure never reaches the frame path, and never costs tracking. The
estimator turns its own exceptions into an `UNAVAILABLE` result, and the
worker does not depend on it doing so: because the boundary exists to be
substituted, `TrackerWorker` catches a raising `estimate` before it can enter
the inference-error path and spend the tracker's rebuild budget, and catches a
raising `reset` before it can end the tracker thread. A persistently failing
estimator is retired until the camera generation changes. See
[`gaze.md`](gaze.md).

### M1 shutdown additions

`ProcessingWorker` calls `processor.close()` in its `finally`, on the
processor thread, so `PipelineRuntime.stop()` bounds it with the same
deadline it already applies to the processor join. `TrackingProcessor.close()`
signals the tracker thread and joins it for at most
`tracking_join_timeout_s`; the tracker thread closes the tracker itself
(that is the only thread that ever touches it). If the thread is inside an
uncancellable native inference or model-load call it is abandoned and logged
(`tracker_shutdown_timeout` by the worker, `tracker_thread_alive_at_close` by
the window): it holds no camera, so camera release is unaffected, and it
still closes the tracker when the native call returns. The tracker thread is
a daemon and the tracking backend adds no Python threads of its own, so a
wedged native call cannot hold the interpreter open: the entry point reports
it (`tracker_thread_alive_at_exit`) and exits normally, with no forced
termination. See docs/tracking.md section 14. The runtime's `STOPPED` latch keeps
its M0 meaning (the runtime-owned capture and processor threads and
prepared-camera cleanup); the tracker thread's state is reported separately
and truthfully rather than folded into it.

# Part II — Architecture baseline for M3–M10

Proposed at the overall architecture pass (2026-09-04) on the frozen M2
baseline, awaiting Product Manager architecture review — the same status the
two ADRs it summarizes carry. This part answers one question: given what
GazeFix actually is
after M2, how do the remaining milestones — offline correction (M3),
real-time correction (M4), temporal stabilization (M5), calibration (M6),
performance (M7), virtual camera (M8), neural evaluation (M9),
productization (M10) — fit into the pipeline without rewriting the core?

It is architecture, not milestone system analysis: it fixes boundaries,
contracts, ownership, dependency direction and failure domains. Algorithm
choices, warp math, mask construction and per-milestone task lists belong to
each milestone's own SA. The final section separates what is now stable from
what is deliberately deferred.

Two decisions with long-term cost are recorded as ADRs and only summarized
here: **ADR-0002** (correction is a separate engine stage behind a
`CorrectionEngine` protocol; gaze estimation stays owned by tracking) and
**ADR-0003** (one processing worker through M4–M8; copy-once frame
ownership; per-consumer output buffers).

## Target MVP architecture

```text
 capture worker ──▶ latest-frame buffer ──▶ processing worker (one thread)
 (unchanged)         (1 slot)                 │
                                              │ 1. tracking + gaze      M1/M2, unchanged
                                              │    (tracker thread, bounded wait)
                                              │ 2. target resolution    M6 (before M6: fixed
                                              │    (calibration profile) camera target)
                                              │ 3. correction policy    M4 (effective strength
                                              │    (deviation/confidence  from requested strength,
                                              │     gates, ramps)         PRD §10 curve)
                                              │ 4. correction engine    M3 code, M4 wiring
                                              │    (geometric first;     — owns masks and
                                              │     neural M9, same seam) blending, writes ONE
                                              │                           working copy
                                              │ 5. dev overlay          existing, moves after
                                              │    (dev builds only)      correction
                                              ▼
                                 ProcessedFrame (immutable again)
                                   ├─▶ preview buffer (1 slot) ─▶ Qt poll (unchanged)
                                   └─▶ output buffer  (1 slot) ─▶ virtual-camera worker (M8)
                                                                    └─▶ VirtualCameraBackend
```

What stays exactly as frozen: capture, discovery, camera generations, the
latest-frame buffers, the `FrameProcessor` seam, the tracker thread and both
its slots, the Qt polling preview, the runtime lifecycle, shutdown
accounting. What is added, per milestone, is stages 2–5 inside the existing
processing worker and one new consumer thread at M8.

This target rewrites nothing — capture, discovery, buffers, the tracker
thread and the runtime lifecycle are untouched — but it does extend frozen
contracts compatibly, and names those extensions now so M4/M8 do not
improvise: `ProcessorOutput` and `ProcessedFrame` gain the optional
`correction` field (the `tracking` precedent; `ProcessorOutput` is the
transport that gets it into `ProcessedFrame`); the runtime wires one more
one-slot output buffer at M8; and `TrackingProcessor` grows small public
accessors so the staged processor can render the overlay after correction.
Everything else happens behind an existing seam or in a new module.

The PRD §18 sketch draws gaze estimation as its own pipeline stage;
the frozen system deliberately runs it inside tracking (on the tracker
thread, riding the `TrackingResult`), and this baseline keeps that: it is
cheaper, gives gaze the frame's identity for free, and M2 froze its failure
containment. The PRD sketch is conceptual; this is the concrete shape.

## Stage boundaries and data contracts

The contract rules that already govern M0–M2 extend to every new stage:
results are immutable frozen dataclasses; every result names its frame
(`capture_sequence`, `captured_at_ns`, `camera_request_id`) or rides on one
that does; unavailable is an explicit status with a reason, never `None`-means-
something or a fabricated value; heuristics carry provenance strings; timing
fields are `None` when nothing was measured.

| Contract | Purpose | Producer → consumers | Notes |
| --- | --- | --- | --- |
| `TrackingResult` (exists) | landmarks, eyes, pose, quality + embedded gaze for one frame | tracker thread → correction policy/engine, overlay, UI | unchanged; already carries everything correction needs |
| `GazeResult` (exists) | uncalibrated source gaze + confidence | gaze estimator → target resolution, policy, UI | unchanged; the *source gaze* of PR-5 |
| target gaze | where corrected eyes should appear to look | target resolution → policy, engine | a unit direction in the `GazeResult` camera frame; default `(0, 0, 1)` — the camera's *optical axis*, which equals "the camera" only for a centred user (`docs/gaze.md` §5); calibration (M6) exists partly to close that gap. Not a new dataclass until M6 gives it structure |
| `CorrectionResult` (M4) | what correction did to one frame | correction stage → `ProcessedFrame`, metrics, UI | metadata only — status `CORRECTED` / `SKIPPED(reason)` / `FAILED(reason)`, applied (effective) strength, `correction_ms`, optional debug metadata (e.g. mask bounds) for the overlay. The corrected pixels travel beside it in the engine's output pair (ADR-0002) and rest in `ProcessedFrame.frame`. Immutable; identity comes from the `TrackingResult` it answers |
| `ProcessedFrame` (exists, extended M4) | the frame a consumer shows/sends + its metadata | processing worker → preview, virtual camera | gains `correction: CorrectionResult \| None` exactly as it carries `tracking` today; `ProcessorOutput`, its transport, gains the same field |
| `CalibrationProfile` (M6) | per-user gaze mapping | calibration store → target resolution | immutable; schema-versioned; persisted locally; see "Calibration seam" |

There is deliberately no `CorrectionRequest` object: the engine call takes
`(frame, tracking, target, strength)` directly (ADR-0002). Bundling those
into a dataclass would add a wrapper with one producer and one consumer and
no identity of its own. Likewise there is no god result: `ProcessedFrame`
aggregates per-stage results by reference and each stage's result stays its
own type. Image data crosses a stage boundary only in the frame slot of a
stage-output pair (`ProcessorOutput` today; the correction engine's output
pair at M4, ADR-0002) and rests only in `ProcessedFrame.frame` — every
*result* contract is metadata.

## Frame ownership and copying

The frozen invariant stands: captured frames are marked read-only at the
source and shared by reference across threads; nothing ever writes a
published array. Correction is the first stage that needs writable pixels,
and the rule is **copy once, then reuse** (ADR-0003):

- The correction engine allocates **one** writable working copy of the
  captured frame per corrected frame, warps and blends into it, and returns
  it. Masks, patches and blending are engine-internal; no second full-frame
  copy exists on the correction path.
- The dev overlay draws on whatever frame the stage chain hands it: the
  working copy when correction ran (no extra copy), its own copy of the
  original otherwise (exactly as today).
- Before publication the working copy is frozen (`setflags(write=False)`),
  so `ProcessedFrame.frame` is immutable again and both consumers share it
  by reference, exactly as the preview shares captured frames today.
- The preview keeps its detached `QImage.copy()`; a virtual-camera backend
  that needs a different pixel format converts inside the backend adapter
  (that conversion is the backend's own buffer, not a pipeline copy).
- An uncorrected frame (correction skipped, failed, disabled, or no valid
  tracking) passes through as the original read-only array with zero copies,
  exactly as every frame does today.

Steady-state cost per displayed corrected frame at 720p is therefore one
≈2.8 MB working copy (1280 × 720 × 3 = 2,764,800 bytes) plus the preview's
existing QImage copy. That is the
budget; shared-memory pools, in-place mutation of capture buffers and
triple-buffer schemes are rejected as unnecessary at this resolution
(ADR-0003 lists the alternatives). Revisit only if M7 measurement shows the
copy itself (≈ millisecond scale) matters.

Stale output cannot occur by construction: correction runs synchronously in
the worker on the frame it was handed, so a correction result can never be
paired with a different frame. If a correction sub-worker is ever split out
(see below), the same identity fields that gate tracking results
(`belongs_to`) gate correction results.

## Threading and execution model

**One processing worker through M4–M8** (ADR-0003). Tracking and gaze stay
on the tracker thread; target resolution, policy, correction and overlay run
serially on the existing `gazefix-processor` thread. No new frame-path
thread is added until measurement proves the budget broken.

The throughput arithmetic, stated honestly: with the frozen submit-then-wait
design the tracker thread is idle while the processor corrects, so per-frame
cost is approximately `min(inference, tracking_wait_ms) + correction` in
series. Tracking inference measured 14.3 ms median — on the Linux
development machine (ADR-0001); the target laptop is unmeasured until M4.
The frame period is 33 ms at 30 FPS and ~42 ms at the 24 FPS floor, so on
hardware where inference stays near 14 ms, correction (policy + warp +
blend + copy + publish) has a derived budget of roughly **19–27 ms**.
Inside that budget, one worker holds full frame rate with no added pipeline
latency. Two caveats keep this honest: every number is an extrapolation
until M4 measures on target hardware; and a tracker that misses
`tracking_wait_ms` (100 ms — 2.4–3× the frame period) breaks the arithmetic
outright, because a timed-out frame costs up to the full wait and passes
uncorrected. A persistently marginal tracker therefore pins output FPS well
below the floor with correction skipped; whether 100 ms remains the right
wait bound once the same thread also corrects is an explicit M4 revisit
item.

**The split trigger:** if, after M4 measurement and reasonable optimization
(and again at M7), `inference + correction` exceeds the ~42 ms floor on the
target machine, correction moves to its own worker fed by a one-slot
latest-value hand-off — the exact pattern the tracker thread already uses —
so inference of frame N+1 overlaps correction of frame N. Splitting helps
only when each term *individually* fits the frame period (post-split
throughput is bounded by `max(inference, correction)`); if inference alone
exceeds the floor on target hardware, the remedy is tracker-side — M7
optimization, inference-resolution trade-offs — not more workers. The split
buys throughput at the price of one frame of extra latency and a second
stale-result guard; it is designed now, reserved, and not built until the
measurement demands it.

**Backpressure is unchanged everywhere:** newest wins at every one-slot
buffer. If correction is slower than capture, frames are replaced in the
capture buffer and output FPS drops; latency never grows and no queue ever
forms. A slow consumer (preview or virtual camera) replaces values in its
own output buffer and affects nobody else.

**Stage skipping:** target resolution falls back to the fixed camera target
when no profile exists; correction is skipped (frame passes as original)
when disabled, when strength resolves to zero, when tracking or gaze is
unavailable for the frame, or when the engine is retired; the overlay is
dev-only; the virtual camera runs only when started. Tracking itself is
never skipped while enabled — a slow tracker times out per frame exactly as
today.

**Degradation stays local; nothing restarts a larger subsystem:** the
camera reopen loop, the tracker rebuild budget, gaze retirement, correction
retirement (below) and virtual-camera stop are each confined to their own
domain. `PipelineRuntime` remains single-use; no failure anywhere escalates
to a pipeline or application restart.

## M3 — offline correction architecture

M3 proves visible gaze redirection on still images, recorded frames or
short clips, without real-time constraints. The architectural requirement
is that the M3 correction code is the *production* engine exercised
offline — not a prototype to be rewritten for M4:

- **`gazefix/correction/`** is created in M3 with the engine behind the
  `CorrectionEngine` protocol (ADR-0002): `description`,
  `correct(frame, tracking, target, strength) -> CorrectionResult`,
  `reset()`, `close()`, created by a factory on its owning thread. The
  module consumes only the existing contracts (`TrackingResult`,
  `GazeResult`) and NumPy/OpenCV; it imports no Qt, no pipeline, no camera
  code, and performs no I/O.
- **The offline harness is a CLI** following the `validate.py` /
  `scripts/tracking_test.py` pattern: load input → run the real tracker and
  analysis with the same synchronous pattern the tracking diagnostic
  already uses, extended to construct and run the gaze estimator directly
  (no offline path runs the estimator today — production reaches it only
  inside the tracker worker) → call the engine with configurable target and
  strength → write before/after outputs and a JSON report. Whether the
  landmark stabiliser and gaze smoother run offline is an M3 SA decision
  (recommendation: configurable, default off, for reproducibility). The
  harness imports the engine; nothing in the engine knows the harness
  exists.
- **Strength semantics** (PRD §9, PR-5): requested strength `s ∈ [0, 1]`,
  interpolation not binary — corrected gaze ≈ source + `s`·(target −
  source), expressed in yaw/pitch space. `0` must be a true no-op
  (bit-identical passthrough). The deviation-dependent curve of PRD §10
  (light near zero deviation, reduced over 25–35°, disabled above 35°) is
  **policy**, not
  engine: the policy layer turns requested strength, deviation and
  confidence into the effective strength the engine receives, so engines
  stay simple and the curve stays tunable without touching engines.
- **Masks and blending are engine-internal** (ADR-0002): the engine returns
  a complete corrected frame. Mask helpers live as library code inside
  `gazefix/correction/` for reuse and for mask-debug output; a separate
  compositor *stage* is deliberately not created (single caller, premature
  contract).
- **Failure behavior:** the engine documents never-raise (unusable input →
  `SKIPPED`/`FAILED` result with a reason) and the caller contains a raise
  anyway — the M2 gaze lesson applied verbatim.

What M3 SA decides (not this document): the warp technique, mask
construction, blending method, eye-region definition, interpolation
details, the quality-scoring procedure against PRD §28, and harness input
formats. M3 is the PRD's major quality gate: if visible, natural
redirection cannot be shown offline, that verdict must surface at the gate
rather than be engineered around.

## M4 — real-time integration

Correction enters through the existing `FrameProcessor` seam by
composition: a staged processor wraps the frozen tracking stage and applies
policy + engine to its output on the processing worker. Concretely,
`process(frame, context)` runs tracking exactly as today, then: if the
result's gaze is `ESTIMATED`, resolve target, compute effective strength,
call the engine, and publish the working copy with a `CORRECTED` result; in
every other case publish the original frame with a `SKIPPED` reason
(`no gaze`, `low confidence`, `timeout`, `disabled`, `strength 0`, engine
retired) or `FAILED`. The dev overlay moves to the end of the chain so it
annotates what the consumer actually sees — concretely, the staged
processor builds the tracking stage with the overlay off, owns the overlay
toggle itself (the existing thread-safe-setter pattern), and calls
`render_overlay` after correction, with the tracker/gaze description
strings exposed through small public accessors on `TrackingProcessor`.
Correction's user-facing controls at M4 (enabled, strength, engine
selection) are session-only mutable state behind the same thread-safe
setters, seeded from `AppSettings` defaults; they migrate to the persisted
tier when the M6 settings file arrives.

- **Gaze unavailable / low confidence:** correction fades rather than
  snaps — the policy ramps effective strength toward zero over a bounded
  interval (refined in M5), then frames pass as originals. Correction never
  runs on `LOW_CONFIDENCE` or stale gaze.
- **Correction failure:** contained like gaze — its own consecutive-error
  budget; retirement until camera generation change or the user toggles
  correction off/on; rate-limited logging; the frame path always keeps the
  original frame. Correction failures never touch the tracker's or gaze's
  budgets.
- **Latency measurement:** `correction_ms` is recorded around policy +
  engine + freeze, on the processing worker, and joins the metrics snapshot
  and dev detail line; the existing `processing_ms` automatically absorbs it,
  keeping the end-to-end pipeline latency truthful.
- **Engine lifecycle:** the factory is invoked and the engine created,
  reset and closed on the processing worker (mirroring the tracker-thread
  ownership rule); engine initialization failure marks correction
  unavailable with an actionable message and never blocks the preview.
- The M4 acceptance target (≥ 20 FPS development prototype) is measured
  with the diagnostics below, not asserted.

## Temporal stabilization (M5)

Four smoothers with four owners — deliberately not one generic smoothing
subsystem, because the signals have different frames, rates and reset
rules:

1. **Landmark stabiliser** (exists, tracker thread) — image-space landmark
   jitter.
2. **Gaze smoother** (exists, inside the estimator) — eye-in-head direction.
3. **Correction-parameter smoothing** (M4/M5, policy layer, processing
   worker) — effective strength and target ramps: fade-in on acquisition,
   fade-out on loss/disable, slew-limited strength changes. This is the
   primary tool against correction flicker and oscillation.
4. **Image/output stabilization** (M5, only if 1–3 prove insufficient) — a
   last resort, because image-space smoothing costs copies and risks ghosting;
   its necessity is an M5 SA question, not a foregone conclusion.

Reset rules extend the frozen matrix: correction-parameter state resets on
face loss, camera generation change, Refresh/camera switch, correction
disable, and calibration profile change. The structural test pattern that
guards gaze resets today (every stabiliser-reset site must reset the gaze
smoother) extends to the correction-parameter state at M4/M5.

## Calibration seam (M6)

Only the seam is defined now; calibration math, sampling UI and profile
schema details are M6 SA.

- **`CalibrationProfile`** is an immutable, schema-versioned value object,
  produced by a calibration workflow (UI layer) and persisted locally as a
  small file under the per-user data directory (sibling of `logs/` and
  `models/`). Profiles are data, not settings.
- **Ownership:** a `CalibrationStore` (M6, `gazefix/calibration/`) loads,
  validates and saves profiles. The active profile reaches the processing
  stage as an immutable object through a thread-safe setter on the staged
  processor — the same pattern as the overlay toggle — and a profile change
  resets correction-parameter smoothing.
- **What it transforms:** target resolution consumes
  (`GazeResult`, `CalibrationProfile`) and produces the target gaze and any
  per-user parameters (e.g. a calibrated `eye_model_ratio` replacing the
  population average — `docs/gaze.md` already designates it as the constant
  calibration would replace). Uncalibrated operation (no profile) remains a
  first-class mode: fixed camera target, population constants.
- **Independence:** calibration depends on the gaze contract only — never on
  a correction-engine implementation, never on the virtual camera. Engines
  receive the *resolved* target and strength and cannot tell whether a
  profile produced them.
- **Invalidation:** schema version mismatch; explicit recalibration; camera
  or capture-resolution change as a best-effort check — index probing gives
  no stable device identity (a frozen, documented limitation), so profile-to-
  camera matching is advisory (warn and let the user decide), not enforced.
  This is a known risk (R10 below), not a silently ignored one.

## Correction-engine replaceability and the neural boundary (M9)

The PRD requires that GazeFix not be permanently tied to one correction
implementation. The mechanism is the one already proven twice (FaceTracker,
GazeEstimator): a small protocol, a factory, one adapter module per
backend, and contract types that never leak backend types (ADR-0002).

- **Geometric engine** (M3): pure NumPy/OpenCV inside
  `gazefix/correction/`; no model file, no new dependencies.
- **Neural engine** (M9, only if evaluation justifies it): one adapter
  module is the only place that imports ONNX Runtime — exactly as
  `mediapipe_tracker.py` is the only MediaPipe importer. Sessions, tensors,
  providers and DirectML options are private to that module; provider
  selection (CPU first, DirectML optional later) happens inside it with
  automatic CPU fallback; inputs and outputs cross the protocol as NumPy
  arrays only. Model assets follow the M1 pattern: manifest, checksum,
  explicit fetch script, offline runtime, license recorded in an ADR before
  adoption.
- The rest of the application knows an engine only by its `description`
  string and its `CorrectionResult`s. Engine selection is a configuration
  value naming a factory.
- A neural model that wants to estimate gaze internally does not displace
  the tracking-owned `GazeResult` (which remains the source of truth for
  status, confidence and the UI); the pipeline feeds every engine the same
  source gaze. If M9 evaluation shows a compelling model that genuinely
  requires its own estimation path, that is a new ADR at M9, with evidence —
  not a silent contract change.
- ONNX Runtime is **not** added now. One constraint is recorded for M9
  planning: `mediapipe==0.10.21` caps NumPy below 2, so any neural runtime
  must resolve against `numpy<2` (risk R9).

## Virtual-camera boundary (M8)

Defined now, implemented in M8:

- **`VirtualCameraBackend` protocol** (PRD §19 shape):
  `start(width, height, fps)`, `send_frame(frame)`, `stop()`, plus a
  `description`. One adapter module per backend under `gazefix/output/` is
  the only importer of the chosen library; the backend choice
  (pyvirtualcam / OBS / other) is an M8 decision and, because it carries
  driver and licensing weight, an ADR candidate *then*.
- **Execution:** a dedicated output worker thread consumes `ProcessedFrame`s
  from its **own** one-slot buffer (the fan-out in the target diagram), so a
  slow or blocked backend replaces values in its own buffer and can never
  backpressure capture, processing or preview. The fan-out is concrete:
  from M8 the **runtime** owns both output buffers and the processing
  worker always publishes to both — starting or stopping the virtual camera
  changes only consumption, so no buffer is ever attached to or detached
  from a running worker. `select_camera` clears every consumer buffer on a
  camera switch, and the output worker applies the same
  `camera_request_id` check before sending that the preview path applies on
  consume — the frozen two-lines-of-defence pattern extends to the second
  consumer. Frames are sent at publication pace; fixed-rate pacing or
  frame-repeating, if the backend needs it, lives inside the adapter
  (M8 SA).
- **Formats:** the pipeline publishes what it has (BGR888, capture
  resolution); conversion to the backend's format happens in the adapter,
  in the adapter's own buffer.
- **Lifecycle:** the output worker is **window-owned**, like the discovery
  service and its closer: started and stopped explicitly from the UI, and
  joined in `closeEvent` against the same single deadline with its own
  timeout attribution. Start creates the worker and calls `backend.start`;
  stop signals the worker, which stops the backend on its own thread within
  a bounded join — the same ownership rule every other worker follows.
  `PipelineRuntime`, its `STOPPED` latch and its cleanup accounting are
  untouched by M8.
- **Failure isolation:** send failures consume a bounded consecutive-error
  budget, then the output stops itself, surfaces a status to the UI, and
  waits for the user to restart it. A virtual-camera failure never stops
  capture, processing or preview. Camera/virtual-camera coexistence quirks
  on Windows are an M8 verification item (risk R5), not an architecture
  change.

## Diagnostics roadmap

Extend `PipelineMetrics` in place — same recorders/EMA/snapshot/shutdown-log
pattern, no observability platform:

| Metric | Exists | Arrives |
| --- | --- | --- |
| capture FPS, display FPS, processing ms, pipeline latency ms | yes | — |
| tracking inference/total ms, per-status counters, replaced counters | yes | — |
| gaze estimation ms, per-status counters | yes | — |
| correction ms (EMA), corrected/skipped/failed counters, applied strength (dev display) | no | M4 |
| compositing time | folded into correction ms (engine owns compositing); split only if a compositor stage ever exists | — |
| per-consumer output replacement counters | output buffer only | M8 (second buffer) |
| virtual-camera send ms, sent FPS, send-error counter | no | M8 |
| CPU / memory (PRD §21; psutil is the PRD §22 optional dependency) | no | M7, where optimization needs it |
| inference provider / engine description in snapshot | description strings exist in logs/overlay | M9 |

The logging convention stays: structured JSONL events per state change (never
per frame), rate-limited error events, a full metrics snapshot at shutdown.

## Failure domains and recovery ownership

The M2 lesson is now a rule: **every downstream stage gets its own error
budget, and a downstream failure never spends an upstream stage's recovery
budget.** There is deliberately no shared "processing error" mechanism.

| Domain | Contained in | Recovery ownership | User-visible degradation |
| --- | --- | --- | --- |
| camera | capture worker (frozen) | reopen with backoff, backend demotion | status text; preview pauses |
| tracking | tracker worker (frozen) | bounded rebuilds per generation, then wait for camera change | preview continues untracked |
| gaze | tracker worker, own budget (frozen) | retire; revive on generation change | correction fades/stops; preview continues |
| correction | staged processor (M4) | own consecutive-error budget; retire until generation change or user toggle | original frames; status shows correction off |
| compositing | inside the engine = correction domain | same as correction | same as correction |
| calibration | calibration store (M6) | load/save failures fall back to uncalibrated defaults with a visible notice; never block the pipeline | uncalibrated correction |
| virtual camera | output worker (M8) | bounded send-error budget; stop output; user restarts | vcam stops; preview unaffected |

Cross-cutting rules, unchanged from the frozen system: budgets re-arm on
camera generation change; retirement is explicit and logged; every wait is
bounded; every degradation leaves the original-frame preview usable
(PRD §4: continuity of video outranks correction).

## Configuration ownership

Four tiers, extending the split that already exists (`AppSettings` vs
`GazeSettings`):

| Tier | Lives | Examples (future) |
| --- | --- | --- |
| product/user settings — persisted | a small local settings file, introduced **with M6** (calibration is the first feature that must persist data; PRD lists saved settings under M10). At M4, correction controls (enabled, strength, engine selection) are session-only mutable state on the staged processor behind thread-safe setters — the overlay-toggle pattern — seeded from `AppSettings` defaults, and migrate to this tier when the settings file arrives | correction enabled, correction strength, selected engine, selected calibration profile, virtual-camera on/off + format |
| runtime constants — code defaults + CLI | `AppSettings`, exactly as today | correction consecutive-error budget, fade/ramp durations, output-worker join timeout |
| model/engine constants | per-engine settings dataclass in the engine's module (the `GazeSettings` pattern) | mask feathering, warp limits, ONNX provider options |
| developer/debug | `--dev`-gated flags and dev-mode UI, as today | overlay layers, mask debug view, metrics detail |

Calibration profiles are data files, not settings, and live beside `logs/`
and `models/` in the per-user directory. The persisted-settings file format
and migration policy are M6/M10 SA; the tier boundaries are fixed now so new
knobs land in the right place from M3 onward.

## Dependency direction

```text
  ui, main ──────────────▶ pipeline ───────▶ contracts ◀─────── engines/stages
 (Qt only here)   (runtime, processor,   (camera.models,      (camera.source/capture,
      │            buffers, staged        tracking.models,     tracking.*, gaze.estimator,
      │            processor)             gaze.models,         correction.*, calibration.*,
      ▼                                   correction.models*,  output.worker*)
   config, logging, diagnostics.metrics   calibration.models*)        │
   (imported by everyone; import          tracking.models ─▶ gaze.models   ▼
    nothing above this line)              correction.models* ─▶ tracking/gaze models
                                                       backend adapter modules*
                                                       (mediapipe_tracker — mediapipe;
                                                        correction.neural* — onnxruntime;
                                                        output backend* — pyvirtualcam/…)
                                          * = future modules
```

Rules (cheap to keep; the one existing exception is named rather than
papered over):

- Contracts import contracts and stdlib/NumPy only, one direction, no
  cycles (`tracking.models → gaze.models` is the existing edge; future
  `correction.models` depends on both, nothing depends back on it).
- Backend libraries (MediaPipe, ONNX Runtime, pyvirtualcam) are imported by
  exactly one adapter module each, lazily, behind a factory.
- The UI never learns MediaPipe/ONNX/backend types. **Known exception
  today:** `MainWindow` is also the composition root — when no factory is
  injected it imports `mediapipe_tracker_factory` (and the stage modules it
  wires) to assemble the pipeline. Types still never cross; only the
  factory selection lives in the UI module. The rule is binding for every
  *new* backend: correction-engine and output-backend factories are chosen
  in entry-point/composition code, and moving tracker-factory selection
  there too is a natural M4 tidy-up, not a milestone of its own.
- Correction, calibration and output never import Qt.
- Tracking never imports correction; calibration never imports output;
  nothing imports the UI.

## Repository structure

The frozen layout is kept; the PRD §23 sketch is an example, not a target,
and rearranging to match it would churn reviewed code for nothing.

- **Already right:** `gazefix/{camera,pipeline,tracking,gaze,diagnostics,ui}`,
  `config.py`, `logging_config.py`; contracts-in-`models.py` convention;
  one-adapter-per-backend; scripts as thin wrappers over package CLIs;
  per-milestone docs plus this baseline; `docs/decisions/` ADRs.
- **Evolves naturally, in the milestone that needs it:** `gazefix/correction/`
  (M3: engine protocol, geometric engine, models, mask helpers, offline
  harness CLI + `scripts/` wrapper), `gazefix/calibration/` (M6),
  `gazefix/output/` (M8), a neural adapter inside `correction/` (M9),
  per-milestone docs (`docs/correction.md`, …).
- **Waits until actually needed:** any split of `ui/main_window.py`
  (calibration dialog arrives at M6), settings-file module (M6),
  benchmark scripts (M7), installer/packaging layout (M10). No
  restructuring is done speculatively.

## Architectural risk register

Risks that could invalidate architecture or gate a milestone — ordinary
implementation choices are excluded. Each names the milestone where it
bites and the mitigation or decision gate.

| # | Risk | Impact | Milestone | Mitigation / gate |
| --- | --- | --- | --- | --- |
| R1 | correction quality: redirected eyes look synthetic or uncanny | product fails its core promise | M3 (major quality gate) | offline-first experimentation; PO visual scoring (PRD §28); subtlety over aggressiveness (PRD §4); M3 gate verdict is allowed to be FAIL/CHANGE APPROACH |
| R2 | eye-region compositing artifacts (edges, lighting/skin mismatch, blink corruption) | uncanny output, PRD §11 violations | M3–M5 | soft masks and blending inside the engine; blink handling via openness gates; before/after review at the gate |
| R3 | temporal instability (flicker between corrected/uncorrected, strength oscillation) | unusable live output | M4–M5 | parameter-space smoothing first (fades, slew limits); image-space stabilization only as measured last resort; reset discipline already frozen |
| R4 | CPU/latency budget: inference (14.3 ms on the Linux dev machine; unmeasured on target) + correction exceeds the 24–30 FPS budget on the target laptop, or a marginal tracker burns the 100 ms wait per frame | M4/M7 acceptance miss | M4, M7 | measure at M4 on target hardware; eye-region-only processing; revisit `tracking_wait_ms`; M7 optimization; the reserved split-worker design (ADR-0003) as last step — it helps only when each stage individually fits the frame period |
| R5 | camera + virtual camera coexistence and per-client compatibility (Zoom/Meet/Teams) | M8/MVP acceptance miss | M8 | backend abstraction; one-client proof for M8 technical PASS (PRD); client matrix verified before the MVP gate |
| R6 | Windows backend behavior under a second video device (MSMF quirks, driver locks) | instability at M8/M10 | M8, M10 | frozen backend-fallback machinery; PO physical verification; qa-policy HIGH classification for vcam work |
| R7 | frame-copy overhead at 720p | latency creep | M4, M7 | copy-once rule (ADR-0003); measure before adding cleverness |
| R8 | neural model licensing (gaze-redirection models are frequently research-only) | M9 blocked or engine unshippable | M9 | license verified before adoption (dependency policy); ADR with evidence; geometric engine remains the shipping fallback |
| R9 | neural dependency complexity: ONNX Runtime beside MediaPipe under the `numpy<2` cap | unresolvable environment | M9 | resolve-check before adoption; keep runtimes in separate adapter modules; ADR-0001's pin revisit triggers |
| R10 | no stable camera identity for calibration profiles (index probing) | profiles silently applied to the wrong camera | M6 | advisory profile-camera matching with visible warnings; recalibration is cheap (<30 s, PRD §14); real enumeration is an M10 option |
| R11 | uncalibrated gaze error (±10° documented) makes correction mis-target | correction worsens eye contact | M3–M4, M6 | interpolative correction tolerates moderate error; deviation/confidence policy limits harm; calibration exists to fix exactly this; PO judgment at M3/M4 gates |

Accepted frozen debt stays as recorded: the `PreparedCameraCloser`
ambiguous-`Thread.start()` bookkeeping gap (Part I) remains non-blocking,
revisited before M10.

## Reconciliation: PRD, documentation, and frozen code

Verified during this pass; recorded rather than silently "fixed".

**PRD vs frozen code — resolved by decision:**

- PRD §15 sketches one `GazeCorrectionEngine` bundling `estimate_gaze` and
  `correct`. Frozen M2 ships gaze estimation as a separate, tested stage
  owned by tracking. **ADR-0002** resolves this: the estimator seam and the
  correction-engine seam together satisfy PRD §15's intent (a stable model
  interface, geometric/neural swappable); `estimate_gaze` is not moved into
  the correction engine.
- PRD §18 draws a linear stage diagram with gaze as a pipeline stage and a
  single processed-frame path. Frozen code runs gaze inside tracking, and
  the target adds per-consumer output buffers. Kept as built/designed; the
  PRD's binding constraints (latest-frame, no unbounded queues, UI
  decoupling, replaceable processor) are all honored.

**PRD vs frozen code — documented deviations, no action:**

- §23 repository sketch (`app/`, `devices.py`, `correction/`…) vs the actual
  `gazefix/` layout — the PRD authorizes adjustment; the layout stays.
- §21 diagnostics: CPU/memory and an inference-provider metric are not yet
  implemented (arrive M7/M9); "capture latency" exists only as
  pipeline-latency (capture-timestamp → publish), which excludes driver
  latency — the boundary is defined in `docs/tracking.md` §6 and the
  metrics module docstring.
- §17 ONNX preference: intentionally absent until M9 (milestone-scoped
  dependency rule).
- §20 UI sketch: correction/calibration/vcam controls absent (features
  don't exist); the consumer window shows more metrics than the sketch —
  acceptable at prototype stage, revisit wording at M10.
- §22: `requires-python <3.13`, contrib OpenCV, and the `mediapipe==0.10.21`
  privacy pin are recorded deviations with rationale (ADR-0001).

**Documentation vs code (nits found by inspection, left for their owning
docs' next natural edit — none is load-bearing):**

- `docs/gaze.md` §9 says the overlay prints "five factors" of confidence;
  there are six (code and README both say six).
- `README.md` setup has one garbled parenthetical implying the *shipped*
  MediaPipe uploads at close; that behavior belongs to the rejected 1.0.x
  line only (the privacy section itself is accurate).
- `gazefix/tracking/worker.py`'s module docstring claims a rebuild may cost
  "a network attempt inside close()" — unverified folklore; nothing in the
  adapter or ADR-0001's traces supports it.
- Milestone-stamped docstrings lag reality in places (`config.py` says
  "M0/M1"; `tracking/__init__.py` says "Milestone 1") — cosmetic.
- The `mirrored()` contract family is implemented and tested but has no
  caller yet (the preview is unmirrored); it is deliberate future surface,
  now noted as such.

## Stable decisions and deferred questions

**Architecture decisions now stable** (guide all future milestones; change
requires a new ADR):

1. Pipeline shape: capture → latest-frame buffer → one processing worker →
   per-consumer one-slot output buffers; newest-wins everywhere; no queues
   (frozen + ADR-0003).
2. Tracking + gaze remain on the tracker thread exactly as frozen; gaze
   estimation stays owned by tracking, not by correction engines (ADR-0002).
3. Correction is a separate stage on the processing worker behind the
   `CorrectionEngine` protocol; engines own masks and compositing; policy
   (deviation/confidence → effective strength) is outside engines
   (ADR-0002).
4. One processing worker through M4–M8, with a defined, measurement-gated
   split trigger and a reserved split design (ADR-0003).
5. Frame ownership: published frames immutable; correction copies once,
   downstream reuses; `ProcessedFrame` re-frozen before fan-out (ADR-0003).
6. Every stage is its own failure domain with its own bounded budget and
   explicit retirement/revival; no shared processing-error mechanism.
7. Contracts are immutable, identity-carrying, explicit-unavailability
   dataclasses; new stages follow the existing contract rules.
8. Substitution pattern: small protocol + factory + single adapter module
   per external backend (MediaPipe today; ONNX, pyvirtualcam later).
9. Dependency direction as diagrammed; the five prohibition rules.
10. Four-tier configuration ownership; persisted settings arrive with M6.
11. Virtual camera is an independent consumer on its own thread and buffer;
    its failure never stops the pipeline.
12. Diagnostics extend `PipelineMetrics` in place; no telemetry service.
13. Repository layout evolves by adding milestone packages; no speculative
    restructuring.

**Deferred to M3 SA:** warp/redirection technique; mask construction and
blending method; eye-region definition; the strength↔deviation curve values;
harness input formats and CLI shape; the PRD §28 scoring procedure;
`CorrectionResult` debug-metadata fields.

**Deferred to later milestone SA:** M5 — whether image-space output
stabilization is needed at all, and its algorithm; M6 — calibration math,
profile schema/persistence format, sampling UI, settings-file format; M7 —
optimization targets, psutil adoption, and whether the split trigger fires;
M8 — virtual-camera backend choice (ADR then), pacing/format details,
client-compatibility handling; M9 — neural model choice, ONNX
provider/DirectML strategy, model licensing (ADR then), and whether any
model justifies revisiting gaze-estimation ownership; M10 — settings
persistence scope, installer/packaging, real device enumeration,
production-hardening backlog including the accepted M0 closer debt.

**Left to runtime / Product Owner experimentation:** correction naturalness
thresholds and default strength; the deviation-curve breakpoints; glasses/
lighting behavior; Windows runtime network confirmation (standing PO check
from M1); physical performance numbers on the target laptop.
