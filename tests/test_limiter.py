"""Complete Limiter test suite
"""
from inspect import isawaitable

import pytest

from .conftest import DEFAULT_RATES
from .conftest import logger
from .demo_bucket_factory import DemoBucketFactory
from .helpers import async_acquire
from .helpers import concurrent_acquire
from .helpers import flushing_bucket
from .helpers import inspect_bucket_items
from .helpers import prefilling_bucket
from pyrate_limiter import AbstractBucket
from pyrate_limiter import BucketAsyncWrapper
from pyrate_limiter import BucketFactory
from pyrate_limiter import BucketFullException
from pyrate_limiter import Duration
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import Limiter
from pyrate_limiter import LimiterDelayException
from pyrate_limiter import SingleBucketFactory
from pyrate_limiter import TimeClock


@pytest.mark.asyncio
async def test_limiter_constructor_01(clock):
    limiter = Limiter(DEFAULT_RATES[0], clock=clock)
    assert isinstance(limiter.bucket_factory, BucketFactory)
    assert isinstance(limiter.bucket_factory.bucket, InMemoryBucket)
    assert limiter.bucket_factory.bucket.rates == [DEFAULT_RATES[0]]
    assert limiter.bucket_factory.clock == clock

    limiter = Limiter(DEFAULT_RATES, clock=clock)
    assert isinstance(limiter.bucket_factory, BucketFactory)
    assert isinstance(limiter.bucket_factory.bucket, InMemoryBucket)
    assert limiter.bucket_factory.bucket.rates == DEFAULT_RATES
    assert limiter.bucket_factory.clock == clock


@pytest.mark.asyncio
async def test_limiter_constructor_02(
    create_bucket,
    limiter_should_raise,
    limiter_delay,
):
    bucket = await create_bucket(DEFAULT_RATES)

    limiter = Limiter(bucket)
    assert isinstance(limiter.bucket_factory, SingleBucketFactory)
    assert isinstance(limiter.bucket_factory.clock, TimeClock)
    assert limiter.max_delay is None
    assert limiter.raise_when_fail is True

    limiter = Limiter(
        bucket,
        clock=TimeClock(),
        raise_when_fail=limiter_should_raise,
        max_delay=limiter_delay,
    )

    assert isinstance(limiter.bucket_factory, BucketFactory)
    assert limiter.raise_when_fail == limiter_should_raise
    assert limiter.max_delay == limiter_delay

    acquire_ok = limiter.try_acquire("example")

    if isawaitable(acquire_ok):
        acquire_ok = await acquire_ok

    assert acquire_ok

    factory = DemoBucketFactory(TimeClock(), demo=bucket)
    limiter = Limiter(
        factory,
        raise_when_fail=limiter_should_raise,
        max_delay=limiter_delay,
    )
    assert limiter.bucket_factory is factory
    assert limiter.raise_when_fail == limiter_should_raise
    assert limiter.max_delay == limiter_delay


@pytest.mark.asyncio
async def test_limiter_01(
    create_bucket,
    limiter_should_raise,
    limiter_delay,
):
    bucket = await create_bucket(DEFAULT_RATES)
    factory = DemoBucketFactory(TimeClock(), demo=bucket)
    limiter = Limiter(
        factory,
        raise_when_fail=limiter_should_raise,
        max_delay=limiter_delay,
    )
    bucket = BucketAsyncWrapper(bucket)
    item = "demo"

    logger.info("If weight = 0, it just passes thru")
    acquire_ok, cost = await async_acquire(limiter, item, weight=0)
    assert acquire_ok
    assert cost <= 10
    assert await bucket.count() == 0

    logger.info("Limiter Test #1")
    await prefilling_bucket(limiter, 0.3, item)

    if not limiter_should_raise:
        acquire_ok, cost = await async_acquire(limiter, item)
        if limiter_delay is None:
            assert cost <= 50
            assert not acquire_ok
        else:
            assert acquire_ok
    else:
        if limiter_delay is None:
            with pytest.raises(BucketFullException):
                acquire_ok, cost = await async_acquire(limiter, item)
        else:
            acquire_ok, cost = await async_acquire(limiter, item)
            assert cost > 400
            assert acquire_ok

    # # Flush before testing again
    await flushing_bucket(bucket)
    logger.info("Limiter Test #2")
    await prefilling_bucket(limiter, 0, item)

    if limiter_should_raise:
        if limiter_delay == 500:
            with pytest.raises(LimiterDelayException) as err:
                await async_acquire(limiter, item)
                assert err.meta_info["max_delay"] == 500
                assert err.meta_info["actual_delay"] > 600
                assert err.meta_info["name"] == item
        elif limiter_delay == 2000:
            acquire_ok, cost = await async_acquire(limiter, item)
            assert acquire_ok
        elif limiter_delay == Duration.MINUTE:
            acquire_ok, cost = await async_acquire(limiter, item)
            assert acquire_ok
        else:
            with pytest.raises(BucketFullException) as err:
                await async_acquire(limiter, item)
    else:
        acquire_ok, cost = await async_acquire(limiter, item)
        if limiter_delay == 500 or limiter_delay is None:
            assert not acquire_ok
        else:
            assert acquire_ok

    # Flush before testing again
    await flushing_bucket(bucket)
    logger.info("Limiter Test #3: exceeding weight")
    await prefilling_bucket(limiter, 0, item)

    if limiter_should_raise:
        with pytest.raises(BucketFullException) as err:
            await async_acquire(limiter, item, 5)
    else:
        acquire_ok, cost = await async_acquire(limiter, item, 5)
        assert cost <= 50
        assert not acquire_ok


@pytest.mark.asyncio
async def test_limiter_concurrency(
    create_bucket,
    limiter_should_raise,
    limiter_delay,
):
    bucket: AbstractBucket = await create_bucket(DEFAULT_RATES)
    factory = DemoBucketFactory(TimeClock(), demo=bucket)
    limiter = Limiter(
        factory,
        raise_when_fail=limiter_should_raise,
        max_delay=limiter_delay,
    )

    logger.info("Test Limiter Concurrency: inserting 4 items")
    items = ["demo" for _ in range(4)]

    if not limiter_should_raise:
        if not limiter_delay or limiter_delay == 500:
            result = await concurrent_acquire(limiter, items)
            item_names = await inspect_bucket_items(bucket, 3)
            logger.info(
                "(No raise, delay is None or delay > max_delay) Result = %s, Item = %s",
                result,
                item_names,
            )
        else:
            result = await concurrent_acquire(limiter, items)
            item_names = await inspect_bucket_items(bucket, 3)
            logger.info(
                "(No raise, delay < max_delay) Result = %s, Item = %s",
                result,
                item_names,
            )
    else:
        if not limiter_delay:
            with pytest.raises(BucketFullException):
                await concurrent_acquire(limiter, items)
        elif limiter_delay == 500:
            with pytest.raises(LimiterDelayException):
                await concurrent_acquire(limiter, items)
        else:
            result = await concurrent_acquire(limiter, items)
            item_names = await inspect_bucket_items(bucket, 4)
            logger.info("(Raise, delay) Result = %s, Item = %s", result, item_names)


@pytest.mark.asyncio
async def test_limiter_decorator(
    create_bucket,
    limiter_should_raise,
    limiter_delay,
):
    bucket = await create_bucket(DEFAULT_RATES)
    factory = DemoBucketFactory(TimeClock(), demo=bucket)
    limiter = Limiter(
        factory,
        raise_when_fail=limiter_should_raise,
        max_delay=limiter_delay,
    )
    limiter_wrapper = limiter.as_decorator()

    def mapping(_: int):
        return "demo", 1

    counter = 0

    @limiter_wrapper(mapping)
    def inc_counter(num: int):
        nonlocal counter
        counter += num

    @limiter_wrapper(mapping)
    async def async_inc_counter(num: int):
        nonlocal counter
        counter += num

    inc = inc_counter(1)

    if isawaitable(inc):
        await inc

    assert counter == 1

    await async_inc_counter(1)
    assert counter == 2
