from logzero import logger  # noqa
from time import sleep
from snaky_bucket.basic_algorimth import Bucket
from snaky_bucket.exceptions import BucketFullException
import pytest

bucket = None


@pytest.mark.xfail(raises=BucketFullException)
def test_bucket_overloaded():
    global bucket
    # Leaking rate is 3 seconds, capacity is 3-items
    bucket = Bucket(capacity=3, window=3)

    # Continuous hit to bucket should fail at maximum-capacity overloading
    for _ in range(3):
        bucket.append(_)


def test_bucket_cooldown():
    # Current bucket: [0, 1, 2]
    global bucket
    sleep(3)
    bucket.leak()
    assert len(bucket.queue) == 0

    # After window time, bucket queue should be empty
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
