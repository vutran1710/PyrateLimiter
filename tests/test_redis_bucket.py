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
