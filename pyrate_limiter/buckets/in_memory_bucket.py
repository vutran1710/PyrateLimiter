from threading import RLock as Lock
from typing import Coroutine
from typing import List
from typing import Optional
from typing import Union

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem
from ..utils import binary_search


class InMemoryBucket(AbstractBucket):
    """Simple In-memory Bucket using native list
    Clock can be either `time.time` or `time.monotonic`
    When leak, clock is required
    Pros: fast, safe, and precise
    Cons: since it resides in local memory, the data is not persistent, nor scalable
    Usecase: small applications, simple logic
    """

    items: List[RateItem]
    lock: Lock
    failing_rate: Optional[Rate]

    def __init__(self, rates: List[Rate]):
        self.rates = sorted(rates, key=lambda r: r.interval)
        self.items = []
        self.lock = Lock()
        self.failing_rate = None

    def put(self, item: RateItem) -> bool:
        with self.lock:
            for rate in self.rates:
                lower_bound_value = item.timestamp - rate.interval
                lower_bound_idx = binary_search(self.items, lower_bound_value)

                if lower_bound_idx >= 0:
                    count_existing_items = len(self.items) - lower_bound_idx
                    space_available = rate.limit - count_existing_items
                else:
                    space_available = rate.limit

                if space_available < item.weight:
                    self.failing_rate = rate
                    return False

            self.failing_rate = None
            self.items.extend(item.weight * [item])
            return True

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        assert current_timestamp is not None
        with self.lock:
            if self.items:
                max_interval = self.rates[-1].interval
                lower_bound = current_timestamp - max_interval

                if lower_bound > self.items[-1].timestamp:
                    remove_count = len(self.items)
                    self.items = []
                    return remove_count

                if lower_bound < self.items[0].timestamp:
                    return 0

                idx = binary_search(self.items, lower_bound)
                self.items = self.items[idx:]
                return idx

            return 0

    def flush(self) -> None:
        with self.lock:
            self.items = []

    def count(self) -> int:
        return len(self.items)

    def availability(self, weight: int) -> Union[int, Coroutine[None, None, int]]:
        if self.failing_rate is None:
            if weight > self.rates[-1].limit:
                return -1

            return 0

        aggregated_weight = 0
        cursor = 0

        while aggregated_weight < weight:
            aggregated_weight += self.items[cursor].weight
            cursor += 1

        if cursor == 0:
            # NOTE: technically, this first item is the lower bound of the time interval
            # and it means the bucket is immediately available
            # To avoid flaky-ness, we add a slight delay here (10ms)
            return 10

        remaining_time = self.items[cursor].timestamp - self.items[0].timestamp
        return remaining_time
