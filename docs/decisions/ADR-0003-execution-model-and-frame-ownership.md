# ADR-0003: One processing worker through M4–M8; copy-once frame ownership; per-consumer output buffers

**Status:** proposed at the overall architecture pass (2026-09-04), awaiting
Product Manager architecture review. **Decides:** the execution model that
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
   needed.** With submit-then-wait, per-frame cost is ≈ tracking inference
   (~14 ms measured, ADR-0001) + correction, in series; the frame period is
   33 ms at 30 FPS and 41 ms at the 24 FPS floor. If, after M4 measurement
   and per-stage optimization (and re-checked at M7), inference +
   correction exceeds the 41 ms floor on the target machine, correction
   moves to a dedicated worker fed by a one-slot latest-value hand-off —
   the tracker thread's proven pattern — so inference of frame N+1 overlaps
   correction of frame N. Cost of splitting: one extra frame of latency and
   a second stale-result guard (the same `belongs_to` identity check).
   Until the trigger fires, the split does not exist.

3. **Backpressure stays newest-wins at every boundary.** Slow correction
   lowers output FPS by replacement in the capture buffer; it never grows
   latency and never forms a queue. Slow consumers replace values in their
   own output buffers and affect nobody else.

4. **Copy-once frame ownership.** Captured frames remain immutable and
   shared. The correction engine allocates exactly **one** writable working
   copy per corrected frame and blends into it; the dev overlay draws on
   that same copy when correction ran (its own copy of the original
   otherwise, as today); the copy is re-frozen (`setflags(write=False)`)
   before publication, so `ProcessedFrame.frame` is immutable for all
   consumers. Uncorrected frames pass through as the original read-only
   array with zero copies. Per corrected 720p frame: one ≈2.7 MB copy plus
   the preview's existing QImage copy; a backend that needs another pixel
   format converts in its own adapter buffer.

5. **Per-consumer one-slot output buffers.** The processing worker
   publishes the same immutable `ProcessedFrame` reference into one buffer
   per consumer: the preview buffer (today's behavior, unchanged) and, from
   M8, an output buffer drained by a dedicated virtual-camera worker
   thread. `LatestValueBuffer` stays single-consumer per instance;
   fan-out is N buffers, not a multicast buffer. Each consumer's
   replacement counter is its own staleness metric.

6. **The virtual-camera worker is an isolated consumer.** It waits on its
   own buffer, converts and sends inside the backend adapter, stops itself
   after a bounded run of send errors, and is joined against a bounded
   deadline at shutdown like every other worker. It can never backpressure
   or fail the pipeline; a wedged driver call abandons a daemon thread at
   process exit, the same rule the capture and tracker threads already
   follow.

## Consequences

- M4 integration is a composition change inside the existing
  `FrameProcessor` seam; capture, buffers, runtime lifecycle and UI polling
  are untouched.
- Frame-rate arithmetic is explicit: correction has a ~15–25 ms CPU budget
  to hold 24–30 FPS in the single-worker model. That budget, not taste,
  decides the split.
- The immutability invariant survives correction: only the engine, only on
  its own working copy, only before publication. Consumers can never
  observe a mutating frame, and cross-thread mutation stays structurally
  impossible.
- Publishing by reference into two buffers means both consumers share one
  frozen frame; memory cost is bounded by slots (one frame per buffer),
  not by consumer speed.
- If the split trigger fires, the change is contained: a worker + hand-off
  slot behind the correction stage, with contracts and ownership unchanged.

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
