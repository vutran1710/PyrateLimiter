"""Clock implementation using different backend"""
from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from time import monotonic
from time import time
from typing import Optional
from typing import TYPE_CHECKING
from typing import Union

from .abstracts import AbstractClock
from .buckets import SQLiteBucket
from .utils import dedicated_sqlite_clock_connection

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool
    from threading import RLock


class MonotonicClock(AbstractClock):
    def __init__(self):
        monotonic()

    def now(self):
        return int(1000 * monotonic())


class TimeClock(AbstractClock):
    def now(self):
        return int(1000 * time())


class TimeAsyncClock(AbstractClock):
    """Time Async Clock, meant for testing only"""

    async def now(self) -> int:
        return int(1000 * time())


class SQLiteClock(AbstractClock):
    """Get timestamp using SQLite as remote clock backend"""

    time_query = (
        "SELECT CAST(ROUND((julianday('now') - 2440587.5)*86400000) As INTEGER)"
    )

    def __init__(self, conn: Union[sqlite3.Connection, SQLiteBucket]):
        """
        In multiprocessing cases, use the bucket, so that a shared lock is used.
        """

        self.lock: Optional[RLock] = None

        if isinstance(conn, SQLiteBucket):
            self.conn = conn.conn
            self.lock = conn.lock
        else:
            self.conn = conn

    @classmethod
    def default(cls):
        conn = dedicated_sqlite_clock_connection()
        return cls(conn)

    def now(self) -> int:
        with self.lock if self.lock else nullcontext():
            cur = self.conn.execute(self.time_query)
            now = cur.fetchone()[0]
            cur.close()
            return int(now)


class PostgresClock(AbstractClock):
    """Get timestamp using Postgres as remote clock backend"""

    def __init__(self, pool: "ConnectionPool"):
        self.pool = pool

    def now(self) -> int:
        value = 0

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT EXTRACT(epoch FROM current_timestamp) * 1000")
                result = cur.fetchone()
                assert result, "unable to get current-timestamp from postgres"
                value = int(result[0])

        return value
