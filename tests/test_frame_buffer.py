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
    polls: list[float] = []

    def cancelled() -> bool:
        # Evaluated under the buffer's condition, first on entry to the wait.
        # Once it has run, the consumer holds the condition until wait()
        # releases it, so wake_all below cannot acquire the condition before
        # the consumer is actually parked: the notification is delivered to
        # a real waiter, deterministically, with no sleep to line it up.
        polls.append(time.perf_counter())
        return stop.is_set()

    def consume() -> None:
        began = time.perf_counter()
        buffer.wait_for_latest(timeout=5.0, cancelled=cancelled)
        released.append(time.perf_counter() - began)

    thread = Thread(target=consume)
    thread.start()
    deadline = time.perf_counter() + 2.0
    while not polls and time.perf_counter() < deadline:
        time.sleep(0.001)  # observing progress, not creating the interleaving
    assert polls, "consumer never reached the wait"
    stop.set()  # flag first, then the notification, as ProcessingWorker.stop does
    buffer.wake_all()
    thread.join(2.0)
    assert not thread.is_alive() and released and released[0] < 1.0
    assert len(polls) >= 2  # the predicate ran again on wake: the 'during the wait' path
