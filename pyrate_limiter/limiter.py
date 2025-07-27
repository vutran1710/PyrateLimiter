"""Limiter class implementation
"""
import asyncio
import logging
from contextlib import contextmanager
from functools import wraps
from inspect import isawaitable
from threading import local
from threading import RLock
from time import sleep
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Iterable
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from .abstracts import AbstractBucket
from .abstracts import AbstractClock
from .abstracts import BucketFactory
from .abstracts import Duration
from .abstracts import Rate
from .abstracts import RateItem
from .buckets import InMemoryBucket
from .clocks import TimeClock
from .exceptions import BucketFullException
from .exceptions import LimiterDelayException

logger = logging.getLogger("pyrate_limiter")

ItemMapping = Callable[[Any], Tuple[str, int]]
DecoratorWrapper = Callable[[Callable[[Any], Any]], Callable[[Any], Any]]


class SingleBucketFactory(BucketFactory):
    """Single-bucket factory for quick use with Limiter"""

    bucket: AbstractBucket
    clock: AbstractClock

    def __init__(self, bucket: AbstractBucket, clock: AbstractClock):
        self.clock = clock
        self.bucket = bucket
        self.schedule_leak(bucket, clock)

    def wrap_item(self, name: str, weight: int = 1):
        now = self.clock.now()

        async def wrap_async():
            return RateItem(name, await now, weight=weight)

        def wrap_sync():
            return RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sync()

    def get(self, _: RateItem) -> AbstractBucket:
        return self.bucket


@contextmanager
def combined_lock(locks: Iterable, timeout_sec: Optional[float] = None):
    """Acquires and releases multiple locks. Intended to be used in multiprocessing for a cross-process
    lock combined with in process thread RLocks"""
    acquired = []
    try:
        for lock in locks:
            if timeout_sec is not None:
                if not lock.acquire(timeout=timeout_sec):
                    raise TimeoutError("Timeout while acquiring combined lock.")
            else:
                lock.acquire()
            acquired.append(lock)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()


class Limiter:
    """This class responsibility is to sum up all underlying logic
    and make working with async/sync functions easily
    """

    bucket_factory: BucketFactory
    raise_when_fail: bool
    retry_until_max_delay: bool
    max_delay: Optional[int] = None
    lock: Union[RLock, Iterable]
    buffer_ms: int

    # async_lock is thread local, created on first use
    _thread_local: local

    def __init__(
        self,
        argument: Union[BucketFactory, AbstractBucket, Rate, List[Rate]],
        clock: AbstractClock = TimeClock(),
        raise_when_fail: bool = True,
        max_delay: Optional[Union[int, Duration]] = None,
        retry_until_max_delay: bool = False,
        buffer_ms: int = 50
    ):
        """Init Limiter using either a single bucket / multiple-bucket factory
        / single rate / rate list.

        Parameters:
            argument (Union[BucketFactory, AbstractBucket, Rate, List[Rate]]): The bucket or rate configuration.
            clock (AbstractClock, optional): The clock instance to use for rate limiting. Defaults to TimeClock().
            raise_when_fail (bool, optional): Whether to raise an exception when rate limiting fails. Defaults to True.
            max_delay (Optional[Union[int, Duration]], optional): The maximum delay allowed for rate limiting.
            Defaults to None.
            retry_until_max_delay (bool, optional): If True, retry operations until the maximum delay is reached.
                Useful for ensuring operations eventually succeed within the allowed delay window. Defaults to False.
        """
        self.bucket_factory = self._init_bucket_factory(argument, clock=clock)
        self.raise_when_fail = raise_when_fail
        self.retry_until_max_delay = retry_until_max_delay
        self.buffer_ms = buffer_ms
        if max_delay is not None:
            if isinstance(max_delay, Duration):
                max_delay = int(max_delay)

            assert max_delay >= 0, "Max-delay must not be negative"

        self.max_delay = max_delay
        self.lock = RLock()
        self._thread_local = local()

        if isinstance(argument, AbstractBucket):
            limiter_lock = argument.limiter_lock()
            if limiter_lock is not None:
                self.lock = (limiter_lock, self.lock)

    def buckets(self) -> List[AbstractBucket]:
        """Get list of active buckets
        """
        return self.bucket_factory.get_buckets()

    def dispose(self, bucket: Union[int, AbstractBucket]) -> bool:
        """Dispose/Remove a specific bucket,
        using bucket-id or bucket object as param
        """
        return self.bucket_factory.dispose(bucket)

    def _init_bucket_factory(
        self,
        argument: Union[BucketFactory, AbstractBucket, Rate, List[Rate]],
        clock: AbstractClock,
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
            argument = SingleBucketFactory(argument, clock)

        assert isinstance(argument, BucketFactory), "Not a valid bucket/bucket-factory"

        return argument

    def _raise_bucket_full_if_necessary(
        self,
        bucket: AbstractBucket,
        item: RateItem,
    ):
        if self.raise_when_fail:
            assert bucket.failing_rate is not None  # NOTE: silence mypy
            raise BucketFullException(item, bucket.failing_rate)

    def _raise_delay_exception_if_necessary(
        self,
        bucket: AbstractBucket,
        item: RateItem,
        delay: int,
    ):
        if self.raise_when_fail:
            assert bucket.failing_rate is not None  # NOTE: silence mypy
            assert isinstance(self.max_delay, int)
            raise LimiterDelayException(
                item,
                bucket.failing_rate,
                delay,
                self.max_delay,
            )

    def delay_or_raise(
        self,
        bucket: AbstractBucket,
        item: RateItem,
    ) -> Union[bool, Awaitable[bool]]:
        """On `try_acquire` failed, handle delay or raise error immediately"""
        assert bucket.failing_rate is not None

        if self.max_delay is None:
            self._raise_bucket_full_if_necessary(bucket, item)
            return False

        delay = bucket.waiting(item)

        def _handle_reacquire(re_acquire: bool) -> bool:
            if not re_acquire:
                logger.error("""Failed to re-acquire after the expected delay. If it failed,
                either clock or bucket is unstable.
                If asyncio, use try_acquire_async(). If multiprocessing,
                use retry_until_max_delay=True.""")
                self._raise_bucket_full_if_necessary(bucket, item)

            return re_acquire

        if isawaitable(delay):

            async def _handle_async():
                nonlocal delay
                delay = await delay
                assert isinstance(delay, int), "Delay not integer"

                total_delay = 0
                delay += self.buffer_ms

                while True:
                    total_delay += delay

                    if self.retry_until_max_delay:
                        if self.max_delay is not None and total_delay > self.max_delay:
                            logger.error("Total delay exceeded max_delay: total_delay=%s, max_delay=%s",
                                         total_delay, self.max_delay)
                            self._raise_delay_exception_if_necessary(bucket, item, total_delay)
                            return False
                    else:
                        if self.max_delay is not None and delay > self.max_delay:
                            logger.error(
                                "Required delay too large: actual=%s, expected=%s",
                                delay,
                                self.max_delay,
                            )
                            self._raise_delay_exception_if_necessary(bucket, item, delay)
                            return False

                    await asyncio.sleep(delay / 1000)
                    item.timestamp += delay
                    re_acquire = bucket.put(item)

                    if isawaitable(re_acquire):
                        re_acquire = await re_acquire

                    if not self.retry_until_max_delay:
                        return _handle_reacquire(re_acquire)
                    elif re_acquire:
                        return True

            return _handle_async()

        assert isinstance(delay, int)

        if delay < 0:
            logger.error(
                "Cannot fit item into bucket: item=%s, rate=%s, bucket=%s",
                item,
                bucket.failing_rate,
                bucket,
            )
            self._raise_bucket_full_if_necessary(bucket, item)
            return False

        total_delay = 0

        while True:
            logger.debug("delay=%d, total_delay=%s", delay, total_delay)
            delay = bucket.waiting(item)
            assert isinstance(delay, int)

            delay += self.buffer_ms
            total_delay += delay

            if self.max_delay is not None and total_delay > self.max_delay:
                logger.error(
                    "Required delay too large: actual=%s, expected=%s",
                    delay,
                    self.max_delay,
                )

                if self.retry_until_max_delay:
                    self._raise_delay_exception_if_necessary(bucket, item, total_delay)
                else:
                    self._raise_delay_exception_if_necessary(bucket, item, delay)

                return False

            sleep(delay / 1000)
            item.timestamp += delay
            re_acquire = bucket.put(item)
            # NOTE: if delay is not Awaitable, then `bucket.put` is not Awaitable
            assert isinstance(re_acquire, bool)

            if not self.retry_until_max_delay:
                return _handle_reacquire(re_acquire)
            elif re_acquire:
                return True

    def handle_bucket_put(
        self,
        bucket: AbstractBucket,
        item: RateItem,
    ) -> Union[bool, Awaitable[bool]]:
        """Putting item into bucket"""

        def _handle_result(is_success: bool):
            if not is_success:
                return self.delay_or_raise(bucket, item)

            return True

        acquire = bucket.put(item)

        if isawaitable(acquire):

            async def _put_async():
                nonlocal acquire
                acquire = await acquire
                result = _handle_result(acquire)

                while isawaitable(result):
                    result = await result

                return result

            return _put_async()

        return _handle_result(acquire)  # type: ignore

    def _get_async_lock(self):
        """Must be called before first try_acquire_async for each thread"""
        try:
            return self._thread_local.async_lock
        except AttributeError:
            lock = asyncio.Lock()
            self._thread_local.async_lock = lock
            return lock

    async def try_acquire_async(self, name: str, weight: int = 1) -> bool:
        """
            async version of try_acquire.

            This uses a top level, thread-local async lock to ensure that the async loop doesn't block

            This does not make the entire code async: use an async bucket for that.
        """
        async with self._get_async_lock():
            acquired = self.try_acquire(name=name, weight=weight)

            if isawaitable(acquired):
                return await acquired
            else:
                logger.warning("async call made without an async bucket.")
                return acquired

    def try_acquire(self, name: str, weight: int = 1) -> Union[bool, Awaitable[bool]]:
        """Try acquiring an item with name & weight
        Return true on success, false on failure
        """
        with self.lock if not isinstance(self.lock, Iterable) else combined_lock(self.lock):
            assert weight >= 0, "item's weight must be >= 0"

            if weight == 0:
                # NOTE: if item is weightless, just let it go through
                # NOTE: this might change in the future
                return True

            item = self.bucket_factory.wrap_item(name, weight)

            if isawaitable(item):

                async def _handle_async():
                    nonlocal item
                    item = await item
                    bucket = self.bucket_factory.get(item)
                    if isawaitable(bucket):
                        bucket = await bucket
                    assert isinstance(bucket, AbstractBucket), f"Invalid bucket: item: {name}"
                    result = self.handle_bucket_put(bucket, item)

                    while isawaitable(result):
                        result = await result

                    return result

                return _handle_async()

            assert isinstance(item, RateItem)  # NOTE: this is to silence mypy warning
            bucket = self.bucket_factory.get(item)
            if isawaitable(bucket):

                async def _handle_async_bucket():
                    nonlocal bucket
                    bucket = await bucket
                    assert isinstance(bucket, AbstractBucket), f"Invalid bucket: item: {name}"
                    result = self.handle_bucket_put(bucket, item)

                    while isawaitable(result):
                        result = await result

                    return result

                return _handle_async_bucket()

            assert isinstance(bucket, AbstractBucket), f"Invalid bucket: item: {name}"
            result = self.handle_bucket_put(bucket, item)

            if isawaitable(result):

                async def _handle_async_result():
                    nonlocal result
                    while isawaitable(result):
                        result = await result

                    return result

                return _handle_async_result()

            return result

    def as_decorator(self) -> Callable[[ItemMapping], DecoratorWrapper]:
        """Use limiter decorator
        Use with both sync & async function
        """
        def with_mapping_func(mapping: ItemMapping) -> DecoratorWrapper:
            def decorator_wrapper(func: Callable[[Any], Any]) -> Callable[[Any], Any]:
                """Actual function wrapper"""

                if asyncio.iscoroutinefunction(func):

                    @wraps(func)
                    async def wrapper_async(*args, **kwargs):
                        (name, weight) = mapping(*args, **kwargs)
                        assert isinstance(name, str), "Mapping name is expected but not found"
                        assert isinstance(weight, int), "Mapping weight is expected but not found"
                        accquire_ok = self.try_acquire_async(name, weight)

                        if isawaitable(accquire_ok):
                            await accquire_ok

                        return await func(*args, **kwargs)

                    return wrapper_async
                else:
                    @wraps(func)
                    def wrapper(*args, **kwargs):
                        (name, weight) = mapping(*args, **kwargs)
                        assert isinstance(name, str), "Mapping name is expected but not found"
                        assert isinstance(weight, int), "Mapping weight is expected but not found"
                        accquire_ok = self.try_acquire(name, weight)

                        if not isawaitable(accquire_ok):
                            return func(*args, **kwargs)

                        async def _handle_accquire_async():
                            nonlocal accquire_ok
                            accquire_ok = await accquire_ok

                            result = func(*args, **kwargs)

                            if isawaitable(result):
                                return await result

                            return result

                        return _handle_accquire_async()

                    return wrapper

            return decorator_wrapper

        return with_mapping_func
