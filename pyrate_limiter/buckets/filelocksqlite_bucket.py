"""Bucket implementation using SQLite"""

import sqlite3
from pathlib import Path
from tempfile import gettempdir
from threading import RLock
from typing import List
from typing import Optional
from typing import Tuple

from filelock import FileLock  # https://pypi.org/project/filelock/

from ..abstracts import Rate
from ..abstracts import RateItem
from .sqlite_bucket import Queries, SQLiteBucket


class FileLockSQLiteBucket(SQLiteBucket):
    def __init__(
        self, rates: List[Rate], conn: sqlite3.Connection, table: str, mp_lock: FileLock
    ):
        self.conn = conn
        self.table = table
        self.rates = rates
        self.lock = RLock()
        self.mp_lock = mp_lock

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
        with self.mp_lock:
            return super().put(item)

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        """Leaking/clean up bucket"""
        with self.mp_lock:
            return super().leak(current_timestamp)

    def flush(self) -> None:
        with self.mp_lock:
            return super().flush()

    def count(self) -> int:
        with self.mp_lock:
            return super().count()

    def peek(self, index: int) -> Optional[RateItem]:
        with self.mp_lock:
            return super().peek(index)

    @classmethod
    def init_from_file(
        cls,
        rates: List[Rate],
        table: str = "rate_bucket",
        db_path: Optional[str] = None,
        create_new_table: bool = True,
    ) -> "SQLiteBucket":
        # TODO: This could be more cleanly refactored with sqlite_bucket

        if db_path is None:
            temp_dir = Path(gettempdir())
            db_path = str(temp_dir / "pyrate_limiter.sqlite")

        assert db_path is not None
        assert db_path.endswith(".sqlite"), "Please provide a valid sqlite file path"

        mp_lock = FileLock(f"{db_path}.lock")

        with mp_lock:
            sqlite_connection = sqlite3.connect(
                db_path,
                isolation_level="EXCLUSIVE",
                check_same_thread=False,
            )
            sqlite_connection.execute("PRAGMA journal_mode=WAL;")

            if create_new_table:
                sqlite_connection.execute(
                    Queries.CREATE_BUCKET_TABLE.format(table=table)
                )

            create_idx_query = Queries.CREATE_INDEX_ON_TIMESTAMP.format(
                index_name="idx_rate_item_timestamp",
                table_name=table,
            )

            sqlite_connection.execute(create_idx_query)
            sqlite_connection.commit()

            return cls(rates, sqlite_connection, table=table, mp_lock=mp_lock)
