from time import sleep

import pytest
from redis import Redis

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import RedisSyncBucket
from pyrate_limiter.utils import id_generator

BUCKET_KEY = f"test-bucket/{id_generator()}"


@pytest.fixture
def redis_db():
    conn = Redis(host="localhost", port=6379, db=0)
    assert conn.ping()
    conn.flushall()
    yield conn


def test_01(redis_db, clock):
    rates = [Rate(20, 1000), Rate(30, 2000)]
    bucket = RedisSyncBucket(rates, redis_db, BUCKET_KEY)

    bucket.put(RateItem("item", clock.now(), weight=10))
    assert redis_db.zcard(BUCKET_KEY) == 10

    for nth in range(20):
        is_ok = bucket.put(RateItem("zzzzzzzz", clock.now()))
        assert is_ok == (nth < 10)

    assert redis_db.zcard(BUCKET_KEY) == 20
    print("-----------> Failing rate", bucket.failing_rate)
    assert bucket.failing_rate is rates[0]

    sleep(1)

    for nth in range(20):
        is_ok = bucket.put(RateItem("zzzzzzzz", clock.now()))

    assert redis_db.zcard(BUCKET_KEY) == 30
    print("-----------> Failing rate", bucket.failing_rate)
    assert bucket.failing_rate is rates[1]


def test_leaking(redis_db, clock):
    rates = [Rate(50, 1000)]
    bucket = RedisSyncBucket(rates, redis_db, BUCKET_KEY)

    for nth in range(50):
        bucket.put(RateItem("zzzzzzzz", clock.now()))
        sleep(0.015)

    assert redis_db.zcard(BUCKET_KEY) == 50
    sleep(0.01)
    remove_count = bucket.leak(clock)
    print("Removed ", remove_count, " items")
    assert redis_db.zcard(BUCKET_KEY) == 50 - remove_count
