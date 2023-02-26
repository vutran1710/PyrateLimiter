"""Testing with RedisBucket"""
from time import sleep

import pytest
from fakeredis import FakeStrictRedis

from pyrate_limiter import BucketFullException
from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import RedisBucket
from pyrate_limiter import RedisClusterBucket
from pyrate_limiter import RequestRate
from pyrate_limiter.exceptions import InvalidParams

dummy_redis = FakeStrictRedis()
pool = dummy_redis.connection_pool


def test_bucket_initialization():
    rate = RequestRate(3, 5 * Duration.SECOND)

    try:
        Limiter(
            rate,
            bucket_class=RedisBucket,
            bucket_kwargs={
                "bucket_name": "some-name",
            },
        )
        assert False
    except InvalidParams:
        pass

    try:
        Limiter(
            rate,
            bucket_class=RedisBucket,
            bucket_kwargs={
                "redis_pool": pool,
            },
        )
        assert False
    except InvalidParams:
        pass


def test_simple_01(time_function):
    """Single-rate Limiter with RedisBucket"""
    rate = RequestRate(3, 5 * Duration.SECOND)
    expire_time = rate.interval * rate.limit
    limiter = Limiter(
        rate,
        bucket_class=RedisBucket,
        # Separate buckets used to distinct values from previous run,
        # as time_function return value has different int part.
        bucket_kwargs={
            "redis_pool": pool,
            "bucket_name": str(time_function),
            # After the set time, the bucket key in Redis should expire
            # to prevent unneccessary memory cost
            "expire_time": expire_time,
        },
        time_function=time_function,
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

    # After expire-time, bucket should expires
    assert limiter.get_current_volume(item) > 0
    sleep(expire_time)
    assert limiter.get_current_volume(item) == 0


def test_simple_02(time_function):
    """Multi-rates Limiter with RedisBucket"""
    rate_1 = RequestRate(5, 5 * Duration.SECOND)
    rate_2 = RequestRate(7, 9 * Duration.SECOND)
    limiter4 = Limiter(
        rate_1,
        rate_2,
        bucket_class=RedisBucket,
        bucket_kwargs={
            "redis_pool": pool,
            # Separate buckets used to distinct values from previous run,
            # as time_function return value has different int part.
            "bucket_name": str(time_function),
        },
        time_function=time_function,
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


def test_flushing():
    """Multi-rates Limiter with RedisBucket"""
    rate_1 = RequestRate(5, 5 * Duration.SECOND)
    limiter = Limiter(
        rate_1,
        bucket_class=RedisBucket,
        bucket_kwargs={
            "redis_pool": pool,
            "bucket_name": "Flushing-Bucket",
        },
    )
    item = "redis-test-item"

    for _ in range(3):
        limiter.try_acquire(item)

    size = limiter.get_current_volume(item)
    assert size == 3
    assert limiter.flush_all() == 1

    size = limiter.get_current_volume(item)
    assert size == 0


def test_redis_cluster():
    """Testing RedisClusterBucket initialization"""
    rate = RequestRate(3, 5 * Duration.SECOND)
    bucket = RedisClusterBucket(redis_pool=pool, bucket_name="any-name", identity="id-string")
    Limiter(
        rate,
        bucket_class=RedisClusterBucket,
        bucket_kwargs={"redis_pool": pool, "bucket_name": "test-bucket-1"},
    )

    assert bucket.get_connection()
