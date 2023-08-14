""" Implement this class to create
a workable bucket for Limiter to use
"""
from abc import ABC
from abc import abstractmethod
from inspect import isawaitable
from typing import Awaitable
from typing import List
from typing import Optional
from typing import Union

from .rate import Rate
from .rate import RateItem


class AbstractBucket(ABC):
    """Base bucket interface
    Assumption: len(rates) always > 0
    TODO: allow empty rates
    """

    rates: List[Rate]
    failing_rate: Optional[Rate] = None

    @abstractmethod
    def put(self, item: RateItem) -> Union[bool, Awaitable[bool]]:
        """Put an item (typically the current time) in the bucket"""

    @abstractmethod
    def leak(
        self,
        current_timestamp: Optional[int] = None,
    ) -> Union[int, Awaitable[int]]:
        """Schedule a leak and run in a task"""

    @abstractmethod
    def flush(self) -> Union[None, Awaitable[None]]:
        """Flush the whole bucket
        Must remove `failing-rate` after flushing
        """

    @abstractmethod
    def count(self) -> Union[int, Awaitable[int]]:
        """Count number of items in the bucket"""

    @abstractmethod
    def peek(self, index: int) -> Union[Optional[RateItem], Awaitable[Optional[RateItem]]]:
        """Peek at the rate-item at a specific index in latest-to-earliest order
        NOTE: The reason we cannot peek from the start of the queue(earliest-to-latest) is
        we can't really tell how many outdated items are still in the queue
        """


class BucketFactory(ABC):
    """Asbtract BucketFactory class
    User must implement this class should
    he wants to use a custom bucket backend
    """

    @abstractmethod
    def wrap_item(
        self,
        name: str,
        weight: int = 1,
    ) -> Union[RateItem, Awaitable[RateItem]]:
        """Mark the current timestamp to the receiving item,
        Wrap it into a RateItem
        Can return either a coroutine or a RateItem instance
        """

    @abstractmethod
    def get(self, item: RateItem) -> Union[AbstractBucket]:
        """Create or get the corresponding bucket to this item"""

    @abstractmethod
    def schedule_leak(self) -> None:
        """Schedule all the buckets' leak, reset bucket's failing rate"""

    @abstractmethod
    def schedule_flush(self) -> None:
        """Schedule all the buckets' flush, reset bucket's failing rate"""


def get_bucket_availability(bucket: Union[AbstractBucket], item: RateItem) -> Union[int, Awaitable[int]]:
    """Use clock to calculate time until bucket become availabe"""
    assert bucket.failing_rate is not None, "Wrong use!"
    assert item.weight > 0

    if item.weight > bucket.failing_rate.limit:
        return -1

    bound_item = bucket.peek(bucket.failing_rate.limit - item.weight)
    assert bound_item is not None, "Bound-item not found"

    def _calc_availability(inner_bound_item: RateItem) -> int:
        nonlocal item
        assert bucket.failing_rate is not None  # NOTE: silence mypy
        lower_time_bound = item.timestamp - bucket.failing_rate.interval
        upper_time_bound = inner_bound_item.timestamp
        return upper_time_bound - lower_time_bound

    async def _calc_availability_async() -> int:
        nonlocal item, bound_item

        while isawaitable(bound_item):
            bound_item = await bound_item
        # NOTE: if there is a failing rate, then this can't be None!
        assert isinstance(bound_item, RateItem), "Bound-item not a valid rate-item"
        return _calc_availability(bound_item)

    if isawaitable(bound_item):
        return _calc_availability_async()

    assert isinstance(bound_item, RateItem)
    return _calc_availability(bound_item)


class BucketAsyncWrapper(AbstractBucket):
    """BucketAsyncWrapper is a wrapping over any bucket
    that turns a async/synchronous bucket into an async one
    """

    def __init__(self, bucket: Union[AbstractBucket]):
        assert isinstance(bucket, AbstractBucket)
        self.bucket = bucket

    async def put(self, item: RateItem):
        result = self.bucket.put(item)

        while isawaitable(result):
            result = await result

        return result

    async def count(self):
        result = self.bucket.count()

        while isawaitable(result):
            result = await result

        return result

    async def leak(self, current_timestamp: Optional[int] = None) -> int:
        result = self.bucket.leak(current_timestamp)

        while isawaitable(result):
            result = await result

        assert isinstance(result, int)
        return result

    async def flush(self) -> None:
        result = self.bucket.flush()

        while isawaitable(result):
            result = await result

        return None

    async def peek(self, index: int) -> Optional[RateItem]:
        item = self.bucket.peek(index)

        while isawaitable(item):
            item = await item

        assert item is None or isinstance(item, RateItem)
        return item

    @property
    def failing_rate(self):
        return self.bucket.failing_rate

    @property
    def rates(self):
        return self.bucket.rates
