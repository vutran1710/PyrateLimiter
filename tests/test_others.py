import logging
from inspect import isawaitable
from time import time

import pytest

from pyrate_limiter import binary_search
from pyrate_limiter import Duration
from pyrate_limiter import Rate
from pyrate_limiter import RateItem
from pyrate_limiter import SQLiteClock
from pyrate_limiter import validate_rate_list


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


def test_binary_search():
    """Testing binary-search that find item in array"""
    # Normal list of items
    items = [RateItem("item", nth * 2) for nth in range(5)]

    print([item.timestamp for item in items])

    assert binary_search(items, 0) == 0
    assert binary_search(items, 1) == 1
    assert binary_search(items, 2) == 1
    assert binary_search(items, 3) == 2
    assert binary_search(items, 9) == -1
    assert binary_search(items, 8) == 4

    # If the value is larger than the last item, idx would be -1
    assert binary_search(items, 11) == -1

    # Empty list
    items = []

    assert binary_search(items, 1) == 0
    assert binary_search(items, 2) == 0
    assert binary_search(items, 3) == 0


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


@pytest.mark.asyncio
async def test_clock(clock):
    """Testing clock backends
    """
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
