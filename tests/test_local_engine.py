from logzero import logger  # noqa
from time import sleep
import pytest
from pyrate_limiter.engines.local import LocalBucket
from pyrate_limiter.core import LeakyBucketLimiter, TokenBucketLimiter
from pyrate_limiter.exceptions import InvalidInitialValues, BucketFullException

bucket = None

def test_invalid_initials():
    global bucket
    with pytest.raises(InvalidInitialValues):
        bucket_instance = LocalBucket(initial_values='abc')


def test_leaky_bucket_overloaded():
    global bucket
    # Leaking rate is 3 seconds, capacity is 3-items
    bucket_instance = LocalBucket()
    bucket = LeakyBucketLimiter(bucket_instance, capacity=3, window=3)

    # Continuous hit to bucket should fail at maximum-capacity overloading
    with pytest.raises(BucketFullException):
        for _ in range(4):
            bucket.append(_)

    assert bucket.queue.getlen() == 3
    assert bucket.queue.values()[0]['item'] == 0
    assert bucket.queue.values()[2]['item'] == 2


def test_leaky_bucket_cooldown():
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


def test_token_bucket_overloaded():
    global bucket
    # Window is 4 seconds, capacity is 2-items
    bucket_instance = LocalBucket()
    bucket = TokenBucketLimiter(bucket_instance, capacity=2, window=4)

    # Continuous hit to bucket should fail at maximum-capacity overloading
    with pytest.raises(BucketFullException):
        for _ in range(4):
            bucket.process(_)

    assert bucket.queue.getlen() == 2
    assert bucket.queue.values()[0]['item'] == 0
    assert bucket.queue.values()[1]['item'] == 1


def test_token_bucket_cooldown():
    global bucket
    sleep(4)
    bucket.refill()
    assert bucket.queue.getlen() == 0

    # Start of Window
    bucket.process(1)
    assert bucket.queue.values()[0]['item'] == 1

    # End of Window
    sleep(3.9)
    bucket.process(2)
    assert bucket.queue.values()[1]['item'] == 2

    sleep(0.2)
    with pytest.raises(BucketFullException):
        bucket.process(3)

    sleep(0.2 + 3.8)
    bucket.process(4)
    bucket.process(5)

    assert bucket.queue.values()[0]['item'] == 4
    assert bucket.queue.values()[1]['item'] == 5
    assert bucket.queue.getlen() == 2
