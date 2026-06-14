"""A bucket using PostgreSQL as backend"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Awaitable, List, Optional, Union

from ..abstracts import AbstractBucket, Rate, RateItem
from ..clocks import PostgresClock

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool  # type: ignore[import-untyped]


class Queries:
    """SQL templates composed via ``psycopg.sql``.

    ``{table}`` / ``{index}`` are quoted identifiers filled with
    ``sql.SQL(...).format(...)``; ``%s`` are bound query parameters supplied at
    execution time. Neither uses raw string interpolation (issue #233).
    """

    CREATE_BUCKET_TABLE = """
    CREATE TABLE IF NOT EXISTS {table} (
        name VARCHAR,
        weight SMALLINT,
        item_timestamp TIMESTAMP
    )
    """
    CREATE_INDEX_ON_TIMESTAMP = """
    CREATE INDEX IF NOT EXISTS {index} ON {table} (item_timestamp)
    """
    LOCK_TABLE = """
    LOCK TABLE {table} IN EXCLUSIVE MODE NOWAIT
    """
    COUNT = """
    SELECT COUNT(*) FROM {table}
    """
    COUNT_WINDOW = """
    SELECT COUNT(*) FROM {table}
    WHERE item_timestamp >= TO_TIMESTAMP(%s) - (%s * INTERVAL '1 milliseconds')
    """
    PUT = """
    INSERT INTO {table} (name, weight, item_timestamp)
    SELECT %s, %s, TO_TIMESTAMP(%s) FROM generate_series(1, %s)
    """
    FLUSH = """
    DELETE FROM {table}
    """
    PEEK = """
    SELECT name, weight, (extract(epoch FROM item_timestamp) * 1000) as item_timestamp
    FROM {table}
    ORDER BY item_timestamp DESC
    LIMIT 1
    OFFSET %s
    """
    LEAK = """
    DELETE FROM {table} WHERE item_timestamp < TO_TIMESTAMP(%s)
    """
    LEAK_COUNT = """
    SELECT COUNT(*) FROM {table} WHERE item_timestamp < TO_TIMESTAMP(%s)
    """


class PostgresBucket(AbstractBucket):
    is_async = False
    table: str
    pool: ConnectionPool

    def __init__(self, pool: ConnectionPool, table: str, rates: List[Rate]):
        from psycopg import sql

        self._clock = PostgresClock(pool)
        self.table = table.lower()
        self.pool = pool
        assert rates
        self.rates = rates
        self._full_tbl = f"ratelimit___{self.table}"

        # Compose all SQL with properly-quoted identifiers and bound
        # parameters instead of f-string interpolation (issue #233). The table
        # identifier is fixed per bucket, so the statements are composed once
        # here; only values vary and are passed as query parameters.
        tbl = sql.Identifier(self._full_tbl)
        index_name = sql.Identifier(f"timestampindex_{self.table}")
        self._q_create_table = sql.SQL(Queries.CREATE_BUCKET_TABLE).format(table=tbl)
        self._q_create_index = sql.SQL(Queries.CREATE_INDEX_ON_TIMESTAMP).format(index=index_name, table=tbl)
        self._q_lock = sql.SQL(Queries.LOCK_TABLE).format(table=tbl)
        self._q_count = sql.SQL(Queries.COUNT).format(table=tbl)
        # One scan computing every rate's windowed count via COUNT(*) FILTER,
        # instead of one round trip per rate. Each rate contributes a
        # (TO_TIMESTAMP(%s), %s) pair, filled in self.rates order at put time.
        # Composed with psycopg.sql (no string interpolation).
        _filter = sql.SQL("COUNT(*) FILTER (WHERE item_timestamp >= TO_TIMESTAMP(%s) - (%s * INTERVAL '1 milliseconds'))")
        _fields = sql.SQL(", ").join([_filter] * len(self.rates))
        self._q_count_windows = sql.SQL("SELECT {fields} FROM {table}").format(fields=_fields, table=tbl)
        self._q_put = sql.SQL(Queries.PUT).format(table=tbl)
        self._q_flush = sql.SQL(Queries.FLUSH).format(table=tbl)
        self._q_peek = sql.SQL(Queries.PEEK).format(table=tbl)
        self._q_leak = sql.SQL(Queries.LEAK).format(table=tbl)
        self._q_leak_count = sql.SQL(Queries.LEAK_COUNT).format(table=tbl)

        self._create_table()

    @contextmanager
    def _get_conn(self):
        with self.pool.connection() as conn:
            yield conn

    def _create_table(self):
        with self._get_conn() as conn:
            lock_id = hash(self._full_tbl) & 0x7FFFFFFF
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
            conn.execute(self._q_create_table)
            conn.execute(self._q_create_index)

    def put(self, item: RateItem) -> Union[bool, Awaitable[bool]]:
        """Put an item (typically the current time) in the bucket
        return true if successful, otherwise false
        """
        from psycopg.errors import LockNotAvailable

        if item.weight == 0:
            return True

        item_ts_seconds = item.timestamp / 1000

        with self._get_conn() as conn:
            # Acquire an EXCLUSIVE MODE lock on the bucket table using NOWAIT.
            # This ensures the "check current count" + "insert new items" sequence
            # is atomic with respect to other writers, so rate limits cannot be
            # exceeded due to concurrent requests interleaving.
            #
            # Because we use NOWAIT, if the table is already locked by another
            # transaction, PostgreSQL raises LockNotAvailable and we immediately
            # reject this request (return False) instead of blocking or retrying.
            # This provides predictable, fail-fast behavior but may limit
            # throughput under high contention since only one writer can perform
            # the check-and-put at a time.
            try:
                conn.execute(self._q_lock)
            except LockNotAvailable:
                logger.debug("LockNotAvailable")
                self.failing_rate = self.rates[0]
                return False

            params = [v for rate in self.rates for v in (item_ts_seconds, rate.interval)]
            cur = conn.execute(self._q_count_windows, params)
            counts = cur.fetchone()
            cur.close()

            decision = self._algorithm.admit(self.rates, counts, item.weight)
            if not decision.allowed:
                self.failing_rate = decision.failing_rate
                return False

            self.failing_rate = None
            # Insert all `weight` unit-rows in a single statement (one round
            # trip) instead of `weight` separate INSERTs under the table lock.
            conn.execute(self._q_put, (item.name, item.weight, item_ts_seconds, item.weight))

        return True

    def leak(
        self,
        current_timestamp: Optional[int] = None,
    ) -> Union[int, Awaitable[int]]:
        """leaking bucket - removing items that are outdated"""
        assert current_timestamp is not None, "current-time must be passed on for leak"
        lower_bound = self._algorithm.leak_bound(self.rates, current_timestamp)

        if lower_bound <= 0:
            return 0

        count = 0
        lower_bound_seconds = lower_bound / 1000

        with self._get_conn() as conn:
            cur = conn.execute(self._q_leak_count, (lower_bound_seconds,))
            result = cur.fetchone()

            if result:
                conn.execute(self._q_leak, (lower_bound_seconds,))
                count = int(result[0])

        return count

    def flush(self) -> Union[None, Awaitable[None]]:
        """Flush the whole bucket
        - Must remove `failing-rate` after flushing
        """
        with self._get_conn() as conn:
            conn.execute(self._q_flush)
            self.failing_rate = None

        return None

    def count(self) -> Union[int, Awaitable[int]]:
        """Count number of items in the bucket"""
        count = 0
        with self._get_conn() as conn:
            cur = conn.execute(self._q_count)
            result = cur.fetchone()
            assert result
            count = int(result[0])

        return count

    def peek(self, index: int) -> Union[Optional[RateItem], Awaitable[Optional[RateItem]]]:
        """Peek at the rate-item at a specific index in latest-to-earliest order
        NOTE: The reason we cannot peek from the start of the queue(earliest-to-latest) is
        we can't really tell how many outdated items are still in the queue
        """
        item = None

        with self._get_conn() as conn:
            cur = conn.execute(self._q_peek, (index,))
            result = cur.fetchone()
            if result:
                name, weight, timestamp = result[0], int(result[1]), int(result[2])
                item = RateItem(name=name, weight=weight, timestamp=timestamp)

        return item

    def close(self):
        if self.pool is not None and not self.pool.closed:
            try:
                self.pool.close()
            except Exception as e:
                logger.debug("Exception closing pool, %s", e)
