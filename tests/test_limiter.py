from inspect import iscoroutine
from inspect import iscoroutinefunction
from typing import Union

import pytest

from pyrate_limiter import AbstractBucket
from pyrate_limiter import BucketFactory
from pyrate_limiter import Clock
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import RateItem
from pyrate_limiter.exceptions import BucketFullException


class DummySyncClock(Clock):
    def now(self):
        return 1


class DummyAsyncClock(Clock):
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

    def count(self):
        return 1

    def peek(self, index: int):
        return None


class DummyAsyncBucket(AbstractBucket):
    failing_rate = Rate(1, 100)

    async def put(self, item: RateItem):
        if item.weight == 1:
            return True

        return False

    async def leak(self):
        pass

    async def flush(self):
        pass

    async def count(self):
        return 1

    def peek(self, index: int):
        return None


class DummyBucketFactory(BucketFactory):
    def __init__(self, clock=None):
        self.clock = clock

    def wrap_item(self, name: str, weight: int = 1):
        if self.clock is None:
            return RateItem(name, 0, weight=weight)

        async def wrap_async():
            timestamp = await self.clock.now()
            return RateItem(name, timestamp, weight=weight)

        def wrap_sycn():
            timestamp = self.clock.now()
            return RateItem(name, timestamp, weight=weight)

        return wrap_async() if iscoroutinefunction(self.clock.now) else wrap_sycn()

    def get(self, item: RateItem) -> Union[DummySyncBucket, DummyAsyncBucket]:
        if item.name == "async":
            return DummyAsyncBucket()

        return DummySyncBucket()

    def schedule_leak(self):
        pass

    def schedule_flush(self):
        pass


@pytest.fixture(params=[DummySyncClock(), DummyAsyncClock(), None])
def clock(request):
    """Parametrization for different time functions."""
    return request.param


@pytest.fixture(params=[True, False])
def limiter_should_raise(request):
    return request.param


@pytest.fixture(params=["sync", "async"])
def item_name(request):
    return request.param


@pytest.mark.asyncio
async def test_factory_01(clock):
    factory = DummyBucketFactory(clock)
    item = factory.wrap_item("hello", 1)

    if isinstance(clock, DummySyncClock):
        assert isinstance(item, RateItem)

    if isinstance(clock, DummyAsyncClock):
        assert isinstance(await item, RateItem)

    item = factory.wrap_item("sync", 1)

    if isinstance(clock, DummyAsyncClock):
        item = await item

    assert isinstance(factory.get(item), DummySyncBucket)

    item = factory.wrap_item("async", 1)

    if isinstance(clock, DummyAsyncClock):
        item = await item

    assert isinstance(factory.get(item), DummyAsyncBucket)


@pytest.mark.asyncio
async def test_limiter_02(clock, limiter_should_raise, item_name):
    factory = DummyBucketFactory(clock)
    limiter = Limiter(factory, raise_when_fail=limiter_should_raise)

    try_acquire = limiter.try_acquire("dark-matter", 0)

    if iscoroutine(try_acquire):
        try_acquire = await try_acquire

    assert try_acquire is True

    if limiter_should_raise is False:
        print("----------- Expect no raise, item=", item_name)
        try_acquire = limiter.try_acquire(item_name)

        if iscoroutine(try_acquire):
            try_acquire = await try_acquire

        try_acquire = limiter.try_acquire(item_name, 2)

        while iscoroutine(try_acquire):
            try_acquire = await try_acquire

        assert try_acquire is False
        return

    with pytest.raises(BucketFullException):
        print("----- expect raise full-exception with item=", item_name)
        try_acquire = limiter.try_acquire(item_name, 2)

        if iscoroutine(try_acquire):
            await try_acquire


@pytest.mark.asyncio
async def test_limiter_decorator(clock, limiter_should_raise, item_name):
    factory = DummyBucketFactory(clock)
    limiter = Limiter(factory, raise_when_fail=limiter_should_raise)
    limiter_wrapper = limiter.as_decorator()

    if isinstance(clock, DummySyncClock) or clock is None:
        # Test with pure sync Limiter first
        def mapping_sync(_: int):
            return "sync", 1

        counter = 0

        def inc_counter(num: int):
            nonlocal counter
            counter += num

        wrapped_inc = limiter_wrapper(mapping_sync)(inc_counter)
        wrapped_inc(1)
        assert counter == 1, "Should work with synchronous functions"

        async def async_inc_counter(num: int):
            nonlocal counter
            counter += num

        wrapped_inc = limiter_wrapper(mapping_sync)(async_inc_counter)
        await wrapped_inc(1)
        assert counter == 2, "Should work with async functions"
    else:
        # From this point, Limiter is always async
        def mapping_sync(_: int):
            return "sync", 1

        def mapping_async(_: int):
            return "async", 1

        counter = 0

        def inc_counter(num: int):
            nonlocal counter
            counter += num

        wrapped_inc_1 = limiter_wrapper(mapping_sync)(inc_counter)
        wrapped_inc_2 = limiter_wrapper(mapping_async)(inc_counter)

        await wrapped_inc_1(1)
        assert counter == 1

        await wrapped_inc_2(1)
        assert counter == 2

        async def async_inc_counter(num: int):
            nonlocal counter
            counter += num

        wrapped_inc_3 = limiter_wrapper(mapping_sync)(async_inc_counter)
        wrapped_inc_4 = limiter_wrapper(mapping_async)(async_inc_counter)

        await wrapped_inc_3(1)
        assert counter == 3

        await wrapped_inc_4(1)
        assert counter == 4
