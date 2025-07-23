"""
Testing buckets of all implementations
"""
import asyncio
from inspect import isawaitable
from time import time

import pytest

from .conftest import ClockSet
from .conftest import logger
from pyrate_limiter import AbstractClock
from pyrate_limiter import BucketAsyncWrapper
from pyrate_limiter import Rate
from pyrate_limiter import RateItem
from pyrate_limiter import TimeClock


async def get_now(clock: AbstractClock) -> int:
    """Util function to get time now"""
    now = clock.now()

    if isawaitable(now):
        now = await now

    assert isinstance(now, int)
    return now


@pytest.mark.asyncio
async def test_bucket_01(clock: ClockSet, create_bucket):
    rates = [Rate(20, 1000)]
    bucket = BucketAsyncWrapper(await create_bucket(rates))
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

    await asyncio.sleep(2)
    assert await bucket.put(RateItem("my-item", await get_now(clock))) is True

    await asyncio.sleep(2)
    assert await bucket.put(RateItem("my-item", await get_now(clock), weight=30)) is False


@pytest.mark.asyncio
async def test_bucket_02(clock: ClockSet, create_bucket):
    rates = [Rate(30, 1000), Rate(50, 2000)]
    bucket = BucketAsyncWrapper(await create_bucket(rates))
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
    bucket = BucketAsyncWrapper(await create_bucket(rates))

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
async def test_bucket_waiting(clock: ClockSet, create_bucket):
    rates = [Rate(3, 500)]
    bucket = await create_bucket(rates)

    logger.info("Testing `bucket.waiting` with Bucket: %s, \nclock=%s", bucket, clock)

    bucket = BucketAsyncWrapper(bucket)

    async def create_item(weight: int = 1) -> RateItem:
        now = clock.now()

        if isawaitable(now):
            now = await now

        assert isinstance(now, int)
        return RateItem("item", now, weight)

    start = await get_now(clock)
    assert start > 0

    assert await bucket.waiting(await create_item()) == 0

    for _ in range(3):
        assert await bucket.put(await create_item()) is True
        # NOTE: sleep 100ms between each item
        await asyncio.sleep(0.1)

    end = await get_now(clock)
    assert end > 0

    elapsed = end - start
    assert elapsed > 0

    logger.info("Elapsed: %s", elapsed)
    assert await bucket.put(await create_item()) is False

    availability = await bucket.waiting(await create_item())  # type: ignore
    assert isinstance(availability, int)
    logger.info("1 space available in: %s", availability)

    await asyncio.sleep(availability / 1000 - 0.03)
    assert await bucket.put(await create_item()) is False
    await asyncio.sleep(0.04)
    assert await bucket.put(await create_item()) is True

    assert await bucket.put(await create_item(2)) is False
    availability = await bucket.waiting(await create_item(2))  # type: ignore
    assert isinstance(availability, int)
    logger.info("2 space available in: %s", availability)

    await asyncio.sleep(availability / 1000 - 0.03)
    assert await bucket.put(await create_item(2)) is False
    await asyncio.sleep(0.04)
    assert await bucket.put(await create_item(2)) is True

    assert await bucket.put(await create_item(3)) is False
    availability = await bucket.waiting(await create_item(3))  # type: ignore
    assert isinstance(availability, int)
    logger.info("3 space available in: %s", availability)

    await asyncio.sleep(availability / 1000 - 0.03)
    assert await bucket.put(await create_item(3)) is False
    await asyncio.sleep(0.04)
    assert await bucket.put(await create_item(3)) is True


@pytest.mark.asyncio
async def test_bucket_leak(clock: ClockSet, create_bucket):
    rates = [Rate(100, 3000)]
    bucket = BucketAsyncWrapper(await create_bucket(rates))

    while await bucket.count() < 200:
        await bucket.put(RateItem("item", await get_now(clock)))

    await bucket.leak(await get_now(clock))
    assert await bucket.count() == 100
    assert await bucket.leak(await get_now(clock)) == 0
    assert await bucket.count() == 100

    await asyncio.sleep(3.01)
    assert await bucket.leak(await get_now(clock)) == 100
    assert await bucket.leak(await get_now(clock)) == 0
    assert await bucket.count() == 0


@pytest.mark.asyncio
async def test_bucket_flush(create_bucket):
    """Testing bucket's flush, only need 1 single clock type"""
    rates = [Rate(50, 1000)]
    bucket = BucketAsyncWrapper(await create_bucket(rates))
    assert isinstance(bucket.rates[0], Rate)
    clock = TimeClock()

    while await bucket.put(RateItem("item", clock.now())):
        pass

    assert await bucket.count() == 50
    assert bucket.failing_rate is not None
    await bucket.flush()
    assert await bucket.count() == 0
    assert bucket.failing_rate is None


@pytest.mark.asyncio
async def test_bucket_performance(create_bucket):
    """Bucket's performance test
    Putting a very large number of item into bucket
    Only need to test with a single clock type
    """
    clock = TimeClock()
    rates = [Rate(30000, 50000)]
    bucket = BucketAsyncWrapper(await create_bucket(rates))
    before = time()

    for _ in range(10_000):
        item = RateItem("item", clock.now())
        assert await bucket.put(item) is True

    after = time()
    elapsed = after - before
    assert await bucket.count() == 10_000
    logger.info("Bucket: %s \nPerformance test: insert 10k items %s(secs)", bucket.bucket, elapsed)
