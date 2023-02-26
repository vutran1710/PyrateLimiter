"""Basic tests, non-asynchronous
"""
from time import sleep
from time import time
from unittest.mock import Mock

import pytest

from pyrate_limiter import BucketFullException
from pyrate_limiter import Duration
from pyrate_limiter import ImmutableClassProperty
from pyrate_limiter import InvalidParams
from pyrate_limiter import Limiter
from pyrate_limiter import MemoryListBucket
from pyrate_limiter import RequestRate


def test_sleep(time_function):
    """Make requests at a rate of 6 requests per 5 seconds (avg. 1.2 requests per second).
    If each request takes ~0.5 seconds, then the bucket should be full after 6 requests (3 seconds).
    Run 15 requests, and expect a total of 2 delays required to stay within the rate limit.
    """
    rate = RequestRate(6, 5 * Duration.SECOND)
    limiter = Limiter(rate, time_function=time_function)
    track_sleep = Mock(side_effect=sleep)  # run time.sleep() and track the number of calls
    start = time()

    for i in range(15):
        try:
            limiter.try_acquire("test")
            print(f"[{time() - start:07.4f}] Pushed: {i+1} items")
        except BucketFullException as err:
            print("%s --- %d", err.meta_info, i)
            track_sleep(err.meta_info["remaining_time"])

        # Simulated request rate,
        # IMPORTANT: sleep must be placed here
        sleep(0.5)

    print(f"Elapsed: {time() - start:07.4f} seconds")
    assert track_sleep.call_count == 2


def test_simple_01():
    """Single-rate Limiter"""
    with pytest.raises(InvalidParams):
        # No rates provided
        Limiter()

    with pytest.raises(InvalidParams):
        rate_1 = RequestRate(3, 5 * Duration.SECOND)
        rate_2 = RequestRate(4, 5 * Duration.SECOND)
        Limiter(rate_1, rate_2)

    rate = RequestRate(3, 5 * Duration.SECOND)

    with pytest.raises(ImmutableClassProperty):
        rate.limit = 10

    with pytest.raises(ImmutableClassProperty):
        rate.interval = 10

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
        assert round(err.meta_info["remaining_time"], 0) == 2.0

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

    assert limiter2.flush_all() == 1
    assert limiter2.get_current_volume(item) == 0


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

    assert limiter2.flush_all() == 1
    assert limiter2.get_current_volume(item) == 0


def test_remaining_time(time_function):
    """The remaining_time metadata returned from a BucketFullException should take into account
    the time elapsed during limited calls (including values less than 1 second).
    """
    limiter2 = Limiter(RequestRate(5, Duration.SECOND), time_function=time_function)
    for _ in range(5):
        limiter2.try_acquire("item")
    sleep(0.1)

    delay_time = 0

    try:
        limiter2.try_acquire("item")
    except BucketFullException as err:
        delay_time = err.meta_info["remaining_time"]

    assert round(delay_time, 1) == 0.9
