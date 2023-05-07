import logging
from concurrent.futures import ThreadPoolExecutor
from random import randint
from time import sleep
from time import time
from typing import Union

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import InMemoryBucket
from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import TimeClock


def test_bucket_01(clock: Union[MonotonicClock, TimeClock]):
    rates = [Rate(20, 1000)]
    bucket = InMemoryBucket(rates)
    assert bucket is not None

    bucket.put(RateItem("my-item", clock.now()))
    assert bucket.count() == 1

    bucket.put(RateItem("my-item", clock.now(), weight=10))
    assert bucket.count() == 11

    assert bucket.put(RateItem("my-item", clock.now(), weight=20)) is False
    assert bucket.failing_rate == rates[0]

    assert bucket.put(RateItem("my-item", clock.now(), weight=9)) is True
    assert bucket.count() == 20

    assert bucket.put(RateItem("my-item", clock.now())) is False


def test_bucket_02(clock: Union[MonotonicClock, TimeClock]):
    rates = [Rate(30, 1000), Rate(50, 2000)]
    bucket = InMemoryBucket(rates)

    start = time()
    while bucket.count() < 150:
        bucket.put(RateItem("item", clock.now()))

        if bucket.count() == 31:
            cost = time() - start
            logging.info(">30 items: %s", cost)
            assert cost > 1

        if bucket.count() == 51:
            cost = time() - start
            logging.info(">50 items: %s", cost)
            assert cost > 2

        if bucket.count() == 81:
            cost = time() - start
            logging.info(">80 items: %s", cost)
            assert cost > 3

        if bucket.count() == 101:
            cost = time() - start
            logging.info(">100 items: %s", cost)
            assert cost > 4


def test_bucket_leak(clock: Union[MonotonicClock, TimeClock]):
    rates = [Rate(5000, 1000)]
    bucket = InMemoryBucket(rates)

    while bucket.count() < 10000:
        bucket.put(RateItem("item", clock.now()))

    bucket.leak(clock.now())
    assert bucket.count() == 5000


def test_bucket_flush(clock: Union[MonotonicClock, TimeClock]):
    rates = [Rate(5000, 1000)]
    bucket = InMemoryBucket(rates)

    while bucket.count() < 10000:
        bucket.put(RateItem("item", clock.now()))

    bucket.flush()
    assert bucket.count() == 0


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

        logging.info(
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
    assert bucket.count() == 0


def test_simple_list_bucket_leak_task(clock):
    """Test InMemoryBucket should leak item periodically"""
    rates = [Rate(50, 1000)]
    bucket = InMemoryBucket(rates)

    assert bucket.leak(clock.now()) == 0

    for _ in range(50):
        bucket.put(RateItem("item", clock.now()))

    # Leaking have no effect because all items are within the window
    assert bucket.count() == 50
    bucket.leak(clock.now())
    assert bucket.count() == 50

    # Sleeping 1sec, leak now will discard all items
    sleep(1.001)

    assert bucket.count() == 50
    bucket.leak(clock.now())
    assert bucket.count() == 0

    # Fill the bucket again, slowly
    for _ in range(50):
        bucket.put(RateItem("item", clock.now()))
        sleep(0.01)

    # After this sleep, leak now will discard 2 items
    while clock.now() - 1000 <= bucket.items[1].timestamp:
        sleep(0.005)

    assert bucket.count() == 50
    bucket.leak(clock.now())
    assert bucket.count() == 48
