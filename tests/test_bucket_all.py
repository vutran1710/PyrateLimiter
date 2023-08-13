"""
Testing buckets of all implementations
"""
import logging
import sqlite3
from inspect import iscoroutine
from os import getenv
from pathlib import Path
from tempfile import gettempdir
from time import sleep
from time import time
from typing import List
from typing import Optional
from typing import Union

import pytest
from redis import ConnectionPool
from redis import Redis
from redis.asyncio import ConnectionPool as AsyncConnectionPool
from redis.asyncio import Redis as AsyncRedis

from .conftest import MockAsyncClock
from pyrate_limiter.abstracts import AbstractBucket
from pyrate_limiter.abstracts import Clock
from pyrate_limiter.abstracts import get_bucket_availability
from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import InMemoryBucket
from pyrate_limiter.buckets import RedisBucket
from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries as Queries
from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import SQLiteClock
from pyrate_limiter.clocks import TimeClock
from pyrate_limiter.utils import id_generator


ClockSet = Union[
    MonotonicClock,
    TimeClock,
    SQLiteClock,
    MockAsyncClock,
]


async def get_now(clock: Clock) -> int:
    """Util function to get time now"""
    now = clock.now()

    if iscoroutine(now):
        now = await now

    assert isinstance(now, int)
    return now


async def create_in_memory_bucket(rates: List[Rate]):
    return InMemoryBucket(rates)


async def create_redis_bucket(rates: List[Rate]):
    pool = ConnectionPool.from_url(getenv("REDIS", "redis://localhost:6379"))
    redis_db = Redis(connection_pool=pool)
    bucket_key = f"test-bucket/{id_generator()}"
    redis_db.delete(bucket_key)
    bucket = RedisBucket.init(rates, redis_db, bucket_key)
    assert bucket.count() == 0
    return bucket


async def create_async_redis_bucket(rates: List[Rate]):
    pool = AsyncConnectionPool.from_url(getenv("REDIS", "redis://localhost:6379"))
    redis_db: AsyncRedis = AsyncRedis(connection_pool=pool)
    bucket_key = f"test-bucket/{id_generator()}"
    await redis_db.delete(bucket_key)
    bucket = await RedisBucket.init(rates, redis_db, bucket_key)
    assert await bucket.count() == 0
    return bucket


async def create_sqlite_bucket(rates: List[Rate]):
    temp_dir = Path(gettempdir())
    default_db_path = temp_dir / f"pyrate_limiter_{id_generator(size=5)}.sqlite"
    logging.info("SQLite db path: %s", default_db_path)
    table_name = f"pyrate-test-bucket-{id_generator(size=10)}"
    index_name = table_name + "__timestamp_index"

    conn = sqlite3.connect(
        default_db_path,
        isolation_level="EXCLUSIVE",
        check_same_thread=False,
    )
    drop_table_query = Queries.DROP_TABLE.format(table=table_name)
    drop_index_query = Queries.DROP_INDEX.format(index=index_name)
    create_table_query = Queries.CREATE_BUCKET_TABLE.format(table=table_name)

    conn.execute(drop_table_query)
    conn.execute(drop_index_query)
    conn.execute(create_table_query)

    create_idx_query = Queries.CREATE_INDEX_ON_TIMESTAMP.format(
        index_name=index_name,
        table_name=table_name,
    )

    conn.execute(create_idx_query)

    conn.commit()
    return SQLiteBucket(rates, conn, table_name)


@pytest.fixture(
    params=[
        create_in_memory_bucket,
        create_redis_bucket,
        create_async_redis_bucket,
        create_sqlite_bucket,
    ]
)
def create_bucket(request):
    """Parametrization for different time functions."""
    return request.param


async def awating(coro_or_not):
    if iscoroutine(coro_or_not):
        return await coro_or_not

    return coro_or_not


class BucketWrapper(AbstractBucket):
    def __init__(self, bucket: Union[AbstractBucket]):
        assert isinstance(bucket, AbstractBucket)
        self.bucket = bucket

    async def put(self, item: RateItem):
        return await awating(self.bucket.put(item))

    async def count(self):
        return await awating(self.bucket.count())

    async def leak(self, current_timestamp: Optional[int] = None) -> int:
        return await awating(self.bucket.leak(current_timestamp))

    async def flush(self) -> None:
        return await awating(self.bucket.flush())

    async def peek(self, index: int) -> Optional[RateItem]:
        return await awating(self.bucket.peek(index))

    @property
    def failing_rate(self):
        return self.bucket.failing_rate

    @property
    def rates(self):
        return self.bucket.rates


@pytest.mark.asyncio
async def test_bucket_01(clock: ClockSet, create_bucket):
    rates = [Rate(20, 1000)]
    bucket = BucketWrapper(await create_bucket(rates))
    assert bucket is not None

    await bucket.put(RateItem("my-item", await get_now(clock)))
    assert await bucket.count() == 1

    await bucket.put(RateItem("my-item", await get_now(clock), weight=10))
    assert await bucket.count() == 11

    assert await bucket.put(RateItem("my-item", await get_now(clock), weight=20)) is False
    assert bucket.failing_rate == rates[0]

    assert await bucket.put(RateItem("my-item", await get_now(clock), weight=9)) is True
    assert await bucket.count() == 20

    assert await bucket.put(RateItem("my-item", await get_now(clock))) is False

    sleep(2)
    assert await bucket.put(RateItem("my-item", await get_now(clock))) is True

    sleep(2)
    assert await bucket.put(RateItem("my-item", await get_now(clock), weight=30)) is False


@pytest.mark.asyncio
async def test_bucket_02(clock: ClockSet, create_bucket):
    rates = [Rate(30, 1000), Rate(50, 2000)]
    bucket = BucketWrapper(await create_bucket(rates))
    start = time()

    while await bucket.count() < 150:
        await bucket.put(RateItem("item", await get_now(clock)))

        if await bucket.count() == 31:
            cost = time() - start
            logging.info(">30 items: %s", cost)
            assert cost > 0.99

        if await bucket.count() == 51:
            cost = time() - start
            logging.info(">50 items: %s", cost)
            assert cost > 2

        if await bucket.count() == 81:
            cost = time() - start
            logging.info(">80 items: %s", cost)
            assert cost > 3

        if await bucket.count() == 101:
            cost = time() - start
            logging.info(">100 items: %s", cost)
            assert cost > 4


@pytest.mark.asyncio
async def test_bucket_availability(clock: ClockSet, create_bucket):
    rates = [Rate(3, 500)]
    bucket = await create_bucket(rates)

    logging.info("Testing `get_bucket_availability` with Bucket: %s, \nclock=%s", bucket, clock)

    bucket = BucketWrapper(bucket)

    async def create_item(weight: int = 1) -> RateItem:
        nonlocal clock
        now = clock.now()

        if iscoroutine(now):
            now = await now

        assert isinstance(now, int)
        return RateItem("item", now, weight)

    start = await get_now(clock)
    assert start > 0

    for _ in range(3):
        assert await bucket.put(await create_item()) is True
        # NOTE: sleep 100ms between each item
        sleep(0.1)

    end = await get_now(clock)
    assert end > 0

    elapsed = end - start
    assert elapsed > 0

    logging.info("Elapsed: %s", elapsed)
    assert await bucket.put(await create_item()) is False

    availability = await get_bucket_availability(bucket, await create_item())  # type: ignore
    assert isinstance(availability, int)
    logging.info("1 space available in: %s", availability)

    sleep(availability / 1000 - 0.02)
    assert await bucket.put(await create_item()) is False
    sleep(0.03)
    assert await bucket.put(await create_item()) is True

    assert await bucket.put(await create_item(2)) is False
    availability = await get_bucket_availability(bucket, await create_item(2))  # type: ignore
    assert isinstance(availability, int)
    logging.info("2 space available in: %s", availability)

    sleep(availability / 1000 - 0.02)
    assert await bucket.put(await create_item(2)) is False
    sleep(0.03)
    assert await bucket.put(await create_item(2)) is True

    assert await bucket.put(await create_item(3)) is False
    availability = await get_bucket_availability(bucket, await create_item(3))  # type: ignore
    assert isinstance(availability, int)
    logging.info("3 space available in: %s", availability)

    sleep(availability / 1000 - 0.02)
    assert await bucket.put(await create_item(3)) is False
    sleep(0.03)
    assert await bucket.put(await create_item(3)) is True


@pytest.mark.asyncio
async def test_bucket_leak(clock: ClockSet, create_bucket):
    rates = [Rate(100, 3000)]
    bucket = BucketWrapper(await create_bucket(rates))

    while await bucket.count() < 200:
        await bucket.put(RateItem("item", await get_now(clock)))

    await bucket.leak(await get_now(clock))
    assert await bucket.count() == 100
    assert await bucket.leak(await get_now(clock)) == 0
    assert await bucket.count() == 100

    sleep(3.01)
    assert await bucket.leak(await get_now(clock)) == 100
    assert await bucket.leak(await get_now(clock)) == 0
    assert await bucket.count() == 0


@pytest.mark.asyncio
async def test_bucket_flush(clock: ClockSet, create_bucket):
    rates = [Rate(5000, 1000)]
    bucket = BucketWrapper(await create_bucket(rates))

    while await bucket.count() < 5000:
        await bucket.put(RateItem("item", await get_now(clock)))

    await bucket.flush()
    assert await bucket.count() == 0


@pytest.mark.asyncio
async def test_with_large_items(clock: ClockSet, create_bucket):
    rates = [Rate(10000, 1000), Rate(20000, 3000), Rate(30000, 5000)]
    bucket = BucketWrapper(await create_bucket(rates))

    before = time()

    for _ in range(10_000):
        item = RateItem("item", await get_now(clock))
        await bucket.put(item)

    after = time()
    elapsed = after - before
    logging.info("---------- INSERT 10K ITEMS COST: %s(secs), %s(items)", elapsed, await bucket.count())
