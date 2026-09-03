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

