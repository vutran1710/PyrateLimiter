from os import getenv
from time import sleep
from time import time

import pytest
from redis import ConnectionPool
from redis import Redis

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import RedisSyncBucket
from pyrate_limiter.utils import id_generator


@pytest.fixture
def redis_pool():
    pool = ConnectionPool(host=getenv("REDIS", "localhost"), port=6379, db=0)
    yield pool


def test_01(redis_pool, clock):
    redis_db = Redis(connection_pool=redis_pool)
    bucket_key = f"test-bucket/{id_generator()}"
    rates = [Rate(20, 1000), Rate(30, 2000)]
    bucket = RedisSyncBucket(rates, redis_db, bucket_key)

    bucket.put(RateItem("item", clock.now(), weight=10))
    assert redis_db.zcard(bucket_key) == 10

    for nth in range(20):
        is_ok = bucket.put(RateItem("zzzzzzzz", clock.now()))
        assert is_ok == (nth < 10)

    assert redis_db.zcard(bucket_key) == 20
    print("-----------> Failing rate", bucket.failing_rate)
    assert bucket.failing_rate is rates[0]

    bucket.flush()

    for nth in range(32):
        count_before_put = bucket.count_bucket()
        is_ok = bucket.put(RateItem("zzzzzzzz", clock.now()))

        if nth < 20:
            assert is_ok is True

        if nth == 20:
            assert is_ok is False
            assert bucket.count_bucket() == 20
            print("before sleep:", clock.now())
            sleep(1)
            print("after sleep:", clock.now())

        if 31 > nth > 20:
            assert bucket.count_bucket() > count_before_put
            assert is_ok is True

        if nth == 31:
            assert is_ok is False

    assert redis_db.zcard(bucket_key) == 30
    print("-----------> Failing rate", bucket.failing_rate)
    assert bucket.failing_rate is rates[1]


def test_leaking(redis_pool, clock):
    redis_db = Redis(connection_pool=redis_pool)
    bucket_key = f"test-bucket/{id_generator()}"
    rates = [Rate(10, 1000)]
    bucket = RedisSyncBucket(rates, redis_db, bucket_key)

    for nth in range(10):
        bucket.put(RateItem("zzzzzzzz", clock.now()))
        sleep(0.1)

    assert redis_db.zcard(bucket_key) == 10

    items = redis_db.zrange(bucket_key, 0, clock.now(), withscores=True)
    lowest_timestamp = clock.now() - rates[-1].interval
    items_to_remove = [i[1] for i in items if i[1] < lowest_timestamp]

    print("-----> less than:", lowest_timestamp)
    print("-----> items:", items)
    print("-----> items-remove:", items_to_remove)

    remove_count = bucket.leak(clock.now())
    print("Removed ", remove_count, " items")
    assert remove_count == len(items_to_remove)


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
