import sqlite3
from hashlib import sha1
from os.path import join
from tempfile import gettempdir
from typing import List

from pyrate_limiter.bucket import AbstractBucket


class SQLiteBucket(AbstractBucket):
    """Bucket backed by a SQLite database

    Args:
        maxsize: Maximum number of items in the bucket
        identity: Bucket identity, used as the table name
        path: Path to the SQLite database file; defaults to a temp file in the system temp directory
        kwargs: Additional keyword arguments for :py:func:`sqlite3.connect`
    """

    def __init__(self, maxsize=0, identity: str = None, path: str = None, **kwargs):
        super().__init__(maxsize=maxsize)
        self._connection = None
        self.connection_kwargs = kwargs
        self.path = path or join(gettempdir(), "pyrate_limiter.sqlite")

        if not identity:
            raise ValueError("Bucket identity is required")

        # Hash identity to use as a table name, to avoid potential issues with user-provided values
        self.table = f"ratelimit_{sha1(identity.encode()).hexdigest()}"

    @property
    def connection(self) -> sqlite3.Connection:
        """Create a database connection and initialize the table, if it hasn't already been done.
        This is safe to leave open, but may be manually closed with :py:meth:`.close`, if needed.
        """
        if not self._connection:
            self.connection_kwargs.setdefault("isolation_level", None)  # Use autocommit by default
            self._connection = sqlite3.connect(self.path, **self.connection_kwargs)
            self._connection.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} ("
                "idx INTEGER PRIMARY KEY AUTOINCREMENT, "
                "value REAL)"
            )
        return self._connection

    def close(self):
        """Close the database connection"""
        if self._connection:
            self._connection.close()

    def size(self) -> int:
        return self.connection.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0]

    def put(self, item: float) -> int:
        """Put an item in the bucket.
        Return 1 if successful, else 0
        """
        if self.size() < self.maxsize():
            self.connection.execute(f"INSERT INTO {self.table} (value) VALUES (?)", (item,))
            return 1
        return 0

    def get(self, number: int = 1) -> int:
        """Get items and remove them from the bucket in the FIFO fashion.
        Return the number of items that have been removed.
        """
        keys = [str(key) for key in self._get_keys(number)]

        placeholders = ",".join("?" * len(keys))
        self.connection.execute(f"DELETE FROM {self.table} WHERE idx IN ({placeholders})", keys)

        return len(keys)

    def _get_keys(self, number: int = 1) -> List[float]:
        rows = self.connection.execute(
            f"SELECT idx FROM {self.table} ORDER BY idx LIMIT ?", (number,)
        ).fetchall()
        return [row[0] for row in rows]

    def all_items(self) -> List[float]:
        """Return a list as copies of all items in the bucket"""
        rows = self.connection.execute(f"SELECT value FROM {self.table} ORDER BY idx").fetchall()
        return [row[0] for row in rows]
