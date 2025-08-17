"""Limiter class implementation"""

import asyncio
import logging
from contextlib import contextmanager
from functools import wraps
from inspect import isawaitable, iscoroutinefunction
from threading import RLock, local
from time import sleep
from typing import Any, Awaitable, Callable, Iterable, List, Tuple, TypeVar, Union

from .abstracts import AsyncAbstractBucket, BaseAbstractBucket, BucketFactory, Rate, RateItem, SyncAbstractBucket
from .buckets import InMemoryBucket

T = TypeVar("T")

logger = logging.getLogger("pyrate_limiter")

ItemMapping = Callable[[Any], Tuple[str, int]]
DecoratorWrapper = Callable[[Callable[[Any], Any]], Callable[[Any], Any]]


class SingleBucketFactory(BucketFactory):
    """Single-bucket factory for quick use with Limiter"""

    bucket: AsyncAbstractBucket | SyncAbstractBucket

    def __init__(self, bucket: AsyncAbstractBucket | SyncAbstractBucket):
        self.bucket = bucket
        self.schedule_leak(bucket)

    def wrap_item(self, name: str, weight: int = 1):
        now = self.bucket.now()

        async def wrap_async():
            return RateItem(name, await now, weight=weight)

        def wrap_sync():
            return RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sync()

    def get(self, _: RateItem) -> AsyncAbstractBucket | SyncAbstractBucket:
        return self.bucket


@contextmanager
def combined_lock(locks: Iterable | RLock, blocking: bool, timeout: int | float = -1):
    if not isinstance(locks, Iterable):
        acquired_ok = locks.acquire(blocking=blocking, timeout=timeout)
        if not acquired_ok:
            raise TimeoutError("acquire failed")
        try:
            yield
        finally:
            locks.release()

    else:
        acquired_locks = []
        try:
            for lock in locks:
                if not blocking:
                    ok = lock.acquire(False)
                elif timeout == -1:
                    ok = lock.acquire()
                else:
                    ok = lock.acquire(timeout=timeout)

                if not ok:
                    raise TimeoutError("Timeout while acquiring combined lock.")
                acquired_locks.append(lock)
            yield
        finally:
            for lock in reversed(acquired_locks):
                lock.release()


class Limiter:
    """This class responsibility is to sum up all underlying logic
    and make working with async/sync functions easily
    """

    bucket_factory: BucketFactory
    lock: Union[RLock, Iterable]
    buffer_ms: int

    # async_lock is thread local, created on first use
    _thread_local: local

    def __init__(
        self,
        argument: Union[BucketFactory, SyncAbstractBucket, AsyncAbstractBucket, Rate, List[Rate]],
        buffer_ms: int = 50,
    ):
        """Init Limiter using either a single bucket / multiple-bucket factory
        / single rate / rate list.

        Parameters:
            argument (Union[BucketFactory, AbstractBucket, Rate, List[Rate]]): The bucket or rate configuration.
        """

        self.buffer_ms = buffer_ms
        self.bucket_factory = self._init_bucket_factory(argument)
        self.lock = RLock()
        self._thread_local = local()

        if isinstance(argument, BaseAbstractBucket):
            limiter_lock = argument.limiter_lock()
            if limiter_lock is not None:
                self.lock = (limiter_lock, self.lock)

    def buckets(self) -> List[SyncAbstractBucket | AsyncAbstractBucket]:
        """Get list of active buckets"""
        return self.bucket_factory.get_buckets()

    def dispose(self, bucket: Union[int, SyncAbstractBucket | AsyncAbstractBucket]) -> bool:
        """Dispose/Remove a specific bucket,
        using bucket-id or bucket object as param
        """
        return self.bucket_factory.dispose(bucket)

    def _init_bucket_factory(
        self,
        argument: Union[BucketFactory, SyncAbstractBucket, AsyncAbstractBucket, Rate, List[Rate]],
    ) -> BucketFactory:
        if isinstance(argument, Rate):
            argument = [argument]

        if isinstance(argument, list):
            assert len(argument) > 0, "Rates must not be empty"
            assert isinstance(argument[0], Rate), "Not valid rates list"
            rates = argument
            logger.info("Initializing default bucket(InMemoryBucket) with rates: %s", rates)
            argument = InMemoryBucket(rates)

        if isinstance(argument, BaseAbstractBucket):
            argument = SingleBucketFactory(argument)

        assert isinstance(argument, BucketFactory), "Not a valid bucket/bucket-factory"

        return argument

    def _get_async_lock(self):
        """Returns thread_local, loop-specific lock"""
        loop = asyncio.get_running_loop()
        try:
            # The async loop *can* change in a given thread
            lock = self._thread_local.async_lock
            if self._thread_local.async_lock_loop is loop:
                return lock
        except AttributeError:
            pass
        lock = asyncio.Lock()
        self._thread_local.async_lock = lock
        self._thread_local.async_lock_loop = loop
        return lock

    async def _handle_async_result(self, result: T | Awaitable[T]) -> T:
        """Helper to resolve awaitables"""
        while isawaitable(result):
            result = await result  # type: ignore[union-attr]
        return result

    async def _handle_bucket_put_async(self, bucket: SyncAbstractBucket | AsyncAbstractBucket, item: RateItem, blocking: bool) -> bool:
        """
        Attempt to insert an item into an asynchronous bucket, retrying with delays when needed.

        Parameters
        ----------
        bucket : AsyncAbstractBucket
            The async bucket to acquire from.
        item : RateItem
            The rate-limited item to insert.
        blocking : bool
            If True, keep retrying until the item can be inserted; if False,
            return immediately when acquisition fails.

        Returns
        -------
        bool
            True if the item was successfully inserted into the bucket,
            False if acquisition failed in non-blocking mode.
        """
        acquire = bucket.put(item) if isinstance(bucket, SyncAbstractBucket) else await bucket.put(item)
        if acquire is True:
            return True
        elif not blocking:
            return False
        else:
            while acquire is False:
                delay: int = (
                    bucket.waiting(item) if isinstance(bucket, SyncAbstractBucket) else await bucket.waiting(item)
                )  # mypy: ignore[assignment]

                delay += self.buffer_ms
                await asyncio.sleep(delay / 1000)
                item.timestamp += delay
                acquire = bucket.put(item) if isinstance(bucket, SyncAbstractBucket) else await bucket.put(item)

            return True

    def _handle_bucket_put_sync(self, bucket: SyncAbstractBucket, item: RateItem, blocking: bool) -> bool:
        """
        Attempt to insert an item into a synchronous bucket, retrying if necessary.

        Parameters
        ----------
        bucket : SyncAbstractBucket
            The target bucket to acquire from.
        item : RateItem
            The rate-limited item to insert.
        blocking : bool
            If True, block and retry until the item can be inserted;
            if False, return immediately if acquisition fails.

        Returns
        -------
        bool
            True if the item was successfully inserted into the bucket,
            False if acquisition failed in non-blocking mode.
        """
        acquire = bucket.put(item)
        if acquire is True:
            return True
        elif not blocking:
            return False
        else:
            while acquire is False:
                delay = bucket.waiting(item)

                delay += self.buffer_ms
                sleep(delay / 1000)
                item.timestamp += delay
                acquire = bucket.put(item)
            return True

    def try_acquire(self, name: str = __name__, weight: int = 1, timeout: int = -1, blocking: bool = True) -> Union[bool, Awaitable[bool]]:
        try:
            if weight <= 0:
                return True

            if timeout != -1:
                raise NotImplementedError("timeout not implemented for sync try_acquire yet")

            with combined_lock(self.lock, blocking=blocking):
                item = self.bucket_factory.wrap_item(name, weight)

                if isawaitable(item):
                    raise RuntimeError("Use try_acquire_async() with async buckets")

                assert isinstance(item, RateItem), "Use try_acquire_async with async buckets"
                bucket = self.bucket_factory.get(item)

                if not isinstance(bucket, SyncAbstractBucket):
                    raise RuntimeError("Use try_acquire_async() with async buckets")

                result = self._handle_bucket_put_sync(bucket, item, blocking=blocking)

                return result
        except TimeoutError:
            logger.debug("Acquisition TimeoutError")
            return False

    async def try_acquire_async(self, name: str = __name__, weight: int = 1, blocking: bool = True, timeout: int = -1) -> bool:
        """
        async version of try_acquire. This uses a top level, thread-local async lock to ensure that the async loop doesn't block.

        It is possible for the event loop to get blocked due to cross-process or cross-thread contention.

        """

        if weight <= 0:
            return True

        if not blocking and timeout != -1:
            raise RuntimeError("Can't set timeout with non-blocking")

        if timeout == -1:
            return await self._try_acquire_async_inner(name, weight, blocking=blocking)
        try:
            return await asyncio.wait_for(self._try_acquire_async_inner(name, weight, blocking=blocking), timeout=timeout)
        except asyncio.TimeoutError:
            return False

    async def _try_acquire_async_inner(self, name: str, weight: int, blocking: bool) -> bool:
        """Try acquiring an item with name & weight
        Return true on success, false on failure
        """
        lock = self._get_async_lock()
        async with lock:
            with combined_lock(self.lock, blocking=blocking):
                item = await self._handle_async_result(self.bucket_factory.wrap_item(name, weight))
                bucket: AsyncAbstractBucket | SyncAbstractBucket = await self._handle_async_result(self.bucket_factory.get(item))

                return await self._handle_bucket_put_async(bucket, item, blocking=blocking)

    def as_decorator(self, *, name="ratelimiter", weight=1):
        def deco(func: Callable[..., Any]) -> Callable[..., Any]:
            if iscoroutinefunction(func):

                @wraps(func)
                async def wrapper(*args, **kwargs):
                    r = await self.try_acquire_async(name=name, weight=weight)
                    while isawaitable(r):
                        r = await r
                    return await func(*args, **kwargs)

                return wrapper
            else:

                @wraps(func)
                def wrapper(*args, **kwargs):
                    r = self.try_acquire(name=name, weight=weight)
                    if isawaitable(r):
                        raise RuntimeError("Can't use async bucket with sync decorator")
                    return func(*args, **kwargs)

                return wrapper

        return deco

    def close(self) -> None:
        self.bucket_factory.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
