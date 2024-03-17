""" Implement this class to create
a workable bucket for Limiter to use
"""
import asyncio
import logging
from abc import ABC
from abc import abstractmethod
from collections import defaultdict
from inspect import isawaitable
from inspect import iscoroutine
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


class Leaker(Thread):
    """Responsible for scheduling buckets' leaking at the background either
    through a daemon task(for sync buckets) or a task using asyncio.Task
    """

    daemon = True
    name = "PyrateLimiter's Leaker"
    sync_buckets: Optional[Dict[int, AbstractBucket]] = None
    async_buckets: Optional[Dict[int, AbstractBucket]] = None
    clocks: Optional[Dict[int, AbstractClock]] = None
    leak_interval: int = 10_000
    is_async_leak_started = False

    def __init__(self, leak_interval: int):
        self.sync_buckets = defaultdict()
        self.async_buckets = defaultdict()
        self.clocks = defaultdict()
        self.leak_interval = leak_interval
        self._task = None
        super().__init__()

    def register(self, bucket: AbstractBucket, clock: AbstractClock):
        """Register a new bucket with its associated clock"""
        assert self.sync_buckets is not None
        assert self.clocks is not None
        assert self.async_buckets is not None

        try_leak = bucket.leak(0)

        if iscoroutine(try_leak):
            try_leak.close()
            self.async_buckets[id(bucket)] = bucket
        else:
            self.sync_buckets[id(bucket)] = bucket

        self.clocks[id(bucket)] = clock

    async def _leak(self, sync=True) -> None:
        assert self.clocks

        while True:
            buckets = self.sync_buckets if sync else self.async_buckets
            assert buckets

            for bucket_id, bucket in list(buckets.items()):
                clock = self.clocks[bucket_id]
                now = clock.now()

                while isawaitable(now):
                    now = await now

                assert isinstance(now, int)
                leak = bucket.leak(now)

                while isawaitable(leak):
                    leak = await leak

                assert isinstance(leak, int)

                bucket_type = "sync" if sync else "async"
                logger.debug("> Leaking (%s) bucket: %s, %s items", bucket_type, bucket, leak)

            await asyncio.sleep(self.leak_interval / 1000)

    def leak_async(self):
        if self.async_buckets and not self.is_async_leak_started:
            self.is_async_leak_started = True
            self._task = asyncio.create_task(self._leak(sync=False))

    def run(self) -> None:
        assert self.sync_buckets
        asyncio.run(self._leak(sync=True))

    def start(self) -> None:
        if self.sync_buckets and not self.is_alive():
            super().start()

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()


class BucketFactory(ABC):
    """Asbtract BucketFactory class.
    It is reserved for user to implement/override this class with
    his own bucket-routing/creating logic
    """

    _leaker: Optional[Leaker] = None
    _leak_interval: int = 10_000

    @property
    def leak_interval(self) -> int:
        """Retrieve leak-interval from inner Leaker task"""
        if not self._leaker:
            return self._leak_interval
        return self._leaker.leak_interval

    @leak_interval.setter
    def leak_interval(self, value: int):
        """Set leak-interval for inner Leaker task"""
        if self._leaker:
            self._leaker.leak_interval = value
        self._leak_interval = value

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

        if not self._leaker:
            self._leaker = Leaker(self.leak_interval)

        self._leaker.register(new_bucket, associated_clock)
        self._leaker.start()
        self._leaker.leak_async()


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
