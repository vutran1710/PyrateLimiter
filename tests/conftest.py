"""Pytest config
"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from inspect import isawaitable
from logging import basicConfig
from logging import getLogger
from os import getenv
from pathlib import Path
from tempfile import gettempdir
from time import sleep
from time import time
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

import pytest
from psycopg2.pool import ThreadedConnectionPool

from pyrate_limiter import AbstractBucket
from pyrate_limiter import AbstractClock
from pyrate_limiter import BucketFactory
from pyrate_limiter import Duration
from pyrate_limiter import id_generator
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import Limiter
from pyrate_limiter import MonotonicClock
from pyrate_limiter import PostgresBucket
from pyrate_limiter import PostgresClock
from pyrate_limiter import Rate
from pyrate_limiter import RateItem
from pyrate_limiter import RedisBucket
from pyrate_limiter import SQLiteBucket
from pyrate_limiter import SQLiteClock
from pyrate_limiter import SQLiteQueries as Queries
from pyrate_limiter import TimeAsyncClock
from pyrate_limiter import TimeClock
from pyrate_limiter import validate_rate_list


# Make log messages visible on test failure (or with pytest -s)
basicConfig(level="INFO")
# Uncomment for more verbose output:
logger = getLogger("pyrate_limiter")
logger.setLevel(getenv("LOG_LEVEL", "INFO"))

pg_pool = ThreadedConnectionPool(5, 100, 'postgresql://postgres:postgres@localhost:5432')

clocks = [
    MonotonicClock(),
    TimeClock(),
    SQLiteClock.default(),
    TimeAsyncClock(),
    PostgresClock(pg_pool)
]

ClockSet = Union[
    MonotonicClock,
    TimeClock,
    SQLiteClock,
    TimeAsyncClock,
    PostgresClock
]


@pytest.fixture(params=clocks)
def clock(request):
    """Parametrization for different clock."""
    return request.param


async def create_in_memory_bucket(rates: List[Rate]):
    return InMemoryBucket(rates)


async def create_redis_bucket(rates: List[Rate]):
    from redis import ConnectionPool
    from redis import Redis

    pool = ConnectionPool.from_url(getenv("REDIS", "redis://localhost:6379"))
    redis_db = Redis(connection_pool=pool)
    bucket_key = f"test-bucket/{id_generator()}"
    redis_db.delete(bucket_key)
    bucket = RedisBucket.init(rates, redis_db, bucket_key)
    assert bucket.count() == 0
    return bucket


async def create_async_redis_bucket(rates: List[Rate]):
    from redis.asyncio import ConnectionPool as AsyncConnectionPool
    from redis.asyncio import Redis as AsyncRedis

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
    logger.info("SQLite db path: %s", default_db_path)
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


async def create_postgres_bucket(rates: List[Rate]):
    global pg_pool

    table = f"test_bucket_{id_generator()}"
    bucket = PostgresBucket(pg_pool, table, rates)
    assert bucket.count() == 0
    return bucket


@pytest.fixture(
    params=[
        create_in_memory_bucket,
        create_redis_bucket,
        create_sqlite_bucket,
        create_async_redis_bucket,
        create_postgres_bucket,
    ]
)
def create_bucket(request):
    """Parametrization for different bucket."""
    return request.param


DEFAULT_RATES = [Rate(3, 1000), Rate(4, 1500)]
validate_rate_list(DEFAULT_RATES)


class DemoBucketFactory(BucketFactory):
    """Multi-bucket factory used for testing schedule-leaks"""

    buckets: Optional[Dict[str, AbstractBucket]] = None
    clock: AbstractClock
    auto_leak: bool

    def __init__(self, bucket_clock: AbstractClock, auto_leak=False, **buckets: AbstractBucket):
        self.auto_leak = auto_leak
        self.clock = bucket_clock
        self.buckets = {}
        self.leak_interval = 300

        for item_name_pattern, bucket in buckets.items():
            assert isinstance(bucket, AbstractBucket)
            self.schedule_leak(bucket, bucket_clock)
            self.buckets[item_name_pattern] = bucket

    def wrap_item(self, name: str, weight: int = 1):
        now = self.clock.now()

        async def wrap_async():
            return RateItem(name, await now, weight=weight)

        def wrap_sync():
            return RateItem(name, now, weight=weight)

        return wrap_async() if isawaitable(now) else wrap_sync()

    def get(self, item: RateItem) -> AbstractBucket:
        assert self.buckets is not None

        if item.name in self.buckets:
            bucket = self.buckets[item.name]
            assert isinstance(bucket, AbstractBucket)
            return bucket

        bucket = self.create(self.clock, InMemoryBucket, DEFAULT_RATES)
        self.buckets[item.name] = bucket
        return bucket

    def schedule_leak(self, *args):
        if self.auto_leak:
            super().schedule_leak(*args)


@pytest.fixture(params=[True, False])
def limiter_should_raise(request):
    return request.param


@pytest.fixture(params=[None, 500, Duration.SECOND * 2, Duration.MINUTE])
def limiter_delay(request):
    return request.param


async def inspect_bucket_items(bucket: AbstractBucket, expected_item_count: int):
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


async def async_count(bucket: AbstractBucket) -> int:
    count = bucket.count()

    if isawaitable(count):
        count = await count

    assert isinstance(count, int)
    return count


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


async def flushing_bucket(bucket: AbstractBucket):
    flush = bucket.flush()

    if isawaitable(flush):
        await flush
