"""Owner-scoped cleanup accounting and the monotonic runtime lifecycle.

Regression coverage for the PR #3 re-review blocker: one cleanup thread was
shared between the runtime and discovery, so discovery's deferred token could
flip a finalized runtime back to ``STOPPING``, and a refused request racing
``stop()``'s final check could produce ``True`` with runtime cleanup appearing
afterwards. Now the runtime owns a private cleanup thread, ``STOPPED`` is a
latch taken under the lifecycle lock, and refused-token registration is
serialized under that same lock. Every race here is driven by events or by
hooks placed on the exact wait; nothing sleeps to line an interleaving up.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from threading import Event, Thread

import pytest

from camera_fakes import FakeCameraSource, factory_for, wait_until
from gazefix.camera.discovery import CameraDiscoveryService, DiscoveryResult
from gazefix.camera.models import CameraDevice
from gazefix.camera.source import PreparedCamera, PreparedCameraCloser
from gazefix.config import AppSettings
from gazefix.pipeline.runtime import PipelineRuntime, RuntimeState


DEADLINE_S = 0.05


def settings(**overrides: object) -> AppSettings:
    base = dict(
        reconnect_delay_s=0.01,
        read_retry_delay_s=0.001,
        worker_join_timeout_s=DEADLINE_S,
    )
    base.update(overrides)
    return replace(AppSettings(), **base)  # type: ignore[arg-type]


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == name]


def prepared_token(index: int, close_gate: Event | None = None) -> tuple[FakeCameraSource, PreparedCamera]:
    warm = FakeCameraSource(close_gate=close_gate)
    device = CameraDevice(index)
    return warm, PreparedCamera(device, warm, warm.open(device))


def stopped_runtime(**overrides: object) -> PipelineRuntime:
    runtime = PipelineRuntime(settings(**overrides), source_factory=factory_for([]))
    runtime.start()
    assert runtime.stop() is True
    assert runtime.state is RuntimeState.STOPPED
    return runtime


# --- 1 + 4: discovery cannot resurrect a finalized runtime ----------------------


def test_runtime_stays_stopped_when_discovery_later_hands_off_its_own_token() -> None:
    """Codex's reproduction: stop() True, then discovery.join submits a token.

    With owner-scoped closers the token lands on discovery's cleanup thread;
    the runtime's lifecycle never sees it.
    """

    runtime = stopped_runtime()
    gate = Event()
    discovery_closer = PreparedCameraCloser("test-discovery-close")
    sources: list[FakeCameraSource] = []
    results: list[DiscoveryResult] = []
    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=1),
        on_finished=results.append,
        on_error=lambda _m: None,
        source_factory=factory_for(sources, close_gate=gate),
        prepared_closer=discovery_closer,
    )
    assert service.start()
    assert wait_until(lambda: bool(results) and not service.is_running)
    assert results[0].prepared is not None and results[0].prepared.is_pending

    service.request_stop()
    assert service.join(1.0)  # hands the unadopted token to discovery's closer
    assert discovery_closer.outstanding == 1  # tracked by its owner...
    assert runtime.cleanup_outstanding == 0  # ...never by the runtime
    assert runtime.state is RuntimeState.STOPPED  # no STOPPED -> STOPPING
    assert runtime.stop() is True  # and stop() stays True

    gate.set()
    assert discovery_closer.join(2.0)
    assert runtime.state is RuntimeState.STOPPED


def test_no_stopped_to_stopping_transition_under_any_later_submission() -> None:
    """Hammer a finalized runtime with every post-shutdown token path."""

    runtime = stopped_runtime()
    observed: list[RuntimeState] = []
    for index in range(5):
        warm, token = prepared_token(index)
        runtime.select_camera(CameraDevice(index), token)  # refused: disposal
        observed.append(runtime.state)
        runtime._capture.request_camera(CameraDevice(index + 10), None)  # worker-level refusal
        observed.append(runtime.state)
        assert wait_until(lambda: warm.closed)  # never leaked
    assert runtime.join_cleanup(2.0)
    observed.append(runtime.state)
    assert observed == [RuntimeState.STOPPED] * len(observed)
    assert runtime.stop() is True


# --- 3: the refused-request race against the final check ------------------------


def test_refused_token_registered_before_the_final_check_denies_success(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Codex's interleaving, made deterministic with a barrier on the last wait.

    The refused registration lands after stop()'s joins but before its final
    check. Serialization under the lifecycle lock means the check must see it:
    stop() returns False, state is STOPPING, and only draining the token
    finalizes the runtime. stop() == True can therefore never coexist with
    runtime-owned cleanup registered before the check.
    """

    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    runtime.start()
    closer = runtime._closer  # test seam: the private cleanup thread
    gate = Event()
    warm, token = prepared_token(7, gate)
    at_final_wait, refusal_done = Event(), Event()
    original_join = closer.join

    def join_then_wait_for_the_refusal(timeout: float) -> bool:
        result = original_join(timeout)
        if not at_final_wait.is_set():  # only the wind-down's own join
            at_final_wait.set()
            assert refusal_done.wait(2.0)
        return result

    monkeypatch.setattr(closer, "join", join_then_wait_for_the_refusal)

    def refuse_between_joins_and_final_check() -> None:
        assert at_final_wait.wait(2.0)
        runtime.select_camera(CameraDevice(7), token)  # refused: stop in progress
        refusal_done.set()

    racer = Thread(target=refuse_between_joins_and_final_check)
    racer.start()
    result = runtime.stop()
    racer.join(2.0)
    assert not racer.is_alive()

    assert result is False  # the registered token denied success
    assert runtime.state is RuntimeState.STOPPING
    assert closer.outstanding == 1
    assert wait_until(lambda: warm.close_calls == 1) and not warm.closed  # in flight, off-thread

    gate.set()
    assert closer.join(2.0) and warm.closed
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert warm.close_calls == 1


def test_refused_token_after_the_latch_is_disposed_without_reviving_the_lifecycle() -> None:
    """The other side of the race: registration after finalization is a disposal."""

    runtime = stopped_runtime(worker_join_timeout_s=0.5)
    gate = Event()
    warm, token = prepared_token(3, gate)
    runtime.select_camera(CameraDevice(3), token)
    assert runtime.state is RuntimeState.STOPPED  # latched
    assert runtime.stop() is True  # still True with a disposal in flight
    assert runtime.cleanup_outstanding == 1  # app accounting still sees it
    gate.set()
    assert runtime.join_cleanup(2.0) and warm.closed and warm.close_calls == 1


# --- 5 + 7: independent, owner-scoped accounting --------------------------------


def test_runtime_and_discovery_cleanup_are_accounted_independently() -> None:
    runtime_gate, discovery_gate = Event(), Event()
    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    warm_r, token_r = prepared_token(1, runtime_gate)
    # Never started: the token stays in the worker's request slot, so stop()
    # deterministically takes it over as runtime-owned cleanup.
    runtime.select_camera(CameraDevice(1), token_r)
    discovery_closer = PreparedCameraCloser("test-discovery-close")
    warm_d, token_d = prepared_token(2, discovery_gate)
    discovery_closer.submit(token_d)

    assert runtime.stop() is False  # runtime-owned release blocked: STOPPING/False
    assert runtime.state is RuntimeState.STOPPING
    assert runtime.cleanup_outstanding == 1
    assert discovery_closer.outstanding == 1  # counted by its own owner only

    runtime_gate.set()
    assert runtime.join_cleanup(2.0) and warm_r.closed
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert discovery_closer.outstanding == 1  # still blocked; runtime unaffected
    discovery_gate.set()
    assert discovery_closer.join(2.0) and warm_d.closed


# --- 8 + 9: claim-once and no-op accounting --------------------------------------


def test_two_closers_racing_the_same_token_release_it_exactly_once() -> None:
    for _ in range(50):
        first = PreparedCameraCloser("test-close-a")
        second = PreparedCameraCloser("test-close-b")
        warm, token = prepared_token(0)
        first.submit(token)
        second.submit(token)
        assert first.join(2.0) and second.join(2.0)
        assert warm.closed and warm.close_calls == 1  # claim-once: one release


def test_an_already_claimed_token_is_dropped_at_submit_and_never_counted() -> None:
    closer = PreparedCameraCloser("test-close")
    warm, token = prepared_token(4)
    assert token.claim() is not None  # someone adopted it
    closer.submit(token)
    assert closer.outstanding == 0  # dropped on the spot, not a queued no-op
    assert closer.join(0.5)
    assert warm.close_calls == 0  # the claimant owns the source


# --- The hand-off accounting barrier (Cases A-D of the final review) -------------


def gated_take(runtime: PipelineRuntime, *, before: bool) -> tuple[Event, Event]:
    """Pause the first slot-to-closer transfer, before or during it.

    ``before=True`` gates the whole sweep (the token is still in the worker's
    slots while paused); ``before=False`` gates the cleanup thread's first
    acceptance (the token has been extracted and sits in the runtime's
    retained storage while paused). Neither pause holds any lock, so
    concurrent ``state``/``stop()`` calls run freely. Returns
    ``(paused, resume)``; later calls pass through untouched.
    """

    paused, resume = Event(), Event()
    if before:
        original_sweep = runtime._submit_pending_prepared

        def sweep() -> None:
            if not paused.is_set():
                paused.set()
                assert resume.wait(5.0)
            original_sweep()

        runtime._submit_pending_prepared = sweep  # type: ignore[method-assign]
    else:
        original_submit = runtime._closer.submit

        def submit(prepared: PreparedCamera) -> None:
            if not paused.is_set():
                paused.set()
                assert resume.wait(5.0)
            original_submit(prepared)

        runtime._closer.submit = submit  # type: ignore[method-assign]
    return paused, resume


@pytest.mark.parametrize("pause_before_take", [False, True], ids=["mid-transfer", "pre-sweep"])
def test_case_a_finalization_is_denied_while_a_pre_existing_token_is_in_handoff(pause_before_take: bool) -> None:
    """Case A: stop-before-start with an accepted token, paused in the hand-off.

    The reviewer's reproduction: the token has left (or not yet left) the
    worker's slots and has not reached the cleanup thread. Neither a state
    read nor a second stop() may finalize during that window, and with the
    release blocked the runtime stays STOPPING/False until cleanup completes.
    """

    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    close_gate = Event()
    warm, token = prepared_token(0, close_gate)
    runtime.select_camera(CameraDevice(0), token)  # accepted: runtime-owned work
    paused, resume = gated_take(runtime, before=pause_before_take)

    first_stop: dict[str, bool] = {}
    stopper = Thread(target=lambda: first_stop.setdefault("result", runtime.stop()))
    stopper.start()
    assert paused.wait(2.0)
    # The old accounting gap: token still in the slots, or extracted but not
    # yet accepted by the cleanup thread (now durably retained and counted).
    assert runtime.state is RuntimeState.STOPPING  # a state read cannot latch
    assert runtime.stop() is False  # a concurrent second stop cannot latch
    assert runtime.state is RuntimeState.STOPPING
    resume.set()
    stopper.join(3.0)
    assert not stopper.is_alive()

    assert first_stop["result"] is False  # release blocked: no success
    assert runtime.state is RuntimeState.STOPPING
    assert runtime.cleanup_outstanding == 1
    assert wait_until(lambda: warm.close_calls == 1) and not warm.closed

    close_gate.set()
    assert runtime.join_cleanup(2.0) and warm.closed
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert warm.close_calls == 1  # exactly one release; never reclassified away


def test_case_b_second_stop_cannot_latch_during_another_stops_handoff() -> None:
    """Case B: two concurrent stop() calls; one is inside the hand-off.

    With an unblocked release, the paused stop() itself must still finish as
    True only after the token is really released: pre-existing runtime-owned
    work is never reported successful while merely in transfer.
    """

    runtime = PipelineRuntime(settings(worker_join_timeout_s=1.0), source_factory=factory_for([]))
    warm, token = prepared_token(1)
    runtime.select_camera(CameraDevice(1), token)
    paused, resume = gated_take(runtime, before=False)

    first_stop: dict[str, bool] = {}
    stopper = Thread(target=lambda: first_stop.setdefault("result", runtime.stop()))
    stopper.start()
    assert paused.wait(2.0)
    assert runtime.stop() is False  # the accounting gap is closed
    assert runtime.state is RuntimeState.STOPPING
    resume.set()
    stopper.join(3.0)
    assert not stopper.is_alive()

    # The paused stop() resumed, registered the token, and waited for its
    # release within its own deadline; True therefore implies released.
    assert first_stop["result"] is True
    assert warm.closed and warm.close_calls == 1
    assert runtime.state is RuntimeState.STOPPED
    assert runtime.stop() is True


def test_case_c_worker_death_alone_cannot_finalize_past_an_in_handoff_token() -> None:
    """Case C: a real started capture worker exits mid-shutdown while a
    pre-existing token is still in hand-off; its death must not open the latch."""

    from camera_fakes import fake_open_result
    from gazefix.camera.models import CameraOpenResult

    open_gate = Event()
    sources: list[FakeCameraSource] = []

    class GatedOpenSource(FakeCameraSource):
        def __init__(self, registry: list[FakeCameraSource]) -> None:
            super().__init__(registry)

        def open(self, device: CameraDevice) -> CameraOpenResult:
            self.open_calls += 1
            self.open_started.set()
            open_gate.wait(10.0)
            self.index = device.index
            self.closed = False
            return fake_open_result()

        def interrupt(self) -> None:
            self.interrupt_calls += 1  # flag only

    runtime = PipelineRuntime(settings(), source_factory=lambda _s: GatedOpenSource(sources))
    runtime.start()
    runtime.select_camera(CameraDevice(0))
    assert wait_until(lambda: bool(sources) and sources[0].open_started.is_set())
    close_gate = Event()
    warm, token = prepared_token(5, close_gate)
    runtime.select_camera(CameraDevice(5), token)  # lands in the slots; worker is stuck
    paused, resume = gated_take(runtime, before=False)

    first_stop: dict[str, bool] = {}
    stopper = Thread(target=lambda: first_stop.setdefault("result", runtime.stop()))
    stopper.start()
    assert paused.wait(2.0)  # token taken from the slots, not yet with the closer
    open_gate.set()  # the driver returns; the worker sees stop and dies
    assert wait_until(lambda: not runtime.workers_alive, timeout=3.0)
    assert sources[0].closed  # it released its own camera on its own thread
    # Worker death alone must not finalize: the token is still in hand-off.
    assert runtime.state is RuntimeState.STOPPING
    assert runtime.stop() is False
    resume.set()
    stopper.join(3.0)
    assert not stopper.is_alive()

    assert first_stop["result"] is False  # its release is gated
    assert runtime.state is RuntimeState.STOPPING and runtime.cleanup_outstanding == 1
    close_gate.set()
    assert runtime.join_cleanup(2.0) and warm.closed and warm.close_calls == 1
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED


def test_case_d_pre_existing_work_and_post_latch_disposals_are_distinguished() -> None:
    """Case D: the same runtime shows both contracts, in order.

    A token accepted before shutdown blocks finalization until released; a
    genuinely new token refused after finalization is disposed asynchronously
    without reopening the lifecycle.
    """

    pre_gate = Event()
    runtime = PipelineRuntime(settings(), source_factory=factory_for([]))
    warm_pre, token_pre = prepared_token(1, pre_gate)
    runtime.select_camera(CameraDevice(1), token_pre)  # pre-existing runtime-owned work

    assert runtime.stop() is False  # blocked release: never True while it lives
    assert runtime.state is RuntimeState.STOPPING
    pre_gate.set()
    assert runtime.join_cleanup(2.0) and warm_pre.closed
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED

    post_gate = Event()
    warm_post, token_post = prepared_token(2, post_gate)
    runtime.select_camera(CameraDevice(2), token_post)  # genuinely new, post-latch
    assert runtime.state is RuntimeState.STOPPED  # asynchronous disposal, no reopen
    assert runtime.stop() is True
    assert runtime.cleanup_outstanding == 1  # still visible to app accounting
    post_gate.set()
    assert runtime.join_cleanup(2.0) and warm_post.closed and warm_post.close_calls == 1
    assert runtime.state is RuntimeState.STOPPED


# --- Exception-safe ownership retention (Cases E-I of the final review) ----------


def accepted_tokens(runtime: PipelineRuntime, count: int = 3) -> list[FakeCameraSource]:
    """Accept ``count`` prepared tokens pre-stop; earlier ones become orphans."""

    warms: list[FakeCameraSource] = []
    for index in range(count):
        warm, token = prepared_token(index)
        runtime.select_camera(CameraDevice(index), token)
        warms.append(warm)
    return warms


class FaultySubmit:
    """Closer.submit fault injection: raise after ``accept_first`` acceptances."""

    def __init__(self, runtime: PipelineRuntime, accept_first: int = 0) -> None:
        self.original = runtime._closer.submit
        self.accept_first = accept_first
        self.accepted = 0
        self.armed = True
        runtime._closer.submit = self  # type: ignore[method-assign]

    def __call__(self, prepared: PreparedCamera) -> None:
        if self.armed and self.accepted >= self.accept_first:
            raise RuntimeError("queue insertion failed")
        self.accepted += 1
        self.original(prepared)


def test_case_e_registration_failure_before_any_acceptance_retains_everything() -> None:
    runtime = PipelineRuntime(settings(worker_join_timeout_s=0.5), source_factory=factory_for([]))
    warms = accepted_tokens(runtime)
    fault = FaultySubmit(runtime, accept_first=0)

    for _ in range(1):
        assert runtime.stop() is False  # cannot finalize with retained work
    assert runtime.state is RuntimeState.STOPPING
    assert runtime.cleanup_outstanding == 3  # every token accounted for
    assert [w.close_calls for w in warms] == [0, 0, 0]
    assert len(runtime._retained_prepared) == 3  # durably runtime-owned, retryable

    fault.armed = False  # the fault is removed; retry via the next shutdown
    assert runtime.stop() is True
    assert runtime.state is RuntimeState.STOPPED
    assert runtime.join_cleanup(2.0)
    assert [w.closed for w in warms] == [True, True, True]
    assert [w.close_calls for w in warms] == [1, 1, 1]  # exactly once each


def test_case_f_partial_acceptance_splits_ownership_without_loss_or_overlap() -> None:
    runtime = PipelineRuntime(settings(worker_join_timeout_s=0.5), source_factory=factory_for([]))
    warms = accepted_tokens(runtime)
    fault = FaultySubmit(runtime, accept_first=1)

    assert runtime.stop() is False
    assert runtime.state is RuntimeState.STOPPING
    accepted = [w for w in warms if wait_until(lambda w=w: w.closed, timeout=1.0)]
    assert len(accepted) == 1  # the accepted prefix was released by the closer
    retained = list(runtime._retained_prepared)
    assert len(retained) == 2  # failed token + unsubmitted suffix stay runtime-owned
    assert all(token.is_pending for token in retained)  # not in both owners: still unclaimed
    assert runtime._closer.outstanding == 0  # nothing of the remainder leaked into the closer
    assert runtime.cleanup_outstanding == 2

    fault.armed = False
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert runtime.join_cleanup(2.0)
    assert [w.closed for w in warms] == [True, True, True]
    assert [w.close_calls for w in warms] == [1, 1, 1]


class FaultyRetainedList(list):
    """Runtime retained storage whose append fails after ``accept`` successes.

    Exercises the real per-token drain: a failing append must leave the
    current token (and everything behind it) still in the worker's slots.
    """

    def __init__(self, accept: int) -> None:
        super().__init__()
        self.accept = accept
        self.armed = True

    def append(self, item: PreparedCamera) -> None:  # type: ignore[override]
        if self.armed and len(self) >= self.accept:
            raise RuntimeError("batch construction failed")
        super().append(item)


def test_case_g_extraction_construction_failure_leaves_tokens_worker_owned() -> None:
    runtime = PipelineRuntime(settings(worker_join_timeout_s=0.5), source_factory=factory_for([]))
    warms = accepted_tokens(runtime)
    faulty = FaultyRetainedList(accept=1)
    runtime._retained_prepared = faulty  # the receiving storage fails mid-construction

    assert runtime.stop() is False  # cannot falsely finalize
    assert runtime.state is RuntimeState.STOPPING
    # The wind-down sweeps twice and each sweep moves exactly one token past
    # the faulty storage (append succeeds while it is empty, then trips), so
    # two tokens were moved and released and the third never left the slots:
    # no token was destructively cleared ahead of a durable owner.
    assert runtime._capture.pending_prepared_count() == 1
    assert sum(w.close_calls for w in warms) == 2
    assert runtime.cleanup_outstanding == 1

    faulty.armed = False  # fault removed: normal operation retries
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert runtime.join_cleanup(2.0)
    assert [w.closed for w in warms] == [True, True, True]
    assert [w.close_calls for w in warms] == [1, 1, 1]


def test_case_h_repeated_handoff_failure_survives_until_the_fault_is_removed() -> None:
    runtime = PipelineRuntime(settings(worker_join_timeout_s=0.5), source_factory=factory_for([]))
    warms = accepted_tokens(runtime)
    fault = FaultySubmit(runtime, accept_first=0)

    for attempt in range(3):  # repeated failed shutdowns
        assert runtime.stop() is False, attempt
        assert runtime.state is RuntimeState.STOPPING
        assert len(runtime._retained_prepared) == 3  # no loss, no duplication
        assert runtime.cleanup_outstanding == 3
        assert all(w.close_calls == 0 for w in warms)
    assert runtime.join_cleanup(0.2) is False  # join is truthful about retained work

    fault.armed = False
    assert runtime.join_cleanup(2.0)  # the app-level join is itself a recovery path
    assert [w.closed for w in warms] == [True, True, True]
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert [w.close_calls for w in warms] == [1, 1, 1]


def test_case_i_accounting_stays_truthful_while_tokens_are_retained() -> None:
    """No STOPPED, no stop() True, and honest counts while retained work exists."""

    runtime = PipelineRuntime(settings(worker_join_timeout_s=0.5), source_factory=factory_for([]))
    warms = accepted_tokens(runtime)
    fault = FaultySubmit(runtime, accept_first=0)

    observations: list[tuple[RuntimeState, int, bool]] = []
    for _ in range(2):
        result = runtime.stop()
        observations.append((runtime.state, runtime.cleanup_outstanding, result))
    assert observations == [(RuntimeState.STOPPING, 3, False)] * 2
    assert not runtime.workers_alive  # only the retained tokens hold it open

    fault.armed = False
    assert runtime.stop() is True and runtime.state is RuntimeState.STOPPED
    assert runtime.cleanup_outstanding == 0 or runtime.join_cleanup(2.0)
    assert [w.close_calls for w in warms] == [1, 1, 1]
