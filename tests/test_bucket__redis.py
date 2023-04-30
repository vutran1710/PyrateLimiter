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
    rates = [Rate(5, 1000)]
    bucket = RedisSyncBucket(rates, db, BUCKET_KEY)
    bucket.flush()
    bucket.put(RateItem("item", 0, weight=10))
    assert db.zcard(BUCKET_KEY) == 10
