"""Bucket implementation using SQLite"""


import logging
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from tempfile import gettempdir
from threading import RLock
from time import time, time_ns
from typing import List, Optional, Union

try:
    # Running inside package source tree
    from ..abstracts import AbstractBucket, Rate, RateItem
    from ..clocks import AbstractClock
    from ..utils import dedicated_sqlite_clock_connection
except ImportError:
    # Running as standalone module with installed package
    from pyrate_limiter import AbstractBucket, Rate, RateItem  # type: ignore
    from pyrate_limiter.clocks import AbstractClock  # type: ignore
    from pyrate_limiter.utils import dedicated_sqlite_clock_connection  # type: ignore

logger = logging.getLogger(__name__)


def _quote_identifier(identifier: str) -> str:
    """Quote SQLite identifier safely."""
    if not identifier:
        raise ValueError("identifier must not be empty")
    if "\x00" in identifier:
        raise ValueError("identifier contains null byte")
    return '"' + identifier.replace('"', '""') + '"'


class Queries:
    CREATE_BUCKET_TABLE = """
    CREATE TABLE IF NOT EXISTS {table} (
        name TEXT,
        item_timestamp INTEGER
    )
    """
    CREATE_INDEX_ON_TIMESTAMP = """
    CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} (item_timestamp)
    """
    COUNT_BEFORE_INSERT = """
    SELECT COUNT(*) FROM {table}
    WHERE item_timestamp >= ? - ?
    """
    PUT_ITEM = """
    INSERT INTO {table} (name, item_timestamp) VALUES (?, ?)
    """
    LEAK = """
    DELETE FROM {table} WHERE rowid IN (
        SELECT rowid FROM {table}
        ORDER BY item_timestamp ASC
        LIMIT ?
    )
    """.strip()
    COUNT_BEFORE_LEAK = """
    SELECT COUNT(*) FROM {table}
    WHERE item_timestamp < ? - ?
    """
    FLUSH = "DELETE FROM {table}"
    COUNT_ALL = "SELECT COUNT(*) FROM {table}"
    PEEK = """
    SELECT name, item_timestamp
    FROM {table}
    ORDER BY item_timestamp DESC
    LIMIT 1 OFFSET ?
    """


class SQLiteBucket(AbstractBucket):
    """SQLite-backed bucket with injection-safe SQL handling."""

    rates: List[Rate]
    failing_rate: Optional[Rate]
    conn: Optional[sqlite3.Connection]
    table: str
    lock: RLock
    use_limiter_lock: bool

    def __init__(self, rates: List[Rate], conn: sqlite3.Connection, table: str, lock=None):
        self.conn = conn
        self.table = table
        self.rates = rates
        self._quoted_table = _quote_identifier(table)

        if not lock:
            self.use_limiter_lock = False
            self.lock = RLock()
        else:
            self.use_limiter_lock = True
            self.lock = lock

    def now(self):
        # Keep existing behavior for compatibility
        return time_ns() // 1000000

    def limiter_lock(self):
        if self.use_limiter_lock:
            return self.lock
        return None

    def _require_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("SQLiteBucket is already closed")
        return self.conn

    def put(self, item: RateItem) -> bool:
        with self.lock:
            conn = self._require_conn()
            count_query = Queries.COUNT_BEFORE_INSERT.format(table=self._quoted_table)

            for rate in self.rates:
                cur = conn.execute(count_query, (item.timestamp, rate.interval))
                count = int(cur.fetchone()[0])
                cur.close()

                space_available = rate.limit - count
                if space_available < item.weight:
                    self.failing_rate = rate
                    return False

            self.failing_rate = None
            insert_query = Queries.PUT_ITEM.format(table=self._quoted_table)
            conn.executemany(insert_query, ((item.name, item.timestamp) for _ in range(item.weight)))
            conn.commit()
            return True

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        with self.lock:
            assert current_timestamp is not None
            conn = self._require_conn()

            count_query = Queries.COUNT_BEFORE_LEAK.format(table=self._quoted_table)
            cur = conn.execute(count_query, (current_timestamp, self.rates[-1].interval))
            count = int(cur.fetchone()[0])
            cur.close()

            if count <= 0:
                return 0

            leak_query = Queries.LEAK.format(table=self._quoted_table)
            conn.execute(leak_query, (count,)).close()
            conn.commit()
            return count

    def flush(self) -> None:
        with self.lock:
            conn = self._require_conn()
            conn.execute(Queries.FLUSH.format(table=self._quoted_table)).close()
            conn.commit()
            self.failing_rate = None

    def count(self) -> int:
        with self.lock:
            conn = self._require_conn()
            cur = conn.execute(Queries.COUNT_ALL.format(table=self._quoted_table))
            ret = int(cur.fetchone()[0])
            cur.close()
            return ret

    def peek(self, index: int) -> Optional[RateItem]:
        with self.lock:
            conn = self._require_conn()
            query = Queries.PEEK.format(table=self._quoted_table)
            cur = conn.execute(query, (index,))
            item = cur.fetchone()
            cur.close()

            if not item:
                return None
            return RateItem(item[0], item[1])

    def close(self):
        with self.lock:
            if self.conn is not None:
                try:
                    self.conn.close()
                    self.conn = None
                except Exception as exc:  # pragma: no cover
                    logger.debug("Exception %s closing sql connection", exc)

    @classmethod
    def init_from_file(
        cls,
        rates: List[Rate],
        table: str = "rate_bucket",
        db_path: Optional[str] = None,
        create_new_table: bool = True,
        use_file_lock: bool = False,
    ) -> "SQLiteBucket":
        if db_path is None and use_file_lock:
            raise ValueError("db_path must be specified when using use_file_lock")

        if db_path is None:
            temp_dir = Path(gettempdir())
            db_path = str(temp_dir / f"pyrate_limiter_{time()}.sqlite")

        file_lock = None
        file_lock_ctx = nullcontext()

        if use_file_lock:
            try:
                from filelock import FileLock  # type: ignore[import-untyped]

                file_lock = FileLock(db_path + ".lock")  # type: ignore[no-redef]
                file_lock_ctx = file_lock  # type: ignore[assignment]
            except ImportError as exc:
                raise ImportError("filelock is required for file locking. Please install it as optional dependency") from exc

        quoted_table = _quote_identifier(table)
        quoted_index = _quote_identifier(f"idx_{table}_rate_item_timestamp")

        with file_lock_ctx:
            assert db_path is not None
            sqlite_connection = sqlite3.connect(
                db_path,
                isolation_level="DEFERRED",
                check_same_thread=False,
            )

            cur = sqlite_connection.cursor()
            if use_file_lock:
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")

            if create_new_table:
                cur.execute(Queries.CREATE_BUCKET_TABLE.format(table=quoted_table))

            cur.execute(Queries.CREATE_INDEX_ON_TIMESTAMP.format(index_name=quoted_index, table_name=quoted_table))
            cur.close()
            sqlite_connection.commit()

            return cls(rates, sqlite_connection, table=table, lock=file_lock)


class SQLiteClock(AbstractClock):
    """Get timestamp using SQLite as remote clock backend."""

    time_query = "SELECT CAST(ROUND((julianday('now') - 2440587.5)*86400000) As INTEGER)"

    def __init__(self, conn: Union[sqlite3.Connection, SQLiteBucket]):
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
            assert self.conn is not None
            cur = self.conn.execute(self.time_query)
            now = cur.fetchone()[0]
            cur.close()
            return int(now)
