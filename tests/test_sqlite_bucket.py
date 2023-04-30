import sqlite3
from time import sleep

import pytest

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries as Queries

file_path = "/Users/vutran/pyrate-limiter.sqlite"
table_name = "pyrate-test-bucket"
index_name = table_name + "__timestamp_index"


def count_all(conn: sqlite3.Connection) -> int:
    count = conn.execute(Queries.COUNT_ALL.format(table=table_name)).fetchone()[0]
    return count


@pytest.fixture
def conn():
    db_conn = sqlite3.connect(file_path, isolation_level="EXCLUSIVE")
    drop_table_query = Queries.DROP_TABLE.format(table=table_name)
    drop_index_query = Queries.DROP_INDEX.format(index=index_name)
    create_table_query = Queries.CREATE_BUCKET_TABLE.format(table=table_name)

    db_conn.execute(drop_table_query)
    db_conn.execute(drop_index_query)
    db_conn.execute(create_table_query)

    create_idx_query = Queries.CREATE_INDEX_ON_TIMESTAMP.format(
        index_name=index_name,
        table_name=table_name,
    )

    db_conn.execute(create_idx_query)

    db_conn.commit()

    yield db_conn


def test_bucket_init(conn):
    rates = [Rate(20, 1000)]
    bucket = SQLiteBucket(conn, table_name, rates)
    assert bucket is not None

    bucket.put(RateItem("my-item", 0))

    assert count_all(conn) == 1

    bucket.put(RateItem("my-item", 0, weight=10))
    assert count_all(conn) == 11

    count = conn.execute(
        Queries.COUNT_BEFORE_INSERT.format(
            table=table_name,
            interval=1000,
        )
    ).fetchone()[0]
    assert count == 11

    # Insert 10 more item, it should fail
    sleep(1)
    for ntn in range(21):
        is_ok = bucket.put(RateItem("my-item", 0))
        sleep(0.03)

        if ntn == 20:
            assert is_ok is False

    sleep(1)
    # Insert an item with excessive weight should fail
    assert bucket.put(RateItem("some-heavy-item", 0, weight=22)) is False

    conn.close()


def test_leaking(conn):
    rates = [Rate(10, 1000)]
    bucket = SQLiteBucket(conn, table_name, rates)

    assert count_all(conn) == 0

    for n in range(20):
        bucket.put(RateItem(f"item={n}", 0))
        sleep(0.04)

    assert count_all(conn) == 10

    def sleep_past_first_item():
        lag = conn.execute(Queries.GET_LAG.format(table=table_name)).fetchone()[0]
        time_remain = 1 - lag / 1000
        print("remaining time util first item can be removed:", time_remain)
        sleep(time_remain)

    sleep_past_first_item()
    bucket.leak()
    assert count_all(conn) == 9

    sleep_past_first_item()
    bucket.leak()
    assert count_all(conn) == 8

    sleep_past_first_item()
    bucket.leak()
    assert count_all(conn) == 7

    sleep(1)
    bucket.leak()
    assert count_all(conn) == 0

    conn.close()
