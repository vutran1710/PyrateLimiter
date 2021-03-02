from time import sleep
import pytest

from pyrate_limiter import (
    BucketFullException,
    Duration,
    RequestRate,
    Limiter,
    MemoryListBucket,
)


def test_sleep():
    rate = RequestRate(6, 10 * Duration.SECOND)
    iterations = 10
    limiter = Limiter(rate)
    push = 0

    for i in range(iterations):
        try:
            for _ in range(2):
                limiter.try_acquire("test")
                push += 1
            print(f"Pushed: {push} items")
            sleep(1)
        except BucketFullException as e:
            sleep_time = e.meta_info["remaining_time"]
            print(f"Stuck at {i}, sleep for {sleep_time}")
            sleep(sleep_time)


def test_simple_01():
    """Single-rate Limiter"""
    rate = RequestRate(3, 5 * Duration.SECOND)
    limiter = Limiter(rate)
    item = "vutran"

    has_raised = False
    try:
        for _ in range(4):
            limiter.try_acquire(item)
            sleep(1)
    except BucketFullException as err:
        has_raised = True
        print(err)
        assert str(err)
        assert isinstance(err.meta_info, dict)
        assert err.meta_info["remaining_time"] == 2

    assert has_raised

    sleep(6)
    limiter.try_acquire(item)
    vol = limiter.get_current_volume(item)
    assert vol == 1

    limiter.try_acquire(item)
    limiter.try_acquire(item)

    with pytest.raises(BucketFullException):
        limiter.try_acquire(item)


def test_simple_02():
    """Multi-rates Limiter"""
    rate_1 = RequestRate(5, 5 * Duration.SECOND)
    rate_2 = RequestRate(7, 9 * Duration.SECOND)
    limiter2 = Limiter(rate_1, rate_2)
    item = "tranvu"
    err = None

    with pytest.raises(BucketFullException) as err:
        # Try add 6 items within 5 seconds
        # Exceed Rate-1
        for _ in range(6):
            limiter2.try_acquire(item)

    print(err.value.meta_info)
    assert limiter2.get_current_volume(item) == 5

    sleep(6)
    # Still shorter than Rate-2 interval, so all items must be kept
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)
    assert limiter2.get_current_volume(item) == 7

    with pytest.raises(BucketFullException) as err:
        # Exceed Rate-2
        limiter2.try_acquire(item)

    print(err.value.meta_info)
    sleep(6)
    # 12 seconds passed
    limiter2.try_acquire(item)
    # Only items within last 9 seconds kept, plus the new one
    assert limiter2.get_current_volume(item) == 3

    # print('Bucket Rate-1:', limiter2.get_filled_slots(rate_1, item))
    # print('Bucket Rate-2:', limiter2.get_filled_slots(rate_2, item))
    # Within the nearest 5 second interval
    # Rate-1 has only 1 item, so we can add 4 more
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)

    with pytest.raises(BucketFullException):
        # Exceed Rate-1 again
        limiter2.try_acquire(item)

    # Withint the nearest 9 second-interval, we have 7 items
    assert limiter2.get_current_volume(item) == 7

    # Fast forward to 6 more seconds
    # Bucket Rate-1 is refreshed and empty by now
    # Bucket Rate-2 has now only 5 items
    sleep(6)
    # print('Bucket Rate-1:', limiter2.get_filled_slots(rate_1, item))
    # print('Bucket Rate-2:', limiter2.get_filled_slots(rate_2, item))
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)

    with pytest.raises(BucketFullException):
        # Exceed Rate-2 again
        limiter2.try_acquire(item)


def test_simple_03():
    """Single-rate Limiter with MemoryListBucket"""
    rate = RequestRate(3, 5 * Duration.SECOND)
    limiter = Limiter(rate, bucket_class=MemoryListBucket)
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


def test_simple_04():
    """Multi-rates Limiter with MemoryListBucket"""
    rate_1 = RequestRate(5, 5 * Duration.SECOND)
    rate_2 = RequestRate(7, 9 * Duration.SECOND)
    limiter2 = Limiter(rate_1, rate_2, bucket_class=MemoryListBucket)
    item = "tranvu_list"

    with pytest.raises(BucketFullException):
        # Try add 6 items within 5 seconds
        # Exceed Rate-1
        for _ in range(6):
            limiter2.try_acquire(item)

    assert limiter2.get_current_volume(item) == 5

    sleep(6)
    # Still shorter than Rate-2 interval, so all items must be kept
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)
    assert limiter2.get_current_volume(item) == 7

    with pytest.raises(BucketFullException):
        # Exceed Rate-2
        limiter2.try_acquire(item)

    sleep(6)
    # 12 seconds passed
    limiter2.try_acquire(item)
    # Only items within last 9 seconds kept, plus the new one
    assert limiter2.get_current_volume(item) == 3

    # print('Bucket Rate-1:', limiter2.get_filled_slots(rate_1, item))
    # print('Bucket Rate-2:', limiter2.get_filled_slots(rate_2, item))
    # Within the nearest 5 second interval
    # Rate-1 has only 1 item, so we can add 4 more
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)

    with pytest.raises(BucketFullException):
        # Exceed Rate-1 again
        limiter2.try_acquire(item)

    # Withint the nearest 9 second-interval, we have 7 items
    assert limiter2.get_current_volume(item) == 7

    # Fast forward to 6 more seconds
    # Bucket Rate-1 is refreshed and empty by now
    # Bucket Rate-2 has now only 5 items
    sleep(6)
    # print('Bucket Rate-1:', limiter2.get_filled_slots(rate_1, item))
    # print('Bucket Rate-2:', limiter2.get_filled_slots(rate_2, item))
    limiter2.try_acquire(item)
    limiter2.try_acquire(item)

    with pytest.raises(BucketFullException):
        # Exceed Rate-2 again
        limiter2.try_acquire(item)
