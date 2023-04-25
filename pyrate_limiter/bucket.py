""" Implement this class to create
a workable bucket for Limiter to use
"""
from abc import ABC
from abc import abstractmethod
from threading import Lock
from threading import Thread
from time import sleep
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from .exceptions import BucketFullException
from .rate import Rate
from .rate import RateItem


class AbstractBucket(ABC):
    """Base bucket `SYNCHRONOUS` interface"""

    @abstractmethod
    def put(self, item: RateItem, rates: List[Rate]) -> None:
        """Put an item (typically the current time) in the bucket"""

    @abstractmethod
    def leak(self) -> int:
        """Schedule a leak and run in a task"""


class AbstractAsyncBucket(ABC):
    """Base bucket `ASYNCHRONOUS` interface"""

    @abstractmethod
    async def put(self, item: RateItem, rates: List[Rate]) -> None:
        """Put an item (typically the current time) in the bucket"""

    @abstractmethod
    async def leak(self) -> int:
        """Schedule a leak and run in a task"""


class BucketFactory(ABC):
    """Asbtract BucketFactory class
    User must implement this class should
    he wants to use a custom bucket backend
    """

    @abstractmethod
    def get(self, item: RateItem) -> Union[AbstractBucket, AbstractAsyncBucket]:
        """Init or get the corresponding bucket to this item"""


# Default implementation of Bucket, in-memory list
class SimpleListBucket(AbstractBucket):
    leak_from_idx: int = 0
    leak_task: Thread

    def __init__(self):
        self.items = []
        self.lock = Lock()
        self.leak_task = Thread(target=self._leak_until_empty)

    def _leak_until_empty(self):
        while self.items:
            sleep(10)
            self.leak()

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

        assert False

    def put(self, item: RateItem, rates: List[Rate]) -> None:
        with self.lock:
            for rate_idx, rate in enumerate(rates):
                count, idx = self.count(self.items, item.timestamp, rate.interval)
                if not count <= (rate.limit - item.weight):
                    raise BucketFullException(item.name, rate, -1)

                if rate_idx == len(rates) - 1:
                    self.leak_from_idx = idx

            self.items.append(item)

            if not self.leak_task.is_alive():
                print("start leaking...")
                self.leak_task.start()

    def leak(self) -> int:
        with self.lock:
            self.items = self.items[self.leak_from_idx :]
            return self.leak_from_idx


class DefaultBucketFactory(BucketFactory):
    buckets: Dict[str, SimpleListBucket]

    def __init__(self):
        self.buckets = {}
        self.lock = Lock()

    def get(self, item: RateItem) -> SimpleListBucket:
        with self.lock:
            if item.name not in self.buckets:
                bucket = SimpleListBucket()
                self.buckets.update({item.name: bucket})

            return self.buckets[item.name]
