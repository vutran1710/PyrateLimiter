import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import gettempdir
from time import sleep
from time import time

import pytest

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries as Queries
from pyrate_limiter.utils import id_generator

TEMP_DIR = Path(gettempdir())
DEFAULT_DB_PATH = TEMP_DIR / "pyrate_limiter.sqlite"
TABLE_NAME = f"pyrate-test-bucket-{id_generator()}"
INDEX_NAME = TABLE_NAME + "__timestamp_index"


def count_all(conn: sqlite3.Connection) -> int:
    count = conn.execute(Queries.COUNT_ALL.format(table=TABLE_NAME)).fetchone()[0]
    return count


@pytest.fixture
def conn():
    db_conn = sqlite3.connect(
        DEFAULT_DB_PATH,
        isolation_level="EXCLUSIVE",
        check_same_thread=False,
    )
    drop_table_query = Queries.DROP_TABLE.format(table=TABLE_NAME)
    drop_index_query = Queries.DROP_INDEX.format(index=INDEX_NAME)
    create_table_query = Queries.CREATE_BUCKET_TABLE.format(table=TABLE_NAME)

    db_conn.execute(drop_table_query)
    db_conn.execute(drop_index_query)
    db_conn.execute(create_table_query)

    create_idx_query = Queries.CREATE_INDEX_ON_TIMESTAMP.format(
        index_name=INDEX_NAME,
        table_name=TABLE_NAME,
    )

    db_conn.execute(create_idx_query)

    db_conn.commit()

    yield db_conn


def test_bucket_init(conn):
    rates = [Rate(20, 1000)]
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)
    assert bucket is not None

    bucket.put(RateItem("my-item", 0))

    assert count_all(conn) == 1

    bucket.put(RateItem("my-item", 0, weight=10))
    assert count_all(conn) == 11

    count = conn.execute(
        Queries.COUNT_BEFORE_INSERT.format(
            table=TABLE_NAME,
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
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)

    assert count_all(conn) == 0

    for nth in range(20):
        bucket.put(RateItem(f"item={nth}", 0))
        sleep(0.04)

    assert count_all(conn) == 10
    items = conn.execute(Queries.GET_ALL_ITEM.format(table=TABLE_NAME)).fetchall()
    for idx, item in enumerate(items):
        if idx == 0:
            continue

        delta = item[1] - items[idx - 1][1]
        logging.info("-------> delta: %s", delta)

    def sleep_past_first_item():
        lag = conn.execute(Queries.GET_LAG.format(table=TABLE_NAME)).fetchone()[0]
        time_remain = 1 - lag / 1000 + 0.01
        print("remaining time util first item can be removed:", time_remain)

        if time_remain > 0:
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


def test_flush(conn):
    rates = [Rate(10, 1000)]
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)

    assert count_all(conn) == 0

    for n in range(30):
        bucket.put(RateItem(f"item={n}", 0))

    assert count_all(conn) == 10
    bucket.flush()
    assert count_all(conn) == 0


def test_stress_test(conn):
    rates = [Rate(10000, 1000), Rate(20000, 3000), Rate(30000, 4000), Rate(40000, 5000)]
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)

    assert count_all(conn) == 0

    before = time()

    def put_item(nth: int):
        bucket.put(RateItem(f"item={nth}", 0))

    with ThreadPoolExecutor() as executor:
        for _ in executor.map(put_item, list(range(30000))):
            pass

    after = time()
    print("Cost: ", after - before)
    print("Count: ", count_all(conn))
