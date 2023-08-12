"""
Testing buckets of all implementations
"""
import logging
import sqlite3
from os import getenv
from pathlib import Path
from tempfile import gettempdir
from time import sleep
from time import time
from typing import List
from typing import Union

import pytest
from redis import ConnectionPool
from redis import Redis

from pyrate_limiter.abstracts import get_bucket_availability
from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import InMemoryBucket
from pyrate_limiter.buckets import RedisSyncBucket
from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries as Queries
from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import SQLiteClock
from pyrate_limiter.clocks import TimeClock
from pyrate_limiter.utils import id_generator


def create_in_memory_bucket(rates: List[Rate]):
    return InMemoryBucket(rates)


def create_redis_bucket(rates: List[Rate]):
    pool = ConnectionPool.from_url(getenv("REDIS", "redis://localhost:6379"))
    redis_db = Redis(connection_pool=pool)
    bucket_key = f"test-bucket/{id_generator()}"
    redis_db.delete(bucket_key)
    return RedisSyncBucket(rates, redis_db, bucket_key)


def create_sqlite_bucket(rates: List[Rate]):
    temp_dir = Path(gettempdir())
    default_db_path = temp_dir / "pyrate_limiter.sqlite"
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
        create_sqlite_bucket,
    ]
)
def create_bucket(request):
    """Parametrization for different time functions."""
    return request.param


def test_bucket_01(clock: Union[MonotonicClock, TimeClock, SQLiteClock], create_bucket):
    rates = [Rate(20, 1000)]
    bucket = create_bucket(rates)
    assert bucket is not None

    bucket.put(RateItem("my-item", clock.now()))
    assert bucket.count() == 1

    bucket.put(RateItem("my-item", clock.now(), weight=10))
    assert bucket.count() == 11

    assert bucket.put(RateItem("my-item", clock.now(), weight=20)) is False
    assert bucket.failing_rate == rates[0]

    assert bucket.put(RateItem("my-item", clock.now(), weight=9)) is True
    assert bucket.count() == 20

    assert bucket.put(RateItem("my-item", clock.now())) is False

    sleep(2)
    assert bucket.put(RateItem("my-item", clock.now())) is True

    sleep(2)
    assert bucket.put(RateItem("my-item", clock.now(), weight=30)) is False


def test_bucket_02(clock: Union[MonotonicClock, TimeClock, SQLiteClock], create_bucket):
    rates = [Rate(30, 1000), Rate(50, 2000)]
    bucket = create_bucket(rates)

    start = time()
    while bucket.count() < 150:
        bucket.put(RateItem("item", clock.now()))

        if bucket.count() == 31:
            cost = time() - start
            logging.info(">30 items: %s", cost)
            assert cost > 1

        if bucket.count() == 51:
            cost = time() - start
            logging.info(">50 items: %s", cost)
            assert cost > 2

        if bucket.count() == 81:
            cost = time() - start
            logging.info(">80 items: %s", cost)
            assert cost > 3

        if bucket.count() == 101:
            cost = time() - start
            logging.info(">100 items: %s", cost)
            assert cost > 4


def test_bucket_availability(clock: Union[MonotonicClock, TimeClock, SQLiteClock], create_bucket):
    rates = [Rate(3, 1000)]
    bucket = create_bucket(rates)

    logging.info("Testing `get_bucket_availability` with Bucket: %s, \nclock=%s", bucket, clock)

    assert get_bucket_availability(bucket, clock.now(), 1) == 0

    start = clock.now()
    assert start > 0

    for i in range(3):
        assert bucket.put(RateItem(f"a:{i}", clock.now())) is True
        # NOTE: sleep 100ms between each item
        sleep(0.2)

    end = clock.now()
    assert end > 0

    elapsed = end - start
    assert elapsed > 0

    logging.info("Elapsed: %s", elapsed)
    assert bucket.put(RateItem("a:3", clock.now())) is False

    availability = get_bucket_availability(bucket, clock.now(), 1)
    assert isinstance(availability, int)
    logging.info("1 space available in: %s", availability)

    sleep(availability / 1000 - 0.05)
    assert bucket.put(RateItem("a:3", clock.now())) is False
    sleep(0.05)
    assert bucket.put(RateItem("a:3", clock.now())) is True

    assert bucket.put(RateItem("a:4", clock.now(), weight=2)) is False
    availability = get_bucket_availability(bucket, clock.now(), 2)
    assert isinstance(availability, int)
    logging.info("2 space available in: %s", availability)

    sleep(availability / 1000 - 0.05)
    assert bucket.put(RateItem("a:4", clock.now(), weight=2)) is False
    sleep(0.05)
    assert bucket.put(RateItem("a:4", clock.now(), weight=2)) is True

    assert bucket.put(RateItem("a:5", clock.now(), weight=3)) is False
    availability = get_bucket_availability(bucket, clock.now(), 3)
    assert isinstance(availability, int)
    logging.info("3 space available in: %s", availability)

    sleep(availability / 1000 - 0.05)
    assert bucket.put(RateItem("a:5", clock.now(), weight=3)) is False
    sleep(0.05)
    assert bucket.put(RateItem("a:5", clock.now(), 3)) is True


def test_bucket_leak(clock: Union[MonotonicClock, TimeClock, SQLiteClock], create_bucket):
    rates = [Rate(100, 3000)]
    bucket = create_bucket(rates)

    while bucket.count() < 200:
        bucket.put(RateItem("item", clock.now()))

    bucket.leak(clock.now())
    assert bucket.count() == 100
    assert bucket.leak(clock.now()) == 0
    assert bucket.count() == 100

    sleep(3.01)
    assert bucket.leak(clock.now()) == 100
    assert bucket.leak(clock.now()) == 0
    assert bucket.count() == 0


def test_bucket_flush(clock: Union[MonotonicClock, TimeClock, SQLiteClock], create_bucket):
    rates = [Rate(5000, 1000)]
    bucket = create_bucket(rates)

    while bucket.count() < 5000:
        bucket.put(RateItem("item", clock.now()))

    bucket.flush()
    assert bucket.count() == 0


def test_with_large_items(clock: Union[MonotonicClock, TimeClock, SQLiteClock], create_bucket):
    rates = [Rate(10000, 1000), Rate(20000, 3000), Rate(30000, 5000)]
    bucket = create_bucket(rates)

    before = time()

    for _ in range(10_000):
        item = RateItem("item", clock.now())
        bucket.put(item)

    after = time()
    elapsed = after - before
    logging.info("---------- INSERT 10K ITEMS COST: %s(secs), %s(items)", elapsed, bucket.count())
