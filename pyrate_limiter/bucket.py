""" Implement this class to create
a workable bucket for Limiter to use
"""
from abc import ABC
from abc import abstractmethod
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from .exceptions import BucketFullException
from .rate import Rate
from .rate import RateItem


class AbstractBucket(ABC):
    """Base bucket `SYNCHRONOUS` interface"""

    @abstractmethod
    def put(self, item: RateItem, rates: List[Rate]) -> None:
        """Put an item (typically the current time) in the bucket"""


class AbstractAsyncBucket(ABC):
    """Base bucket `ASYNCHRONOUS` interface"""

    @abstractmethod
    async def put(self, item: RateItem, rates: List[Rate]) -> None:
        """Put an item (typically the current time) in the bucket"""


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
    def __init__(self):
        self.items = []

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
            return pivot_idx + self.binary_search(items[pivot_idx:], lower)

        # NOTE: code will not reach here, but must refactor
        return -1

    def count(self, items: List[RateItem], upper: int, window_length: int) -> int:
        """Count how many items within the window"""
        lower = upper - window_length
        counter = 0

        idx = self.binary_search(items, lower)

        if idx is not None:
            counter = len(items) - idx
            return counter

        return 0

    def put(self, item: RateItem, rates: List[Rate]) -> None:
        from threading import Lock

        with Lock():
            for rate in rates:
                if not self.count(self.items, item.timestamp, rate.interval) <= (rate.limit - item.weight):
                    raise BucketFullException(item.name, rate, -1)

            self.items.append(item)


class DefaultBucketFactory(BucketFactory):
    buckets: Dict[str, SimpleListBucket]

    def __init__(self):
        self.buckets = dict()

    def get(self, item: RateItem) -> SimpleListBucket:
        if item.name not in self.buckets:
            bucket = SimpleListBucket()
            self.buckets.update({item.name: bucket})

        return self.buckets[item.name]
