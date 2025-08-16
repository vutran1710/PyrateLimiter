# ruff: noqa: T201
import asyncio
import time
from datetime import datetime
from typing import List

import pytest
import redis

from pyrate_limiter import Duration, Limiter, Rate, RedisBucket


async def ticker():
    for _ in range(8):
        print(f"[TICK] {datetime.now()}")
        await asyncio.sleep(0.5)


def create_redis_bucket(rates: List[Rate]):
    redis_db = redis.Redis(host="localhost")
    bucket = RedisBucket.init(rates, redis_db, "test")
    bucket.flush()
    assert bucket.count() == 0
    return bucket


async def create_async_redis_bucket(rates: List[Rate]):
    redis_db = redis.asyncio.Redis(host="localhost")
    bucket = await RedisBucket.init(rates, redis_db, "test3")
    await bucket.flush()
    assert await bucket.count() == 0
    return bucket


@pytest.mark.asyncio
async def test_redis_async():
    rates = [Rate(3, Duration.SECOND)]

    redis_bucket = await create_async_redis_bucket(rates)
    limiter = Limiter(redis_bucket, raise_when_fail=False, max_delay=Duration.DAY)

    async def task(name, weight):
        acquired = await limiter.try_acquire_async(name, weight)
        print(f"{datetime.now()} {name}: {weight}, {acquired=}")

    start = time.time()
    await asyncio.gather(ticker(), *[task(str(i), 1) for i in range(10)])
    print(f"Run 10 calls in {time.time() - start:,.2f} sec")


def test_redis_sync():
    rates = [Rate(3, Duration.SECOND)]

    def task(name, weight):
        acquired = limiter.try_acquire(name, weight)
        print(f"{datetime.now()} {name}: {weight}, {acquired=}")

    redis_bucket = create_redis_bucket(rates)
    limiter = Limiter(redis_bucket, raise_when_fail=False, max_delay=Duration.DAY)
    for i in range(10):
        task(str(i), 1)


if __name__ == "__main__":
    print("To start a redis container: \n# docker run -d --name redis-test -p 6379:6379 redis:7")

    print("Redis (non-Async) bucket")
    test_redis_sync()

    print("AsyncRedis bucket")
    asyncio.run(test_redis_async())
