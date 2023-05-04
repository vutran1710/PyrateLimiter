from inspect import iscoroutine
from inspect import iscoroutinefunction
from typing import Coroutine
from typing import Optional
from typing import Union

from .abstracts import AbstractAsyncBucket
from .abstracts import AbstractBucket
from .abstracts import AsyncClock
from .abstracts import BucketFactory
from .abstracts import RateItem
from .abstracts import SyncClock
from .clocks import TimeClock
from .exceptions import BucketFullException

LimiterClockType = Optional[Union[AsyncClock, SyncClock]]


class Limiter:
    clock: LimiterClockType
    bucket_factory: BucketFactory

    def __init__(
        self,
        bucket_factory: BucketFactory,
        clock: LimiterClockType = TimeClock(),
    ):
        self.bucket_factory = bucket_factory
        self.clock = clock
        bucket_factory.schedule_leak()
        bucket_factory.schedule_flush()

    def wrap_item(self, item_name: str, weight: int) -> Union[RateItem, Coroutine[None, None, RateItem]]:
        if self.clock is None:
            return RateItem(item_name, 0, weight=weight)

        async def wrap_async():
            timestamp = await self.clock.now()
            return RateItem(item_name, timestamp, weight=weight)

        def wrap_sycn():
            timestamp = self.clock.now()
            return RateItem(item_name, timestamp, weight=weight)

        return wrap_async() if iscoroutinefunction(self.clock.now) else wrap_sycn()

    def handle_bucket_put(
        self,
        bucket: Union[AbstractBucket, AbstractAsyncBucket],
        item: RateItem,
    ) -> Union[None, Coroutine[None, None, None]]:
        def check_acquire(is_success: bool):
            if not is_success:
                assert bucket.failing_rate is not None
                raise BucketFullException(item.name, bucket.failing_rate, -1)

        async def put_async():
            check_acquire(await bucket.put(item))

        def put_sync():
            check_acquire(bucket.put(item))

        return put_async() if iscoroutinefunction(bucket.put) else put_sync()

    def try_acquire(self, identity: str, weight: int = 1) -> Union[None, Coroutine[None, None, None]]:
        assert weight >= 0

        if weight == 0:
            return None

        item = self.wrap_item(identity, weight)

        if iscoroutine(item):

            async def acquire_async():
                nonlocal item
                item = await item
                bucket = self.bucket_factory.get(await item)
                result = self.handle_bucket_put(bucket, item)
                return (await result) if iscoroutine(result) else result

            return acquire_async()

        assert type(item) == RateItem
        bucket = self.bucket_factory.get(item)
        return self.handle_bucket_put(bucket, item)
