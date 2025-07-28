"""Pytest config & fixtures"""
from logging import basicConfig
from logging import getLogger
from os import getenv
from pathlib import Path
from tempfile import gettempdir
from typing import List
from typing import Union

import pytest

from pyrate_limiter import Duration
from pyrate_limiter import id_generator
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import limiter_factory
from pyrate_limiter import MonotonicClock
from pyrate_limiter import MultiprocessBucket
from pyrate_limiter import PostgresBucket
from pyrate_limiter import Rate
from pyrate_limiter import RedisBucket
from pyrate_limiter import TimeAsyncClock
from pyrate_limiter import TimeClock


# Make log messages visible on test failure (or with pytest -s)
basicConfig(level="INFO")
# Uncomment for more verbose output:
logger = getLogger("pyrate_limiter")
logger.setLevel(getenv("LOG_LEVEL", "INFO"))

DEFAULT_RATES = [Rate(3, 1000), Rate(4, 1500)]

clocks = [
    pytest.param(MonotonicClock(), marks=pytest.mark.monotonic),
    pytest.param(TimeClock(), marks=pytest.mark.timeclock),
    pytest.param(TimeAsyncClock(), marks=pytest.mark.asyncclock),
]

ClockSet = Union[
    MonotonicClock,
    TimeClock,
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

    pool: AsyncConnectionPool = AsyncConnectionPool.from_url(
        getenv("REDIS", "redis://localhost:6379")
    )
    redis_db: AsyncRedis = AsyncRedis(connection_pool=pool)
    bucket_key = f"test-bucket/{id_generator()}"
    await redis_db.delete(bucket_key)
    bucket = await RedisBucket.init(rates, redis_db, bucket_key)
    assert await bucket.count() == 0
    return bucket


async def create_mp_bucket(rates: List[Rate]):
    bucket = MultiprocessBucket.init(rates)

    return bucket


async def create_sqlite_bucket(rates: List[Rate], file_lock: bool = False):

    temp_dir = Path(gettempdir())
    default_db_path = temp_dir / f"pyrate_limiter_{id_generator(size=5)}.sqlite"
    table_name = f"pyrate-test-bucket-{id_generator(size=10)}"

    logger.info("SQLite db path: %s", default_db_path)

    return limiter_factory.create_sqlite_bucket(rates=rates,
                                                db_path=str(default_db_path),
                                                table_name=table_name,
                                                use_file_lock=file_lock)


async def create_filelocksqlite_bucket(rates: List[Rate]):
    return await create_sqlite_bucket(rates=rates, file_lock=True)


async def create_postgres_bucket(rates: List[Rate]):
    from psycopg_pool import ConnectionPool as PgConnectionPool

    pool = PgConnectionPool("postgresql://postgres:postgres@localhost:5432")
    table = f"test_bucket_{id_generator()}"
    bucket = PostgresBucket(pool, table, rates)
    assert bucket.count() == 0
    return bucket


@pytest.fixture(
    params=[
        create_in_memory_bucket,
        create_redis_bucket,
        create_sqlite_bucket,
        create_async_redis_bucket,
        create_postgres_bucket,
        create_filelocksqlite_bucket,
        pytest.param(create_mp_bucket, marks=pytest.mark.mpbucket)
    ]
)
def create_bucket(request):
    """Parametrization for different bucket."""
    return request.param


@pytest.fixture(params=[True, False])
def limiter_should_raise(request):
    return request.param


@pytest.fixture(params=[None, 500, Duration.SECOND * 2, Duration.MINUTE])
def limiter_delay(request):
    return request.param
