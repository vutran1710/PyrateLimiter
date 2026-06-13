"""Characterization / regression tests for the Limiter acquire path
(_delay_waiter / handle_bucket_put / _try_acquire) and AbstractBucket.waiting().

These pin the (sync|async) x blocking x timeout x weight matrix of the
highest-churn code in the library, using a deterministic InMemoryBucket.
buffer_ms=0 is used deliberately so the leaky-bucket boundary math is tested
honestly (the default buffer_ms=50 otherwise masks an off-by-one). Timing
tolerances are generous to avoid flakiness.
"""
import time
from inspect import isawaitable

import pytest

from pyrate_limiter import BucketAsyncWrapper, InMemoryBucket, Limiter, Rate, RateItem


def _limiter(rates=None, buffer_ms=0):
    return Limiter(InMemoryBucket(rates or [Rate(1, 100)]), buffer_ms=buffer_ms)


# ------------------------------------------- _plan_delay_step (shared helper)

def test_plan_delay_step_outcomes():
    """The deadline math shared by both _delay_waiter branches."""
    from time import monotonic

    from pyrate_limiter.limiter import _plan_delay_step

    # No deadline -> sleep the full delay, never time out.
    assert _plan_delay_step(None, 200) == (0.2, False)

    # Deadline far in the future (remaining > delay) -> sleep the delay.
    secs, timed_out = _plan_delay_step(monotonic() + 10, 200)
    assert abs(secs - 0.2) < 0.02 and timed_out is False

    # Deadline near (remaining < delay) -> sleep the remainder, then time out.
    secs, timed_out = _plan_delay_step(monotonic() + 0.05, 200)
    assert 0 < secs <= 0.07 and timed_out is True

    # Deadline already passed -> raise immediately (no sleep).
    with pytest.raises(TimeoutError):
        _plan_delay_step(monotonic() - 1, 200)


# ------------------------------------------------- waiting() boundary (Bug X)

def test_waiting_clears_inclusive_lower_bound():
    """waiting() must return the delay to push an item PAST the inclusive
    window lower bound. After sleeping exactly `waiting()`, a re-put must
    succeed; otherwise _delay_waiter loops at delay=0 (busy-spin)."""
    b = InMemoryBucket([Rate(1, 100)])
    assert b.put(RateItem("a", 1000, weight=1)) is True
    assert b.put(RateItem("b", 1000, weight=1)) is False  # full -> sets failing_rate

    delay = b.waiting(RateItem("b", 1000))
    assert isinstance(delay, int) and delay > 0
    # Re-put after exactly `delay` must succeed (the freed item is out of window).
    assert b.put(RateItem("b", 1000 + delay, weight=1)) is True


# ---------------------------------------------------------------- weight == 0

def test_weight_zero_sync_always_true_even_when_full():
    lim = _limiter()
    assert lim.try_acquire("k", weight=0) is True
    assert lim.try_acquire("k") is True  # consume the only slot
    assert lim.try_acquire("k", weight=0) is True
    assert lim.try_acquire("k", weight=0, blocking=False) is True


@pytest.mark.asyncio
async def test_weight_zero_async_always_true_even_when_full():
    lim = _limiter()
    assert await lim.try_acquire_async("k", weight=0) is True
    assert await lim.try_acquire_async("k") is True
    assert await lim.try_acquire_async("k", weight=0) is True
    assert await lim.try_acquire_async("k", weight=0, blocking=False) is True


# ----------------------------------------------- input validation (async)

@pytest.mark.asyncio
async def test_async_nonblocking_with_timeout_raises():
    lim = _limiter()
    with pytest.raises(RuntimeError, match="Can't set timeout with non-blocking"):
        await lim.try_acquire_async("k", blocking=False, timeout=0.1)


# --------------------------------------------------------------- timeout == 0

def test_timeout_zero_sync_succeeds_if_available_else_immediate_false():
    lim = _limiter()
    assert lim.try_acquire("k", blocking=True, timeout=0) is True
    t0 = time.perf_counter()
    ok = lim.try_acquire("k", blocking=True, timeout=0)
    dt = time.perf_counter() - t0
    assert ok is False
    assert dt < 0.05


@pytest.mark.asyncio
async def test_timeout_zero_async_succeeds_if_available_else_immediate_false():
    """Bug Y: try_acquire_async(timeout=0) must succeed when capacity is free
    (it previously always returned False via asyncio.wait_for(timeout=0))."""
    lim = _limiter([Rate(5, 100)])
    assert await lim.try_acquire_async("k", blocking=True, timeout=0) is True
    # Fill to the limit, then a timeout=0 acquire must fail immediately.
    for _ in range(4):
        assert await lim.try_acquire_async("k", blocking=True, timeout=0) is True
    t0 = time.perf_counter()
    ok = await lim.try_acquire_async("k", blocking=True, timeout=0)
    dt = time.perf_counter() - t0
    assert ok is False
    assert dt < 0.05


# ------------------------- blocking (no timeout) waits then OK, without spin

def test_sync_blocking_succeeds_after_wait_without_spin():
    lim = _limiter([Rate(1, 100)])
    assert lim.try_acquire("k") is True
    t0 = time.perf_counter()
    assert lim.try_acquire("k") is True  # waits ~interval, then succeeds
    dt = time.perf_counter() - t0
    assert dt >= 0.05          # actually waited
    assert dt < 1.0            # did NOT busy-spin to the background leaker (~10s)


@pytest.mark.asyncio
async def test_async_blocking_succeeds_after_wait_without_spin():
    lim = _limiter([Rate(1, 100)])
    assert await lim.try_acquire_async("k") is True
    t0 = time.perf_counter()
    assert await lim.try_acquire_async("k") is True
    dt = time.perf_counter() - t0
    assert dt >= 0.05
    assert dt < 1.0


# ------------------------------------ blocking + generous timeout: succeeds

def test_sync_blocking_timeout_long_enough_succeeds():
    lim = _limiter([Rate(1, 100)])
    assert lim.try_acquire("k") is True
    t0 = time.perf_counter()
    ok = lim.try_acquire("k", blocking=True, timeout=1)  # 1s >> ~100ms wait
    dt = time.perf_counter() - t0
    assert ok is True
    assert dt < 1.0  # succeeded well before the deadline


@pytest.mark.asyncio
async def test_async_blocking_timeout_long_enough_succeeds():
    lim = _limiter([Rate(1, 100)])
    assert await lim.try_acquire_async("k") is True
    t0 = time.perf_counter()
    ok = await lim.try_acquire_async("k", blocking=True, timeout=1)
    dt = time.perf_counter() - t0
    assert ok is True
    assert dt < 1.0


# --------------------------- async _delay_waiter branch under internal deadline

@pytest.mark.asyncio
async def test_async_delay_branch_times_out_mid_wait():
    """An async bucket acquired via *sync* try_acquire(timeout=...) runs the
    async _delay_waiter branch under the internal deadline (no asyncio.wait_for
    wrapper). When the required wait exceeds the timeout, it sleeps up to the
    deadline and resolves to False."""
    lim = Limiter(BucketAsyncWrapper(InMemoryBucket([Rate(1, 500)])), buffer_ms=0)
    assert await lim.try_acquire("k") is True  # consume the only slot

    t0 = time.perf_counter()
    res = lim.try_acquire("k", blocking=True, timeout=0.1)  # ~500ms wait > 0.1s timeout
    assert isawaitable(res)
    ok = await res
    dt = time.perf_counter() - t0
    assert ok is False
    assert 0.05 <= dt <= 0.45


@pytest.mark.asyncio
async def test_async_delay_branch_succeeds_after_wait():
    """Same async branch, but the timeout is generous: it sleeps then re-acquires."""
    lim = Limiter(BucketAsyncWrapper(InMemoryBucket([Rate(1, 100)])), buffer_ms=0)
    assert await lim.try_acquire("k") is True
    res = lim.try_acquire("k", blocking=True, timeout=2)
    assert isawaitable(res)
    assert await res is True
