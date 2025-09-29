"""Limiter class implementation"""

import asyncio
import logging
from contextlib import contextmanager
from functools import wraps
from inspect import isawaitable, iscoroutinefunction
from threading import RLock, local
from time import sleep
from typing import Any, Awaitable, Callable, Iterable, List, Protocol, Tuple, Union

from .abstracts import AbstractBucket, BucketFactory, Rate, RateItem
from .buckets import InMemoryBucket

logger = logging.getLogger(__name__)

ItemMapping = Callable[[Any], Tuple[str, int]]
DecoratorWrapper = Callable[[Callable[[Any], Any]], Callable[[Any], Any]]


class LockLike(Protocol):
    def acquire(self, blocking: bool = ..., timeout: Union[float, int, None] = ...) -> bool: ...
    def release(self) -> None: ...


class SingleBucketFactory(BucketFactory):
    """Single-bucket factory for quick use with Limiter"""

    bucket: AbstractBucket

    def __init__(self, bucket: AbstractBucket):
        self.bucket = bucket
        self.schedule_leak(bucket)

    def wrap_item(self, name: str, weight: int = 1):
        now = self.bucket.now()

        async def wrap_async():
            return RateItem(name, await now, weight=weight)

        def wrap_sync():
            return RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sync()

    def get(self, _: RateItem) -> AbstractBucket:
        return self.bucket


@contextmanager
def combined_lock(locks: Iterable[LockLike] | RLock, blocking: bool, timeout: int | float = -1):
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
        argument: Union[BucketFactory, AbstractBucket, Rate, List[Rate]],
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

        if isinstance(argument, AbstractBucket):
            limiter_lock = argument.limiter_lock()
            if limiter_lock is not None:
                self.lock = (limiter_lock, self.lock)

    def buckets(self) -> List[AbstractBucket]:
        """Get list of active buckets"""
        return self.bucket_factory.get_buckets()

    def dispose(self, bucket: Union[int, AbstractBucket]) -> bool:
        """Dispose/Remove a specific bucket,
        using bucket-id or bucket object as param
        """
        return self.bucket_factory.dispose(bucket)

    def _init_bucket_factory(
        self,
        argument: Union[BucketFactory, AbstractBucket, Rate, List[Rate]],
    ) -> BucketFactory:
        if isinstance(argument, Rate):
            argument = [argument]

        if isinstance(argument, list):
            assert len(argument) > 0, "Rates must not be empty"
            assert isinstance(argument[0], Rate), "Not valid rates list"
            rates = argument
            logger.info("Initializing default bucket(InMemoryBucket) with rates: %s", rates)
            argument = InMemoryBucket(rates)

        if isinstance(argument, AbstractBucket):
            argument = SingleBucketFactory(argument)

        assert isinstance(argument, BucketFactory), "Not a valid bucket/bucket-factory"

        return argument

    def _delay_waiter(self, bucket: AbstractBucket, item: RateItem, blocking: bool, _force_async: bool = False) -> Union[bool, Awaitable[bool]]:
        """On `try_acquire` failed, handle delay"""
        assert bucket.failing_rate is not None

        if not blocking:
            return False

        delay = bucket.waiting(item)

        if _force_async or isawaitable(delay):

            async def _handle_async(delay):
                while True:
                    d = await delay if isawaitable(delay) else delay
                    assert isinstance(d, int) and d >= 0
                    d += self.buffer_ms
                    await asyncio.sleep(d / 1000)
                    item.timestamp += d
                    r = bucket.put(item)
                    r = await r if isawaitable(r) else r
                    if r:
                        return True
                    delay = bucket.waiting(item)

            return _handle_async(delay)
        else:
            total_delay = 0

            while True:
                assert not isawaitable(delay)
                logger.debug("delay=%d, total_delay=%s", delay, total_delay)

                delay += self.buffer_ms
                total_delay += delay

                sleep(delay / 1000)
                item.timestamp += delay
                re_acquire = bucket.put(item)
                # NOTE: if delay is not Awaitable, then `bucket.put` is not Awaitable
                assert isinstance(re_acquire, bool)

                if re_acquire:
                    return True
                delay = bucket.waiting(item)

    def handle_bucket_put(self, bucket: AbstractBucket, item: RateItem, blocking: bool, _force_async: bool = False) -> Union[bool, Awaitable[bool]]:
        """Putting item into bucket"""

        def _handle_result(is_success: bool):
            if not is_success:
                return self._delay_waiter(bucket, item, blocking=blocking, _force_async=_force_async)

            return True

        acquire = bucket.put(item)

        if isawaitable(acquire):

            async def _put_async(acquire):
                acquire = await acquire
                result = _handle_result(acquire)

                while isawaitable(result):
                    result = await result

                return result

            return _put_async(acquire)

        return _handle_result(acquire)  # type: ignore

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

    def try_acquire(self, name: str = "pyrate", weight: int = 1, timeout: int = -1, blocking: bool = True) -> Union[bool, Awaitable[bool]]:
        """
        Attempt to acquire a permit from the limiter.

        Parameters
        ----------
        name : str, default "pyrate"
            The bucket key to acquire from.
        weight : int, default 1
            Number of permits to consume.
        timeout : int, default -1
            Maximum time (in seconds) to wait; -1 means wait indefinitely.
            ** Timeout is not yet implemented for sync path. Use try_acquire_async **
        blocking : bool, default True
            If True, block until a permit is available (subject to timeout);
            if False, return immediately.

        Returns
        -------
        bool or Awaitable[bool]
            True if the permit was acquired, False otherwise. Async limiters
            return an awaitable resolving to the same.
        """
        try:
            return self._try_acquire(name=name, weight=weight, timeout=timeout, blocking=blocking)
        except TimeoutError:
            logger.debug("Acquisition TimeoutError")
            return False

    async def _acquire_async(self, blocking, name, weight):
        return await self._handle_async_result(self._try_acquire(name, weight, blocking=blocking, _force_async=True))

    async def try_acquire_async(self, name: str = "pyrate", weight: int = 1, blocking: bool = True, timeout: int = -1) -> bool:
        """
        Attempt to asynchronously acquire a permit from the limiter.

        Parameters
        ----------
        name : str, default "pyrate"
            The bucket key to acquire from.
        weight : int, default 1
            Number of permits to consume.
        blocking : bool, default True
            If True, wait until a permit is available (subject to timeout);
            if False, return immediately.
        timeout : int, default -1
            Maximum time (in seconds) to wait; -1 means wait indefinitely.

        Returns
        -------
        bool
            True if the permit was acquired, False otherwise.

        Notes
        -----
        This is the async variant of ``try_acquire``. A top-level, thread-local
        async lock is used to prevent blocking the event loop.
        """

        if weight == 0:
            return True

        if not blocking and timeout != -1:
            raise RuntimeError("Can't set timeout with non-blocking")

        async def run():
            lock = self._get_async_lock()
            async with lock:
                return await self._acquire_async(blocking=blocking, name=name, weight=weight)

        if timeout == -1:
            return await run()
        try:
            return await asyncio.wait_for(run(), timeout=timeout)
        except asyncio.TimeoutError:
            return False

    async def _handle_async_acquire(
        self,
        item: Awaitable[RateItem],
        blocking: bool,
        _force_async: bool = False,
    ):
        this_item = await item
        bucket = self.bucket_factory.get(this_item)
        if isawaitable(bucket):
            bucket = await bucket
        assert isinstance(bucket, AbstractBucket), f"Invalid bucket: item: {this_item.name}"
        result = self.handle_bucket_put(bucket, this_item, blocking=blocking, _force_async=_force_async)

        while isawaitable(result):
            result = await result

        return result

    async def _handle_async_bucket(
        self,
        bucket: Awaitable[AbstractBucket],
        item: RateItem,
        blocking: bool,
        _force_async: bool = False,
    ):
        this_bucket = await bucket
        assert isinstance(this_bucket, AbstractBucket), f"Invalid bucket: item: {item.name}"
        result = self.handle_bucket_put(this_bucket, item, blocking=blocking, _force_async=_force_async)

        while isawaitable(result):
            result = await result

        return result

    async def _handle_async_result(self, result):
        while isawaitable(result):
            result = await result

        return result

    def _try_acquire(self, name: str, weight: int, blocking: bool, timeout: int = -1, _force_async: bool = False) -> Union[bool, Awaitable[bool]]:
        """Try acquiring an item with name & weight
        Return true on success, false on failure
        """

        if timeout != -1:
            raise NotImplementedError("timeout not implemented for sync try_acquire yet")

        with combined_lock(self.lock, blocking=blocking, timeout=timeout):
            assert weight >= 0, "item's weight must be >= 0"

            if weight == 0:
                # NOTE: if item is weightless, just let it go through
                # NOTE: this might change in the future
                return True

            item = self.bucket_factory.wrap_item(name, weight)

            if isawaitable(item):
                return self._handle_async_acquire(item, blocking=blocking)

            assert isinstance(item, RateItem)

            bucket = self.bucket_factory.get(item)
            if isawaitable(bucket):
                return self._handle_async_bucket(bucket=bucket, item=item, blocking=blocking, _force_async=_force_async)

            assert isinstance(bucket, AbstractBucket), f"Invalid bucket: item: {name}"
            result = self.handle_bucket_put(bucket, item, blocking=blocking, _force_async=_force_async)

            if isawaitable(result):
                return self._handle_async_result(result)

            return result

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
