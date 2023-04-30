import sqlite3
from time import sleep

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries as Queries

file_path = "/Users/vutran/pyrate-limiter.sqlite"
table_name = "pyrate-test-bucket"
index_name = table_name + "__timestamp_index"


def setup_db(conn: sqlite3.Connection):
    drop_table_query = Queries.DROP_TABLE.format(table=table_name)
    drop_index_query = Queries.DROP_INDEX.format(index=index_name)
    create_table_query = Queries.CREATE_BUCKET_TABLE.format(table=table_name)

    conn.execute(drop_table_query)
    conn.execute(drop_index_query)
    conn.execute(create_table_query)

    create_idx_query = Queries.CREATE_INDEX_ON_TIMESTAMP.format(
        index_name=index_name,
        table_name=table_name,
    )

    conn.execute(create_idx_query)

    conn.commit()


def test_bucket_init():
    conn = sqlite3.connect(file_path, isolation_level="EXCLUSIVE")
    setup_db(conn)

    rates = [Rate(20, 1000)]
    bucket = SQLiteBucket(conn, table_name, rates)
    assert bucket is not None

    bucket.put(RateItem("my-item", 0))

    count = conn.execute(Queries.COUNT_ALL.format(table=table_name)).fetchone()[0]
    assert count == 1

    bucket.put(RateItem("my-item", 0, weight=10))
    count = conn.execute(Queries.COUNT_ALL.format(table=table_name)).fetchone()[0]
    assert count == 11

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


def test_leaking():
    conn = sqlite3.connect(file_path, isolation_level="EXCLUSIVE")
    setup_db(conn)

    rates = [Rate(10, 1000)]
    bucket = SQLiteBucket(conn, table_name, rates)

    count = conn.execute(Queries.COUNT_ALL.format(table=table_name)).fetchone()[0]
    assert count == 0

    for n in range(20):
        bucket.put(RateItem(f"item={n}", 0))
        sleep(0.03)

    count = conn.execute(Queries.COUNT_ALL.format(table=table_name)).fetchone()[0]
    assert count == 10

    def get_first_item_timestamp() -> int:
        name, tick = conn.execute(Queries.GET_FIRST_ITEM.format(table=table_name)).fetchone()
        print("-------- earliest item:", name, tick)
        return tick

    def get_lag(tick: int) -> float:
        lag = conn.execute(
            "select (strftime('%s','now') || substr(strftime('%f','now'),4)) - {}".format(tick),
        ).fetchone()[0]
        return lag / 1000

    def count_items() -> int:
        count = conn.execute(Queries.COUNT_ALL.format(table=table_name)).fetchone()[0]
        return count

    sleep(1 - get_lag(get_first_item_timestamp()))
    bucket.leak()
    assert count_items() == 9

    sleep(1 - get_lag(get_first_item_timestamp()))
    bucket.leak()
    assert count_items() == 8

    sleep(1 - get_lag(get_first_item_timestamp()))
    bucket.leak()
    assert count_items() == 7

    sleep(1)
    bucket.leak()
    assert count_items() == 0

    conn.close()
