from concurrent.futures import ThreadPoolExecutor
from pprint import pprint
from random import randint
from time import sleep
from time import time
from typing import List
from typing import Union

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import TimeClock
from pyrate_limiter.default_buckets import binary_search
from pyrate_limiter.default_buckets import SimpleListBucket


def debug_rate_items(items: List[RateItem], from_idx=0):
    pprint([i.timestamp for i in items[from_idx:]])


def hr_divider():
    print("----------------------------------------")


def test_binary_search():
    """Testing binary-search that find item in array"""
    # Normal list of items
    items = [RateItem("item", nth * 2) for nth in range(5)]
    debug_rate_items(items)

    assert binary_search(items, 0) == 0
    assert binary_search(items, 1) == 1
    assert binary_search(items, 2) == 1
    assert binary_search(items, 3) == 2

    # If the value is larger than the last item, idx would be -1
    assert binary_search(items, 11) == -1

    # Empty list
    items = []
    debug_rate_items(items)

    assert binary_search(items, 1) == 0
    assert binary_search(items, 2) == 0
    assert binary_search(items, 3) == 0


def test_simple_list_bucket_using_time_clock_01(clock: Union[MonotonicClock, TimeClock]):
    """SimpleListBucket with 1 rate, using synchronous clock"""
    rates = [Rate(5, 200)]

    bucket = SimpleListBucket(rates)

    for nth in range(10):
        # Putting 10 items into the bucket instantly
        # The items has the same timestamp
        if nth < 5:
            assert bucket.put(RateItem("item", clock.now())) is True
            assert bucket.rate_at_limit is None

        if nth >= 6:
            assert bucket.put(RateItem("item", clock.now())) is False
            assert bucket.rate_at_limit == rates[0]

        debug_rate_items(bucket.items)

    sleep(0.200)
    hr_divider()
    # After sleeping for 200msec, the limit is gone
    # because all the existing items have the same timestamp
    for _ in range(5):
        assert bucket.put(RateItem("item", clock.now())) is True
        assert bucket.rate_at_limit is None
        debug_rate_items(bucket.items, from_idx=5)

    sleep(0.2)
    hr_divider()
    # After sleeping for another 200msec, the limit is gone
    # Putting an item with excessive weight is not possible
    assert bucket.put(RateItem("item", clock.now(), weight=6)) is False
    debug_rate_items(bucket.items, from_idx=5)


def test_simple_list_bucket_using_time_clock_02(clock: Union[MonotonicClock, TimeClock]):
    """SimpleListBucket in thread-safe
    Confirm the bucket works without race-condition
    """
    rates = [Rate(20, 100 * 1000)]
    bucket = SimpleListBucket(rates)

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
