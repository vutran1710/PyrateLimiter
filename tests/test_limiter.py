from inspect import iscoroutine
from typing import Union

import pytest

from pyrate_limiter import AbstractAsyncBucket
from pyrate_limiter import AbstractBucket
from pyrate_limiter import AsyncClock
from pyrate_limiter import BucketFactory
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import RateItem
from pyrate_limiter import SyncClock
from pyrate_limiter.exceptions import BucketFullException
from pyrate_limiter.exceptions import BucketRetrievalFail


class DummySyncClock(SyncClock):
    def now(self):
        return 1


class DummyAsyncClock(AsyncClock):
    async def now(self):
        return 1


class DummySyncBucket(AbstractBucket):
    failing_rate = Rate(1, 100)

    def put(self, item: RateItem):
        if item.weight == 1:
            return True

        return False

    def leak(self):
        pass

    def flush(self):
        pass


class DummyAsyncBucket(AbstractAsyncBucket):
    failing_rate = Rate(1, 100)

    async def put(self, item: RateItem):
        if item.weight == 1:
            return True

        return False

    async def leak(self):
        pass

    async def flush(self):
        pass


class DummyBucketFactory(BucketFactory):
    def get(self, item: RateItem) -> Union[DummySyncBucket, DummyAsyncBucket]:
        if item.name == "sync":
            return DummySyncBucket()

        if item.name == "async":
            return DummyAsyncBucket()

        raise BucketRetrievalFail(item.name)

    def schedule_leak(self):
        pass

    def schedule_flush(self):
        pass


@pytest.mark.asyncio
async def test_limiter_01():
    factory = DummyBucketFactory()
    sync_clock = DummySyncClock()
    async_clock = DummyAsyncClock()

    sync_limiter = Limiter(factory, sync_clock)
    async_limiter = Limiter(factory, async_clock)

    sync_item = sync_limiter.wrap_item("hello", 1)
    async_item = await async_limiter.wrap_item("hello", 1)

    assert isinstance(sync_item, RateItem)
    assert isinstance(async_item, RateItem)

    print("---> SyncItem", sync_item)
    print("---> AsyncItem", async_item)


@pytest.mark.asyncio
async def test_limiter_02():
    factory = DummyBucketFactory()
    limiter = Limiter(factory, clock=None)

    item = limiter.wrap_item("sync", 1)
    assert isinstance(factory.get(item), DummySyncBucket)

    item = limiter.wrap_item("async", 1)
    assert isinstance(factory.get(item), DummyAsyncBucket)

    with pytest.raises(BucketRetrievalFail):
        factory.get(limiter.wrap_item("unknown-item", 1))

    assert limiter.try_acquire("sync") is None
    assert iscoroutine(limiter.try_acquire("async"))
    assert (await limiter.try_acquire("async")) is None

    with pytest.raises(BucketFullException):
        limiter.try_acquire("sync", 2)

    with pytest.raises(BucketFullException):
        await limiter.try_acquire("async", 2)
