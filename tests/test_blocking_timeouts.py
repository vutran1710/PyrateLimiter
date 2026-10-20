# tests/test_limiter_blocking_behavior.py
import asyncio
import time
from inspect import isawaitable
import pytest
from pyrate_limiter import Rate
from pyrate_limiter.abstracts import AbstractBucket, BucketFactory, RateItem
from pyrate_limiter.buckets import InMemoryBucket
from pyrate_limiter.limiter import Limiter, SingleBucketFactory

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
    assert elapsed >= 0.15

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
    assert elapsed >= 0.15

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
    assert 0.08 <= (t1 - t0) <= 0.35         # waited ~timeout, not full 200ms


@pytest.mark.asyncio
@pytest.mark.parametrize("async_clock", [False, True])
async def test_try_acquire_async_late_wake_uses_factory_timestamp(monkeypatch, async_clock):
    class ManualClock:
        timestamp = 0

        def now(self):
            return self.timestamp

    class AsyncManualClock(ManualClock):
        async def now(self):
            return self.timestamp

    clock = AsyncManualClock() if async_clock else ManualClock()
    bucket = InMemoryBucket([Rate(1, 1000)])
    bucket._clock = clock
    limiter = Limiter(SingleBucketFactory(bucket, schedule_leak=False), buffer_ms=0)

    async def wake_late(_seconds):
        # Simulate the event loop resuming several windows after the requested
        # wait without introducing real-time sleeps into the test.
        clock.timestamp = 5000

    monkeypatch.setattr(asyncio, "sleep", wake_late)

    assert await limiter.try_acquire_async("late-wake") is True
    assert await limiter.try_acquire_async("late-wake") is True
    # The second permit was granted at timestamp 5000, so it must still occupy
    # the one-per-second window when queried at that same time.
    assert await limiter.try_acquire_async("late-wake", blocking=False) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("async_wrap", [False, True])
async def test_async_retry_uses_factory_clock_not_bucket_clock(monkeypatch, async_wrap):
    class FactoryClock:
        timestamp = 100

    factory_clock = FactoryClock()

    class BucketClock:
        timestamp = 50_000

        def now(self):
            return self.timestamp

    bucket_clock = BucketClock()
    bucket = InMemoryBucket([Rate(1, 1000)])
    bucket._clock = bucket_clock

    class DifferentClockFactory(BucketFactory):
        def wrap_item(self, name: str, weight: int = 1):
            if async_wrap:
                async def wrap_async():
                    return RateItem(name, timestamp=factory_clock.timestamp, weight=weight)

                return wrap_async()
            return RateItem(name, timestamp=factory_clock.timestamp, weight=weight)

        def get(self, item: RateItem):
            return bucket

    limiter = Limiter(DifferentClockFactory(), buffer_ms=0)

    async def wake_late(_seconds):
        factory_clock.timestamp = 5100

    monkeypatch.setattr(asyncio, "sleep", wake_late)

    assert await limiter.try_acquire_async("different-clocks") is True
    assert await limiter.try_acquire_async("different-clocks") is True
    acquired_item = bucket.peek(0)
    assert acquired_item is not None
    assert acquired_item.timestamp == 5100


@pytest.mark.asyncio
async def test_async_retry_awaitable_factory_refresh_obeys_deadline(monkeypatch):
    class CountingBucket(InMemoryBucket):
        put_count = 0

        def put(self, item):
            self.put_count += 1
            return super().put(item)

    bucket = CountingBucket([Rate(1, 10)])

    class DelayedRefreshFactory(BucketFactory):
        wrap_count = 0

        def wrap_item(self, name: str, weight: int = 1):
            self.wrap_count += 1
            if self.wrap_count == 3:
                async def wait_for_refresh():
                    await asyncio.Event().wait()

                return wait_for_refresh()
            return RateItem(name, timestamp=bucket.now(), weight=weight)

        def get(self, item: RateItem):
            return bucket

    factory = DelayedRefreshFactory()
    limiter = Limiter(factory, buffer_ms=0)

    async def skip_sleep(_seconds):
        pass

    monkeypatch.setattr(asyncio, "sleep", skip_sleep)

    assert await limiter.try_acquire_async("deadline") is True
    assert await limiter.try_acquire_async("deadline", timeout=0.05) is False
    assert factory.wrap_count == 3
    assert bucket.put_count == 2


@pytest.mark.asyncio
async def test_async_retry_factory_refresh_inserts_before_clock_callback(monkeypatch):
    class FactoryClock:
        timestamp = 100

    clock = FactoryClock()
    admissions = []

    class RecordingBucket(InMemoryBucket):
        def put(self, item):
            admissions.append((item.timestamp, clock.timestamp))
            return super().put(item)

    bucket = RecordingBucket([Rate(1, 1000)])

    class ScheduledClockFactory(BucketFactory):
        wrap_count = 0

        def wrap_item(self, name: str, weight: int = 1):
            self.wrap_count += 1
            is_retry = self.wrap_count == 3

            async def wrap_async():
                timestamp = clock.timestamp
                if is_retry:
                    asyncio.get_running_loop().call_soon(setattr, clock, "timestamp", timestamp + 1000)
                return RateItem(name, timestamp=timestamp, weight=weight)

            return wrap_async()

        def get(self, item: RateItem):
            return bucket

    limiter = Limiter(ScheduledClockFactory(), buffer_ms=0)

    async def wake_late(_seconds):
        clock.timestamp = 5100

    monkeypatch.setattr(asyncio, "sleep", wake_late)

    assert await limiter.try_acquire_async("clock-handoff", timeout=1) is True
    assert await limiter.try_acquire_async("clock-handoff", timeout=5) is True
    assert admissions[-1] == (5100, 5100)

# --- sync timeout enforces max wait ---
def test_try_acquire_sync_timeout():
    lim = make_limiter()
    assert lim.try_acquire("k", blocking=True) is True  # take the only slot

    t0 = time.perf_counter()
    ok = lim.try_acquire("k", blocking=True, timeout=0.1)
    t1 = time.perf_counter()

    assert ok is False                        # timed out
    assert 0.08 <= (t1 - t0) <= 0.35         # waited ~timeout, not full 200ms


def test_try_acquire_sync_nonblocking_rejects_timeout():
    lim = make_limiter()

    with pytest.raises(RuntimeError, match="Can't set timeout with non-blocking"):
        lim.try_acquire("k", blocking=False, timeout=0.1)


def test_try_acquire_sync_rejects_invalid_negative_timeout():
    lim = make_limiter()

    with pytest.raises(ValueError, match="timeout must be -1 or >= 0"):
        lim.try_acquire("k", blocking=True, timeout=-2)


def test_try_acquire_sync_blocking_unacquirable_weight_returns_false():
    lim = make_limiter()

    t0 = time.perf_counter()
    ok = lim.try_acquire("k", weight=2, blocking=True)
    t1 = time.perf_counter()

    assert ok is False
    assert (t1 - t0) < 0.05


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
    assert 0.08 <= (t1 - t0) <= 0.35


@pytest.mark.asyncio
async def test_try_acquire_async_rejects_invalid_negative_timeout():
    lim = make_limiter()

    with pytest.raises(ValueError, match="timeout must be -1 or >= 0"):
        await lim.try_acquire_async("k", blocking=True, timeout=-2)


@pytest.mark.asyncio
async def test_try_acquire_async_blocking_unacquirable_weight_returns_false():
    lim = make_limiter()

    t0 = time.perf_counter()
    ok = await lim.try_acquire_async("k", weight=2, blocking=True)
    t1 = time.perf_counter()

    assert ok is False
    assert (t1 - t0) < 0.05


# --- as_decorator: a weight that can never be admitted must deny the call,
# not run the wrapped function anyway (regression test for the silent-bypass
# bug where the boolean result of try_acquire()/try_acquire_async() was
# discarded) ---
def test_as_decorator_sync_unacquirable_weight_raises():
    lim = make_limiter()

    @lim.as_decorator(weight=2)
    def work():
        return "ran"

    with pytest.raises(RuntimeError, match="can never admit weight=2"):
        work()


@pytest.mark.asyncio
async def test_as_decorator_async_unacquirable_weight_raises():
    lim = make_limiter()

    @lim.as_decorator(weight=2)
    async def work():
        return "ran"

    with pytest.raises(RuntimeError, match="can never admit weight=2"):
        await work()


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
    assert 0.08 <= (t1 - t0) <= 0.35
