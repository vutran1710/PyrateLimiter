import sqlite3
from threading import RLock as Lock
from typing import List
from typing import Optional

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem


class Queries:
    CREATE_BUCKET_TABLE = """
    CREATE TABLE IF NOT EXISTS '{table}' (
        name VARCHAR,
        item_timestamp INTEGER DEFAULT (strftime('%s','now') || substr(strftime('%f','now'),4))
    )
    """
    CREATE_INDEX_ON_TIMESTAMP = """
    CREATE INDEX IF NOT EXISTS '{index_name}' ON '{table_name}' (item_timestamp)
    """
    COUNT_BEFORE_INSERT = """
    SELECT {interval} as interval, COUNT(*) FROM '{table}'
    WHERE item_timestamp >= (strftime('%s','now') || substr(strftime('%f','now'),4)) - {interval}
    """
    QUERY_COUNT_VIEW = """
    SELECT * FROM '{table}_view__rate_limit_counts'
    """
    PUT_ITEM = """
    INSERT INTO '{table}' (name) VALUES %s
    """
    LEAK = """
    DELETE FROM '{table}'
    WHERE item_timestamp < (strftime('%s','now') || substr(strftime('%f','now'),4)) - {interval}
    """
    FLUSH = """
    DELETE FROM '{table}'
    """
    # The below sqls are for testing only
    DROP_TABLE = "DROP TABLE IF EXISTS '{table}'"
    DROP_INDEX = "DROP INDEX IF EXISTS '{index}'"
    COUNT_ALL = "SELECT COUNT(*) FROM '{table}'"
    GET_ALL_ITEM = "SELECT * FROM '{table}' ORDER BY item_timestamp ASC"
    GET_FIRST_ITEM = "SELECT name, item_timestamp FROM '{table}' ORDER BY item_timestamp ASC"
    GET_LAG = """
    SELECT (strftime ('%s', 'now') || substr(strftime ('%f', 'now'), 4)) - (
    SELECT item_timestamp
    FROM '{table}'
    ORDER BY item_timestamp
    ASC
    LIMIT 1
    )
    """


class SQLiteBucket(AbstractBucket):
    """For sqlite bucket, we are using the sql time function as the clock
    item's timestamp wont matter here
    """

    rates: List[Rate]
    failing_rate: Optional[Rate]
    lock: Lock
    conn: sqlite3.Connection
    table: str
    full_count_query: str

    def __init__(self, rates: List[Rate], conn: sqlite3.Connection, table: str):
        self.conn = conn
        self.table = table
        self.rates = rates
        self.lock = Lock()
        self.full_count_query = self._build_full_count_query()
        self._create_limit_count_view()

    def _build_full_count_query(self) -> str:
        full_query: List[str] = []

        for rate in self.rates:
            query = Queries.COUNT_BEFORE_INSERT.format(
                table=self.table,
                interval=rate.interval,
            )

            full_query.append(query)

        join_full_query = " union ".join(full_query) if len(full_query) > 1 else full_query[0]
        return join_full_query

    def _create_limit_count_view(self):
        assert self.full_count_query
        self.conn.execute(
            f"""
        CREATE VIEW IF NOT EXISTS '{self.table}_view__rate_limit_counts'
        AS
        {self.full_count_query}
        """
        )

    def put(self, item: RateItem) -> bool:
        with self.lock:
            rate_limit_counts = self.conn.execute(Queries.QUERY_COUNT_VIEW.format(table=self.table)).fetchall()

            for idx, result in enumerate(rate_limit_counts):
                interval, count = result
                rate = self.rates[idx]
                assert interval == rate.interval
                space_available = rate.limit - count

                if space_available < item.weight:
                    return False

            items = ", ".join([f"('{name}')" for name in [item.name] * item.weight])
            query = Queries.PUT_ITEM.format(table=self.table) % items
            self.conn.execute(query)
            self.conn.commit()
            return True

    def leak(self, _: Optional[int] = None) -> int:
        """Leaking/clean up bucket"""
        with self.lock:
            query = Queries.LEAK.format(
                table=self.table,
                interval=self.rates[-1].interval,
            )
            self.conn.execute(query)
            self.conn.commit()
            return 0

    def flush(self) -> None:
        with self.lock:
            self.conn.execute(Queries.FLUSH.format(table=self.table))
            self.conn.commit()
