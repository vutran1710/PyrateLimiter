"""Pytest config
"""
from logging import basicConfig
from logging import getLogger
from os import getenv
from typing import Union

import pytest

from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import SQLiteClock
from pyrate_limiter.clocks import TimeAsyncClock
from pyrate_limiter.clocks import TimeClock

# Make log messages visible on test failure (or with pytest -s)
basicConfig(level="INFO")
# Uncomment for more verbose output:
getLogger("pyrate_limiter").setLevel(getenv("LOG_LEVEL", "INFO"))


clocks = [MonotonicClock(), TimeClock(), SQLiteClock(), TimeAsyncClock()]

ClockSet = Union[
    MonotonicClock,
    TimeClock,
    SQLiteClock,
    TimeAsyncClock,
]


@pytest.fixture(params=clocks)
def clock(request):
    """Parametrization for different time functions."""
    return request.param
