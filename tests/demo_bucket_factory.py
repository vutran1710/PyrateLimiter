from inspect import isawaitable
from os import getenv
from typing import Awaitable, Dict
from typing import Optional

from typing import Iterable
from redis.asyncio import ConnectionPool as AsyncConnectionPool
from redis.asyncio import Redis as AsyncRedis

from .conftest import DEFAULT_RATES
from .helpers import flushing_bucket
from pyrate_limiter import BaseAbstractBucket, AsyncAbstractBucket, SyncAbstractBucket
from pyrate_limiter import AbstractClock
from pyrate_limiter import BucketFactory
from pyrate_limiter import id_generator
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import RateItem
from pyrate_limiter import RedisBucket, AsyncRedisBucket


class DemoBucketFactory(BucketFactory):
    """Multi-bucket factory used for testing schedule-leaks"""

    buckets: Optional[Dict[str, SyncAbstractBucket | AsyncAbstractBucket]] = None
    auto_leak: bool

    def __init__(self, auto_leak=False, **buckets: SyncAbstractBucket | AsyncAbstractBucket):
        self.auto_leak = auto_leak
        self.buckets = {}
        self.leak_interval = 300

        for item_name_pattern, bucket in buckets.items():
            self.schedule_leak(bucket)
            self.buckets[item_name_pattern] = bucket

    def wrap_item(self, name: str, weight: int = 1):
        assert self.buckets is not None
        now = next((b for b in self.buckets.values())).now()

        async def wrap_async():
            return RateItem(name, await now, weight=weight)

        def wrap_sync():
            return RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sync()

    def get(self, item: RateItem) -> AsyncAbstractBucket | SyncAbstractBucket:
        assert self.buckets is not None

        if item.name in self.buckets:
            bucket = self.buckets[item.name]
            return bucket

        bucket = self.create(InMemoryBucket, DEFAULT_RATES)
        self.buckets[item.name] = bucket
        return bucket

    def schedule_leak(self, *args):
        if self.auto_leak:
            super().schedule_leak(*args)


class DemoAsyncGetBucketFactory(BucketFactory):
    """Async multi-bucket factory used for testing schedule-leaks"""

    buckets: dict[str, SyncAbstractBucket | AsyncAbstractBucket] 

    def __init__(self, auto_leak=False, **buckets: AsyncAbstractBucket):
        self.auto_leak = auto_leak
        self.buckets = {"test": InMemoryBucket(DEFAULT_RATES)}
        self.leak_interval = 300

        for item_name_pattern, bucket in buckets.items():
            assert isinstance(bucket, AsyncAbstractBucket)
            self.schedule_leak(bucket)
            self.buckets[item_name_pattern] = bucket

    def wrap_item(self, name: str, weight: int = 1):
        now = next((b for b in self.buckets.values())).now()

        async def wrap_async():
            return RateItem(name, await now, weight=weight)

        def wrap_sync():
            return RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sync()

    def get(self, item: RateItem) -> SyncAbstractBucket | AsyncAbstractBucket | Awaitable[SyncAbstractBucket] | Awaitable[AsyncAbstractBucket]:
        if item.name in self.buckets:
            return self.buckets[item.name]

        async def _make() -> AsyncAbstractBucket:
            pool: AsyncConnectionPool = AsyncConnectionPool.from_url(getenv("REDIS", "redis://localhost:6379"))
            redis_db = AsyncRedis(connection_pool=pool)
            key = f"test-bucket/{id_generator()}"
            await redis_db.delete(key)
            bucket = await AsyncRedisBucket.init(DEFAULT_RATES, redis_db, key)
            self.schedule_leak(bucket)
            self.buckets[item.name] = bucket
            return bucket
        
        return _make()
    

    def schedule_leak(self, *args):
        if self.auto_leak:
            super().schedule_leak(*args)

    async def flush(self):
        for bucket in self.buckets.values():
            await flushing_bucket(bucket)
