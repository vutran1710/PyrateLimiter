"""Complete Limiter test suite
"""
import asyncio
from inspect import isawaitable
from time import sleep

import pytest

from .conftest import DEFAULT_RATES
from .conftest import logger
from .demo_bucket_factory import DemoBucketFactory
from .helpers import async_count
from pyrate_limiter import AbstractBucket
from pyrate_limiter import RateItem


@pytest.mark.asyncio
async def test_factory_01(clock, create_bucket):
    factory = DemoBucketFactory(
        clock,
        hello=await create_bucket(DEFAULT_RATES),
    )

    item = factory.wrap_item("hello", 1)

    if isawaitable(item):
        item = await item

    assert isinstance(item, RateItem)
    assert item.weight == 1

    bucket = factory.get(item)

    assert isinstance(bucket, AbstractBucket)


@pytest.mark.asyncio
async def test_factory_leak(clock, create_bucket):
    bucket1 = await create_bucket(DEFAULT_RATES)
    bucket2 = await create_bucket(DEFAULT_RATES)
    assert id(bucket1) != id(bucket2)

    factory = DemoBucketFactory(clock, auto_leak=True, b1=bucket1, b2=bucket2)
    assert len(factory.buckets) == 2
    logger.info("Factory initiated with %s buckets", len(factory.buckets))

    for item_name in ["b1", "b2", "a1"]:
        for _ in range(3):
            is_async = False
            item = factory.wrap_item(item_name)

            if isawaitable(item):
                is_async = True
                item = await item

            bucket = factory.get(item)
            put_ok = bucket.put(item)

            if isawaitable(put_ok):
                is_async = True
                put_ok = await put_ok

            assert put_ok
            sleep(0.1)

        if item_name == "b1":
            assert await async_count(bucket1) == 3

        if item_name == "b2":
            assert await async_count(bucket2) == 3

        if item_name == "a1":
            assert await async_count(factory.buckets[item_name]) == 3

        if is_async:
            await asyncio.sleep(6)
        else:
            sleep(6)

        assert await async_count(bucket1) == 0
        assert await async_count(bucket2) == 0
        assert await async_count(factory.buckets[item_name]) == 0

    assert len(factory.buckets) == 3

    for bucket in factory.get_buckets():
        factory.dispose(bucket)

    sleep(1)
    assert factory._leaker.is_alive() is False
    assert factory._leaker.aio_leak_task is None
