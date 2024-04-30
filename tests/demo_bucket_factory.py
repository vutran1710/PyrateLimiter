from inspect import isawaitable
from os import getenv
from typing import Dict
from typing import Optional

from redis.asyncio import ConnectionPool as AsyncConnectionPool
from redis.asyncio import Redis as AsyncRedis

from .conftest import DEFAULT_RATES
from .helpers import flushing_bucket
from pyrate_limiter import AbstractBucket
from pyrate_limiter import AbstractClock
from pyrate_limiter import BucketFactory
from pyrate_limiter import id_generator
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import RateItem
from pyrate_limiter import RedisBucket


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


class DemoAsyncGetBucketFactory(BucketFactory):
    """Async multi-bucket factory used for testing schedule-leaks"""

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

    async def get(self, item: RateItem) -> AbstractBucket:
        assert self.buckets is not None

        if item.name in self.buckets:
            bucket = self.buckets[item.name]
            assert isinstance(bucket, AbstractBucket)
            return bucket

        pool: AsyncConnectionPool = AsyncConnectionPool.from_url(getenv("REDIS", "redis://localhost:6379"))
        redis_db: AsyncRedis = AsyncRedis(connection_pool=pool)
        key = f"test-bucket/{id_generator()}"
        await redis_db.delete(key)
        bucket = await RedisBucket.init(DEFAULT_RATES, redis_db, key)
        self.schedule_leak(bucket, self.clock)
        self.buckets.update({item.name: bucket})
        return bucket

    def schedule_leak(self, *args):
        if self.auto_leak:
            super().schedule_leak(*args)

    async def flush(self):
        for bucket in self.buckets.values():
            await flushing_bucket(bucket)
