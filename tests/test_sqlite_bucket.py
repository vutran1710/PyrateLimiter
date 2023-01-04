from sqlite3 import ProgrammingError
from tempfile import gettempdir
from time import time

import pytest

from pyrate_limiter import SQLiteBucket


def get_test_bucket(maxsize: int = 1000):
    return SQLiteBucket(identity="id", path=":memory:", maxsize=maxsize)


def test_init():
    # The system temp directory should be used unless a path is provided
    assert str(SQLiteBucket(identity="id")._path).startswith(gettempdir())
    assert str(SQLiteBucket(identity="id", path="bucket.db")._path) == "bucket.db"

    # The table name should be hashed
    assert SQLiteBucket(identity="id").table == "ratelimit_87ea5dfc8b8e384d848979496e706390b497e547"

    # An identity is required since it's used as the table name
    with pytest.raises(ValueError):
        SQLiteBucket()


def test_close():
    bucket = get_test_bucket()
    connection = bucket.connection
    bucket.close()
    with pytest.raises(ProgrammingError):
        connection.execute("SELECT * FROM default_bucket")

    # Closing an unopened connection should have no effect
    bucket = get_test_bucket()
    bucket.close()
    assert bucket._connection is None


def test_put_get_size():
    """Test put, get, and size methods"""
    bucket = get_test_bucket()
    for i in range(1000):
        bucket.put(i)
    assert bucket.size() == 1000

    # Items should be retrieved in FIFO order, optionally with multiple items at a time
    for _ in range(10):
        assert bucket.get() == 1
    assert bucket.get(10) == 10

    next_key = bucket._get_keys()[0]
    assert next_key == 21
    assert bucket.size() == 980


def test_chunked_get():
    bucket = get_test_bucket(maxsize=3000)
    for i in range(2000):
        bucket.put(i)

    n_items = bucket.get(2000)
    assert n_items == 2000
    assert bucket.size() == 0


def test_maxsize():
    """Test that no more items can be added when the bucket is full"""
    bucket = get_test_bucket()
    for i in range(1000):
        assert bucket.put(i) == 1
    assert bucket.put(1) == 0
    assert bucket.size() == 1000


def test_all_items():
    bucket = get_test_bucket()
    for i in range(10):
        bucket.put(i + 0.1)
    assert bucket.all_items() == [0.1, 1.1, 2.1, 3.1, 4.1, 5.1, 6.1, 7.1, 8.1, 9.1]


def test_inspect_expired_items():
    bucket = get_test_bucket()
    current_time = time()

    # Add 30 items at 1-second intervals
    for i in range(30):
        seconds_ago = 29 - i
        bucket.put(current_time - seconds_ago)

    # Expect 10 expired items within a time window starting 10 seconds ago
    item_count, remaining_time = bucket.inspect_expired_items(current_time - 10)
    assert item_count == 10
    # Expect 1 second until the next item expires
    assert remaining_time == 1.0


def test_flushing_bucket():
    bucket = get_test_bucket()
    bucket.flush()
    assert bucket.size() == 0
