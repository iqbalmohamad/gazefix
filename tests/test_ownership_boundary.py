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
    assert runtime.prepared_closer.outstanding == 0  # ...never by the runtime
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
    assert runtime.prepared_closer.join(2.0)
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
    closer = runtime.prepared_closer
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
    assert runtime.prepared_closer.outstanding == 1  # app accounting still sees it
    gate.set()
    assert runtime.prepared_closer.join(2.0) and warm.closed and warm.close_calls == 1


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
    assert runtime.prepared_closer.outstanding == 1
    assert discovery_closer.outstanding == 1  # counted by its own owner only

    runtime_gate.set()
    assert runtime.prepared_closer.join(2.0) and warm_r.closed
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
