from threading import Thread
import time

from gazefix.pipeline.frame_buffer import LatestValueBuffer


def test_latest_value_wins_without_queue_growth() -> None:
    buffer: LatestValueBuffer[int] = LatestValueBuffer()

    for value in range(100):
        buffer.publish(value)

    latest = buffer.consume_latest()
    assert latest is not None
    assert latest.value == 99
    assert latest.sequence == 100
    assert buffer.replaced_count == 99


def test_consumed_value_is_not_counted_as_replaced() -> None:
    buffer: LatestValueBuffer[str] = LatestValueBuffer()
    buffer.publish("first")
    first = buffer.consume_latest()
    assert first is not None

    buffer.publish("second")
    assert buffer.replaced_count == 0


def test_waiter_receives_newest_published_value() -> None:
    buffer: LatestValueBuffer[int] = LatestValueBuffer()
    observed: list[int] = []

    def consume() -> None:
        item = buffer.wait_for_latest(timeout=1.0)
        if item is not None:
            observed.append(item.value)

    thread = Thread(target=consume)
    thread.start()
    time.sleep(0.01)
    buffer.publish(42)
    thread.join(1.0)

    assert not thread.is_alive()
    assert observed == [42]



def test_wait_is_released_by_a_cancellation_set_before_or_during_the_wait() -> None:
    """A stop flag set before the waiter arrives must not cost it the timeout."""

    from threading import Event

    buffer: LatestValueBuffer[int] = LatestValueBuffer()
    stop = Event()
    stop.set()
    started = time.perf_counter()
    assert buffer.wait_for_latest(timeout=1.0, cancelled=stop.is_set) is None
    assert time.perf_counter() - started < 0.5  # returned at once, not after the timeout

    stop = Event()
    released: list[float] = []

    def consume() -> None:
        began = time.perf_counter()
        buffer.wait_for_latest(timeout=5.0, cancelled=stop.is_set)
        released.append(time.perf_counter() - began)

    thread = Thread(target=consume)
    thread.start()
    time.sleep(0.02)
    stop.set()  # flag first, then the notification, as ProcessingWorker.stop does
    buffer.wake_all()
    thread.join(2.0)
    assert not thread.is_alive() and released and released[0] < 1.0
