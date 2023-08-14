"""
Testing buckets of all implementations
"""
from inspect import isawaitable
from time import sleep
from time import time
from typing import Optional
from typing import Union

import pytest

from .conftest import ClockSet
from .conftest import logger
from pyrate_limiter import TimeClock
from pyrate_limiter.abstracts import AbstractBucket
from pyrate_limiter.abstracts import Clock
from pyrate_limiter.abstracts import get_bucket_availability
from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem


async def get_now(clock: Clock) -> int:
    """Util function to get time now"""
    now = clock.now()

    if isawaitable(now):
        now = await now

    assert isinstance(now, int)
    return now


async def awating(coro_or_not):
    while isawaitable(coro_or_not):
        coro_or_not = await coro_or_not

    return coro_or_not


class BucketWrapper(AbstractBucket):
    def __init__(self, bucket: Union[AbstractBucket]):
        assert isinstance(bucket, AbstractBucket)
        self.bucket = bucket

    async def put(self, item: RateItem):
        return await awating(self.bucket.put(item))

    async def count(self):
        return await awating(self.bucket.count())

    async def leak(self, current_timestamp: Optional[int] = None) -> int:
        return await awating(self.bucket.leak(current_timestamp))

    async def flush(self) -> None:
        return await awating(self.bucket.flush())

    async def peek(self, index: int) -> Optional[RateItem]:
        item = self.bucket.peek(index)

        if isawaitable(item):
            item = await item

        assert item is None or isinstance(item, RateItem)
        return item

    @property
    def failing_rate(self):
        return self.bucket.failing_rate

    @property
    def rates(self):
        return self.bucket.rates


@pytest.mark.asyncio
async def test_bucket_01(clock: ClockSet, create_bucket):
    rates = [Rate(20, 1000)]
    bucket = BucketWrapper(await create_bucket(rates))
    assert bucket is not None

    peek = await bucket.peek(0)
    assert peek is None

    await bucket.put(RateItem("my-item", await get_now(clock)))
    assert await bucket.count() == 1

    await bucket.put(RateItem("my-item", await get_now(clock), weight=10))
    assert await bucket.count() == 11

    assert await bucket.put(RateItem("my-item", await get_now(clock), weight=20)) is False
    assert bucket.failing_rate == rates[0]

    assert await bucket.put(RateItem("my-item", await get_now(clock), weight=9)) is True
    assert await bucket.count() == 20

    assert await bucket.put(RateItem("my-item", await get_now(clock))) is False

    sleep(2)
    assert await bucket.put(RateItem("my-item", await get_now(clock))) is True

    sleep(2)
    assert await bucket.put(RateItem("my-item", await get_now(clock), weight=30)) is False


@pytest.mark.asyncio
async def test_bucket_02(clock: ClockSet, create_bucket):
    rates = [Rate(30, 1000), Rate(50, 2000)]
    bucket = BucketWrapper(await create_bucket(rates))
    start = time()

    while await bucket.count() < 150:
        await bucket.put(RateItem("item", await get_now(clock)))

        if await bucket.count() == 31:
            cost = time() - start
            logger.info(">30 items: %s", cost)
            assert cost > 0.99

        if await bucket.count() == 51:
            cost = time() - start
            logger.info(">50 items: %s", cost)
            assert cost > 2

        if await bucket.count() == 81:
            cost = time() - start
            logger.info(">80 items: %s", cost)
            assert cost > 3

        if await bucket.count() == 101:
            cost = time() - start
            logger.info(">100 items: %s", cost)
            assert cost > 4


@pytest.mark.asyncio
async def test_bucket_03(clock: ClockSet, create_bucket):
    rates = [Rate(30, 1000), Rate(50, 2000)]
    bucket = BucketWrapper(await create_bucket(rates))

    peek = await bucket.peek(0)
    assert peek is None

    await bucket.put(RateItem("item1", await get_now(clock)))
    peek = await bucket.peek(0)
    assert isinstance(peek, RateItem)
    assert "item1" in peek.name

    await bucket.put(RateItem("item2", await get_now(clock)))
    peek = await bucket.peek(0)
    assert isinstance(peek, RateItem)
    assert "item2" in peek.name

    peek = await bucket.peek(1)
    assert isinstance(peek, RateItem)
    assert "item1" in peek.name

    await bucket.put(RateItem("item3", await get_now(clock)))
    peek = await bucket.peek(0)
    assert isinstance(peek, RateItem)
    assert "item3" in peek.name

    peek = await bucket.peek(1)
    assert isinstance(peek, RateItem)
    assert "item2" in peek.name

    peek = await bucket.peek(2)
    assert isinstance(peek, RateItem)
    assert "item1" in peek.name

    peek = await bucket.peek(3)
    assert peek is None


@pytest.mark.asyncio
async def test_bucket_availability(clock: ClockSet, create_bucket):
    rates = [Rate(3, 500)]
    bucket = await create_bucket(rates)

    logger.info("Testing `get_bucket_availability` with Bucket: %s, \nclock=%s", bucket, clock)

    bucket = BucketWrapper(bucket)

    async def create_item(weight: int = 1) -> RateItem:
        nonlocal clock
        now = clock.now()

        if isawaitable(now):
            now = await now

        assert isinstance(now, int)
        return RateItem("item", now, weight)

    start = await get_now(clock)
    assert start > 0

    for _ in range(3):
        assert await bucket.put(await create_item()) is True
        # NOTE: sleep 100ms between each item
        sleep(0.1)

    end = await get_now(clock)
    assert end > 0

    elapsed = end - start
    assert elapsed > 0

    logger.info("Elapsed: %s", elapsed)
    assert await bucket.put(await create_item()) is False

    availability = await get_bucket_availability(bucket, await create_item())  # type: ignore
    assert isinstance(availability, int)
    logger.info("1 space available in: %s", availability)

    sleep(availability / 1000 - 0.02)
    assert await bucket.put(await create_item()) is False
    sleep(0.03)
    assert await bucket.put(await create_item()) is True

    assert await bucket.put(await create_item(2)) is False
    availability = await get_bucket_availability(bucket, await create_item(2))  # type: ignore
    assert isinstance(availability, int)
    logger.info("2 space available in: %s", availability)

    sleep(availability / 1000 - 0.02)
    assert await bucket.put(await create_item(2)) is False
    sleep(0.03)
    assert await bucket.put(await create_item(2)) is True

    assert await bucket.put(await create_item(3)) is False
    availability = await get_bucket_availability(bucket, await create_item(3))  # type: ignore
    assert isinstance(availability, int)
    logger.info("3 space available in: %s", availability)

    sleep(availability / 1000 - 0.02)
    assert await bucket.put(await create_item(3)) is False
    sleep(0.03)
    assert await bucket.put(await create_item(3)) is True


@pytest.mark.asyncio
async def test_bucket_leak(clock: ClockSet, create_bucket):
    rates = [Rate(100, 3000)]
    bucket = BucketWrapper(await create_bucket(rates))

    while await bucket.count() < 200:
        await bucket.put(RateItem("item", await get_now(clock)))

    await bucket.leak(await get_now(clock))
    assert await bucket.count() == 100
    assert await bucket.leak(await get_now(clock)) == 0
    assert await bucket.count() == 100

    sleep(3.01)
    assert await bucket.leak(await get_now(clock)) == 100
    assert await bucket.leak(await get_now(clock)) == 0
    assert await bucket.count() == 0


@pytest.mark.asyncio
async def test_bucket_flush(clock: ClockSet, create_bucket):
    rates = [Rate(5000, 1000)]
    bucket = BucketWrapper(await create_bucket(rates))

    while await bucket.count() < 5000:
        await bucket.put(RateItem("item", await get_now(clock)))

    await bucket.flush()
    assert await bucket.count() == 0


@pytest.mark.asyncio
async def test_with_large_items(clock: ClockSet, create_bucket):
    """Bucket's performance test
    Only need to test with a single clock type
    """
    if not isinstance(clock, TimeClock):
        return

    rates = [Rate(10000, 1000), Rate(20000, 3000), Rate(30000, 5000)]
    bucket = BucketWrapper(await create_bucket(rates))

    before = time()

    for _ in range(10_000):
        item = RateItem("item", await get_now(clock))
        await bucket.put(item)

    after = time()
    elapsed = after - before
    logger.info("---------- INSERT 10K ITEMS COST: %s(secs), %s(items)", elapsed, await bucket.count())
