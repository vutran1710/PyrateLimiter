"""Clock implementation using different backend"""

from __future__ import annotations

from abc import ABC, abstractmethod
from time import monotonic
from typing import TYPE_CHECKING, Awaitable, Union

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool


class AbstractClock(ABC):
    """Clock that return timestamp for `now`"""

    @abstractmethod
    def now(self) -> Union[int, Awaitable[int]]:
        """Get time as of now, in miliseconds"""

    from psycopg_pool import ConnectionPool


class MonotonicClock(AbstractClock):
    def __init__(self):
        monotonic()

    def now(self):
        return int(1000 * monotonic())


class MonotonicAsyncClock(AbstractClock):
    """Monotonic Async Clock, meant for testing only"""

    async def now(self) -> int:
        return int(1000 * monotonic())


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
