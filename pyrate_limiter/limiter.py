from inspect import iscoroutine
from inspect import iscoroutinefunction
from typing import Coroutine
from typing import Union

from .abstracts import AbstractAsyncBucket
from .abstracts import AbstractBucket
from .abstracts import BucketFactory
from .abstracts import RateItem
from .exceptions import BucketFullException
from .exceptions import BucketRetrievalFail


class Limiter:
    bucket_factory: BucketFactory

    def __init__(self, bucket_factory: BucketFactory):
        self.bucket_factory = bucket_factory
        bucket_factory.schedule_leak()
        bucket_factory.schedule_flush()

    def handle_bucket_put(
        self,
        bucket: Union[AbstractBucket, AbstractAsyncBucket],
        item: RateItem,
    ) -> Union[None, Coroutine[None, None, None]]:
        def check_acquire(is_success: bool):
            if not is_success:
                assert bucket.failing_rate is not None
                raise BucketFullException(item.name, bucket.failing_rate)

        async def put_async():
            check_acquire(await bucket.put(item))

        def put_sync():
            check_acquire(bucket.put(item))

        return put_async() if iscoroutinefunction(bucket.put) else put_sync()

    def try_acquire(self, name: str, weight: int = 1) -> Union[None, Coroutine[None, None, None]]:
        assert weight >= 0

        if weight == 0:
            # NOTE: if item is weightless, just let it go through
            # NOTE: this might change in the futre
            return None

        item = self.bucket_factory.wrap_item(name, weight)

        if iscoroutine(item):

            async def acquire_async():
                nonlocal item
                item = await item
                bucket = self.bucket_factory.get(item)

                if bucket is None:
                    raise BucketRetrievalFail(item.name)

                result = self.handle_bucket_put(bucket, item)
                return (await result) if iscoroutine(result) else result

            return acquire_async()

        assert type(item) == RateItem
        bucket = self.bucket_factory.get(item)

        if not bucket:
            raise BucketRetrievalFail(item.name)

        return self.handle_bucket_put(bucket, item)
