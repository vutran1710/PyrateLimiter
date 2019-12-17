from logzero import logger  # noqa
from time import sleep
from pyrate_limiter.basic_algorimth import TokenBucket
from pyrate_limiter.exceptions import BucketFullException
import pytest

bucket = None
"""TokenBucket with Fixed-Window Algorithm can be described as
multiple groups of Going-In-Items that does not exceed the Bucket Capacity
running into the Bucket at fixed-interval between groups

* Notable characteristic: bucket's queue reset if interval between 2 items
is larger or equal {window} time.

Timeline:

>--- [x (requests)] ------ (window-time) ------ [y (requests)] ------ (window-time) ------ [z (requests)] --->  # noqa
eg:     3reqs/3s              <5sec>               2reqs/1s              <5sec>               3reqs/3s
"""


def test_bucket_overloaded():
    global bucket
    # Window is 4 seconds, capacity is 2-items
    bucket = TokenBucket(capacity=2, window=4)

    # Continuous hit to bucket should fail at maximum-capacity overloading
    with pytest.raises(BucketFullException):
        for _ in range(4):
            bucket.process(_)

    assert len(bucket.queue) == 2
    assert bucket.queue[0]['item'] == 0
    assert bucket.queue[1]['item'] == 1


def test_bucket_cooldown():
    global bucket
    sleep(4)
    bucket.refill()
    assert len(bucket.queue) == 0

    # Start of Window
    bucket.process(1)
    assert bucket.queue[0]['item'] == 1

    # End of Window
    sleep(3.9)
    bucket.process(2)
    assert bucket.queue[1]['item'] == 2

    sleep(0.2)
    with pytest.raises(BucketFullException):
        bucket.process(3)

    sleep(0.2 + 3.8)
    bucket.process(4)
    bucket.process(5)

    assert bucket.queue[0]['item'] == 4
    assert bucket.queue[1]['item'] == 5
    assert len(bucket.queue) == 2
