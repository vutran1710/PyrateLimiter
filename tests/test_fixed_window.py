"""FixedWindow: wall-clock-aligned windows that reset, rather than rolling."""
import importlib.util
from typing import List

import pytest

from pyrate_limiter import Duration, FixedWindow, InMemoryBucket, Limiter, Rate, RateItem, SlidingWindowLog, id_generator

# ------------------------------------------------------------------ the math

def test_window_start_aligns_to_the_interval():
    algo = FixedWindow()
    rate = Rate(3, 1000)
    assert algo.window_start(rate, 0) == 0
    assert algo.window_start(rate, 999) == 0
    assert algo.window_start(rate, 1000) == 1000
    assert algo.window_start(rate, 1999) == 1000


def test_sliding_window_start_rolls():
    algo = SlidingWindowLog()
    rate = Rate(3, 1000)
    assert algo.window_start(rate, 1500) == 500
    assert algo.window_start(rate, 1501) == 501


def test_retry_after_is_the_next_boundary():
    algo = FixedWindow()
    rate = Rate(3, 1000)
    assert algo.retry_after(rate, now=1500, blocking_timestamp=None) == 500
    assert algo.retry_after(rate, now=1999, blocking_timestamp=None) == 1
    # Never 0: now is always strictly inside its own window, so the limiter
    # cannot busy-spin at delay 0.
    assert algo.retry_after(rate, now=1000, blocking_timestamp=None) == 1000


def test_fixed_window_asks_for_no_blocking_entry():
    # The whole window clears at once, so no stored entry is consulted and
    # backends skip the lookup entirely.
    assert FixedWindow().blocking_offset(Rate(3, 1000), weight=1) is None
    assert SlidingWindowLog().blocking_offset(Rate(3, 1000), weight=1) == 2


def test_leak_bound_is_the_earliest_window_start():
    rates = [Rate(3, 1000), Rate(5, 5000)]
    # Generic default over window_start reproduces the old widest-window rule.
    assert SlidingWindowLog().leak_bound(rates, now=10_000) == 10_000 - 5000
    assert FixedWindow().leak_bound(rates, now=10_500) == 10_000


# --------------------------------------------------------------- behaviour

def test_window_resets_at_the_boundary():
    bucket = InMemoryBucket([Rate(3, 1000)], algorithm=FixedWindow())

    for ts in (1000, 1400, 1900):
        assert bucket.put(RateItem("a", ts)) is True

    denied = RateItem("a", 1950)
    assert bucket.put(denied) is False
    assert bucket.waiting(denied) == 50  # to the 2000 boundary

    assert bucket.put(RateItem("a", 2000)) is True


def test_fixed_window_allows_a_double_burst_across_a_boundary():
    """The defining trade-off: 2 * limit can pass in one interval's span."""
    bucket = InMemoryBucket([Rate(3, 1000)], algorithm=FixedWindow())

    # 3 at the end of one window...
    for ts in (1900, 1950, 1999):
        assert bucket.put(RateItem("a", ts)) is True

    # ...and 3 more immediately after it rolls over.
    for ts in (2000, 2001, 2002):
        assert bucket.put(RateItem("a", ts)) is True

    assert bucket.put(RateItem("a", 2003)) is False


def test_sliding_window_refuses_that_same_burst():
    bucket = InMemoryBucket([Rate(3, 1000)], algorithm=SlidingWindowLog())

    for ts in (1900, 1950, 1999):
        assert bucket.put(RateItem("a", ts)) is True

    # Still 3 within the rolling second, so no rollover reprieve.
    assert bucket.put(RateItem("a", 2000)) is False


def test_default_algorithm_is_unchanged():
    assert isinstance(InMemoryBucket([Rate(3, 1000)])._algorithm, SlidingWindowLog)


def test_weight_over_limit_never_fits():
    rates = [Rate(3, 1000)]
    bucket = InMemoryBucket(rates, algorithm=FixedWindow())

    item = RateItem("a", 1000, weight=5)
    assert bucket.put(item) is False
    assert bucket.failing_rate is rates[0]
    assert bucket.waiting(item) == -1


def test_multi_rate_reports_the_first_failing_window():
    rates = [Rate(2, 1000), Rate(3, 10_000)]
    bucket = InMemoryBucket(rates, algorithm=FixedWindow())

    assert bucket.put(RateItem("a", 1000)) is True
    assert bucket.put(RateItem("a", 1100)) is True

    tight = RateItem("a", 1200)
    assert bucket.put(tight) is False
    assert bucket.failing_rate is rates[0]
    assert bucket.waiting(tight) == 800  # 2000 boundary

    # Next second admits one more, then the 10s window is the binding one.
    assert bucket.put(RateItem("a", 2000)) is True
    wide = RateItem("a", 2100)
    assert bucket.put(wide) is False
    assert bucket.failing_rate is rates[1]
    assert bucket.waiting(wide) == 7900  # 10000 boundary


def test_limiter_blocks_until_the_window_resets():
    limiter = Limiter(InMemoryBucket([Rate(2, Duration.SECOND)], algorithm=FixedWindow()), buffer_ms=10)

    assert limiter.try_acquire("k", blocking=False) is True
    assert limiter.try_acquire("k", blocking=False) is True
    assert limiter.try_acquire("k", blocking=False) is False
    # Blocking waits out the window rather than failing.
    assert limiter.try_acquire("k", blocking=True, timeout=3) is True


# ------------------------------------------------------- across the backends

def _in_memory(rates: List[Rate]):
    return InMemoryBucket(rates, algorithm=FixedWindow())


def _sqlite(rates: List[Rate]):
    from pyrate_limiter import SQLiteBucket

    return SQLiteBucket.init_from_file(rates, table=f"fw_{id_generator()}", algorithm=FixedWindow())


def _mp(rates: List[Rate]):
    from pyrate_limiter import MultiprocessBucket

    return MultiprocessBucket.init(rates, algorithm=FixedWindow())


def _redis(rates: List[Rate]):
    from redis import Redis

    from pyrate_limiter import RedisBucket

    client = Redis.from_url("redis://localhost:6379")
    key = f"fw-test/{id_generator()}"
    client.delete(key)
    return RedisBucket.init(rates, client, key, algorithm=FixedWindow())


def _postgres(rates: List[Rate]):
    from psycopg_pool import ConnectionPool

    from pyrate_limiter import PostgresBucket

    pool = ConnectionPool("postgresql://postgres:postgres@localhost:5432", open=True)
    return PostgresBucket(pool, f"fw_{id_generator()}", rates, algorithm=FixedWindow())


# Markers, not just import guards: CI installs every driver everywhere but only
# runs the servers on Linux, so the non-Linux jobs deselect by marker.
backends = [
    pytest.param(_in_memory, id="inmemory", marks=pytest.mark.inmemory),
    pytest.param(_sqlite, id="sqlite", marks=pytest.mark.sqlite),
    pytest.param(_mp, id="mpbucket", marks=pytest.mark.mpbucket),
]

if importlib.util.find_spec("redis") is not None:
    backends.append(pytest.param(_redis, id="redis", marks=pytest.mark.redis))

if importlib.util.find_spec("psycopg_pool") is not None:
    backends.append(pytest.param(_postgres, id="postgres", marks=pytest.mark.postgres))


@pytest.mark.parametrize("make_bucket", backends)
def test_backends_clear_a_denial_on_a_weightless_put(make_bucket):
    """Every backend's weight==0 short-circuit must still record the verdict."""
    rates = [Rate(1, 1000)]
    bucket = make_bucket(rates)

    assert bucket.put(RateItem("a", 1000)) is True
    assert bucket.put(RateItem("a", 1000)) is False
    assert bucket.failing_rate == rates[0]

    assert bucket.put(RateItem("a", 1000, weight=0)) is True
    assert bucket.failing_rate is None
    bucket.close()


@pytest.mark.parametrize("make_bucket", backends)
def test_backends_agree_on_fixed_window(make_bucket):
    """Every backend must count over the aligned window and wait to its edge."""
    rates = [Rate(3, 1000)]
    bucket = make_bucket(rates)

    for ts in (1000, 1400, 1900):
        assert bucket.put(RateItem("a", ts)) is True

    denied = RateItem("a", 1950)
    assert bucket.put(denied) is False
    assert bucket.failing_rate == rates[0]
    assert bucket.waiting(denied) == 50

    # The boundary clears the window even though the entries are still stored.
    assert bucket.put(RateItem("a", 2000)) is True

    bucket.close()
