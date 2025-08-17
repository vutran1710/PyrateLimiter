"""Complete Limiter test suite
"""
from inspect import isawaitable

import pytest
from .conftest import wrap_bucket

from .conftest import DEFAULT_RATES
from .conftest import logger
from .demo_bucket_factory import DemoAsyncGetBucketFactory
from .demo_bucket_factory import DemoBucketFactory
from .helpers import async_acquire
from .helpers import concurrent_acquire, concurrent_acquire_async
from .helpers import inspect_bucket_items
from .helpers import prefilling_bucket
from pyrate_limiter import AsyncAbstractBucket
from pyrate_limiter import BucketFactory
from pyrate_limiter import Duration
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import SingleBucketFactory


@pytest.mark.asyncio
async def test_limiter_constructor_01():
    limiter = Limiter(DEFAULT_RATES[0])
    assert isinstance(limiter.bucket_factory, BucketFactory)
    assert isinstance(limiter.bucket_factory.bucket, InMemoryBucket)
    assert limiter.bucket_factory.bucket.rates == [DEFAULT_RATES[0]]

    limiter = Limiter(DEFAULT_RATES)
    assert isinstance(limiter.bucket_factory, BucketFactory)
    assert isinstance(limiter.bucket_factory.bucket, InMemoryBucket)
    assert limiter.bucket_factory.bucket.rates == DEFAULT_RATES

    assert len(limiter.buckets()) == 1


@pytest.mark.asyncio
async def test_limiter_constructor_02(
    create_bucket,
):
    bucket = await create_bucket(DEFAULT_RATES)

    limiter = Limiter(bucket)
    assert isinstance(limiter.bucket_factory, SingleBucketFactory)

    limiter = Limiter(
        bucket
    )

    assert isinstance(limiter.bucket_factory, BucketFactory)

    if isinstance(bucket, AsyncAbstractBucket):
        with pytest.raises(RuntimeError):
            acquire_ok = limiter.try_acquire("example")
        acquire_ok = await limiter.try_acquire_async("example")

    else:
        acquire_ok = limiter.try_acquire("example")

    assert acquire_ok

    factory = DemoBucketFactory(demo=bucket)
    limiter = Limiter(
        factory,

    )
    assert limiter.bucket_factory is factory


@pytest.mark.asyncio
async def test_limiter_01(
    request,
    create_bucket,
):
    if request.node.get_closest_marker("mpbucket"):
        pytest.skip("Skipped mpbucket test due to erratic performance timing compared to more deterministic buckets")

    bucket = await create_bucket(DEFAULT_RATES)

    factory = DemoBucketFactory(demo=bucket)
    limiter = Limiter(
        factory,
        buffer_ms=10
    )
    bucket = wrap_bucket(bucket)

    item = "demo"

    logger.info("If weight = 0, it just passes thru")
    acquire_ok, cost = await async_acquire(limiter, item, weight=0)
    assert acquire_ok
    assert cost <= 10
    assert await bucket.count() == 0

    logger.info("Limiter Test #1")
    await prefilling_bucket(limiter, 0.1, item)

    acquired, cost = await async_acquire(limiter, item, blocking=False)
    assert not acquired, f"{await bucket.count()=}, {acquired=}"

    acquired, cost = await async_acquire(limiter, item, weight=0, blocking=False)
    assert acquired


    acquired, cost = await async_acquire(limiter, item, blocking=False)

    assert not acquired



@pytest.mark.asyncio
async def test_limiter_async_factory_get_weight0(
):
    factory = DemoAsyncGetBucketFactory()
    limiter = Limiter(
        factory,

        buffer_ms=5
    )
    item = "demo"

    logger.info("If weight = 0, it just passes thru")
    acquire_ok, cost = await async_acquire(limiter, item, blocking=True, weight=0)
    assert acquire_ok
    assert cost <= 10


    await prefilling_bucket(limiter, 0.3, item)

    # Not blocking blocking, if weight is 0 then it's nearly instant 
    acquire_ok, cost = await async_acquire(limiter, item, blocking=True, weight=0)
    assert acquire_ok
    assert cost <= 10


    # Even if blocking, if weight is 0 then it's nearly instant 
    acquire_ok, cost = await async_acquire(limiter, item, blocking=True, weight=0)
    assert acquire_ok
    assert cost <= 10

@pytest.mark.asyncio
async def test_limiter_async_factory_get(
):
    factory = DemoAsyncGetBucketFactory()
    limiter = Limiter(
        factory,
        buffer_ms=5
    )
    item = "demo"


    await prefilling_bucket(limiter, 0.3, item)

    # A non-blocking request should return immediately and fail
    acquire_ok, cost = await async_acquire(limiter, item, blocking=False)
    assert not acquire_ok 
    assert cost <= 50

    
    # A blocking request should wait about 600+ ms
    acquire_ok, cost = await async_acquire(limiter, item, blocking=True)
    assert acquire_ok 
    assert 300 <= cost <= 900

    # Same as above
    acquire_ok, cost = await async_acquire(limiter, item)
    assert acquire_ok 
    assert 300 <= cost <= 900


    # # Flush before testing again
    await factory.flush()
    logger.info("Limiter Test #2")
    await prefilling_bucket(limiter, 0, item)

    # A non-blocking request should return immediately and fail
    acquire_ok, cost = await async_acquire(limiter, item, blocking=False)
    assert not acquire_ok 
    assert cost <= 50

    # A blocking request should wait about 600+ ms
    acquire_ok, cost = await async_acquire(limiter, item, blocking=True)
    assert acquire_ok 
    assert 300 <= cost <= 1200



@pytest.mark.asyncio
async def test_limiter_concurrency(
    create_bucket,
):
    bucket = await create_bucket(DEFAULT_RATES)
    factory = DemoBucketFactory(demo=bucket)
    limiter = Limiter(
        factory,
    )

    logger.info("Test Limiter Concurrency: inserting 4 items")
    items = ["demo" for _ in range(4)]
    
    if isinstance(bucket, AsyncAbstractBucket):
        with pytest.raises(RuntimeError):
            result = await concurrent_acquire(limiter, items)
    else:
        result = await concurrent_acquire(limiter, items)

        item_names = await inspect_bucket_items(bucket, 3)

        result = await concurrent_acquire(limiter, items)
        item_names = await inspect_bucket_items(bucket, 3)
        logger.info(
            "(No raise, delay is None or delay > max_delay) Result = %s, Item = %s",
            result,
            item_names,
        )
    
@pytest.mark.asyncio
async def test_limiter_concurrency_async(create_bucket):
    bucket = await create_bucket(DEFAULT_RATES)
    limiter = Limiter(DemoBucketFactory(demo=bucket))
    
    items = ["demo"] * 4

    # use async variant
    result = await concurrent_acquire_async(limiter, items)
    item_names = await inspect_bucket_items(bucket, 3)

    result = await concurrent_acquire_async(limiter, items)
    item_names = await inspect_bucket_items(bucket, 3)
    logger.info("Result=%s, Items=%s", result, item_names)


@pytest.mark.asyncio
async def test_limiter_concurrency_async_wrap(create_bucket):
    bucket = await create_bucket(DEFAULT_RATES)
    limiter = Limiter(DemoBucketFactory(demo=bucket))
    bucket = wrap_bucket(bucket)
    items = ["demo"] * 4

    # use async variant
    result = await concurrent_acquire_async(limiter, items)
    item_names = await inspect_bucket_items(bucket, 3)

    result = await concurrent_acquire_async(limiter, items)
    item_names = await inspect_bucket_items(bucket, 3)
    logger.info("Result=%s, Items=%s", result, item_names)

@pytest.mark.asyncio
async def test_limiter_decorator(
    create_bucket,
):
    bucket = await create_bucket(DEFAULT_RATES)
    factory = DemoBucketFactory(demo=bucket)
    limiter = Limiter(
        factory,
        
    )
    limiter_wrapper = limiter.as_decorator(name="demo", weight=1)

    counter = 0


    @limiter_wrapper
    async def async_inc_counter(num: int):
        nonlocal counter
        counter += num

    if isinstance(bucket, AsyncAbstractBucket):
        with pytest.raises(RuntimeError):
            @limiter_wrapper
            def inc_counter(num: int):
                nonlocal counter
                counter += num
            inc = inc_counter(1)

    else:
        @limiter_wrapper
        def inc_counter(num: int):
            nonlocal counter
            counter += num
        inc = inc_counter(1)
        if isawaitable(inc):
            await inc

        assert counter == 1

        await async_inc_counter(1)
        assert counter == 2


def test_wait_too_long():

    requests_per_second = 10

    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = InMemoryBucket([rate])
    limiter = Limiter(bucket)

    for i in range(500):
        success = limiter.try_acquire("mytest", weight=1, blocking=False)
        if not success:
            break

    assert not success  # retried and then failed
