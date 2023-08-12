import sqlite3
from logging import basicConfig
from logging import getLogger
from os import getenv
from pathlib import Path
from tempfile import gettempdir

import pytest

from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import SQLiteClock
from pyrate_limiter.clocks import TimeClock

# Make log messages visible on test failure (or with pytest -s)
basicConfig(level="INFO")
# Uncomment for more verbose output:
getLogger("pyrate_limiter").setLevel(getenv("LOG_LEVEL", "INFO"))


temp_dir = Path(gettempdir())
default_db_path = temp_dir / "pyrate_limiter_clock_only.sqlite"

conn = sqlite3.connect(
    default_db_path,
    isolation_level="EXCLUSIVE",
    check_same_thread=False,
)

clocks = [MonotonicClock(), TimeClock(), SQLiteClock(conn)]


@pytest.fixture(params=clocks)
def clock(request):
    """Parametrization for different time functions."""
    return request.param
