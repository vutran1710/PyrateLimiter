from threading import Lock
from time import time
from typing import List
from typing import Optional
from typing import Tuple

from .bucket import AbstractBucket
from .rate import Rate
from .rate import RateItem


class SimpleListBucket(AbstractBucket):
    items: List[RateItem]

    def __init__(self, rates: List[Rate]):
        self.rates = sorted(rates, key=lambda r: r.interval)
        self.items = []
        self.lock = Lock()

    def binary_search(self, items: List[RateItem], lower: int) -> Optional[int]:
        if not items:
            return None

        if items[0].timestamp > lower:
            return 0

        if items[-1].timestamp < lower:
            return None

        pivot_idx = int(len(items) / 2)

        left = items[pivot_idx - 1].timestamp
        right = items[pivot_idx].timestamp

        if left < lower <= right:
            return pivot_idx

        if left >= lower:
            return self.binary_search(items[:pivot_idx], lower)

        if right < lower:
            next_idx = self.binary_search(items[pivot_idx:], lower)
            return pivot_idx + next_idx if next_idx is not None else None

        # NOTE: code will not reach here, but must refactor
        return -1

    def count(self, items: List[RateItem], upper: int, window_length: int) -> Tuple[int, int]:
        """Count how many items within the window"""
        lower = upper - window_length
        counter = 0

        idx = self.binary_search(items, lower)

        if idx is not None:
            counter = len(items) - idx
            return counter, idx

        return 0, 0

    def put(self, item: RateItem) -> bool:
        with self.lock:
            for rate_idx, rate in enumerate(self.rates):
                count, idx = self.count(self.items, item.timestamp, rate.interval)
                if not count <= (rate.limit - item.weight):
                    return False

            self.items.append(item)
            return True

    def clock(self) -> int:
        return int(1000 * time())

    def leak(self) -> int:
        with self.lock:
            now = self.clock()
            window_lower_bound = now - self.rates[-1].interval - 1
            idx = self.binary_search(self.items, window_lower_bound)

            if idx is not None and idx > 0:
                self.items = self.items[idx:]
                return idx

            return 0
