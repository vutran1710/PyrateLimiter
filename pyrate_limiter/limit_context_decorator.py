import asyncio
from functools import wraps
from inspect import iscoroutinefunction
from logging import getLogger
from time import sleep
from typing import Union

from .exceptions import BucketFullException

logger = getLogger(__name__)


class LimitContextDecorator:
    """A class that can be used as a:
    * decorator
    * async decorator
    * contextmanager
    * async contextmanager

    Mainly used via ``Limiter.ratelimit()``. Depending on arguments, calls that exceed the rate
    limit will either raise an exception, or sleep until space is available in the bucket.

    Args:
        limiter: Limiter object
        identities: Bucket identities
        delay: Delay until the next request instead of raising an exception
        max_delay: The maximum allowed delay time (in seconds); anything over this will raise
            an exception
    """

    def __init__(
        self,
        limiter,
        *identities,
        delay: bool = False,
        max_delay: Union[int, float] = None,
    ):
        self.delay = delay
        self.max_delay = max_delay
        self.try_acquire = lambda: limiter.try_acquire(*identities)

    def __call__(self, func):
        """Allows usage as a decorator for both normal and async functions"""

        @wraps(func)
        def wrapper(*args, **kwargs):
            self.delayed_acquire()
            return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            await self.async_delayed_acquire()
            return await func(*args, **kwargs)

        # Return either an async or normal wrapper, depending on the type of the wrapped function
        return async_wrapper if iscoroutinefunction(func) else wrapper

    def __enter__(self):
        """Allows usage as a contextmanager"""
        self.delayed_acquire()

    def __exit__(self, *exc):
        pass

    async def __aenter__(self):
        """Allows usage as an async contextmanager"""
        await self.async_delayed_acquire()

    async def __aexit__(self, *exc):
        pass

    def delayed_acquire(self):
        """Delay and retry until we can successfully acquire an available bucket item"""
        while True:
            try:
                self.try_acquire()
            except BucketFullException as err:
                delay_time = self.delay_or_reraise(err)
                sleep(delay_time)
            else:
                break

    async def async_delayed_acquire(self):
        """Delay and retry until we can successfully acquire an available bucket item"""
        while True:
            try:
                self.try_acquire()
            except BucketFullException as err:
                delay_time = self.delay_or_reraise(err)
                await asyncio.sleep(delay_time)
            else:
                break

    def delay_or_reraise(self, err: BucketFullException) -> int:
        """Determine if we should delay after exceeding a rate limit. If so, return the delay time,
        otherwise re-raise the exception.
        """
        delay_time = err.meta_info["remaining_time"]
        logger.debug(err.meta_info)
        logger.info(f"Rate limit reached; {delay_time} seconds remaining before next request")
        exceeded_max_delay = bool(self.max_delay) and (delay_time > self.max_delay)
        if self.delay and not exceeded_max_delay:
            return delay_time
        raise err
