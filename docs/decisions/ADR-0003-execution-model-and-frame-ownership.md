# ADR-0003: One processing worker through M4–M8; copy-once frame ownership; per-consumer output buffers

**Status:** accepted for M3–M10 (2026-09-04) at the overall architecture pass;
independently reviewed, corrected, and **frozen 2026-09-05** as part of the
canonical post-M2 architecture baseline (`architecture-v1`). Amend only through
milestone Solution Architecture or a deliberate new ADR, never by silent edits
during implementation. **Decides:** the execution model that
carries correction, compositing and virtual-camera output into the frozen
real-time pipeline, who may write to frame memory and when frames are
copied, and how multiple consumers receive processed frames.

## Context

The frozen M2 pipeline is: capture worker → one-slot latest-frame buffer →
processing worker (tracking via the tracker thread's bounded hand-off) →
one-slot output buffer → Qt-polled preview. Captured frames are marked
read-only and shared by reference across threads; the only copies today are
the tracker's RGB conversion, the dev overlay's drawing copy, and the
preview's detached `QImage.copy()`. The PRD's binding constraints: prefer
the newest frame, no unbounded queues anywhere, UI decoupled from capture,
720p ≥ 24 FPS with < 100 ms processing latency on a CPU-only i7/Iris Xe
laptop, and continuity of video over correction.

M4 adds per-frame correction work; M8 adds a second consumer (virtual
camera) that may be slower or block in a driver. Both invite accidental
complexity: speculative worker fan-out, in-place mutation, or frame queues.

## Decision

1. **One processing worker through M4–M8.** Tracking + gaze stay on the
   tracker thread exactly as frozen. Target resolution, correction policy,
   the correction engine, and the dev overlay run serially on the existing
   `gazefix-processor` thread. No new frame-path thread is introduced at
   M4.

2. **A measurement-gated split trigger, designed now and built only if
   needed.** With submit-then-wait, per-frame cost is ≈
   `min(inference, tracking_wait_ms) + correction` in series; the frame
   period is 33 ms at 30 FPS and ~42 ms at the 24 FPS floor. Tracking
   inference measured 14.3 ms median on the Linux development machine
   (ADR-0001); the target laptop is unmeasured until M4, and a tracker
   that misses `tracking_wait_ms` (100 ms) breaks the arithmetic outright
   (a timed-out frame costs up to the full wait and passes uncorrected) —
   whether 100 ms remains the right wait bound once the same thread also
   corrects is an M4 revisit item. If, after M4 measurement and per-stage
   optimization (and re-checked at M7), inference + correction exceeds the
   ~42 ms floor on the target machine, correction moves to a dedicated
   worker fed by a one-slot latest-value hand-off — the tracker thread's
   proven pattern — so inference of frame N+1 overlaps correction of
   frame N. Splitting helps only when each term individually fits the
   frame period (post-split throughput is `max(inference, correction)`);
   an inference-dominated miss is remedied tracker-side, not with more
   workers. Cost of splitting: one extra frame of latency and a second
   stale-result guard (the same `belongs_to` identity check). Until the
   trigger fires, the split does not exist.

3. **A lifecycle-isolation trigger, independent of the split trigger.**
   Steady-state throughput and lifecycle blocking are separate concerns: a
   component can fit the average frame budget and still stall the sole
   frame publisher during engine/model/provider initialization, provider
   switching, reset, or shutdown/cleanup. Newest-wins buffering prevents
   queued stale-frame latency from accumulating; it does not keep frames
   flowing while the worker itself is inside a blocking call. Therefore:
   an engine or provider whose lifecycle transitions cannot be bounded
   tightly enough to preserve video continuity must initialize or
   transition **off the active frame-publication path**, the way the
   frozen tracker already loads its model on the tracker thread while
   frames pass through as `INITIALIZING`. While such a transition is
   pending, the live pipeline keeps publishing safe original/passthrough
   frames (correction `SKIPPED (initializing)`); a transition that
   completes late or was superseded (newer camera generation, engine
   selection, or session) is discarded under the existing
   generation/identity rules and never applied to newer state; the
   transitioning resource keeps a single owner with explicit bounded
   cleanup. **No extra worker or thread is created until an actual engine
   or provider requires this behavior** — the geometric engine's lifecycle
   is trivial and stays synchronous; the M9 neural engine's
   session/provider setup is the expected first candidate.

4. **Backpressure stays newest-wins at every boundary.** Slow correction
   lowers output FPS by replacement in the capture buffer; queued
   stale-frame latency cannot accumulate and no frame queue ever forms.
   That guarantee is about queuing only — it does not shorten a blocking
   operation already executing on the worker, which is what item 3 exists
   for. Slow consumers replace values in their own output buffers and
   affect nobody else.

5. **Copy-once frame ownership.** Captured frames remain immutable and
   shared. The correction engine allocates exactly **one** writable working
   copy per corrected frame and blends into it; the dev overlay reuses
   that same copy when correction ran — via a small compatible M4
   draw-into-owned-canvas helper, because the frozen `render_overlay`
   always allocates a copy of its own (the copy-producing wrapper stays
   for existing callers); with correction skipped, the overlay's own copy
   is the frame's single copy, as today. The working canvas is exclusively
   owned by the staged processor until publication, only it may be
   mutated, no writable alias survives publication, and the copy is
   re-frozen (`setflags(write=False)`) before publication, so
   `ProcessedFrame.frame` is immutable for all consumers. Uncorrected,
   un-overlaid frames pass through as the original read-only array with
   zero copies. Per corrected 720p frame: one ≈2.8 MB copy
   (2,764,800 bytes) plus the preview's existing QImage copy; a backend
   that needs another pixel format converts in its own adapter buffer.

6. **Per-consumer one-slot output buffers.** The processing worker
   publishes the same immutable `ProcessedFrame` reference into one buffer
   per consumer: the preview buffer (today's behavior, unchanged) and, from
   M8, an output buffer drained by a dedicated virtual-camera worker
   thread. The runtime owns both buffers and the worker always publishes to
   both — starting/stopping the virtual camera changes only consumption, so
   no buffer is attached to or detached from a running worker.
   `select_camera` clears every consumer buffer on a camera switch, and the
   output worker applies the same `camera_request_id` check before sending
   that the preview path applies on consume. `LatestValueBuffer` stays
   single-consumer per instance; fan-out is N buffers, not a multicast
   buffer. Each consumer's replacement counter is its own staleness metric.

7. **The virtual-camera worker is an isolated, window-owned consumer.**
   Like the discovery service, it is started and stopped from the UI and
   joined in `closeEvent` against the single shutdown deadline with its own
   timeout attribution; `PipelineRuntime`, its `STOPPED` latch and its
   cleanup accounting are untouched. It waits on its own buffer, converts
   and sends inside the backend adapter, stops itself after a bounded run
   of send errors, and can never backpressure or fail the pipeline; a
   wedged driver call abandons a daemon thread at process exit, the same
   rule the capture and tracker threads already follow.

## Consequences

- M4 integration is a composition change inside the existing
  `FrameProcessor` seam; capture, buffers, runtime lifecycle and UI polling
  are untouched.
- Frame-rate arithmetic is explicit: correction has a derived ~19–27 ms CPU
  budget to hold 24–30 FPS in the single-worker model, extrapolated from
  the Linux measurement until M4 measures on target hardware. That budget,
  not taste, decides the split.
- The immutability invariant survives correction: only the engine, only on
  its own working copy, only before publication. Consumers can never
  observe a mutating frame, and cross-thread mutation stays structurally
  impossible.
- Publishing by reference into two buffers means both consumers share one
  frozen frame; memory cost is bounded by slots (one frame per buffer),
  not by consumer speed.
- If the split trigger fires, the change is contained: a worker + hand-off
  slot behind the correction stage, with contracts and ownership unchanged.
- Lifecycle isolation (item 3) is specified, not built: it adds no thread
  today, and when an engine first requires it, the mechanism is the
  already-proven tracker-thread pattern — off-path initialization,
  passthrough publication while pending, generation-gated adoption of the
  finished transition, single-owner bounded cleanup.

## Alternatives considered

- **Dedicated correction worker from day one:** adds a pipeline stage of
  latency, a second stale-result path and more shutdown accounting before
  any measurement says the budget needs it. Rejected as speculative
  concurrency.
- **In-place correction on the captured frame:** breaks the shared-
  immutability invariant every thread relies on (the same array is
  concurrently referenced by buffers, the tracker's submission slot and the
  preview); saving one copy is not worth reintroducing cross-thread
  mutation risk. Rejected.
- **Multicast/broadcast buffer or subscriber registry:** more mechanism
  than two consumers justify; N one-slot buffers keep the frozen,
  well-tested type and give per-consumer replacement counters for free.
  Rejected.
- **Queue between processor and virtual camera ("don't drop sent
  frames"):** violates the PRD's no-unbounded-queue constraint and the
  freshness principle; a conferencing client wants the newest frame, not a
  backlog. Rejected.
- **Shared-memory pools / triple buffering / GPU surfaces:** premature at
  720p CPU scale; nothing measured motivates them. Rejected until M7
  evidence says otherwise.
