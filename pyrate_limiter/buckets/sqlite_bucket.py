import sqlite3

from ..abstracts import AbstractBucket
from ..abstracts import RateItem
from ..abstracts import SyncClock


class Queries:
    CREATE_BUCKET_TABLE = """
    CREATE TABLE IF NOT EXISTS '{table}' (name VARCHAR, timestamp INTEGER)
    """
    CREATE_INDEX_ON_TIMESTAMP = """
    CREATE INDEX IF NOT EXISTS '{index_name}' ON '{table_name}' (timestamp)
    """
    PUT_ITEMS = """
    INSERT INTO %s (name, "timestamp")
    VALUES(%s, datetime('now'))
    """
    REMOVE_ITEMS = """
    -- remove items here
    """


class SQLiteBucket(AbstractBucket):
    conn: sqlite3.Connection

    def __init__(self, conn: sqlite3.Connection, table: str):
        self.conn = conn
        self.table = str

    def put(self, item: RateItem) -> bool:
        """Put an item (typically the current time) in the bucket"""
        pass

    def leak(self, clock: SyncClock) -> int:
        """Schedule a leak and run in a task"""
        pass
