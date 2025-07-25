"""Bucket implementation using SQLite"""
import logging
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from tempfile import gettempdir
from threading import RLock
from time import time
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem

logger = logging.getLogger(__name__)


class Queries:
    CREATE_BUCKET_TABLE = """
    CREATE TABLE IF NOT EXISTS '{table}' (
        name VARCHAR,
        item_timestamp INTEGER
    )
    """
    CREATE_INDEX_ON_TIMESTAMP = """
    CREATE INDEX IF NOT EXISTS '{index_name}' ON '{table_name}' (item_timestamp)
    """
    COUNT_BEFORE_INSERT = """
    SELECT :interval{index} as interval, COUNT(*) FROM '{table}'
    WHERE item_timestamp >= :current_timestamp - :interval{index}
    """
    PUT_ITEM = """
    INSERT INTO '{table}' (name, item_timestamp) VALUES %s
    """
    LEAK = """
    DELETE FROM "{table}" WHERE rowid IN (
    SELECT rowid FROM "{table}" ORDER BY item_timestamp ASC LIMIT {count});
    """.strip()
    COUNT_BEFORE_LEAK = """SELECT COUNT(*) FROM '{table}' WHERE item_timestamp < {current_timestamp} - {interval}"""
    FLUSH = """DELETE FROM '{table}'"""
    # The below sqls are for testing only
    DROP_TABLE = "DROP TABLE IF EXISTS '{table}'"
    DROP_INDEX = "DROP INDEX IF EXISTS '{index}'"
    COUNT_ALL = "SELECT COUNT(*) FROM '{table}'"
    GET_ALL_ITEM = "SELECT * FROM '{table}' ORDER BY item_timestamp ASC"
    GET_FIRST_ITEM = (
        "SELECT name, item_timestamp FROM '{table}' ORDER BY item_timestamp ASC"
    )
    GET_LAG = """
    SELECT (strftime ('%s', 'now') || substr(strftime ('%f', 'now'), 4)) - (
    SELECT item_timestamp
    FROM '{table}'
    ORDER BY item_timestamp
    ASC
    LIMIT 1
    )
    """
    PEEK = 'SELECT * FROM "{table}" ORDER BY item_timestamp DESC LIMIT 1 OFFSET {count}'


class SQLiteBucket(AbstractBucket):
    """For sqlite bucket, we are using the sql time function as the clock
    item's timestamp wont matter here
    """

    rates: List[Rate]
    failing_rate: Optional[Rate]
    conn: sqlite3.Connection
    table: str
    full_count_query: str
    lock: RLock
    use_limiter_lock: bool

    def __init__(
        self, rates: List[Rate], conn: sqlite3.Connection, table: str, lock=None
    ):
        self.conn = conn
        self.table = table
        self.rates = rates

        if not lock:
            self.use_limiter_lock = False
            self.lock = RLock()
        else:
            self.use_limiter_lock = True
            self.lock = lock

    def limiter_lock(self):
        if self.use_limiter_lock:
            return self.lock
        else:
            return None

    def _build_full_count_query(self, current_timestamp: int) -> Tuple[str, dict]:
        full_query: List[str] = []

        parameters = {"current_timestamp": current_timestamp}

        for index, rate in enumerate(self.rates):
            parameters[f"interval{index}"] = rate.interval
            query = Queries.COUNT_BEFORE_INSERT.format(table=self.table, index=index)
            full_query.append(query)

        join_full_query = (
            " union ".join(full_query) if len(full_query) > 1 else full_query[0]
        )
        return join_full_query, parameters

    def put(self, item: RateItem) -> bool:
        with self.lock:
            query, parameters = self._build_full_count_query(item.timestamp)
            cur = self.conn.execute(query, parameters)
            rate_limit_counts = cur.fetchall()
            cur.close()

            for idx, result in enumerate(rate_limit_counts):
                interval, count = result
                rate = self.rates[idx]
                assert interval == rate.interval
                space_available = rate.limit - count

                if space_available < item.weight:
                    self.failing_rate = rate
                    return False

            items = ", ".join(
                [f"('{name}', {item.timestamp})" for name in [item.name] * item.weight]
            )
            query = (Queries.PUT_ITEM.format(table=self.table)) % items
            self.conn.execute(query).close()
            self.conn.commit()
            return True

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        """Leaking/clean up bucket"""
        with self.lock:
            assert current_timestamp is not None
            query = Queries.COUNT_BEFORE_LEAK.format(
                table=self.table,
                interval=self.rates[-1].interval,
                current_timestamp=current_timestamp,
            )
            cur = self.conn.execute(query)
            count = cur.fetchone()[0]
            query = Queries.LEAK.format(table=self.table, count=count)
            cur.execute(query)
            cur.close()
            self.conn.commit()
            return count

    def flush(self) -> None:
        with self.lock:
            self.conn.execute(Queries.FLUSH.format(table=self.table)).close()
            self.conn.commit()
            self.failing_rate = None

    def count(self) -> int:
        with self.lock:
            cur = self.conn.execute(
                Queries.COUNT_ALL.format(table=self.table)
            )
            ret = cur.fetchone()[0]
            cur.close()
            return ret

    def peek(self, index: int) -> Optional[RateItem]:
        with self.lock:
            query = Queries.PEEK.format(table=self.table, count=index)
            cur = self.conn.execute(query)
            item = cur.fetchone()
            cur.close()

            if not item:
                return None

            return RateItem(item[0], item[1])

    @classmethod
    def init_from_file(
        cls,
        rates: List[Rate],
        table: str = "rate_bucket",
        db_path: Optional[str] = None,
        create_new_table: bool = True,
        use_file_lock: bool = False
    ) -> "SQLiteBucket":

        if db_path is None and use_file_lock:
            raise ValueError("db_path must be specified when using use_file_lock")

        if db_path is None:
            temp_dir = Path(gettempdir())
            db_path = str(temp_dir / f"pyrate_limiter_{time()}.sqlite")

        # TBD: FileLock switched to a thread-local FileLock in 3.11.0.
        # Should we set FileLock's thread_local to False, for cases where user is both multiprocessing & threading?
        # As is, the file lock should be Multi Process - Single Thread and non-filelock is Single Process - Multi Thread
        # A hybrid lock may be needed to gracefully handle both cases
        file_lock = None
        file_lock_ctx = nullcontext()

        if use_file_lock:
            try:
                from filelock import FileLock  # type: ignore[import-untyped]
                file_lock = FileLock(db_path + ".lock")  # type: ignore[no-redef]
                file_lock_ctx: Union[nullcontext, FileLock] = file_lock  # type: ignore[no-redef]
            except ImportError:
                raise ImportError(
                    "filelock is required for file locking. "
                    "Please install it as optional dependency"
                )

        with file_lock_ctx:
            assert db_path is not None
            assert db_path.endswith(".sqlite"), (
                "Please provide a valid sqlite file path"
            )

            sqlite_connection = sqlite3.connect(
                db_path,
                isolation_level="DEFERRED",
                check_same_thread=False,
            )

            cur = sqlite_connection.cursor()
            if use_file_lock:
                # https://www.sqlite.org/wal.html
                cur.execute("PRAGMA journal_mode=WAL;")

                # https://www.sqlite.org/pragma.html#pragma_synchronous
                cur.execute("PRAGMA synchronous=NORMAL;")

            if create_new_table:
                cur.execute(
                    Queries.CREATE_BUCKET_TABLE.format(table=table)
                )

            create_idx_query = Queries.CREATE_INDEX_ON_TIMESTAMP.format(
                index_name=f"idx_{table}_rate_item_timestamp",
                table_name=table,
            )

            cur.execute(create_idx_query)
            cur.close()
            sqlite_connection.commit()

            return cls(rates, sqlite_connection, table=table, lock=file_lock)
