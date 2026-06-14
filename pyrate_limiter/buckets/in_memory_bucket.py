"""Naive bucket implementation using built-in list"""

from bisect import bisect_left
from operator import attrgetter
from threading import RLock
from typing import List, Optional

from ..abstracts.bucket import AbstractBucket
from ..abstracts.rate import Rate, RateItem

# Items are kept sorted by timestamp ascending; key for bisect lookups.
_by_timestamp = attrgetter("timestamp")


class InMemoryBucket(AbstractBucket):
    """Simple In-memory Bucket using native list
    Clock can be either `time.time` or `time.monotonic`
    When leak, clock is required
    Pros: fast, safe, and precise
    Cons: since it resides in local memory, the data is not persistent, nor scalable
    Usecase: small applications, simple logic
    """

    items: List[RateItem]
    failing_rate: Optional[Rate]
    is_async = False

    def __init__(self, rates: List[Rate]):
        super().__init__()

        self.rates = rates  # AbstractBucket.rates setter sorts + validates
        self.items = []
        # Guards `self.items` against the background Leaker thread, which calls
        # leak() WITHOUT holding the Limiter lock. Without this, leak()'s
        # `del self.items[:idx]` can interleave with put()/peek() and corrupt
        # window counts or raise IndexError (issue #300). RLock so the methods
        # may call each other (peek -> count) re-entrantly.
        self._lock = RLock()

    def put(self, item: RateItem) -> bool:
        if item.weight == 0:
            return True

        with self._lock:
            # In-memory native implementation of the SlidingWindowLog policy
            # (see self._algorithm): the admit decision is the same
            # `limit - count < weight` check, kept inline here so the
            # `after_length < limit` shortcut can skip the bisect entirely
            # rather than materialising a full per-rate counts list.
            current_length = len(self.items)
            after_length = item.weight + current_length

            for rate in self.rates:
                if after_length < rate.limit:
                    break

                lower_bound_value = item.timestamp - rate.interval
                # First item still inside this rate's window (timestamp >= lower bound).
                # When all items are older, bisect returns len(items) -> 0 in window.
                lower_bound_idx = bisect_left(self.items, lower_bound_value, key=_by_timestamp)
                count_existing_items = len(self.items) - lower_bound_idx
                space_available = rate.limit - count_existing_items

                if space_available < item.weight:
                    self.failing_rate = rate
                    return False

            self.failing_rate = None

            if item.weight > 1:
                self.items.extend([item for _ in range(item.weight)])
            else:
                self.items.append(item)

            return True

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        assert current_timestamp is not None
        with self._lock:
            if self.items:
                lower_bound = self._algorithm.leak_bound(self.rates, current_timestamp)

                if lower_bound > self.items[-1].timestamp:
                    remove_count = len(self.items)
                    del self.items[:]
                    return remove_count

                if lower_bound < self.items[0].timestamp:
                    return 0

                idx = bisect_left(self.items, lower_bound, key=_by_timestamp)
                del self.items[:idx]
                return idx

            return 0

    def flush(self) -> None:
        with self._lock:
            self.failing_rate = None
            del self.items[:]

    def count(self) -> int:
        with self._lock:
            return len(self.items)

    def peek(self, index: int) -> RateItem | None:
        with self._lock:
            if not self.items:
                return None

            return self.items[-1 - index] if abs(index) < self.count() else None

    def __getstate__(self):
        """A threading RLock can't be pickled; drop it and recreate on
        unpickle so the Limiter stays picklable (issue #262)."""
        state = self.__dict__.copy()
        state.pop("_lock", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._lock = RLock()
