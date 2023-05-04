from inspect import iscoroutine
from inspect import iscoroutinefunction
from typing import Optional
from typing import Union

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

    def wrap_item(self, item_name: str, weight: int) -> RateItem:
        if self.clock is None:
            return RateItem(item_name, 0, weight=weight)

        async def wrap_async():
            timestamp = await self.clock.now()
            return RateItem(item_name, timestamp, weight=weight)

        def wrap_sycn():
            timestamp = self.clock.now()
            return RateItem(item_name, timestamp, weight=weight)

        return wrap_async() if iscoroutinefunction(self.clock.now) else wrap_sycn()

    def try_acquire(self, identity: str, weight: int = 1) -> None:
        assert weight >= 0

        if weight == 0:
            return

        item = self.wrap_item(identity, weight)

        if iscoroutine(item):

            async def acquire_async():
                bucket = self.bucket_factory.get(await item)
                acquire = bucket.put(item)

                if iscoroutine(acquire):
                    acquire = await acquire

                if acquire is False:
                    assert bucket.failing_rate is not None
                    raise BucketFullException(identity, bucket.failing_rate, -1)

            return acquire_async()

        bucket = self.bucket_factory.get(item)

        if iscoroutinefunction(bucket.put):

            async def acquire_async():
                acquire = await bucket.put(item)
                if acquire is False:
                    assert bucket.failing_rate is not None
                    raise BucketFullException(identity, bucket.failing_rate, -1)

            return acquire_async()

        if bucket.put(item) is False:
            assert bucket.failing_rate is not None
            raise BucketFullException(identity, bucket.failing_rate, -1)
