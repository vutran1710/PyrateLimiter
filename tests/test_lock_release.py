"""Regression test for #301: the limiter lock must NOT be held during the
sync blocking sleep, otherwise a long wait on one key serializes acquisitions
for every other key sharing the limiter.
"""
import threading
import time

from pyrate_limiter import BucketFactory, InMemoryBucket, Limiter, Rate, RateItem
from pyrate_limiter.clocks import MonotonicClock


class _KeyedInMemoryFactory(BucketFactory):
    """Minimal per-key factory: one InMemoryBucket per name, all sharing the
    single limiter lock. No background leak (not needed for correctness)."""

    def __init__(self, rates):
        self._rates = rates
        self._buckets: dict = {}
        self._clock = MonotonicClock()

    def wrap_item(self, name, weight=1):
        return RateItem(name, self._clock.now(), weight=weight)

    def get(self, item):
        if item.name not in self._buckets:
            self._buckets[item.name] = InMemoryBucket(list(self._rates))
        return self._buckets[item.name]


def test_blocking_wait_on_one_key_does_not_serialize_other_keys():
    """While key 'A' is blocked waiting for its window, an acquire on the
    unrelated key 'B' (with free capacity) must return promptly - i.e. the
    limiter lock is released during A's sleep."""
    limiter = Limiter(_KeyedInMemoryFactory([Rate(1, 400)]), buffer_ms=10)

    assert limiter.try_acquire("A") is True  # consume A's only slot

    started = threading.Event()

    def block_on_a():
        started.set()
        assert limiter.try_acquire("A") is True  # full -> blocks ~400ms then ok

    t = threading.Thread(target=block_on_a)
    t.start()
    started.wait()
    time.sleep(0.05)  # let A's waiter reach its (unlocked) sleep

    t0 = time.perf_counter()
    assert limiter.try_acquire("B") is True  # B has free capacity
    dt = time.perf_counter() - t0

    # Lock released during A's sleep -> B is immediate. Before #301's fix B
    # would block on the limiter lock until A's ~400ms wait elapsed.
    assert dt < 0.15, f"B acquire took {dt:.3f}s - serialized behind A's wait?"

    t.join(timeout=2)
    assert not t.is_alive()
