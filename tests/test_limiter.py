"""Complete Limiter test suite
"""
from concurrent.futures import ThreadPoolExecutor
from inspect import isawaitable
from time import sleep
from time import time
from typing import List
from typing import Tuple
from typing import Union

import pytest

from .conftest import logger
from pyrate_limiter import AbstractBucket
from pyrate_limiter import BucketAsyncWrapper
from pyrate_limiter import BucketFactory
from pyrate_limiter import Clock
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import RateItem
from pyrate_limiter.exceptions import BucketFullException
from pyrate_limiter.exceptions import LimiterDelayException
from pyrate_limiter.utils import validate_rate_list


DEFAULT_RATES = [Rate(3, 1000), Rate(4, 1500)]
validate_rate_list(DEFAULT_RATES)


class DummyBucketFactory(BucketFactory):
    def __init__(self, bucket_clock: Clock, bucket: AbstractBucket):
        self.clock = bucket_clock
        self.bucket = bucket

    def wrap_item(self, name: str, weight: int = 1):
        now = self.clock.now()

        async def wrap_async():
            return RateItem(name, await now, weight=weight)

        def wrap_sycn():
            return RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sycn()

    def get(self, item: RateItem) -> Union[AbstractBucket]:
        return self.bucket


@pytest.fixture(params=[True, False])
def limiter_should_raise(request):
    return request.param


@pytest.fixture(params=[None, 500, 2000])
def limiter_delay(request):
    return request.param


async def inspect_bucket_items(bucket: Union[AbstractBucket], expected_item_count: int):
    """Inspect items in the bucket
    - Assert number of item == expected-item-count
    - Assert that items are ordered by timestamps, from latest to earliest
    """
    collected_items = []

    for idx in range(expected_item_count):
        item = bucket.peek(idx)

        if isawaitable(item):
            item = await item

        assert isinstance(item, RateItem)
        collected_items.append(item)

    item_names = [item.name for item in collected_items]

    for i in range(1, expected_item_count):
        item = collected_items[i]
        prev_item = collected_items[i - 1]
        assert item.timestamp <= prev_item.timestamp

    return item_names


async def concurrent_acquire(limiter: Limiter, items: List[str]):
    with ThreadPoolExecutor() as executor:
        result = list(executor.map(limiter.try_acquire, items))
        for idx, coro in enumerate(result):
            while isawaitable(coro):
                coro = await coro
                result[idx] = coro

        return result


async def async_acquire(limiter: Limiter, item: str, weight: int = 1) -> Tuple[bool, int]:
    start = time()
    acquire = limiter.try_acquire(item, weight=weight)

    if isawaitable(acquire):
        acquire = await acquire

    time_cost_in_ms = int((time() - start) * 1000)
    assert isinstance(acquire, bool)
    return acquire, time_cost_in_ms


async def prefilling_bucket(limiter: Limiter, sleep_interval: float, item: str):
    """Pre-filling bucket to the limit before testing
    the time cost might vary depending on the bucket's backend
    - For in-memory bucket, this should be less than a 1ms
    - For external bucket's source ie Redis, this mostly depends on the network latency
    """
    acquire_ok, cost = await async_acquire(limiter, item)
    logger.info("cost = %s", cost)
    assert cost <= 50
    assert acquire_ok
    sleep(sleep_interval)

    acquire_ok, cost = await async_acquire(limiter, item)
    logger.info("cost = %s", cost)
    assert cost <= 50
    assert acquire_ok
    sleep(sleep_interval)

    acquire_ok, cost = await async_acquire(limiter, item)
    logger.info("cost = %s", cost)
    assert cost <= 50
    assert acquire_ok


async def flushing_bucket(bucket: Union[AbstractBucket]):
    flush = bucket.flush()

    if isawaitable(flush):
        await flush


@pytest.mark.asyncio
async def test_factory_01(clock, create_bucket):
    factory = DummyBucketFactory(
        clock,
        await create_bucket(DEFAULT_RATES),
    )

    item = factory.wrap_item("hello", 1)

    if isawaitable(item):
        item = await item

    assert isinstance(item, RateItem)
    assert item.weight == 1

    bucket = factory.get(item)

    assert isinstance(bucket, AbstractBucket)


@pytest.mark.asyncio
async def test_limiter_01(
    clock,
    create_bucket,
    limiter_should_raise,
    limiter_delay,
):
    bucket = await create_bucket(DEFAULT_RATES)
    factory = DummyBucketFactory(clock, bucket)
    bucket = BucketAsyncWrapper(bucket)
    limiter = Limiter(
        factory,
        raise_when_fail=limiter_should_raise,
        allowed_delay=limiter_delay,
    )

    item = "hello"

    logger.info("If weight = 0, it just passes thru")
    acquire_ok, cost = await async_acquire(limiter, item, weight=0)
    assert acquire_ok
    assert cost == 0
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
                assert err.meta_info["allowed_delay"] == 500
                assert err.meta_info["actual_delay"] > 600
                assert err.meta_info["name"] == item
        elif limiter_delay == 2000:
            acquire_ok, cost = await async_acquire(limiter, item)
            assert acquire_ok
        else:
            with pytest.raises(BucketFullException) as err:
                await async_acquire(limiter, item)
    else:
        acquire_ok, cost = await async_acquire(limiter, item)
        assert acquire_ok if limiter_delay == 2000 else not acquire_ok

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
    clock,
    create_bucket,
    limiter_should_raise,
    limiter_delay,
):
    bucket: AbstractBucket = await create_bucket(DEFAULT_RATES)
    factory = DummyBucketFactory(clock, bucket)
    limiter = Limiter(
        factory,
        raise_when_fail=limiter_should_raise,
        allowed_delay=limiter_delay,
    )

    logger.info("Test Limiter Concurrency: inserting 4 items")
    items = [f"item:{i}" for i in range(4)]

    if not limiter_should_raise:
        if not limiter_delay or limiter_delay == 500:
            result = await concurrent_acquire(limiter, items)
            item_names = await inspect_bucket_items(bucket, 3)
            logger.info(
                "(No raise, delay is None or delay > allowed_delay) Result = %s, Item = %s",
                result,
                item_names,
            )
        else:
            result = await concurrent_acquire(limiter, items)
            item_names = await inspect_bucket_items(bucket, 3)
            logger.info(
                "(No raise, delay < allowed_delay) Result = %s, Item = %s",
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
    clock,
    create_bucket,
    limiter_should_raise,
    limiter_delay,
):
    bucket = await create_bucket(DEFAULT_RATES)
    factory = DummyBucketFactory(clock, bucket)
    limiter = Limiter(
        factory,
        raise_when_fail=limiter_should_raise,
        allowed_delay=limiter_delay,
    )
    limiter_wrapper = limiter.as_decorator()

    def mapping(_: int):
        return "hello", 1

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
