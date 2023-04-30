from redis import Redis

from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import RedisSyncBucket

BUCKET_KEY = "test-bucket"


def test_01():
    redis = Redis(host="localhost", port=6379, db=0)
    assert redis.ping()
    redis.flushall()

    bucket = RedisSyncBucket(redis, BUCKET_KEY)
    bucket.put(RateItem("item", 0, weight=10))
    assert redis.zcard(BUCKET_KEY) == 10
