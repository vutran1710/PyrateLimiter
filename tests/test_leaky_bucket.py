from logzero import logger  # noqa
from time import sleep
from snaky_bucket.basic_algorimth import LeakyBucket
from snaky_bucket.exceptions import BucketFullException
import pytest

bucket = None
"""LeakyBucket with Sliding-Window Algorimth is a capped bucket
of items. Every item expires after {window} time, making room for later items
to go in.

* Notable characteristic: item's expiring-rate is {window} time.

Timeline:

TIME <<--------------[======================WINDOW======================]---------------------------
REQS >>--- <req> ---- <req> ---- <req> ---- <req> ---- <req> ---- <req> ---- <req> ---- <req> ---->>  # noqa

"""


def test_bucket_overloaded():
    global bucket
    # Leaking rate is 3 seconds, capacity is 3-items
    bucket = LeakyBucket(capacity=3, window=3)

    # Continuous hit to bucket should fail at maximum-capacity overloading
    with pytest.raises(BucketFullException):
        for _ in range(4):
            bucket.append(_)

    assert len(bucket.queue) == 3
    assert bucket.queue[0]['item'] == 0
    assert bucket.queue[2]['item'] == 2


def test_bucket_cooldown():
    # Current bucket: [0, 1, 2]
    global bucket
    sleep(3)
    bucket.leak()
    assert len(bucket.queue) == 0

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

    assert len(bucket.queue) == 3
    assert bucket.queue[2]['item'] == 6
    assert bucket.queue[0]['item'] == 4

    sleep(2)
    bucket.append(7)
    bucket.append(8)

    with pytest.raises(BucketFullException):
        bucket.append('fail')

    assert len(bucket.queue) == 3
    assert bucket.queue[2]['item'] == 8
    assert bucket.queue[0]['item'] == 6
