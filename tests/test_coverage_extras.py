"""Targeted tests for previously-uncovered, service-independent code paths:
limiter_factory helpers, Duration/RateItem edges, BucketAsyncWrapper, the
async decorator, and Limiter.dispose().
"""
from pathlib import Path
from tempfile import gettempdir

import pytest

from pyrate_limiter import (
    BucketAsyncWrapper,
    Duration,
    InMemoryBucket,
    Limiter,
    Rate,
    RateItem,
    id_generator,
    limiter_factory,
)


# ----------------------------------------------------- limiter_factory helpers

def test_create_inmemory_limiter():
    lim = limiter_factory.create_inmemory_limiter(rate_per_duration=2, duration=Duration.SECOND)
    assert isinstance(lim, Limiter)
    assert lim.try_acquire("k") is True
    assert lim.try_acquire("k") is True
    assert lim.try_acquire("k", blocking=False) is False
    lim.close()


def test_create_sqlite_limiter():
    db_path = str(Path(gettempdir()) / f"pyrate_factory_{id_generator()}.sqlite")
    lim = limiter_factory.create_sqlite_limiter(
        rate_per_duration=2, duration=Duration.SECOND, db_path=db_path, table_name=f"t_{id_generator()}"
    )
    assert isinstance(lim, Limiter)
    assert lim.try_acquire("k") is True
    lim.close()


def test_init_global_limiter():
    limiter_factory.init_global_limiter(InMemoryBucket([Rate(2, Duration.SECOND)]))
    assert isinstance(limiter_factory.LIMITER, Limiter)
    assert limiter_factory.LIMITER.try_acquire("k") is True


# ---------------------------------------------------------- Duration / RateItem

def test_duration_eq_with_unsupported_type_is_false():
    # __eq__ returns NotImplemented for non-(Duration|int) -> Python falls back to False
    assert (Duration.SECOND == "1000") is False
    assert (Duration.SECOND != object()) is True
    # supported comparisons still work
    assert Duration.SECOND == 1000
    assert Duration.MINUTE == Duration.MINUTE


def test_rate_item_str():
    assert str(RateItem("foo", 1234, weight=3)) == "RateItem(name=foo, weight=3, timestamp=1234)"


# --------------------------------------------------------------- Limiter.dispose

def test_limiter_dispose_removes_bucket():
    lim = Limiter([Rate(5, Duration.SECOND)])
    buckets = lim.buckets()
    assert len(buckets) == 1
    assert lim.dispose(buckets[0]) is True
    assert lim.buckets() == []
    # disposing an unknown bucket id returns False
    assert lim.dispose(424242) is False
    lim.close()


# ---------------------------------------------------------------- async decorator

@pytest.mark.asyncio
async def test_async_decorator_wraps_and_runs():
    lim = Limiter([Rate(5, Duration.SECOND)])

    @lim.as_decorator(name="job", weight=1)
    async def work(x):
        return x * 2

    assert await work(21) == 42
    lim.close()


# ------------------------------------------------------------- BucketAsyncWrapper

@pytest.mark.asyncio
async def test_bucket_async_wrapper_over_sync_bucket():
    b = BucketAsyncWrapper(InMemoryBucket([Rate(5, 10_000)]))

    assert await b.count() == 0
    assert await b.put(RateItem("x", b.now())) is True
    assert await b.put(RateItem("x", b.now(), weight=2)) is True
    assert await b.count() == 3

    item = await b.peek(0)
    assert item is not None and item.name == "x"

    wait = await b.waiting(RateItem("x", b.now(), weight=1))
    assert isinstance(wait, int)

    # Everything is outside the window far in the future -> fully leaked.
    assert await b.leak(b.now() + 20_000) == 3
    assert await b.count() == 0

    await b.flush()
    assert await b.count() == 0


@pytest.mark.asyncio
async def test_bucket_async_wrapper_over_async_bucket():
    """Wrapping a bucket whose methods return awaitables exercises the
    `while isawaitable(...): await` loops in BucketAsyncWrapper."""
    from pyrate_limiter import AbstractBucket

    class _AsyncBucket(AbstractBucket):
        def __init__(self):
            self.rates = [Rate(5, 10_000)]
            self._store = []

        async def put(self, item):
            self._store.append(item)
            return True

        async def count(self):
            return len(self._store)

        async def leak(self, current_timestamp=None):
            n = len(self._store)
            self._store.clear()
            return n

        async def flush(self):
            self._store.clear()

        async def peek(self, index):
            return self._store[-1 - index] if index < len(self._store) else None

        def now(self):
            return 0

    b = BucketAsyncWrapper(_AsyncBucket())
    assert await b.count() == 0
    assert await b.put(RateItem("x", b.now())) is True
    assert await b.count() == 1
    assert (await b.peek(0)).name == "x"
    assert await b.leak(0) == 1
    await b.flush()
    assert await b.count() == 0
    # rates getter/setter delegate to the wrapped bucket
    assert b.rates[0].limit == 5
    b.rates = [Rate(7, 10_000)]
    assert b.rates[0].limit == 7


def test_inmemory_put_weight_zero_returns_true():
    bucket = InMemoryBucket([Rate(5, Duration.SECOND)])
    assert bucket.put(RateItem("x", bucket.now(), weight=0)) is True
    assert bucket.count() == 0


# --------------------------------------------- async wrapper over an async bucket

class SlowAsyncBucket(InMemoryBucket):
    """Async enough that waiting() itself comes back awaitable."""

    is_async = True

    def put(self, item: RateItem):
        admitted = super().put(item)
        self._last_wait = None  # force the derive-from-storage path

        async def _put():
            return admitted

        return _put()

    # Deliberately widens InMemoryBucket's narrowed peek() back to the
    # abstract contract, which allows an awaitable.
    async def peek(self, index: int):  # type: ignore[override]
        return super().peek(index)


@pytest.mark.asyncio
async def test_wrapper_awaits_an_awaitable_waiting():
    """BucketAsyncWrapper.waiting() must resolve what the inner bucket returns."""
    wrapped = BucketAsyncWrapper(SlowAsyncBucket([Rate(1, 1000)]))

    assert await wrapped.put(RateItem("a", 1000)) is True

    item = RateItem("a", 1200)
    assert await wrapped.put(item) is False
    assert await wrapped.waiting(item) == 1000 + 1000 - 1200 + 1


# ------------------------------------------------------ BucketFactory plumbing

def test_leak_interval_round_trips_through_the_leaker():
    limiter = Limiter(InMemoryBucket([Rate(2, 1000)]))
    factory = limiter.bucket_factory

    # A leaker exists once a bucket is scheduled, so both accessors go through it.
    assert factory.leak_interval == 10_000
    factory.leak_interval = 250
    assert factory.leak_interval == 250

    limiter.close()


def test_dispose_without_a_leaker_is_false():
    bucket = InMemoryBucket([Rate(2, 1000)])
    limiter = Limiter(bucket)
    limiter.close()  # drops the leaker

    assert limiter.dispose(bucket) is False
