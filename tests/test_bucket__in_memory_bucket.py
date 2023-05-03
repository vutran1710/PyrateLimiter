from concurrent.futures import ThreadPoolExecutor
from pprint import pprint
from random import randint
from time import sleep
from time import time
from typing import List
from typing import Union

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import InMemoryBucket
from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import TimeClock


def debug_rate_items(items: List[RateItem], from_idx=0):
    pprint([i.timestamp for i in items[from_idx:]])


def hr_divider():
    print("----------------------------------------")


def test_simple_list_bucket(clock: Union[MonotonicClock, TimeClock]):
    """InMemoryBucket with 1 rate, using synchronous clock"""
    rates = [Rate(5, 200)]

    bucket = InMemoryBucket(rates)

    for nth in range(10):
        # Putting 10 items into the bucket instantly
        # The items has the same timestamp
        if nth < 5:
            assert bucket.put(RateItem("item", clock.now())) is True
            assert bucket.failing_rate is None

        if nth >= 6:
            assert bucket.put(RateItem("item", clock.now())) is False
            assert bucket.failing_rate == rates[0]

        debug_rate_items(bucket.items)

    sleep(0.200)
    hr_divider()
    # After sleeping for 200msec, the limit is gone
    # because all the existing items have the same timestamp
    for _ in range(5):
        assert bucket.put(RateItem("item", clock.now())) is True
        assert bucket.failing_rate is None
        debug_rate_items(bucket.items, from_idx=5)

    sleep(0.2)
    hr_divider()
    # After sleeping for another 200msec, the limit is gone
    # Putting an item with excessive weight is not possible
    before_bucket_size = len(bucket.items)

    item = RateItem("item", clock.now(), weight=6)
    assert bucket.put(item) is False

    item = RateItem("item", clock.now(), weight=5)
    assert bucket.put(item) is True
    assert before_bucket_size == len(bucket.items) - item.weight


def test_simple_list_bucket_thread_safe_02(clock: Union[MonotonicClock, TimeClock]):
    """InMemoryBucket in thread-safe
    Confirm the bucket works without race-condition
    """
    rates = [Rate(20, 100 * 1000)]
    bucket = InMemoryBucket(rates)

    success, failure = [], []

    def put(nth: int):
        sleep(randint(1, 10) / 100)

        before = time()
        is_ok = bucket.put(RateItem("item", clock.now()))
        processing_time = round((time() - before) * 1000, 3)

        if is_ok:
            success.append(True)
        else:
            # Before failing, the bucket must be filled first
            assert len(success) == 20
            failure.append(False)

        print(
            f"""
Completed task#{nth}, Ok/Fail={len(success)}/{len(failure)}
- processing_time={processing_time}ms"""
        )

    with ThreadPoolExecutor() as executor:
        for _future in executor.map(put, list(range(40))):
            pass

    # All the timestamps are in a asc-sorted order
    assert sorted(bucket.items, key=lambda x: x.timestamp) == bucket.items

    # Flushing
    bucket.flush()
    assert len(bucket.items) == 0


def test_simple_list_bucket_leak_task(clock):
    """Test InMemoryBucket should leak item periodically"""
    rates = [Rate(50, 1000)]
    bucket = InMemoryBucket(rates)

    for _ in range(50):
        bucket.put(RateItem("item", clock.now()))

    # Leaking have no effect because all items are within the window
    assert len(bucket.items) == 50
    bucket.leak(clock.now())
    assert len(bucket.items) == 50

    # Sleeping 1sec, leak now will discard all items
    sleep(1.001)

    assert len(bucket.items) == 50
    bucket.leak(clock.now())
    assert len(bucket.items) == 0
