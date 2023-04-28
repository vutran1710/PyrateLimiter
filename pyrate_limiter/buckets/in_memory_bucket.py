from threading import RLock as Lock
from typing import List
from typing import Optional

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem
from ..abstracts import SyncClock
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

    def put(self, item: RateItem) -> bool:
        with self.lock:
            for rate in self.rates:
                if len(self.items) < rate.limit:
                    continue

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

    def leak(self, clock: Optional[SyncClock] = None) -> int:
        assert clock is not None
        with self.lock:
            if self.items:
                max_interval = self.rates[-1].interval
                now = clock.now()
                lower_bound = now - max_interval

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
