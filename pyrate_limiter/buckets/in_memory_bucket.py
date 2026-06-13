"""Naive bucket implementation using built-in list"""

from bisect import bisect_left
from operator import attrgetter
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

    def __init__(self, rates: List[Rate]):
        super().__init__()

        self.rates = rates  # AbstractBucket.rates setter sorts + validates
        self.items = []

    def put(self, item: RateItem) -> bool:
        if item.weight == 0:
            return True

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
        if self.items:
            max_interval = self.rates[-1].interval
            lower_bound = current_timestamp - max_interval

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
        self.failing_rate = None
        del self.items[:]

    def count(self) -> int:
        return len(self.items)

    def peek(self, index: int) -> RateItem | None:
        if not self.items:
            return None

        return self.items[-1 - index] if abs(index) < self.count() else None
