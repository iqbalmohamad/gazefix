from threading import Event

from gazefix.camera.discovery import CameraDiscoveryService, discover_camera_devices
from gazefix.camera.models import CameraDevice, CameraOpenResult
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
