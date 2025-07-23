import time

import pytest

from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import MultiprocessBucket
from pyrate_limiter import Rate
from pyrate_limiter.exceptions import LimiterDelayException


@pytest.mark.asyncio
async def test_async_timeout():
    limiter = Limiter([Rate(1, Duration.SECOND)], max_delay=500, raise_when_fail=False)

    # First acquires immediately
    ok = await limiter.try_acquire_async("a")
    assert ok

    # Second should timeout (more than 1 per sec)
    start = time.perf_counter()
    ok = await limiter.try_acquire_async("a")
    elapsed = (time.perf_counter() - start) * 1000
    assert not ok
    assert elapsed < 600


def test_rlock_timeout():
    limiter = Limiter([Rate(1, Duration.SECOND)], max_delay=100, raise_when_fail=False)

    ok = limiter.try_acquire("lock_test")

    start = time.perf_counter()
    ok = limiter.try_acquire("lock_test")
    elapsed = (time.perf_counter() - start) * 1000
    print(f"RLock test: acquired={ok}, elapsed={elapsed:.2f}ms")
    assert not ok
    assert elapsed < 200


def test_mp_back_to_back():
    rate = Rate(1, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])
    limiter = Limiter(bucket, raise_when_fail=False, max_delay=100)

    # Back to back acquires should fail the rate limit
    limiter.try_acquire("x")
    start = time.perf_counter()
    ok = limiter.try_acquire("x")
    elapsed = (time.perf_counter() - start) * 1000
    assert not ok
    assert elapsed < 200


def test_mp_raisewhenfail():
    # Back to back acquires should fail the rate limit
    rate = Rate(1, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])

    limiter = Limiter(bucket, raise_when_fail=True, max_delay=100)
    limiter.try_acquire("x")

    with pytest.raises(LimiterDelayException):
        limiter.try_acquire("x")


@pytest.mark.asyncio
async def test_async_raisewhenfail():
    limiter = Limiter([Rate(1, Duration.SECOND)], max_delay=100, raise_when_fail=True)
    await limiter.try_acquire_async("a")
    with pytest.raises(LimiterDelayException):
        await limiter.try_acquire_async("a")
