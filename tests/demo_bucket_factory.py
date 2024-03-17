from inspect import isawaitable
from typing import Dict
from typing import Optional

from .conftest import DEFAULT_RATES
from pyrate_limiter import AbstractBucket
from pyrate_limiter import AbstractClock
from pyrate_limiter import BucketFactory
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import RateItem


class DemoBucketFactory(BucketFactory):
    """Multi-bucket factory used for testing schedule-leaks"""

    buckets: Optional[Dict[str, AbstractBucket]] = None
    clock: AbstractClock
    auto_leak: bool

    def __init__(self, bucket_clock: AbstractClock, auto_leak=False, **buckets: AbstractBucket):
        self.auto_leak = auto_leak
        self.clock = bucket_clock
        self.buckets = {}
        self.leak_interval = 300

        for item_name_pattern, bucket in buckets.items():
            assert isinstance(bucket, AbstractBucket)
            self.schedule_leak(bucket, bucket_clock)
            self.buckets[item_name_pattern] = bucket

    def wrap_item(self, name: str, weight: int = 1):
        now = self.clock.now()

        async def wrap_async():
            return RateItem(name, await now, weight=weight)

        def wrap_sync():
            return RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sync()

    def get(self, item: RateItem) -> AbstractBucket:
        assert self.buckets is not None

        if item.name in self.buckets:
            bucket = self.buckets[item.name]
            assert isinstance(bucket, AbstractBucket)
            return bucket

        bucket = self.create(self.clock, InMemoryBucket, DEFAULT_RATES)
        self.buckets[item.name] = bucket
        return bucket

    def schedule_leak(self, *args):
        if self.auto_leak:
            super().schedule_leak(*args)
