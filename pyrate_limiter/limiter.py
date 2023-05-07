from inspect import iscoroutine
from inspect import iscoroutinefunction
from typing import Coroutine
from typing import Union

from .abstracts import AbstractBucket
from .abstracts import BucketFactory
from .abstracts import RateItem
from .exceptions import BucketFullException
from .exceptions import BucketRetrievalFail


class Limiter:
    bucket_factory: BucketFactory
    raise_when_fail: bool

    def __init__(self, bucket_factory: BucketFactory, raise_when_fail: bool = True):
        self.bucket_factory = bucket_factory
        bucket_factory.schedule_leak()
        bucket_factory.schedule_flush()
        self.raise_when_fail = raise_when_fail

    def handle_bucket_put(
        self,
        bucket: Union[AbstractBucket],
        item: RateItem,
    ) -> Union[bool, Coroutine[None, None, bool]]:
        def check_acquire(is_success: bool):
            if not is_success:
                assert bucket.failing_rate is not None, "No failing rate when not success, logical error"

                if self.raise_when_fail:
                    raise BucketFullException(item.name, bucket.failing_rate)

                return False

            return True

        async def put_async():
            return check_acquire(await bucket.put(item))

        def put_sync():
            return check_acquire(bucket.put(item))

        return put_async() if iscoroutinefunction(bucket.put) else put_sync()

    def try_acquire(self, name: str, weight: int = 1) -> Union[bool, Coroutine[None, None, bool]]:
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
