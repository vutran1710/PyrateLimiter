from threading import Lock
from threading import Thread
from typing import List
from typing import Optional

from .bucket import AbstractBucket
from .rate import Rate
from .rate import RateItem
from .utils import binary_search
from .utils import LocalClock


class SimpleListBucket(AbstractBucket):
    """Simple In-memory Bucket using native list
    Clock can be either `time.time` or `time.monotonic`
    Pros: fast, safe, and precise
    Cons: since it resides in local memory, the data is not persistent, nor scalable
    Usecase: small applications, simple logic
    """

    items: List[RateItem]
    rate_at_limit: Optional[Rate]
    _clock: LocalClock

    def __init__(
        self,
        rates: List[Rate],
        clock: LocalClock = LocalClock.TIME,
    ):
        self.rates = sorted(rates, key=lambda r: r.interval)
        self._clock = clock

        self.items = []
        self.lock = Lock()
        self.leak_task = Thread(target=self.leak)

    def clock(self) -> int:
        return self._clock()  # type: ignore

    def put(self, item: RateItem) -> bool:
        with self.lock:
            for rate in self.rates:
                lower_bound_value = self.clock() - rate.interval
                lower_bound_idx = binary_search(self.items, lower_bound_value)

                if lower_bound_idx >= 0:
                    count_existing_items = len(self.items) - lower_bound_idx
                    space_available = rate.limit - count_existing_items
                else:
                    space_available = rate.limit

                if space_available < item.weight:
                    self.rate_at_limit = rate
                    return False

            self.rate_at_limit = None
            item.timestamp = self.clock()
            self.items.append(item)
            return True

    def leak(self) -> int:
        return -1
