# tests/test_limiter_blocking_behavior.py
import asyncio
import time
from inspect import isawaitable
import pytest
from pyrate_limiter import Rate
from pyrate_limiter.abstracts import AbstractBucket, BucketFactory, RateItem
from pyrate_limiter.buckets import InMemoryBucket
from pyrate_limiter.limiter import Limiter

RATE = Rate(1, 200)  # 1 token per 200ms

def make_limiter():
    return Limiter(InMemoryBucket([RATE]), buffer_ms=0)

# --- sync decorator blocks ---
def test_sync_decorator_blocks():
    lim = make_limiter()

    @lim.as_decorator()
    def work():
        return time.perf_counter()

    t0 = time.perf_counter()
    work()                      # consumes the only slot
    t1 = work()                 # must block ~200ms waiting for leak
    elapsed = t1 - t0
    assert elapsed >= 0.18

# --- async decorator blocks ---
@pytest.mark.asyncio
async def test_async_decorator_blocks():
    lim = make_limiter()

    @lim.as_decorator()
    async def work():
        return time.perf_counter()

    t0 = time.perf_counter()
    await work()               # consumes the only slot
    t1 = await work()          # must block ~200ms
    elapsed = t1 - t0
    assert elapsed >= 0.18

# --- try_acquire: non-blocking fails on contention ---
def test_try_acquire_nonblocking_false():
    lim = make_limiter()
    assert lim.try_acquire("k", blocking=False) is True
    assert lim.try_acquire("k", blocking=False) is False  # immediate refusal

# --- try_acquire_async: non-blocking fails on contention ---
@pytest.mark.asyncio
async def test_try_acquire_async_nonblocking_false():
    lim = make_limiter()
    # ensure clean slate
    for b in lim.buckets():
        f = b.flush()
        if asyncio.iscoroutine(f): await f

    assert await lim.try_acquire_async("k_async_nb", blocking=False) is True
    assert await lim.try_acquire_async("k_async_nb", blocking=False) is False

    
# --- try_acquire_async with timeout enforces max wait ---
@pytest.mark.asyncio
async def test_try_acquire_async_timeout():
    lim = make_limiter()
    assert await lim.try_acquire_async("k", blocking=True) is True  # take the only slot

    t0 = time.perf_counter()
    ok = await lim.try_acquire_async("k", blocking=True, timeout=0.1)
    t1 = time.perf_counter()

    assert ok is False                       # timed out
    assert 0.09 <= (t1 - t0) <= 0.25         # waited ~timeout, not full 200ms

# --- sync timeout enforces max wait ---
def test_try_acquire_sync_timeout():
    lim = make_limiter()
    assert lim.try_acquire("k", blocking=True) is True  # take the only slot

    t0 = time.perf_counter()
    ok = lim.try_acquire("k", blocking=True, timeout=0.1)
    t1 = time.perf_counter()

    assert ok is False                        # timed out
    assert 0.09 <= (t1 - t0) <= 0.25         # waited ~timeout, not full 200ms


@pytest.mark.asyncio
async def test_try_acquire_timeout_with_awaitable_wrap_item():
    class AsyncNowInMemoryBucket(InMemoryBucket):
        async def now(self):
            await asyncio.sleep(0.2)
            now = super().now()
            if isawaitable(now):
                now = await now
            assert isinstance(now, int)
            return now

    lim = Limiter(AsyncNowInMemoryBucket([RATE]), buffer_ms=0)

    t0 = time.perf_counter()
    result = lim.try_acquire("k", blocking=True, timeout=0.1)
    assert isawaitable(result)
    ok = await result
    t1 = time.perf_counter()

    assert ok is False
    assert 0.09 <= (t1 - t0) <= 0.25


@pytest.mark.asyncio
async def test_try_acquire_timeout_with_awaitable_get_bucket():
    class AsyncGetFactory(BucketFactory):
        def __init__(self, bucket: AbstractBucket):
            self.bucket = bucket

        def wrap_item(self, name: str, weight: int = 1):
            now = self.bucket.now()
            assert isinstance(now, int)
            return RateItem(name, now, weight=weight)

        async def get(self, item: RateItem):
            await asyncio.sleep(0.2)
            return self.bucket

    lim = Limiter(AsyncGetFactory(InMemoryBucket([RATE])), buffer_ms=0)

    t0 = time.perf_counter()
    result = lim.try_acquire("k", blocking=True, timeout=0.1)
    assert isawaitable(result)
    ok = await result
    t1 = time.perf_counter()

    assert ok is False
    assert 0.09 <= (t1 - t0) <= 0.25
