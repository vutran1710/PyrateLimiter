import logging
import re
from inspect import isawaitable
from time import time

import pytest

from pyrate_limiter import Duration
from pyrate_limiter import Rate
from pyrate_limiter import SQLiteClock
from pyrate_limiter import MonotonicClock
from pyrate_limiter import AbstractClock

from pyrate_limiter import validate_rate_list


def test_version():
    from pyrate_limiter import _version
    assert re.match(r'^\d+\.\d+\.\d+(\..*)?', _version.__version__), f"""{_version.__version__=}
    doesn't match a version pattern (x.y.z)"""


def test_duration():
    assert int(Duration.SECOND) == 1000
    assert Duration.SECOND.value == 1000

    assert Duration.SECOND * 60 == 60 * Duration.SECOND == Duration.MINUTE.value == int(Duration.MINUTE)
    assert Duration.MINUTE * 60 == 60 * Duration.MINUTE == Duration.HOUR.value == int(Duration.HOUR)
    assert Duration.HOUR * 24 == 24 * Duration.HOUR == Duration.DAY.value == int(Duration.DAY)
    assert Duration.DAY * 7 == 7 * Duration.DAY == Duration.WEEK.value == int(Duration.WEEK)
    assert Duration.DAY + Duration.DAY == Duration.DAY * 2
    assert Duration.MINUTE + 30000 == 30000 + Duration.MINUTE == 90000


def test_readable_duration():
    assert Duration.readable(300) == "300ms"

    assert Duration.readable(1000) == "1.0s"
    assert Duration.readable(1300) == "1.3s"

    assert Duration.readable(Duration.SECOND * 3.5) == "3.5s"
    assert Duration.readable(Duration.SECOND * 60 * 24 + Duration.SECOND * 30) == "24.5m"

    assert Duration.readable(Duration.MINUTE * 3.5) == "3.5m"
    assert Duration.readable(Duration.MINUTE * 60 + Duration.MINUTE * 30) == "1.5h"

    assert Duration.readable(Duration.HOUR * 3.5) == "3.5h"
    assert Duration.readable(Duration.DAY * 3.5) == "3.5d"
    assert Duration.readable(Duration.WEEK * 3.5) == "3.5w"


def test_rate():
    rate = Rate(1000, Duration.SECOND)
    assert str(rate) == "limit=1000/1.0s"
    assert repr(rate) == "limit=1000/1000"

    rate = Rate(1000, Duration.SECOND * 3)
    assert str(rate) == "limit=1000/3.0s"
    assert repr(rate) == "limit=1000/3000"

    rate = Rate(1000, 3500)
    assert str(rate) == "limit=1000/3.5s"

    rate = Rate(1000, Duration.MINUTE * 3.5)
    assert str(rate) == "limit=1000/3.5m"

    rate = Rate(1000, Duration.MINUTE * 3)
    assert str(rate) == "limit=1000/3.0m"


def test_rate_validator():
    rates = []
    assert validate_rate_list(rates) is False

    rates = [Rate(1, 1)]
    assert validate_rate_list(rates) is True

    rates = [Rate(2, 1), Rate(1, 1)]
    assert validate_rate_list(rates) is False

    rates = [Rate(1, 1), Rate(2, 1)]
    assert validate_rate_list(rates) is False

    rates = [Rate(1, 1), Rate(2, 2)]
    assert validate_rate_list(rates) is True

    rates = [Rate(2, 1), Rate(1, 2)]
    assert validate_rate_list(rates) is False

    rates = [Rate(2, 1), Rate(3, 2)]
    assert validate_rate_list(rates) is True

    rates = [Rate(1, 1), Rate(3, 2), Rate(4, 1)]
    assert validate_rate_list(rates) is False

    rates = [Rate(2, 1), Rate(3, 2), Rate(4, 3)]
    assert validate_rate_list(rates) is True


def test_inmemory_bucket_rejects_illformed_rates():
    """Ill-formed rate lists must raise at construction instead of silently
    misbehaving (issue #239). InMemoryBucket sorts by interval, so the rates
    are validated in interval-ascending order."""
    from pyrate_limiter import InMemoryBucket

    # 3/min AND 1/day: the longer interval has a *smaller* limit -> ill-formed
    bad_rates = [Rate(3, Duration.MINUTE), Rate(1, Duration.DAY)]
    assert validate_rate_list(sorted(bad_rates, key=lambda r: r.interval)) is False

    with pytest.raises(ValueError):
        InMemoryBucket(bad_rates)

    # Well-formed config (generous-before-tight) must still be accepted, and
    # unordered-but-well-formed input is accepted because the bucket sorts it.
    InMemoryBucket([Rate(100, Duration.SECOND), Rate(200, Duration.MINUTE)])
    InMemoryBucket([Rate(200, Duration.MINUTE), Rate(100, Duration.SECOND)])
    InMemoryBucket([Rate(10, Duration.SECOND)])


@pytest.mark.asyncio
async def test_clock(clock: AbstractClock | None = None):
    """Testing clock backends
    """
    if clock is None:
        clock = MonotonicClock()
    now = clock.now()

    while isawaitable(now):
        now = await now

    logging.info("Testing clock: %s -> %d", clock, now)
    assert now > 0

    if now > 1000:
        # NOTE: if not MonotonicClock, the time values should be almost equal
        use_time = time() * 1000
        assert int(now) - round(use_time) < 2


@pytest.mark.asyncio
async def test_sqlite_clock():
    """Testing clock backends
    """
    await test_clock(SQLiteClock.default())

    from .conftest import create_sqlite_bucket

    bucket = await create_sqlite_bucket([Rate(1, Duration.SECOND)])
    await test_clock(SQLiteClock(bucket.conn))

    await test_clock(SQLiteClock(bucket))
