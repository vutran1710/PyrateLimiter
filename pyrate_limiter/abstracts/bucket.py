"""Implement this class to create
a workable bucket for Limiter to use
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from inspect import isawaitable, iscoroutine
from threading import Event, Thread
from typing import Any, Awaitable, Dict, Generic, List, Optional, Type, TypeVar, Union, overload

from ..clocks import AbstractClock, MonotonicClock
from .rate import Rate, RateItem

logger = logging.getLogger("pyrate_limiter")


class _SyncMode:
    """Sentinel type marking a synchronous bucket/factory."""


class _AsyncMode:
    """Sentinel type marking an asynchronous bucket/factory."""


_BucketMode = TypeVar("_BucketMode", _SyncMode, _AsyncMode)


class AbstractBucket(ABC, Generic[_BucketMode]):
    """Base bucket interface
    Assumption: len(rates) always > 0
    TODO: allow empty rates
    """

    rates: List[Rate]
    failing_rate: Optional[Rate] = None
    _clock: AbstractClock = MonotonicClock()

    def now(self):
        """Retrieve current timestamp from the clock backend."""
        return self._clock.now()

    @overload
    def put(self: "AbstractBucket[_SyncMode]", item: RateItem) -> bool: ...

    @overload
    def put(self: "AbstractBucket[_AsyncMode]", item: RateItem) -> Awaitable[bool]: ...

    @abstractmethod
    def put(self, item: RateItem) -> Union[bool, Awaitable[bool]]:
        """Put an item (typically the current time) in the bucket
        return true if successful, otherwise false
        """

    @overload
    def leak(self: "AbstractBucket[_SyncMode]", current_timestamp: Optional[int] = None) -> int: ...

    @overload
    def leak(self: "AbstractBucket[_AsyncMode]", current_timestamp: Optional[int] = None) -> Awaitable[int]: ...

    @abstractmethod
    def leak(
        self,
        current_timestamp: Optional[int] = None,
    ) -> Union[int, Awaitable[int]]:
        """leaking bucket - removing items that are outdated"""

    @overload
    def flush(self: "AbstractBucket[_SyncMode]") -> None: ...

    @overload
    def flush(self: "AbstractBucket[_AsyncMode]") -> Awaitable[None]: ...

    @abstractmethod
    def flush(self) -> Union[None, Awaitable[None]]:
        """Flush the whole bucket
        - Must remove `failing-rate` after flushing
        """

    @overload
    def count(self: "AbstractBucket[_SyncMode]") -> int: ...

    @overload
    def count(self: "AbstractBucket[_AsyncMode]") -> Awaitable[int]: ...

    @abstractmethod
    def count(self) -> Union[int, Awaitable[int]]:
        """Count number of items in the bucket"""

    @overload
    def peek(self: "AbstractBucket[_SyncMode]", index: int) -> Optional[RateItem]: ...

    @overload
    def peek(self: "AbstractBucket[_AsyncMode]", index: int) -> Awaitable[Optional[RateItem]]: ...

    @abstractmethod
    def peek(self, index: int) -> Union[Optional[RateItem], Awaitable[Optional[RateItem]]]:
        """Peek at the rate-item at a specific index in latest-to-earliest order
        NOTE: The reason we cannot peek from the start of the queue(earliest-to-latest) is
        we can't really tell how many outdated items are still in the queue
        """

    @overload
    def waiting(self: "AbstractBucket[_SyncMode]", item: RateItem) -> int: ...

    @overload
    def waiting(self: "AbstractBucket[_AsyncMode]", item: RateItem) -> Awaitable[int]: ...

    def waiting(self, item: RateItem) -> Union[int, Awaitable[int]]:
        """Calculate time until bucket become availabe to consume an item again"""
        if self.failing_rate is None:
            return 0

        assert item.weight > 0, "Item's weight must > 0"

        if item.weight > self.failing_rate.limit:
            return -1

        bound_item = self.peek(self.failing_rate.limit - item.weight)  # type: ignore[reportAttributeAccessIssue]

        if bound_item is None:
            # NOTE: No waiting, bucket is immediately ready
            return 0

        def _calc_waiting(inner_bound_item: RateItem) -> int:
            assert self.failing_rate is not None  # NOTE: silence mypy
            lower_time_bound = item.timestamp - self.failing_rate.interval
            upper_time_bound = inner_bound_item.timestamp
            return upper_time_bound - lower_time_bound

        async def _calc_waiting_async() -> int:
            nonlocal bound_item

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

    def limiter_lock(self) -> Optional[object]:  # type: ignore
        """An additional lock to be used by Limiter in-front of the thread lock.
        Intended for multiprocessing environments where a thread lock is insufficient.
        """
        return None

    def close(self) -> None:  # noqa: B027
        """Release any resources held by the bucket.

        Subclasses may override this method to perform any necessary cleanup
        (e.g., closing files, network connections, or releasing locks) when the
        bucket is no longer needed.
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class Leaker(Thread):
    """Responsible for scheduling buckets' leaking at the background either
    through a daemon task(for sync buckets) or a task using asyncio.Task
    """

    daemon = True
    name = "PyrateLimiter's Leaker"
    sync_buckets: Dict[int, AbstractBucket]
    async_buckets: Dict[int, AbstractBucket]
    leak_interval: int = 10_000
    aio_leak_task: Optional[asyncio.Task] = None
    _stop_event: Any

    def __init__(self, leak_interval: int):
        self.sync_buckets = defaultdict()
        self.async_buckets = defaultdict()
        self.leak_interval = leak_interval
        self._stop_event = Event()  # <--- add here

        super().__init__()

    def register(self, bucket: AbstractBucket):
        """Register a new bucket with its associated clock"""
        assert self.sync_buckets is not None
        assert self.async_buckets is not None

        try_leak = bucket.leak(0)
        bucket_id = id(bucket)

        if iscoroutine(try_leak):
            try_leak.close()
            self.async_buckets[bucket_id] = bucket
        else:
            self.sync_buckets[bucket_id] = bucket

    def deregister(self, bucket_id: int) -> bool:
        """Deregister a bucket"""
        if self.sync_buckets and bucket_id in self.sync_buckets:
            del self.sync_buckets[bucket_id]
            return True

        if self.async_buckets and bucket_id in self.async_buckets:
            del self.async_buckets[bucket_id]

            if not self.async_buckets and self.aio_leak_task:
                self.aio_leak_task.cancel()
                self.aio_leak_task = None

            return True

        return False

    async def _leak(self, buckets: Dict[int, AbstractBucket]) -> None:
        while not self._stop_event.is_set() and buckets:
            try:
                for _, bucket in tuple(buckets.items()):
                    now = bucket.now()

                    while isawaitable(now):
                        now = await now

                    assert isinstance(now, int)
                    leak = bucket.leak(now)

                    while isawaitable(leak):
                        leak = await leak

                    assert isinstance(leak, int)

                await asyncio.sleep(self.leak_interval / 1000)
            except RuntimeError as e:
                logger.debug("Leak task stopped due to event loop shutdown. %s", e)
                return

    def leak_async(self):
        if self.async_buckets and not self.aio_leak_task:
            self.aio_leak_task = asyncio.create_task(self._leak(self.async_buckets))

    def run(self) -> None:
        """Override the original method of Thread
        Not meant to be called directly
        """
        assert self.sync_buckets
        asyncio.run(self._leak(self.sync_buckets))

    def start(self) -> None:
        """Override the original method of Thread
        Call to run leaking sync buckets
        """
        if self.sync_buckets and not self.is_alive():
            super().start()

    def close(self):
        self._stop_event.set()
        self.sync_buckets.clear()
        self.async_buckets.clear()


class BucketFactory(ABC, Generic[_BucketMode]):
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

    @overload
    def wrap_item(self: "BucketFactory[_SyncMode]", name: str, weight: int = 1) -> RateItem: ...

    @overload
    def wrap_item(self: "BucketFactory[_AsyncMode]", name: str, weight: int = 1) -> Awaitable[RateItem]: ...

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

    @overload
    def get(self: "BucketFactory[_SyncMode]", item: RateItem) -> "AbstractBucket[_SyncMode]": ...

    @overload
    def get(self: "BucketFactory[_AsyncMode]", item: RateItem) -> "Awaitable[AbstractBucket[_AsyncMode]]": ...

    @abstractmethod
    def get(self, item: RateItem) -> Union[AbstractBucket, Awaitable[AbstractBucket]]:
        """Get the corresponding bucket to this item"""

    def create(
        self,
        bucket_class: Type[AbstractBucket],
        *args,
        **kwargs,
    ) -> AbstractBucket:
        """Creating a bucket dynamically"""
        bucket = bucket_class(*args, **kwargs)
        self.schedule_leak(bucket)
        return bucket

    def schedule_leak(self, new_bucket: AbstractBucket) -> None:
        """Schedule all the buckets' leak, reset bucket's failing rate"""
        assert new_bucket.rates, "Bucket rates are not set"

        if not self._leaker:
            self._leaker = Leaker(self.leak_interval)

        self._leaker.register(new_bucket)
        self._leaker.start()
        self._leaker.leak_async()

    def get_buckets(self) -> List[AbstractBucket]:
        """Iterator over all buckets in the factory"""
        if not self._leaker:
            return []

        buckets = []

        if self._leaker.sync_buckets:
            for _, bucket in self._leaker.sync_buckets.items():
                buckets.append(bucket)

        if self._leaker.async_buckets:
            for _, bucket in self._leaker.async_buckets.items():
                buckets.append(bucket)

        return buckets

    def dispose(self, bucket: Union[int, AbstractBucket]) -> bool:
        """Delete a bucket from the factory"""
        if isinstance(bucket, AbstractBucket):
            bucket = id(bucket)

        assert isinstance(bucket, int), "not valid bucket id"

        if not self._leaker:
            return False

        return self._leaker.deregister(bucket)

    def __del__(self):
        # Make sure all leakers are deregistered
        for bucket in self.get_buckets():
            try:
                self.dispose(bucket)
            except Exception as e:
                logger.debug("Exception %s (%s) deleting bucket %r", type(e).__name__, e, bucket)

    def close(self) -> None:
        try:
            if self._leaker is not None:
                self._leaker.close()
                self._leaker = None
        except Exception as e:
            logger.info("Exception %s (%s) deleting bucket %r", type(e).__name__, e, self._leaker)

        for bucket in self.get_buckets():
            try:
                logger.debug("Closing bucket %s", bucket)
                bucket.close()
            except Exception as e:
                logger.info("Exception %s (%s) deleting bucket %r", type(e).__name__, e, bucket)
