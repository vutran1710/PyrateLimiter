from inspect import iscoroutine
from typing import Optional
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
    def get(self, item: RateItem) -> Optional[Union[DummySyncBucket, DummyAsyncBucket]]:
        if item.name == "sync":
            return DummySyncBucket()

        if item.name == "async":
            return DummyAsyncBucket()

        return None

    def schedule_leak(self):
        pass

    def schedule_flush(self):
        pass


clocks = [DummySyncClock(), DummyAsyncClock()]


@pytest.fixture(params=clocks)
def clock(request):
    """Parametrization for different time functions."""
    return request.param


@pytest.mark.asyncio
async def test_limiter_01(clock):
    factory = DummyBucketFactory()
    limiter = Limiter(factory, clock)
    item = limiter.wrap_item("hello", 1)

    if isinstance(clock, DummySyncClock):
        assert isinstance(item, RateItem)

    if isinstance(clock, DummyAsyncClock):
        assert isinstance(await item, RateItem)


@pytest.mark.asyncio
async def test_limiter_02(clock):
    factory = DummyBucketFactory()
    limiter = Limiter(factory, clock)

    item = limiter.wrap_item("sync", 1)

    if isinstance(clock, DummyAsyncClock):
        item = await item

    assert isinstance(factory.get(item), DummySyncBucket)

    item = limiter.wrap_item("async", 1)

    if isinstance(clock, DummyAsyncClock):
        item = await item

    assert isinstance(factory.get(item), DummyAsyncBucket)

    with pytest.raises(BucketRetrievalFail):
        try_acquire = limiter.try_acquire("unknown", 1)

        if iscoroutine(try_acquire):
            await try_acquire

    try_acquire = limiter.try_acquire("sync")

    if iscoroutine(try_acquire):
        try_acquire = await try_acquire

    assert try_acquire is None

    assert iscoroutine(limiter.try_acquire("async"))
    assert (await limiter.try_acquire("async")) is None

    with pytest.raises(BucketFullException):
        try_acquire = limiter.try_acquire("sync", 2)

        if iscoroutine(try_acquire):
            await try_acquire

    with pytest.raises(BucketFullException):
        await limiter.try_acquire("async", 2)
