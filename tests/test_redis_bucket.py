from time import sleep
import json
import pytest
from logzero import logger  # noqa
from pyrate_limiter.engines.redis import LeakyRedis
from pyrate_limiter.core import LeakyBucketLimiter
from pyrate_limiter.exceptions import BucketFullException

b = LeakyRedis('redis://localhost:6377', hash='hash-name')
bucket = LeakyBucketLimiter(b, capacity=3, window=3)
bucket.queue.config(key='user-id')


def test_bucket_overloaded():
    global bucket

    # Continuous hit to bucket should fail at maximum-capacity overloading
    with pytest.raises(BucketFullException):
        for _ in range(4):
            bucket.append(_)

    assert bucket.queue.getlen() == 3
    assert bucket.queue.values()[0]['item'] == 0
    assert bucket.queue.values()[2]['item'] == 2


def test_bucket_cooldown():
    # Current bucket: [0, 1, 2]
    global bucket
    sleep(3)
    bucket.leak()
    assert bucket.queue.getlen() == 0

    # After window time, bucket queue should be empty, because
    # the first items in buckets were sent almost simultanously
    # Putting new item every 1 seconds to balance the leaking rate
    bucket.append(3)
    # Current bucket: [3]
    sleep(1)
    bucket.append(4)
    sleep(1)
    bucket.append(5)
    sleep(1)
    bucket.append(6)
    # Current bucket: [4, 5, 6]

    with pytest.raises(BucketFullException):
        # Instant addition to queue should fail
        bucket.append('fail')

    assert bucket.queue.getlen() == 3
    assert bucket.queue.values()[2]['item'] == 6
    assert bucket.queue.values()[0]['item'] == 4

    sleep(2)
    bucket.append(7)
    bucket.append(8)

    with pytest.raises(BucketFullException):
        bucket.append('fail')

    assert bucket.queue.getlen() == 3
    assert bucket.queue.values()[2]['item'] == 8
    assert bucket.queue.values()[0]['item'] == 6


def test_normalize_redis_value():
    global bucket
    bucket.queue.conn.hset('hash-name', 'wow', 'invalid-value')

    bucket.queue.config(key='wow')
    assert bucket.queue.__values__ == []

    bucket.queue.conn.hset('hash-name', 'ahihi', json.dumps({'key': 'value'}))

    bucket.queue.config(key='ahihi')
    assert bucket.queue.__values__ == []
