""" Testing with RedisBucket
"""
from time import sleep

import pytest
from fakeredis import FakeStrictRedis
from pyrate_limiter import (BucketFullException, Duration, Limiter,
                            RedisBucket, RedisClusterBucket, RequestRate)

dummy_redis = FakeStrictRedis()
pool = dummy_redis.connection_pool


def test_simple_01():
    """Single-rate Limiter with RedisBucket"""
    rate = RequestRate(3, 5 * Duration.SECOND)
    limiter = Limiter(
        rate,
        bucket_class=RedisBucket,
        bucket_kwargs={"redis_pool": pool, "bucket_name": "test-bucket-1"},
    )
    item = "vutran_list"

    with pytest.raises(BucketFullException):
        for _ in range(4):
            limiter.try_acquire(item)

    sleep(6)
    limiter.try_acquire(item)
    vol = limiter.get_current_volume(item)
    assert vol == 1

    limiter.try_acquire(item)
    limiter.try_acquire(item)

    with pytest.raises(BucketFullException):
        limiter.try_acquire(item)


def test_simple_02():
    """Multi-rates Limiter with RedisBucket"""
    rate_1 = RequestRate(5, 5 * Duration.SECOND)
    rate_2 = RequestRate(7, 9 * Duration.SECOND)
    limiter4 = Limiter(
        rate_1,
        rate_2,
        bucket_class=RedisBucket,
        bucket_kwargs={
            "redis_pool": pool,
            "bucket_name": "test-bucket-2",
        },
    )
    item = "redis-test-item"

    with pytest.raises(BucketFullException):
        # Try add 6 items within 5 seconds
        # Exceed Rate-1
        for _ in range(6):
            limiter4.try_acquire(item)

    assert limiter4.get_current_volume(item) == 5

    sleep(6.5)
    # Still shorter than Rate-2 interval, so all items must be kept
    limiter4.try_acquire(item)
    # print('Bucket Rate-1:', limiter4.get_filled_slots(rate_1, item))
    # print('Bucket Rate-2:', limiter4.get_filled_slots(rate_2, item))
    limiter4.try_acquire(item)
    assert limiter4.get_current_volume(item) == 7

    with pytest.raises(BucketFullException):
        # Exceed Rate-2
        limiter4.try_acquire(item)

    sleep(6)
    # 12 seconds passed
    limiter4.try_acquire(item)
    # Only items within last 9 seconds kept, plus the new one
    assert limiter4.get_current_volume(item) == 3

    # print('Bucket Rate-1:', limiter4.get_filled_slots(rate_1, item))
    # print('Bucket Rate-2:', limiter4.get_filled_slots(rate_2, item))
    # Within the nearest 5 second interval
    # Rate-1 has only 1 item, so we can add 4 more
    limiter4.try_acquire(item)
    limiter4.try_acquire(item)
    limiter4.try_acquire(item)
    limiter4.try_acquire(item)

    with pytest.raises(BucketFullException):
        # Exceed Rate-1 again
        limiter4.try_acquire(item)

    # Withint the nearest 9 second-interval, we have 7 items
    assert limiter4.get_current_volume(item) == 7

    # Fast forward to 6 more seconds
    # Bucket Rate-1 is refreshed and empty by now
    # Bucket Rate-2 has now only 5 items
    sleep(6)
    # print('Bucket Rate-1:', limiter4.get_filled_slots(rate_1, item))
    # print('Bucket Rate-2:', limiter4.get_filled_slots(rate_2, item))
    limiter4.try_acquire(item)
    limiter4.try_acquire(item)

    with pytest.raises(BucketFullException):
        # Exceed Rate-2 again
        limiter4.try_acquire(item)


def test_redis_cluster():
    "Testing RedisClusterBucket initialization"
    rate = RequestRate(3, 5 * Duration.SECOND)
    Limiter(
        rate,
        bucket_class=RedisClusterBucket,
        bucket_kwargs={"redis_pool": pool, "bucket_name": "test-bucket-1"},
    )
