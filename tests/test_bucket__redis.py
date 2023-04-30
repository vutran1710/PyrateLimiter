import pytest
from redis import Redis

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import RedisSyncBucket

BUCKET_KEY = "test-bucket"


@pytest.fixture
def db():
    conn = Redis(host="localhost", port=6379, db=0)
    assert conn.ping()
    conn.flushall()
    yield conn


def test_01(db, clock):
    rates = [Rate(20, 1000)]
    bucket = RedisSyncBucket(rates, db, BUCKET_KEY)

    bucket.put(RateItem("item", clock.now(), weight=10))
    assert db.zcard(BUCKET_KEY) == 10

    for n in range(20):
        is_ok = bucket.put(RateItem("zzzzzzzz", clock.now()))
        assert is_ok == (n < 10)

    assert db.zcard(BUCKET_KEY) == 20
