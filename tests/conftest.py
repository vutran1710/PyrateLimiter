"""Pytest config
"""
import sqlite3
from logging import basicConfig
from logging import getLogger
from os import getenv
from pathlib import Path
from tempfile import gettempdir
from typing import List
from typing import Union

import pytest

from pyrate_limiter import id_generator
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import MonotonicClock
from pyrate_limiter import Rate
from pyrate_limiter import RedisBucket
from pyrate_limiter import SQLiteBucket
from pyrate_limiter import SQLiteClock
from pyrate_limiter import SQLiteQueries as Queries
from pyrate_limiter import TimeAsyncClock
from pyrate_limiter import TimeClock


# Make log messages visible on test failure (or with pytest -s)
basicConfig(level="INFO")
# Uncomment for more verbose output:
logger = getLogger("pyrate_limiter")
logger.setLevel(getenv("LOG_LEVEL", "INFO"))

clocks = [
    MonotonicClock(),
    TimeClock(),
    SQLiteClock.default(),
    TimeAsyncClock(),
]

ClockSet = Union[
    MonotonicClock,
    TimeClock,
    SQLiteClock,
    TimeAsyncClock,
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


@pytest.fixture(
    params=[
        create_in_memory_bucket,
        create_redis_bucket,
        create_async_redis_bucket,
        create_sqlite_bucket,
    ]
)
def create_bucket(request):
    """Parametrization for different bucket."""
    return request.param
