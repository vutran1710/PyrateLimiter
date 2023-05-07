import logging
from os import getenv
from time import time
from typing import Union

import pytest
from redis import ConnectionPool
from redis import Redis

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import RedisSyncBucket
from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import TimeClock
from pyrate_limiter.utils import id_generator


@pytest.fixture
def redis_pool():
    pool = ConnectionPool.from_url(getenv("REDIS", "redis://localhost:6379"))
    yield pool


def test_bucket_01(clock: Union[MonotonicClock, TimeClock], redis_pool):
    redis_db = Redis(connection_pool=redis_pool)
    bucket_key = f"test-bucket/{id_generator()}"
    rates = [Rate(20, 1000)]
    bucket = RedisSyncBucket(rates, redis_db, bucket_key)
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


def test_bucket_02(clock: Union[MonotonicClock, TimeClock], redis_pool):
    rates = [Rate(30, 1000), Rate(50, 2000)]
    redis_db = Redis(connection_pool=redis_pool)
    bucket_key = f"test-bucket/{id_generator()}"
    bucket = RedisSyncBucket(rates, redis_db, bucket_key)

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


def test_bucket_leak(clock: Union[MonotonicClock, TimeClock], redis_pool):
    rates = [Rate(1000, 1000)]
    redis_db = Redis(connection_pool=redis_pool)
    bucket_key = f"test-bucket/{id_generator()}"
    bucket = RedisSyncBucket(rates, redis_db, bucket_key)

    while bucket.count() < 2000:
        bucket.put(RateItem("item", clock.now()))

    bucket.leak(clock.now())
    assert bucket.count() == 1000


def test_bucket_flush(clock: Union[MonotonicClock, TimeClock], redis_pool):
    rates = [Rate(5000, 1000)]
    redis_db = Redis(connection_pool=redis_pool)
    bucket_key = f"test-bucket/{id_generator()}"
    bucket = RedisSyncBucket(rates, redis_db, bucket_key)

    while bucket.count() < 10000:
        bucket.put(RateItem("item", clock.now()))

    bucket.flush()
    assert bucket.count() == 0


def test_with_large_items(redis_pool, clock):
    redis_db = Redis(connection_pool=redis_pool)
    bucket_key = f"test-bucket/{id_generator()}"
    rates = [Rate(10000, 1000), Rate(20000, 3000), Rate(30000, 5000)]
    bucket = RedisSyncBucket(rates, redis_db, bucket_key)

    before = time()

    for _ in range(10_000):
        item = RateItem("item", clock.now())
        bucket.put(item)

    after = time()
    elapsed = after - before
    print("---------- COST: ", elapsed, bucket.count_bucket())
