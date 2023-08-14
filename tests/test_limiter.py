from inspect import isawaitable
from time import sleep
from time import time
from typing import Tuple
from typing import Union

import pytest

from .conftest import logger
from pyrate_limiter import AbstractBucket
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


@pytest.fixture(params=[None, 500])
def limiter_delay(request):
    return request.param


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
async def test_limiter_01(clock, create_bucket, limiter_should_raise, limiter_delay):
    bucket = await create_bucket(DEFAULT_RATES)
    factory = DummyBucketFactory(clock, bucket)
    limiter = Limiter(
        factory,
        raise_when_fail=limiter_should_raise,
        allowed_delay=limiter_delay,
    )

    item = "hello"

    async def async_acquire(weight: int = 1) -> Tuple[bool, int]:
        nonlocal item
        start = time()
        acquire = limiter.try_acquire(item, weight=weight)

        if isawaitable(acquire):
            acquire = await acquire

        delay_time_in_ms = int((time() - start) * 1000)
        return acquire, delay_time_in_ms

    logger.info("If weight = 0, it just passes thru")
    acquire_ok, cost = await async_acquire(weight=0)
    assert acquire_ok
    assert cost == 0
    count = bucket.count()

    if isawaitable(count):
        count = await count

    assert count == 0

    logger.info("----------- Limiter Test #1: allowed_delay=500ms")
    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert cost <= 20
    assert acquire_ok
    sleep(0.3)

    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert cost <= 20
    assert acquire_ok
    sleep(0.3)

    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert cost <= 20
    assert acquire_ok

    if not limiter_should_raise:
        logger.info("Test#1: If delay allowed, it should be OK: limiter does not raise")
        acquire_ok, cost = await async_acquire()
        logger.info("cost = %s", cost)
        if limiter_delay is None:
            logger.info("Test#1: No delay allowed, return False immediately")
            assert cost <= 20
            assert not acquire_ok
        else:
            logger.info("Test#1: Delay allowed up to 500ms, return True after delay")
            assert 500 > cost > 400
            assert acquire_ok
    else:
        logger.info("Test#1: If delay allowed, it should be OK, otherwise raise")
        if limiter_delay is None:
            logger.info("Test#1: No delay, limiter should raise")
            with pytest.raises(BucketFullException):
                acquire_ok, cost = await async_acquire()
        else:
            logger.info("Test#1: Delay allowed, return True, no raise")
            acquire_ok, cost = await async_acquire()
            assert cost > 400
            assert acquire_ok

    # # Flush before testing again
    flushing = factory.bucket.flush()

    if isawaitable(flushing):
        await flushing

    assert factory.bucket.failing_rate is None

    logger.info("----------- Limiter Test #2: delay > allowed_delay")
    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert acquire_ok
    assert cost <= 20

    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert acquire_ok
    assert cost <= 20

    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert acquire_ok
    assert cost <= 20

    if limiter_should_raise:
        logger.info("Test#2: Limiter shall raise")
        if limiter_delay is not None:
            logger.info("Test#2: Limiter shall raise: delay too long")
            with pytest.raises(LimiterDelayException) as err:
                await async_acquire()
                assert err.meta_info["allowed_delay"] == 500
                assert err.meta_info["actual_delay"] > 600
                assert err.meta_info["name"] == item
        else:
            logger.info("Test#2: Limiter shall raise: no delay")
            with pytest.raises(BucketFullException) as err:
                await async_acquire()
    else:
        logger.info("Test#2: Limiter doesnt raise, return False imediately")
        acquire_ok, cost = await async_acquire()
        logger.info("cost = %s", cost)
        assert cost <= 20
        assert not acquire_ok

    # Flush before testing again
    flushing = factory.bucket.flush()

    if isawaitable(flushing):
        await flushing

    assert factory.bucket.failing_rate is None
    logger.info("----------- Limiter Test #3: exceeding weight")
    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert acquire_ok
    assert cost <= 20

    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert acquire_ok
    assert cost <= 20

    acquire_ok, cost = await async_acquire()
    logger.info("cost = %s", cost)
    assert acquire_ok
    assert cost <= 20

    if limiter_should_raise:
        logger.info("Test#3: Exceeding weight, limit should raise")
        with pytest.raises(BucketFullException) as err:
            await async_acquire(5)
    else:
        logger.info("Test#3: Exceeding weight, no raise but return False immediately")
        acquire_ok, cost = await async_acquire(5)
        logger.info("cost = %s", cost)
        assert cost <= 20
        assert not acquire_ok


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
