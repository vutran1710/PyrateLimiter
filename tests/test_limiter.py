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

    def schedule_leak(self):
        pass

    def schedule_flush(self):
        pass


@pytest.fixture(params=[True, False])
def limiter_should_raise(request):
    return request.param


@pytest.fixture(params=[None, 500, 2000])
def limiter_delay(request):
    return request.param


async def check_items_in_bucket(bucket: Union[AbstractBucket], expected_item_count: int):
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


async def thread_pool_acquire(limiter: Limiter, items: List[str]):
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

    delay_time_in_ms = int((time() - start) * 1000)
    assert isinstance(acquire, bool)
    return acquire, delay_time_in_ms


async def pre_filling_bucket(limiter: Limiter, sleep_interval: float, item: str):
    """Prefilling bucket to the limit
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

    logger.info("----------- Limiter Test #1")
    await pre_filling_bucket(limiter, 0.3, item)

    if not limiter_should_raise:
        logger.info("Test#1: If delay allowed, it should be OK: limiter does not raise")
        acquire_ok, cost = await async_acquire(limiter, item)
        logger.info("cost = %s", cost)
        if limiter_delay is None:
            logger.info("Test#1: No delay allowed, return False immediately")
            assert cost <= 50
            assert not acquire_ok
        else:
            logger.info("Test#1: Delay allowed up to 500ms, return True after delay")
            assert acquire_ok
    else:
        logger.info("Test#1: If delay allowed, it should be OK, otherwise raise")
        if limiter_delay is None:
            logger.info("Test#1: No delay, limiter should raise")
            with pytest.raises(BucketFullException):
                acquire_ok, cost = await async_acquire(limiter, item)
        else:
            logger.info("Test#1: Delay allowed, return True, no raise")
            acquire_ok, cost = await async_acquire(limiter, item)
            assert cost > 400
            assert acquire_ok

    # # Flush before testing again
    await flushing_bucket(bucket)
    logger.info("----------- Limiter Test #2")
    await pre_filling_bucket(limiter, 0, item)

    if limiter_should_raise:
        logger.info("Test#2: Limiter shall raise")
        if limiter_delay == 500:
            logger.info("Test#2: Limiter shall raise: delay too long")
            with pytest.raises(LimiterDelayException) as err:
                await async_acquire(limiter, item)
                assert err.meta_info["allowed_delay"] == 500
                assert err.meta_info["actual_delay"] > 600
                assert err.meta_info["name"] == item
        elif limiter_delay == 2000:
            acquire_ok, cost = await async_acquire(limiter, item)
            assert acquire_ok
        else:
            logger.info("Test#2: Limiter shall raise: no delay")
            with pytest.raises(BucketFullException) as err:
                await async_acquire(limiter, item)
    else:
        acquire_ok, cost = await async_acquire(limiter, item)
        assert acquire_ok if limiter_delay == 2000 else not acquire_ok

    # Flush before testing again
    await flushing_bucket(bucket)
    logger.info("----------- Limiter Test #3: exceeding weight")
    await pre_filling_bucket(limiter, 0, item)

    if limiter_should_raise:
        logger.info("Test#3: Exceeding weight, limit should raise")
        with pytest.raises(BucketFullException) as err:
            await async_acquire(limiter, item, 5)
    else:
        logger.info("Test#3: Exceeding weight, no raise but return False immediately")
        acquire_ok, cost = await async_acquire(limiter, item, 5)
        logger.info("cost = %s", cost)
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
            result = await thread_pool_acquire(limiter, items)
            item_names = await check_items_in_bucket(bucket, 3)
            logger.info(
                "(No raise, delay is None or delay > allowed_delay) Result = %s, Item = %s",
                result,
                item_names,
            )
        else:
            result = await thread_pool_acquire(limiter, items)
            item_names = await check_items_in_bucket(bucket, 3)
            logger.info(
                "(No raise, delay < allowed_delay) Result = %s, Item = %s",
                result,
                item_names,
            )
    else:
        if not limiter_delay:
            with pytest.raises(BucketFullException):
                await thread_pool_acquire(limiter, items)
        elif limiter_delay == 500:
            with pytest.raises(LimiterDelayException):
                await thread_pool_acquire(limiter, items)
        else:
            result = await thread_pool_acquire(limiter, items)
            item_names = await check_items_in_bucket(bucket, 4)
            logger.info("(Raise, delay) Result = %s, Item = %s", result, item_names)


@pytest.mark.asyncio
async def test_limiter_decorator(clock, create_bucket, limiter_should_raise, limiter_delay):
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

    def inc_counter(num: int):
        nonlocal counter
        counter += num

    async def async_inc_counter(num: int):
        nonlocal counter
        counter += num

    wrapped_inc_1 = limiter_wrapper(mapping)(inc_counter)
    wrapped_inc_2 = limiter_wrapper(mapping)(async_inc_counter)

    inc = wrapped_inc_1(1)

    if isawaitable(inc):
        await inc

    assert counter == 1

    await wrapped_inc_2(1)
    assert counter == 2
