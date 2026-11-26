import pytest

from pyrate_limiter import Rate
from pyrate_limiter import RateItem

from .conftest import create_async_redis_bucket
from .conftest import create_redis_bucket

pytest.importorskip("redis")


@pytest.mark.redis
@pytest.mark.asyncio
async def test_redis_bucket_batches_large_weight():
    bucket = await create_redis_bucket([Rate(1001, 1000)])

    try:
        assert bucket.put(RateItem("item", bucket.now(), weight=1001)) is True
        assert bucket.count() == 1001
    finally:
        bucket.flush()


@pytest.mark.asyncredis
@pytest.mark.asyncio
async def test_async_redis_bucket_batches_large_weight():
    bucket = await create_async_redis_bucket([Rate(1001, 1000)])

    try:
        assert await bucket.put(RateItem("item", bucket.now(), weight=1001)) is True
        assert await bucket.count() == 1001
    finally:
        await bucket.flush()


@pytest.mark.redis
@pytest.mark.asyncio
@pytest.mark.parametrize("fixed_window", [False, True], ids=["sliding", "fixed"])
async def test_redis_leak_preserves_window_start(fixed_window):
    from pyrate_limiter import FixedWindow, SlidingWindowLog

    bucket = await create_redis_bucket([Rate(1, 1000)])
    bucket._algorithm = FixedWindow() if fixed_window else SlidingWindowLog()
    leak_time = 1500 if fixed_window else 2000
    expired_time = 2000 if fixed_window else 2001

    try:
        assert bucket.put(RateItem("item", 1000)) is True
        assert bucket.put(RateItem("item", leak_time)) is False
        assert bucket.leak(leak_time) == 0
        assert bucket.count() == 1
        assert bucket.put(RateItem("item", leak_time)) is False
        assert bucket.leak(expired_time) == 1
        assert bucket.count() == 0
        assert bucket.put(RateItem("item", expired_time)) is True
    finally:
        bucket.flush()


@pytest.mark.asyncredis
@pytest.mark.asyncio
@pytest.mark.parametrize("fixed_window", [False, True], ids=["sliding", "fixed"])
async def test_async_redis_leak_preserves_window_start(fixed_window):
    from pyrate_limiter import FixedWindow, SlidingWindowLog

    bucket = await create_async_redis_bucket([Rate(1, 1000)])
    bucket._algorithm = FixedWindow() if fixed_window else SlidingWindowLog()
    leak_time = 1500 if fixed_window else 2000
    expired_time = 2000 if fixed_window else 2001

    try:
        assert await bucket.put(RateItem("item", 1000)) is True
        assert await bucket.put(RateItem("item", leak_time)) is False
        assert await bucket.leak(leak_time) == 0
        assert await bucket.count() == 1
        assert await bucket.put(RateItem("item", leak_time)) is False
        assert await bucket.leak(expired_time) == 1
        assert await bucket.count() == 0
        assert await bucket.put(RateItem("item", expired_time)) is True
    finally:
        await bucket.flush()
