from threading import Event
import time

from camera_fakes import FakeCameraSource, factory_for, wait_until
from gazefix.camera.discovery import (
    CameraDiscoveryService,
    DiscoveryResult,
    discover_camera_devices,
    probe_camera,
)
from gazefix.camera.models import CameraDevice, CameraOpenResult
from gazefix.camera.source import PreparedCamera
from gazefix.config import AppSettings


def test_discovery_returns_only_validated_candidates() -> None:
    probed: list[int] = []

    def probe(index: int) -> CameraDevice | None:
        probed.append(index)
        return CameraDevice(index) if index in {1, 3} else None

    settings = AppSettings(camera_probe_limit=5)
    devices = discover_camera_devices(settings, probe=probe)

    assert [device.index for device in devices] == [1, 3]
    assert probed == [0, 1, 2, 3, 4]


def test_discovery_honors_shutdown_request() -> None:
    stop_event = Event()
    calls = 0

    def probe(index: int) -> CameraDevice | None:
        nonlocal calls
        calls += 1
        stop_event.set()
        return CameraDevice(index)

    devices = discover_camera_devices(
        AppSettings(camera_probe_limit=5), stop_event=stop_event, probe=probe
    )

    assert calls == 1
    assert devices == [CameraDevice(0)]


class BlockingCameraSource:
    def __init__(self, started: Event) -> None:
        self.started = started
        self.interrupted = Event()

    def open(self, device: CameraDevice) -> CameraOpenResult:
        self.started.set()
        self.interrupted.wait(2.0)
        raise RuntimeError("interrupted")

    def read(self):  # type: ignore[no-untyped-def]
        return False, None

    def close(self) -> None:
        pass

    def interrupt(self) -> None:
        self.interrupted.set()


def test_discovery_service_interrupts_blocked_camera_open() -> None:
    started = Event()
    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=1),
        on_finished=lambda _devices: None,
        on_error=lambda _message: None,
        source_factory=lambda _settings: BlockingCameraSource(started),
    )

    assert service.start()
    assert started.wait(0.5)

    assert service.stop(timeout=1.0)
    assert not service.is_running


def test_probe_relies_on_open_validation_and_closes_unless_kept() -> None:
    sources: list[FakeCameraSource] = []
    device = probe_camera(0, AppSettings(), source_factory=factory_for(sources))
    assert device is not None and device.index == 0 and device.validated_backend is not None
    assert sources[0].open_calls == 1 and sources[0].reads == 0
    assert sources[0].closed

    kept: list[PreparedCamera] = []
    device = probe_camera(
        1, AppSettings(), source_factory=factory_for(sources), on_prepared=kept.append
    )
    assert device is not None and len(kept) == 1
    assert kept[0].device == device and not sources[1].closed
    assert kept[0].close_if_unclaimed() and sources[1].closed


def test_probe_reports_failure_and_closes_source() -> None:
    sources: list[FakeCameraSource] = []
    assert probe_camera(2, AppSettings(), source_factory=factory_for(sources, openable=set())) is None
    assert sources[0].closed


def test_service_hands_over_first_validated_camera_still_open() -> None:
    sources: list[FakeCameraSource] = []
    results: list[DiscoveryResult] = []
    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=4),
        on_finished=results.append,
        on_error=lambda _message: None,
        source_factory=factory_for(sources, openable={1, 2}),
    )
    assert service.start()
    assert wait_until(lambda: bool(results))
    result = results[0]
    assert [d.index for d in result.devices] == [1, 2]
    assert result.prepared is not None and result.prepared.device == result.devices[0]
    assert result.prepared.is_pending
    by_index = {s.index: s for s in sources if s.index is not None}
    assert not by_index[1].closed  # handed over open
    assert by_index[2].closed  # only the first candidate is kept
    assert all(s.closed for s in sources if s.index is None)  # failed probes released

    claimed = result.prepared.claim()
    assert claimed is not None and claimed[0] is by_index[1]
    assert service.stop(1.0)
    assert not by_index[1].closed  # claimed sources belong to the claimant


def test_service_closes_unclaimed_prepared_camera_on_stop_and_on_restart() -> None:
    sources: list[FakeCameraSource] = []
    results: list[DiscoveryResult] = []
    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=1),
        on_finished=results.append,
        on_error=lambda _message: None,
        source_factory=factory_for(sources),
    )
    assert service.start()
    assert wait_until(lambda: len(results) == 1)
    assert wait_until(lambda: not service.is_running)
    first = sources[0]
    assert not first.closed

    assert service.start()  # nobody claimed it; the new run closes it
    assert wait_until(lambda: len(results) == 2)
    assert first.closed
    assert not results[1].prepared.is_pending or not sources[1].closed

    assert service.stop(1.0)
    assert sources[1].closed
    assert not results[1].prepared.is_pending


def test_service_keep_first_open_can_be_disabled() -> None:
    sources: list[FakeCameraSource] = []
    results: list[DiscoveryResult] = []
    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=2),
        on_finished=results.append,
        on_error=lambda _message: None,
        source_factory=factory_for(sources),
        keep_first_open=False,
    )
    assert service.start()
    assert wait_until(lambda: bool(results))
    assert results[0].prepared is None
    assert wait_until(lambda: all(s.closed for s in sources))


def test_request_stop_then_join_bounds_shutdown_and_closes_prepared() -> None:
    sources: list[FakeCameraSource] = []
    slow = Event()

    class SlowSecondProbe(FakeCameraSource):
        def open(self, device: CameraDevice) -> CameraOpenResult:
            if device.index == 1:
                self.open_started.set()
                self.interrupted.wait(2.0)
                raise RuntimeError("interrupted")
            return super().open(device)

    def create(_settings: AppSettings) -> SlowSecondProbe:
        return SlowSecondProbe(sources)

    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=3),
        on_finished=lambda _result: None,
        on_error=lambda _message: None,
        source_factory=create,
    )
    assert service.start()
    assert wait_until(lambda: len(sources) == 2 and sources[1].open_started.is_set())
    started = time.perf_counter()
    service.request_stop()
    assert service.join(1.0)
    assert time.perf_counter() - started < 1.0
    assert sources[1].interrupt_calls == 1
    assert sources[0].closed  # the kept-open first candidate was never adopted
    assert len(sources) == 2  # index 2 was never probed
    slow.set()


def test_service_keeps_the_requested_index_open_when_it_validates() -> None:
    sources: list[FakeCameraSource] = []
    results: list[DiscoveryResult] = []
    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=3),
        on_finished=results.append,
        on_error=lambda _message: None,
        source_factory=factory_for(sources),
    )
    assert service.start(keep_open_index=2)
    assert wait_until(lambda: bool(results))
    result = results[0]
    assert [d.index for d in result.devices] == [0, 1, 2]
    assert result.prepared is not None and result.prepared.device.index == 2
    by_index = {s.index: s for s in sources}
    assert by_index[0].closed and by_index[1].closed and not by_index[2].closed
    assert service.stop(1.0)
    assert by_index[2].closed


def test_service_falls_back_to_first_candidate_when_requested_index_is_gone() -> None:
    sources: list[FakeCameraSource] = []
    results: list[DiscoveryResult] = []
    service = CameraDiscoveryService(
        AppSettings(camera_probe_limit=2),
        on_finished=results.append,
        on_error=lambda _message: None,
        source_factory=factory_for(sources, openable={0}),
    )
    assert service.start(keep_open_index=1)
    assert wait_until(lambda: bool(results))
    assert [d.index for d in results[0].devices] == [0]
    assert results[0].prepared is None  # nothing kept open: the UI opens index 0 itself
    assert all(s.closed for s in sources)
    assert service.stop(1.0)
