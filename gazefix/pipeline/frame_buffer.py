"""A single-value overwrite buffer for real-time frame freshness."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Condition
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class VersionedValue(Generic[T]):
    sequence: int
    value: T


class LatestValueBuffer(Generic[T]):
    """Thread-safe, single-consumer buffer in which the newest value wins.

    Publishing never blocks. If an unread value is replaced, it is discarded and
    ``replaced_count`` is incremented. The buffer therefore uses constant memory
    even when a producer is much faster than its consumer.
    """

    def __init__(self) -> None:
        self._condition = Condition()
        self._value: T | None = None
        self._sequence = 0
        self._last_consumed_sequence = 0
        self._replaced_count = 0

    def publish(self, value: T) -> int:
        with self._condition:
            if self._value is not None and self._sequence > self._last_consumed_sequence:
                self._replaced_count += 1
            self._sequence += 1
            self._value = value
            self._condition.notify_all()
            return self._sequence

    def consume_latest(self, after_sequence: int = 0) -> VersionedValue[T] | None:
        with self._condition:
            return self._consume_if_new(after_sequence)

    def wait_for_latest(
        self, after_sequence: int = 0, timeout: float | None = None
    ) -> VersionedValue[T] | None:
        with self._condition:
            if self._value is None or self._sequence <= after_sequence:
                self._condition.wait_for(
                    lambda: self._value is not None and self._sequence > after_sequence,
                    timeout=timeout,
                )
            return self._consume_if_new(after_sequence)

    def _consume_if_new(self, after_sequence: int) -> VersionedValue[T] | None:
        if self._value is None or self._sequence <= after_sequence:
            return None
        self._last_consumed_sequence = max(
            self._last_consumed_sequence, self._sequence
        )
        return VersionedValue(self._sequence, self._value)

    def clear(self) -> None:
        with self._condition:
            self._value = None
            self._last_consumed_sequence = self._sequence
            self._condition.notify_all()

    def wake_all(self) -> None:
        """Wake waiting workers so they can observe their own stop event."""

        with self._condition:
            self._condition.notify_all()

    @property
    def replaced_count(self) -> int:
        with self._condition:
            return self._replaced_count

    @property
    def sequence(self) -> int:
        with self._condition:
            return self._sequence

