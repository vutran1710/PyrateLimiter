import sqlite3
from threading import RLock as Lock
from typing import List
from typing import Optional

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem
from ..abstracts import SyncClock


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
    SELECT COUNT(*) FROM '{table}'
    WHERE item_timestamp >= (strftime('%s','now') || substr(strftime('%f','now'),4)) - {interval}
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


class SQLiteBucket(AbstractBucket):
    """For sqlite bucket, we are using the sql time function as the clock
    item's timestamp wont matter here
    """

    rates: List[Rate]
    failing_rate: Optional[Rate]
    lock: Lock
    conn: sqlite3.Connection
    table: str

    def __init__(self, conn: sqlite3.Connection, table: str, rates: List[Rate]):
        self.conn = conn
        self.table = table
        self.rates = rates
        self.lock = Lock()

    def put(self, item: RateItem) -> bool:
        with self.lock:
            # Check before insert
            # NOTE: this part can be rewritten using pure SQL, but its kinda complex,
            # so I leave it as room for improvement
            for rate in self.rates:
                count = self.conn.execute(
                    Queries.COUNT_BEFORE_INSERT.format(
                        table=self.table,
                        interval=rate.interval,
                    )
                ).fetchone()[0]

                space_available = rate.limit - count

                if space_available < item.weight:
                    self.failing_rate = rate
                    return False

            items = ", ".join(["('%s')" % name for name in [item.name] * item.weight])
            query = Queries.PUT_ITEM.format(table=self.table) % items
            self.conn.execute(query)
            self.conn.commit()
            return True

    def leak(self, clock: Optional[SyncClock] = None) -> int:
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
