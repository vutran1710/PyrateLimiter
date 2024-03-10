""" Implement this class to create
a workable bucket for Limiter to use
"""
import asyncio
import logging
from abc import ABC
from abc import abstractmethod
from collections import defaultdict
from inspect import isawaitable
from threading import Thread
from typing import Awaitable
from typing import Dict
from typing import List
from typing import Optional
from typing import Type
from typing import Union

from .clock import AbstractClock
from .rate import Rate
from .rate import RateItem

logger = logging.getLogger("pyrate_limiter")


class AbstractBucket(ABC):
    """Base bucket interface
    Assumption: len(rates) always > 0
    TODO: allow empty rates
    """

    rates: List[Rate]
    failing_rate: Optional[Rate] = None

    @abstractmethod
    def put(self, item: RateItem) -> Union[bool, Awaitable[bool]]:
        """Put an item (typically the current time) in the bucket
        return true if successful, otherwise false
        """

    @abstractmethod
    def leak(
        self,
        current_timestamp: Optional[int] = None,
    ) -> Union[int, Awaitable[int]]:
        """leaking bucket - removing items that are outdated"""

    @abstractmethod
    def flush(self) -> Union[None, Awaitable[None]]:
        """Flush the whole bucket
        - Must remove `failing-rate` after flushing
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

    def waiting(self, item: RateItem) -> Union[int, Awaitable[int]]:
        """Calculate time until bucket become availabe to consume an item again"""
        if self.failing_rate is None:
            return 0

        assert item.weight > 0, "Item's weight must > 0"

        if item.weight > self.failing_rate.limit:
            return -1

        bound_item = self.peek(self.failing_rate.limit - item.weight)

        if bound_item is None:
            # NOTE: No waiting, bucket is immediately ready
            return 0

        def _calc_waiting(inner_bound_item: RateItem) -> int:
            nonlocal item
            assert self.failing_rate is not None  # NOTE: silence mypy
            lower_time_bound = item.timestamp - self.failing_rate.interval
            upper_time_bound = inner_bound_item.timestamp
            return upper_time_bound - lower_time_bound

        async def _calc_waiting_async() -> int:
            nonlocal item, bound_item

            while isawaitable(bound_item):
                bound_item = await bound_item

            if bound_item is None:
                # NOTE: No waiting, bucket is immediately ready
                return 0

            assert isinstance(bound_item, RateItem)
            return _calc_waiting(bound_item)

        if isawaitable(bound_item):
            return _calc_waiting_async()

        assert isinstance(bound_item, RateItem)
        return _calc_waiting(bound_item)


class BucketFactory(ABC):
    """Asbtract BucketFactory class.
    It is reserved for user to implement/override this class with
    his own bucket-routing/creating logic
    """

    leak_interval: int = 10_000
    _buckets: Optional[Dict[int, AbstractBucket]] = None
    _clocks: Optional[Dict[int, AbstractClock]] = None
    _t: Optional[Thread] = None

    @abstractmethod
    def wrap_item(
        self,
        name: str,
        weight: int = 1,
    ) -> Union[RateItem, Awaitable[RateItem]]:
        """Add the current timestamp to the receiving item using any clock backend
        - Turn it into a RateItem
        - Can return either a coroutine or a RateItem instance
        """

    @abstractmethod
    def get(self, item: RateItem) -> AbstractBucket:
        """Get the corresponding bucket to this item"""

    def create(
        self,
        clock: AbstractClock,
        bucket_class: Type[AbstractBucket],
        *args,
        **kwargs,
    ) -> AbstractBucket:
        """Creating a bucket dynamically"""
        bucket = bucket_class(*args, **kwargs)
        self.schedule_leak(bucket, clock)
        return bucket

    def schedule_leak(self, new_bucket: AbstractBucket, associated_clock: AbstractClock) -> None:
        """Schedule all the buckets' leak, reset bucket's failing rate"""
        assert new_bucket.rates

        if self._buckets is None:
            self._buckets = defaultdict()

        if self._clocks is None:
            self._clocks = defaultdict()

        bucket_id = id(new_bucket)
        self._buckets[bucket_id] = new_bucket
        self._clocks[bucket_id] = associated_clock

        if self._t:
            return

        async def _background_leak():
            while True:
                for bucket_id, bucket in list(self._buckets.items()):
                    clock = self._clocks[bucket_id]
                    now = clock.now()

                    while isawaitable(now):
                        now = await now

                    assert isinstance(now, int)
                    leak = bucket.leak(now)

                    while isawaitable(leak):
                        leak = await leak

                    assert isinstance(leak, int)

                    if leak > 0:
                        logger.debug("(async)leaking bucket: %s, %s items", bucket, leak)

                await asyncio.sleep(self.leak_interval / 1000)

        def wrap():
            asyncio.run(_background_leak())

        self._t = Thread(target=wrap, daemon=True, name="PyrateLimiter Background Leaks")
        self._t.start()


class BucketAsyncWrapper(AbstractBucket):
    """BucketAsyncWrapper is a wrapping over any bucket
    that turns a async/synchronous bucket into an async one
    """

    def __init__(self, bucket: AbstractBucket):
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

    async def waiting(self, item: RateItem) -> int:
        wait = super().waiting(item)

        if isawaitable(wait):
            wait = await wait

        assert isinstance(wait, int)
        return wait

    @property
    def failing_rate(self):
        return self.bucket.failing_rate

    @property
    def rates(self):
        return self.bucket.rates
