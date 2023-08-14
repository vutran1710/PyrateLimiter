"""Clock implementation using different backend
"""
import sqlite3
from pathlib import Path
from tempfile import gettempdir
from time import monotonic
from time import time

from .abstracts import Clock


class MonotonicClock(Clock):
    def __init__(self):
        monotonic()

    def now(self):
        return int(1000 * monotonic())


class TimeClock(Clock):
    def now(self):
        return int(1000 * time())


class TimeAsyncClock(Clock):
    """Time Async Clock, meant for testing only"""

    async def now(self) -> int:
        return int(1000 * time())


class SQLiteClock(Clock):
    """Get timestamp using SQLite as remote clock backend"""

    conn: sqlite3.Connection
    time_query = "SELECT CAST(ROUND((julianday('now') - 2440587.5)*86400000) As INTEGER)"

    def __init__(self, conn: sqlite3.Connection = None):
        if conn is None:
            temp_dir = Path(gettempdir())
            default_db_path = temp_dir / "pyrate_limiter_clock_only.sqlite"

            conn = sqlite3.connect(
                default_db_path,
                isolation_level="EXCLUSIVE",
                check_same_thread=False,
            )

        self.conn = conn

    def now(self) -> int:
        now = self.conn.execute(self.time_query).fetchone()[0]
        return int(now)
