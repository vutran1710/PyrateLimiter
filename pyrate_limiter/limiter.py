"""
Limiter class implementation
- Smart logic,
- Switching async/sync context
- Can be used as decorator
"""
import asyncio
from functools import wraps
from inspect import iscoroutine
from inspect import iscoroutinefunction
from time import sleep
from typing import Any
from typing import Callable
from typing import Coroutine
from typing import Optional
from typing import Tuple
from typing import Union

from .abstracts import AbstractBucket
from .abstracts import BucketFactory
from .abstracts import get_bucket_availability
from .abstracts import RateItem
from .exceptions import BucketFullException
from .exceptions import BucketRetrievalFail


ItemMapping = Callable[[Any], Tuple[str, int]]
DecoratorWrapper = Callable[[Callable[[Any], Any]], Callable[[Any], Any]]


class Limiter:
    """This class responsibility is to sum up all underlying logic
    and make working with async/sync functions easily
    """

    bucket_factory: BucketFactory
    raise_when_fail: bool
    delay: Optional[int]

    def __init__(self, bucket_factory: BucketFactory, raise_when_fail: bool = True, delay: Optional[int] = None):
        self.bucket_factory = bucket_factory
        bucket_factory.schedule_leak()
        bucket_factory.schedule_flush()
        self.raise_when_fail = raise_when_fail
        self.delay = delay

    def handle_bucket_put(
        self,
        bucket: Union[AbstractBucket],
        item: RateItem,
    ) -> Union[bool, Coroutine[None, None, bool]]:
        """Putting item into bucket"""

        def check_acquire(is_success: bool):
            if not is_success:
                error_msg = "No failing rate when not success, logical error"
                assert bucket.failing_rate is not None, error_msg

                if self.raise_when_fail:
                    raise BucketFullException(item.name, bucket.failing_rate)

                return False

            return True

        async def handle_delay():
            nonlocal bucket, item
            until_available = get_bucket_availability(bucket, item.timestamp, item.weight)
            async_delay = False

            if iscoroutine(until_available):
                until_available = await until_available
                async_delay = True

            if until_available > self.delay:
                return False

            if async_delay:
                await asyncio.sleep(until_available / 1000)
            else:
                sleep(until_available / 1000)

            return self.handle_bucket_put(bucket, item)

        async def put_async():
            accquire_ok = check_acquire(await bucket.put(item))

            if accquire_ok is False and self.delay:
                return handle_delay()

            return accquire_ok

        def put_sync():
            accquire_ok = check_acquire(bucket.put(item))

            if accquire_ok is False and self.delay:
                return handle_delay()

            return accquire_ok

        return put_async() if iscoroutinefunction(bucket.put) else put_sync()

    def try_acquire(self, name: str, weight: int = 1) -> Union[bool, Coroutine[None, None, bool]]:
        """Try accquiring an item with name & weight
        Return true on success, false on failure
        """
        assert weight >= 0, "item's weight must be >= 0"

        if weight == 0:
            # NOTE: if item is weightless, just let it go through
            # NOTE: this might change in the futre
            return True

        item = self.bucket_factory.wrap_item(name, weight)

        if iscoroutine(item):

            async def acquire_async():
                nonlocal item
                item = await item
                bucket = self.bucket_factory.get(item)

                if bucket is None:
                    if self.raise_when_fail:
                        raise BucketRetrievalFail(item.name)

                    return False

                result = self.handle_bucket_put(bucket, item)

                if iscoroutine(result):
                    result = await result

                return result

            return acquire_async()

        assert isinstance(item, RateItem)  # NOTE: this is to silence mypy warning
        bucket = self.bucket_factory.get(item)

        if not bucket:
            if self.raise_when_fail:
                raise BucketRetrievalFail(item.name)

            return False

        return self.handle_bucket_put(bucket, item)

    def as_decorator(self) -> Callable[[ItemMapping], DecoratorWrapper]:
        """Use limiter decorator
        Use with both sync & async function
        """

        def with_mapping_func(mapping: ItemMapping) -> DecoratorWrapper:
            def decorator_wrapper(func: Callable[[Any], Any]) -> Callable[[Any], Any]:
                """Actual function warpper"""

                @wraps(func)
                def wrapper(*args, **kwargs):
                    (name, weight) = mapping(*args, **kwargs)
                    assert isinstance(name, str), "Mapping name is expected but not found"
                    assert isinstance(weight, int), "Mapping weight is expected but not found"
                    accquire_ok = self.try_acquire(name, weight)

                    if not iscoroutine(accquire_ok):
                        return func(*args, **kwargs)

                    async def handle_accquire_is_coroutine():
                        nonlocal accquire_ok
                        accquire_ok = await accquire_ok
                        result = func(*args, **kwargs)

                        if iscoroutine(result):
                            return await result

                        return result

                    return handle_accquire_is_coroutine()

                return wrapper

            return decorator_wrapper

        return with_mapping_func
