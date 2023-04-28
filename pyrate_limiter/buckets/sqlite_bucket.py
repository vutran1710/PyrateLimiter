import sqlite3
from typing import List

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem
from ..abstracts import SyncClock


class Queries:
    CREATE_BUCKET_TABLE = """
    CREATE TABLE IF NOT EXISTS '{table}' (
        name VARCHAR,
        timestamp INTEGER DEFAULT (strftime('%s','now') || substr(strftime('%f','now'),4))
    )
    """
    CREATE_INDEX_ON_TIMESTAMP = """
    CREATE INDEX IF NOT EXISTS '{index_name}' ON '{table_name}' (timestamp)
    """
    PUT_ITEMS = """
    INSERT INTO '{table}' (name) VALUES %s
    """
    REMOVE_ITEMS = """
    -- remove items here
    """


class SQLiteBucket(AbstractBucket):
    """For sqlite bucket, we are using the sql time function as the clock
    item's timestamp wont matter here
    """

    rates: List[Rate]
    conn: sqlite3.Connection
    table: str

    def __init__(self, conn: sqlite3.Connection, table: str):
        self.conn = conn
        self.table = table

    def put(self, item: RateItem) -> bool:
        """Put an item (typically the current time) in the bucket"""
        self.conn.isolation_level = "EXCLUSIVE"
        self.conn.execute("BEGIN EXCLUSIVE")
        items = ", ".join(["('%s')" % name for name in [item.name] * item.weight])
        self.conn.execute(Queries.PUT_ITEMS.format(table=self.table) % items)
        self.conn.commit()
        return True

    def leak(self, clock: SyncClock) -> int:
        """Schedule a leak and run in a task"""
        pass
